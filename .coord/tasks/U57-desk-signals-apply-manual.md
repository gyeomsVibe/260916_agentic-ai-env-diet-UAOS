```contract
work_id: U57
worker: apply
goal: Desk signals that remove user relays: Codex usage-limit evidence reads LIMITED, coord watch wakes a session on new letters at zero tokens, deliver queues for a watching interactive Claude, coord presence --lease flag, session guidance.
inputs:
- v7_harness/coord/presence.py sha256=554c0518602ae9a45bf45b6d9c003df209e22785490c90272a88dbf8d577252f
- v7_harness/coord/deliver.py sha256=725a694207034ffa3d7d676045f6f95b02d93e2e02da24efba5e27c5554f651d
- v7_harness/cli.py sha256=9ede710554826b844419712be3d47d7d366cbc3fdcdacdb825e122d7c4169cd9
- v7_harness/coord/hook_context.py sha256=6cc262fce039c5e696a78602dcb3418b198aa565afa9026f28eda1691fef462f
- CLAUDE.md sha256=9344a6ba215d986f595edce92a357f402742bce835ebb94ee3e345c69bac72a0
- AGENTS.md sha256=2d511e027ba6a04c0f96bf4dcb14d610cec60c0900456e09dc8cd2b09334872a
- uaos_everywhere/uaos_global_rule_block.md sha256=c99bd2e8da02d9ae2a0625f482ea7be01490e2ec06cfeefc7cac33054a3480a8
- uaos_everywhere/adapters/claude.md sha256=aeb0abc2b94394d83b9b12c07f21a82d0ab4cff085c091cc873237067839effa
allow:
- v7_harness/coord/presence.py
- v7_harness/coord/deliver.py
- v7_harness/cli.py
- v7_harness/coord/hook_context.py
- v7_harness/coord/watch.py
- tests/test_u57_desk_signals.py
- CLAUDE.md
- AGENTS.md
- uaos_everywhere/uaos_global_rule_block.md
- uaos_everywhere/adapters/claude.md
acceptance: C:/Python314/python.exe -m unittest tests.test_u57_desk_signals tests.test_u48_deliver tests.test_u48_deliver_d1 tests.test_u53_nonstop_relay tests.test_u53_turn_lock_delete_pending tests.test_u15_coord_cli tests.test_u37_install_everywhere tests.test_u38_cost_gate_and_claude_worker tests.test_b20_model_flag tests.test_b23_concurrency_summary tests.test_b25_db_unavailable tests.test_b41_bundle tests.test_cli tests.test_r2_minimal_control
forbidden: design changes; edits outside allow; weakening or deleting existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Card: U57, user order 2026-09-28 ('사용자를 귀찮게하는 오류를 싹 다 잡아 없어 영구히 오류 없게해줘'). Root causes seen 2026-09-27: (A) Codex hook wrote ACTIVE for a prompt Codex refused with usage_limit_exceeded, so route went to Codex; (B) Claude-to-Claude chat messages held for user approval; (C) cold claude -p while an interactive session listened; (D) hand-written sentinel loop and a Python-only lease. New test red on HEAD (import error), green on stage with test_u48_deliver 33 OK. Acting judge Claude; Codex re-reviews.

===FILE: v7_harness/coord/presence.py===
"""Who is at the desk: one heartbeat file per tool, written by that tool's own session hooks.

The user used to declare "Codex is absent" by hand in PLAN.md, and that line stayed true until someone edited it.
A heartbeat carries its own expiry, so a tool that stops reporting (quota, crash, closed window) turns UNKNOWN
by itself. Reading and writing a small JSON file costs no model tokens.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PRESENCE_DIR = Path(".coord") / "presence"
TOOLS = ("codex", "claude", "antigravity")
STATES = ("ACTIVE", "LIMITED", "ABSENT")
DEFAULT_TTL_S = 3600


class PresenceRejected(ValueError):
    pass


def _path(project: Path, tool: str) -> Path:
    if tool not in TOOLS:
        raise PresenceRejected(f"unknown tool: {tool}")
    return Path(project) / PRESENCE_DIR / f"{tool}.json"


def mark(project: Path, tool: str, state: str, *, ttl_s: int = DEFAULT_TTL_S, now: float | None = None,
         lease: bool = False) -> Path:
    """Write one heartbeat. `lease=True` records a capability fact (e.g. a provider's quota answer) that a session
    heartbeat of another state cannot overwrite before it expires.

    U47-A1b: Codex's re-review (2026-09-27) found that the next ACTIVE session hook replaced the LIMITED state
    `pilot judge` had recorded from agy's 429 answer, so routing again sent verdict requests to a tool that could not
    answer. A live lease is kept and the heartbeat is dropped; another lease replaces it.
    """
    if state not in STATES:
        raise PresenceRejected(f"unknown state: {state}")
    if ttl_s <= 0:
        raise PresenceRejected("ttl_s must be positive")
    moment = time.time() if now is None else now
    target = _path(project, tool)
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "tool": tool,
        "state": state,
        "observed_at": (datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=moment)).isoformat(timespec="seconds"),
        "expires_at": moment + ttl_s,
    }
    if lease:
        record["lease"] = True
    # U47-RW1c: Codex's race (2026-09-27) let a heartbeat pass the lease check, a lease land, and the heartbeat then
    # replace it. The check and the replace now happen under one lock shared by threads and processes.
    with _tool_lock(target):
        if not lease and _live_lease(target, moment, state):
            return target
        tmp = target.with_name(f".{tool}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(tmp, target)
    return target


# A heartbeat write takes milliseconds; 10 s of waiting means a stuck writer, and a lock file older than 60 s is taken
# as left by a dead process (the same bounds as coord/stream.py, measured there under an 8-process race).
LOCK_TIMEOUT_S = 10.0
LOCK_STALE_S = 60.0
_THREAD_LOCK = threading.Lock()


@contextmanager
def _tool_lock(target: Path):
    """Exclusive O_EXCL lock file beside the heartbeat; raises PresenceRejected on timeout (the write is dropped)."""
    lock_path = target.with_name(f".{target.stem}.lock")
    deadline = time.monotonic() + LOCK_TIMEOUT_S
    with _THREAD_LOCK:
        handle = None
        while handle is None:
            try:
                handle = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except (FileExistsError, PermissionError):
                # Windows answers PermissionError for a lock file pending deletion: another writer holds it.
                try:
                    age = time.time() - lock_path.stat().st_mtime
                except (FileNotFoundError, PermissionError):
                    time.sleep(0.01)
                    continue
                if age > LOCK_STALE_S:
                    lock_path.unlink(missing_ok=True)
                    continue
                if time.monotonic() > deadline:
                    raise PresenceRejected("PRESENCE_LOCK_TIMEOUT") from None
                time.sleep(0.01)
        try:
            yield
        finally:
            os.close(handle)
            lock_path.unlink(missing_ok=True)


def _live_lease(target: Path, moment: float, state: str) -> bool:
    """True while the file holds an unexpired lease of a different state; an unreadable file holds nothing."""
    try:
        record = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    # U47-RW1d: a capability lease protects its original expiry from every ordinary heartbeat. A same-state
    # heartbeat is not new quota evidence and must not shorten a 162-hour provider lease to the session TTL.
    if not isinstance(record, dict) or record.get("lease") is not True:
        return False
    expires_at = record.get("expires_at")
    return isinstance(expires_at, (int, float)) and not isinstance(expires_at, bool) and expires_at > moment


def read(project: Path, tool: str, *, now: float | None = None) -> dict[str, Any]:
    moment = time.time() if now is None else now
    unknown = {"tool": tool, "state": "UNKNOWN", "observed_at": None, "expires_at": None}
    try:
        record = json.loads(_path(project, tool).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return unknown
    if not isinstance(record, dict):
        return unknown
    expires_at = record.get("expires_at")
    if record.get("state") not in STATES or isinstance(expires_at, bool) or not isinstance(expires_at, (int, float)):
        return unknown
    if expires_at <= moment:
        return {**unknown, "observed_at": record.get("observed_at"), "expires_at": expires_at}
    if tool == "codex" and record["state"] == "ACTIVE":
        blocked = codex_quota_block(_epoch(record.get("observed_at")), moment)
        if blocked is not None:
            return {"tool": tool, "state": "LIMITED", "observed_at": record.get("observed_at"),
                    "expires_at": blocked["until"], "evidence": blocked}
    return {"tool": tool, "state": record["state"], "observed_at": record.get("observed_at"), "expires_at": expires_at}


# U57-A (2026-09-27): Codex's UserPromptSubmit hook writes ACTIVE before the turn runs, so a relay prompt that Codex
# then refused with `usage_limit_exceeded` left the desk saying ACTIVE. `coord route` sent work to Codex and the
# acting conductor had to write a LIMITED lease by hand. Codex records the refusal in its own rollout log; reading
# the newest one turns that ACTIVE into LIMITED until the reset time Codex printed. Reading is local and costs no
# tokens; a missing or unreadable log changes nothing.
CODEX_SESSIONS_ENV = "UAOS_CODEX_SESSIONS"
# The last task_complete line of a rollout sits in its final lines; 64 KiB held 20+ events in the 2026-09-27 logs.
ROLLOUT_TAIL_BYTES = 64 * 1024
# Newest three rollouts of the newest two day folders: sessions run in parallel and one may cross midnight.
ROLLOUT_DAYS = 2
ROLLOUT_FILES = 3
# The hook stamps observed_at in whole seconds just before the turn starts; 5 s covers the truncation and the gap.
HEARTBEAT_SLACK_S = 5
# When the reset time cannot be parsed, assume one hour; the next refused prompt writes a fresh refusal anyway.
UNPARSED_RESET_S = 3600


def _epoch(stamp: Any) -> float | None:
    if not isinstance(stamp, str):
        return None
    try:
        parsed = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _codex_rollouts() -> list[Path]:
    root = Path(os.environ.get(CODEX_SESSIONS_ENV) or (Path.home() / ".codex" / "sessions"))
    try:
        days = sorted((d for d in root.glob("*/*/*") if d.is_dir()), key=lambda d: d.parts[-3:], reverse=True)
        files = [f for d in days[:ROLLOUT_DAYS] for f in d.glob("rollout-*.jsonl") if f.is_file()]
        return sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)[:ROLLOUT_FILES]
    except OSError:
        return []


def _last_task_complete(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - ROLLOUT_TAIL_BYTES))
            lines = handle.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if '"task_complete"' not in line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue  # the first line of the tail may be cut
        payload = event.get("payload") if isinstance(event, dict) else None
        if isinstance(payload, dict) and payload.get("type") == "task_complete":
            return payload
    return None


def _reset_at(message: str, completed_at: float) -> float:
    match = re.search(r"try again at (\d{1,2}):(\d{2})\s*([AP]M)", message or "", re.IGNORECASE)
    if not match:
        return completed_at + UNPARSED_RESET_S
    hour, minute, half = int(match.group(1)) % 12, int(match.group(2)), match.group(3).upper()
    hour += 12 if half == "PM" else 0
    # Codex prints the reset in the machine's local time; roll to the next day when that clock time has passed.
    local = datetime.fromtimestamp(completed_at).astimezone()
    reset = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if reset.timestamp() <= completed_at:
        reset += timedelta(days=1)
    return reset.timestamp()


def codex_quota_block(observed_epoch: float | None, moment: float) -> dict[str, Any] | None:
    """Return the refusal that outranks an ACTIVE heartbeat, or None.

    It counts only when Codex refused a turn at or after the heartbeat (the heartbeat was for that failed prompt), the
    refusal is not in the future of `moment`, and the reset time has not passed. A heartbeat written after the refusal
    is a newer prompt and wins; if that prompt is refused too, its own refusal is newer again.
    """
    if observed_epoch is None:
        return None
    newest: dict[str, Any] | None = None
    for path in _codex_rollouts():
        payload = _last_task_complete(path)
        completed = payload.get("completed_at") if payload else None
        if isinstance(completed, (int, float)) and not isinstance(completed, bool) and (
                newest is None or completed > newest["completed_at"]):
            newest = {"completed_at": completed, "payload": payload, "rollout": str(path)}
    if newest is None:
        return None
    error = newest["payload"].get("error")
    if not isinstance(error, dict) or error.get("codex_error_info") != "usage_limit_exceeded":
        return None
    completed_at = float(newest["completed_at"])
    if completed_at + HEARTBEAT_SLACK_S < observed_epoch or completed_at > moment:
        return None
    until = _reset_at(str(error.get("message", "")), completed_at)
    if until <= moment:
        return None
    return {"source": "codex_rollout", "reason": "usage_limit_exceeded", "completed_at": completed_at,
            "until": until, "rollout": newest["rollout"]}


def read_all(project: Path, *, now: float | None = None) -> dict[str, dict[str, Any]]:
    return {tool: read(project, tool, now=now) for tool in TOOLS}


# U45 G1/G3: the succession order of docs/27 §4. Codex conducts; Claude acts while Codex is LIMITED or ABSENT;
# Antigravity acts only while both are. Only desk states count: a quota figure beside a state is ignored on purpose.
SUCCESSION = ("codex", "claude", "antigravity")
AWAY = ("LIMITED", "ABSENT")


def conductor(desk: dict[str, dict[str, Any]]) -> dict[str, Any]:
    for position, tool in enumerate(SUCCESSION):
        state = (desk.get(tool) or {}).get("state", "UNKNOWN")
        if state == "ACTIVE":
            acting = position > 0
            reason = f"{tool} ACTIVE" + (f"; {', '.join(SUCCESSION[:position])} away" if acting else "")
            return {"conductor": tool, "acting": acting, "reason": reason}
        if state not in AWAY:
            # An expired heartbeat is not absence: stop here instead of handing authority to the next tool.
            return {"conductor": "UNKNOWN", "acting": False, "reason": f"{tool} {state}: heartbeat not current"}
    return {"conductor": "none", "acting": False, "reason": "all three tools LIMITED or ABSENT"}
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
from contextlib import contextmanager
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


# ── 통합 전달기 ──────────────────────────────────────────────
# Why 300 s: a live dispatcher holds the guard at most for the Claude CLI timeout (120 s) plus receipt writes; 300 s
# gives 2.5x margin so a slow but live dispatcher is never taken for a crashed one.
GUARD_STALE_S = 300.0
# The recovery lock is held only for a stat, a rename and an open (milliseconds); 60 s means its holder crashed.
RECOVER_STALE_S = 60.0
# 50 x 20 ms bounds the claim retry at about 1 s, well above the few ms a concurrent publish holds the file open.
CLAIM_TRIES = 50
CLAIM_SLEEP_S = 0.02
# Release waits for the recovery lock at most 5 s: recovery holds it for milliseconds, so 5 s only runs out when a
# recoverer crashed inside it; the guard is then left for stale recovery, which can delay but never double-dispatch.
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


def _release_guard(guard: Path, owner: str) -> None:
    """Remove the dispatch guard only if this dispatcher still owns it, under the same lock recovery uses.

    U49-G1R (Codex REJECT of G1, 2026-09-27): an unconditional unlink by a dispatcher that outlived GUARD_STALE_S removed
    the new holder's guard, and G1's owner check alone still let a recovery land between the read and the unlink.
    Holding `<guard>.recover` across compare and unlink makes release and recovery mutually exclusive, because recovery
    ages, renames and re-creates the guard only while holding that lock too.
    """
    recover = guard.with_name(guard.name + ".recover")
    deadline = time.monotonic() + RELEASE_WAIT_S
    rfd = _open_excl(recover)
    while rfd is None and time.monotonic() < deadline:
        try:
            if time.time() - recover.stat().st_mtime >= RECOVER_STALE_S:
                os.rename(recover, recover.with_name(f"{recover.name}.stale-{uuid.uuid4().hex}"))
        except OSError:
            pass
        time.sleep(CLAIM_SLEEP_S)
        rfd = _open_excl(recover)
    if rfd is None:
        return  # left for stale recovery: a delay, never a second dispatcher
    os.close(rfd)
    try:
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
    finally:
        recover.unlink(missing_ok=True)


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

    # U57-C (2026-09-28): an interactive Claude session running `coord watch` wakes on this inbox letter by itself.
    # A cold `claude -p` would answer without the conversation and race the live session, so leave the letter queued.
    if target == "claude":
        from v7_harness.coord.watch import watcher_live
        if watcher_live(project, "claude"):
            return DeliverResult(False, "claude", "QUEUED_INTERACTIVE", (), "", message_id, digest,
                                 str(box.inbox_dir / f"{message_id}.json"))

    accepted =box.root / "delivery" / "accepted" / f"{message_id}.json"
    if accepted.is_file():
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
                thread = resolve_thread(project)
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
    owner = uuid.uuid4().hex
    with os.fdopen(fd, "wb") as handle:
        handle.write(json.dumps({"message_id": message_id, "digest": digest, "actor": actor,
                                 "message": message, "target": target, "owner": owner},
                                ensure_ascii=False).encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    try:
        return _deliver_unlocked(project, message=message, actor=actor, target=target,
                                 thread=thread, runner=runner)
    finally:
        _release_guard(guard, owner)
===FILE: v7_harness/cli.py===
"""
Command-line interface for v7 harness.

Provides unified commands for:
- context lease validation
- intent ledger operations & integrity verification
- proof receipt execution
- deterministic snapshot capture
- next-stage eligibility evaluation
- A/B benchmark execution
- concise reporting
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Optional

from .benchmark_hook import BenchmarkHook
from .context_lease import ContextLease, ContextLeaseValidator
from .intent_ledger import IntentLedger
from .proof_receipt import ProofReceiptStore, run_with_receipt
from .reporter import generate_report
from .snapshot import take_snapshot
from .stage_evaluator import AcceptanceCheck, StageEvaluator

# 로컬 계산기가 멈추면(시간 초과·공급자 오류) 다음 계산기로 넘긴다 (실측 2026-09-23: qwen2.5-coder 7b 가 cli.py 과제에서 600초 PROVIDER_ERROR).


def cmd_lease_check(args: argparse.Namespace) -> int:
    lease_path = Path(args.file)
    if not lease_path.exists():
        print(f"Error: lease file '{lease_path}' does not exist.", file=sys.stderr)
        return 1

    with open(lease_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        leases = [ContextLease.from_dict(d) for d in data]
    else:
        leases = [ContextLease.from_dict(data)]

    validator = ContextLeaseValidator()
    results, valid_ids = validator.validate_lease_set(leases, target_scope=args.scope)

    all_valid = len(valid_ids) == len(leases)
    for lid, res in results.items():
        status = "VALID" if res.valid else "INVALID"
        print(f"[{status}] Lease {lid}: errors={res.errors}, warnings={res.warnings}")

    return 0 if all_valid else 2


def cmd_ledger_append(args: argparse.Namespace) -> int:
    ledger = IntentLedger(args.ledger_file)
    entry = ledger.append(
        task_id=args.task_id,
        actor=args.actor,
        category=args.category,
        content=args.content,
        rationale=args.rationale,
        assumption=args.assumption,
        invalidation_condition=args.invalidation_condition,
    )
    print(f"Appended entry: {entry.entry_id} (hash: {entry.entry_hash[:12]}...)")
    return 0


def cmd_ledger_verify(args: argparse.Namespace) -> int:
    ledger = IntentLedger(args.ledger_file)
    valid, reason = ledger.verify_integrity()
    if valid:
        print(f"Ledger integrity OK: {len(ledger.entries)} entries verified.")
        return 0
    else:
        print(f"Ledger integrity FAILED: {reason}", file=sys.stderr)
        return 1


def cmd_receipt_run(args: argparse.Namespace) -> int:
    cmd = list(args.cmd)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("Error: No command specified for receipt-run.", file=sys.stderr)
        return 2
    store = ProofReceiptStore(args.store) if args.store else None
    receipt = run_with_receipt(
        command=cmd,
        task_id=args.task_id,
        actor=args.actor,
        receipt_store=store,
    )
    print(json.dumps(receipt.to_dict(), indent=2, ensure_ascii=False))
    return receipt.exit_code


def cmd_snapshot(args: argparse.Namespace) -> int:
    snap = take_snapshot(target_path=args.target_path, force_non_git=args.force_non_git)
    if args.output:
        out_p = Path(args.output)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(snap.to_dict(), f, indent=2, ensure_ascii=False)
        print(f"Snapshot written to {out_p} (hash: {snap.snapshot_hash[:12]}..., type: {snap.snapshot_type})")
    else:
        print(json.dumps(snap.to_dict(), indent=2, ensure_ascii=False))
    return 0


def cmd_eval_next(args: argparse.Namespace) -> int:
    evaluator = StageEvaluator()
    # Dummy or CLI checks
    check = AcceptanceCheck(
        criterion_id="ALL",
        description="CLI passed checks",
        passed=not args.has_failures,
    )
    pending_actions = args.pending_actions or []
    eligibility = evaluator.evaluate_eligibility(
        current_task_id=args.current_task_id,
        checks=[check],
        pending_actions=pending_actions,
        next_task_candidate=args.next_task,
    )
    print(json.dumps(eligibility.to_dict(), indent=2, ensure_ascii=False))
    return 0 if eligibility.is_eligible else 1


def cmd_benchmark(args: argparse.Namespace) -> int:
    hook = BenchmarkHook(args.name)

    def dummy_baseline():
        sum(i * i for i in range(100_000))

    def dummy_candidate():
        sum(i * i for i in range(50_000))

    res = hook.run_comparison(dummy_baseline, dummy_candidate)
    print(json.dumps(res.to_dict(), indent=2, ensure_ascii=False))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    verification_str: Optional[str] = None
    if args.verification is not None:
        verification_str = ", ".join(args.verification)

    checks = [] if verification_str is not None else [("CLI test", 0)]
    rep = generate_report(
        result=args.result,
        changed=args.changed or [],
        checks=checks,
        risks=args.risks,
        next_action=args.next_action,
        user_action_required=args.user_action_required,
        verification=verification_str,
    )
    print(rep.to_concise_markdown())
    return 0


def manual_project(manual: Path) -> Path:
    """U45-F1: the project a manual's paths are relative to, when no --source is given: the nearest folder above the
    manual that holds .coord/PLAN.md, else the current folder. Lint run from another cwd used to report INPUT_MISSING
    for files that exist under the pilot source (U45-O1b)."""
    for folder in Path(manual).resolve().parents:
        if (folder / ".coord" / "PLAN.md").is_file():
            return folder
    return Path(".")


def mandatory_watch_roots(work_dir: Path, source_dir: Path) -> list[Path]:
    """Shallow roots a worker must not write into during a run.

    U45-F5: the work dir's parent used to be watched always. When that parent is a shared `.work/` folder, the
    conductor keeps writing its own notes there during a paid run (U45-G7 a001: two conductor files flagged, run
    abandoned, $0.319 lost). A shared `.work/` is therefore not watched; home, temp, the source's parent and the stage
    stay watched. A worker writing a sibling file inside `.work/` goes unseen, and `.work/` is never committed.
    """
    work = work_dir.resolve()
    return list(dict.fromkeys([
        Path.home().resolve(),
        Path(tempfile.gettempdir()).resolve(),
        *([] if work.parent.name == ".work" else [work.parent]),
        source_dir.resolve().parent,
        (work_dir / "stage").resolve(),
    ]))


def cmd_pilot_run(args: argparse.Namespace) -> int:
    task_id = args.task
    source_dir = Path(args.source)
    if not source_dir.exists():
        print(f"Error: source directory '{source_dir}' does not exist.", file=sys.stderr)
        return 1

    # U34: a manual is a contract. It is linted before anything runs and its fields drive the run, so the
    # worker receives exactly the checked text and cannot change files outside `allow`.
    contract: Optional[dict] = None
    manual_path = getattr(args, "manual", None)
    if manual_path:
        from .manual import lint

        mfile = Path(manual_path)
        if not mfile.is_file():
            print(f"Error: manual '{mfile}' does not exist.", file=sys.stderr)
            return 1
        prompt = mfile.read_text(encoding="utf-8")
        report = lint(prompt, source_dir)
        if not report.ok:
            print(json.dumps({"task_id": task_id, "state": "REFUSED", "error_class": "MANUAL_INVALID",
                              "verdict_hint": "BLOCKED", "manual_errors": report.errors,
                              "manual_warnings": report.warnings}, indent=2, ensure_ascii=False))
            return 2
        contract = report.contract
        for warning in report.warnings:
            print(f"[manual] {warning}", file=sys.stderr)
        if contract.get("work_id") != task_id:
            # U45-F7: refuse before any worker runs. A warning here let a paid run finish first (U45-G7r, $0.263 lost).
            print(json.dumps({"task_id": task_id, "state": "REFUSED", "error_class": "MANUAL_TASK_MISMATCH",
                              "verdict_hint": "BLOCKED", "manual_work_id": contract.get("work_id")},
                             indent=2, ensure_ascii=False))
            return 2
        if args.approve:
            approver = getattr(args, "coord_actor", None) or detect_actor()
            # An approver the harness cannot identify used to pass silently (B85 review). Name it with --coord-actor.
            # This is a speed bump, not authentication: on one OS account every name can be forged (B83).
            if approver is None or approver != contract["judge"].lower():
                print(json.dumps({"task_id": task_id, "state": "REFUSED",
                                  "error_class": "APPROVER_UNKNOWN" if approver is None else "APPROVER_NOT_JUDGE",
                                  "verdict_hint": "BLOCKED", "judge": contract["judge"], "approver": approver},
                                 indent=2, ensure_ascii=False))
                return 2
    elif args.prompt_file:
        pfile = Path(args.prompt_file)
        if not pfile.is_file():
            print(f"Error: prompt file '{pfile}' does not exist.", file=sys.stderr)
            return 1
        prompt = pfile.read_text(encoding="utf-8")
    elif args.prompt:
        prompt = args.prompt
    else:
        print("Error: one of --manual, --prompt-file or --prompt must be provided.", file=sys.stderr)
        return 2

    # 실행 전에 지시문의 구체성을 알려 준다. 막지는 않는다. 벤치에서 로컬 모델이 실패한
    # 유일한 축이 모호함이었으므로, 고르기 전에 한 줄이라도 보이는 편이 낫다.
    from .adapters.ollama_worker import dictated_paths
    from .adapters.worker_advice import advise

    advice = advise(prompt)
    chosen = contract["worker"] if contract else getattr(args, "worker", "agy")
    # auto: 지휘자가 코드를 이미 적었으면(받아쓰기) 모델 없이 그대로 적용하고, 아니면 구체성으로 고른다.
    if chosen == "auto":
        if dictated_paths(prompt):
            chosen = "apply"
        else:
            chosen = "cascade" if advice.worker == "local" else "agy"
        routed = {"worker": chosen, "specificity": advice.specificity}
    else:
        routed = None
    if advice.worker != chosen and chosen != "apply":
        print(
            f"[조언] 지시문 구체성 {advice.specificity}/100 → --worker {advice.worker} 권장"
            f" (현재 {chosen}): {'; '.join(advice.reasons[:2])}",
            file=sys.stderr,
        )

    # U38: a Claude worker spends the same subscription as the Claude commander. When Claude reports LIMITED, the
    # commander keeps the remaining quota (docs/40 §2-1).
    uses_claude = chosen == "claude" or (chosen == "cascade" and getattr(args, "escalate_to", "agy") == "claude")
    if uses_claude and not args.approve:
        from .coord.presence import read as read_presence

        if read_presence(source_dir, "claude")["state"] == "LIMITED":
            print(json.dumps({"task_id": task_id, "state": "REFUSED", "error_class": "CLAUDE_LIMITED",
                              "verdict_hint": "BLOCKED",
                              "message": "Claude presence is LIMITED; its quota is kept for the commander"},
                             indent=2, ensure_ascii=False))
            return 2

    # B85 rework (Codex): a paid worker runs only under a contract. Without a manual there is no budget and no dollar
    # cap, and an approval could promote a run nothing ever measured.
    from .manual import REMOTE_WORKERS

    if chosen in REMOTE_WORKERS and contract is None:
        print(json.dumps({"task_id": task_id, "state": "REFUSED", "error_class": "REMOTE_WITHOUT_MANUAL",
                          "verdict_hint": "BLOCKED", "worker": chosen,
                          "message": "paid workers (agy, claude) need --manual with remote_budget_tokens"},
                         indent=2, ensure_ascii=False))
        return 2

    work_dir = Path(args.work_dir) if args.work_dir else Path(".coord")
    mandatory_roots = mandatory_watch_roots(work_dir, source_dir)
    explicit_roots = [Path(w).resolve() for w in args.watch_root] if args.watch_root else []
    watch_roots = list(dict.fromkeys(mandatory_roots + explicit_roots))
    agy_cmd = resolve_worker_command(chosen, args.agy_command)
    # Pre-spend hard cap for a Claude worker (Codex): the contract's dollar cap goes to `claude --max-budget-usd`.
    # The token gate after the run stays; dollars are never inferred from tokens (model and cache prices differ).
    usd_cap = str(contract.get("remote_budget_usd") or "") if contract else ""

    def _with_cap(command: list[str], worker: str) -> list[str]:
        return [*command, "--max-budget-usd", usd_cap] if worker == "claude" and usd_cap else command

    agy_cmd = _with_cap(agy_cmd, chosen)

    from .pilot import PilotConfig, run_pilot

    allowed = list(contract["allow"]) if contract else []
    allowed += list(getattr(args, "allow", None) or [])
    remote_budget = int(contract.get("remote_budget_tokens") or 0) if contract else None
    config = PilotConfig(
        task_id=task_id,
        title=args.title or f"Pilot task {task_id}",
        prompt=prompt,
        source_dir=source_dir,
        work_dir=work_dir,
        agy_command=agy_cmd,
        watch_roots=watch_roots,
        print_timeout_s=int(contract["timeout_s"]) if contract else args.print_timeout,
        approve_bundle_id=args.approve,
        accept_cmd=args.accept_cmd or (contract["acceptance"] if contract else None),
        # U38: a contract may name its model (e.g. a Claude worker's Haiku or Sonnet); --model on the command line wins.
        model=getattr(args, "model", None) or ((contract.get("model") or None) if contract else None),
        allow_no_changes=getattr(args, "allow_no_changes", False),
        allowed_scopes=allowed or None,
        # B85: every paid run is checked against the contract budget, not only a cascade escalation.
        remote_budget_tokens=(remote_budget or None) if chosen in REMOTE_WORKERS else None,
    )

    from .broker.core import BrokerAlreadyRunning
    from .isolation.errors import SourceDivergenceError

    try:
        summary = run_pilot(config)
    except BrokerAlreadyRunning:
        summary = {
            "task_id": task_id,
            "state": "FAILED",
            "error_class": "BROKER_ALREADY_RUNNING",
            "effect_state": "NONE",
            "verdict_hint": "BLOCKED",
            "message": "Another broker is currently running on this work directory.",
        }
    except SourceDivergenceError as exc:
        summary = {
            "task_id": task_id,
            "state": "FAILED",
            "error_class": "SOURCE_DIVERGED",
            "effect_state": "NONE",
            "verdict_hint": "BLOCKED",
            "message": f"Source directory diverged from staging baseline: {exc}",
        }
    except sqlite3.DatabaseError as exc:
        summary = {
            "task_id": task_id,
            "state": "FAILED",
            "error_class": "DB_UNAVAILABLE",
            "effect_state": "UNKNOWN",
            "verdict_hint": "BLOCKED",
            "message": f"Database error or corruption: {exc}. Recovery hint: run 'python -m v7_harness.cli pilot reconcile --task {task_id}' or backup coord.sqlite3.",
        }

    # cascade: 싼 local 을 먼저 쓰고 실패 종류에 따라 한 번만 넘긴다. A/B(2026-09-23, 10과제): local 6/10·51.8초,
    # lane 9/10·218초(4.2배), 계산상 cascade 10/10·2.7배. 같은 id 재실행은 원장이 막으므로 단계마다 id가 다르다.
    # U39 (docs/41 §5): deterministic → Ollama once → Antigravity once. Only a format-only failure gets one more local
    # try, inside the same local budget; a semantic failure never loops locally; a remote failure goes to splitting.
    # The approval run stays on the original task. Every stage runs under its own task id.
    def _run(cfg: Any) -> dict[str, Any]:
        try:
            return run_pilot(cfg)
        except (BrokerAlreadyRunning, SourceDivergenceError, sqlite3.DatabaseError) as exc:
            return {"task_id": cfg.task_id, "state": "FAILED", "error_class": type(exc).__name__,
                    "effect_state": "UNKNOWN", "verdict_hint": "BLOCKED", "message": str(exc)}

    if chosen == "cascade" and not args.approve:
        from .routing import classify_failure, local_tokens, next_route

        failure = classify_failure(summary)
        used_local = local_tokens(summary)
        trace = [f"local:{failure or 'PASS'}"]
        route = next_route("local", failure, local_attempts=1, local_tokens=used_local)
        if route == "local_retry":
            config.task_id = f"{task_id}-retry"
            summary = _run(config)
            failure = classify_failure(summary)
            used_local += local_tokens(summary)
            trace.append(f"local_retry:{failure or 'PASS'}")
            route = next_route("local_retry", failure, local_attempts=2, local_tokens=used_local)
        if route == "remote":
            first = summary
            escalate_to = getattr(args, "escalate_to", "agy")
            if escalate_to in REMOTE_WORKERS and not remote_budget:
                # B85 rework: no contract budget, no paid escalation (lane runs the local model and stays allowed).
                summary["escalation"] = "REFUSED:REMOTE_WITHOUT_MANUAL"
                trace.append("refused")
            else:
                config.task_id = f"{task_id}-{escalate_to}"
                config.agy_command = _with_cap(resolve_worker_command(escalate_to, None), escalate_to)
                config.remote_budget_tokens = (remote_budget or None) if escalate_to in REMOTE_WORKERS else None
                summary = _run(config)
                summary["cascade_from"] = {"task_id": task_id, "verdict_hint": first.get("verdict_hint"),
                                           "error_class": first.get("error_class"), "escalated_to": escalate_to}
                remote_failure = classify_failure(summary)
                trace.append(f"remote:{remote_failure or 'PASS'}")
                if next_route("remote", remote_failure, local_attempts=2, local_tokens=used_local) == "split":
                    trace.append("split")
        elif route == "stop":
            trace.append("stop")
        summary["route"] = trace
    # The pilot gates the budget itself (B85). This covers a summary that came back without the gate.
    if remote_budget and "cost_gate" not in summary and (chosen in REMOTE_WORKERS or "cascade_from" in summary):
        from .pilot import evaluate_cost_gate

        summary["cost_gate"] = evaluate_cost_gate(summary.get("agy_usage"), remote_budget)
        if summary["cost_gate"] != "WITHIN":
            summary["verdict_hint"] = "BLOCKED"
            summary["error_class"] = "COST_UNKNOWN" if summary["cost_gate"] == "UNKNOWN" else "COST_EXCEEDED"

    # U33: 보고는 기억이 아니라 실행 끝에서 저절로 남는다(비둘기 퇴출). 기록 대상은 --source 프로젝트이고,
    # .coord/PLAN.md 가 있는 UAOS 프로젝트일 때만 쓴다. 예전에 기본을 켰을 때 CLI 를 부르는 테스트가 실제
    # 스트림에 사건 8건을 흘렸다. 테스트 패키지는 UAOS_STREAM_AUTOLOG=0 으로 끈다(tests/__init__.py).
    if getattr(args, "coord_log", False) and os.environ.get("UAOS_STREAM_AUTOLOG", "1") != "0":
        coord_project = Path(getattr(args, "coord_project", None) or source_dir)
        actor = getattr(args, "coord_actor", None) or detect_actor()
        if (coord_project / ".coord" / "PLAN.md").is_file() and actor:
            record_pilot_in_stream(coord_project, summary, actor=actor, task=summary.get("task_id") or task_id)

    if routed is not None:
        summary["routed_by"] = routed
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    # ACCEPT_INFRA·ACCEPT_NOT_RUN으로 state가 SUCCEEDED여도 BLOCKED 판정이면 1 반환
    if summary.get("verdict_hint") == "BLOCKED":
        return 1
    return 0 if summary.get("state") == "SUCCEEDED" else 1


def cmd_pilot_manual_lint(args: argparse.Namespace) -> int:
    from .manual import lint

    source = Path(args.source) if args.source else manual_project(Path(args.manual))
    report = lint(Path(args.manual).read_text(encoding="utf-8"), source)
    print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    return 0 if report.ok else 1


def cmd_pilot_manual_new(args: argparse.Namespace) -> int:
    from .manual import lint, new_manual

    source = Path(args.source)
    instructions = Path(args.instructions_file).read_text(encoding="utf-8") if args.instructions_file else ""
    text = new_manual(
        source,
        work_id=args.work_id,
        worker=args.worker,
        goal=args.goal,
        inputs=args.input,
        allow=args.allow,
        acceptance=args.accept,
        judge=args.judge,
        timeout_s=args.timeout,
        remote_budget_tokens=args.remote_budget,
        remote_budget_usd=args.remote_budget_usd,
        instructions=instructions,
        context_allow=args.context_allow,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    report = lint(text, source)
    print(json.dumps({"written": str(out), **report.as_dict()}, indent=2, ensure_ascii=False))
    return 0 if report.ok else 1


def cmd_pilot_reconcile(args: argparse.Namespace) -> int:
    from .pilot import reconcile_pilot

    work_dir = Path(args.work_dir) if args.work_dir else Path(".coord")
    try:
        report = reconcile_pilot(work_dir=work_dir, task_id=args.task)
    except sqlite3.DatabaseError as exc:
        report = {
            "task_id": args.task,
            "state": "FAILED",
            "error_class": "DB_UNAVAILABLE",
            "message": f"Database corruption detected during reconcile: {exc}. Recovery hint: restore coord.sqlite3 from backup.",
        }
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="v7_harness", description="v7 Minimal Automation Harness")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # lease-check
    p_lease = subparsers.add_parser("lease-check")
    p_lease.add_argument("--file", required=True)
    p_lease.add_argument("--scope", default=None)
    p_lease.set_defaults(func=cmd_lease_check)

    # ledger-append
    p_lapp = subparsers.add_parser("ledger-append")
    p_lapp.add_argument("--ledger-file", required=True)
    p_lapp.add_argument("--task-id", required=True)
    p_lapp.add_argument("--actor", required=True)
    p_lapp.add_argument("--category", required=True)
    p_lapp.add_argument("--content", required=True)
    p_lapp.add_argument("--rationale", default=None)
    p_lapp.add_argument("--assumption", default=None)
    p_lapp.add_argument("--invalidation-condition", default=None)
    p_lapp.set_defaults(func=cmd_ledger_append)

    # ledger-verify
    p_lver = subparsers.add_parser("ledger-verify")
    p_lver.add_argument("--ledger-file", required=True)
    p_lver.set_defaults(func=cmd_ledger_verify)

    # receipt-run
    p_run = subparsers.add_parser("receipt-run")
    p_run.add_argument("--task-id", required=True)
    p_run.add_argument("--actor", required=True)
    p_run.add_argument("--store", default=None)
    p_run.add_argument("cmd", nargs=argparse.REMAINDER)
    p_run.set_defaults(func=cmd_receipt_run)

    # snapshot
    p_snap = subparsers.add_parser("snapshot")
    p_snap.add_argument("--target-path", default=None)
    p_snap.add_argument("--output", default=None)
    p_snap.add_argument("--force-non-git", action="store_true")
    p_snap.set_defaults(func=cmd_snapshot)

    # eval-next
    p_eval = subparsers.add_parser("eval-next")
    p_eval.add_argument("--current-task-id", required=True)
    p_eval.add_argument("--next-task", default="U08")
    p_eval.add_argument("--has-failures", action="store_true")
    p_eval.add_argument("--pending-actions", nargs="*", default=[])
    p_eval.set_defaults(func=cmd_eval_next)

    # benchmark
    p_bench = subparsers.add_parser("benchmark")
    p_bench.add_argument("--name", default="sample_bench")
    p_bench.set_defaults(func=cmd_benchmark)

    # report
    p_rep = subparsers.add_parser("report")
    p_rep.add_argument("--result", required=True)
    p_rep.add_argument("--changed", nargs="*", default=[])
    p_rep.add_argument("--verification", nargs="*", default=None, help="Explicit verification items or summary")
    p_rep.add_argument("--risks", default="None")
    p_rep.add_argument("--next-action", default="Proceed to review")
    p_rep.add_argument("--user-action-required", action="store_true")
    p_rep.set_defaults(func=cmd_report)

    # pilot run
    p_pilot = subparsers.add_parser("pilot")
    p_pilot_subs = p_pilot.add_subparsers(dest="pilot_subcommand", required=True)
    p_pilot_run = p_pilot_subs.add_parser("run")
    p_pilot_run.add_argument("--task", "--task-id", dest="task", required=True, help="Pilot task ID (e.g. P01)")
    p_pilot_run.add_argument("--source", "--source-dir", dest="source", required=True, help="Source directory path")
    p_pilot_run.add_argument("--prompt-file", default=None, help="Path to prompt file")
    p_pilot_run.add_argument("--prompt", default=None, help="Prompt text directly")
    p_pilot_run.add_argument("--title", default=None, help="Task title")
    p_pilot_run.add_argument("--work-dir", default=".coord", help="Work directory (default: .coord)")
    p_pilot_run.add_argument("--approve", default=None, help="Approve bundle ID for live promotion")
    p_pilot_run.add_argument("--watch-root", action="append", default=[], help="Watch roots for external write detection")
    p_pilot_run.add_argument("--print-timeout", type=int, default=600, help="Print timeout in seconds")
    p_pilot_run.add_argument("--agy-command", nargs="*", default=None, help="Custom worker command prefix (overrides --worker)")
    p_pilot_run.add_argument("--worker", choices=["agy", "local", "lane", "cascade", "auto", "apply", "claude"], default="agy", help="claude = Claude Code on the paid account (needs a manual with remote_budget_tokens; judge codex or user); agy = remote worker (uses account quota); local = this machine's Ollama model, one-shot; lane = Claude Code tool loop on the local model; apply = apply the ===FILE/===EDIT blocks written in the prompt, no model (0 tokens)")
    p_pilot_run.add_argument("--manual", default=None,
                             help="Work manual with a ```contract block: linted first, then its worker, acceptance, allow list and timeout drive the run")
    p_pilot_run.add_argument("--allow", action="append", default=[],
                             help="Path or glob the worker may change (repeatable); anything else is rejected as SCOPE_VIOLATION")
    # cascade 승격 대상 작업자(lane의 e2e 실패 빈발로 기본값은 agy)
    p_pilot_run.add_argument("--escalate-to", choices=["agy", "lane", "claude"], default="agy", help="Worker for cascade second stage when local gets REWORK (default: agy)")
    p_pilot_run.add_argument("--coord-log", dest="coord_log", action="store_true", default=True,
                             help="Record this run in the coordination stream (.coord/stream); on by default")
    p_pilot_run.add_argument("--no-coord-log", dest="coord_log", action="store_false",
                             help="Do not record this run in the coordination stream")
    p_pilot_run.add_argument("--coord-project", default=None,
                             help="Project whose coordination stream records this run (default: the --source project)")
    p_pilot_run.add_argument("--coord-actor", choices=["codex", "claude", "antigravity", "user"], default=None,
                             help="Who ran this pilot (default: detected from the calling tool's environment)")
    p_pilot_run.add_argument("--model", default=None, help="Model name to pass to agy (e.g. gemini-3.7-flash)")
    p_pilot_run.add_argument("--accept-cmd", default=None, help="Acceptance test command to run in staging")
    p_pilot_run.add_argument("--allow-no-changes", action="store_true", default=False, help="Allow PASS verdict even when no files were changed (for read-only tasks)")
    p_pilot_run.set_defaults(func=cmd_pilot_run)

    # pilot manual: U34 work-manual contracts
    p_pilot_manual = p_pilot_subs.add_parser("manual")
    p_manual_subs = p_pilot_manual.add_subparsers(dest="manual_subcommand", required=True)
    p_manual_lint = p_manual_subs.add_parser("lint")
    p_manual_lint.add_argument("--manual", required=True)
    p_manual_lint.add_argument("--source", default=None,
                               help="Project the manual's paths are relative to (default: the folder above the manual "
                                    "that holds .coord/PLAN.md, else the current folder)")
    p_manual_lint.set_defaults(func=cmd_pilot_manual_lint)
    p_manual_new = p_manual_subs.add_parser("new")
    p_manual_new.add_argument("--out", required=True, help="Manual file to write")
    p_manual_new.add_argument("--source", default=".")
    p_manual_new.add_argument("--work-id", required=True)
    p_manual_new.add_argument("--worker", required=True, choices=["local", "apply", "agy", "lane", "cascade", "claude"])
    p_manual_new.add_argument("--goal", required=True)
    p_manual_new.add_argument("--input", action="append", default=[], help="Input file to pin by SHA-256 (repeatable)")
    p_manual_new.add_argument("--allow", action="append", default=[], required=True)
    p_manual_new.add_argument("--context-allow", action="append", default=None,
                              help="U50: extra file or pattern the worker may see (repeatable); omit to keep all")
    p_manual_new.add_argument("--accept", required=True, help="Acceptance command")
    p_manual_new.add_argument("--judge", required=True, choices=["codex", "claude", "antigravity", "user"])
    p_manual_new.add_argument("--timeout", type=int, default=180)
    p_manual_new.add_argument("--remote-budget", type=int, default=0)
    p_manual_new.add_argument("--remote-budget-usd", type=float, default=0.0,
                              help="Dollar cap for worker claude (claude --max-budget-usd); lint requires it > 0")
    p_manual_new.add_argument("--instructions-file", default=None, help="Prose instructions to append")
    p_manual_new.set_defaults(func=cmd_pilot_manual_new)

    # pilot reconcile
    p_pilot_review = p_pilot_subs.add_parser("review", help="U38: read-only advisory review of a bundle by Claude Code")
    p_pilot_review.add_argument("--task", required=True)
    p_pilot_review.add_argument("--work-dir", required=True)
    p_pilot_review.add_argument("--source", default=".")
    p_pilot_review.add_argument("--manual", required=True, help="The contract manual the bundle was built from")
    p_pilot_review.add_argument("--reviewer", default="claude", choices=["claude", "agy"],
                                help="agy = Antigravity CLI, read-only, token budget only (U46-J1, docs/47)")
    p_pilot_review.add_argument("--budget", type=int, required=True, help="Token budget for the review call")
    # Not required by argparse any more: run_review refuses a claude review without it (agy has no dollar option).
    p_pilot_review.add_argument("--budget-usd", type=float, default=0.0,
                                help="Dollar cap passed to claude --max-budget-usd (checked before spending); "
                                     "required for --reviewer claude")
    p_pilot_review.add_argument("--model", default=None)
    p_pilot_review.add_argument("--timeout", type=int, default=600)
    p_pilot_review.set_defaults(func=cmd_pilot_review)

    # U46-J4: binding judgement by the contract's judge tool through its CLI, only while Codex is LIMITED/ABSENT.
    p_pilot_judge = p_pilot_subs.add_parser("judge", help="U46-J4: Antigravity judges a bundle via its CLI while Codex is away")
    p_pilot_judge.add_argument("--task", required=True)
    p_pilot_judge.add_argument("--work-dir", required=True)
    p_pilot_judge.add_argument("--source", default=".")
    p_pilot_judge.add_argument("--manual", required=True, help="The contract manual the bundle was built from")
    p_pilot_judge.add_argument("--project", default=None, help="Project whose presence desk says Codex is away")
    p_pilot_judge.add_argument("--judge", default="agy", choices=["agy", "codex"])
    p_pilot_judge.add_argument("--budget", type=int, default=None,
                               help="Token cap; default scales with the diff: clamp(30,000 + 3 x diff chars, "
                                    "100,000, 250,000) (U47-J5: R1c's 34 KB bundle cost 114,644)")
    p_pilot_judge.add_argument("--timeout", type=int, default=600)
    p_pilot_judge.add_argument("--no-apply", action="store_true", help="Record the verdict without running --approve")
    p_pilot_judge.set_defaults(func=cmd_pilot_judge)

    p_pilot_rec = p_pilot_subs.add_parser("reconcile")
    p_pilot_rec.add_argument("--task", "--task-id", dest="task", required=True, help="Pilot task ID to reconcile")
    p_pilot_rec.add_argument("--work-dir", default=".coord", help="Work directory (default: .coord)")
    p_pilot_rec.set_defaults(func=cmd_pilot_reconcile)

    # coord: U15 조율 스트림
    p_coord = subparsers.add_parser("coord")
    p_coord_subs = p_coord.add_subparsers(dest="coord_subcommand", required=True)

    p_coord_log = p_coord_subs.add_parser("log")
    p_coord_log.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_log.add_argument("--actor", required=True, choices=["codex", "antigravity", "claude"])
    p_coord_log.add_argument("--kind", required=True, choices=["PLAN", "RUN", "VERDICT", "BLOCKED", "HANDOFF", "NOTE"])
    p_coord_log.add_argument("--step", required=True, help="Step or task id (e.g. U15-S4)")
    p_coord_log.add_argument("--summary", required=True, help="One line, 200 chars max")
    p_coord_log.add_argument("--ref", action="append", default=[], help="Evidence path (repeatable)")
    p_coord_log.add_argument("--cmd", default=None, help="Command that produced the evidence")
    p_coord_log.add_argument("--exit-code", dest="exit_code", type=int, default=None, help="Exit code of that command")
    p_coord_log.add_argument("--bundle", default=None, help="Bundle id when a promotion is involved")
    p_coord_log.set_defaults(func=cmd_coord_log)

    p_coord_status = p_coord_subs.add_parser("status")
    p_coord_status.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_status.set_defaults(func=cmd_coord_status)

    p_coord_brief = p_coord_subs.add_parser("brief")
    p_coord_brief.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_brief.add_argument("--owner", default=None, help="Current step owner")
    p_coord_brief.add_argument("--lock", default=None, help="Active lock, if any")
    p_coord_brief.add_argument("--pending", action="append", default=[], help="Item waiting for a Codex verdict (repeatable)")
    p_coord_brief.add_argument("--next", action="append", default=[], help="Next candidate (repeatable)")
    p_coord_brief.add_argument("--write", action="store_true", default=False, help="Write .coord/codex_brief.md instead of printing")
    p_coord_brief.set_defaults(func=cmd_coord_brief)

    p_coord_notify = p_coord_subs.add_parser("notify")
    p_coord_notify.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_notify.add_argument("--actor", required=True, choices=["codex", "antigravity", "claude"])
    p_coord_notify.add_argument("--headline", required=True, help="One line for the Codex window")
    p_coord_notify.add_argument("--thread", default=None, help="Codex session id (default: newest session for this project)")
    p_coord_notify.add_argument("--pending", action="append", default=[], help="Verdict-waiting item (default: read from PLAN)")
    p_coord_notify.add_argument(
        "--verdict-requested",
        choices=["yes", "no", "auto"],
        default="auto",
        help="Override verdict_requested (yes/no/auto; auto sets no if codex is absent)",
    )
    p_coord_notify.add_argument("--send", action="store_true", default=False, help="Actually queue it (default: dry run)")
    p_coord_notify.set_defaults(func=cmd_coord_notify)

    p_coord_archive = p_coord_subs.add_parser("archive")
    p_coord_archive.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_archive.set_defaults(func=cmd_coord_archive)

    p_coord_deliver = p_coord_subs.add_parser("deliver", help="Durable direct tool delivery")
    p_coord_deliver.add_argument("--project", default=".")
    p_coord_deliver.add_argument("--actor", required=True, choices=["codex", "claude", "antigravity"])
    p_coord_deliver.add_argument("--target", default=None, choices=["codex", "claude"])
    p_coord_deliver.add_argument("--message", required=True)
    p_coord_deliver.add_argument("--thread", default="")
    p_coord_deliver.set_defaults(func=cmd_coord_deliver)

    p_coord_sentinel = p_coord_subs.add_parser("sentinel")
    p_coord_sentinel.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_sentinel.add_argument("--once", action="store_true", default=False, help="Run single cycle and exit")
    p_coord_sentinel.add_argument("--loop", action="store_true", default=False, help="Run continuous monitoring loop")
    p_coord_sentinel.add_argument("--interval", type=int, default=30, help="Loop interval in seconds (default: 30)")
    p_coord_sentinel.add_argument("--write-brief", action="store_true", default=False, help="Write .coord/codex_brief.md")
    p_coord_sentinel.add_argument("--recipient", default="codex", help="P1 alert recipient (default: codex)")
    p_coord_sentinel.add_argument("--log", default=None,
                                  help="Append each cycle's JSON line to this file (a resident loop has no console)")
    p_coord_sentinel.add_argument("--ring", action="store_true", default=False,
                                  help="Ring Codex (codex queue) for waiting P1 wakes while Codex has a fresh ACTIVE heartbeat")
    p_coord_sentinel.set_defaults(func=cmd_coord_sentinel)

    p_coord_presence = p_coord_subs.add_parser("presence")
    p_coord_presence.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_presence.add_argument("--tool", choices=["codex", "claude", "antigravity"], default=None)
    p_coord_presence.add_argument("--state", choices=["ACTIVE", "LIMITED", "ABSENT"], default=None)
    p_coord_presence.add_argument("--ttl", type=int, default=3600, help="Seconds until the heartbeat reads UNKNOWN")
    p_coord_presence.add_argument("--if-uaos", action="store_true", default=False,
                                  help="Do nothing unless the project has .coord/PLAN.md (for global session hooks)")
    p_coord_presence.add_argument("--from-hook", action="store_true", default=False,
                                  help="Find the project from the hook payload on stdin (cwd, workspacePaths), "
                                       "CLAUDE_PROJECT_DIR or --project, walking up to .coord/PLAN.md; never fails the hook")
    p_coord_presence.add_argument("--say", choices=["json", "brief", "none", "empty-json", "p1"], default="json",
                                  help="What to print: presence JSON (default), one context line, nothing, {}, or "
                                       "p1 = one line only when a P1 wake waits and Codex is not ACTIVE (U38)")
    # U57-D: the acting conductor had to write a Codex quota lease through Python (2026-09-27); the lease itself
    # (U47-A1b) already existed in presence.mark, only the flag was missing.
    p_coord_presence.add_argument("--lease", action="store_true", default=False,
                                  help="Record a capability lease that ordinary heartbeats cannot overwrite until --ttl")
    p_coord_presence.set_defaults(func=cmd_coord_presence)

    p_coord_watch = p_coord_subs.add_parser("watch", help="Block until a new mailbox letter for a target arrives")
    p_coord_watch.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_watch.add_argument("--target", action="append", required=True, choices=["codex", "claude", "antigravity"])
    p_coord_watch.add_argument("--timeout", type=float, default=4 * 3600.0, help="Seconds before exit 3 (default: 4 h)")
    p_coord_watch.add_argument("--interval", type=float, default=30.0, help="Seconds between inbox scans (default: 30)")
    p_coord_watch.set_defaults(func=cmd_coord_watch)

    p_coord_route = p_coord_subs.add_parser("route", help="Choose the sole authority from fresh presence states")
    p_coord_route.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_route.set_defaults(func=cmd_coord_route)

    p_coord_init = p_coord_subs.add_parser("init")
    p_coord_init.add_argument("--project", default=".", help="Project to prepare for UAOS (default: .)")
    p_coord_init.set_defaults(func=cmd_coord_init)

    p_coord_inbox = p_coord_subs.add_parser("inbox")
    p_coord_inbox.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_inbox.set_defaults(func=cmd_coord_inbox)

    p_coord_ack = p_coord_subs.add_parser("ack")
    p_coord_ack.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_ack.add_argument("--id", dest="message_id", required=True, help="Mailbox message id to mark handled")
    p_coord_ack.add_argument("--consumer", default="commander", help="Who handled it (default: commander)")
    p_coord_ack.set_defaults(func=cmd_coord_ack)

    p_coord_pub = p_coord_subs.add_parser("publish-thread")
    p_coord_pub.add_argument("--actor", required=True, choices=["agy", "claude", "antigravity"])
    p_coord_pub.add_argument("--task", required=True, help="Task name (e.g. 'MIA 전략 레드팀')")
    p_coord_pub.add_argument("--prompt", default="", help="User prompt text (optional if --transcript is given)")
    p_coord_pub.add_argument("--response", default=None, help="Assistant response text")
    p_coord_pub.add_argument("--response-file", default=None, help="File containing assistant response text")
    p_coord_pub.add_argument("--transcript", default=None, help="Path to transcript.jsonl for full session import")
    p_coord_pub.add_argument("--thread-id", default=None, help="Optional thread UUID")
    p_coord_pub.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_pub.set_defaults(func=cmd_coord_publish_thread)

    # rsi: evidence-gated self-improvement (docs/38). observe → propose → try → gate → judge → rollback.
    p_rsi = subparsers.add_parser("rsi", help="Evidence-gated self-improvement: report, propose, gate, adopt, rollback")
    p_rsi_subs = p_rsi.add_subparsers(dest="rsi_subcommand", required=True)
    p_rsi_report = p_rsi_subs.add_parser("report", help="Per-worker pass/rework/blocked rates and recurring causes")
    p_rsi_report.add_argument("--project", default=".")
    p_rsi_report.set_defaults(func=cmd_rsi_report)
    p_rsi_propose = p_rsi_subs.add_parser("propose", help="Deterministic remedies for the causes in the ledger")
    p_rsi_propose.add_argument("--project", default=".")
    p_rsi_propose.add_argument("--candidate-for", default=None, metavar="PROPOSAL_ID",
                               help="Print a candidate file to fill after the trial runs")
    p_rsi_propose.add_argument("--author", default=None, help="Author of the candidate (default: detected tool)")
    p_rsi_propose.set_defaults(func=cmd_rsi_propose)
    p_rsi_gate = p_rsi_subs.add_parser("gate", help="Judge a tried candidate on ledger evidence (read only)")
    p_rsi_gate.add_argument("--project", default=".")
    p_rsi_gate.add_argument("--candidate", required=True, help="Candidate JSON file")
    p_rsi_gate.set_defaults(func=cmd_rsi_gate)
    p_rsi_adopt = p_rsi_subs.add_parser("adopt", help="Refused by design (B83): prints the gate evidence and the proposed file for a PLAN card")
    p_rsi_adopt.add_argument("--project", default=".")
    p_rsi_adopt.add_argument("--candidate", required=True)
    p_rsi_adopt.add_argument("--judge", required=True, choices=["codex", "claude", "user"],
                             help="Codex, Claude while Codex is absent, or the user (docs/31 §3)")
    p_rsi_adopt.set_defaults(func=cmd_rsi_adopt)
    p_rsi_rollback = p_rsi_subs.add_parser("rollback", help="Refused by design (B83): prints the previous policy as a proposed file")
    p_rsi_rollback.add_argument("--project", default=".")
    p_rsi_rollback.add_argument("--judge", required=True, choices=["codex", "claude", "user"])
    p_rsi_rollback.add_argument("--reason", required=True)
    p_rsi_rollback.set_defaults(func=cmd_rsi_rollback)

    p_rsi_watch = p_rsi_subs.add_parser("watch", help="Deterministic change detection cycle (U42)")
    p_rsi_watch.add_argument("--project", default=".")
    p_rsi_watch.add_argument("--config", default=None, help="Watcher config JSON path")
    p_rsi_watch.set_defaults(func=cmd_rsi_watch)

    p_rsi_prepare = p_rsi_subs.add_parser("prepare", help="Prepare a release packet (dry-run by default, --apply to write)")
    p_rsi_prepare.add_argument("--project", default=".")
    p_rsi_prepare.add_argument("--packet", required=True, help="Release packet JSON file")
    p_rsi_prepare.add_argument("--apply", action="store_true", help="Write version and update documents")
    p_rsi_prepare.add_argument("--date", default="2026-09-25", help="Release date string")
    p_rsi_prepare.set_defaults(func=cmd_rsi_prepare)

    p_rsi_ship = p_rsi_subs.add_parser("ship", help="Ship an approved release (dry-run by default, --execute to push & pr)")
    p_rsi_ship.add_argument("--project", default=".")
    p_rsi_ship.add_argument("--packet", required=True, help="Release packet JSON file")
    p_rsi_ship.add_argument("--approval", required=True, help="Approval receipt JSON file")
    p_rsi_ship.add_argument("--execute", action="store_true", help="Execute git commit, push, and gh pr create")
    p_rsi_ship.set_defaults(func=cmd_rsi_ship)

    p_rsi_schedule = p_rsi_subs.add_parser("schedule", help="Manage Windows Task Scheduler for RSI watch")
    p_rsi_schedule.add_argument("--project", default=".")
    p_rsi_schedule.add_argument("--action", choices=["install", "status", "remove", "manual-now"], default="status")
    p_rsi_schedule.add_argument("--apply", action="store_true", help="Apply schtasks command / run manual-now")
    p_rsi_schedule.add_argument("--python-bin", default=None, help="Python executable path")
    p_rsi_schedule.set_defaults(func=cmd_rsi_schedule)

    p_rsi_retention = p_rsi_subs.add_parser("retention", help="Deletion-free retention plan (dry-run manifest, U42-R1)")
    p_rsi_retention.add_argument("--project", default=".")
    p_rsi_retention.add_argument("--archive", action="store_true", help="Archive candidate files into a verified zip")
    p_rsi_retention.add_argument("--rollup-olla", action="store_true", help="Roll up olla usage ledger")
    p_rsi_retention.add_argument("--purge", default=None, metavar="ZIP",
                                 help="Validate an archive then return the fail-closed deletion boundary")
    p_rsi_retention.add_argument("--approval", default=None, metavar="FILE",
                                 help="Compatibility only; file labels are never treated as authentication")
    p_rsi_retention.set_defaults(func=cmd_rsi_retention)

    return parser


def detect_actor() -> Optional[str]:
    """Which of the three tools is running this command, from its shell environment. None for a plain terminal."""
    from .olla import _caller

    caller = _caller()
    return caller if caller in ("codex", "claude", "antigravity") else None


def record_pilot_in_stream(project: Path, summary: dict, *, actor: str = "claude", task: Optional[str] = None) -> Optional[str]:
    """파일럿 결과를 조율 스트림에 한 줄로 남긴다.

    사람이 기억해서 적으면 빠뜨린다. 실행이 끝나는 자리에서 바로 남겨야 지휘자가
    무엇을 판정해야 하는지 알 수 있다. 기록이 실패해도 파일럿 결과 보고는 막지 않는다.
    """
    from .coord.stream import StreamRejected, append_event

    verdict = str(summary.get("verdict_hint") or "UNKNOWN")
    state = str(summary.get("state") or "UNKNOWN")
    # run_pilot's summary has no task_id on a normal run, so every event used to read "pilot".
    task = str(task or summary.get("task_id") or "pilot")
    changed = summary.get("changed_files") or []
    bundle = summary.get("bundle_id") or ""
    promotion = summary.get("promotion") or ""
    kind = "RUN" if state == "SUCCEEDED" else "BLOCKED"
    detail = f"{state}/{verdict}"
    if promotion:
        detail += f"/{promotion}"
    summary_line = f"파일럿 {task}: {detail}, 변경 {len(changed)}개"
    if summary.get("error_class") not in (None, "", "NONE"):
        summary_line += f", {summary['error_class']}"

    evidence = {"cmd": f"pilot run --task {task}", "exit": 0 if state == "SUCCEEDED" else 1}
    if bundle:
        evidence["bundle"] = bundle
    refs = []
    if summary.get("summary_path"):
        # The stream refuses absolute refs, which silently dropped the whole event when --work-dir was absolute.
        ref = Path(str(summary["summary_path"]).replace("\\", "/"))
        if ref.is_absolute():
            try:
                ref = ref.resolve().relative_to(Path(project).resolve())
            except ValueError:
                ref = None
        if ref is not None:
            refs = [ref.as_posix()]
    try:
        event = append_event(
            project,
            actor=actor,
            kind=kind,
            step=task,
            summary=summary_line[:200],
            refs=refs,
            evidence=evidence,
        )
        return event.id
    except (StreamRejected, OSError, RuntimeError):
        # 기록 실패가 실행 보고를 덮지 않게 한다. 다음 브리핑에서 빈자리로 드러난다.
        return None


def cmd_pilot_review(args: argparse.Namespace) -> int:
    from .review import ReviewRefused, run_review

    try:
        manual_text = Path(args.manual).read_text(encoding="utf-8")
        record = run_review(task_id=args.task, work_dir=Path(args.work_dir), source=Path(args.source),
                            manual_text=manual_text, reviewer=args.reviewer, budget=args.budget,
                            budget_usd=args.budget_usd, model=args.model,
                            timeout_s=args.timeout)
    except (ReviewRefused, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)[:400]}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, **record}, ensure_ascii=False, indent=2))
    return 0


def cmd_pilot_judge(args: argparse.Namespace) -> int:
    from .judge import JudgeRefused, run_judge

    try:
        record = run_judge(task_id=args.task, work_dir=Path(args.work_dir), source=Path(args.source),
                           manual_path=Path(args.manual), project=Path(args.project) if args.project else None,
                           judge=args.judge, budget=args.budget, timeout_s=args.timeout, apply=not args.no_apply)
    except (JudgeRefused, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)[:400]}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, **record}, ensure_ascii=False, indent=2))
    return 0 if record["verdict"] in ("APPROVE", "REJECT") else 3


def resolve_worker_command(worker: str, explicit: Optional[Sequence[str]]) -> list[str]:
    """어느 작업자에게 맡길지 정한다.

    `agy`는 계정 할당량을 쓰는 원격 작업자, `local`은 이 PC의 Ollama 모델이다.
    할당량이 소진돼도 진행이 멈추지 않도록 두 번째 손을 둔다. 판정은 어느 쪽이든
    파일럿의 인수 검사와 게이트가 하므로, 작업자가 약해도 거짓 성공은 통과하지 못한다.
    """
    if explicit:
        return list(explicit)
    if worker in ("local", "cascade"):  # cascade starts on local; cmd_pilot_run switches to lane on REWORK
        return [sys.executable, str(Path(__file__).resolve().parent / "adapters" / "ollama_worker.py")]
    if worker == "lane":  # Claude Code's tool loop on the local model; kept beside "local" for the A/B
        return [sys.executable, str(Path(__file__).resolve().parent / "adapters" / "lane_worker.py")]
    if worker == "apply":  # U34: the commander already wrote the code; apply it without a model
        return [sys.executable, str(Path(__file__).resolve().parent / "adapters" / "apply_worker.py")]
    if worker == "claude":  # U38: Claude Code on the paid account, budget-gated (docs/40)
        return [sys.executable, str(Path(__file__).resolve().parent / "adapters" / "claude_worker.py")]
    return ["agy"]


def cmd_coord_log(args: argparse.Namespace) -> int:
    """U15: 조율 사건 한 줄을 스트림에 남긴다. 세 도구가 같은 입구를 쓴다."""
    from .coord.stream import StreamRejected, append_event

    evidence: dict[str, object] = {}
    if args.cmd:
        evidence["cmd"] = args.cmd
    if args.exit_code is not None:
        evidence["exit"] = args.exit_code
    if args.bundle:
        evidence["bundle"] = args.bundle
    try:
        event = append_event(
            Path(args.project),
            actor=args.actor,
            kind=args.kind,
            step=args.step,
            summary=args.summary,
            refs=args.ref,
            evidence=evidence or None,
        )
    except StreamRejected as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "id": event.id, "ts": event.ts}, ensure_ascii=False))
    return 0


def cmd_coord_status(args: argparse.Namespace) -> int:
    """Report coordinator and harness health status."""
    project = Path(args.project)
    lock_file = project / ".work" / "QUIET_LOCK"
    lock_status = "LOCKED" if lock_file.is_file() else "CLEAN"

    mailbox_dir = project / ".coord" / "mailbox" / "inbox"
    mailbox_count = len(list(mailbox_dir.glob("*.json"))) if mailbox_dir.is_dir() else 0

    from .coord.stream import StreamRejected, read_events

    try:
        stream_count = len(read_events(project))
    except StreamRejected as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    usage_file = project / ".coord" / "usage" / "runs.jsonl"
    usage_count = len(usage_file.read_text(encoding="utf-8").splitlines()) if usage_file.is_file() else 0

    out = {
        "ok": True,
        "lock": lock_status,
        "mailbox_pending": mailbox_count,
        "stream_events": stream_count,
        "ledger_entries": usage_count,
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


def cmd_coord_brief(args: argparse.Namespace) -> int:
    """U15: 스트림을 접어 Codex 브리핑을 만든다. 같은 입력이면 같은 결과다."""
    from .coord.brief import brief_hash, pending_from_plan, render_brief, write_brief

    project = Path(args.project)
    # 판정 대기를 손으로 넘기지 않으면 PLAN 상태 칸에서 읽는다. 사람이 넘기면 빠뜨린다.
    pending = list(args.pending) or pending_from_plan(project)
    text = render_brief(
        project,
        owner=args.owner,
        lock=args.lock,
        pending=pending,
        next_candidates=args.next,
    )
    if args.write:
        path = write_brief(project, text)
        print(json.dumps({"ok": True, "path": str(path), "hash": brief_hash(text)[:12], "lines": len(text.splitlines())}, ensure_ascii=False))
    else:
        print(text, end="")
    return 0


def cmd_coord_notify(args: argparse.Namespace) -> int:
    """U15: 브리핑이 바뀌었을 때만 Codex 대화창으로 한 건 보낸다. 기본은 드라이런이다."""
    from .coord.brief import pending_from_plan
    from .coord.notify import NotifyRefused, notify, resolve_thread

    project = Path(args.project)
    brief_file = project / ".coord" / "codex_brief.md"
    if not brief_file.is_file():
        print(json.dumps({"ok": False, "error": "BRIEF_MISSING"}, ensure_ascii=False))
        return 1

    thread = args.thread or resolve_thread(project)
    if not thread:
        # 스레드를 못 고르면 보내지 않는다. 엉뚱한 작업 창에 배달하는 것보다 안 보내는 편이 낫다.
        print(json.dumps({"ok": False, "error": "THREAD_UNRESOLVED"}, ensure_ascii=False))
        return 1

    vr_arg = getattr(args, "verdict_requested", "auto")
    vr_val = True if vr_arg == "yes" else (False if vr_arg == "no" else None)

    try:
        result = notify(
            project,
            thread=thread,
            actor=args.actor,
            brief_text=brief_file.read_text(encoding="utf-8"),
            headline=args.headline,
            pending=list(args.pending) or pending_from_plan(project),
            verdict_requested=vr_val,
            dry_run=not args.send,
        )
    except NotifyRefused as exc:
        print(json.dumps({"ok": False, "error": str(exc), "thread": thread}, ensure_ascii=False))
        return 1

    print(json.dumps({"ok": True, "sent": result.sent, "reason": result.reason, "thread": thread, "message": result.message}, ensure_ascii=False))
    return 0


def cmd_coord_archive(args: argparse.Namespace) -> int:
    """U15: 판정이 끝난 사건을 보관함으로 옮겨 현역 스트림을 짧게 유지한다."""
    from .coord.stream import archive_settled

    report = archive_settled(Path(args.project))
    print(json.dumps({"ok": True, **report}, ensure_ascii=False))
    return 0


def cmd_coord_deliver(args: argparse.Namespace) -> int:
    from .coord.deliver import deliver

    result = deliver(Path(args.project), message=args.message, actor=args.actor,
                     target=args.target, thread=args.thread)
    # U57-C: QUEUED_INTERACTIVE means a live `coord watch` holds the letter for the interactive session; not a failure.
    ok = result.reason in ("PUBLISHED", "DISPATCHED", "ACKED", "QUEUED_INTERACTIVE")
    print(json.dumps({"ok": ok, "target": result.target, "reason": result.reason,
                      "message_id": result.message_id, "digest": result.digest,
                      "receipt": result.receipt, "output": result.output[:500]}, ensure_ascii=False))
    return 0 if ok else 1


def cmd_coord_publish_thread(args: argparse.Namespace) -> int:
    """U24 / docs/24: 도구의 프로세스 대화를 Codex 데스크톱 프로젝트 대화로 편입·발행한다."""
    from .coord.codex_session_bridge import parse_transcript_to_turns, publish_codex_thread

    if args.transcript:
        turns = parse_transcript_to_turns(Path(args.transcript))
        if not turns:
            print(json.dumps({"ok": False, "error": "EMPTY_OR_INVALID_TRANSCRIPT"}, ensure_ascii=False))
            return 1
    else:
        resp_text = args.response or ""
        if args.response_file:
            resp_text = Path(args.response_file).read_text(encoding="utf-8")
        if not resp_text:
            print(json.dumps({"ok": False, "error": "MISSING_RESPONSE"}, ensure_ascii=False))
            return 1
        turns = [(args.prompt, resp_text)]

    result = publish_codex_thread(
        actor=args.actor,
        task_name=args.task,
        turns=turns,
        project_dir=Path(args.project),
        thread_id=args.thread_id,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


def cmd_coord_sentinel(args: argparse.Namespace) -> int:
    """U23 S4 / U32b: 0-token sentinel (deterministic rules, no model call) — one cycle or a resident loop."""
    import time
    from .coord.mailbox import Mailbox
    from .coord.sentinel import generate_briefing, run_sentinel_cycle

    project = Path(args.project)
    mailbox_dir = project / ".coord" / "mailbox"
    mailbox_dir.mkdir(parents=True, exist_ok=True)
    box = Mailbox(mailbox_dir)

    def _execute_once() -> dict[str, Any]:
        cycle_res = run_sentinel_cycle(project, box, recipient=args.recipient, ring=getattr(args, "ring", False))
        if args.write_brief:
            brief_text = generate_briefing(project, box=box)
            brief_file = project / ".coord" / "codex_brief.md"
            brief_file.parent.mkdir(parents=True, exist_ok=True)
            brief_file.write_text(brief_text, encoding="utf-8")
        return cycle_res

    log_path = Path(args.log) if getattr(args, "log", None) else None

    def _report(res: dict[str, Any]) -> None:
        line = json.dumps(res, ensure_ascii=False)
        print(line, flush=True)  # a no-op under pythonw, where stdout is None
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            # One line a minute is ~0.4 MB a day; keep one previous file instead of growing forever.
            if log_path.is_file() and log_path.stat().st_size > SENTINEL_LOG_MAX_BYTES:
                os.replace(log_path, log_path.with_name(log_path.name + ".1"))
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    if args.loop:
        # A logon task and a manual start must not run two operators on one project.
        from .coord.sentinel import _is_pid_alive

        pid_file = project / ".work" / "sentinel" / "loop.pid"
        try:
            running = int(pid_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            running = 0
        if running and running != os.getpid() and _is_pid_alive(running):
            _report({"ok": True, "skipped": "ALREADY_RUNNING", "pid": running})
            return 0
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(os.getpid()), encoding="utf-8")
        while True:
            # A resident operator must outlive one bad cycle (locked file, corrupt line); it reports and goes on.
            try:
                res = _execute_once()
            except Exception as exc:  # noqa: BLE001
                res = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
            _report(res)
            time.sleep(args.interval)
        return 0

    _report(_execute_once())
    return 0


def cmd_coord_presence(args: argparse.Namespace) -> int:
    """U32b: record one tool's heartbeat, or show all three. Called from each tool's session hooks."""
    from .coord.presence import conductor, mark, read_all

    say = getattr(args, "say", "json")

    def _emit(data: dict[str, Any], line: str = "") -> None:
        if say == "json":
            print(json.dumps(data, ensure_ascii=False))
        elif say in ("brief", "p1") and line:
            print(line)
        elif say == "empty-json":
            print("{}")

    if getattr(args, "from_hook", False):
        from .coord.hook_context import (
            brief_line,
            hook_project,
            p1_is_new,
            p1_line,
            read_stdin,
            retention_alert,
            retention_alert_is_new,
        )

        # A pilot worker (U38) runs inside a staged copy that holds .coord/PLAN.md; a hook there must write nothing.
        if os.environ.get("UAOS_WORKER"):
            _emit({"ok": True, "skipped": "UAOS_WORKER"})
            return 0
        # A session hook must never break the session: every failure is reported and the exit code stays 0.
        try:
            project = hook_project(read_stdin(), args.project)
            if project is None:
                _emit({"ok": True, "skipped": "NOT_A_UAOS_PROJECT"})
                return 0
            if args.tool and args.state:
                mark(project, args.tool, args.state, ttl_s=args.ttl)
            presence = read_all(project)
            line = p1_line(project, presence) if say == "p1" else brief_line(project, presence)
            if say == "brief":
                alert = retention_alert(project)
                if retention_alert_is_new(project, alert):
                    line = line + " " + alert
            elif say == "p1" and not p1_is_new(project, line):
                line = ""  # U46-P1: an unchanged P1 set is ACK_ONLY; it was repeated on every prompt
            _emit({"ok": True, "project": str(project), "presence": presence, "conductor": conductor(presence)}, line)
        except Exception as exc:  # noqa: BLE001
            _emit({"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]})
        return 0

    project = Path(args.project)
    if getattr(args, "if_uaos", False) and not (project / ".coord" / "PLAN.md").is_file():
        # Global hooks fire in every project; only UAOS projects get a presence file.
        _emit({"ok": True, "skipped": "NOT_A_UAOS_PROJECT"})
        return 0
    if args.tool or args.state:
        if not (args.tool and args.state):
            print(json.dumps({"ok": False, "error": "--tool and --state go together"}, ensure_ascii=False))
            return 2
        mark(project, args.tool, args.state, ttl_s=args.ttl, lease=getattr(args, "lease", False))
    presence = read_all(project)
    _emit({"ok": True, "presence": presence, "conductor": conductor(presence)})
    return 0


def cmd_coord_watch(args: argparse.Namespace) -> int:
    """U57-B: wait at zero model tokens until a new letter for one of the targets lands; exit 3 on timeout."""
    from .coord.watch import watch

    found = watch(Path(args.project), tuple(args.target), timeout_s=args.timeout, interval_s=args.interval)
    if found is None:
        print(json.dumps({"ok": False, "reason": "TIMEOUT", "targets": args.target}, ensure_ascii=False))
        return 3
    print(json.dumps({"ok": True, "reason": "NEW_LETTER", **found}, ensure_ascii=False))
    return 0


def cmd_coord_route(args: argparse.Namespace) -> int:
    """Choose authority from provider states; percentages and reset windows are never token balances."""
    from .budget_route import route_authority
    from .coord.presence import read_all

    presence = read_all(Path(args.project))
    states = {tool: (presence.get(tool) or {}).get("state", "UNKNOWN")
              for tool in ("codex", "claude", "antigravity")}
    authority = route_authority(states["codex"], states["claude"], states["antigravity"])
    print(json.dumps({"ok": not authority.startswith("BLOCKED_"), "authority": authority,
                      "states": states, "quota_conversion": "FORBIDDEN"}, ensure_ascii=False))
    return 0 if not authority.startswith("BLOCKED_") else 1


SENTINEL_LOG_MAX_BYTES = 5 * 1024 * 1024

UAOS_GITIGNORE_LINES = (
    ".work/",
    ".coord/pilot/",
    ".coord/stream/",
    ".coord/codex_brief.md",
    ".coord/mailbox/",
    ".coord/presence/",
    ".coord/usage/runs.jsonl",
)

PLAN_TEMPLATE = """# 통합 실행 계획 (UAOS)

상태 기준: `READY → ACTIVE → REVIEW → DONE`. 한 번에 활성 단계 하나, 단계마다 소유자 한 명.

| ID | 상태 | 소유자 | 산출물/판정 |
|---|---|---|---|
| S01 | READY | (지휘자) | 첫 단계: 인수 명령을 먼저 정한다 |

도구 상태(시각이 지나면 UNKNOWN): `python -m v7_harness.cli coord presence`로 확인한다.
"""

PROJECT_MANUAL_TEMPLATE = """# 프로젝트 총괄 매뉴얼 (UAOS Project Manual)

- work_id: PROJECT
- 프로젝트 목표: 프로젝트 전체 목적과 해결 과제를 정의한다.
- 승인 경계: 데이터 삭제, push·배포, 결제, 권한 변경은 사용자 승인 필수.
- 권한 상태기계: Codex ACTIVE → Claude ACTIVE → 둘 다 LIMITED/ABSENT일 때 Antigravity ACTIVE. UNKNOWN은 fail-closed.
- 예산: 잔여율·리셋 창을 토큰으로 환산하지 않고, 호출별 token/USD/time 상한을 각각 집행한다.
- 위임: 계약 파일을 먼저 발행·lint하고 그 내용 전체를 호출에 포함한다.
- 단일 원장: `.coord/PLAN.md`; 작성자와 최종 판정자는 분리한다.
- 보존: archive candidate와 복구 manifest만 만들고 실제 삭제는 별도 최신 승인을 요구한다.

## Goal
One sentence: what is done when this project is done.

## Scope
Files and folders the tools may change.

## Forbidden
Actions that always need the user: deletion, push/deploy/publish, payment, account/permission/credential changes.

## Gates
The commands that decide done (tests, checks). A step without a gate is unmeasured.

## Workers
Who does what: apply (0 tokens) when the code is known, Ollama for narrow mechanical work, Antigravity or `worker: claude` with a token and dollar cap for judgment work.

## Judge
The tool that approves, never the author of the same change.
"""

CONTRACT_MANUAL_TEMPLATE = "Generated per project by cmd_coord_init with a pinned .coord/PLAN.md hash."


def cmd_coord_init(args: argparse.Namespace) -> int:
    """Prepare any project for UAOS. Idempotent: existing files are never overwritten, only missing lines are added."""
    project = Path(args.project)
    if not project.is_dir():
        print(json.dumps({"ok": False, "error": f"not a directory: {project}"}, ensure_ascii=False))
        return 1
    created: list[str] = []
    plan = project / ".coord" / "PLAN.md"
    if not plan.is_file():
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text(PLAN_TEMPLATE, encoding="utf-8")
        created.append(".coord/PLAN.md")
    project_manual = project / ".coord" / "PROJECT_MANUAL.md"
    if not project_manual.is_file():
        project_manual.write_text(PROJECT_MANUAL_TEMPLATE, encoding="utf-8")
        created.append(".coord/PROJECT_MANUAL.md")
    for folder in (".coord/tasks", ".coord/mailbox", ".work"):
        if not (project / folder).is_dir():
            (project / folder).mkdir(parents=True)
            created.append(folder + "/")
    task_tpl = project / ".coord" / "tasks" / "contract_template.md"
    if not task_tpl.is_file():
        from .manual import new_manual

        task_tpl.parent.mkdir(parents=True, exist_ok=True)
        task_tpl.write_text(new_manual(
            project,
            work_id="T01_EXTRACT_READY_ID",
            worker="local",
            goal="Extract the first exact READY work item ID from `.coord/PLAN.md` into `.work/T01-result.txt`.",
            inputs=[".coord/PLAN.md"],
            allow=[".work/T01-result.txt"],
            acceptance='python -c "from pathlib import Path; assert Path(\'.work/T01-result.txt\').is_file()"',
            judge="codex",
            timeout_s=300,
        ), encoding="utf-8")
        created.append(".coord/tasks/contract_template.md")
    gitignore = project / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.is_file() else []
    missing = [line for line in UAOS_GITIGNORE_LINES if line not in existing]
    if missing:
        prefix = "" if not existing or existing[-1] == "" else "\n"
        with gitignore.open("a", encoding="utf-8") as handle:
            handle.write(prefix + "# UAOS runtime state (coord init)\n" + "\n".join(missing) + "\n")
    print(json.dumps({"ok": True, "created": created, "gitignore_added": missing,
                      "contract_manuals": ".coord/tasks/<work_id>-manual.md",
                      "next": ["coord presence --tool <codex|claude|antigravity> --state ACTIVE",
                               "fill .coord/PROJECT_MANUAL.md (big picture) before the first delegation",
                               "pilot manual new ... then pilot manual lint ... then pilot run --manual ..."]},
                     ensure_ascii=False))
    return 0


def cmd_coord_inbox(args: argparse.Namespace) -> int:
    """U32b: list what waits in the voicemail without claiming it."""
    from .coord.mailbox import Mailbox

    mailbox_dir = Path(args.project) / ".coord" / "mailbox"
    if not mailbox_dir.is_dir():
        print(json.dumps({"ok": True, "messages": [], "bad": []}, ensure_ascii=False))
        return 0
    box = Mailbox(mailbox_dir)
    messages = []
    for message_id, payload in box.peek():
        data = payload if isinstance(payload, dict) else {}
        messages.append({
            "id": message_id,
            "kind": data.get("kind") or ("P1" if data.get("p1_alert") else None),
            "step": data.get("step"),
            "summary": data.get("summary") or data.get("wake_reason"),
        })
    print(json.dumps({"ok": True, "messages": messages, "bad": box.list_bad()}, ensure_ascii=False))
    return 0


def cmd_coord_ack(args: argparse.Namespace) -> int:
    """U32b: mark one voicemail message as handled so it stops showing up in briefs and bells."""
    from .coord.mailbox import Mailbox, MailboxRejected

    box = Mailbox(Path(args.project) / ".coord" / "mailbox")
    claim = box.claim(args.message_id, consumer_id=args.consumer)
    if claim is None:
        already = (box.ack_dir / f"{args.message_id}.json").is_file()
        print(json.dumps({"ok": already, "id": args.message_id,
                          "error": None if already else "NOT_IN_INBOX"}, ensure_ascii=False))
        return 0 if already else 1
    try:
        box.ack(claim)
    except (MailboxRejected, OSError) as exc:
        box.nack(claim)
        print(json.dumps({"ok": False, "id": args.message_id, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "id": args.message_id}, ensure_ascii=False))
    return 0


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_rsi_report(args: argparse.Namespace) -> int:
    from .olla import USAGE_LOG
    from .rsi import analyze, load_policy, load_rows, local_usage, open_trials, read_decisions

    project = Path(args.project)
    policy = load_policy(project)
    rows = load_rows(project)
    report = analyze(rows, policy)
    # U47-D1: the local model's real work (fake 1/1 rows excluded), joined to the pilot ledger by work_id.
    report["local"] = local_usage(USAGE_LOG, rows)
    report["policy"] = policy
    report["decisions"] = len(read_decisions(project))
    # An adopted change whose window is complete is due for its re-check: keep it or `rsi rollback`.
    report["trials"] = open_trials(project, rows)
    _print_json(report)
    return 0


def cmd_rsi_propose(args: argparse.Namespace) -> int:
    from .rsi import analyze, candidate_template, load_policy, load_rows, propose

    project = Path(args.project)
    policy = load_policy(project)
    proposals = propose(analyze(load_rows(project), policy), policy)
    if args.candidate_for:
        match = [proposal for proposal in proposals if proposal["id"] == args.candidate_for]
        if not match:
            _print_json({"ok": False, "error": f"unknown proposal id: {args.candidate_for}"})
            return 1
        _print_json(candidate_template(match[0], args.author or detect_actor() or "unknown"))
        return 0
    _print_json({"proposals": proposals,
                 "next": "try one proposal on a trial manual, then `rsi gate --candidate FILE` and hand it to the judge"})
    return 0


def _read_candidate(path: str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("the candidate file must hold a JSON object")
    return data


def cmd_rsi_gate(args: argparse.Namespace) -> int:
    from .rsi import gate_from_ledger

    try:
        candidate = _read_candidate(args.candidate)
    except (OSError, ValueError) as exc:
        _print_json({"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]})
        return 1
    verdict = gate_from_ledger(Path(args.project), candidate)
    _print_json(verdict)
    return 0 if verdict["decision"] == "ADOPT_CANDIDATE" else 2


def cmd_rsi_adopt(args: argparse.Namespace) -> int:
    from .rsi import RsiRefused, adopt

    try:
        result = adopt(Path(args.project), _read_candidate(args.candidate), args.judge)
    except RsiRefused as exc:
        # B83: always refused; the evidence and the proposed file go into a PLAN card instead.
        _print_json({"ok": False, "error": str(exc)[:500], "evidence": exc.evidence,
                     "proposed_policy_json": exc.proposed_policy})
        return 2
    except (OSError, ValueError) as exc:
        _print_json({"ok": False, "error": str(exc)[:500]})
        return 2
    _print_json({"ok": True, **result})
    return 0


def cmd_rsi_rollback(args: argparse.Namespace) -> int:
    from .rsi import RsiRefused, rollback

    try:
        result = rollback(Path(args.project), args.judge, args.reason)
    except RsiRefused as exc:
        _print_json({"ok": False, "error": str(exc), "proposed_policy_json": exc.proposed_policy})
        return 2
    _print_json({"ok": True, **result})
    return 0


def cmd_rsi_watch(args: argparse.Namespace) -> int:
    import time
    from .rsi_release import run_scheduler_cycle

    project = Path(args.project)
    config_path = Path(args.config) if args.config else project / ".coord" / "rsi" / "watcher.json"
    if not config_path.is_file():
        config = {
            "interval_seconds": 86400,
            "timeout_seconds": 15,
            "max_retries": 3,
            "backoff_base_seconds": 60,
            "lock_ttl_seconds": 3600,
            "sources": [],
        }
    else:
        config = json.loads(config_path.read_text(encoding="utf-8"))

    def _record(event: dict[str, Any]) -> None:
        # A quiet local scheduler still leaves one line when it recovers a dead/stale lock.
        print(json.dumps({"scheduler_event": event}, ensure_ascii=False))

    res = run_scheduler_cycle(project, config, now=time.time(), sleeper=time.sleep, record=_record)
    _print_json(res)
    return 0 if res.get("status") in ("ACK_ONLY", "ACTIONABLE_DELTA") else 1


def cmd_rsi_retention(args: argparse.Namespace) -> int:
    import time

    from . import olla
    from .retention import (
        RetentionRefused,
        apply_retention,
        archive_candidates,
        default_policy,
        plan_retention,
        purge_archived,
        rollup_jsonl,
        work_dir_report,
    )

    now = time.time()
    project = Path(args.project)
    policy = default_policy()
    plan = plan_retention(project, policy, now=now)
    result = apply_retention(project, plan)
    out: dict = {"ok": True, **result}

    if getattr(args, "archive", False):
        out["archive"] = archive_candidates(project, plan, now=now)

    if getattr(args, "rollup_olla", False):
        out["rollup"] = rollup_jsonl(olla.USAGE_LOG, olla.USAGE_LOG.parent / "archive")

    if getattr(args, "purge", None):
        approval_path = Path(args.approval) if getattr(args, "approval", None) else project / "unused_approval.json"
        try:
            purge_archived(project, Path(args.purge), approval_path)
        except RetentionRefused as exc:
            _print_json({
                "ok": False,
                "status": "FRESH_DELETE_APPROVAL_REQUIRED",
                "error": str(exc),
                "purge": {"status": "REFUSED", "deleted": 0},
            })
            return 2
        raise AssertionError("purge_archived must always fail closed")

    out["work_report"] = work_dir_report(project, now=now)
    _print_json(out)
    return 0


def cmd_rsi_prepare(args: argparse.Namespace) -> int:
    from .rsi_release import ReleaseRefused, prepare_release

    project = Path(args.project)
    packet = json.loads(Path(args.packet).read_text(encoding="utf-8"))
    try:
        plan = prepare_release(project, packet, apply=args.apply, date=args.date)
    except (ReleaseRefused, ValueError) as exc:
        _print_json({"ok": False, "error": str(exc)})
        return 1
    _print_json({"ok": True, **plan})
    return 0


def cmd_rsi_ship(args: argparse.Namespace) -> int:
    from .rsi_release import ReleaseRefused, ship_release

    project = Path(args.project)
    packet = json.loads(Path(args.packet).read_text(encoding="utf-8"))
    approval = json.loads(Path(args.approval).read_text(encoding="utf-8"))
    try:
        res = ship_release(project, packet, approval, execute=args.execute)
    except (ReleaseRefused, ValueError) as exc:
        _print_json({"ok": False, "error": str(exc)})
        return 1
    _print_json({"ok": True, **res})
    return 0


def cmd_rsi_schedule(args: argparse.Namespace) -> int:
    from .rsi_release import windows_schedule

    project = Path(args.project)
    python_bin = args.python_bin or sys.executable
    res = windows_schedule(project, python_bin, action=args.action, apply=args.apply)
    _print_json(res)
    return 0 if res.get("status") == "DRY_RUN" or res.get("ok") else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    # Windows 콘솔 기본(cp949)에서는 `coord brief` 등의 한국어가 깨진다. olla.main 과 같은 처리.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
===FILE: v7_harness/coord/hook_context.py===
"""Find the UAOS project a tool's session hook fired for, and say one line about it.

Global hooks fire in every project, from wherever the tool chose to run them:
- Claude Code passes `cwd` on stdin and sets CLAUDE_PROJECT_DIR.
- Codex passes `cwd` on stdin (SessionStart, UserPromptSubmit).
- Antigravity runs hooks inside ~/.gemini/config/ (antigravity-cli#1005) and passes `workspacePaths` on stdin (#893).
So the project comes from the payload first, the environment second and the current folder last, and the search walks
up to the folder that holds `.coord/PLAN.md` (a session may start in a subfolder). No such folder means no UAOS project,
and the hook stays silent: other projects pay nothing, not even a line of context.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, Iterable

PLAN = Path(".coord") / "PLAN.md"
_PAYLOAD_KEYS = ("cwd", "workspacePaths", "workspace_paths", "workspaceRoots", "workspace_roots", "project_dir")


def read_stdin(timeout_s: float = 2.0) -> str:
    """The hook payload, or "" for a terminal or a runner that never closes stdin."""
    stream = sys.stdin
    if stream is None or stream.closed:
        return ""
    try:
        if stream.isatty():
            return ""
    except (ValueError, OSError):
        return ""
    box: list[str] = []

    def _read() -> None:
        try:
            box.append(stream.read())
        except (OSError, ValueError, UnicodeDecodeError):
            box.append("")

    reader = threading.Thread(target=_read, daemon=True)
    reader.start()
    reader.join(timeout_s)
    return box[0] if box else ""


def payload_candidates(stdin_text: str) -> list[str]:
    try:
        payload = json.loads(stdin_text) if stdin_text.strip() else {}
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    found: list[str] = []
    for key in _PAYLOAD_KEYS:
        value = payload.get(key)
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, dict):
                item = item.get("path") or item.get("uri")
            if isinstance(item, str) and item.strip():
                item = item.removeprefix("file://")
                # file:///C:/work becomes /C:/work; the drive letter needs the leading slash removed on Windows.
                if len(item) > 2 and item[0] == "/" and item[2] == ":" and item[1].isalpha():
                    item = item[1:]
                found.append(item)
    return found


def find_project(candidates: Iterable[str | Path], max_depth: int = 25) -> Path | None:
    for candidate in candidates:
        try:
            current = Path(candidate).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            continue
        for _ in range(max_depth):
            if (current / PLAN).is_file():
                return current
            if current.parent == current:
                break
            current = current.parent
    return None


def hook_project(stdin_text: str, fallback: str | Path | None, env: dict[str, str] | None = None) -> Path | None:
    env = os.environ if env is None else env
    candidates: list[str | Path] = payload_candidates(stdin_text)
    if env.get("CLAUDE_PROJECT_DIR"):
        candidates.append(env["CLAUDE_PROJECT_DIR"])
    if fallback is not None:
        candidates.append(fallback)
    return find_project(candidates)


def brief_line(project: Path, presence: dict[str, Any]) -> str:
    """One line of session context (a SessionStart hook's stdout becomes context in Claude Code and Codex)."""
    inbox: list[str] = []
    box_dir = Path(project) / ".coord" / "mailbox" / "inbox"
    if box_dir.is_dir():
        inbox = sorted(path.stem for path in box_dir.glob("*.json"))
    wakes = sum(1 for item in inbox if item.startswith("wake_"))
    reviews = sum(1 for item in inbox if item.startswith("rsi_review_"))
    desk = ", ".join(f"{tool}={info.get('state')}" for tool, info in presence.items())
    return (f"UAOS project {Path(project).name}: inbox {len(inbox)} (P1 {wakes}, RSI reviews {reviews}); desk {desk}. "
            "Read .coord/PLAN.md; `coord inbox` lists what waits. "
            # U57-B: the only way a session wakes on a letter without the user relaying or approving it.
            "Keep `coord watch --target <you>` running in the background; send by `coord deliver`, never via the user."
            )[:400]


def p1_line(project: Path, presence: dict[str, Any]) -> str:
    """U38: the P1 hand-off to Claude while Codex is away. Empty unless a wake waits and Codex is not ACTIVE, so an
    ordinary prompt carries nothing (a hook's stdout on UserPromptSubmit is added to the prompt)."""
    if (presence.get("codex") or {}).get("state") == "ACTIVE":
        return ""  # the sentinel rings Codex itself (codex queue)
    box_dir = Path(project) / ".coord" / "mailbox" / "inbox"
    wakes = sorted(box_dir.glob("wake_*.json")) if box_dir.is_dir() else []
    if not wakes:
        return ""
    reason = ""
    try:
        data = json.loads(wakes[0].read_text(encoding="utf-8"))
        payload = data.get("payload") if isinstance(data, dict) else None
        if isinstance(payload, dict):
            reason = str(payload.get("wake_reason") or "")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        pass
    codex = (presence.get("codex") or {}).get("state", "UNKNOWN")
    return (f"UAOS P1 waiting ({len(wakes)}), Codex {codex}: {reason or 'see mailbox'}. Claude acts as deputy: "
            "`coord inbox`, handle it, then `coord ack --id <id>`.")[:400]


# Runtime state beside the presence files (.coord/presence/ is git-ignored); presence reads only <tool>.json.
P1_SEEN = Path(".coord") / "presence" / "p1_hook_seen.txt"


def p1_is_new(project: Path, line: str) -> bool:
    """U46-P1: say a P1 line only when it differs from the last one said. The line carries the wake count, Codex's
    state and the first reason, and the fingerprint adds the wake ids, so any new wake or state change speaks again."""
    if not line:
        return False
    box_dir = Path(project) / ".coord" / "mailbox" / "inbox"
    ids = sorted(path.stem for path in box_dir.glob("wake_*.json")) if box_dir.is_dir() else []
    fingerprint = hashlib.sha256("\n".join([line, *ids]).encode("utf-8")).hexdigest()
    seen = Path(project) / P1_SEEN
    try:
        if seen.read_text(encoding="utf-8").strip() == fingerprint:
            return False
    except OSError:
        pass
    try:
        seen.parent.mkdir(parents=True, exist_ok=True)
        seen.write_text(fingerprint, encoding="utf-8")
    except OSError:
        pass  # a hook never fails the session; the line is said again next time
    return True


RETENTION_SEEN = Path(".coord") / "presence" / "retention_seen.txt"


def _scan_zone(target_path: Path | str) -> tuple[int, int]:
    count = 0
    total_bytes = 0
    stack = [str(target_path)]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            count += 1
                            total_bytes += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return count, total_bytes


def retention_alert(project: Path | str, policy: dict[str, Any] | None = None) -> str:
    """Walk retention zones with stat only and return an alert line if any zone exceeds count or byte caps."""
    if policy is None:
        from v7_harness.retention import default_policy
        policy = default_policy()

    root = Path(project)
    over_cap: list[str] = []

    for zone in policy.get("zones", []):
        zone_path = zone.get("path")
        if not zone_path:
            continue
        target = root / zone_path
        if not target.is_dir():
            continue
        count, total_bytes = _scan_zone(target)
        max_count = zone.get("max_count")
        max_bytes = zone.get("max_bytes")

        is_over_count = max_count is not None and count > max_count
        is_over_bytes = max_bytes is not None and total_bytes > max_bytes

        if is_over_count or is_over_bytes:
            cur_mb = round(total_bytes / 10**6, 1)
            max_mb = round((max_bytes or 0) / 10**6, 1)
            cur_mb_s = f"{int(cur_mb) if cur_mb.is_integer() else cur_mb}"
            max_mb_s = f"{int(max_mb) if max_mb.is_integer() else max_mb}"
            over_cap.append(f"{zone_path} {count}/{max_count} files, {cur_mb_s}/{max_mb_s} MB")

    if not over_cap:
        return ""

    line = f"UAOS retention: {'; '.join(over_cap)} - run `rsi retention` (dry run), then `--archive`"
    line = line.replace("\n", " ")
    return line[:299]


def retention_alert_is_new(project: Path | str, line: str) -> bool:
    """Say a retention alert line only when it differs from the last one said."""
    if not line:
        return False
    fingerprint = hashlib.sha256(line.encode("utf-8")).hexdigest()
    seen = Path(project) / RETENTION_SEEN
    try:
        if seen.read_text(encoding="utf-8").strip() == fingerprint:
            return False
    except OSError:
        pass
    try:
        seen.parent.mkdir(parents=True, exist_ok=True)
        seen.write_text(fingerprint, encoding="utf-8")
    except OSError:
        pass  # a hook never fails the session
    return True
===FILE: v7_harness/coord/watch.py===
"""U57: `coord watch` — block until a new mailbox letter for a tool arrives, at zero model tokens.

Why (2026-09-27/28): an interactive session wakes only on a user prompt. Letters between Claude sessions were held
by the app for the user's approval (sessions with different permission modes), one expired unseen, and the acting
conductor had to hand-write a shell loop over the inbox to be woken. The user then had to approve or copy messages.
This makes that loop a tested harness command: a session runs it in the background, and it exits when a letter for
its tool lands, so the session wakes without the user.

While a watch runs it keeps `.coord/presence/<tool>.watch.json` fresh. `coord deliver` reads that file: a live
watcher means an interactive session is listening, so the letter is left in the inbox for it (QUEUED_INTERACTIVE)
instead of starting a cold headless session that cannot see the conversation.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from v7_harness.coord.mailbox import Mailbox
from v7_harness.coord.presence import PRESENCE_DIR, TOOLS

# 30 s between inbox scans: the hand-written loop used 30 s on 2026-09-27 and a letter waited at most that long;
# one scan lists one directory, so a shorter interval costs only disk reads, never tokens.
DEFAULT_INTERVAL_S = 30.0
# 4 h per watch: the longest single wait seen on 2026-09-27 (Codex quota window). The session re-arms it after.
DEFAULT_TIMEOUT_S = 4 * 3600.0
# A watcher counts as live for three missed scans, and never less than 90 s, so one slow scan does not make
# `coord deliver` fall back to a cold session while the watcher is still running.
LIVE_SCANS = 3
LIVE_MIN_S = 90.0


def watch_file(project: Path, tool: str) -> Path:
    if tool not in TOOLS:
        raise ValueError(f"unknown tool: {tool}")
    return Path(project) / PRESENCE_DIR / f"{tool}.watch.json"


def _beat(project: Path, tools: tuple[str, ...], token: str, interval_s: float, moment: float) -> None:
    live_for = max(LIVE_SCANS * interval_s, LIVE_MIN_S)
    for tool in tools:
        target = watch_file(project, tool)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps({"tool": tool, "token": token, "pid": os.getpid(),
                                   "expires_at": moment + live_for}), encoding="utf-8")
        os.replace(tmp, target)


def _clear(project: Path, tools: tuple[str, ...], token: str) -> None:
    """Remove only this watch's files; a newer watch for the same tool keeps its own."""
    for tool in tools:
        target = watch_file(project, tool)
        try:
            if json.loads(target.read_text(encoding="utf-8")).get("token") == token:
                target.unlink(missing_ok=True)
        except (OSError, ValueError, AttributeError):
            pass


def watcher_live(project: Path, tool: str, *, now: float | None = None) -> bool:
    moment = time.time() if now is None else now
    try:
        record = json.loads(watch_file(project, tool).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    expires_at = record.get("expires_at") if isinstance(record, dict) else None
    return isinstance(expires_at, (int, float)) and not isinstance(expires_at, bool) and expires_at > moment


def _addressed(payload: Any, tools: tuple[str, ...]) -> bool:
    if not isinstance(payload, dict):
        return False
    return payload.get("requested_target") in tools or payload.get("to") in tools


def watch(project: Path, tools: tuple[str, ...], *, timeout_s: float = DEFAULT_TIMEOUT_S,
          interval_s: float = DEFAULT_INTERVAL_S, clock: Callable[[], float] | None = None,
          sleep: Callable[[float], None] | None = None) -> dict[str, Any] | None:
    """Return the first letter addressed to one of `tools` that was not in the inbox when the watch began.

    Letters already waiting are what `coord inbox` shows at session start; the watch reports only new ones, so a
    re-armed watch never wakes the session twice for the same letter. None means the timeout passed.
    """
    clock = clock or time.time
    sleep = sleep or time.sleep  # looked up per call so tests and callers can patch time.sleep
    for tool in tools:
        watch_file(project, tool)  # validates the name before anything is written
    box = Mailbox(Path(project) / ".coord" / "mailbox")
    seen = set(box.list_inbox())
    token = uuid.uuid4().hex
    deadline = clock() + timeout_s
    try:
        while True:
            _beat(project, tools, token, interval_s, clock())
            for message_id, payload in box.peek():
                if message_id in seen:
                    continue
                seen.add(message_id)
                if _addressed(payload, tools):
                    body = payload if isinstance(payload, dict) else {}
                    return {"id": message_id, "kind": body.get("kind"), "actor": body.get("actor"),
                            "requested_target": body.get("requested_target") or body.get("to")}
            if clock() >= deadline:
                return None
            sleep(interval_s)
    finally:
        _clear(project, tools, token)
===FILE: tests/test_u57_desk_signals.py===
"""U57: desk signals that stop the user from relaying, approving, or copy-pasting between sessions (2026-09-28).

A. A Codex heartbeat written for a prompt that Codex then refused with usage_limit_exceeded reads LIMITED.
B. `coord watch` wakes on a new letter for its tool at zero model tokens, and times out with exit 3.
C. `coord deliver` to Claude leaves the letter queued while an interactive session watches, instead of cold `claude -p`.
D. `coord presence --lease` writes the lease that a later ACTIVE heartbeat cannot overwrite.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from v7_harness.cli import main
from v7_harness.coord import presence
from v7_harness.coord.deliver import deliver
from v7_harness.coord.mailbox import Mailbox
from v7_harness.coord.watch import watch, watch_file, watcher_live


def _rollout(root: Path, completed_at: float, error: dict | None, name: str = "a") -> Path:
    day = datetime.fromtimestamp(completed_at)
    folder = root / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"rollout-{name}.jsonl"
    event = {"type": "event_msg", "payload": {"type": "task_complete", "completed_at": int(completed_at),
                                              "started_at": int(completed_at) - 5}}
    if error is not None:
        event["payload"]["error"] = error
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"type": "event_msg", "payload": {"type": "user_message"}}) + "\n")
        handle.write(json.dumps(event) + "\n")
    return path


def _refusal(reset: datetime) -> dict:
    clock = reset.strftime("%I:%M %p").lstrip("0")
    return {"message": f"You've hit your usage limit. ... or try again at {clock}.",
            "codex_error_info": "usage_limit_exceeded"}


class _Project(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord" / "mailbox").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        self.sessions = Path(self._tmp.name) / "codex_sessions"
        self.sessions.mkdir()
        self._env = patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(self.sessions)})
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()
        self._tmp.cleanup()


class TestCodexQuotaEvidence(_Project):
    def test_refused_prompt_reads_limited_until_reset(self):
        now = time.time()
        # the heartbeat outlives the reset so the last assertion sees ACTIVE, not an expired UNKNOWN
        presence.mark(self.project, "codex", "ACTIVE", now=now - 10, ttl_s=4 * 3600)
        reset = (datetime.fromtimestamp(now) + timedelta(hours=2)).replace(second=0, microsecond=0)
        _rollout(self.sessions, now - 5, _refusal(reset))
        state = presence.read(self.project, "codex", now=now)
        self.assertEqual("LIMITED", state["state"])
        self.assertEqual("usage_limit_exceeded", state["evidence"]["reason"])
        self.assertAlmostEqual(reset.timestamp(), state["expires_at"], delta=1)
        # after the reset the same heartbeat is ACTIVE again
        self.assertEqual("ACTIVE", presence.read(self.project, "codex", now=reset.timestamp() + 1)["state"])

    def test_reset_clock_before_refusal_rolls_to_next_day(self):
        now = time.time()
        presence.mark(self.project, "codex", "ACTIVE", now=now - 10)
        earlier = (datetime.fromtimestamp(now) - timedelta(hours=1)).replace(second=0, microsecond=0)
        _rollout(self.sessions, now - 5, _refusal(earlier))
        state = presence.read(self.project, "codex", now=now)
        self.assertEqual("LIMITED", state["state"])
        self.assertAlmostEqual((earlier + timedelta(days=1)).timestamp(), state["expires_at"], delta=3700)
        self.assertGreater(state["expires_at"], now)

    def test_heartbeat_newer_than_refusal_stays_active(self):
        now = time.time()
        reset = datetime.fromtimestamp(now) + timedelta(hours=2)
        _rollout(self.sessions, now - 600, _refusal(reset))
        presence.mark(self.project, "codex", "ACTIVE", now=now - 10)
        self.assertEqual("ACTIVE", presence.read(self.project, "codex", now=now)["state"])

    def test_successful_turn_after_refusal_stays_active(self):
        now = time.time()
        presence.mark(self.project, "codex", "ACTIVE", now=now - 100)
        _rollout(self.sessions, now - 90, _refusal(datetime.fromtimestamp(now) + timedelta(hours=2)), name="a")
        _rollout(self.sessions, now - 20, None, name="b")
        os.utime(next(self.sessions.rglob("rollout-b.jsonl")), (now, now))
        self.assertEqual("ACTIVE", presence.read(self.project, "codex", now=now)["state"])

    def test_missing_or_bad_logs_change_nothing(self):
        now = time.time()
        presence.mark(self.project, "codex", "ACTIVE", now=now - 10)
        self.assertEqual("ACTIVE", presence.read(self.project, "codex", now=now)["state"])
        folder = self.sessions / "2026" / "09" / "28"
        folder.mkdir(parents=True)
        (folder / "rollout-x.jsonl").write_bytes(b"\xff\xfe not json \"task_complete\"\n")
        self.assertEqual("ACTIVE", presence.read(self.project, "codex", now=now)["state"])

    def test_route_goes_to_claude_after_refusal(self):
        now = time.time()
        presence.mark(self.project, "codex", "ACTIVE", now=now - 10)
        presence.mark(self.project, "claude", "ACTIVE", now=now - 10)
        _rollout(self.sessions, now - 5, _refusal(datetime.fromtimestamp(now) + timedelta(hours=1)))
        self.assertEqual("claude", presence.conductor(presence.read_all(self.project, now=now))["conductor"])

    def test_other_tools_ignore_codex_logs(self):
        now = time.time()
        presence.mark(self.project, "claude", "ACTIVE", now=now - 10)
        _rollout(self.sessions, now - 5, _refusal(datetime.fromtimestamp(now) + timedelta(hours=1)))
        self.assertEqual("ACTIVE", presence.read(self.project, "claude", now=now)["state"])


class TestWatch(_Project):
    def _letter(self, message_id: str, target: str) -> None:
        Mailbox(self.project / ".coord" / "mailbox").publish(
            message_id, {"kind": "NOTE", "actor": "claude", "requested_target": target, "message": "x"})

    def test_returns_new_letter_for_target_and_ignores_old_and_others(self):
        self._letter("old_letter", "claude")
        ticks = {"n": 0}

        def sleep(_s):
            ticks["n"] += 1
            self.assertTrue(watcher_live(self.project, "claude"))
            if ticks["n"] == 1:
                self._letter("for_codex", "codex")
            elif ticks["n"] == 2:
                self._letter("for_claude", "claude")

        found = watch(self.project, ("claude",), timeout_s=60, interval_s=1, sleep=sleep)
        self.assertEqual("for_claude", found["id"])
        self.assertEqual("claude", found["requested_target"])
        self.assertFalse(watch_file(self.project, "claude").exists())

    def test_timeout_returns_none_and_clears_watch_file(self):
        clock = {"t": 1000.0}

        def sleep(s):
            clock["t"] += s

        self.assertIsNone(watch(self.project, ("claude",), timeout_s=5, interval_s=2,
                                clock=lambda: clock["t"], sleep=sleep))
        self.assertFalse(watch_file(self.project, "claude").exists())
        self.assertFalse(watcher_live(self.project, "claude"))

    def test_cli_timeout_exit_3_and_new_letter_exit_0(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["coord", "watch", "--project", str(self.project), "--target", "claude",
                         "--timeout", "0", "--interval", "0.01"])
        self.assertEqual(3, code)
        self.assertEqual("TIMEOUT", json.loads(out.getvalue())["reason"])

        def sleep(_s):
            self._letter("wake_me", "codex")

        out = io.StringIO()
        with patch("v7_harness.coord.watch.time.sleep", sleep), redirect_stdout(out):
            code = main(["coord", "watch", "--project", str(self.project), "--target", "claude",
                         "--target", "codex", "--timeout", "30", "--interval", "0.01"])
        self.assertEqual(0, code)
        self.assertEqual("wake_me", json.loads(out.getvalue())["id"])

    def test_unknown_tool_rejected_before_writing(self):
        with self.assertRaises(ValueError):
            watch(self.project, ("nobody",), timeout_s=0)
        self.assertFalse((self.project / ".coord" / "presence").exists())

    def test_expired_watch_file_is_not_live(self):
        target = watch_file(self.project, "claude")
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps({"expires_at": time.time() - 1}), encoding="utf-8")
        self.assertFalse(watcher_live(self.project, "claude"))
        target.write_text("not json", encoding="utf-8")
        self.assertFalse(watcher_live(self.project, "claude"))


class _Runner:
    def __init__(self):
        self.calls = []

    def __call__(self, command, **_kw):
        self.calls.append(command)
        raise AssertionError("a cold session must not start while a watcher is live")


class TestDeliverQueuesForWatcher(_Project):
    def _live_watch(self) -> None:
        target = watch_file(self.project, "claude")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"tool": "claude", "token": "t", "expires_at": time.time() + 300}),
                          encoding="utf-8")

    def test_explicit_claude_target_is_queued(self):
        self._live_watch()
        runner = _Runner()
        with patch("v7_harness.coord.deliver.shutil.which", return_value="claude"):
            result = deliver(self.project, message="U57 queued", actor="codex", target="claude", runner=runner)
        self.assertEqual("QUEUED_INTERACTIVE", result.reason)
        self.assertEqual([], runner.calls)
        self.assertIn(result.message_id, Mailbox(self.project / ".coord" / "mailbox").list_inbox())

    def test_auto_route_to_claude_is_queued(self):
        self._live_watch()
        presence.mark(self.project, "codex", "LIMITED")
        presence.mark(self.project, "claude", "ACTIVE")
        runner = _Runner()
        result = deliver(self.project, message="U57 auto", actor="antigravity", runner=runner)
        self.assertEqual(("claude", "QUEUED_INTERACTIVE"), (result.target, result.reason))
        self.assertEqual([], runner.calls)

    def test_cli_reports_queued_as_ok(self):
        self._live_watch()
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["coord", "deliver", "--project", str(self.project), "--actor", "codex",
                         "--target", "claude", "--message", "U57 cli"])
        self.assertEqual(0, code)
        body = json.loads(out.getvalue())
        self.assertEqual((True, "QUEUED_INTERACTIVE"), (body["ok"], body["reason"]))


class TestPresenceLeaseFlag(_Project):
    def test_lease_survives_active_heartbeat(self):
        with redirect_stdout(io.StringIO()):
            code = main(["coord", "presence", "--project", str(self.project), "--tool", "codex",
                         "--state", "LIMITED", "--ttl", "600", "--lease"])
        self.assertEqual(0, code)
        presence.mark(self.project, "codex", "ACTIVE")
        self.assertEqual("LIMITED", presence.read(self.project, "codex")["state"])

    def test_without_flag_heartbeat_replaces(self):
        with redirect_stdout(io.StringIO()):
            main(["coord", "presence", "--project", str(self.project), "--tool", "codex",
                  "--state", "LIMITED", "--ttl", "600"])
        presence.mark(self.project, "codex", "ACTIVE")
        self.assertEqual("ACTIVE", presence.read(self.project, "codex")["state"])


if __name__ == "__main__":
    unittest.main()
===FILE: CLAUDE.md===
# Claude Code — 이 프로젝트의 상시 진입 규칙

- 단일 작업 원장은 `.coord/PLAN.md`, 공통 예산·품질 정본은 `docs/27_token-budget-routing-policy.md`다. 작업 시작 전에 현재 카드와 작성자를 확인한다.
- 사용자 대화창은 짧고 가독성 있게, 저장소 학습 가이드는 초보자에게 충분히 자세히 쓴다. 사용자의 미완성 아이디어는 `docs/AI_4도구_아이디어_조사와_위임전_매뉴얼_운영규칙.md`에 따라 근거 조사·실행 계약으로 바꾼다. Antigravity나 Ollama 호출 전 작업 프로세스 매뉴얼을 파일로 발행하고 **내용을 실제 입력으로 전달**한다.
- 매 작업 시작·끝에 `/usage`의 구독 한도와 세션 토큰을 구분해 기록한다. 예측값과 판정 예약량이 부족하면 새 장문 단계 대신 작은 계약과 로컬 Ollama 계산을 선택한다. 세부 절차: `docs/28_claude-budget-manual.md`.
- Codex 활동 중에는 지정된 구현·검토만 수행한다. Codex가 실제 제한·부재일 때에만 부지휘자 역할을 한 번 인수한다. Antigravity 총괄 대행은 Codex와 Claude 둘 다 실제 제한·부재일 때만 허용한다.
- Ollama는 단순 추론·의지 없는 전자계산기, 전화기다. 요약·추출·정확한 패치에 먼저 사용하고 작업 ID·토큰·벽시계·인수 결과를 기록한다. 설계·승인·성공 판정은 Claude 또는 복귀한 Codex가 한다.
- 같은 파일을 동시에 수정하지 않는다. 사용량 절약은 실패한 인수나 작성자 자기 검증을 정당화하지 못한다. 유료 모델의 주기적 대기 폴링은 하지 않는다.
- RSI 정본 `docs/31_evidence-gated-rsi-for-uaos.md`를 따른다. 같은 `work_id`의 사용·실패 영수증을 `.coord/usage/`에 기록하고, 독립 반례/고정 인수 없이 자기 제안을 승격하지 않는다. 자동 장부 수집은 `pilot run`에만 적용된다(U27). 개선 후보는 `rsi gate`(장부 재계산)를 거치고 자기 후보는 판정하지 않는다(docs/38). 모든 프로젝트 설치는 `uaos_everywhere/`(docs/39).
- Claude Code는 UAOS 정식 작업자다(U38): `worker: claude`(예산 필수, 판정은 codex·user), 읽기 전용 검증 `pilot review --reviewer claude`(참고 증거), Codex 부재 중 P1은 다음 프롬프트에 한 줄로 받는다. 세부 docs/40.
- Ollama·Antigravity 위임은 `pilot manual new`→`pilot manual lint`→`pilot run --manual`(계약 밖 변경·요청 밖 삭제 자동 거부, 판정자만 승인). 코드를 이미 정했으면 `worker: apply`(0토큰). 세션 시작 시 `coord presence --tool claude --state ACTIVE`, 쌓인 보고는 `coord inbox`. 세부: `docs/37`.
- 세션 간 연락(U57)은 대화창 메시지가 아니라 우편함이다: 보낼 때 `coord deliver --actor claude --target <도구> --message …`, 받을 때 `coord watch --target claude`를 백그라운드로 켜 둔다(새 편지가 오면 종료되어 세션을 깨운다, 0토큰). 대화창 교차 메시지는 권한 모드가 다르면 사용자 승인에 걸리므로 쓰지 않고, 다른 세션의 권한 모드를 올리지도 않는다. Codex 한도 초과는 Codex 로그에서 자동으로 LIMITED가 되고, 수동 표시가 필요하면 `coord presence --tool codex --state LIMITED --ttl <초> --lease`.
===FILE: AGENTS.md===
# Unified Codex–Antigravity Execution

이 프로젝트의 모든 작업은 [`docs/01_unified-agent-orchestration-design.md`](docs/01_unified-agent-orchestration-design.md)를 단일 원본으로 따른다.

## 고정 규칙

- Codex는 프로젝트 조율자이며 하나의 마스터 계획, 작업 순서, 승인 게이트를 관리한다.
- 실제 수행은 프로젝트 안의 단계별 전용 대화창에서만 한다. 사용자 지시창이나 총괄 대화창에서 구현을 대신하지 않는다.
- 각 수행 단계에는 대화창 하나와 단일 소유자 한 명만 둔다. Antigravity가 수행할 때도 Codex 프로젝트의 해당 단계 전용 대화창을 맡은 실행자로 취급한다.
- 단계 대화창 제목은 짧은 접두어 `[U##]`로 시작한다. `##`는 마스터 계획의 두 자리 순번이다. 예: `[U03] 인증 오류 수정`.
- 활성 단계는 기본적으로 하나다. 선행 단계가 검증 게이트를 통과한 뒤 다음 단계를 연다.
- 두 도구가 같은 단계, 파일 범위, 브랜치, 작업트리, 데이터베이스, 포트 또는 외부 자원을 동시에 수정하지 않는다.
- 모든 인계는 말로만 하지 않고 해당 작업 카드에 결과, 변경 범위, 검증 증거, 미해결 위험, 다음 행동을 기록한다.
- 완료 보고만으로 완료 처리하지 않는다. 검토자가 인수 조건과 검증 증거를 확인한 뒤 `DONE`으로 전환한다.
- 컨텍스트는 현재 목표·승인 경계·활성 카드와 직접 의존 자료만 로딩한다. 오래된 문서·로그·폐기 결정은 권위와 유효성을 확인하기 전에는 규칙으로 사용하지 않는다.
- 사용자 보고는 결과·변경·검증·위험·다음 자동 행동만 간결하게 제시하고 상세 증거는 카드나 산출물에 보존한다.
- 사용자가 해야 할 일이 없으면 질문하지 않고 다음 `READY` 단계를 자동 진행한다. 목표·범위 변경과 명시적 승인 대상만 사용자에게 묻는다.
- 삭제, 덮어쓰기, 배포, 푸시, 결제, 계정·권한·자격증명 변경은 사용자에게 그 행동별 명시적 승인을 받는다.
- 구현·수정 작업은 Antigravity에 SQLite 경로로 위임한다: `python -m v7_harness.cli pilot run --task <ID> --source <dir> --prompt-file <md> --accept-cmd "<인수 테스트>" --work-dir .coord/pilot`
- **계약 매뉴얼 위임(U34, 2026-09-25)**: Ollama·Antigravity 위임은 `pilot manual new`로 만든 ```contract 매뉴얼을 `pilot manual lint`로 통과시킨 뒤 `pilot run --manual <파일>`로 한다. 허용 범위 밖 변경·요청 밖 삭제·문법 오류는 자동 거부되고, 승인은 계약의 판정자만 한다. 지휘자가 코드를 이미 정했으면 `worker: apply`(모델 없음·0토큰). 세부: `docs/37`.
- **출석·음성사서함(U32b)**: 세션 시작 시 `python -m v7_harness.cli coord presence --tool <codex|claude|antigravity> --state ACTIVE`를 실행하고, `coord inbox`로 쌓인 보고를 읽은 뒤 처리한 것은 `coord ack --id <ID>`로 표시한다. 새 편지를 기다릴 때는 `coord watch --target <자기 도구>`를 백그라운드로 켜 두고(U57, 0토큰, 새 편지 도착 시 exit 0, 시간 초과 exit 3), 다른 도구에게는 `coord deliver`로 보낸다. 사용자에게 전달·복사·승인을 부탁하지 않는다.
- 작업자는 둘이다. `--worker agy`(원격, 계정 한도 소모)와 `--worker local`(이 PC의 Ollama, 한도 없음). Codex가 과제마다 고른다. 고르는 기준(벤치 실측 근거, `docs/16` 벤치 v2): **바꿀 내용을 프롬프트에 구체적으로 적을 수 있으면 `local`**. 파일 크기(483줄)와 파일 수(3개 리팩터)는 한계가 아니었고, 실제로 갈린 축은 **지시의 모호함**이다. "적절히 개선"처럼 판단을 요구하는 과제와 설계·탐색은 `agy`. 로컬 기본 모델은 `qwen2.5-coder:7b`(모호한 지시까지 통과한 유일한 모델). 원격 작업자가 `QUOTA`로 막히면 같은 과제를 `local`로 1회 재시도하고 그 사실을 기록한다. 어느 쪽이든 판정은 동일한 인수 게이트가 한다(`ollama/01_작동원리와_운영_Ollama는_어떻게_돌아가나.md` §7-1).
- **계산기 원칙(사용자 지정, 2026-09-23; U30 보정)**: Claude Code·Codex·Antigravity(지휘자)에게 Ollama는 유료 API 토큰을 쓰지 않는 전자계산기다. 다만 로컬 추론 시간·토큰·전력은 든다. 지휘자는 먼저 결정적 도구로 끝낼 수 있는지 살피고, 필요한 기계적 구현은 고정 인수와 제한된 매뉴얼을 붙여 `pilot run --worker local`에 맡긴다. 모호한 설계는 지휘자가 구체화하거나 별도 예산 판단 뒤 Antigravity에 맡긴다. `--worker auto`의 REWORK→원격 자동 승격은 U30 비용·품질 관문과 충돌하므로 사용하지 않는다. 로컬 실패를 원격 재시도의 자동 허가로 보지 않는다. 커밋 관문 `.githooks/commit-msg`(`v7_harness/calculator_gate.py`)가 APPLIED pilot 결과가 아닌 `v7_harness/*.py` 변경을 막고, 예외는 커밋 메시지 `Calculator-Exempt: <이유>` 줄로만 남긴다(`docs/01` §16).
- **올라마 = '생각 없는 전자계산기이자 3대 도구의 토큰절약도구' 영구 고정(사용자 지정, 2026-09-23, 2026-09-24 재확인; U30 보정)**: 올라마는 스스로 계획·판정·승인하지 않는 로컬 계산기다. 지휘자는 구체성 80점 이상의 작업명령서(`docs/24`)를 입력 해시·출력 형식·허용 경로·원문 인용·고정 인수와 함께 전달한다. 4대 불변식: (1) **판정권 배제**: 결정론적 인수 테스트(Acceptance Gate)와 원문 대조만이 판정한다. (2) **기계 작업 위임**: 결정적 추출이 더 싸고 정확하면 모델을 호출하지 않는다. 그 밖의 좁은 요약·변환·반복 편집은 Ollama를 우선 검토한다. (3) **실패 격리**: 출력은 독립 검증 전 반영하지 않으며, 같은 원인 2회 실패 시 경로를 바꾼다. (4) **3대 도구 공통 의무**: Codex·Claude Code·Antigravity 모두 호출 비용과 검증 비용을 비교하고 실패까지 기록한다. 무조건 호출하거나 비용 0원이라고 단정하는 것도 설계 결함이다.
- **올라마 = '원할 때 언제든지 쓰는 유선 전화기' 아키텍처 모델(사용자 지정, 2026-09-24)**: 올라마는 평소에 대기하다가 필요할 때 지휘자가 다이얼을 걸어 즉시 응답을 받는 통화료 0원의 유선 전화기다. 디스크 기반 우편함(`.coord/mailbox/`, `docs/23`, `docs/24`)은 '음성사서함(Voicemail)'으로 기능하여 지휘자 부재 중 비동기 메시지를 100% 무손실 보존한다. 로컬 올라마 기반 상주 감시관(Sentinel)은 24/7 교환원으로서 상태 감시·잠금 점검·로그 트리아지를 0원에 전담하고, P1 차단 결함 또는 사용자 승인 대상 발생 시에만 지휘자의 벨을 울려(Wake-on-P1 Ringing) 1회 선별 기상시킨다. 유료 LLM의 주기적 상주 폴링(cron)은 통화료가 계속 나가는 위성전화를 켜놓는 낭비이므로 3대 도구 전체에서 영구 금지한다.
- **Codex 활성 대화창 실시간 편입 및 U15 정본 규약(사용자 지정, 2026-09-24 환원)**: Codex 앱 재시작이나 새로고침 없는 실시간 반영을 위해 U15 정본 전달기(`coord notify` / `codex queue`)를 단일 표준으로 고정한다. Antigravity와 Claude Code의 수행 보고는 현재 프로젝트 활성 대화창(`resolve_thread`)으로 즉시 배달되며, 메시지 첫머리는 `[안티그래비티에서 온 대화]`, `[클로드에게서 온 대화]` 표식을 달아 기존 대화창에 즉각 표시된다. Electron 데스크톱 앱의 UI 실시간 갱신이 불가능한 정적 SQLite/세션 직접 생성은 실시간 통신에서 제외한다(`docs/tasks/U15-coordination-stream.md`).
- **Codex 부재 중 대화창 메시지 발송 전면 금지 및 큐 오염 차단(사용자 강력 지정, 2026-09-24)**: Codex가 사용 제한·부재(`LIMITED` 또는 `ABSENT`) 상태일 때, Codex 대화창 및 메시지 큐(`codex queue`, `coord notify`)로의 메시지 발송은 예외 없이 **전면 거부(HARD REFUSE: `CODEX_ABSENT`)**된다. 한도 초과 상태인 Codex 대화창에 메시지를 전송하여 한도 에러 화면을 유발하거나 큐를 오염시키는 일체의 시도를 원천 차단하며, 모든 작업 상황은 디스크 우편함(`.coord/mailbox/`) 및 브리핑 파일에만 기록한다.

- 비용 절감 위임의 기본 경로는 `Codex 작업 계약 1회 → 결정적 control layer → Antigravity pilot → Codex 증거 판정 1회`로 한다. 토큰 대리지표와 실제 계정 사용 한도 절감은 구분하고, 후자는 직접 측정 전까지 `UNMEASURED`로 기록한다.
- **Claude Code는 Codex 활동 중에는 Codex의 지휘를 받는 부관(비서)이고, Codex 부재 중에는 대신 지휘하는 동등한 부지휘자다(사용자 지정, 2026-09-21 / 독립 분리 철회 2026-09-23).** Codex 부재 중(한도·정지·무응답)에는 Codex의 모든 권한(계획·작업자 선택·bundle 승인·PLAN 판정)을 대행한다. 대행 중 만든 변경은 반영하되 Codex 복귀 시 재검토 대상으로 표시한다.
- **Antigravity의 임시 대행 및 독자행동 권한(사용자 지정, 2026-09-23)**: Codex와 Claude Code 둘 다 사용 제한·부재(한도 소진, 정지, 무응답) 상태일 때, Antigravity는 Codex·Claude Code의 총괄 조율·계획·수행 권한을 임시 위임받아 독자행동(Autonomous Action)을 수행한다. 조율 계획(`PLAN.md`), 아키텍처 문서, 훅 및 도구 설정을 독자적으로 갱신하고 프로세스를 마무리하되, 영구 안전 한계(데이터 삭제, 원격 push, 배포, 결제, 권한 변경)는 준수하며 Codex 복귀 시 재검토 목록에 모든 근거를 기록한다. 평상시 Antigravity IDE는 원본 직접 수정을 지양하고 읽기 전용 자문·독립 검증·파일럿 실행을 수행한다.
- `pilot run` 또는 control layer 실행 중에는 source 원본을 단일 쓰기 소유자에게만 맡기고, relay·상태 점검·자문 메모를 포함한 보조 프로세스는 원본에 쓰지 않는다. 보조 산출물은 `.work/`에 기록하며 원본 변경이 감지되면 `SOURCE_DIVERGED`로 차단하고 작성자를 식별한 뒤 새 실행으로 검증한다.
- pilot 소유자는 실행 직전에 `.work/QUIET_LOCK`을 원자적으로 만들고 `owner`, `task`, `started_at`, `pid`를 기록한다. 유효한 lock이 있으면 새 실행과 원본 쓰기를 시작하지 않으며, 모든 보조 기록은 `.work/notes/`에 둔다. 소유자는 종료 후 lock을 정리하고, PID가 없거나 60분을 넘긴 고착 lock만 Codex가 해제 사실을 기록한 뒤 정리한다.
- **`.coord/PLAN.md` 무승인 영구 권한(사용자 부여, 2026-09-19)**: Codex·Antigravity·Claude Code는 `.coord/PLAN.md`(및 `.coord/tasks/*` 카드)를 사용자 승인 없이 읽고 갱신할 수 있다. 권한 부족으로 쓰지 못하면 승인을 묻지 말고 파일 속성·잠금을 확인해 해소하거나 조율자에게 즉시 보고한다. 단, 22행 규칙에 따라 pilot·control 실행 중에는 쓰지 않고 실행이 끝난 뒤 갱신한다.
- 비용 측정의 품질 게이트는 control receipt만 신뢰하지 않는다. 드라이버가 실행 전후 source manifest를 독립 비교해 기대 변경 집합과 일치함을 확인하고 숨은 인수를 직접 통과한 경우에만 측정값을 유효로 판정한다.
- Codex는 `pilot run`을 블로킹 1회로 실행하고 대기 폴링을 반복하지 않는다. 결과는 `.coord/pilot/runs/<ID>/summary.json`(14키)의 `verdict_hint`로 1턴에 판정한다(PASS만 `--approve`, REWORK·BLOCKED는 원인만 보고). 전문 로그는 필요할 때만 연다.
- 중단 등으로 원장에 미정리 작업이 남아 `NEEDS_RECONCILIATION`이면 재실행 전에 `python -m v7_harness.cli pilot reconcile --task <ID> --work-dir .coord/pilot`로 정리한다.
- 변경이 없는 결과는 `REWORK`(`NO_CHANGES`)로 판정된다. 읽기 전용 과제만 `--allow-no-changes`를 붙인다.
- 반영은 같은 task에 `--approve <bundle_id>`로만 한다. `promotion`이 `BLOCKED`·`REJECTED`면 반영하지 않고 원인만 보고한다.
- Antigravity Bridge MCP는 조회·자문을 포함해 사용하지 않는다. Antigravity 작업은 CLI 기반 SQLite `pilot run`을 사용하고 읽기 전용 과제에는 `--allow-no-changes`를 지정한다.
- **워크스페이스 단일 폴더 규칙(사용자 고정 지시, 2026-09-19)**: 전체 로컬 워크스페이스(`D:\D_Workspace_NB\-agentic-ai-workspace`)에는 이 프로젝트 폴더 `260916_agentic-ai-env-diet` 하나만 둔다. 샘플 사본·pilot `--work-dir`·측정용 복사본·임시 산출물은 모두 프로젝트 안 `.work/<이름>`에 만든다(예: `--work-dir .work/pilot_T01`). 워크스페이스 최상위에 형제 폴더를 만들지 않는다. `.work/`와 `.coord/pilot`은 manifest·staging에서 제외되므로 프로젝트 자신을 `--source .`로 써도 안전하다.
- 격리는 설정된 감시 루트(watch roots) 내부에서만 보증되며, 탐지 범위 밖 경로는 보증하지 않는다.

## 최소 실행 루프

1. Codex가 마스터 계획에서 다음 `READY` 단계 하나를 선택한다.
2. `[U##]` 전용 대화창을 만들고 단일 소유자와 수정 범위를 기록한다.
3. 소유자가 단계를 `ACTIVE`로 점유한 뒤 범위 안에서만 수행한다.
4. 소유자가 검증 결과와 인계 기록을 남기고 `REVIEW`로 반환한다.
5. Codex가 증거를 재검토해 `DONE`, `READY` 재작업, 또는 `BLOCKED`를 결정한다.
6. `DONE`일 때만 다음 순번을 활성화한다.

규칙 원문과 상태·카드 형식은 설계 문서를 참조하고, 도구별 규칙에 별도의 상충 사본을 만들지 않는다.

## 토큰예산 영구 운영 규칙 (U25, 2026-09-24)

- 사용자 대화창은 결과만 짧고 읽기 쉽게 보고한다. 저장소의 [초보자 학습 가이드](docs/UAOS_처음부터_이해하고_사용하는_학습가이드.md)는 과정·진단·한계를 충분히 설명한다. [네 AI 도구 운영 규칙](docs/AI_4도구_아이디어_조사와_위임전_매뉴얼_운영규칙.md)에 따라 아이디어를 출처 조사·실행 계약으로 구체화하고, Antigravity·Ollama 호출 전 매뉴얼을 파일로 발행해 실제 입력으로 전달한다.

- 모든 작업은 `docs/27_token-budget-routing-policy.md`의 **계정별 전후 사용량·예측·판정 예약량·품질 관문**을 따른다. 실제 절감은 대조 측정 전 `UNMEASURED`다. Codex·Claude의 남은 퍼센트를 토큰 수로 환산하거나 오래된 3%/6% 기록을 재사용하지 않는다.
- 잔여율이 낮다는 이유만으로 Antigravity에 총괄을 넘기지 않는다. Codex가 부족하면 Claude 부지휘자에게 한 번 인계하고, 두 도구 모두 실제 제한·부재일 때만 기존 임시 Antigravity 대행 규칙을 발동한다. 작성자는 자기 변경의 유일한 검증자가 될 수 없다.
- Codex·Claude·Antigravity는 좁고 기계적인 일을 Ollama 전화기로 우선 보내고, 호출자·로컬 토큰·벽시계·인수 결과를 같은 작업 ID로 남긴다. Ollama에게 설계·판정·승인을 맡기지 않는다. 세부 절차는 `docs/28_claude-budget-manual.md`, `docs/29_antigravity-budget-manual.md`, `docs/30_ollama-calculator-manual.md`를 따른다.
- U23의 우편함 무손실·감시관 1회 기상 주장은 독립 반례가 해결될 때까지 인수 보류다. 새 정책은 U23의 전달 보증을 전제로 작동하지 않는다.

## 증거 관문형 RSI 및 사용량 장부 (U26, 2026-09-24)

- `docs/31_evidence-gated-rsi-for-uaos.md`의 관찰→가설→고정 인수→작은 후보→대조→독립 판정 순서를 따른다. 자기 평가만으로 자기 규칙·코드·테스트를 승격하지 않는다.
- Codex·Claude·Antigravity는 각 작업의 Ollama/원격 호출 사용량과 실패도 같은 `work_id`로 `.coord/usage/runs.jsonl`에 남긴다. 확인되지 않은 값은 `UNKNOWN`/`null`로 둔다. 원문 프롬프트·비밀은 남기지 않는다. pilot의 원본 감시 중에는 장부에 쓰지 않는다.
- **RSI 명령(U36, B83 개정 2026-09-25)**: `rsi report`→`rsi propose`→시험→`rsi gate --candidate`(참고 증거). `rsi adopt`·`rsi rollback`은 항상 거부하고 아무것도 쓰지 않는다(`UNAUTHENTICATED_ACTOR`, 같은 계정의 이름표는 인증이 아님). 채택·되돌리기는 PLAN 카드와 검토된 커밋으로만. 관문은 장부로 전후를 다시 계산하고 평가기·장부 변경·자기 검증·기준 완화·다중 지표 회귀를 거부한다. 세부 docs/38.
- **Claude Code 정식 작업자(U38)**: `worker: claude` 매뉴얼은 `remote_budget_tokens`와 codex·user 판정자가 필수다. 모든 유료 작업자(agy·claude)는 예산 초과·미보고 시 BLOCKED이고 승인할 수 없다(B85). `pilot review --reviewer claude`는 참고 증거일 뿐 승인을 대신하지 않는다. 세부 docs/40.
- **전 프로젝트 가동(U37)**: `python uaos_everywhere/install_uaos_everywhere.py --apply`가 세 도구 전역 규칙 문단·출석 훅·Claude 예약 도구 차단을 설치한다(미리보기 기본, 백업, `--check`, `--uninstall`). 새 프로젝트는 `coord init`. 세부 docs/39.
- **복귀 시 권한대행 인계 확인**: 한도·부재 후 다시 구동된 도구(Codex·Claude Code)는 구동과 동시에 `coord inbox`로 권한대행(Antigravity)의 인계 통지를 확인하고, `.coord/tasks/NEXT_MORNING_RESUME.md` 및 `.coord/codex_return_checklist.md`에 명시된 대행 구축 프로세스·프로젝트 검증 목록을 확인한 뒤 지휘·조율을 정상 재개한다.
- 사용 기록은 개선 제안의 입력일 뿐 승인·판정 권한이 아니다. 10개 유효 표본마다 품질·재작업·토큰·시간을 비교하고, P1·품질 저하·3배 비용 회귀면 개선안을 채택하지 않는다. 자동 수집은 U27 검증 전까지 미구현이다.
===FILE: uaos_everywhere/uaos_global_rule_block.md===
## UAOS — 모든 프로젝트에 공통인 협업 운영 체계(Unified Agent Operating System)

- 명령 `uaos` = `{uaos}`. UAOS 저장소의 `v7_harness`를 어느 폴더에서든 실행한다. 아래 `uaos …`는 이 명령으로 바꿔 읽는다.
- 프로젝트 안이나 그 상위 폴더에 `.coord/PLAN.md`가 있으면 UAOS 프로젝트다. 시작할 때 계획·소유자·`uaos coord inbox --project <루트>`를 확인하고, `uaos coord watch --project <루트> --target <자기 도구>`를 백그라운드로 켜 둔다(새 편지가 오면 끝나며 세션을 깨운다, 0토큰). 도구끼리는 `uaos coord deliver`로 보내고 사용자에게 전달·복사·승인을 부탁하지 않는다.
- UAOS 프로젝트가 아니고 둘 이상의 도구가 협업할 일이면 `uaos coord init --project <루트>`로 준비한다. 기존 파일은 덮어쓰지 않는다.
- 프로젝트 시작 전에 `.coord/PROJECT_MANUAL.md`, 모든 위임 전에 해시 고정 계약 매뉴얼을 발행·lint하고 그 내용 전체를 호출에 전달한다. 유료 작업자는 token/USD/time 상한을 따로 두며 초과 결과는 승인하지 않는다.
- 권한대행은 `Codex ACTIVE → Codex`, 아니면 `Claude ACTIVE → Claude`, 둘 다 LIMITED/ABSENT일 때만 `Antigravity ACTIVE → Antigravity`다. UNKNOWN은 대행 근거가 아니며 `uaos coord route`가 fail-closed 한다. 잔여율·리셋 창을 토큰으로 환산하지 않는다.
- Ollama는 계산기다. 요약·추출·정확한 치환만 하고 설계·승인·판정은 하지 않는다. 같은 원인으로 두 번 실패하면 경로를 바꾼다. 유료 모델로 기다림 폴링이나 예약 호출을 하지 않는다. 기다림은 우편함과 교환원(sentinel)이 맡는다.
- 건설적 자율 릴레이(Constructive Autonomous Relay): `verdict_requested=no`, 생존 확인, 동일 상태, 빈 출력은 `ACK_ONLY`로 내부 기록만 하고 사용자·다른 유료 도구를 깨우지 않는다. 실제 변경·새 증거·검증 실패·P1·승인 필요만 `ACTIONABLE_DELTA`다. 변화가 있으면 중복/소유권을 먼저 확인하고 의존성이 충족된 가장 작은 `READY` 작업 하나를 `선택 → 수행 → 고정 인수 → 카드 기록`까지 끝낸 뒤 필요한 상대에게 `사실/증거/다음 한 단계`만 보낸다. 작업 없이 연락만 반복하는 주기 실행은 결함이다.
- 자가개선(RSI)은 증거만 만든다: `uaos rsi report` → `uaos rsi propose` → 시험 실행 → `uaos rsi gate --candidate <파일>`(참고 증거) → 릴리스는 `uaos rsi prepare` → `uaos rsi ship`(fetch·commit·push·PR, 자동병합 금지, 모든 외부 단계 실패는 fail-closed). 채택은 PLAN 카드와 검토된 커밋으로만 한다. 같은 계정 안의 이름표는 인증이 아니므로 `rsi adopt`로 자동 채택하지 않는다(B83). 평가기(테스트·장부·관문 코드)는 개선 대상이 아니다.
- 유료 LLM으로 크론·폴링을 돌리지 않는다: 변경 감시는 `uaos rsi schedule`(Windows 예약, 프로젝트별 고유 작업 이름, 기본 드라이런)이 로컬에서 결정적으로 돈다. 변화가 없으면(`ACK_ONLY`) 조용하고, 내용 해시가 실제로 바뀐 경우(`ACTIONABLE_DELTA`)만 한 번 모아서 고정 관문 PR 루프(`rsi prepare`/`rsi ship`)로 들어간다. 보존(`uaos rsi retention`)은 항상 드라이런 매니페스트이고, 삭제는 이 계획과 별도의 최신 승인이 있어야 한다.
- 복귀 도구는 우편함·복귀 체크리스트·대행 diff와 인수를 재검토한 뒤에만 지휘를 재개한다.
- 멈추고 사용자에게 물을 것: 삭제, push·배포·게시, 결제, 계정·권한·시스템 설정 변경.
===FILE: uaos_everywhere/adapters/claude.md===
## Claude Code 역할 어댑터

- Codex가 LIMITED/ABSENT이고 Claude가 ACTIVE일 때만 부지휘자로 대행한다.
- `worker: claude`이면 계약 범위만 수정하고 자기 결과를 단독 판정하지 않는다.
- 복귀할 Codex가 재검토할 diff·인수·예산 영수증을 우편함에 남긴다.
- 다른 Claude 세션과는 대화창 메시지 대신 우편함으로 주고받는다: `coord deliver`로 보내고 `coord watch --target claude`로 기다린다. 권한 모드가 다른 세션 사이의 대화창 메시지는 사용자 승인에 걸리며, 그 승인을 없애려고 권한 모드를 올리지 않는다.
===END===

## Output

- Reply with ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.
