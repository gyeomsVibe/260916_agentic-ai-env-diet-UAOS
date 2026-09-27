```contract
work_id: U49-M2
worker: apply
goal: Mailbox.publish fails closed when an existing ack or claimed copy stays locked after PUBLISH_TRIES reads, instead of treating it as absent and publishing an acked id again.
inputs:
- v7_harness/coord/mailbox.py sha256=39537b8be1578c6d2de32663ac87c5b211e83a8f1dfe6576e28b317d9f8f9dab
allow:
- v7_harness/coord/mailbox.py
- tests/test_u49_mailbox_locked_ack.py
acceptance: C:/Python314/python.exe -m unittest tests.test_u49_mailbox_locked_ack tests.test_u32_mailbox_lossless tests.test_u23_mailbox tests.test_u48_deliver tests.test_u48_deliver_d1
forbidden: design changes; edits outside allow; weakening or deleting existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Card: PLAN U49-M2, REDTEAM P2 from .coord/tasks/U49-acting-codex-review-20260927.md (D0 _read_settled). New test red on HEAD (1 failure: locked ack republished), 2 guard tests green. Acting judge Claude (user order 2026-09-27); Codex re-reviews.

===FILE: v7_harness/coord/mailbox.py===
from __future__ import annotations
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
import time
import uuid

class MailboxRejected(ValueError):
    pass

WINDOWS_RESERVED_NAMES = frozenset({
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
})

SECRET_PATTERNS = (
    re.compile(r"sk-[a-zA-Z0-9_\-]{20,}"),
    re.compile(r"ghp_[a-zA-Z0-9]{20,}"),
    re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]{20,}"),
    re.compile(r"(?:api[_-]?key|secret|token|password|credential)[\"']?\s*[:=]\s*[\"']?[a-zA-Z0-9_\-]{16,}", re.IGNORECASE),
)

def _is_symlink_or_reparse(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        if hasattr(path, "is_junction") and path.is_junction():
            return True
        st = path.lstat()
        attrs = getattr(st, "st_file_attributes", 0)
        if attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            return True
    except (OSError, ValueError):
        pass
    return False

MESSAGE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
# U48-D0 (Claude, 2026-09-27): on Windows a file another process is renaming or unlinking briefly raises
# PermissionError (delete pending); 3 of 50 eight-process runs failed that way. 50 x 20 ms bounds a publish at
# about 1 s, well above the few ms such a rename takes.
PUBLISH_TRIES = 50
SETTLE_SLEEP_S = 0.02


def _read_settled(path: Path) -> bytes | None:
    """Read a file that may be mid-rename by another process; None means it is gone (or never settled)."""
    for _ in range(PUBLISH_TRIES):
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None
        except PermissionError:
            time.sleep(SETTLE_SLEEP_S)
    return None


def _fsync_dir(path: Path) -> None:
    # A new link is durable only after its directory entry is flushed (POSIX). Windows cannot open a directory
    # for fsync; NTFS journals the metadata instead.
    if os.name == "nt":
        return
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_message(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


@dataclass(frozen=True)
class ClaimedMessage:
    message_id: str
    consumer_id: str
    claimed_path: Path
    payload: object
    schema: str = "u23-mailbox-v1"

class Mailbox:
    def __init__(self, root: Path, *, max_message_bytes: int = 65536):
        if max_message_bytes <= 0:
            raise MailboxRejected("max_message_bytes must be positive")
        self.root = Path(root)
        if not self.root.exists() or not self.root.is_dir():
            raise MailboxRejected("root must exist and be a directory")
        if _is_symlink_or_reparse(self.root):
            raise MailboxRejected("root cannot be a symlink or reparse point")
        self.max_message_bytes = max_message_bytes
        self.tmp_dir = self.root / "tmp"
        self.inbox_dir = self.root / "inbox"
        self.claimed_dir = self.root / "claimed"
        self.ack_dir = self.root / "ack"
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.claimed_dir.mkdir(parents=True, exist_ok=True)
        self.ack_dir.mkdir(parents=True, exist_ok=True)
        if (
            _is_symlink_or_reparse(self.tmp_dir)
            or _is_symlink_or_reparse(self.inbox_dir)
            or _is_symlink_or_reparse(self.claimed_dir)
            or _is_symlink_or_reparse(self.ack_dir)
        ):
            raise MailboxRejected("directories cannot be symlinks or reparse points")

    def publish(self, message_id: str, payload: object) -> Path:
        if not isinstance(message_id, str):
            raise MailboxRejected("message_id must be a string")
        if not MESSAGE_ID_RE.fullmatch(message_id):
            raise MailboxRejected(f"invalid message_id: {message_id!r}")
        if message_id.upper() in WINDOWS_RESERVED_NAMES:
            raise MailboxRejected(f"reserved device name: {message_id}")

        data = {
            "schema": "u23-mailbox-v1",
            "message_id": message_id,
            "payload": payload,
        }
        try:
            encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise MailboxRejected(f"non-JSON payload: {exc}")

        if len(encoded) > self.max_message_bytes:
            raise MailboxRejected(f"encoded message exceeds max_message_bytes ({len(encoded)} > {self.max_message_bytes})")

        raw_str = encoded.decode("utf-8", errors="replace")
        for pat in SECRET_PATTERNS:
            if pat.search(raw_str):
                raise MailboxRejected("secret detected in message payload")

        # One message id carries one content wherever it is (inbox, claimed or ack). An acked id is not
        # delivered again, and a different content under a known id is refused instead of replacing it.
        for existing in (self.ack_dir / f"{message_id}.json", *self._claimed_files(message_id)):
            existing_bytes = _read_settled(existing)
            if existing_bytes is None:
                # U49-M2: None also means "still locked after PUBLISH_TRIES". Treating a locked ack as absent would
                # publish an acked id again, so a file that still exists fails closed; the sender retries later.
                if existing.exists():
                    raise MailboxRejected(f"unsettled {existing.name}: still locked after {PUBLISH_TRIES} reads")
                continue
            if existing_bytes == encoded:
                return existing
            raise MailboxRejected(f"collision with different content for {message_id}")

        tmp_name = f"{message_id}_{os.getpid()}_{uuid.uuid4().hex}.tmp"
        tmp_file = self.tmp_dir / tmp_name
        inbox_file = self.inbox_dir / f"{message_id}.json"

        try:
            with open(tmp_file, "wb") as f:
                f.write(encoded)
                f.flush()
                os.fsync(f.fileno())
            for _ in range(PUBLISH_TRIES):
                try:
                    os.link(str(tmp_file), str(inbox_file))
                except FileExistsError:
                    existing_bytes = _read_settled(inbox_file)
                    if existing_bytes is None:
                        # Another process claimed the inbox link between the
                        # hard-link collision and this read. Find that exact
                        # claim or retry; never treat its move as data loss.
                        for existing in (self.ack_dir / f"{message_id}.json", *self._claimed_files(message_id)):
                            if _read_settled(existing) == encoded:
                                return existing
                        time.sleep(SETTLE_SLEEP_S)
                        continue
                    if existing_bytes == encoded:
                        return inbox_file
                    raise MailboxRejected(f"collision with different content for {message_id}")
                else:
                    _fsync_dir(self.inbox_dir)
                    return inbox_file
            raise MailboxRejected(f"publish race did not settle for {message_id}")
        finally:
            try:
                tmp_file.unlink(missing_ok=True)
            except OSError:
                pass

    def _claimed_files(self, message_id: str) -> list[Path]:
        # Claimed names start with "<id>_", but ids may contain "_", so the id inside the file decides.
        return [
            path
            for path in sorted(self.claimed_dir.glob(f"{message_id}_*.json"))
            if (_read_message(path) or {}).get("message_id") == message_id
        ]

    def has_message(self, message_id: str) -> bool:
        return (
            (self.inbox_dir / f"{message_id}.json").is_file()
            or (self.ack_dir / f"{message_id}.json").is_file()
            or bool(self._claimed_files(message_id))
        )

    def list_inbox(self) -> list[str]:
        return sorted([p.stem for p in self.inbox_dir.glob("*.json") if p.is_file()])

    def peek(self) -> list[tuple[str, object]]:
        """Read inbox payloads without claiming them, so a status check never hides a message from a consumer."""
        messages: list[tuple[str, object]] = []
        for path in sorted(self.inbox_dir.glob("*.json")):
            data = _read_message(path)
            if data is not None:
                messages.append((path.stem, data.get("payload")))
        return messages

    def list_bad(self) -> list[str]:
        bad_dir = self.root / "bad"
        return sorted(p.name for p in bad_dir.glob("*")) if bad_dir.is_dir() else []

    def _quarantine(self, path: Path) -> None:
        # An unreadable file is kept, not deleted, and surfaced by list_bad() instead of hiding in claimed/.
        bad_dir = self.root / "bad"
        bad_dir.mkdir(exist_ok=True)
        try:
            os.rename(str(path), str(bad_dir / f"{path.stem}_{uuid.uuid4().hex}{path.suffix}"))
        except OSError:
            pass

    def claim(self, message_id: str, consumer_id: str) -> ClaimedMessage | None:
        inbox_file = self.inbox_dir / f"{message_id}.json"
        if not inbox_file.is_file():
            return None
        claimed_name = f"{message_id}_{consumer_id}_{os.getpid()}_{uuid.uuid4().hex}.json"
        claimed_file = self.claimed_dir / claimed_name
        try:
            # The lease starts now. rename keeps the publish-time mtime, which made old messages look stale
            # the moment they were claimed.
            os.utime(str(inbox_file))
            os.rename(str(inbox_file), str(claimed_file))
        except OSError:
            return None
        data = _read_message(claimed_file)
        if data is None:
            self._quarantine(claimed_file)
            return None
        return ClaimedMessage(
            message_id=message_id,
            consumer_id=consumer_id,
            claimed_path=claimed_file,
            payload=data.get("payload"),
            schema=data.get("schema", "u23-mailbox-v1"),
        )

    def renew(self, claim: ClaimedMessage) -> bool:
        """Extend the lease of a long-running claim. False means the claim was already recovered."""
        try:
            os.utime(str(claim.claimed_path))
        except FileNotFoundError:
            return False
        return True

    def ack(self, claim: ClaimedMessage) -> Path:
        ack_file = self.ack_dir / f"{claim.message_id}.json"
        if not claim.claimed_path.exists():
            if ack_file.is_file():
                return ack_file
            raise MailboxRejected(f"claim lost before ack (lease expired or recovered): {claim.message_id}")
        try:
            os.link(str(claim.claimed_path), str(ack_file))
        except FileExistsError:
            pass
        else:
            _fsync_dir(self.ack_dir)
        claim.claimed_path.unlink(missing_ok=True)
        return ack_file

    def _return_to_inbox(self, path: Path, message_id: str) -> bool:
        # link, not rename: rename silently replaces an inbox file on POSIX. The claimed copy is removed only
        # after the inbox holds the same bytes; on any other failure it stays for the next lease expiry.
        inbox_file = self.inbox_dir / f"{message_id}.json"
        try:
            os.link(str(path), str(inbox_file))
        except FileExistsError:
            if inbox_file.read_bytes() != path.read_bytes():
                self._quarantine(path)
                return False
        except OSError:
            return False
        else:
            _fsync_dir(self.inbox_dir)
        path.unlink(missing_ok=True)
        return True

    def nack(self, claim: ClaimedMessage) -> Path:
        inbox_file = self.inbox_dir / f"{claim.message_id}.json"
        if claim.claimed_path.exists():
            self._return_to_inbox(claim.claimed_path, claim.message_id)
        return inbox_file

    def recover_stale_claims(self, stale_timeout_s: float = 60.0) -> list[str]:
        recovered: list[str] = []
        now = time.time()
        for path in sorted(self.claimed_dir.glob("*.json")):
            if not path.is_file():
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if now - mtime < stale_timeout_s:
                continue
            msg_id = (_read_message(path) or {}).get("message_id")
            if (
                not isinstance(msg_id, str)
                or not MESSAGE_ID_RE.fullmatch(msg_id)
                or msg_id.upper() in WINDOWS_RESERVED_NAMES
            ):
                self._quarantine(path)
                continue
            if self._return_to_inbox(path, msg_id):
                recovered.append(msg_id)
        return recovered
===FILE: tests/test_u49_mailbox_locked_ack.py===
"""U49-M2: an ack file that stays locked must not be read as "absent" (that would publish an acked id again)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import mailbox as mailbox_module
from v7_harness.coord.mailbox import Mailbox, MailboxRejected

PAYLOAD = {"kind": "HANDOFF", "message": "hello"}


class LockedAckTests(unittest.TestCase):
    def _acked_box(self, directory: str) -> tuple[Mailbox, Path]:
        box = Mailbox(Path(directory))
        box.publish("m1", PAYLOAD)
        claim = box.claim("m1", "reader")
        box.ack(claim)
        ack = box.ack_dir / "m1.json"
        self.assertTrue(ack.is_file())
        return box, ack

    def test_locked_ack_fails_closed_instead_of_republishing(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            box, ack = self._acked_box(d)
            real = Path.read_bytes

            def locked(path: Path) -> bytes:
                if path == ack:
                    raise PermissionError(13, "locked", str(path))
                return real(path)

            with mock.patch.object(Path, "read_bytes", locked), mock.patch.object(mailbox_module.time, "sleep"):
                with self.assertRaises(MailboxRejected):
                    box.publish("m1", PAYLOAD)
            self.assertFalse((box.inbox_dir / "m1.json").exists())

    def test_readable_ack_still_dedupes(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            box, ack = self._acked_box(d)
            self.assertEqual(ack, box.publish("m1", PAYLOAD))
            self.assertFalse((box.inbox_dir / "m1.json").exists())

    def test_vanished_file_is_still_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            box = Mailbox(Path(d))
            path = box.inbox_dir / "m2.json"
            self.assertIsNone(mailbox_module._read_settled(path))
            box.publish("m2", PAYLOAD)
            self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()
===END===

## Output

- Reply with ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.
