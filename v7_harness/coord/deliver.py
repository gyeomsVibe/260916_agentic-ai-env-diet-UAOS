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
from datetime import datetime
from pathlib import Path
from typing import Any

from v7_harness.coord.stream import SECRET_PATTERNS, _try_lock, _unlock
from v7_harness.coord.mailbox import Mailbox


AGY_APP_HOME_ENV = "UAOS_AGY_APP_HOME"  # tests point this at a fixture; default ~/.gemini/antigravity


REPLACE_TRIES = 20  # Windows refuses os.replace while another process replaces the same file; 20 x 50 ms = 1 s


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
# U141-B: quoted data is never an instruction. Fenced blocks (``` or ~~~, an unclosed fence runs to the end) go first,
# then "...", curly quotes, 'single' quotes, `code` and "> " reply lines are blanked before the token scan. A single
# quote counts only with no word character outside it, so apostrophes (it's, tools') never open a span (U141-B2 REWORK).
_FENCE_RE = re.compile(r"^[ \t]*(```|~~~).*?(?:^[ \t]*\1[^\n]*$|\Z)", re.MULTILINE | re.DOTALL)
_QUOTED_RE = re.compile(r'"[^"\n]*"|“[^”\n]*”|(?<![\w\'])\'[^\'\n]*\'(?!\w)|`[^`\n]*`|^[ \t]*>.*$', re.MULTILINE)
DELTA_LIMIT = 200  # an inferred delta is the hook's one-line summary; the full text stays in `message`


def _digest(actor: str, message: str, card: str = "", window: str | None = None,
            target: str | None = None, fields: dict[str, Any] | None = None) -> str:
    # U115: a card letter's id also covers its card and window, so the same text routed to another window is a new
    # letter instead of a mailbox collision; without a card the id is exactly today's.
    key = actor + "\0" + message + (f"\0{card}\0{window or ''}" if card else "")
    # U141-B: every structured field stored in the payload, explicit or inferred, joins the id (v3). A letter stored
    # before inference existed (v2, no fields) and its inferred retry are then two ids, never a collision or a shared
    # ACK (U141-B2 REWORK). Without fields the v2/legacy ids stay exactly as published.
    if fields:
        key = json.dumps(["uaos-relay-v3", actor, message, card, window or "" if card else "", target, fields],
                         ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    # Explicit destination is payload identity; None preserves legacy auto IDs.
    elif target is not None:
        key = json.dumps(["uaos-relay-v2", actor, message, card, window or "" if card else "", target],
                         ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _requires_wake(message: str) -> bool:
    """Only a real delta may spend a paid turn; ACK_ONLY, negated, incidental or quoted tokens never do."""
    upper = _QUOTED_RE.sub(" ", _FENCE_RE.sub(" ", message)).upper()
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
             window: str | None = None, *, wake_class: str | None = None, verdict_requested: bool | None = None,
             verdict: str | None = None, delta: str | None = None) -> dict[str, Any]:
    """The one published body: the same bytes from every caller, so publish stays idempotent."""
    body = {"kind": "HANDOFF", "actor": actor, "message": message, "digest": digest,
            "requested_target": target or "auto"}
    if card:  # U115: only a card letter carries these keys, so a letter without --card keeps today's bytes
        body.update(card=card, window=window)
    # U141-A: the structured wake fields the watcher classifies. They are written only when given, so an untagged
    # letter keeps today's bytes and stays LEGACY.
    for key, value in (("wake_class", wake_class), ("verdict_requested", verdict_requested), ("verdict", verdict),
                       ("delta", delta)):
        if value is not None:
            body[key] = value
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


# U147: text that a tool, not 윤겸스, puts into a Codex thread as a user turn: injected AGENTS.md, app context blocks
# (<...>), and UAOS relays and sentinel data (seen in the 2026-10-04 rollouts).
# U163 (relay_3ce52b3d): the wrappers _deliver_unlocked puts on a relayed letter are injected text too.
INJECTED_PREFIXES = ("# AGENTS.md", "<", "[UAOS relay", "[DATA]", "[안티그래비티에서 온 대화]", "[코덱스에서 온 대화]",
                     "[클로드에게서 온 대화]")


def last_human_input(path: Path) -> str:
    """U147: ISO timestamp of the last user turn 윤겸스 typed in a Codex rollout, '' when there is none.

    The newest-written rollout is not the user's window: a background Codex thread that answers relays is written on
    every letter, stays newest, and pulled every later letter away from the window 윤겸스 watched (2026-10-04,
    relay_54d2ee83 went to 01a1006f, not 01a102e7). The window a human last typed in is the one the user reads.
    """
    last = ""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if '"role":"user"' not in line and '"role": "user"' not in line:
                    continue  # cheap filter: four 1-4 MiB rollouts scanned in 0.05 s (2026-10-04)
                try:
                    data = json.loads(line)
                except ValueError:
                    continue
                payload = data.get("payload") if isinstance(data, dict) else None
                if not isinstance(payload, dict) or payload.get("role") != "user":
                    continue
                content = payload.get("content")
                text = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict)) \
                    if isinstance(content, list) else ""
                if text.strip() and not text.lstrip().startswith(INJECTED_PREFIXES):
                    last = str(data.get("timestamp") or last)
    except OSError:
        return ""
    return last


# U147-D: the guessed window is only a bootstrap. Any truncated candidate list starves the user's window: newest 12
# (relay_6dfa9184) and a 7-day window capped at 500 (relay_ef4ac44f) both lost it to newer relay-only threads, and a
# day cutoff drops a quiet desk. The guess therefore reads every rollout or none: above ROUTE_SCAN_MAX rollouts it
# fails closed and only the designated user desk routes. 226 rollouts existed on 2026-10-04, one first line each.
ROUTE_SCAN_MAX = 500


def _iso_epoch(stamp: str) -> float:
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return 0.0


def verified_rollouts(desk: Path, sessions_dir: Path, exclude_threads: set[str] = ()) -> tuple[list[tuple[str, Path]], bool]:
    """U147-D: ((thread, rollout) of this project's verified Codex threads, newest-written first; overflow).

    overflow is True when more than ROUTE_SCAN_MAX rollouts exist; the list is then empty, never a truncated guess.
    """
    if not sessions_dir.is_dir():
        return [], False
    stamped = []
    for path in sessions_dir.glob("*/*/*/rollout-*.jsonl"):
        try:
            stamped.append((path.stat().st_mtime, path))
        except OSError:
            continue
    if len(stamped) > ROUTE_SCAN_MAX:
        return [], True
    reg_roots = _registered_roots(desk)
    verified: list[tuple[str, Path]] = []
    for _mtime, path in sorted(stamped, key=lambda item: item[0], reverse=True):
        chosen_id, cwd, status = _read_rollout_meta(path)
        if status == "OK" and chosen_id not in exclude_threads:
            if cwd and os.path.normcase(str(cwd.resolve())) in reg_roots:
                verified.append((chosen_id, path))
    return verified, False


def _newest_verified_thread(desk: Path, sessions_dir: Path, exclude_threads: set[str] = ()) -> str:
    """Bootstrap guess of the user's verified thread when no user desk is designated; '' above ROUTE_SCAN_MAX.

    U147: among verified threads, the one 윤겸스 typed in last wins; with no human turn anywhere, the newest-written.
    U147-R: a rollout's last human turn is never later than its write time, so the newest-first scan stops at the
    first rollout written before the best human turn found; with every rollout listed, that stop is exact.
    """
    verified, _overflow = verified_rollouts(desk, sessions_dir, exclude_threads)
    if not verified:
        return ""
    best_stamp, best_epoch, best_id = "", 0.0, verified[0][0]
    for chosen_id, path in verified:  # newest-written first, so a tie keeps the newest-written thread
        try:
            if best_stamp and path.stat().st_mtime < best_epoch:
                break
        except OSError:
            continue
        stamp = last_human_input(path)
        if stamp > best_stamp:  # ISO-8601 UTC strings of one format sort by time
            best_stamp, best_epoch, best_id = stamp, _iso_epoch(stamp), chosen_id
    return best_id


def _codex_thread(desk: Path, thread: str) -> tuple[str, dict[str, str], str]:
    """U134-D / U134-R F1: Resolve Codex thread with strict identity and workspace verification.

    Returns (chosen_thread, fallback_dict, status).
    Status is 'DISPATCH' on success, or 'THREAD_UNVERIFIED', 'THREAD_PROJECT_MISMATCH', 'NO_VERIFIED_THREAD',
    'USER_DESK_STALE' (U147-D).
    U147-D: with no usable explicit thread, the designated user desk routes; a designated desk that fails
    verification fails closed instead of falling back to a guess. Only an undesignated desk uses the bootstrap guess.
    """
    root = _codex_sessions()
    why = ""
    if thread and not UUID_RE.fullmatch(thread):
        why = "not_uuid"
    elif thread and not list(root.glob(f"*/*/*/rollout-*-{thread}.jsonl")):
        why = "no_rollout"
    elif thread:
        status = _verify_thread(desk, root, thread)
        return (thread, {}, status) if status == "DISPATCH" else ("", {}, status)

    desk_state, designated = user_desk_state(desk, "codex")
    if desk_state == "INVALID":
        return "", {"why": "user_desk_invalid"}, "USER_DESK_STALE"
    if designated:
        status = _verify_thread(desk, root, designated)
        if status != "DISPATCH":
            return "", {"designated": designated, "why": status}, "USER_DESK_STALE"
        return designated, ({"given": thread, "used": designated, "why": why} if why else {}), "DISPATCH"
    newest = _newest_verified_thread(desk, root)
    if newest:
        return newest, ({"given": thread, "used": newest, "why": why} if why else {}), "DISPATCH"
    return "", {}, "NO_VERIFIED_THREAD"


def _verify_thread(desk: Path, root: Path, thread: str) -> str:
    """U134-R F1 strict identity: a UUID whose rollout names itself and a cwd inside this project."""
    if not UUID_RE.fullmatch(thread):
        return "THREAD_UNVERIFIED"
    matched = list(root.glob(f"*/*/*/rollout-*-{thread}.jsonl"))
    if not matched:
        return "THREAD_UNVERIFIED"
    cid, cwd, status = _read_rollout_meta(matched[0])
    if status != "OK" or cid != thread:
        return "THREAD_UNVERIFIED"
    if not cwd or os.path.normcase(str(cwd.resolve())) not in _registered_roots(desk):
        return "THREAD_PROJECT_MISMATCH"
    return "DISPATCH"


# U147-D designated user desk, the window 윤겸스 types in, per tool:
# - registered: by the tool's UserPromptSubmit hook when the prompt is human-typed (not INJECTED_PREFIXES), so it
#   follows the user to a new window on their next prompt; `register_user_desk` is also callable directly.
# - stored: `.coord/presence/user_desk_<tool>.json`, one file per tool so two tools' hooks never overwrite each other;
#   written by temp file + os.replace, so a reader sees the old or the new record, never half of one.
# - verified at every delivery (`_verify_thread`); a stale desk (rollout gone, other project) fails closed as
#   USER_DESK_STALE and the letter stays in the mailbox until the next human prompt registers a live desk.
USER_DESK_TOOLS = ("codex", "claude", "antigravity")


def user_desk_path(project: Path, tool: str) -> Path:
    return Path(project) / ".coord" / "presence" / f"user_desk_{tool}.json"


def user_desk_state(project: Path, tool: str) -> tuple[str, str]:
    """U147-D: ("ABSENT", "") when no record exists, ("OK", thread), or ("INVALID", "") for a record that exists but
    cannot be read or holds no UUID. Only ABSENT allows the bootstrap guess (Codex relay_48fb8d38: a broken record
    must not silently hand a designated desk's letters to a guessed window)."""
    path = user_desk_path(project, tool)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "ABSENT", ""
    except (OSError, ValueError):
        return "INVALID", ""
    try:
        data = json.loads(text)
    except ValueError:
        return "INVALID", ""
    thread = data.get("thread") if isinstance(data, dict) else None
    if isinstance(thread, str) and UUID_RE.fullmatch(thread):
        return "OK", thread
    return "INVALID", ""


def read_user_desk(project: Path, tool: str) -> str:
    return user_desk_state(project, tool)[1]


def is_human_prompt(prompt: object) -> bool:
    return isinstance(prompt, str) and bool(prompt.strip()) and not prompt.lstrip().startswith(INJECTED_PREFIXES)


def register_user_desk(project: Path, tool: str, thread: str, *, source: str) -> bool:
    if tool not in USER_DESK_TOOLS or not isinstance(thread, str) or not UUID_RE.fullmatch(thread):
        return False
    if read_user_desk(project, tool) == thread:
        return True  # every prompt in the same window would otherwise rewrite the record
    path = user_desk_path(project, tool)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    temp.write_text(json.dumps({"thread": thread, "at": time.time(), "source": source}), encoding="utf-8")
    for _attempt in range(REPLACE_TRIES):
        try:
            os.replace(temp, path)
            return True
        except PermissionError:
            time.sleep(0.05)
    temp.unlink(missing_ok=True)
    return False


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
                                "thread": thread, "attempts": 0, "digest": digest})
    except FileExistsError:
        pass  # the same letter sent again stays one queued letter
    return DeliverResult(False, tool, "QUEUED_UNTIL_ACTIVE", (), "", message_id, digest, str(marker))


def _park_failed(source_file: Path, message_id: str, queue_dir: Path) -> Path:
    """U134-F2: park a corrupt or exceeded-retries letter as .failed without overwriting existing evidence."""
    target = queue_dir / f"{message_id}.failed"
    # Decision: never overwrite existing .failed evidence; use unique hex suffix if default name is taken
    if target.exists():
        target = queue_dir / f"{message_id}.{uuid.uuid4().hex}.failed"
    os.replace(source_file, target)
    return target


def queued_letters(project: Path, tool: str) -> list[Path]:
    """U134-B: letters waiting for `tool`, oldest name first; a missing queue is empty (the hook's cheap check).
    U134-F2: collect letter ids from both <id>.json markers and orphan <id>.<hex>.taking files, each id once."""
    folder = _queue_dir(project, tool)
    if not folder.is_dir():
        return []
    ids: set[str] = set()
    for p in folder.iterdir():
        if not p.is_file():
            continue
        if p.name.endswith(".json"):
            ids.add(p.stem)
        elif p.name.endswith(".taking"):
            # Decision: <id>.<hex>.taking -> extract <id> (first segment before the dot)
            ids.add(p.name.split(".")[0])
    # Decision: build list of marker paths so each id is processed once, in name order
    return [folder / f"{letter_id}.json" for letter_id in sorted(ids)]


def dispatch_queued(project: Path, tool: str, *, runner: Any = None) -> list[dict[str, str]]:
    """U134-B/F2: send each letter queued for `tool` once under a per-letter OS lock with scoped crash recovery.

    Documented risk: a crash after the remote send but before the accepted receipt can duplicate one send.

    A heartbeat takes each letter under a per-letter non-blocking OS lock (<id>.lock), held across the rename,
    send, and settle. A live owner keeps the lock even if paused, preventing stolen letters. If an orphan .taking
    exists under the lock, the previous owner is dead, so it is recovered along with any claimed mailbox entry.
    An unsettled send goes back to the queue without incrementing attempts if IN_FLIGHT, or increments attempts
    and parks as .failed after 3 tries.
    """
    # Reasons that end a queued letter's trip: sent, already acknowledged, or held for the interactive session.
    settled = ("DISPATCHED", "ACKED", "QUEUED_INTERACTIVE", "QUEUED_ACK_ONLY")
    # One try per hook kind (SessionStart, UserPromptSubmit, PostToolUse) before parking: a letter that keeps failing
    # (no thread, CLI error) must not fire `codex queue` on every heartbeat forever.
    # 3: max retries per hook kind before parking to failed
    tries = 3
    project = Path(project).resolve()
    box = _project_mailbox(project)
    desk = box.root.parent.parent
    folder = _queue_dir(project, tool)
    sent: list[dict[str, str]] = []

    for marker in queued_letters(project, tool):
        message_id = marker.stem
        lock_file = folder / f"{message_id}.lock"
        # Decision: per-letter OS lock. Open <message_id>.lock and take a non-blocking lock.
        # Decision: never unlink .lock file; the OS automatically releases locks on process exit/termination.
        try:
            fd = os.open(lock_file, os.O_CREAT | os.O_RDWR)
        except OSError:
            continue

        locked = False
        try:
            if not _try_lock(fd):
                # Decision: busy lock means a live owner has it (even if paused); skip to next letter.
                continue
            locked = True

            # Decision: letter claim and orphan recovery under the per-letter lock.
            taking_files = sorted(folder.glob(f"{message_id}.*.taking"))
            is_orphan = False
            taking: Path
            if taking_files:
                # Decision: holding the lock while an orphan .taking exists proves its owner is dead. Adopt it.
                is_orphan = True
                # Judge fix (U134-F2a): adopt the oldest orphan only and delete nothing; the contract forbids deletion.
                taking = taking_files[0]
            elif marker.is_file():
                taking = marker.with_name(f"{message_id}.{uuid.uuid4().hex}.taking")
                try:
                    os.rename(marker, taking)
                except OSError:
                    continue
            else:
                # Neither taking nor marker exists; already settled or removed
                continue

            if is_orphan:
                # Decision: scoped mailbox recovery for THIS message id: if claimed and inbox is absent, move back to inbox.
                # Do not call box.recover_stale_claims or touch any other message id.
                claims = sorted(box.claimed_dir.glob(f"{message_id}_*.json"))
                if claims:
                    inbox_file = box.inbox_dir / f"{message_id}.json"
                    # Judge fix (U134-F2a): only move one claim back, never delete a claim (another holder may own it).
                    if not inbox_file.is_file():
                        os.replace(claims[0], inbox_file)
                # Decision: write an attempt receipt with state QUEUE_CLAIM_RECOVERED under delivery/attempts/
                attempts_dir = box.root / "delivery" / "attempts"
                attempts_dir.mkdir(parents=True, exist_ok=True)
                _write_receipt(
                    attempts_dir / f"{message_id}_{uuid.uuid4().hex}.json",
                    {
                        "message_id": message_id,
                        "state": "QUEUE_CLAIM_RECOVERED",
                        "timestamp_ns": time.time_ns(),
                    },
                )

            # Decision: read letter from taking file; handle corrupt markers without overwriting evidence
            try:
                letter = json.loads(taking.read_text(encoding="utf-8"))
                if not isinstance(letter, dict):
                    raise ValueError("letter is not a json object")
            except (OSError, ValueError):
                _park_failed(taking, message_id, folder)
                continue

            card = str(letter.get("card") or "")
            thread = str(letter.get("thread") or "")
            if card:
                from v7_harness.coord.windows import window_for
                thread = window_for(desk, card, tool) or thread  # U115: card's own window of the now-ACTIVE tool

            message = str(letter.get("message") or "")
            actor = str(letter.get("actor") or "")
            # Keep the published identity, including destination and legacy queued IDs.
            digest = str(letter.get("digest") or _digest(actor, message, card, ""))

            # Decision: acquire per-message dispatch guard following U83 age rule (_acquire_guard, GUARD_STALE_S)
            guard = box.root / "delivery" / "guards" / f"{message_id}.lock"
            guard.parent.mkdir(parents=True, exist_ok=True)
            guard_fd = _acquire_guard(guard, box, message_id, digest)
            if guard_fd is None:
                # Decision: guard is still young held by another active/recent dispatcher -> IN_FLIGHT
                result = DeliverResult(False, tool, "IN_FLIGHT", (), "", message_id, digest)
            else:
                guard_owner = uuid.uuid4().hex
                with os.fdopen(guard_fd, "wb") as handle:
                    handle.write(
                        json.dumps(
                            {
                                "message_id": message_id,
                                "digest": digest,
                                "actor": actor,
                                "message": message,
                                "target": tool,
                                "owner": guard_owner,
                            },
                            ensure_ascii=False,
                        ).encode("utf-8")
                    )
                    handle.flush()
                    os.fsync(handle.fileno())

                pending_owner = None
                if tool == "claude" and _requires_wake(message):
                    pending = box.root / "delivery" / "pending" / f"{message_id}.json"
                    pending.parent.mkdir(parents=True, exist_ok=True)
                    pending.write_text(
                        json.dumps(
                            {
                                "message_id": message_id,
                                "target": "claude",
                                "state": "PENDING",
                                "owner": guard_owner,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        encoding="utf-8",
                    )
                    pending_owner = guard_owner

                try:
                    result = _deliver_unlocked(
                        project,
                        message=message,
                        actor=actor,
                        target=tool,
                        thread=thread,
                        runner=runner,
                        pending_owner=pending_owner,
                        card=card,
                        window="",
                        identity_digest=digest,
                    )
                finally:
                    _release_guard(guard, guard_owner)

            sent.append({"message_id": str(letter.get("message_id") or message_id), "reason": result.reason})

            # Decision: settle logic
            if result.reason in settled:
                taking.unlink(missing_ok=True)
                continue

            if result.reason == "IN_FLIGHT":
                # Decision: guard is still young; return letter to <message_id>.json without adding an attempt
                os.replace(taking, folder / f"{message_id}.json")
                continue

            # Decision: any other unsettled result adds one attempt and parks after tries (3) attempts
            letter["attempts"] = int(letter.get("attempts") or 0) + 1
            taking.write_text(json.dumps(letter, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            if letter["attempts"] < tries:
                os.replace(taking, folder / f"{message_id}.json")
            else:
                _park_failed(taking, message_id, folder)
        finally:
            if locked:
                try:
                    _unlock(fd)
                except OSError:
                    pass
            try:
                os.close(fd)
            except OSError:
                pass

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
    identity_digest: str | None = None,
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
    digest = identity_digest or _digest(actor, message, card, window)
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
        sent_thread = ""  # U147: the receipt names the Codex thread, so a misrouted letter is visible
        if target == "codex":
            if window:  # U115: the card's own Codex thread replaces the default thread
                thread = window
            chosen_thread, fallback, status = _codex_thread(desk, thread)
            if status != "DISPATCH":
                result = DeliverResult(False, "codex", status, (), "")
            else:
                result = _deliver_to_codex(envelope, chosen_thread, runner=runner)
                sent_thread = chosen_thread
                # Rule 6: retry once on rc != 0 with newest verified thread other than failed one
                # U147-D: a letter to the designated user desk is never re-sent to a guessed relay window.
                if not result.delivered and result.reason.startswith("DELIVERY_FAILED:rc=") \
                        and chosen_thread != read_user_desk(desk, "codex"):
                    alt_thread = _newest_verified_thread(desk, _codex_sessions(), exclude_threads={chosen_thread})
                    if alt_thread:
                        fallback = {"given": chosen_thread, "used": alt_thread, "why": "send_failed"}
                        result = _deliver_to_codex(envelope, alt_thread, runner=runner)
                        sent_thread = alt_thread
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
                   "output": result.output, **({"thread_fallback": fallback} if fallback else {}),
                   **({"thread": sent_thread} if sent_thread else {})}
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
    wake_class: str | None = None,
    verdict_requested: bool | None = None,
    verdict: str | None = None,
    delta: str | None = None,
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
    explicit = {key: value for key, value in (("wake_class", wake_class), ("verdict_requested", verdict_requested),
                                              ("verdict", verdict), ("delta", delta)) if value is not None}
    if not explicit and requested_target and _requires_wake(message):
        # U141-B: an ordinary letter whose text asks for a turn becomes a structured ACTIONABLE envelope, so the
        # structured watcher (which never reads text) wakes its receiver. Explicit fields, even NOTICE, always win.
        first = next((line.strip() for line in message.splitlines() if line.strip()), "")
        wake_class, delta = "ACTIONABLE", first[:DELTA_LIMIT]
        explicit = {"wake_class": wake_class, "delta": delta}  # stored fields, so the id is v3 (see _digest)
    digest = _digest(actor, message, card, window, requested_target, explicit)
    message_id = "relay_" + digest[:32]
    if explicit.get("wake_class") or explicit.get("verdict_requested") is True or explicit.get("verdict"):
        # U155 (C6 class): a letter that declares a wake intent with malformed fields (ACTIONABLE without delta, a
        # NOTICE asking for a verdict) used to publish an INVALID envelope that never wakes anyone. Refuse it before
        # any marker or publish, so the sender gets a non-OK result instead of a silent stall. Untagged, NOTICE,
        # ACK_ONLY and verdict_requested=False letters keep today's bytes (U141-B frozen test).
        from v7_harness.coord.watch import classify
        cls, diag = classify(_payload(actor, message, digest, requested_target, card, window, **explicit))
        if cls == "INVALID":
            return DeliverResult(False, target or "mailbox_only", "INVALID_INTENT", (), diag, message_id, digest)
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
    box.publish(message_id, _payload(actor, message, digest, requested_target, card, window, wake_class=wake_class,
                                     verdict_requested=verdict_requested, verdict=verdict, delta=delta))
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
                                 card=card, window=window or "", identity_digest=digest)
    finally:
        _release_guard(guard, owner)


def agy_desktop_conversation(conversation: object) -> bool:
    if not isinstance(conversation, str) or not UUID_RE.fullmatch(conversation):
        return False
    home = Path(os.environ.get(AGY_APP_HOME_ENV) or (Path.home() / ".gemini" / "antigravity"))
    return (home / "conversations" / f"{conversation}.db").is_file() or (home / "brain" / conversation).is_dir()
