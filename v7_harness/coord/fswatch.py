"""U329: push transport. A directory change event wakes the receiver; no model, no polling loop of paid calls.

Priority 1 of 윤겸스 (spec 9.4-2): a letter's arrival must wake the receiving session and be ACKed by a deterministic
watcher within ACK_DEADLINE_S (10 s), without waiting for the next prompt hook. `watchdog` is not installed in this
runtime, so this is stdlib only:

* Windows: `FindFirstChangeNotificationW` + `WaitForSingleObject` (the kernel's ReadDirectoryChangesW family). The thread
  sleeps inside the kernel and wakes on the file event, so arrival -> wake is milliseconds and costs no CPU.
* Elsewhere (no stdlib inotify): the fallback re-lists the directory every FALLBACK_TICK_S (0.2 s). It is a local
  directory listing, free, and 50x under the 10 s deadline; it is the documented fallback, not the Windows path.

`InboxWatcher.run` ACKs every new letter by writing `<ack_dir>/<letter>.ack.json` atomically (PUBLISHED != ACK: this is
the ACK) and calls `on_letter` (the session wake). Letters are JSON with a `sent_at` epoch; the receipt records the
arrival->ACK latency so a test or the ledger can report p95.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from pathlib import Path
from typing import Callable

from .nowait import atomic_write_text

FALLBACK_TICK_S = 0.2
WAIT_SLICE_S = 0.5  # how long one kernel wait blocks, so a stop request is honoured quickly


class _Notifier:
    """Blocks until the directory changes or the timeout; True when the kernel (or the fallback tick) saw a change."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.handle = None
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.FindFirstChangeNotificationW.restype = wintypes.HANDLE
            k32.FindFirstChangeNotificationW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL, wintypes.DWORD]
            k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            k32.WaitForSingleObject.restype = wintypes.DWORD  # unsigned: WAIT_FAILED is 0xFFFFFFFF, not -1
            k32.FindNextChangeNotification.restype = wintypes.BOOL
            k32.FindCloseChangeNotification.restype = wintypes.BOOL
            k32.FindNextChangeNotification.argtypes = [wintypes.HANDLE]
            k32.FindCloseChangeNotification.argtypes = [wintypes.HANDLE]
            # FILE_NOTIFY_CHANGE_FILE_NAME (1) | LAST_WRITE (0x10) | SIZE (8)
            handle = k32.FindFirstChangeNotificationW(str(self.path), False, 0x1 | 0x8 | 0x10)
            if handle not in (None, wintypes.HANDLE(-1).value):
                self.k32, self.handle = k32, handle

    def wait(self, timeout_s: float) -> bool:
        if self.handle is None:
            time.sleep(min(timeout_s, FALLBACK_TICK_S))
            return True  # the caller re-lists the directory
        status = self.k32.WaitForSingleObject(self.handle, int(timeout_s * 1000))
        if status == 0:
            if not self.k32.FindNextChangeNotification(self.handle):
                self.close()  # the kernel handle is unusable: fall back to the directory re-list, never busy-spin
            return True
        if status != 0x102:  # not WAIT_TIMEOUT: WAIT_FAILED / WAIT_ABANDONED -> same fallback
            self.close()
            time.sleep(min(timeout_s, FALLBACK_TICK_S))
            return True
        return False

    def close(self) -> None:
        if self.handle is not None:
            self.k32.FindCloseChangeNotification(self.handle)
            self.handle = None


class InboxWatcher:
    def __init__(self, inbox: Path, ack_dir: Path, *, on_letter: Callable[[Path, dict], None] | None = None,
                 clock: Callable[[], float] = time.time):
        self.inbox, self.ack_dir, self.on_letter, self.clock = Path(inbox), Path(ack_dir), on_letter, clock
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.ack_dir.mkdir(parents=True, exist_ok=True)
        self._stop = threading.Event()
        self.thread: threading.Thread | None = None
        self.ready = threading.Event()
        self.callback_errors = 0

    def _scan(self) -> int:
        acked = 0
        for letter in sorted(self.inbox.glob("*.json")):
            if letter.name.endswith(".ack.json"):
                continue  # a receipt is never a letter (ack_dir may equal the inbox)
            receipt = self.ack_dir / f"{letter.stem}.ack.json"
            if receipt.exists():
                continue
            try:
                body = json.loads(letter.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue  # half-written: the next change event brings it back
            if not isinstance(body, dict):
                continue
            now = self.clock()
            sent = body.get("sent_at")
            record = {"letter": letter.name, "acked_at": now,
                      "latency_s": round(now - float(sent), 4)
                      if isinstance(sent, (int, float)) and not isinstance(sent, bool) and math.isfinite(sent) else None}
            atomic_write_text(receipt, json.dumps(record))  # atomic, and no temp file survives a failure
            acked += 1
            if self.on_letter:
                try:
                    self.on_letter(letter, body)  # the wake: the receiving session is told now, not at its next prompt
                except Exception:  # a failing callback must not kill the watcher thread; the ACK is already durable
                    self.callback_errors += 1
        return acked

    def run(self, *, max_s: float = 3600.0) -> None:
        notifier = _Notifier(self.inbox)
        end = time.monotonic() + max_s
        try:
            self._scan()  # letters that arrived before the watch started
            self.ready.set()
            while not self._stop.is_set() and time.monotonic() < end:
                if notifier.wait(WAIT_SLICE_S):
                    self._scan()
        finally:
            notifier.close()

    def start(self, *, max_s: float = 3600.0) -> "InboxWatcher":
        self.thread = threading.Thread(target=self.run, kwargs={"max_s": max_s}, daemon=True)
        self.thread.start()
        self.ready.wait(5)
        return self

    def stop(self) -> None:
        self._stop.set()
        if self.thread:
            self.thread.join(timeout=5)


def p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))] if ordered else float("nan")
