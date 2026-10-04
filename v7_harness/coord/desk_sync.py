"""U163: an explicit user-desk designation in one tool reaches the other two tools' hooks once, at zero paid cost.

Receipt (Codex relay_79d08c71): the hook registered a desk on every human prompt, so typing in an execution chat stole
the desk, and no peer heard of a change. Frozen acceptance: tests/test_u163_desk_sync.py (Codex execution agent).
- Only a fresh explicit declaration designates (user_window.is_declaration, or `coord presence --desk-thread`). A
  worker session (UAOS_WORKER) never designates. An Antigravity turn is keyed by conversation, turn count and text, so
  a replayed turn never designates again.
- A designation that changes the thread raises the tool's generation; the same thread again changes nothing.
- Peers pull the change: each receiver's desk delta shows every peer record newer than its own cursor, and the cursor
  advances only after the hook wrote that text (output precedes ack), so a notice counts as delivered only once the
  receiver's own hook showed it. Nothing is published and no paid turn is dispatched.
- Writes happen under one OS file lock (stream._try_lock): a dead holder is freed by the OS, a live one is never
  robbed, and nothing is reclaimed by age. A record that exists but cannot be read fails closed and is never
  overwritten.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from v7_harness.coord import deliver
from v7_harness.coord.stream import _try_lock, _unlock

TOOLS = deliver.USER_DESK_TOOLS
LOCK_TIMEOUT_S = 10.0  # the user_window claim's wait (LOCK_WAIT_S): a hook must not hang a session longer
REPLACE_TRIES = 40  # x 0.05 s: a reader holding the record open on Windows blocks os.replace briefly
SEEN_KEEP = 200  # replayed Antigravity turn keys kept; older keys belong to turns far behind the transcript end


def _desk(project: Path) -> Path:
    return deliver._project_mailbox(Path(project).resolve()).root.parent.parent


def peers_of(tool: str) -> tuple[str, ...]:
    return tuple(peer for peer in TOOLS if peer != tool)


@contextmanager
def _locked(desk: Path):
    path = desk / ".coord" / "presence" / "user_desk.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + LOCK_TIMEOUT_S
    fd = None
    try:
        while True:
            if fd is None:
                try:
                    fd = os.open(path, os.O_CREAT | os.O_RDWR)
                except PermissionError:
                    fd = None
            if fd is not None and _try_lock(fd):
                break
            if time.monotonic() > deadline:
                raise TimeoutError("USER_DESK_LOCK_BUSY")
            time.sleep(0.01)
        try:
            yield
        finally:
            _unlock(fd)
    finally:
        if fd is not None:
            os.close(fd)


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    for _attempt in range(REPLACE_TRIES):
        try:
            os.replace(temp, path)
            return
        except PermissionError:
            time.sleep(0.05)
    temp.unlink(missing_ok=True)
    raise PermissionError(f"could not replace {path}")


def _record(desk: Path, tool: str) -> dict[str, Any]:
    """{} when no record exists; ValueError when one exists but is unreadable. A legacy record is generation 0."""
    path = deliver.user_desk_path(desk, tool)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as error:
        raise ValueError(f"USER_DESK_RECORD_UNREADABLE {path.name}") from error
    try:
        data = json.loads(text)
    except ValueError as error:
        raise ValueError(f"USER_DESK_RECORD_CORRUPT {path.name}") from error
    thread = data.get("thread") if isinstance(data, dict) else None
    if not isinstance(thread, str) or not deliver.UUID_RE.fullmatch(thread):
        raise ValueError(f"USER_DESK_RECORD_CORRUPT {path.name}")
    generation = data.get("generation")
    return {**data, "generation": generation if isinstance(generation, int) and generation >= 0 else 0}


def _seen_path(desk: Path) -> Path:
    return desk / ".coord" / "presence" / "desk_seen.json"


def _seen(desk: Path) -> list[str]:
    try:
        data = json.loads(_seen_path(desk).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [item for item in data if isinstance(item, str)] if isinstance(data, list) else []


def designate(project: Path, tool: str, thread: str, *, source: str, fingerprint: str | None = None,
              repair: bool = False) -> bool:
    """Make `thread` the user's desk for `tool`; True when it is the desk afterwards.

    False for an invalid tool or thread, a replayed turn, or a lock a live holder keeps past LOCK_TIMEOUT_S.
    Raises ValueError when the existing record is unreadable: it is never overwritten. Only `repair` (the explicit
    `coord presence --desk-thread` command, U148) replaces it, after keeping the unreadable bytes as `.corrupt`."""
    if tool not in TOOLS or not isinstance(thread, str) or not deliver.UUID_RE.fullmatch(thread):
        return False
    desk = _desk(project)
    try:
        with _locked(desk):
            try:
                record = _record(desk, tool)
            except ValueError:
                if not repair:
                    raise
                path = deliver.user_desk_path(desk, tool)
                os.replace(path, path.with_name(f"{path.name}.{time.time_ns()}.corrupt"))
                record = {}
            seen = _seen(desk)
            if fingerprint and fingerprint in seen:
                return False  # the same Antigravity turn seen again: it designated (or not) the first time
            if fingerprint:
                _write_json(_seen_path(desk), (seen + [fingerprint])[-SEEN_KEEP:])
            if record.get("thread") == thread:
                return True
            _write_json(deliver.user_desk_path(desk, tool), {"thread": thread, "at": time.time(), "source": source,
                                                             "generation": record.get("generation", 0) + 1})
    except TimeoutError:
        return False
    return True


def _cursor_path(desk: Path, receiver: str) -> Path:
    return desk / ".coord" / "presence" / f"desk_notice_{receiver}.json"


def _acked(desk: Path, receiver: str) -> dict[str, int]:
    try:
        data = json.loads(_cursor_path(desk, receiver).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    acked = data.get("acked") if isinstance(data, dict) else None
    if not isinstance(acked, dict):
        return {}
    return {tool: number for tool, number in acked.items() if tool in TOOLS and isinstance(number, int)}


def prepare_notice(project: Path, receiver: str, session: str | None = None) -> tuple[str, Callable[[], None]]:
    """The peers' desk changes `receiver` has not seen, and an ack() to call only after the text was written.

    ack() records the generations shown here, never later ones, so a designation made between the two calls is
    still shown next time. A peer whose record is unreadable is skipped (fail closed: no guessed desk)."""
    def nothing() -> None:
        return None

    if receiver not in TOOLS:
        return "", nothing
    desk = _desk(project)
    acked = _acked(desk, receiver)
    shown: dict[str, int] = {}
    lines: list[str] = []
    for tool in peers_of(receiver):
        try:
            record = _record(desk, tool)
        except ValueError:
            continue
        generation = record.get("generation", 0)
        if generation > acked.get(tool, 0):
            shown[tool] = generation
            lines.append(f"USER DESK {tool}: 윤겸스 now talks to {tool} in thread {record['thread']} "
                         f"(generation {generation}); send {tool}'s user-facing letters there (U163).")
    if not shown:
        return "", nothing

    def ack() -> None:
        with _locked(desk):
            current = _acked(desk, receiver)
            for tool, generation in shown.items():
                current[tool] = max(current.get(tool, 0), generation)
            _write_json(_cursor_path(desk, receiver), {"acked": current, "session": str(session or ""),
                                                       "at": time.time()})

    return "\n".join(lines), ack


def on_prompt(project: Path, tool: str, thread: str, prompt: object) -> bool:
    """A human prompt designates its own thread only when it is a fresh explicit declaration."""
    from v7_harness.coord.user_window import is_declaration

    if os.environ.get("UAOS_WORKER") or tool not in TOOLS or not is_declaration(prompt):
        return False
    try:
        return designate(project, tool, thread, source="UserPromptSubmit")
    except (OSError, ValueError):
        return False


def on_hook(project: Path, tool: str, event: dict[str, Any], session: str) -> bool:
    """The hook's whole part: designate on a fresh declaration. Never raises; a hook never fails the session."""
    try:
        if tool in ("codex", "claude") and event.get("hook_event_name") == "UserPromptSubmit":
            return bool(session) and on_prompt(project, tool, session, event.get("prompt"))
        if tool == "antigravity" and event.get("invocationNum", 0) == 0 and event.get("transcriptPath") \
                and not os.environ.get("UAOS_WORKER"):
            conversation = str(event.get("conversationId") or "")
            if deliver.agy_desktop_conversation(conversation):
                from v7_harness.coord.codex_session_bridge import parse_transcript_to_turns
                from v7_harness.coord.user_window import is_declaration

                turns = parse_transcript_to_turns(Path(str(event["transcriptPath"])))
                prompt = turns[-1][0] if turns else None
                if is_declaration(prompt):
                    key = hashlib.sha256(f"{conversation}\0{len(turns)}\0{prompt}".encode("utf-8")).hexdigest()
                    return designate(project, "antigravity", conversation, source="PreInvocation", fingerprint=key)
    except (OSError, ValueError, TimeoutError):
        return False
    return False
