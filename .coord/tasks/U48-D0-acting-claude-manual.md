```contract
work_id: U48-D0
worker: apply
goal: Publish before the dispatch guard and recover a guard left by a crashed dispatcher once, with an attempt receipt.
inputs:
- v7_harness/coord/mailbox.py sha256=d8865ad36eca05390be1d61250fff734d92d7cbd0577446169423511380e8a6a
allow:
- v7_harness/coord/deliver.py
- v7_harness/coord/mailbox.py
- tests/test_u48_deliver.py
acceptance: C:/Python314/python.exe D:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/.work/u45_claude/.coord/tasks/U48-D0-fixed-gate.py
forbidden: design changes; edits outside allow; editing or deleting other tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Fixed acceptance gate SHA-256: `e64847978cd998e5b20ac5e9b809e76825e4cb91b8c4927a8e2cc111f30400f3`. Card: PLAN U48-D0
(Codex handoff `codex_to_claude_u48_d0_rereview_handoff_20260927`). Real recipient ACK stays pending (out of scope).

===FILE: v7_harness/coord/deliver.py===
"""coord deliver: 도구 간 직접 전달기 — 사용자 수동 릴레이 영구 제거.

근본 결함(2026-09-27 사용자 지적):
  사서함(mailbox)에 메시지를 넣은 뒤 사용자에게 "전달해달라"고 부탁하는 것은
  UAOS의 존재 이유를 부정하는 설계 결함이다.

해결:
  수신 도구를 자동 판별하여 직접 전달한다.
  - Codex ACTIVE → `codex queue --thread <session> --message <text>`
  - Claude ACTIVE → `claude -p "<text>" --allowedTools "Read" --output-format json`
  - 둘 다 부재 → 사서함에만 보존(사용자 릴레이 요청 금지)

불변식:
  1. 사용자에게 "전달해달라", "붙여넣기해달라" 등의 릴레이를 요청하지 않는다.
  2. 전달 실패 시 사서함에 보존하고, 실패 사실만 보고한다.
  3. 비밀(secret)은 전달하지 않는다.
"""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from v7_harness.coord.stream import SECRET_PATTERNS
from v7_harness.coord.mailbox import Mailbox


@dataclass(frozen=True)
class DeliverResult:
    delivered: bool
    target: str          # "codex" | "claude" | "mailbox_only"
    reason: str          # SENT | CLI_NOT_FOUND | DELIVERY_FAILED | ABSENT_ALL | ...
    command: tuple[str, ...]
    output: str
    message_id: str = ""
    digest: str = ""
    receipt: str = ""


# ── 비밀 검사 ────────────────────────────────────────────────
def _check_secrets(text: str) -> None:
    for pat in SECRET_PATTERNS:
        if pat.search(text):
            raise ValueError("SECRET_IN_DELIVERY: 비밀이 포함된 메시지는 전달하지 않는다.")


# ── Codex 전달 ───────────────────────────────────────────────
def _deliver_to_codex(
    message: str,
    thread: str,
    *,
    runner: Any = None,
    timeout: int = 60,
) -> DeliverResult:
    codex_bin = shutil.which("codex")
    if not codex_bin:
        return DeliverResult(False, "codex", "CLI_NOT_FOUND", (), "")

    argv = (codex_bin, "queue", "--thread", thread, "--message", message)
    execute = runner or subprocess.run
    try:
        cp = execute(list(argv), capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return DeliverResult(False, "codex", f"DELIVERY_FAILED:{exc}", argv, "")

    if getattr(cp, "returncode", 1) != 0:
        stderr = getattr(cp, "stderr", "") or ""
        return DeliverResult(False, "codex", f"DELIVERY_FAILED:rc={cp.returncode}", argv, stderr[:500])

    return DeliverResult(True, "codex", "SENT", argv, "")


# ── Claude 전달 ──────────────────────────────────────────────
def _deliver_to_claude(
    message: str,
    *,
    project_dir: Path | None = None,
    runner: Any = None,
    timeout: int = 120,
    allowed_tools: tuple[str, ...] = ("Read",),
) -> DeliverResult:
    claude_bin = shutil.which("claude")
    if not claude_bin:
        return DeliverResult(False, "claude", "CLI_NOT_FOUND", (), "")

    argv_list = [
        claude_bin, "-p", message,
        "--output-format", "json",
    ]
    for tool in allowed_tools:
        argv_list.extend(["--allowedTools", tool])

    execute = runner or subprocess.run
    kwargs: dict[str, Any] = dict(capture_output=True, text=True, timeout=timeout)
    if project_dir:
        kwargs["cwd"] = str(project_dir)

    try:
        cp = execute(argv_list, **kwargs)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return DeliverResult(False, "claude", f"DELIVERY_FAILED:{exc}", tuple(argv_list), "")

    rc = getattr(cp, "returncode", 1)
    stdout = getattr(cp, "stdout", "") or ""
    stderr = getattr(cp, "stderr", "") or ""

    if rc != 0:
        return DeliverResult(False, "claude", f"DELIVERY_FAILED:rc={rc}", tuple(argv_list), stderr[:500])

    # Claude CLI JSON 응답에서 result 추출
    result_text = ""
    try:
        data = json.loads(stdout)
        if not isinstance(data, dict) or data.get("is_error") or data.get("type") == "error_max_budget_usd":
            return DeliverResult(False, "claude", "DELIVERY_FAILED:UNUSABLE_RESPONSE", tuple(argv_list), stdout[:500])
        result_text = data.get("result", stdout[:500])
    except (json.JSONDecodeError, AttributeError):
        result_text = stdout[:500]

    return DeliverResult(True, "claude", "SENT", tuple(argv_list), str(result_text)[:2000])


def _write_receipt(path: Path, payload: dict[str, Any]) -> None:
    """Create one immutable receipt; concurrent attempts get separate names."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


# ── 통합 전달기 ──────────────────────────────────────────────
# Why 300 s: a live dispatcher holds the guard at most for the Claude CLI timeout (120 s) plus receipt writes; 300 s
# gives 2.5x margin so a slow but live dispatcher is never taken for a crashed one.
GUARD_STALE_S = 300.0
# The recovery lock is held only for a stat, a rename and an open (milliseconds); 60 s means its holder crashed.
RECOVER_STALE_S = 60.0
# 50 x 20 ms bounds the claim retry at about 1 s, well above the few ms a concurrent publish holds the file open.
CLAIM_TRIES = 50
CLAIM_SLEEP_S = 0.02


def _payload(actor: str, message: str, digest: str, target: str | None) -> dict[str, Any]:
    """The one published body: the same bytes from every caller, so publish stays idempotent."""
    return {"kind": "HANDOFF", "actor": actor, "message": message, "digest": digest,
            "requested_target": target or "auto"}


def _open_excl(path: Path) -> int | None:
    """Create path exclusively; None if it exists. On Windows a file being unlinked by its holder raises
    PermissionError (delete pending, seen 1 of 50 eight-process runs), so that case is retried, not raised."""
    for _ in range(CLAIM_TRIES):
        try:
            return os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return None
        except PermissionError:
            time.sleep(CLAIM_SLEEP_S)
    return None


def _acquire_guard(guard: Path, box: Mailbox, message_id: str, digest: str) -> int | None:
    """Take the per-message dispatch guard, recovering one left by a crashed dispatcher. None means IN_FLIGHT.

    Recovery runs under a second exclusive lock so the age check and the rename cannot interleave with another
    recoverer (otherwise one could rename a guard that another had just re-created). The stale guard is renamed,
    not deleted, and an attempt receipt records the recovery.
    """
    fd = _open_excl(guard)
    if fd is not None:
        return fd
    try:
        if time.time() - guard.stat().st_mtime < GUARD_STALE_S:
            return None
    except OSError:
        pass  # released since (or delete pending on Windows); the exclusive open below decides
    recover = guard.with_name(guard.name + ".recover")
    rfd = _open_excl(recover)
    if rfd is None:
        try:
            if time.time() - recover.stat().st_mtime >= RECOVER_STALE_S:
                os.rename(recover, recover.with_name(f"{recover.name}.stale-{uuid.uuid4().hex}"))
        except OSError:
            pass
        return None  # another recoverer is working now; this caller's message is already published
    os.close(rfd)
    try:
        try:
            age = time.time() - guard.stat().st_mtime
        except OSError:
            age = None
        if age is not None:
            if age < GUARD_STALE_S:
                return None  # a live dispatcher re-created it between our checks
            stale = guard.with_name(f"{guard.name}.stale-{uuid.uuid4().hex}")
            os.rename(guard, stale)
            _write_receipt(box.root / "delivery" / "attempts" / f"{message_id}_{uuid.uuid4().hex}.json",
                           {"message_id": message_id, "digest": digest, "state": "GUARD_RECOVERED",
                            "stale_guard": str(stale), "age_s": round(age, 1), "timestamp_ns": time.time_ns()})
        return _open_excl(guard)
    finally:
        recover.unlink(missing_ok=True)


def _deliver_unlocked(
    project: Path,
    *,
    message: str,
    actor: str,
    target: str | None = None,
    thread: str = "",
    runner: Any = None,
) -> DeliverResult:
    """메시지를 대상 도구에게 직접 전달한다.

    target: "codex" | "claude" | None (자동 판별).
    자동 판별 시 presence를 읽어 ACTIVE인 도구에게 보낸다.
    Codex ACTIVE면 Codex, 아니면 Claude에게 보낸다.

    불변식: 사용자에게 수동 릴레이를 요청하지 않는다.
    """
    _check_secrets(message)
    project = Path(project).resolve()
    box = Mailbox(project / ".coord" / "mailbox")
    # Stable id makes repeated calls with the same sender and bytes idempotent.
    digest = hashlib.sha256((actor + "\0" + message).encode("utf-8")).hexdigest()
    message_id = "relay_" + digest[:32]
    box.publish(message_id, _payload(actor, message, digest, target))
    ack_file = box.ack_dir / f"{message_id}.json"
    if ack_file.is_file():
        return DeliverResult(True, target or "auto", "ACKED", (), "", message_id, digest, str(ack_file))

    # 자동 판별
    if target is None:
        from v7_harness.coord.presence import read as read_presence
        codex_state = read_presence(project, "codex")["state"]
        if codex_state == "ACTIVE":
            target = "codex"
        else:
            claude_state = read_presence(project, "claude")["state"]
            if claude_state == "ACTIVE":
                target = "claude"
            else:
                # 둘 다 부재: 사서함에만 보존, 사용자 릴레이 요청 금지
                return DeliverResult(False, "mailbox_only", "PUBLISHED", (), "", message_id, digest)

    accepted = box.root / "delivery" / "accepted" / f"{message_id}.json"
    if accepted.is_file():
        return DeliverResult(False, target, "DISPATCHED", (), "", message_id, digest, str(accepted))

    # A same-id caller publishing outside the guard may hold the inbox file open for a moment, and Windows then
    # refuses the claim's rename. Retry briefly instead of reporting IN_FLIGHT with nobody dispatching.
    inbox_file = box.inbox_dir / f"{message_id}.json"
    claim = None
    for _ in range(CLAIM_TRIES):
        claim = box.claim(message_id, "dispatcher")
        if claim is not None or not inbox_file.is_file():
            break
        time.sleep(CLAIM_SLEEP_S)
    if claim is None:
        return DeliverResult(False, target, "IN_FLIGHT", (), "", message_id, digest)

    result: DeliverResult
    try:
        # A contender may have checked before the first sender wrote this
        # receipt, then acquired the claim after the first sender returned it.
        if accepted.is_file():
            return DeliverResult(False, target, "DISPATCHED", (), "", message_id, digest, str(accepted))
        # The claim serializes competing dispatchers. The original is returned
        # to inbox after the attempt; only recipient coord ack may settle it.
        envelope = (f"[UAOS relay id={message_id} digest={digest}]\n{message}\n"
                    f"After processing, run coord ack --id {message_id} for this project. "
                    "The sender keeps this message in the inbox until ACK.")
        if target == "codex":
            if not thread:
                from v7_harness.coord.notify import resolve_thread
                thread = resolve_thread(project)
            result = (_deliver_to_codex(envelope, thread, runner=runner) if thread else
                      DeliverResult(False, "codex", "NO_THREAD", (), ""))
        elif target == "claude":
            prefix = "[안티그래비티에서 온 대화] " if actor.lower() in ("agy", "antigravity") else (
                "[코덱스에서 온 대화] " if actor.lower() == "codex" else "")
            result = _deliver_to_claude(prefix + envelope, project_dir=project, runner=runner)
        else:
            result = DeliverResult(False, str(target), f"UNKNOWN_TARGET:{target}", (), "")

        receipt = {"message_id": message_id, "digest": digest, "target": target,
                   "state": "DISPATCHED" if result.delivered else "FAILED", "reason": result.reason,
                   "timestamp_ns": time.time_ns()}
        attempts = box.root / "delivery" / "attempts"
        attempt_path = attempts / f"{message_id}_{uuid.uuid4().hex}.json"
        _write_receipt(attempt_path, receipt)
        if result.delivered:
            try:
                _write_receipt(accepted, receipt)
            except FileExistsError:
                pass
            return DeliverResult(False, target, "DISPATCHED", result.command, result.output,
                                 message_id, digest, str(accepted))
        return DeliverResult(False, str(target), result.reason, result.command, result.output,
                             message_id, digest, str(attempt_path))
    finally:
        try:
            box.nack(claim)
        except OSError:
            # A same-id publisher reading the claimed copy can block its unlink on Windows. The bytes are already in
            # the inbox or stay in claimed/ for recover_stale_claims, so nothing is lost; do not fail the dispatch.
            pass


def deliver(
    project: Path,
    *,
    message: str,
    actor: str,
    target: str | None = None,
    thread: str = "",
    runner: Any = None,
) -> DeliverResult:
    """Serialize the complete publish-to-dispatch transaction per message.

    On Windows, another publisher opening a claimed file can prevent NACK
    from unlinking it. This outer guard prevents same-id callers from touching
    mailbox files while the owner is publishing or dispatching.
    """
    _check_secrets(message)
    digest = hashlib.sha256((actor + "\0" + message).encode("utf-8")).hexdigest()
    message_id = "relay_" + digest[:32]
    project = Path(project).resolve()
    box = Mailbox(project / ".coord" / "mailbox")
    # U48-D0 re-review (Claude, 2026-09-27): publish before the guard. A guard left by a crashed dispatcher used to
    # return IN_FLIGHT before any publish, so the message never reached the inbox. Publish is idempotent by id+bytes.
    box.publish(message_id, _payload(actor, message, digest, target))
    guard = box.root / "delivery" / "guards" / f"{message_id}.lock"
    guard.parent.mkdir(parents=True, exist_ok=True)
    fd = _acquire_guard(guard, box, message_id, digest)
    if fd is None:
        return DeliverResult(False, target or "mailbox_only", "IN_FLIGHT", (), "", message_id, digest)
    with os.fdopen(fd, "wb") as handle:
        handle.write(json.dumps({"message_id": message_id, "digest": digest, "actor": actor,
                                 "message": message, "target": target}, ensure_ascii=False).encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    try:
        return _deliver_unlocked(project, message=message, actor=actor, target=target,
                                 thread=thread, runner=runner)
    finally:
        guard.unlink(missing_ok=True)
===END===

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
===END===

===FILE: tests/test_u48_deliver.py===
"""coord deliver 단위 테스트 — 사용자 수동 릴레이 영구 제거 검증.

불변식:
  1. 사용자에게 "전달해달라"는 요청이 발생하지 않는다.
  2. Codex ACTIVE → codex queue, Claude ACTIVE → claude -p 직접 호출.
  3. 둘 다 부재 → 사서함에만 보존, 사용자 릴레이 요청 금지.
  4. 비밀 포함 메시지는 전달 거부.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from v7_harness.coord.deliver import (
    GUARD_STALE_S,
    DeliverResult,
    _check_secrets,
    _deliver_to_claude,
    _deliver_to_codex,
    deliver,
)
from v7_harness.coord.mailbox import Mailbox


def _delivery_process(project_text: str, results) -> None:
    runner = FakeRunner(returncode=0, stdout=json.dumps({"result": "accepted", "type": "result"}))
    with patch("v7_harness.coord.deliver.shutil.which", return_value="claude"):
        outcome = deliver(Path(project_text), message="U48-D0 parallel contract", actor="codex",
                          target="claude", runner=runner)
    results.put({"reason": outcome.reason, "calls": len(runner.calls), "id": outcome.message_id})


class FakeRunner:
    """CLI 호출을 가로채는 테스트용 러너."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.calls: list[list[str]] = []
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        return SimpleNamespace(
            returncode=self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
        )


class TestSecretCheck(unittest.TestCase):
    def test_clean_message_passes(self):
        _check_secrets("U47-R1e 857 테스트 통과, 매뉴얼 요청")

    def test_api_key_rejected(self):
        with self.assertRaises(ValueError):
            _check_secrets("api_key=sk-abc1234567890abcdefghij")


class TestDeliverToCodex(unittest.TestCase):
    def test_sends_via_codex_queue(self):
        runner = FakeRunner(returncode=0)
        result = _deliver_to_codex("test message", "thread-123", runner=runner)
        self.assertTrue(result.delivered)
        self.assertEqual(result.target, "codex")
        self.assertEqual(result.reason, "SENT")
        self.assertEqual(len(runner.calls), 1)
        self.assertIn("queue", runner.calls[0])
        self.assertIn("test message", runner.calls[0])

    def test_failure_does_not_ask_user(self):
        runner = FakeRunner(returncode=1, stderr="connection refused")
        result = _deliver_to_codex("test", "thread-1", runner=runner)
        self.assertFalse(result.delivered)
        self.assertEqual(result.target, "codex")
        self.assertIn("DELIVERY_FAILED", result.reason)
        # 핵심: 사용자에게 릴레이를 요청하는 텍스트가 없어야 한다
        self.assertNotIn("전달해 주세요", result.output)
        self.assertNotIn("붙여넣기", result.output)


class TestDeliverToClaude(unittest.TestCase):
    def test_sends_via_claude_cli(self):
        runner = FakeRunner(
            returncode=0,
            stdout=json.dumps({"result": "매뉴얼 수신 완료", "type": "result"}),
        )
        result = _deliver_to_claude("test message", runner=runner)
        self.assertTrue(result.delivered)
        self.assertEqual(result.target, "claude")
        self.assertEqual(result.reason, "SENT")
        self.assertEqual(len(runner.calls), 1)
        self.assertIn("-p", runner.calls[0])

    def test_failure_does_not_ask_user(self):
        runner = FakeRunner(returncode=1, stderr="timeout")
        result = _deliver_to_claude("test", runner=runner)
        self.assertFalse(result.delivered)
        self.assertIn("DELIVERY_FAILED", result.reason)
        self.assertNotIn("전달해 주세요", result.output)
        self.assertNotIn("붙여넣기", result.output)


class TestDeliverAutoRoute(unittest.TestCase):
    """자동 판별: presence에 따라 대상을 고른다."""

    def _mock_presence(self, codex_state: str, claude_state: str):
        def fake_read(project, tool):
            states = {"codex": codex_state, "claude": claude_state}
            return {"state": states.get(tool, "UNKNOWN")}
        return fake_read

    @patch("v7_harness.coord.deliver.shutil.which", return_value="/usr/bin/claude")
    def test_codex_absent_routes_to_claude(self, _mock_which):
        runner = FakeRunner(
            returncode=0,
            stdout=json.dumps({"result": "ok", "type": "result"}),
        )
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / ".coord" / "mailbox").mkdir(parents=True)
            with patch("v7_harness.coord.presence.read", self._mock_presence("LIMITED", "ACTIVE")):
                result = deliver(project, message="테스트", actor="antigravity", runner=runner)
        self.assertFalse(result.delivered)
        self.assertEqual("DISPATCHED", result.reason)
        self.assertEqual(result.target, "claude")
        # Claude CLI가 직접 호출되었는지 확인
        self.assertEqual(len(runner.calls), 1)
        self.assertIn("-p", runner.calls[0])
        sent = runner.calls[0][runner.calls[0].index("-p") + 1]
        self.assertIn(result.message_id, sent)
        self.assertIn(result.digest, sent)

    def test_both_absent_saves_to_mailbox_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / ".coord" / "mailbox").mkdir(parents=True)
            with patch("v7_harness.coord.presence.read", self._mock_presence("ABSENT", "ABSENT")):
                result = deliver(project, message="테스트", actor="antigravity")
        self.assertFalse(result.delivered)
        self.assertEqual(result.target, "mailbox_only")
        self.assertEqual(result.reason, "PUBLISHED")
        # 핵심 불변식: 사용자 릴레이 요청 금지
        self.assertEqual("", result.output)


class TestAntiRelay(unittest.TestCase):
    """사용자에게 수동 릴레이를 부탁하는 문구가 코드에 존재하지 않음을 검증."""

    def test_deliver_module_has_no_user_relay_request(self):
        import v7_harness.coord.deliver as mod
        source = Path(mod.__file__).read_text(encoding="utf-8")
        banned_phrases = [
            "전달해 주세요",
            "붙여넣기해 주세요",
            "전달해주세요",
            "복사해서 전달",
            "대화창에 아래",
            "아래 1줄을 전달",
        ]
        for phrase in banned_phrases:
            self.assertNotIn(
                phrase, source,
                f"deliver.py에 사용자 릴레이 요청 문구 '{phrase}'가 포함되어 있다 — 설계 결함",
            )


class TestDurableDelivery(unittest.TestCase):
    def test_absent_recipient_still_publishes_original_message(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / ".coord" / "mailbox").mkdir(parents=True)
            with patch("v7_harness.coord.presence.read", return_value={"state": "ABSENT"}):
                result = deliver(project, message="U48-D0 fixed contract", actor="codex", target=None)
            self.assertFalse(result.delivered)
            inbox = list((project / ".coord" / "mailbox" / "inbox").glob("*.json"))
            self.assertEqual(1, len(inbox))
            self.assertIn("U48-D0 fixed contract", inbox[0].read_text(encoding="utf-8"))

    def test_cli_exit_zero_is_dispatch_not_receiver_ack(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / ".coord" / "mailbox").mkdir(parents=True)
            runner = FakeRunner(returncode=0, stdout=json.dumps({"result": "ok", "type": "result"}))
            with patch("v7_harness.coord.deliver.shutil.which", return_value="claude"):
                result = deliver(project, message="U48-D0 fixed contract", actor="codex", target="claude", runner=runner)
            self.assertFalse(result.delivered)
            self.assertEqual("DISPATCHED", result.reason)
            self.assertEqual(1, len(list((project / ".coord" / "mailbox" / "inbox").glob("*.json"))))
            self.assertEqual(0, len(list((project / ".coord" / "mailbox" / "ack").glob("*.json"))))

    def test_eight_processes_one_dispatch_and_explicit_ack(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / ".coord" / "mailbox").mkdir(parents=True)
            ctx = multiprocessing.get_context("spawn")
            results = ctx.Queue()
            workers = [ctx.Process(target=_delivery_process, args=(str(project), results)) for _ in range(8)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(15)
                self.assertEqual(0, worker.exitcode)
            outcomes = [results.get(timeout=2) for _ in workers]
            ids = {outcome["id"] for outcome in outcomes}
            self.assertEqual(1, len(ids))
            self.assertEqual(1, sum(outcome["calls"] for outcome in outcomes), outcomes)
            box = Mailbox(project / ".coord" / "mailbox")
            message_id = ids.pop()
            inbox = box.inbox_dir / f"{message_id}.json"
            self.assertTrue(inbox.is_file())
            original = inbox.read_bytes()
            self.assertEqual(1, len(list((box.root / "delivery" / "attempts").glob("*.json"))))
            self.assertFalse((box.ack_dir / f"{message_id}.json").exists())
            claim = box.claim(message_id, "receiver")
            self.assertIsNotNone(claim)
            ack = box.ack(claim)
            self.assertEqual(original, ack.read_bytes())
            result = deliver(project, message="U48-D0 parallel contract", actor="codex", target="claude")
            self.assertTrue(result.delivered)
            self.assertEqual("ACKED", result.reason)

    def test_failed_attempt_is_retained_and_retryable(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / ".coord" / "mailbox").mkdir(parents=True)
            with patch("v7_harness.coord.deliver.shutil.which", return_value="claude"):
                first = deliver(project, message="retry contract", actor="codex", target="claude",
                                runner=FakeRunner(returncode=1, stderr="connection refused"))
                second = deliver(project, message="retry contract", actor="codex", target="claude",
                                 runner=FakeRunner(returncode=0, stdout=json.dumps({"result": "ok"})))
            self.assertIn("DELIVERY_FAILED", first.reason)
            self.assertEqual("DISPATCHED", second.reason)
            self.assertEqual(first.message_id, second.message_id)
            attempts = list((project / ".coord" / "mailbox" / "delivery" / "attempts").glob("*.json"))
            self.assertEqual(2, len(attempts))
            self.assertTrue((project / ".coord" / "mailbox" / "inbox" /
                             f"{first.message_id}.json").is_file())


def _guard_for(project: Path, message: str, actor: str = "codex") -> Path:
    digest = hashlib.sha256((actor + "\0" + message).encode("utf-8")).hexdigest()
    guard = project / ".coord" / "mailbox" / "delivery" / "guards" / f"relay_{digest[:32]}.lock"
    guard.parent.mkdir(parents=True, exist_ok=True)
    guard.write_text("{}", encoding="utf-8")
    return guard


def _age(path: Path, seconds: float) -> None:
    old = time.time() - seconds
    os.utime(path, (old, old))


class TestGuardRecovery(unittest.TestCase):
    """U48-D0 re-review (Claude, 2026-09-27): a guard left by a crashed dispatcher must not block the message."""

    def test_fresh_guard_is_in_flight_but_message_is_published(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / ".coord" / "mailbox").mkdir(parents=True)
            guard = _guard_for(project, "held contract")
            runner = FakeRunner(returncode=0, stdout=json.dumps({"result": "ok"}))
            with patch("v7_harness.coord.deliver.shutil.which", return_value="claude"):
                result = deliver(project, message="held contract", actor="codex", target="claude", runner=runner)
            self.assertEqual("IN_FLIGHT", result.reason)
            self.assertEqual([], runner.calls)
            self.assertTrue(guard.is_file())  # a live holder's guard is never touched
            inbox = project / ".coord" / "mailbox" / "inbox" / f"{result.message_id}.json"
            self.assertIn("held contract", inbox.read_text(encoding="utf-8"))

    def test_aged_guard_is_recovered_once_with_a_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / ".coord" / "mailbox").mkdir(parents=True)
            guard = _guard_for(project, "crashed contract")
            _age(guard, GUARD_STALE_S + 100)
            runner = FakeRunner(returncode=0, stdout=json.dumps({"result": "ok"}))
            with patch("v7_harness.coord.deliver.shutil.which", return_value="claude"):
                result = deliver(project, message="crashed contract", actor="codex", target="claude", runner=runner)
            self.assertEqual("DISPATCHED", result.reason)
            self.assertEqual(1, len(runner.calls))
            guards = guard.parent
            self.assertFalse(guard.exists())
            self.assertEqual(1, len(list(guards.glob(f"{guard.name}.stale-*"))))  # preserved, not deleted
            self.assertEqual([], list(guards.glob("*.recover")))
            attempts = project / ".coord" / "mailbox" / "delivery" / "attempts"
            states = [json.loads(p.read_text(encoding="utf-8")).get("state") for p in attempts.glob("*.json")]
            self.assertEqual(1, states.count("GUARD_RECOVERED"))

    def test_eight_processes_recover_an_aged_guard_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / ".coord" / "mailbox").mkdir(parents=True)
            guard = _guard_for(project, "U48-D0 parallel contract")
            _age(guard, GUARD_STALE_S + 100)
            ctx = multiprocessing.get_context("spawn")
            results = ctx.Queue()
            workers = [ctx.Process(target=_delivery_process, args=(str(project), results)) for _ in range(8)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(15)
                self.assertEqual(0, worker.exitcode)
            outcomes = [results.get(timeout=2) for _ in workers]
            self.assertEqual(1, sum(outcome["calls"] for outcome in outcomes), outcomes)
            self.assertEqual(1, len(list(guard.parent.glob(f"{guard.name}.stale-*"))))


if __name__ == "__main__":
    unittest.main()
===END===

## Output

- Reply with ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.
