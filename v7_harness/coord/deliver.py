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
import re
import shutil
import subprocess
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from v7_harness.coord.stream import SECRET_PATTERNS, _try_lock, _unlock
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


# U64-F (Claude acting, 2026-09-28): whole tokens only. Substrings woke a paid cold turn for "inbox 140 (P1 0)",
# "STEP1" and "no ACTIONABLE_DELTA since last"; an ACK_ONLY marker always wins.
_TOKEN = r"(?<![A-Z0-9_=]){}(?![A-Z0-9_])"
_ACK_RE = re.compile(_TOKEN.format("ACK_ONLY"))
_NEGATED_RE = re.compile(r"\b(?:NO|NOT|WITHOUT|NON)[\s-]+ACTIONABLE_DELTA\b")
_WAKE_RES = tuple(re.compile(_TOKEN.format(token)) for token in (
    "ACTIONABLE_DELTA", "VERDICT_REQUESTED=YES", "APPROVAL_REQUIRED", r"(?:PRIORITY|SEVERITY|P1)=(?:P1|YES|1)"))


def _requires_wake(message: str) -> bool:
    """Only a real delta may spend a paid turn; ACK_ONLY, negated or incidental tokens never do."""
    upper = message.upper()
    if _ACK_RE.search(upper):
        return False
    upper = _NEGATED_RE.sub(" ", upper)
    return any(pattern.search(upper) for pattern in _WAKE_RES)


# ── 비밀 검사 ────────────────────────────────────────────────
def _check_secrets(text: str) -> None:
    for pat in SECRET_PATTERNS:
        if pat.search(text):
            raise ValueError("SECRET_IN_DELIVERY: 비밀이 포함된 메시지는 전달하지 않는다.")


# ── Codex 전달 ───────────────────────────────────────────────
def _project_mailbox(project: Path) -> Mailbox:
    """Use one runtime mailbox per repository while preserving the caller's source worktree separately."""
    from v7_harness.coord.hook_context import shared_desk
    root = shared_desk(Path(project)) / ".coord" / "mailbox"
    root.mkdir(parents=True, exist_ok=True)
    return Mailbox(root)


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
@contextmanager
def _claude_turn(project_dir: Path | None, timeout: int):
    """Serialize messages through the one persisted Claude conversation, including across processes."""
    if project_dir is None:
        yield
        return
    lock = project_dir / ".coord" / "mailbox" / "delivery" / "claude-session.turn.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout + 5
    fd = None
    while time.monotonic() < deadline:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            break
        except PermissionError:
            # U53-F1: on Windows the previous holder's unlink leaves the lock delete-pending for a moment and
            # O_EXCL then raises PermissionError, not FileExistsError (1 of 30 eight-process runs). Wait, do not crash.
            time.sleep(CLAIM_SLEEP_S)
            continue
        except FileExistsError:
            try:
                stale = time.time() - lock.stat().st_mtime > timeout + 30
            except OSError:
                stale = False
            if stale:
                try:
                    os.rename(lock, lock.with_name(f"{lock.name}.stale-{uuid.uuid4().hex}"))
                except OSError:
                    pass
            time.sleep(CLAIM_SLEEP_S)
    if fd is None:
        raise TimeoutError("CLAUDE_TURN_TIMEOUT")
    with os.fdopen(fd, "wb") as handle:
        handle.write(str(os.getpid()).encode("ascii"))
        handle.flush()
        os.fsync(handle.fileno())
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def _deliver_to_claude(
    message: str,
    *,
    project_dir: Path | None = None,
    runner: Any = None,
    timeout: int = 120,
    allowed_tools: tuple[str, ...] = ("Read",),
) -> DeliverResult:
    try:
        with _claude_turn(project_dir, timeout):
            return _deliver_to_claude_locked(
                message, project_dir=project_dir, runner=runner, timeout=timeout, allowed_tools=allowed_tools
            )
    except TimeoutError as exc:
        return DeliverResult(False, "claude", f"DELIVERY_FAILED:{exc}", (), "")


def _deliver_to_claude_locked(
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

    session_path: Path | None = None
    session_id = ""
    resume = False
    if project_dir:
        session_path = project_dir / ".coord" / "mailbox" / "delivery" / "claude-session.json"
        session_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            state = json.loads(session_path.read_text(encoding="utf-8"))
            session_id = str(state.get("session_id") or "")
            resume = bool(state.get("ready"))
        except (FileNotFoundError, OSError, ValueError, AttributeError):
            state = {}
        if not session_id:
            session_id = str(uuid.uuid4())
            initial = (json.dumps({"session_id": session_id, "ready": False}, sort_keys=True) + "\n").encode("utf-8")
            try:
                fd = os.open(str(session_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                state = json.loads(session_path.read_text(encoding="utf-8"))
                session_id = str(state["session_id"])
                resume = bool(state.get("ready"))
            else:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(initial)
                    handle.flush()
                    os.fsync(handle.fileno())

    argv_list = [claude_bin, "-p", message, "--output-format", "json"]
    if session_id:
        argv_list.extend(["--resume" if resume else "--session-id", session_id])
    for tool in allowed_tools:
        argv_list.extend(["--allowedTools", tool])

    execute = runner or subprocess.run
    # Claude emits UTF-8. Windows' locale is CP949 on this host, so text=True without an explicit encoding loses the
    # reply in subprocess' reader thread even when Claude exits successfully.
    kwargs: dict[str, Any] = dict(capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
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

    if session_path and session_id:
        temporary = session_path.with_suffix(f".tmp-{uuid.uuid4().hex}")
        temporary.write_text(json.dumps({"session_id": session_id, "ready": True}, sort_keys=True) + "\n",
                             encoding="utf-8")
        os.replace(temporary, session_path)
    reply = str(result_text)[:2000]
    try:
        _check_secrets(reply)
    except ValueError:
        return DeliverResult(False, "claude", "DELIVERY_FAILED:SECRET_IN_RESPONSE", tuple(argv_list), "")
    return DeliverResult(True, "claude", "SENT", tuple(argv_list), reply)


def _receipt_output(path: Path) -> str:
    """Return a previously persisted reply; malformed receipts fail closed to an empty reply."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(data.get("output") or "") if isinstance(data, dict) else ""


def _write_receipt(path: Path, payload: dict[str, Any]) -> None:
    """Create one immutable receipt; concurrent attempts get separate names."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _clear_owned_pending(path: Path, owner: str | None) -> None:
    """Remove only the direct-dispatch marker owned by this guard winner."""
    if not owner:
        return
    try:
        if json.loads(path.read_text(encoding="utf-8")).get("owner") == owner:
            path.unlink(missing_ok=True)
    except (OSError, ValueError, AttributeError):
        pass


# ── 통합 전달기 ──────────────────────────────────────────────
# Why 300 s: a live dispatcher holds the guard at most for the Claude CLI timeout (120 s) plus receipt writes; 300 s
# gives 2.5x margin so a slow but live dispatcher is never taken for a crashed one.
GUARD_STALE_S = 300.0
# U83 (Codex REJECT of U49-G1R, 2026-09-29): the recovery lock is an OS byte-range lock on `<guard>.recover`, not an
# exclusively created file aged by mtime. The OS drops it when its holder exits or crashes, so nothing ever steals it by
# age: a holder paused for any length of time keeps it, and the file itself is never unlinked, so no caller can delete
# another holder's lock.
# 50 x 20 ms bounds the claim retry at about 1 s, well above the few ms a concurrent publish holds the file open.
CLAIM_TRIES = 50
CLAIM_SLEEP_S = 0.02
# Release waits for the recovery lock at most 5 s: recovery holds it for milliseconds, so 5 s only runs out when a
# recoverer is paused inside it; the guard is then left for stale recovery, which can delay but never double-dispatch.
RELEASE_WAIT_S = 5.0


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


# U86: the OS lock helpers moved to stream.py, which now locks the same way (imported above).


@contextmanager
def _recover_lock(guard: Path, wait_s: float):
    """Yield True while holding the OS lock on `<guard>.recover`, or False if it was not taken within wait_s."""
    path = guard.with_name(guard.name + ".recover")
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        yield False
        return
    try:
        deadline = time.monotonic() + wait_s
        while not _try_lock(fd):
            if time.monotonic() >= deadline:
                yield False
                return
            time.sleep(CLAIM_SLEEP_S)
        try:
            yield True
        finally:
            try:
                _unlock(fd)
            except OSError:
                pass  # close below releases it anyway
    finally:
        os.close(fd)


def _acquire_guard(guard: Path, box: Mailbox, message_id: str, digest: str) -> int | None:
    """Take the per-message dispatch guard, recovering one left by a crashed dispatcher. None means IN_FLIGHT.

    Recovery runs under the OS recovery lock so the age check and the rename cannot interleave with another
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
    with _recover_lock(guard, 0.0) as held:
        if not held:
            return None  # another recoverer or releaser is working now; this caller's message is already published
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


def _release_guard(guard: Path, owner: str) -> None:
    """Remove the dispatch guard only if this dispatcher still owns it, under the same lock recovery uses.

    U49-G1R (Codex REJECT of G1, 2026-09-27): an unconditional unlink by a dispatcher that outlived GUARD_STALE_S removed
    the new holder's guard, and G1's owner check alone still let a recovery land between the read and the unlink.
    Holding the recovery lock across compare and unlink makes release and recovery mutually exclusive, because recovery
    ages, renames and re-creates the guard only while holding that lock too.
    """
    with _recover_lock(guard, RELEASE_WAIT_S) as held:
        if not held:
            return  # left for stale recovery: a delay, never a second dispatcher
        data = None
        for _ in range(CLAIM_TRIES):  # a Windows sharing violation is transient; do not strand our own guard
            try:
                data = json.loads(guard.read_text(encoding="utf-8"))
                break
            except PermissionError:
                time.sleep(CLAIM_SLEEP_S)
            except (OSError, ValueError):
                return
        if isinstance(data, dict) and data.get("owner") == owner:
            guard.unlink(missing_ok=True)


def _dispatch_count(attempts: Path, message_id: str) -> int:
    """Count earlier dispatch attempts (DISPATCHED or FAILED) for one message; GUARD_RECOVERED receipts do not count.

    Called while holding the claim, so dispatchers of the same id are serialized and the count cannot race. A receipt
    that cannot be read yet (Windows delete-pending) or is not JSON is still counted: it can only be an attempt.
    U49-D2: valid JSON that is not an object (e.g. a list) is counted the same way instead of raising AttributeError.
    """
    count = 0
    for path in attempts.glob(f"{message_id}_*.json") if attempts.is_dir() else ():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        state = data.get("state") if isinstance(data, dict) else None
        if state != "GUARD_RECOVERED":
            count += 1
    return count


def _deliver_unlocked(
    project: Path,
    *,
    message: str,
    actor: str,
    target: str | None = None,
    thread: str = "",
    runner: Any = None,
    pending_owner: str | None = None,
) -> DeliverResult:
    """메시지를 대상 도구에게 직접 전달한다.

    target: "codex" | "claude" | None (자동 판별).
    자동 판별 시 presence를 읽어 ACTIVE인 도구에게 보낸다.
    Codex ACTIVE면 Codex, 아니면 Claude에게 보낸다.

    불변식: 사용자에게 수동 릴레이를 요청하지 않는다.
    """
    _check_secrets(message)
    project = Path(project).resolve()
    box = _project_mailbox(project)
    desk = box.root.parent.parent
    # Stable id makes repeated calls with the same sender and bytes idempotent.
    digest = hashlib.sha256((actor + "\0" + message).encode("utf-8")).hexdigest()
    message_id = "relay_" + digest[:32]
    pending = box.root / "delivery" / "pending" / f"{message_id}.json"
    ack_file = box.ack_dir / f"{message_id}.json"
    if ack_file.is_file():
        _clear_owned_pending(pending, pending_owner)
        return DeliverResult(True, target or "auto", "ACKED", (), "", message_id, digest, str(ack_file))

    # U64 (2026-09-28): coord watch only returns to the shell process that launched it; it cannot start a new AI turn.
    # It may suppress an ACK-only/liveness delivery, but a real delta must use the direct Claude dispatch path.
    if target == "claude":
        from v7_harness.coord.watch import watcher_live
        if watcher_live(desk, "claude") and not _requires_wake(message):
            return DeliverResult(False, "claude", "QUEUED_INTERACTIVE", (), "", message_id, digest,
                                 str(box.inbox_dir / f"{message_id}.json"))
        # U74-D: an explicit ACK_ONLY never spends a paid turn, even with no watcher (global relay rule). The letter
        # is already published; the next session reads it from the inbox.
        if _ACK_RE.search(message.upper()):
            return DeliverResult(False, "claude", "QUEUED_ACK_ONLY", (), "", message_id, digest,
                                 str(box.inbox_dir / f"{message_id}.json"))

    accepted = box.root / "delivery" / "accepted" / f"{message_id}.json"
    if accepted.is_file():
        _clear_owned_pending(pending, pending_owner)
        return DeliverResult(False, target, "DISPATCHED", (), _receipt_output(accepted),
                             message_id, digest, str(accepted))

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
        _clear_owned_pending(pending, pending_owner)
        return DeliverResult(False, target, "IN_FLIGHT", (), "", message_id, digest)

    result: DeliverResult
    try:
        # A contender may have checked before the first sender wrote this
        # receipt, then acquired the claim after the first sender returned it.
        if accepted.is_file():
            return DeliverResult(False, target, "DISPATCHED", (), _receipt_output(accepted),
                                 message_id, digest, str(accepted))
        # The claim serializes competing dispatchers. The original is returned
        # to inbox after the attempt; only recipient coord ack may settle it.
        envelope = f"[UAOS relay id={message_id} digest={digest}]\n{message}"
        if target != "claude":
            envelope += (f"\nAfter processing, run coord ack --id {message_id} for this project. "
                         "The sender keeps this message in the inbox until ACK.")
        if target == "codex":
            if not thread:
                from v7_harness.coord.notify import resolve_thread
                thread = resolve_thread(desk)
            result = (_deliver_to_codex(envelope, thread, runner=runner) if thread else
                      DeliverResult(False, "codex", "NO_THREAD", (), ""))
        elif target == "claude":
            prefix = "[안티그래비티에서 온 대화] " if actor.lower() in ("agy", "antigravity") else (
                "[코덱스에서 온 대화] " if actor.lower() == "codex" else "")
            result = _deliver_to_claude(prefix + envelope, project_dir=project, runner=runner)
        else:
            result = DeliverResult(False, str(target), f"UNKNOWN_TARGET:{target}", (), "")

        attempts = box.root / "delivery" / "attempts"
        receipt = {"message_id": message_id, "digest": digest, "target": target,
                   "state": "DISPATCHED" if result.delivered else "FAILED", "reason": result.reason,
                   "attempt": _dispatch_count(attempts, message_id) + 1, "timestamp_ns": time.time_ns(),
                   "output": result.output}
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
        _clear_owned_pending(pending, pending_owner)
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
    box = _project_mailbox(project)
    desk = box.root.parent.parent
    requested_target = target
    if target is None:
        from v7_harness.coord.presence import read as read_presence
        from v7_harness.coord.watch import watcher_live
        if read_presence(desk, "codex")["state"] == "ACTIVE":
            target = "codex"
        elif read_presence(desk, "claude")["state"] == "ACTIVE" or watcher_live(desk, "claude"):
            target = "claude"
    # U66: the intent marker exists before the inbox letter. A racing watcher waits instead of starting a second
    # paid turn; on failure `_deliver_unlocked` removes it and the same unseen letter becomes the fallback route.
    pending = box.root / "delivery" / "pending" / f"{message_id}.json"
    if target == "claude" and _requires_wake(message) and not pending.is_file():
        try:
            _write_receipt(pending, {"message_id": message_id, "target": "claude", "state": "PENDING"})
        except FileExistsError:
            pass
    # U48-D0 re-review (Claude, 2026-09-27): publish before the guard. A guard left by a crashed dispatcher used to
    # return IN_FLIGHT before any publish, so the message never reached the inbox. Publish is idempotent by id+bytes.
    box.publish(message_id, _payload(actor, message, digest, requested_target))
    if target is None:
        return DeliverResult(False, "mailbox_only", "PUBLISHED", (), "", message_id, digest)
    guard = box.root / "delivery" / "guards" / f"{message_id}.lock"
    guard.parent.mkdir(parents=True, exist_ok=True)
    fd = _acquire_guard(guard, box, message_id, digest)
    if fd is None:
        return DeliverResult(False, target or "mailbox_only", "IN_FLIGHT", (), "", message_id, digest)
    owner = uuid.uuid4().hex
    with os.fdopen(fd, "wb") as handle:
        handle.write(json.dumps({"message_id": message_id, "digest": digest, "actor": actor,
                                 "message": message, "target": target, "owner": owner},
                                ensure_ascii=False).encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    pending_owner = None
    if target == "claude" and _requires_wake(message):
        # The guard winner takes ownership even if another contender created the provisional marker. Guard losers
        # cannot remove it; this closes the last window where a watcher could start a second paid turn.
        pending.parent.mkdir(parents=True, exist_ok=True)
        pending.write_text(json.dumps({"message_id": message_id, "target": "claude", "state": "PENDING",
                                       "owner": owner}, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        pending_owner = owner
    try:
        return _deliver_unlocked(project, message=message, actor=actor, target=target,
                                 thread=thread, runner=runner, pending_owner=pending_owner)
    finally:
        _release_guard(guard, owner)
