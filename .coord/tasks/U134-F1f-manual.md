```contract
work_id: U134-F1f
worker: apply
apply_after: U134-L6
goal: cwd fail-closed validation and fixture alignment for U113/U115 under U134 (U134-F1c)
inputs:
- tests/test_u134_thread_fallback.py sha256=a272923674c458ba9e06fc364f3c69b0276c5415006d931ddab2f005e597d944
- tests/test_u134_judge_counterexamples.py sha256=019608228ca494af4c798d735c066bf6a182401ef5b338d8f7f3dbf265d52ad3
- tests/test_u134_f1b_cwd.py sha256=496a3bbdeceaac1aeb02af5652cbfaf98e0b990825ad6100d29360e593dc5930
- tests/test_u113_desk_truth.py sha256=c8ae91607a946fc8becf49d36c394f5c6f3f8ee1405bc1a7df5b0147bcdf0a96
- tests/test_u115_card_window_route.py sha256=9a4d83a67a2cbc44ec8d52260dbf84a9e9fae91994d0a7a7fb072941d739e75b
allow:
- v7_harness/coord/deliver.py
- tests/test_u113_desk_truth.py
- tests/test_u115_card_window_route.py
acceptance: python -m unittest tests.test_u134_thread_fallback tests.test_u134_judge_counterexamples tests.test_u134_f1b_cwd tests.test_u113_desk_truth tests.test_u114_merge_relay tests.test_u115_card_window_route tests.test_u115_claude_full_session tests.test_u117_watch_wakes_session tests.test_u118_agy_letter_unread
forbidden: production behavior beyond F1b guard; deletion; main edits; promotion; commit/push; U144
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 900
remote_budget_tokens: 0
```

## Work Order: U134-F1f (F1c content re-based on main with F1d applied; acting conductor Claude, Codex LIMITED)

Receipt: U134-F1e FAILED DICTATION_EDIT_SEARCH_NOT_FOUND (EDIT blocks targeted stage base 12a3d75d, not main feb63673).
Fix: whole-file blocks copied byte-exact from F1c stage (Codex-verified 49/49, bundle 08a1f5ad):
deliver.py 6cceeb12, test_u113 9648d9d1, test_u115 4fb1b1cd. No other change.

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


def _digest(actor: str, message: str, card: str = "", window: str | None = None) -> str:
    # U115: a card letter's id also covers its card and window, so the same text routed to another window is a new
    # letter instead of a mailbox collision; without a card the id is exactly today's.
    key = actor + "\0" + message + (f"\0{card}\0{window or ''}" if card else "")
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


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
    session: str = "",
) -> DeliverResult:
    try:
        with _claude_turn(project_dir, timeout):
            return _deliver_to_claude_locked(
                message, project_dir=project_dir, runner=runner, timeout=timeout, allowed_tools=allowed_tools,
                session=session,
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
    session: str = "",
) -> DeliverResult:
    claude_bin = shutil.which("claude")
    if not claude_bin:
        return DeliverResult(False, "claude", "CLI_NOT_FOUND", (), "")

    session_path: Path | None = None
    session_id = ""
    resume = False
    window_cwd = ""
    if session:  # U115: a card window is an existing session; the default delivery session file is left alone
        from v7_harness.coord.windows import claude_session

        (session_id, window_cwd), resume = claude_session(session), True
    elif project_dir:
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
    if window_cwd:  # U115 judge: resume where the window's transcript lives (it may have entered a worktree)
        kwargs["cwd"] = window_cwd

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


def _payload(actor: str, message: str, digest: str, target: str | None, card: str = "",
             window: str | None = None) -> dict[str, Any]:
    """The one published body: the same bytes from every caller, so publish stays idempotent."""
    body = {"kind": "HANDOFF", "actor": actor, "message": message, "digest": digest,
            "requested_target": target or "auto"}
    if card:  # U115: only a card letter carries these keys, so a letter without --card keeps today's bytes
        body.update(card=card, window=window)
    return body


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


def _codex_sessions() -> Path:
    """U134-D: where Codex writes its rollouts; UAOS_CODEX_SESSIONS (presence.CODEX_SESSIONS_ENV) isolates tests."""
    from v7_harness.coord.presence import CODEX_SESSIONS_ENV
    return Path(os.environ.get(CODEX_SESSIONS_ENV) or (Path.home() / ".codex" / "sessions"))


META_LINE_MAX = 256 * 1024
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _read_rollout_meta(path: Path) -> tuple[str, Path | None, str]:
    """Read session_id and canonical cwd from rollout file metadata.

    U134-R F1:
    - Bounded read (max 256 KiB bytes).
    - Requires type == 'session_meta' (rejects event_msg).
    - Every present id key (id, session_id) must be a non-empty string; at least one present; all equal.
    - Strict UUID format check and filename suffix check.
    - Returns (chosen_id, canonical_cwd, status).
    """
    try:
        with path.open("rb") as handle:
            raw_line = handle.readline(META_LINE_MAX + 1)
            if not raw_line or len(raw_line) > META_LINE_MAX:
                return "", None, "THREAD_UNVERIFIED"
            line = raw_line.decode("utf-8", errors="replace")
            data = json.loads(line)
    except (OSError, json.JSONDecodeError):
        return "", None, "THREAD_UNVERIFIED"
    if not isinstance(data, dict) or data.get("type") != "session_meta":
        return "", None, "THREAD_UNVERIFIED"
    payload = data.get("payload")
    if not isinstance(payload, dict):
        return "", None, "THREAD_UNVERIFIED"

    present_ids: list[str] = []
    for key in ("id", "session_id"):
        if key in payload:
            val = payload[key]
            if not isinstance(val, str) or not val.strip():
                return "", None, "THREAD_UNVERIFIED"
            present_ids.append(val.strip())

    if not present_ids:
        return "", None, "THREAD_UNVERIFIED"

    first = present_ids[0]
    if any(pid.lower() != first.lower() for pid in present_ids):
        return "", None, "THREAD_UNVERIFIED"

    chosen_id = first
    if not UUID_RE.fullmatch(chosen_id):
        return "", None, "THREAD_UNVERIFIED"
    if not path.name.lower().endswith(f"-{chosen_id.lower()}.jsonl"):
        return "", None, "THREAD_UNVERIFIED"
    if "cwd" in payload:
        cwd_val = payload["cwd"]
        if not isinstance(cwd_val, str) or not cwd_val.strip():
            return "", None, "THREAD_UNVERIFIED"
        cwd = Path(cwd_val).resolve()
    else:
        cwd = None
    return chosen_id, cwd, "OK"


def _registered_roots(project: Path) -> set[str]:
    """Return canonical checkouts belonging to this repository, including git worktrees.

    U134-R F1:
    - Resolves linked worktree back to main repository without subprocess.
    - Resolves <main>/.git/worktrees/*/gitdir and verifies back-pointers.
    - Normalizes paths with os.path.normcase(str(p)).
    """
    project_res = project.resolve()
    main_repo = project_res
    git_entry = project_res / ".git"

    if git_entry.is_file():
        try:
            content = git_entry.read_text(encoding="utf-8").strip()
            if content.startswith("gitdir:"):
                raw_target = content[7:].strip()
                gitdir_path = Path(raw_target)
                if not gitdir_path.is_absolute():
                    gitdir_path = (project_res / gitdir_path).resolve()
                else:
                    gitdir_path = gitdir_path.resolve()
                if "worktrees" in gitdir_path.parts:
                    p = gitdir_path
                    while p.name != ".git" and p.parent != p:
                        p = p.parent
                    if p.name == ".git":
                        main_repo = p.parent.resolve()
        except OSError:
            pass

    roots = {os.path.normcase(str(project_res)), os.path.normcase(str(main_repo))}
    worktrees_dir = main_repo / ".git" / "worktrees"
    if worktrees_dir.is_dir():
        try:
            for entry in worktrees_dir.iterdir():
                if entry.is_dir():
                    gitdir_file = entry / "gitdir"
                    if gitdir_file.is_file():
                        try:
                            target = gitdir_file.read_text(encoding="utf-8").strip()
                            tpath = Path(target)
                            if not tpath.is_absolute():
                                tpath = (entry / tpath).resolve()
                            else:
                                tpath = tpath.resolve()
                            wt_dir = tpath.parent if tpath.name == ".git" else tpath
                            wt_git = wt_dir / ".git"
                            if wt_git.is_file():
                                back_content = wt_git.read_text(encoding="utf-8").strip()
                                if back_content.startswith("gitdir:"):
                                    bpath = Path(back_content[7:].strip())
                                    if not bpath.is_absolute():
                                        bpath = (wt_dir / bpath).resolve()
                                    else:
                                        bpath = bpath.resolve()
                                    if os.path.normcase(str(bpath)) == os.path.normcase(str(entry.resolve())):
                                        roots.add(os.path.normcase(str(wt_dir.resolve())))
                            elif wt_dir.resolve() == main_repo.resolve():
                                roots.add(os.path.normcase(str(wt_dir.resolve())))
                        except OSError:
                            pass
        except OSError:
            pass

    return roots


def _newest_verified_thread(desk: Path, sessions_dir: Path, exclude_threads: set[str] = ()) -> str:
    """Discover the newest verified thread for this project from up to 12 recent rollouts."""
    if not sessions_dir.is_dir():
        return ""
    reg_roots = _registered_roots(desk)
    candidates = sorted(sessions_dir.glob("*/*/*/rollout-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates[:12]:
        chosen_id, cwd, status = _read_rollout_meta(path)
        if status == "OK" and chosen_id not in exclude_threads:
            if cwd and os.path.normcase(str(cwd.resolve())) in reg_roots:
                return chosen_id
    return ""


def _codex_thread(desk: Path, thread: str) -> tuple[str, dict[str, str], str]:
    """U134-D / U134-R F1: Resolve Codex thread with strict identity and workspace verification.

    Returns (chosen_thread, fallback_dict, status).
    Status is 'DISPATCH' on success, or 'THREAD_UNVERIFIED', 'THREAD_PROJECT_MISMATCH', 'NO_VERIFIED_THREAD'.
    """
    root = _codex_sessions()
    if not thread:
        newest = _newest_verified_thread(desk, root)
        if newest:
            return newest, {}, "DISPATCH"
        return "", {}, "NO_VERIFIED_THREAD"

    if not UUID_RE.fullmatch(thread):
        newest = _newest_verified_thread(desk, root)
        if newest:
            return newest, {"given": thread, "used": newest, "why": "not_uuid"}, "DISPATCH"
        return "", {}, "NO_VERIFIED_THREAD"

    matched = list(root.glob(f"*/*/*/rollout-*-{thread}.jsonl"))
    if not matched:
        newest = _newest_verified_thread(desk, root)
        if newest:
            return newest, {"given": thread, "used": newest, "why": "no_rollout"}, "DISPATCH"
        return "", {}, "NO_VERIFIED_THREAD"

    reg_roots = _registered_roots(desk)
    for mf in matched:
        cid, cwd, status = _read_rollout_meta(mf)
        if status != "OK":
            return "", {}, "THREAD_UNVERIFIED"
        if not cwd or os.path.normcase(str(cwd.resolve())) not in reg_roots:
            return "", {}, "THREAD_PROJECT_MISMATCH"
        return thread, {}, "DISPATCH"

    return "", {}, "THREAD_UNVERIFIED"


def _queue_dir(project: Path, tool: str) -> Path:
    """U134: letters waiting for `tool` to turn ACTIVE live beside the mailbox's other delivery records."""
    return _project_mailbox(Path(project).resolve()).root / "delivery" / "queued" / tool


def _queue_until_active(project: Path, tool: str, *, message_id: str, digest: str, actor: str, message: str,
                        card: str, thread: str) -> DeliverResult:
    """U134-C (2026-10-03): a letter to a LIMITED/ABSENT codex/claude came back `mailbox_only` PUBLISHED with ok=true
    and nothing re-sent it when the tool returned (relay_18758c37 never reached Codex). It is now queued, and the
    tool's next ACTIVE heartbeat with dispatch (presence.mark -> dispatch_queued) sends it."""
    marker = _queue_dir(project, tool) / f"{message_id}.json"
    try:
        _write_receipt(marker, {"message_id": message_id, "actor": actor, "message": message, "card": card,
                                "thread": thread, "attempts": 0})
    except FileExistsError:
        pass  # the same letter sent again stays one queued letter
    return DeliverResult(False, tool, "QUEUED_UNTIL_ACTIVE", (), "", message_id, digest, str(marker))


def queued_letters(project: Path, tool: str) -> list[Path]:
    """U134-B: letters waiting for `tool`, oldest name first; a missing queue is empty (the hook's cheap check)."""
    folder = _queue_dir(project, tool)
    return sorted(folder.glob("relay_*.json")) if folder.is_dir() else []


def dispatch_queued(project: Path, tool: str, *, runner: Any = None) -> list[dict[str, str]]:
    """U134-B: send each letter queued for `tool` once.

    A heartbeat takes a letter by renaming it (atomic; a racing heartbeat gets OSError and skips it), so two
    heartbeats in parallel send it once. The send reuses `_deliver_unlocked` with the queued message id (an empty
    window digests like the None the queue was written with), so the accepted and ack receipts keep it idempotent.
    An unsettled send goes back to the queue; after the last try it is parked as `<message_id>.failed`.
    """
    # Reasons that end a queued letter's trip: sent, already acknowledged, or held for the interactive session.
    settled = ("DISPATCHED", "ACKED", "QUEUED_INTERACTIVE", "QUEUED_ACK_ONLY")
    # One try per hook kind (SessionStart, UserPromptSubmit, PostToolUse) before parking: a letter that keeps failing
    # (no thread, CLI error) must not fire `codex queue` on every heartbeat forever.
    tries = 3
    project = Path(project).resolve()
    desk = _project_mailbox(project).root.parent.parent
    sent: list[dict[str, str]] = []
    for marker in queued_letters(project, tool):
        taking = marker.with_name(f"{marker.stem}.{uuid.uuid4().hex}.taking")
        try:
            os.rename(marker, taking)
        except OSError:
            continue
        try:
            letter = json.loads(taking.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            os.replace(taking, marker.with_suffix(".failed"))
            continue
        card = str(letter.get("card") or "")
        thread = str(letter.get("thread") or "")
        if card:
            from v7_harness.coord.windows import window_for
            thread = window_for(desk, card, tool) or thread  # U115: the card's own window of the now-ACTIVE tool
        result = _deliver_unlocked(project, message=str(letter.get("message") or ""),
                                   actor=str(letter.get("actor") or ""), target=tool, thread=thread,
                                   runner=runner, card=card, window="")
        sent.append({"message_id": str(letter.get("message_id") or marker.stem), "reason": result.reason})
        if result.reason in settled:
            taking.unlink(missing_ok=True)
            continue
        letter["attempts"] = int(letter.get("attempts") or 0) + 1
        taking.write_text(json.dumps(letter, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(taking, marker if letter["attempts"] < tries else marker.with_suffix(".failed"))
    return sent


def _deliver_unlocked(
    project: Path,
    *,
    message: str,
    actor: str,
    target: str | None = None,
    thread: str = "",
    runner: Any = None,
    pending_owner: str | None = None,
    card: str = "",
    window: str = "",
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
    digest = _digest(actor, message, card, window)
    message_id = "relay_" + digest[:32]
    pending = box.root / "delivery" / "pending" / f"{message_id}.json"
    ack_file = box.ack_dir / f"{message_id}.json"
    if ack_file.is_file():
        _clear_owned_pending(pending, pending_owner)
        return DeliverResult(True, target or "auto", "ACKED", (), "", message_id, digest, str(ack_file))

    # U64 (2026-09-28): coord watch only returns to the shell process that launched it; it cannot start a new AI turn.
    # It may suppress an ACK-only/liveness delivery, but a real delta must use the direct Claude dispatch path.
    if target == "claude":
        from v7_harness.coord.watch import watcher_live, watcher_wakes
        # U117: a watcher that wakes its own session takes real deltas too; U64's headless turn stays for the rest.
        if watcher_live(desk, "claude") and (not _requires_wake(message) or watcher_wakes(desk, "claude")):
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
        fallback: dict[str, str] = {}
        if target == "codex":
            if window:  # U115: the card's own Codex thread replaces the default thread
                thread = window
            chosen_thread, fallback, status = _codex_thread(desk, thread)
            if status != "DISPATCH":
                result = DeliverResult(False, "codex", status, (), "")
            else:
                result = _deliver_to_codex(envelope, chosen_thread, runner=runner)
                # Rule 6: retry once on rc != 0 with newest verified thread other than failed one
                if not result.delivered and result.reason.startswith("DELIVERY_FAILED:rc="):
                    alt_thread = _newest_verified_thread(desk, _codex_sessions(), exclude_threads={chosen_thread})
                    if alt_thread:
                        fallback = {"given": chosen_thread, "used": alt_thread, "why": "send_failed"}
                        result = _deliver_to_codex(envelope, alt_thread, runner=runner)
        elif target == "claude":
            prefix = "[안티그래비티에서 온 대화] " if actor.lower() in ("agy", "antigravity") else (
                "[코덱스에서 온 대화] " if actor.lower() == "codex" else "")
            result = _deliver_to_claude(prefix + envelope, project_dir=project, runner=runner, session=window)
        else:
            result = DeliverResult(False, str(target), f"UNKNOWN_TARGET:{target}", (), "")

        attempts = box.root / "delivery" / "attempts"
        receipt = {"message_id": message_id, "digest": digest, "target": target,
                   "state": "DISPATCHED" if result.delivered else "FAILED", "reason": result.reason,
                   "attempt": _dispatch_count(attempts, message_id) + 1, "timestamp_ns": time.time_ns(),
                   "output": result.output, **({"thread_fallback": fallback} if fallback else {})}
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
    card: str = "",
) -> DeliverResult:
    """Serialize the complete publish-to-dispatch transaction per message.

    On Windows, another publisher opening a claimed file can prevent NACK
    from unlinking it. This outer guard prevents same-id callers from touching
    mailbox files while the owner is publishing or dispatching.
    """
    _check_secrets(message)
    digest = _digest(actor, message)
    message_id = "relay_" + digest[:32]
    project = Path(project).resolve()
    box = _project_mailbox(project)
    desk = box.root.parent.parent
    requested_target = target
    queued_for = ""
    if target is None:
        from v7_harness.coord.presence import read as read_presence
        from v7_harness.coord.watch import watcher_live
        if read_presence(desk, "codex")["state"] == "ACTIVE":
            target = "codex"
        elif read_presence(desk, "claude")["state"] == "ACTIVE" or watcher_live(desk, "claude"):
            target = "claude"
    # U113: a relay queued into a LIMITED tool's thread waits there and costs one paid turn per letter when it returns
    # (7 relays piled up in Codex's thread on 2026-10-01); its hooks show the inbox instead (desk delta, U103).
    elif target in ("codex", "claude"):
        from v7_harness.coord.presence import read as read_presence
        if read_presence(desk, target)["state"] in ("LIMITED", "ABSENT"):
            queued_for, target = target, None  # U134-C: queued below until the tool's next ACTIVE turn
    # U115: a card letter goes into the card's window of the resolved target (U114 record). A LIMITED/ABSENT target
    # was resolved to None above, so it gets no window and is queued without one (U113, U134-C).
    window = None
    if card:
        from v7_harness.coord.windows import window_for
        window = window_for(desk, card, target or "")  # a bad card id raises before anything is published
        digest = _digest(actor, message, card, window)
        message_id = "relay_" + digest[:32]
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
    box.publish(message_id, _payload(actor, message, digest, requested_target, card, window))
    if target == "antigravity":
        # U95-A: no CLI wakes Antigravity; its PreInvocation hook names the letter on its next turn (agy_line).
        # U118: a real delta stays unread until a user turn there; say so and name the headless route (user report).
        unread = ("UNREAD until a user turn in Antigravity; for a verdict run `pilot review --reviewer agy` "
                  "(headless, no user)") if _requires_wake(message) else ""
        if unread and actor in ("claude", "codex") and os.environ.get("UAOS_AGY_AUTO", "1") != "0":
            # U120: a headless one-turn answer (U119 live: 27,989 tokens) is mailed back to the sender; a failure,
            # a loop tag or the daily cap keeps the U118 UNREAD route. UAOS_AGY_AUTO=0 opts out.
            from v7_harness.coord.agy_dispatch import dispatch
            row = dispatch(desk, message_id=message_id, actor=actor, message=message, runner=runner or subprocess.run,
                           card=card)
            detail = json.dumps(row, ensure_ascii=False)[:300] if row["state"] == "ANSWERED" else unread
            unread = f"AGY_{row['state']} {detail}"
        return DeliverResult(False, "antigravity", "PUBLISHED", (), unread, message_id, digest)
    if target is None and queued_for:
        return _queue_until_active(project, queued_for, message_id=message_id, digest=digest, actor=actor,
                                   message=message, card=card, thread=thread)
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
                                 thread=thread, runner=runner, pending_owner=pending_owner,
                                 card=card, window=window or "")
    finally:
        _release_guard(guard, owner)
===END===

===FILE: tests/test_u113_desk_truth.py===
"""U113: the desk tells the truth about who can take a letter now, and no letter waits in a LIMITED tool's thread.

Receipts (2026-10-01):
- Codex was LIMITED (usage limit until 10-04 02:35), yet `coord deliver --target codex` ran `codex queue` for every
  letter; 7 relays piled up in Codex's thread, each one a paid Codex turn (~140k context) when it returns. A returning
  tool already sees the inbox through its hooks (desk delta, U103), so a LIMITED or ABSENT target gets the mailbox only.
- The desk said `antigravity=UNKNOWN` while Antigravity was open and had answered three hours earlier. An expired
  heartbeat is not "unknown": the desk now names it `IDLE(<age>)`; UNKNOWN stays for a tool never seen. Routing does
  not change: an idle tool still does not conduct (fail closed, U45).
Fixed acceptance written by the judge (claude) first.
"""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import presence
from v7_harness.coord.deliver import deliver
from v7_harness.coord.hook_context import agy_line, brief_line


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, command, **_kw):
        self.calls.append(command)
        raise OSError("codex not installed here")


class _Isolated(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        self.sessions = Path(self._tmp.name) / "codex-sessions"  # never the PC's real Codex logs
        self.sessions.mkdir()
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(self.sessions)})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()


class NoLetterWaitsInALimitedThread(_Isolated):
    def test_limited_or_absent_codex_gets_the_mailbox_only(self):
        for n, state in enumerate(("LIMITED", "ABSENT")):
            presence.mark(self.project, "codex", state)
            runner = _Recorder()
            with mock.patch("v7_harness.coord.deliver.shutil.which", return_value="codex"):
                result = deliver(self.project, message=f"U113 {state}", actor="claude", target="codex",
                                 runner=runner, thread="t1")
            # U134-C: still no dispatch while LIMITED/ABSENT, but the letter is queued for the next ACTIVE turn.
            self.assertEqual(("codex", "QUEUED_UNTIL_ACTIVE"), (result.target, result.reason), state)
            self.assertEqual([], runner.calls, state)
            self.assertTrue((self.project / ".coord" / "mailbox" / "inbox" / f"{result.message_id}.json").is_file())

    def test_active_codex_is_still_dispatched(self):
        presence.mark(self.project, "codex", "ACTIVE")
        runner = _Recorder()
        thread_id = "0199cccc-0000-7000-8000-000000000003"
        day = self.sessions / "2026" / "10" / "03"
        day.mkdir(parents=True, exist_ok=True)
        path = day / f"rollout-2026-10-03T06-00-00-{thread_id}.jsonl"
        path.write_text(json.dumps({"type": "session_meta", "payload": {"id": thread_id, "session_id": thread_id, "cwd": str(self.project)}}) + "\n", encoding="utf-8")
        with mock.patch("v7_harness.coord.deliver.shutil.which", return_value="codex"):
            deliver(self.project, message="U113 active", actor="claude", target="codex", runner=runner, thread=thread_id)
        self.assertEqual(1, len(runner.calls))
        self.assertIn("queue", runner.calls[0])


class DeskNamesIdleTools(_Isolated):
    def _desk(self):
        return {tool: presence.read(self.project, tool) for tool in presence.SUCCESSION}

    def test_expired_heartbeat_reads_idle_with_its_age_and_never_seen_reads_unknown(self):
        presence.mark(self.project, "antigravity", "ACTIVE", ttl_s=3600, now=time.time() - 3 * 3600 - 60)
        presence.mark(self.project, "claude", "ACTIVE")
        line = brief_line(self.project, self._desk())
        self.assertIn("antigravity=IDLE(3h)", line)
        self.assertIn("claude=ACTIVE", line)
        self.assertIn("codex=UNKNOWN", line)

    def test_antigravity_hook_line_uses_the_same_labels(self):
        presence.mark(self.project, "codex", "ACTIVE", ttl_s=60, now=time.time() - 30 * 60)
        line = agy_line(self.project, self._desk(), "{}")
        self.assertIn("codex=IDLE(30m)", line)  # the age counts from the last heartbeat, not from its expiry

    def test_desk_label_words(self):
        now = time.time()
        self.assertEqual("ACTIVE", presence.desk_label({"state": "ACTIVE"}, now))
        self.assertEqual("LIMITED", presence.desk_label({"state": "LIMITED", "observed_at": None}, now))
        self.assertEqual("UNKNOWN", presence.desk_label({"state": "UNKNOWN", "observed_at": None}, now))
        presence.mark(self.project, "claude", "ACTIVE", ttl_s=60, now=now - 125 * 60)
        self.assertEqual("IDLE(2h)", presence.desk_label(presence.read(self.project, "claude", now=now), now))
        presence.mark(self.project, "claude", "ACTIVE", ttl_s=60, now=now - 5 * 60)
        self.assertEqual("IDLE(5m)", presence.desk_label(presence.read(self.project, "claude", now=now), now))

    def test_idle_still_does_not_conduct(self):
        presence.mark(self.project, "codex", "ACTIVE", ttl_s=60, now=time.time() - 7200)
        presence.mark(self.project, "claude", "ACTIVE")
        self.assertEqual("UNKNOWN", presence.conductor(self._desk())["conductor"])


class HarnessOnlyWorkersWatchTheStage(unittest.TestCase):
    """U113-D a001 was blocked as EXTERNAL_WRITE for `~/.codex/config.toml`: the running Codex app rewrote its own
    config while the local model answered (U106-A2-agy: the Claude app's settings.json). A local or apply worker never
    touches the file system (the harness writes the stage), so home and temp watches catch only other apps there.
    A worker with tools (agy, claude, lane, cascade with escalation) keeps every watch."""

    def test_local_and_apply_watch_only_the_stage(self):
        from v7_harness.cli import mandatory_watch_roots
        with tempfile.TemporaryDirectory() as d:
            work, source = Path(d) / ".coord", Path(d) / "src"
            for worker in ("local", "apply"):
                self.assertEqual([(work / "stage").resolve()], mandatory_watch_roots(work, source, worker), worker)
            for worker in ("agy", "claude", "lane", "cascade"):
                self.assertIn(Path.home().resolve(), mandatory_watch_roots(work, source, worker), worker)
            self.assertIn(Path.home().resolve(), mandatory_watch_roots(work, source))  # default stays strict


if __name__ == "__main__":
    unittest.main()
===END===

===FILE: tests/test_u115_card_window_route.py===
"""U115: a letter about a card goes into that card's window.

Receipt (2026-10-01): U114 opened one named window per card in each tool (`.coord/windows/<card>.json`), but
`coord deliver` still dropped every letter into the tool's default thread, so a card's window never heard about its
own card. `coord deliver --card U##` now dispatches into the window recorded for the resolved target tool:
codex -> `codex queue --thread <window>`, claude -> `claude -p ... --resume <window>`, antigravity -> mailbox only with
the window recorded. Without `--card`, or without a window, behaviour is exactly today's. A LIMITED/ABSENT target stays
mailbox-only (U113) even when a window exists. Fixed acceptance written by the judge (claude) first; no test here
starts a paid session (fake runners, fake `shutil.which`, isolated Codex session logs).
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from v7_harness.cli import build_parser
from v7_harness.coord import presence
from v7_harness.coord.deliver import deliver


class _Runner:
    """Records argv; answers like a successful CLI (claude JSON reply, codex queue ok)."""

    def __init__(self):
        self.calls = []

    def __call__(self, command, **_kw):
        self.calls.append(list(command))
        return SimpleNamespace(returncode=0, stdout=json.dumps({"result": "ok"}), stderr="")


class _Isolated(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        self.sessions = Path(self._tmp.name) / "codex-sessions"  # never the PC's real Codex logs
        self.sessions.mkdir()
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(self.sessions)})
        self._env.start()
        self._which = mock.patch("v7_harness.coord.deliver.shutil.which", side_effect=lambda name: name)
        self._which.start()

    def tearDown(self):
        self._which.stop()
        self._env.stop()
        self._tmp.cleanup()

    def _window(self, card, **ids):
        path = self.project / ".coord" / "windows" / f"{card}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        tools = {tool: {"id": window_id, "opened_at": 0} for tool, window_id in ids.items()}
        path.write_text(json.dumps({"card": card, "title": f"[{card}] t", "tools": tools}), encoding="utf-8")

    def _payload(self, result):
        letter = self.project / ".coord" / "mailbox" / "inbox" / f"{result.message_id}.json"
        return json.loads(letter.read_text(encoding="utf-8"))["payload"]

    @staticmethod
    def _after(argv, flag):
        return argv[argv.index(flag) + 1]


class CodexWindow(_Isolated):
    def test_card_with_a_codex_window_queues_into_that_thread(self):
        presence.mark(self.project, "codex", "ACTIVE")
        win_thread = "0199aaaa-0000-7000-8000-000000000001"
        def_thread = "0199bbbb-0000-7000-8000-000000000002"
        day = self.sessions / "2026" / "10" / "03"
        day.mkdir(parents=True, exist_ok=True)
        for tid in (win_thread, def_thread):
            (day / f"rollout-2026-10-03T06-00-00-{tid}.jsonl").write_text(
                json.dumps({"type": "session_meta", "payload": {"id": tid, "session_id": tid, "cwd": str(self.project)}}) + "\n",
                encoding="utf-8",
            )
        self._window("U115", codex=win_thread)
        runner = _Runner()
        result = deliver(self.project, message="U115 codex window", actor="claude", target="codex",
                         thread=def_thread, runner=runner, card="U115")
        self.assertEqual(1, len(runner.calls))
        self.assertIn("queue", runner.calls[0])
        self.assertEqual(win_thread, self._after(runner.calls[0], "--thread"))
        payload = self._payload(result)
        self.assertEqual(("U115", win_thread), (payload["card"], payload["window"]))

    def test_without_card_or_without_a_window_the_default_thread_is_used(self):
        presence.mark(self.project, "codex", "ACTIVE")
        win_thread = "0199aaaa-0000-7000-8000-000000000001"
        def_thread = "0199bbbb-0000-7000-8000-000000000002"
        day = self.sessions / "2026" / "10" / "03"
        day.mkdir(parents=True, exist_ok=True)
        for tid in (win_thread, def_thread):
            (day / f"rollout-2026-10-03T06-00-00-{tid}.jsonl").write_text(
                json.dumps({"type": "session_meta", "payload": {"id": tid, "session_id": tid, "cwd": str(self.project)}}) + "\n",
                encoding="utf-8",
            )
        self._window("U115", codex=win_thread)
        for n, card in enumerate(("", "U999")):
            runner = _Runner()
            result = deliver(self.project, message=f"U115 default {n}", actor="claude", target="codex",
                             thread=def_thread, runner=runner, card=card)
            self.assertEqual(def_thread, self._after(runner.calls[0], "--thread"), card)
            payload = self._payload(result)
            if card:
                self.assertEqual(("U999", None), (payload["card"], payload.get("window")))
            else:  # no --card: today's payload bytes, unchanged
                self.assertNotIn("card", payload)
                self.assertNotIn("window", payload)


class ClaudeWindow(_Isolated):
    def test_card_with_a_claude_window_resumes_that_session(self):
        presence.mark(self.project, "claude", "ACTIVE")
        self._window("U115", claude="abc12345def")
        runner = _Runner()
        result = deliver(self.project, message="U115 claude window ACTIONABLE_DELTA", actor="codex",
                         target="claude", runner=runner, card="U115")
        self.assertEqual(1, len(runner.calls))
        argv = runner.calls[0]
        self.assertEqual("abc12345def", self._after(argv, "--resume"))
        self.assertNotIn("--session-id", argv)
        # The default delivery session is not touched by a window letter.
        self.assertFalse((self.project / ".coord" / "mailbox" / "delivery" / "claude-session.json").exists())
        self.assertEqual("abc12345def", self._payload(result)["window"])

    def test_without_card_claude_keeps_the_default_delivery_session(self):
        presence.mark(self.project, "claude", "ACTIVE")
        self._window("U115", claude="abc12345def")
        runner = _Runner()
        deliver(self.project, message="U115 claude default ACTIONABLE_DELTA", actor="codex", target="claude",
                runner=runner)
        argv = runner.calls[0]
        self.assertIn("--session-id", argv)
        self.assertNotIn("abc12345def", argv)


class AntigravityWindow(_Isolated):
    def test_antigravity_stays_mailbox_only_and_records_the_window(self):
        presence.mark(self.project, "antigravity", "ACTIVE")
        self._window("U115", antigravity="conv-1")
        runner = _Runner()
        result = deliver(self.project, message="U115 agy window", actor="claude", target="antigravity",
                         runner=runner, card="U115")
        self.assertEqual(("antigravity", "PUBLISHED"), (result.target, result.reason))
        self.assertEqual([], runner.calls)
        payload = self._payload(result)
        self.assertEqual(("U115", "conv-1"), (payload["card"], payload["window"]))


class LimitedTargetIgnoresTheWindow(_Isolated):
    def test_limited_or_absent_target_with_a_window_gets_the_mailbox_only(self):
        self._window("U115", codex="thr-window", claude="abc12345def")
        for tool in ("codex", "claude"):
            for state in ("LIMITED", "ABSENT"):
                presence.mark(self.project, tool, state)
                runner = _Runner()
                result = deliver(self.project, message=f"U115 {tool} {state} ACTIONABLE_DELTA", actor="claude",
                                 target=tool, runner=runner, card="U115")
                # U134-C: queued for the tool's next ACTIVE turn instead of a bare mailbox_only; still no dispatch.
                self.assertEqual((tool, "QUEUED_UNTIL_ACTIVE"), (result.target, result.reason), (tool, state))
                self.assertEqual([], runner.calls, (tool, state))
                payload = self._payload(result)
                self.assertEqual("U115", payload["card"])
                self.assertIsNone(payload.get("window"), (tool, state))


class CardIdAndCli(_Isolated):
    def test_bad_card_id_is_refused_before_anything_is_published(self):
        presence.mark(self.project, "codex", "ACTIVE")
        runner = _Runner()
        with self.assertRaises(ValueError):
            deliver(self.project, message="U115 bad card", actor="claude", target="codex", thread="t",
                    runner=runner, card="../x")
        self.assertEqual([], runner.calls)
        inbox = self.project / ".coord" / "mailbox" / "inbox"
        self.assertEqual([], list(inbox.glob("*.json")) if inbox.is_dir() else [])

    def test_cli_deliver_accepts_card_and_passes_it(self):
        args = build_parser().parse_args(["coord", "deliver", "--project", str(self.project), "--actor", "claude",
                                          "--target", "codex", "--message", "hi", "--card", "U115"])
        self.assertEqual("U115", args.card)
        seen = {}

        def fake(project, **kw):
            seen.update(kw)
            return SimpleNamespace(target="codex", reason="DISPATCHED", message_id="m", digest="d", receipt="",
                                   output="")

        with mock.patch("v7_harness.coord.deliver.deliver", side_effect=fake), \
                mock.patch("builtins.print"):
            self.assertEqual(0, args.func(args))
        self.assertEqual("U115", seen["card"])
        no_card = build_parser().parse_args(["coord", "deliver", "--actor", "claude", "--message", "hi"])
        self.assertEqual("", no_card.card)


if __name__ == "__main__":
    unittest.main()
===END===

