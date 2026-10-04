"""U42: evidence-to-PR release pipeline and deterministic change watcher.

Automates the cycle:
  observe / research → snapshot hash & dedupe → packet draft →
  fixed acceptance / holdout / red-team receipts → independent judge →
  SemVer bump → top document updates → approval-receipt bound shipping (git fetch/commit/push + gh pr create).
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable, Optional, Sequence


APPROVAL_TEXT = (
    "이 요청은 이 U42 범위의 전역 규칙 배포, 브랜치 생성, 커밋, 원격 푸시, PR 생성에 대한 명시적 승인이다. "
    "삭제·결제·계정/자격증명 변경은 금지한다."
)

REQUIRED_APPROVAL_ACTIONS = (
    "global_rule_deploy",
    "branch_create",
    "commit",
    "push",
    "pull_request_create",
)

FORBIDDEN_ACTIONS = (
    "delete_data",
    "spend_money",
    "change_account",
    "change_credentials",
    "auto_merge",
)

EVALUATOR_PATTERNS = (
    "tests/*",
    ".githooks/*",
    ".coord/runs/*",
    ".coord/usage/*",
    ".coord/rsi/decisions.jsonl",
    "v7_harness/rsi.py",
    "v7_harness/manual.py",
    "v7_harness/calculator_gate.py",
    "v7_harness/olla_evidence.py",
    "v7_harness/accept_triage.py",
    "v7_harness/adapters/ollama_worker.py",
    "v7_harness/isolation/*",
)

ALLOWED_DIRTY_PATTERNS = (
    ".coord/*",
    "docs/*",
    "tests/*",
    "v7_harness/*",
    "uaos_everywhere/*",
    "README.md",
)


class ReleaseRefused(Exception):
    """Raised when release validation, approval, or execution violates invariants."""


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def packet_fingerprint(packet: dict[str, Any]) -> str:
    """Stable cryptographic digest of the entire packet payload."""
    raw = json.dumps(packet, sort_keys=True, ensure_ascii=False)
    return _sha(raw)


def validate_packet(packet: dict[str, Any]) -> list[str]:
    """Validate release candidate packet against safety invariants."""
    problems: list[str] = []

    # 1. Sources: deduplication and snapshot integrity
    seen_urls: set[str] = set()
    for source in packet.get("sources", []):
        url = source.get("url", "")
        if url in seen_urls:
            problems.append(f"DUPLICATE_SOURCE:{url}")
        seen_urls.add(url)

        snapshot = source.get("snapshot", "")
        expected_hash = _sha(snapshot)
        if source.get("snapshot_sha256") != expected_hash:
            problems.append(f"SOURCE_HASH_MISMATCH:{url}")

    # 2. Evidence receipts: acceptance, holdout, red-team
    for stage in ("acceptance", "holdout", "red_team"):
        receipt = packet.get(stage)
        stage_upper = stage.upper()
        if not receipt or not isinstance(receipt, dict):
            problems.append(f"{stage_upper}_RECEIPT_MISSING")
            continue
        if receipt.get("exit_code") != 0:
            problems.append(f"{stage_upper}_NOT_PASS")
        if not receipt.get("fixed_sha256"):
            problems.append(f"{stage_upper}_FIXED_HASH_MISSING")

    # 3. Independent roles
    author = packet.get("author")
    verifier = packet.get("verifier")
    judge = packet.get("judge")
    if not author or not verifier or not judge:
        problems.append("ROLES_MISSING")
    else:
        if judge == author or judge == verifier:
            problems.append("JUDGE_NOT_INDEPENDENT")
        if verifier == author:
            problems.append("VERIFIER_NOT_INDEPENDENT")

    # 4. Protected paths
    for path in packet.get("changed_files", []):
        posix_path = str(Path(path).as_posix())
        if any(fnmatch.fnmatch(posix_path, pat) for pat in EVALUATOR_PATTERNS):
            problems.append(f"PROTECTED_PATH:{path}")

    # 5. Usage evidence
    usage = packet.get("usage")
    if not usage or not isinstance(usage, dict):
        problems.append("USAGE_MISSING")
    else:
        budget = usage.get("remote_budget_tokens")
        actual = usage.get("actual_tokens")
        if budget is not None and actual is not None and actual > budget:
            problems.append("REMOTE_BUDGET_EXCEEDED")
        if usage.get("wall_seconds") is None:
            problems.append("WALL_TIME_UNKNOWN")

    return problems


def duplicate_problems(packet: dict[str, Any], existing_proposals: Sequence[dict[str, Any]]) -> list[str]:
    """Check if the proposal has already been registered."""
    fp = packet_fingerprint(packet)
    existing_fps = {p.get("fingerprint") for p in existing_proposals if isinstance(p, dict)}
    if fp in existing_fps:
        return [f"DUPLICATE_PROPOSAL:{fp}"]
    return []


def bump_version(version: str, change_type: str) -> str:
    """Deterministically increment SemVer version."""
    parts = version.strip().split(".")
    if len(parts) != 3:
        raise ValueError(f"Invalid SemVer version string: '{version}'")
    try:
        major, minor, patch = (int(p) for p in parts)
    except ValueError as exc:
        raise ValueError(f"Non-integer SemVer component in: '{version}'") from exc

    ct = change_type.lower().strip()
    if ct in ("fix", "patch"):
        patch += 1
    elif ct in ("feature", "minor"):
        minor += 1
        patch = 0
    elif ct in ("breaking", "major"):
        major += 1
        minor = 0
        patch = 0
    else:
        raise ValueError(f"Unsupported change_type: '{change_type}'")
    return f"{major}.{minor}.{patch}"


def render_top_update(original: str, *, version: str, date: str, summary: str, fingerprint: str) -> str:
    """Insert an update section right under the top-level heading in an idempotent manner."""
    marker = f"<!-- uaos-update:{fingerprint} -->"
    if marker in original:
        return original

    block = f"{marker}\n## 업데이트 ({version}, {date})\n\n- {summary}\n\n"

    # Find position after the first # Title heading
    lines = original.splitlines(keepends=True)
    insert_idx = 0
    found_title = False
    for i, line in enumerate(lines):
        if line.startswith("# "):
            found_title = True
            # Find next non-empty line after title
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            insert_idx = j
            break

    if found_title:
        before = "".join(lines[:insert_idx])
        after = "".join(lines[insert_idx:])
        if not before.endswith("\n\n"):
            before = before.rstrip("\n") + "\n\n"
        return before + block + after
    return block + original


def prepare_release(
    root: Path,
    packet: dict[str, Any],
    *,
    apply: bool = False,
    date: str = "2026-09-25",
) -> dict[str, Any]:
    """Prepare release artifacts and version bump, defaulting to dry run."""
    problems = validate_packet(packet)
    if problems:
        raise ReleaseRefused(f"PACKET_INVALID: {', '.join(problems)}")

    version_rel = packet.get("version_file", "VERSION")
    version_file = root / version_rel
    current_version = "0.0.0"
    if version_file.is_file():
        current_version = version_file.read_text(encoding="utf-8").strip() or "0.0.0"

    next_ver = bump_version(current_version, packet.get("change_type", "feature"))
    fp = packet_fingerprint(packet)

    plan = {
        "current_version": current_version,
        "next_version": next_ver,
        "version_file": version_rel,
        "fingerprint": fp,
        "apply": apply,
    }

    if apply:
        version_file.parent.mkdir(parents=True, exist_ok=True)
        version_file.write_text(f"{next_ver}\n", encoding="utf-8")

        summary = packet.get("summary", "")
        for doc_rel in packet.get("update_documents", []):
            doc_path = root / doc_rel
            if doc_path.is_file():
                doc_text = doc_path.read_text(encoding="utf-8")
                updated_text = render_top_update(
                    doc_text,
                    version=next_ver,
                    date=date,
                    summary=summary,
                    fingerprint=fp,
                )
                doc_path.write_text(updated_text, encoding="utf-8")

    return plan


def validate_approval(approval: dict[str, Any], *, work_id: str) -> list[str]:
    """Validate explicit user approval receipt."""
    problems: list[str] = []

    if approval.get("work_id") != work_id:
        problems.append("WORK_ID_MISMATCH")

    text = approval.get("approval_text", "")
    expected_hash = _sha(text)
    if approval.get("approval_sha256") != expected_hash:
        problems.append("APPROVAL_HASH_MISMATCH")

    allowed = set(approval.get("allowed_actions", []))
    for act in REQUIRED_APPROVAL_ACTIONS:
        if act not in allowed:
            problems.append(f"APPROVAL_ACTION_MISSING:{act}")

    for act in allowed:
        if act in FORBIDDEN_ACTIONS:
            problems.append(f"FORBIDDEN_ACTION_ALLOWED:{act}")

    return problems


def _run_step(
    run: Callable[..., subprocess.CompletedProcess],
    command: list[str],
    *,
    cwd: Path,
    stage: str,
) -> subprocess.CompletedProcess:
    """Run one external step; fail closed with the stage name and bounded output on any nonzero exit."""
    proc = run(command, cwd=cwd, capture_output=True, text=True, check=False)
    rc = getattr(proc, "returncode", None) if proc is not None else None
    if proc is None or rc != 0:
        stderr = (getattr(proc, "stderr", "") or "")[:500] if proc is not None else ""
        stdout = (getattr(proc, "stdout", "") or "")[:500] if proc is not None else ""
        raise ReleaseRefused(f"{stage} failed (rc={rc}): stdout={stdout!r} stderr={stderr!r}")
    return proc


def ship_release(
    root: Path,
    packet: dict[str, Any],
    approval: dict[str, Any],
    *,
    execute: bool = False,
    run: Optional[Callable[..., subprocess.CompletedProcess]] = None,
) -> dict[str, Any]:
    """Commit, push, and open PR with strict fail-closed safety checks.

    Every external step (`git status`, `fetch`, `add`, `commit`, `rev-parse HEAD`, `push`,
    `ls-remote`, `gh pr create`, `gh pr view`) is checked; a nonzero return code refuses with the
    stage name and bounded stdout/stderr. A failed push, or a missing/mismatched remote SHA, can
    never return SHIPPED, and merge is never invoked.
    """
    if run is None:
        run = subprocess.run

    # 1. Invariant validation
    packet_problems = validate_packet(packet)
    if packet_problems:
        raise ReleaseRefused(f"PACKET_INVALID: {', '.join(packet_problems)}")

    approval_problems = validate_approval(approval, work_id=packet.get("work_id", ""))
    if approval_problems:
        raise ReleaseRefused(f"APPROVAL_INVALID: {', '.join(approval_problems)}")

    base_branch = packet.get("base_branch", "main")
    branch = packet.get("branch", f"codex/{packet.get('work_id', 'task').lower()}-release")
    title = packet.get("title", "Automated RSI Release")
    summary = packet.get("summary", "")
    commit_msg = f"feat({packet.get('work_id', 'release').lower()}): {title}"

    commands = [
        ["git", "status", "--porcelain"],
        ["git", "fetch", "origin", base_branch],
        ["git", "add", "<changed_files>"],
        ["git", "commit", "-m", commit_msg],
        ["git", "rev-parse", "HEAD"],
        ["git", "push", "origin", branch],
        ["git", "ls-remote", "origin", f"refs/heads/{branch}"],
        ["gh", "pr", "create", "--base", base_branch, "--head", branch, "--title", title, "--body", summary],
        ["gh", "pr", "view", branch, "--json", "url,state"],
    ]

    if not execute:
        return {"status": "DRY_RUN", "commands": commands}

    # 2. Check git status for unexpected dirty files when executing
    status_proc = _run_step(run, ["git", "status", "--porcelain"], cwd=root, stage="git status")
    if status_proc.stdout:
        expected_paths = {
            str(Path(f).as_posix()) for f in packet.get("changed_files", [])
        }
        for f in packet.get("update_documents", []):
            expected_paths.add(str(Path(f).as_posix()))
        if packet.get("version_file"):
            expected_paths.add(str(Path(packet["version_file"]).as_posix()))

        for line in status_proc.stdout.splitlines():
            line_str = line.strip()
            if not line_str:
                continue
            parts = line_str.split(maxsplit=1)
            if len(parts) < 2:
                continue
            path_part = parts[1].strip()
            if " -> " in path_part:
                path_part = path_part.split(" -> ")[1].strip()
            path_posix = str(Path(path_part).as_posix())

            matched = (
                path_posix in expected_paths
                or any(fnmatch.fnmatch(path_posix, pat) for pat in ALLOWED_DIRTY_PATTERNS)
            )
            if not matched:
                raise ReleaseRefused(f"UNEXPECTED_DIRTY_PATH: {path_part}")

    # 3. Fetch
    _run_step(run, ["git", "fetch", "origin", base_branch], cwd=root, stage="git fetch")

    # 4. Stage only permitted paths
    stage_targets = []
    for f in packet.get("changed_files", []):
        stage_targets.append(str(Path(f).as_posix()))
    for f in packet.get("update_documents", []):
        stage_targets.append(str(Path(f).as_posix()))
    if packet.get("version_file"):
        stage_targets.append(str(Path(packet["version_file"]).as_posix()))

    if stage_targets:
        _run_step(run, ["git", "add"] + stage_targets, cwd=root, stage="git add")

    # 5. Commit
    _run_step(run, ["git", "commit", "-m", commit_msg], cwd=root, stage="git commit")

    # 6. HEAD SHA
    head_proc = _run_step(run, ["git", "rev-parse", "HEAD"], cwd=root, stage="git rev-parse HEAD")
    head_sha = head_proc.stdout.strip()

    # 7. Push
    _run_step(run, ["git", "push", "origin", branch], cwd=root, stage="git push")

    # 8. Check remote SHA: it must exist and equal local HEAD. Never substitute local HEAD for a
    # missing/mismatched remote SHA -- that would silently claim a push that never landed.
    ls_proc = _run_step(
        run, ["git", "ls-remote", "origin", f"refs/heads/{branch}"], cwd=root, stage="git ls-remote"
    )
    remote_sha = ""
    if ls_proc.stdout and ls_proc.stdout.strip():
        remote_sha = ls_proc.stdout.split()[0].strip()
    if not remote_sha:
        raise ReleaseRefused(f"REMOTE_SHA_MISSING: origin has no SHA for refs/heads/{branch}")
    if remote_sha != head_sha:
        raise ReleaseRefused(f"REMOTE_SHA_MISMATCH: local={head_sha} remote={remote_sha}")

    # 9. Create PR (never auto-merge!)
    _run_step(
        run,
        ["gh", "pr", "create", "--base", base_branch, "--head", branch, "--title", title, "--body", summary],
        cwd=root,
        stage="gh pr create",
    )

    # 10. View PR
    view_proc = _run_step(
        run, ["gh", "pr", "view", branch, "--json", "url,state"], cwd=root, stage="gh pr view"
    )
    pr_data: dict[str, Any] = {"state": "UNKNOWN", "url": ""}
    if view_proc.stdout:
        try:
            pr_data = json.loads(view_proc.stdout)
        except (ValueError, json.JSONDecodeError):
            pr_data = {"raw": view_proc.stdout.strip()}

    return {
        "status": "SHIPPED",
        "pr": pr_data,
        "head_sha": head_sha,
        "remote_sha": remote_sha,
    }


def _default_pid_alive(pid: Optional[int]) -> bool:
    """Best-effort real liveness check. Only consulted once a lock is already past the dead-pid
    grace period (see `run_scheduler_cycle`), so a false negative here cannot recover a fresh lock."""
    if not pid:
        return False
    try:
        if os.name == "nt":
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, AttributeError):
        return False


def _try_acquire_lock(lock_file: Path, payload: dict[str, Any]) -> bool:
    """Atomic exclusive lock creation: only one caller (process or thread) ever wins the create."""
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    try:
        os.write(fd, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    finally:
        os.close(fd)
    return True


def run_scheduler_cycle(
    root: Path,
    config: dict[str, Any],
    *,
    fetch: Optional[Callable[..., dict[str, Any]]] = None,
    trigger: Optional[Callable[[dict[str, Any]], None]] = None,
    now: float = 0.0,
    sleeper: Optional[Callable[[float], None]] = None,
    pid_alive: Optional[Callable[[Optional[int]], bool]] = None,
    record: Optional[Callable[[dict[str, Any]], None]] = None,
) -> dict[str, Any]:
    """Run one bounded deterministic change-detection cycle.

    The scheduler lock is acquired with exclusive creation (never a "file exists" check-then-write
    race). A live, non-expired lock returns LOCKED. A lock whose owner PID is dead, or whose age is
    at or past `lock_ttl_seconds`, is recovered (removed, `STALE_LOCK_RECOVERED` is recorded, and
    acquisition is retried once). Only the lock this invocation created is ever removed.
    """
    sleeper = sleeper or (lambda _seconds: None)
    pid_alive = pid_alive or _default_pid_alive
    record = record or (lambda _event: None)

    lock_file = root / ".work" / "rsi-scheduler.lock"
    lock_ttl_seconds = config.get("lock_ttl_seconds", 3600)
    dead_pid_grace_seconds = config.get("stale_lock_grace_seconds", 30)
    token = f"{os.getpid()}:{uuid.uuid4().hex}"
    payload = {"pid": os.getpid(), "started_at": now, "token": token}

    acquired = _try_acquire_lock(lock_file, payload)
    if not acquired:
        try:
            existing = json.loads(lock_file.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            existing = {}
        existing_pid = existing.get("pid")
        existing_started = existing.get("started_at", now)
        age = now - existing_started
        is_stale = age >= lock_ttl_seconds
        is_dead = age >= dead_pid_grace_seconds and not pid_alive(existing_pid)
        if not (is_stale or is_dead):
            return {"status": "LOCKED"}

        record({"event": "STALE_LOCK_RECOVERED", "pid": existing_pid, "age_seconds": age})
        try:
            lock_file.unlink()
        except OSError:
            pass
        acquired = _try_acquire_lock(lock_file, payload)
        if not acquired:
            return {"status": "LOCKED"}

    try:
        timeout = config.get("timeout_seconds", 15)
        max_retries = config.get("max_retries", 3)
        backoff_base = config.get("backoff_base_seconds", 60)
        backoff_seconds = [backoff_base * (2**i) for i in range(max_retries)]

        state_file = root / ".work" / "rsi-scheduler-state.json"
        prior_state: dict[str, dict[str, Any]] = {}
        if state_file.is_file():
            try:
                prior_state = json.loads(state_file.read_text(encoding="utf-8"))
            except (ValueError, json.JSONDecodeError):
                prior_state = {}

        observations: dict[str, dict[str, Any]] = {}
        deltas: list[dict[str, Any]] = []

        for source in config.get("sources", []):
            url = source.get("url", "")
            # Fetch with bounded retries; a real exponential sleep only happens between attempts,
            # never after the final one.
            obs: Optional[dict[str, Any]] = None
            last_exc: Optional[Exception] = None
            for attempt in range(max_retries):
                try:
                    if fetch is not None:
                        obs = fetch(source, timeout)
                    break
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    if attempt < max_retries - 1:
                        sleeper(backoff_seconds[attempt])

            if obs is None:
                return {
                    "status": "FAILED",
                    "backoff_seconds": backoff_seconds,
                    "next_run_at": now + backoff_seconds[-1],
                    "failure_receipt": {"error": f"{type(last_exc).__name__}: {last_exc}"},
                }

            observations[url] = obs

            # Content change is the sole actionable signal; etag/date-only changes are ACK_ONLY.
            prev_obs = prior_state.get(url)
            if prev_obs is not None and obs.get("content_sha256") != prev_obs.get("content_sha256"):
                deltas.append(obs)

        # Update saved state
        state_file.write_text(json.dumps(observations, ensure_ascii=False, indent=2), encoding="utf-8")

        if deltas:
            # Collect every changed source first, dedupe by URL, then trigger exactly once.
            deduped: dict[str, dict[str, Any]] = {d.get("url"): d for d in deltas}
            bundle = {"deltas": list(deduped.values()), "count": len(deduped)}
            if trigger is not None:
                trigger(bundle)
            return {"status": "ACTIONABLE_DELTA", "observations": observations, "deltas": bundle["deltas"]}
        return {"status": "ACK_ONLY", "observations": observations}

    finally:
        try:
            current = json.loads(lock_file.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            current = {}
        if current.get("token") == token:
            try:
                lock_file.unlink()
            except OSError:
                pass


def _project_hash(project: Path) -> str:
    normalized = str(project).replace("\\", "/").rstrip("/").lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:8]


def _task_name(project: Path) -> str:
    """Project-unique task name so two UAOS projects never collide in Task Scheduler."""
    return f"UAOS_RSI_Watch_{_project_hash(project)}"


_TASK_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
# U157: a new error waits at most 15 min for the local scan, which spends no paid tokens; the daily calendar trigger
# repeats it all day. Logon with StartWhenAvailable catches up after sleep or a missed start.
_REPEAT = "PT15M"
# U157: a ceiling, not a measurement; the live proof measures one scan and replaces it.
_TIME_LIMIT = "PT10M"


def _wrapper_text(project: Path, python_bin: str, launcher: Optional[Path] = None) -> str:
    """A deterministic wrapper: `cd` to the project root, then run the installed runtime with absolute paths only.

    U157: the task runs the installed launcher (`~/.uaos/uaos.py`), not the checkout module. It leaves an exit
    receipt in `.coord/rsi/schedule_last.json` and returns the same exit code, so Task Scheduler's Last Result and
    the receipt both show the real result of `rsi watch`.
    """
    project_str = str(project)
    launcher = launcher if launcher is not None else Path.home() / ".uaos" / "uaos.py"
    receipt_dir = f"{project_str}\\.coord\\rsi"
    return (
        "@echo off\r\n"
        f'cd /d "{project_str}"\r\n'
        f'"{python_bin}" "{launcher}" rsi watch --project "{project_str}"\r\n'
        "set UAOS_RC=%ERRORLEVEL%\r\n"
        f'if not exist "{receipt_dir}" mkdir "{receipt_dir}"\r\n'
        f'>"{receipt_dir}\\schedule_last.json" echo {{"exit": %UAOS_RC%, "at": "%DATE% %TIME%"}}\r\n'
        "exit /b %UAOS_RC%\r\n"
    )


def _task_xml(wrapper_path: Path, project: Path) -> str:
    """U157: the whole task as Task Scheduler XML; Exec/Command holds a spaced path as one element."""
    from xml.sax.saxutils import escape

    domain, user = os.environ.get("USERDOMAIN", ""), os.environ.get("USERNAME", "")
    user_id = f"{domain}\\{user}" if domain and user else user
    # A logon trigger for one named user needs no elevation; without a name it would mean any user.
    logon_user = f"<UserId>{escape(user_id)}</UserId>" if user_id else ""
    return (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        f'<Task version="1.2" xmlns="{_TASK_NS}">\n'
        "  <RegistrationInfo><Description>UAOS RSI watch (U157)</Description></RegistrationInfo>\n"
        "  <Triggers>\n"
        "    <CalendarTrigger><StartBoundary>2026-01-01T00:00:00</StartBoundary><Enabled>true</Enabled>"
        f"<Repetition><Interval>{_REPEAT}</Interval><Duration>P1D</Duration>"
        "<StopAtDurationEnd>false</StopAtDurationEnd></Repetition>"
        "<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger>\n"
        f"    <LogonTrigger><Enabled>true</Enabled>{logon_user}</LogonTrigger>\n"
        "  </Triggers>\n"
        f'  <Principals><Principal id="Author">{logon_user}'
        "<LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>\n"
        "  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>"
        "<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>"
        "<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><StartWhenAvailable>true</StartWhenAvailable>"
        f"<ExecutionTimeLimit>{_TIME_LIMIT}</ExecutionTimeLimit><Enabled>true</Enabled></Settings>\n"
        f'  <Actions Context="Author"><Exec><Command>{escape(str(wrapper_path))}</Command>'
        f"<WorkingDirectory>{escape(str(project))}</WorkingDirectory></Exec></Actions>\n"
        "</Task>\n"
    )


def _task_mismatch(xml_text: str, wrapper_path: Path) -> Optional[str]:
    """U157: the first field where the installed task differs from the intended one, or None when it matches."""
    try:
        task = ET.fromstring(xml_text[xml_text.index("<Task"):])
    except (ValueError, ET.ParseError):
        return "parse"
    ns = {"t": _TASK_NS}
    checks = (
        ("command", task.findtext(".//t:Exec/t:Command", namespaces=ns), str(wrapper_path)),
        ("repetition", task.findtext(".//t:CalendarTrigger/t:Repetition/t:Interval", namespaces=ns), _REPEAT),
        ("logon", "present" if task.find(".//t:LogonTrigger", ns) is not None else "", "present"),
        ("instances", task.findtext(".//t:Settings/t:MultipleInstancesPolicy", namespaces=ns), "IgnoreNew"),
        ("catch_up", task.findtext(".//t:Settings/t:StartWhenAvailable", namespaces=ns), "true"),
    )
    for field, actual, wanted in checks:
        if (actual or "").strip() != wanted:
            return field
    return None


def _run_captured(
    cmd: list[str], cwd: Path, run: Optional[Callable[..., subprocess.CompletedProcess]] = None,
) -> tuple[int, str, str]:
    """Run one scheduler command; return (exit code, stdout, stderr), both stripped.

    U157 (Codex REVISE relay_8fda024b): a top-level function that binds `subprocess.run` itself, so
    firewall_audit lists this execution site; a call inside a nested closure was invisible to it.
    """
    if run is None:
        run = subprocess.run
    proc = run(
        cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
        errors="replace", check=False,
    )
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def windows_schedule(
    project: Path,
    python_bin: str,
    *,
    action: str = "install",
    apply: bool = False,
    run: Optional[Callable[..., subprocess.CompletedProcess]] = None,
    launcher: Optional[Path] = None,
) -> dict[str, Any]:
    """Manage a Windows Task Scheduler task that runs rsi watch every 15 minutes and at logon.

    Task names are made project-unique with a stable normalized-project hash so installing on two
    projects never collides. Install goes through a deterministic wrapper that `cd`s to the project
    root and calls absolute python/launcher paths. Supports install/status/remove/manual-now.

    U157: install imports the task as XML and reads it back, and status is a read-only query that runs
    without `apply`. install, remove and manual-now stay dry runs unless `apply=True`. A non-zero exit, or
    an installed task that differs from the intended one, is FAILED with a reason and never APPLIED.
    """
    if run is None:
        run = subprocess.run

    project = Path(project).resolve()
    # U157 (Codex REWORK relay_c8628506): a bare name is looked up on PATH, as a shell would. Path.resolve would
    # turn "python.exe" into <project>\python.exe. The found path is kept unresolved, so a venv launcher stays one.
    found = python_bin if Path(python_bin).is_absolute() else shutil.which(python_bin)
    interpreter = Path(found) if found else None
    python_bin = str(interpreter) if interpreter is not None else python_bin
    launcher = Path(launcher) if launcher is not None else Path.home() / ".uaos" / "uaos.py"
    task_name = _task_name(project)
    wrapper_text = _wrapper_text(project, python_bin, launcher)
    # U157: no space in the name; the old "rsi watch.cmd" split at the space in an unquoted /TR.
    wrapper_path = (project / ".work" / "rsi_watch.cmd").resolve()
    xml_path = wrapper_path.with_name("rsi_watch_task.xml")

    if action == "install":
        command = ["schtasks", "/Create", "/F", "/TN", task_name, "/XML", str(xml_path)]
    elif action == "status":
        command = ["schtasks", "/Query", "/TN", task_name, "/FO", "LIST", "/V"]
    elif action == "remove":
        command = ["schtasks", "/Delete", "/F", "/TN", task_name]
    elif action == "manual-now":
        command = [python_bin, str(launcher), "rsi", "watch", "--project", str(project)]
    else:
        raise ValueError(f"Unknown scheduler action: '{action}'")

    base = {"task_name": task_name, "wrapper_text": wrapper_text, "wrapper_path": str(wrapper_path),
            "launcher": str(launcher), "action": action, "command": command}

    if not apply and action != "status":
        return {"status": "DRY_RUN", **base}

    def call(cmd: list[str]) -> tuple[int, str, str]:
        return _run_captured(cmd, project, run)

    def failed(reason: str, output: str = "", error: str = "") -> dict[str, Any]:
        return {"ok": False, "status": "FAILED", "reason": reason, "output": output, "error": error, **base}

    if action == "install":
        if interpreter is None or not interpreter.is_file():
            return failed("INTERPRETER_MISSING", error=f"python interpreter not found: {python_bin}")
        if not launcher.is_file():
            return failed("RUNTIME_MISSING", error=f"installed runtime not found: {launcher}")
        wrapper_path.parent.mkdir(parents=True, exist_ok=True)
        wrapper_path.write_text(wrapper_text, encoding="utf-8", newline="")
        xml_path.write_text(_task_xml(wrapper_path, project), encoding="utf-16")  # schtasks /XML reads UTF-16
        rc, out, err = call(command)
        if rc != 0:
            return failed("CREATE_FAILED", out, err)
        rc, installed, err = call(["schtasks", "/Query", "/TN", task_name, "/XML"])
        if rc != 0:
            return failed("VERIFY_MISSING", installed, err)
        mismatch = _task_mismatch(installed, wrapper_path)
        if mismatch:
            return failed(f"VERIFY_MISMATCH:{mismatch}", installed, err)
        return {"ok": True, "status": "APPLIED", "output": out, "error": err, **base}

    rc, out, err = call(command)
    if rc != 0:
        return failed("TASK_MISSING" if action == "status" else "COMMAND_FAILED", out, err)
    return {"ok": True, "status": "QUERIED" if action == "status" else "APPLIED", "output": out, "error": err,
            **base}
