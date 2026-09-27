```contract
work_id: U47-RW1e
worker: apply
goal: Promote Codex's RW1c and RW1d fixes from HEAD with the J5 budget fixture shrunk below the 60,000-char binding-diff limit.
inputs:
- v7_harness/adapters/ollama_worker.py sha256=b11aa20d5dbdc29c198fb557a6e8e306523975de7be65f7d59e4bbffdff6f0f4
- v7_harness/cli.py sha256=69f31baf16bcd13ef0b8a1f4d3472786a9cf9be86b45372a4073326cf1f68768
- v7_harness/coord/presence.py sha256=43e091d5720d57facd7c08f0547412502ccc2497068b91b089cc11f0668ffb82
- v7_harness/judge.py sha256=7222487b766d6e7835cabe5a8f43af882e44e2644ccff54a4b420becae2aa455
- tests/test_u47_j5_judge_budget.py sha256=1020bfd1527aeb3fd151cdefd94147c9c98318af595046d75ba4c058d9e55f2f
allow:
- v7_harness/adapters/ollama_worker.py
- v7_harness/cli.py
- v7_harness/coord/presence.py
- v7_harness/judge.py
- tests/test_u47_j5_judge_budget.py
- tests/test_u47_n1d_mixed_endings.py
- tests/test_u47_a1b_presence_lease.py
- tests/test_u47_j6_codex_judge.py
- tests/test_u47_rw1c_counterexamples.py
- tests/test_u47_rw1d_counterexamples.py
acceptance: C:/Python314/python.exe D:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/.work/u45_claude/.coord/tasks/U47-RW1e-fixed-gate.py
forbidden: design changes; edits outside allow; editing or deleting other tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Fixed acceptance gate SHA-256: `ecbbe172c8212f2c61075a153913597a4ced4ddc6e798b6e72b7d73009edec6c`.
The gate is outside the source and allow list, so the worker cannot alter it.
Every block below is Codex's RW1d stage file byte-for-byte (LF), except the J5 fixture change explained in the file.

===EDIT: v7_harness/adapters/ollama_worker.py===
<<<<<<< SEARCH

    for target, (rel, content) in pending.items():
=======

    endings = {target: _line_ending(rel, target) for target, (rel, _content) in pending.items()}
    for target, (rel, content) in pending.items():
>>>>>>> REPLACE

===EDIT: v7_harness/adapters/ollama_worker.py===
<<<<<<< SEARCH
        # acceptance failed on a correct edit. Keep the line ending the file already uses; a new file gets LF.
        eol = "\r\n" if target.is_file() and b"\r\n" in target.read_bytes() else "\n"
        target.write_bytes(content.replace("\r\n", "\n").replace("\n", eol).encode("utf-8"))
    return written
=======
        # acceptance failed on a correct edit. Keep the line ending the file already uses; a new file gets LF.
        target.write_bytes(content.replace("\r\n", "\n").replace("\n", endings[target]).encode("utf-8"))
    return written
>>>>>>> REPLACE

===EDIT: v7_harness/adapters/ollama_worker.py===
<<<<<<< SEARCH
    return written

=======
    return written


def _line_ending(rel: str, target: Path) -> str:
    """The one line ending an existing file uses; LF for a new file or one without line breaks.

    U47-N1d: Codex's re-review (2026-09-27) sent b"a\\r\\nb\\n" and got every line back as CRLF. One ending per file
    cannot keep a mixed file's bytes, and guessing per line after a model rewrote it is not reliable, so a file that
    mixes CRLF, LF or a bare CR is refused before anything is written.
    """
    if not target.is_file():
        return "\n"
    data = target.read_bytes()
    crlf = data.count(b"\r\n")
    kinds = [eol for eol, n in (("\r\n", crlf), ("\n", data.count(b"\n") - crlf), ("\r", data.count(b"\r") - crlf)) if n]
    if len(kinds) > 1:
        raise ValueError(f"MIXED_LINE_ENDINGS:{rel}")
    return kinds[0] if kinds else "\n"

>>>>>>> REPLACE

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
    p_pilot_judge.add_argument("--project", default=None, help="Project whose presence desk says Codex is away")
    p_pilot_judge.add_argument("--judge", default="agy", choices=["agy"])
    p_pilot_judge.add_argument("--budget", type=int, default=None,
=======
    p_pilot_judge.add_argument("--project", default=None, help="Project whose presence desk says Codex is away")
    p_pilot_judge.add_argument("--judge", default="agy", choices=["agy", "codex"])
    p_pilot_judge.add_argument("--budget", type=int, default=None,
>>>>>>> REPLACE

===FILE: v7_harness/coord/presence.py===
"""Who is at the desk: one heartbeat file per tool, written by that tool's own session hooks.

The user used to declare "Codex is absent" by hand in PLAN.md, and that line stayed true until someone edited it.
A heartbeat carries its own expiry, so a tool that stops reporting (quota, crash, closed window) turns UNKNOWN
by itself. Reading and writing a small JSON file costs no model tokens.
"""

from __future__ import annotations

import json
import os
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
    return {"tool": tool, "state": record["state"], "observed_at": record.get("observed_at"), "expires_at": expires_at}


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
===END===

===FILE: v7_harness/judge.py===
"""U46-J4: while Codex is away, the acting conductor gets a binding Antigravity verdict through the agy CLI
(`pilot judge`), so no person relays a mailbox letter. docs/47 §2-1; Antigravity's consult
.coord/notes/U46_J3_agy_consult.md (option A); user decision 2026-09-26: "허용한다 — codex 부재중 권한대행 프로세스".

Default logic stays: while Codex is ACTIVE (or its state is not known), Codex judges and this command refuses.
agy only reads and answers: plan mode, a JSON schema, no permission bypass, the run folder as its only workspace.
The unchanged `pilot run --approve` gate applies the bundle, and only for an APPROVE that names this bundle within the
token budget. The approval stays attributable: the record keeps agy's conversation id and the sha256 of its verdict
(B83: an actor name alone proves nothing). One call per bundle, never retried; a failed call leaves the mailbox route.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

JUDGE_TOOL = {"agy": "antigravity", "codex": "codex"}
# U47-J6: `codex exec` answers headlessly (codex-cli 0.157.1, 2026-09-27), so Codex judges without a person relaying
# a letter. The re-review of that day asked for this route first, agy second, and REVIEW (no approval) when neither
# answers. Codex's desk state does not gate its own judgement; only agy acts *for* an away Codex.
CODEX_BINARY = "codex"
# U46-J1 live review used 71,299 tokens and the U46-J3 consult 89,263; 100,000 is the cap the consult proposed.
DEFAULT_BUDGET = 100_000
# U47-J5: R1c's 34 KB bundle cost 114,644 tokens against the fixed 100,000 cap (UNUSABLE); O3's 2-file bundle 35,126.
# (114,644 - 30,000) / 34,000 diff chars is ~2.5 tokens per char, so 30,000 + 3 per char covers both with margin.
# 250,000 keeps one judgement under a quarter of the U47-R2 worker run (1,141,039 tokens).
JUDGE_BASE_TOKENS = 30_000
JUDGE_TOKENS_PER_DIFF_CHAR = 3
MAX_AUTO_BUDGET = 250_000


def judge_budget(diff_chars: int) -> int:
    """The token cap for one judgement when the caller names none: never below DEFAULT_BUDGET nor above the max."""
    return min(MAX_AUTO_BUDGET,
               max(DEFAULT_BUDGET, JUDGE_BASE_TOKENS + JUDGE_TOKENS_PER_DIFF_CHAR * max(0, diff_chars)))
VERDICT_SCHEMA = {
    "type": "object",
    "required": ["verdict", "bundle_id", "evidence"],
    "properties": {
        "verdict": {"type": "string", "enum": ["APPROVE", "REJECT"]},
        "bundle_id": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
    },
}
# Enough of the acceptance log to show the failing or passing summary without flooding the judge prompt.
ACCEPTANCE_TAIL_CHARS = 4_000
# U47-A1: agy's quota answer names the wait ("Resets in 162h49m0s", 2026-09-27). The desk then reads LIMITED until the
# reset instead of a session heartbeat's ACTIVE, which had routed a verdict request to a tool that could not answer.
QUOTA_RESET_RE = re.compile(r"resets in\s*(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:(\d+)s)?", re.I)
# No reset time in the message: re-probe after an hour rather than guess a long outage.
QUOTA_FALLBACK_TTL_S = 3_600
# agy's error is one line (~170 chars with the reset time); 300 keeps it whole without storing a transcript.
PROVIDER_MESSAGE_CHARS = 300


def quota_ttl(message: str) -> int:
    """Seconds until agy's quota resets, read from its error text; one hour when the text names no time."""
    match = QUOTA_RESET_RE.search(message or "")
    if not match or not any(match.groups()):
        return QUOTA_FALLBACK_TTL_S
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return max(1, hours * 3600 + minutes * 60 + seconds)


def _provider_message(stdout: bytes) -> str:
    """agy's own error text from its JSON envelope, so a failed judgement says why (quota, auth, capacity)."""
    text = stdout.decode("utf-8", errors="replace")
    try:
        envelope = json.loads(text)
    except ValueError:
        return text[:PROVIDER_MESSAGE_CHARS]
    return str(envelope.get("error") or "")[:PROVIDER_MESSAGE_CHARS] if isinstance(envelope, dict) else ""


class JudgeRefused(Exception):
    pass


def build_codex_command(runs: Path, schema: Path, last: Path) -> list[str]:
    """Read-only `codex exec` in the run folder; the prompt goes on stdin and the verdict JSON to `last`."""
    return [CODEX_BINARY, "exec", "-s", "read-only", "--skip-git-repo-check", "-C", str(runs), "--json",
            "--output-schema", str(schema), "-o", str(last), "-"]


def parse_codex_events(stdout: bytes) -> tuple[dict[str, int], str | None, str]:
    """Usage, thread id and the last error from `codex exec --json` lines. Cached input stays inside input_tokens."""
    usage: dict[str, int] = {}
    thread_id = None
    error = ""
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind == "thread.started":
            thread_id = event.get("thread_id")
        elif kind == "turn.completed" and isinstance(event.get("usage"), dict):
            usage = {key: int(value) for key, value in event["usage"].items() if isinstance(value, int)}
        elif kind in ("error", "turn.failed"):
            detail = event.get("message") or (event.get("error") or {})
            error = str(detail.get("message") if isinstance(detail, dict) else detail)[:PROVIDER_MESSAGE_CHARS]
    return usage, thread_id, error


def codex_away(desk: dict[str, Any]) -> tuple[bool, str]:
    """Only a recorded LIMITED or ABSENT Codex hands judging to this path; ACTIVE or an expired heartbeat does not."""
    state = (desk.get("codex") or {}).get("state") or "UNKNOWN"
    if state in ("LIMITED", "ABSENT"):
        return True, f"codex {state}"
    return False, f"CODEX_JUDGES: codex is {state}; while Codex is active or unknown it judges (default logic)"


def judge_prompt(task_id: str, bundle_id: str, manual_text: str, diff: str, acceptance_exit: Any,
                 acceptance_tail: str) -> str:
    from .review import MAX_DIFF_CHARS

    return (f"[{task_id}] You are the judge named in this contract, acting while Codex is away. Decide whether bundle "
            f"{bundle_id} meets it. The diff is the complete change and the pilot already ran the acceptance command; "
            "judge from them. Do not edit any file.\n\n"
            f"## Contract\n{manual_text}\n\n## Acceptance (exit {acceptance_exit}, last lines)\n```\n{acceptance_tail}\n```\n\n"
            f"## Diff\n```diff\n{diff[:MAX_DIFF_CHARS]}\n```\n\n"
            'Reply with one JSON object: {"verdict": "APPROVE" or "REJECT", "bundle_id": "<the id above>", '
            '"evidence": ["path:line quote or failing check", "..."]}')


def gate_usage(usage: dict[str, int]) -> dict[str, int]:
    """agy reports thinking_tokens apart from output_tokens; they are paid output, so the gate counts them."""
    if not usage:
        return {}
    return {"input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0) + usage.get("thinking_tokens", 0)}


def parse_judgement(envelope: dict[str, Any]) -> dict[str, Any] | None:
    raw = envelope.get("structured_output")
    if not isinstance(raw, dict):
        match = re.search(r"\{.*\}", str(envelope.get("response") or ""), re.S)
        try:
            raw = json.loads(match.group(0)) if match else None
        except json.JSONDecodeError:
            raw = None
    if not isinstance(raw, dict) or raw.get("verdict") not in ("APPROVE", "REJECT"):
        return None
    return {"verdict": raw["verdict"], "bundle_id": str(raw.get("bundle_id") or ""),
            "evidence": [str(x)[:300] for x in raw.get("evidence") or []][:40]}


def run_judge(*, task_id: str, work_dir: Path, source: Path, manual_path: Path, project: Path | None = None,
              judge: str = "agy", budget: int | None = None, timeout_s: int = 600, apply: bool = True,
              runner: Any = subprocess.run, approver: Any = subprocess.run,
              desk: dict[str, Any] | None = None) -> dict[str, Any]:
    from .adapters.agy import AgyRequest, build_agy_command, parse_agy_result
    from .coord.presence import read_all
    from .manual import parse_contract
    from .pilot import evaluate_cost_gate
    from .review import bundle_diff

    if judge not in JUDGE_TOOL:
        raise JudgeRefused(f"UNKNOWN_JUDGE:{judge}")
    if budget is not None and budget <= 0:
        raise JudgeRefused("JUDGE_WITHOUT_BUDGET: pass --budget > 0 (a judgement is a paid call)")
    work_dir, source, manual_path = Path(work_dir).resolve(), Path(source).resolve(), Path(manual_path).resolve()
    if judge == "codex":
        why = "codex judges its own contract (U47-J6)"
    else:
        away, why = codex_away(desk if desk is not None else read_all(Path(project or source).resolve()))
        if not away:
            raise JudgeRefused(why)
    manual_text = manual_path.read_text(encoding="utf-8")
    contract = parse_contract(manual_text) or {}
    if contract.get("work_id") != task_id:
        raise JudgeRefused(f"TASK_MISMATCH: manual work_id {contract.get('work_id')!r} is not {task_id!r}")
    if contract.get("judge") != JUDGE_TOOL[judge]:
        raise JudgeRefused(f"NOT_THE_NAMED_JUDGE: the contract names judge {contract.get('judge')!r}")
    runs = work_dir / "runs" / task_id
    try:
        summary = json.loads((runs / "summary.json").read_text(encoding="utf-8"))
        author = (runs / "worker").read_text(encoding="utf-8").strip()
    except (OSError, json.JSONDecodeError) as exc:
        raise JudgeRefused(f"NO_PILOT_RUN:{runs} ({type(exc).__name__})") from exc
    if author in (judge, JUDGE_TOOL[judge]):
        raise JudgeRefused(f"JUDGE_IS_AUTHOR:{judge} wrote this bundle")
    if summary.get("promotion") != "DRY_RUN_PASSED" or summary.get("acceptance_exit") != 0:
        raise JudgeRefused(f"NOT_READY: promotion {summary.get('promotion')!r}, "
                           f"acceptance_exit {summary.get('acceptance_exit')!r}")
    bundle_id = str(summary.get("bundle_id") or "")
    out = runs / f"judge_{judge}.json"
    if out.is_file():
        # One call per bundle: a second call would buy a second opinion; a failed one goes to the mailbox route.
        raise JudgeRefused(f"ALREADY_JUDGED:{out}")
    staging = Path(summary.get("agy_workspace") or "")
    changed = [str(x) for x in summary.get("changed_files") or []]
    if not changed or not staging.is_dir():
        raise JudgeRefused("NOTHING_TO_JUDGE: no changed files or no staged copy")
    log = Path(summary.get("acceptance_log_path") or "")
    log = log if log.is_absolute() else source / log
    tail = log.read_text(encoding="utf-8", errors="replace")[-ACCEPTANCE_TAIL_CHARS:] if log.is_file() else "(no log)"

    diff = bundle_diff(source, staging, changed)
    from .review import MAX_DIFF_CHARS

    # U47-RW1d: the binding judge must see the complete diff. judge_prompt's display cap is not permission to hide
    # a changed tail, so refuse before starting a paid judge call instead of presenting a truncated bundle.
    if len(diff) > MAX_DIFF_CHARS:
        raise JudgeRefused(f"DIFF_TOO_LARGE_FOR_BINDING_JUDGEMENT:{len(diff)}>{MAX_DIFF_CHARS}")
    if budget is None:
        budget = judge_budget(len(diff))  # U47-J5: the cap follows what the judge must read
    request = runs / f"judge_{judge}_request.md"
    prompt_text = judge_prompt(task_id, bundle_id, manual_text, diff, summary.get("acceptance_exit"), tail)
    request.write_text(prompt_text, encoding="utf-8")
    schema = runs / "judge_verdict.schema.json"
    # codex's --output-schema is strict: every object closes its properties.
    schema.write_text(json.dumps({**VERDICT_SCHEMA, "additionalProperties": False}), encoding="utf-8")
    last = runs / "judge_codex_last.json"
    if judge == "codex":
        argv = build_codex_command(runs, schema, last)
    else:
        short = (f"Read {request.name} in this folder: a judge request with the contract, the acceptance result and "
                 "the complete diff. Do not edit any file. Answer with the JSON verdict it asks for.")
        argv = build_agy_command(AgyRequest(task_id=task_id, title="judge", prompt=short, workspace=runs,
                                            isolation_mode="staging", print_timeout_s=timeout_s, schema_path=schema))
        # Read-only planning (consult "Facts about agy"); skip_permissions stays False, so no bypass flag is added.
        argv += ["--mode", "plan"]
    started = time.monotonic()
    usage: dict[str, int] = {}
    conversation_id = None
    judgement = None
    error = ""
    envelope_sha = ""
    provider_message = ""
    presence_marked = ""
    marked_at = None
    try:
        # UAOS_WORKER=1 keeps the judge's own session hooks from writing a heartbeat: a headless judge call is not
        # the tool sitting at its desk (U47-J6 saw `codex exec` re-mark codex ACTIVE through its SessionStart hook).
        env = {**os.environ, "UAOS_WORKER": "1"}
        if judge == "codex":
            last.unlink(missing_ok=True)
            done = runner(argv, cwd=str(runs), env=env, input=prompt_text.encode("utf-8"), capture_output=True,
                          timeout=timeout_s + 60)
            stdout = done.stdout or b""
            usage, conversation_id, provider_message = parse_codex_events(stdout)
            answer = last.read_bytes() if last.is_file() else b""
            envelope_sha = hashlib.sha256(answer).hexdigest() if answer else ""
            # U47-RW1c: Codex's counterexample (2026-09-27) exited 1 but left a valid APPROVE file, which approved.
            # A failed call is never a verdict, whatever it wrote.
            if done.returncode != 0:
                error = f"JUDGE_FAILED:codex exit {done.returncode}"
            elif provider_message:
                error = "JUDGE_FAILED:codex error event"
            else:
                judgement = parse_judgement({"response": answer.decode("utf-8", errors="replace")})
                if judgement is None:
                    error = "JUDGE_UNPARSED: codex did not return the JSON verdict"
        else:
            done = runner(argv, cwd=str(runs), env=env, capture_output=True, timeout=timeout_s + 60)
            stdout = done.stdout or b""
            envelope_sha = hashlib.sha256(stdout).hexdigest()
            outcome = parse_agy_result(stdout=stdout, stderr=done.stderr or b"", exit_code=done.returncode)
            usage, conversation_id = dict(outcome.usage), outcome.conversation_id
            if outcome.successful:
                judgement = parse_judgement(json.loads(stdout.decode("utf-8", errors="replace")))
                if judgement is None:
                    error = "JUDGE_UNPARSED: agy did not return the JSON verdict"
            else:
                error = f"JUDGE_FAILED:agy {outcome.error_class}"
                provider_message = _provider_message(stdout)
                if outcome.error_class == "QUOTA":
                    from .coord.presence import mark

                    marked_at = time.time()
                    mark(Path(project or source).resolve(), JUDGE_TOOL[judge], "LIMITED",
                         ttl_s=quota_ttl(provider_message), now=marked_at, lease=True)  # U47-A1b
                    presence_marked = "LIMITED"
    except subprocess.TimeoutExpired:
        error = f"JUDGE_TIMEOUT:{timeout_s}s"
    except (OSError, ValueError) as exc:
        error = f"JUDGE_FAILED:{type(exc).__name__}: {exc}"[:300]
    cost_gate = evaluate_cost_gate(gate_usage(usage), budget)
    verdict = "UNUSABLE"
    if judgement and cost_gate == "WITHIN":
        if judgement["bundle_id"] == bundle_id:
            verdict = judgement["verdict"]
        else:
            error = f"BUNDLE_MISMATCH: verdict names {judgement['bundle_id']!r}"
    record: dict[str, Any] = {
        "task_id": task_id, "judge": JUDGE_TOOL[judge], "acting_for": None if judge == "codex" else "codex",
        "codex_state": why,
        "author_worker": author, "bundle_id": bundle_id, "verdict": verdict,
        "evidence": (judgement or {}).get("evidence", []),
        "judge_conversation_id": conversation_id, "envelope_sha256": envelope_sha,
        "verdict_sha256": (hashlib.sha256(json.dumps(judgement, sort_keys=True).encode("utf-8")).hexdigest()
                           if judgement else ""),
        "cost_gate": cost_gate, "budget": budget, "usage": usage, "elapsed_s": int(time.monotonic() - started), "error": error,
        "applied": False,
        "provider_message": provider_message, "presence_marked": presence_marked, "marked_at": marked_at,
    }
    if verdict == "APPROVE" and apply:
        # The unchanged approval gate does the promotion and re-checks digest, scope and the recorded cost gate.
        cmd = [sys.executable, "-m", "v7_harness.cli", "pilot", "run", "--task", task_id, "--worker", author,
               "--source", str(source), "--work-dir", str(work_dir), "--manual", str(manual_path),
               "--approve", bundle_id, "--coord-actor", JUDGE_TOOL[judge]]
        done = approver(cmd, cwd=str(Path(__file__).resolve().parents[1]), capture_output=True, timeout=900)
        tail_out = (done.stdout or b"").decode("utf-8", errors="replace")
        record["approve_exit"] = done.returncode
        record["approve_tail"] = tail_out[-1500:]
        record["applied"] = done.returncode == 0 and "APPLIED" in tail_out
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    record["judge_path"] = str(out)
    _record_usage(source, task_id, usage, record, out, judge)
    return record


def _record_usage(source: Path, task_id: str, usage: dict[str, int], record: dict, receipt: Path,
                  judge: str = "agy") -> None:
    if not ((source / ".git").exists() or (source / ".coord" / "PLAN.md").is_file()):
        return
    from .coord.usage_ledger import record_usage

    entry = {
        "schema": "uaos-usage-v2", "work_id": f"{task_id}-judge-{judge}", "actor": JUDGE_TOOL[judge], "model": f"{judge}-default",
        "kind": "judge", "collection_mode": "automatic",
        "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
        "wall_time_s": record["elapsed_s"], "outcome": record["verdict"], "receipt": str(receipt.resolve()),
        "independent_verifier": JUDGE_TOOL[judge], "rsi_eligible": False, "exclusion_reason": "JUDGEMENT",
        "worker": judge, "cost_gate": record["cost_gate"],
    }
    if "thinking_tokens" in usage:
        entry["thinking_tokens"] = usage["thinking_tokens"]
    try:
        record_usage(source, entry)
    except Exception as exc:  # noqa: BLE001 - judge_agy.json is the receipt; the ledger is best effort
        record["usage_ledger_error"] = f"{type(exc).__name__}: {exc}"[:200]
===END===

===FILE: tests/test_u47_j5_judge_budget.py===
"""U47-J5 frozen acceptance (written by Claude): a judgement's token cap scales with the diff it reads.

R1c's 34 KB bundle cost 114,644 tokens against the fixed 100,000 cap and came back UNUSABLE although agy approved it.
With no --budget, `run_judge` now uses `judge_budget(len(diff))` = clamp(30,000 + 3 x diff chars, 100,000, 250,000);
an explicit budget still wins, and the record names the cap it used.
"""

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness import judge

MANUAL = """```contract
work_id: T1
worker: apply
goal: g
allow:
- a.py
acceptance: python -c "pass"
judge: antigravity
remote_budget_tokens: 0
```
"""


class Done:
    def __init__(self, stdout=b"", returncode=0):
        self.stdout = stdout
        self.stderr = b""
        self.returncode = returncode


class BudgetFormulaTest(unittest.TestCase):
    def test_clamped_linear_in_diff_chars(self):
        self.assertEqual(100_000, judge.judge_budget(0))
        self.assertEqual(100_000, judge.judge_budget(-5))
        self.assertEqual(132_000, judge.judge_budget(34_000))
        self.assertEqual(250_000, judge.judge_budget(73_334))
        self.assertEqual(250_000, judge.judge_budget(10**7))

    def test_cli_default_budget_is_automatic(self):
        from v7_harness.cli import build_parser
        args = build_parser().parse_args(["pilot", "judge", "--task", "T1", "--work-dir", "w", "--manual", "m"])
        self.assertIsNone(args.budget)


class RunJudgeBudgetTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.work, self.source, stage = root / "work", root / "src", root / "stage"
        self.runs = self.work / "runs" / "T1"
        for folder in (self.runs, self.source, stage):
            folder.mkdir(parents=True)
        (self.source / "a.py").write_text("X = 1\n", encoding="utf-8")
        (stage / "a.py").write_text("".join(f"X{i} = {i}\n" for i in range(4000)), encoding="utf-8")
        # U47-RW1e: 4,000 lines = a 53,826-char diff (budget 191,478). RW1d refuses a diff over 60,000 chars,
        # so the old 6,000-line fixture (81,826 chars) could no longer reach the budget formula.
        (self.runs / "worker").write_text("claude", encoding="utf-8")
        (self.runs / "summary.json").write_text(json.dumps(
            {"agy_workspace": str(stage), "changed_files": ["a.py"], "bundle_id": "b1",
             "promotion": "DRY_RUN_PASSED", "acceptance_exit": 0}), encoding="utf-8")
        self.manual = root / "m.md"
        self.manual.write_text(MANUAL, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def runner(argv, **kwargs):
        envelope = {"status": "SUCCESS", "conversation_id": "conv-9",
                    "usage": {"input_tokens": 150_000, "output_tokens": 0},
                    "structured_output": {"verdict": "APPROVE", "bundle_id": "b1", "evidence": ["a.py:1 ok"]}}
        return Done(json.dumps(envelope).encode("utf-8"))

    def _judge(self, **kw):
        return judge.run_judge(task_id="T1", work_dir=self.work, source=self.source, manual_path=self.manual,
                               runner=self.runner, apply=False, desk={"codex": {"state": "ABSENT"}}, **kw)

    def test_no_budget_scales_with_the_diff(self):
        record = self._judge()
        self.assertGreaterEqual(record["budget"], 180_000)
        self.assertLessEqual(record["budget"], 250_000)
        self.assertEqual("WITHIN", record["cost_gate"])
        self.assertEqual("APPROVE", record["verdict"])

    def test_explicit_budget_still_wins(self):
        record = self._judge(budget=100_000)
        self.assertEqual(100_000, record["budget"])
        self.assertEqual("UNUSABLE", record["verdict"])

    def test_zero_budget_is_refused(self):
        with self.assertRaises(judge.JudgeRefused) as caught:
            self._judge(budget=0)
        self.assertIn("JUDGE_WITHOUT_BUDGET", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
===END===

===FILE: tests/test_u47_n1d_mixed_endings.py===
"""U47-N1d frozen acceptance (written by Claude): a file that mixes line endings is refused, never rewritten.

Codex's re-review of U47-N1c (2026-09-27) sent b"a\\r\\nb\\n": `_apply` picked CRLF for the whole file and returned
b"a\\r\\nb2\\r\\n", changing a line the edit never touched. The contract is now: one ending per file is kept byte for
byte (CRLF, LF or bare CR); a mixed file raises MIXED_LINE_ENDINGS and no file of the reply is written.
"""

import tempfile
import unittest
from pathlib import Path

from v7_harness.adapters import ollama_worker

EDIT_B = "===EDIT: {name}===\n<<<<<<< SEARCH\nb\n=======\nb2\n>>>>>>> REPLACE\n"


class MixedEndingsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_codex_counterexample_is_refused_and_bytes_kept(self):
        (self.ws / "m.txt").write_bytes(b"a\r\nb\n")
        with self.assertRaisesRegex(ValueError, "MIXED_LINE_ENDINGS:m.txt"):
            ollama_worker._apply(EDIT_B.format(name="m.txt"), self.ws)
        self.assertEqual(b"a\r\nb\n", (self.ws / "m.txt").read_bytes())

    def test_bare_cr_mixed_with_lf_is_refused(self):
        (self.ws / "m.txt").write_bytes(b"a\rb\n")
        with self.assertRaisesRegex(ValueError, "MIXED_LINE_ENDINGS"):
            ollama_worker._apply("===FILE: m.txt===\nz\n===END===\n", self.ws)
        self.assertEqual(b"a\rb\n", (self.ws / "m.txt").read_bytes())

    def test_refusal_writes_no_other_file_of_the_reply(self):
        (self.ws / "ok.txt").write_bytes(b"b\n")
        (self.ws / "m.txt").write_bytes(b"a\r\nb\n")
        with self.assertRaises(ValueError):
            ollama_worker._apply(EDIT_B.format(name="ok.txt") + EDIT_B.format(name="m.txt"), self.ws)
        self.assertEqual(b"b\n", (self.ws / "ok.txt").read_bytes())

    def test_single_ending_files_keep_their_bytes(self):
        for name, before, after in (("lf.txt", b"a\nb\n", b"a\nb2\n"), ("crlf.txt", b"a\r\nb\r\n", b"a\r\nb2\r\n"),
                                    ("cr.txt", b"a\rb\r", b"a\rb2\r")):
            (self.ws / name).write_bytes(before)
            self.assertEqual([name], ollama_worker._apply(EDIT_B.format(name=name), self.ws))
            self.assertEqual(after, (self.ws / name).read_bytes(), name)

    def test_new_file_and_file_without_breaks_get_lf(self):
        (self.ws / "one.txt").write_bytes(b"b")
        ollama_worker._apply("===FILE: one.txt===\nb\nc\n===END===\n===FILE: new.txt===\nx\ny\n===END===\n", self.ws)
        self.assertEqual(b"b\nc\n", (self.ws / "one.txt").read_bytes())
        self.assertEqual(b"x\ny\n", (self.ws / "new.txt").read_bytes())


if __name__ == "__main__":
    unittest.main()
===END===

===FILE: tests/test_u47_a1b_presence_lease.py===
"""U47-A1b frozen acceptance (written by Claude): a quota lease is not overwritten by a later session heartbeat.

Codex's re-review of U47-A1 (2026-09-27): `pilot judge` marked antigravity LIMITED from agy's 429 "Resets in 162h",
but the next ACTIVE session hook (presence.mark) replaced it, so routing again sent work to a tool that could not
answer. A lease holds until it expires; a heartbeat of the same state, a later lease, or expiry ends it.
"""

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord.presence import mark, read

T0 = 1_000_000.0


class PresenceLeaseTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_active_heartbeat_does_not_overwrite_live_lease(self):
        mark(self.project, "antigravity", "LIMITED", ttl_s=585_882, now=T0, lease=True)
        mark(self.project, "antigravity", "ACTIVE", ttl_s=3600, now=T0 + 60)
        desk = read(self.project, "antigravity", now=T0 + 120)
        self.assertEqual("LIMITED", desk["state"])
        self.assertEqual(T0 + 585_882, desk["expires_at"])

    def test_heartbeat_writes_again_after_the_lease_expires(self):
        mark(self.project, "antigravity", "LIMITED", ttl_s=100, now=T0, lease=True)
        mark(self.project, "antigravity", "ACTIVE", ttl_s=3600, now=T0 + 101)
        self.assertEqual("ACTIVE", read(self.project, "antigravity", now=T0 + 102)["state"])

    def test_a_new_lease_replaces_the_old_one(self):
        mark(self.project, "antigravity", "LIMITED", ttl_s=585_882, now=T0, lease=True)
        mark(self.project, "antigravity", "ACTIVE", ttl_s=3600, now=T0 + 10, lease=True)
        self.assertEqual("ACTIVE", read(self.project, "antigravity", now=T0 + 20)["state"])

    def test_plain_heartbeats_still_replace_each_other(self):
        mark(self.project, "codex", "LIMITED", ttl_s=3600, now=T0)
        mark(self.project, "codex", "ACTIVE", ttl_s=3600, now=T0 + 10)
        self.assertEqual("ACTIVE", read(self.project, "codex", now=T0 + 20)["state"])

    def test_lease_is_recorded_and_the_heartbeat_file_is_untouched(self):
        path = mark(self.project, "antigravity", "LIMITED", ttl_s=500, now=T0, lease=True)
        before = path.read_bytes()
        mark(self.project, "antigravity", "ACTIVE", ttl_s=3600, now=T0 + 1)
        self.assertEqual(before, path.read_bytes())
        self.assertIs(True, json.loads(before)["lease"])


if __name__ == "__main__":
    unittest.main()
===END===

===FILE: tests/test_u47_j6_codex_judge.py===
"""U47-J6 frozen acceptance (written by Claude): Codex judges a bundle headlessly through `codex exec`.

2026-09-27: agy answered 429 for 162h, Claude judged its own dictated bundles, and Codex's re-review (reached with
`codex exec`) rejected two of them and asked for this route: Codex first, agy second, and no approval (REVIEW) when
neither answers. The judge call must not write a desk heartbeat (UAOS_WORKER=1), must run read-only, and must
approve only a parsed verdict that names this bundle within budget.
"""

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness import judge
from v7_harness.coord.presence import mark, read

MANUAL = """```contract
work_id: T1
worker: apply
goal: g
allow:
- a.py
acceptance: python -c "pass"
judge: {judge}
remote_budget_tokens: 0
```
"""
EVENTS = [{"type": "thread.started", "thread_id": "th-1"}, {"type": "turn.started"},
          {"type": "turn.completed", "usage": {"input_tokens": 12_000, "cached_input_tokens": 8_000,
                                              "output_tokens": 900, "reasoning_output_tokens": 400}}]


class Done:
    def __init__(self, stdout=b"", returncode=0):
        self.stdout = stdout
        self.stderr = b""
        self.returncode = returncode


class CodexJudgeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.work, self.source, stage, self.project = root / "work", root / "src", root / "stage", root / "project"
        self.runs = self.work / "runs" / "T1"
        for folder in (self.runs, self.source, stage, self.project):
            folder.mkdir(parents=True)
        (self.source / "a.py").write_text("X = 1\n", encoding="utf-8")
        (stage / "a.py").write_text("X = 2\n", encoding="utf-8")
        (self.runs / "worker").write_text("apply", encoding="utf-8")
        (self.runs / "summary.json").write_text(json.dumps(
            {"agy_workspace": str(stage), "changed_files": ["a.py"], "bundle_id": "b1",
             "promotion": "DRY_RUN_PASSED", "acceptance_exit": 0}), encoding="utf-8")
        self.manual = root / "m.md"
        self.calls = []
        self.approvals = []

    def tearDown(self):
        self._tmp.cleanup()

    def run_codex(self, answer, returncode=0, events=EVENTS, judge_name="codex", desk=None):
        self.manual.write_text(MANUAL.format(judge=judge_name), encoding="utf-8")

        def runner(argv, **kwargs):
            self.calls.append((argv, kwargs))
            if answer is not None:
                Path(argv[argv.index("-o") + 1]).write_text(json.dumps(answer), encoding="utf-8")
            return Done("\n".join(json.dumps(e) for e in events).encode("utf-8"), returncode)

        def approver(cmd, **kwargs):
            self.approvals.append(cmd)
            return Done(b"APPLIED")
        return judge.run_judge(task_id="T1", work_dir=self.work, source=self.source, manual_path=self.manual,
                               project=self.project, judge="codex", budget=50_000, runner=runner,
                               approver=approver, desk=desk if desk is not None else {"codex": {"state": "ACTIVE"}})

    def test_approve_runs_read_only_without_heartbeat_and_approves_as_codex(self):
        record = self.run_codex({"verdict": "APPROVE", "bundle_id": "b1", "evidence": ["a.py:1 X = 2"]})
        argv, kwargs = self.calls[0]
        self.assertEqual(["codex", "exec", "-s", "read-only"], argv[:4])
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", argv)
        self.assertEqual("1", kwargs["env"]["UAOS_WORKER"])
        self.assertIn(b"bundle b1", kwargs["input"])
        self.assertEqual("APPROVE", record["verdict"])
        self.assertEqual("th-1", record["judge_conversation_id"])
        self.assertEqual({"input_tokens": 12_000, "output_tokens": 900}, judge.gate_usage(record["usage"]))
        self.assertTrue(record["applied"])
        self.assertEqual("codex", self.approvals[0][self.approvals[0].index("--coord-actor") + 1])
        self.assertTrue((self.runs / "judge_codex.json").is_file())

    def test_codex_judges_whatever_its_desk_says(self):
        self.assertEqual("REJECT", self.run_codex({"verdict": "REJECT", "bundle_id": "b1", "evidence": ["x"]},
                                                  desk={"codex": {"state": "UNKNOWN"}})["verdict"])
        self.assertEqual([], self.approvals)

    def test_failed_call_fails_closed(self):
        errors = [{"type": "thread.started", "thread_id": "th-2"},
                  {"type": "turn.failed", "error": {"message": "usage limit reached"}}]
        record = self.run_codex(None, returncode=1, events=errors)
        self.assertEqual("UNUSABLE", record["verdict"])
        self.assertIn("JUDGE_FAILED:codex", record["error"])
        self.assertIn("usage limit", record["provider_message"])
        self.assertEqual([], self.approvals)

    def test_verdict_for_another_bundle_or_over_budget_is_unusable(self):
        self.assertEqual("UNUSABLE", self.run_codex({"verdict": "APPROVE", "bundle_id": "zz", "evidence": []})["verdict"])
        (self.runs / "judge_codex.json").unlink()
        big = [EVENTS[0], {"type": "turn.completed", "usage": {"input_tokens": 60_000, "output_tokens": 10}}]
        self.assertEqual("UNUSABLE", self.run_codex({"verdict": "APPROVE", "bundle_id": "b1", "evidence": []},
                                                    events=big)["verdict"])
        self.assertEqual([], self.approvals)

    def test_contract_must_name_codex(self):
        with self.assertRaisesRegex(judge.JudgeRefused, "NOT_THE_NAMED_JUDGE"):
            self.run_codex({"verdict": "APPROVE", "bundle_id": "b1", "evidence": []}, judge_name="claude")

    def test_agy_quota_lease_survives_the_next_heartbeat(self):
        self.manual.write_text(MANUAL.format(judge="antigravity"), encoding="utf-8")
        envelope = {"conversation_id": "c1", "status": "ERROR", "response": "",
                    "error": "RESOURCE_EXHAUSTED (code 429): Individual quota reached. Resets in 2h0m0s."}
        judge.run_judge(task_id="T1", work_dir=self.work, source=self.source, manual_path=self.manual,
                        project=self.project, budget=10_000,
                        runner=lambda argv, **k: Done(json.dumps(envelope).encode("utf-8")),
                        approver=lambda *a, **k: Done(), desk={"codex": {"state": "LIMITED"}})
        mark(self.project, "antigravity", "ACTIVE", ttl_s=3600)
        self.assertEqual("LIMITED", read(self.project, "antigravity")["state"])


if __name__ == "__main__":
    unittest.main()
===END===

===FILE: tests/test_u47_rw1c_counterexamples.py===
"""U47-RW1c frozen acceptance (written by Claude): Codex's two counterexamples to bundle U47-RW1 (2026-09-27).

1. `codex exec` exited 1 but left a valid APPROVE file; `pilot judge --judge codex` approved and applied it.
2. A heartbeat passed the lease check, a quota lease was written, and the heartbeat then replaced it (ACTIVE while
   the LIMITED lease was live). Reproduced with ordered threads and checked again with real parallel processes.
"""

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from v7_harness import judge
from v7_harness.coord import presence

ROOT = Path(__file__).resolve().parents[1]
MANUAL = """```contract
work_id: T1
worker: apply
goal: g
allow:
- a.py
acceptance: python -c "pass"
judge: codex
remote_budget_tokens: 0
```
"""
HEARTBEATS = """
import sys
sys.path.insert(0, sys.argv[1])
from v7_harness.coord.presence import mark
for _ in range(int(sys.argv[3])):
    mark(sys.argv[2], "antigravity", "ACTIVE", ttl_s=3600)
"""


class Done:
    def __init__(self, stdout=b"", returncode=0):
        self.stdout = stdout
        self.stderr = b""
        self.returncode = returncode


class NonzeroExitTest(unittest.TestCase):
    def test_failed_codex_call_with_valid_approve_file_is_not_a_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work, source, stage = root / "work", root / "src", root / "stage"
            runs = work / "runs" / "T1"
            for folder in (runs, source, stage):
                folder.mkdir(parents=True)
            (source / "a.py").write_text("X = 1\n", encoding="utf-8")
            (stage / "a.py").write_text("X = 2\n", encoding="utf-8")
            (runs / "worker").write_text("apply", encoding="utf-8")
            (runs / "summary.json").write_text(json.dumps(
                {"agy_workspace": str(stage), "changed_files": ["a.py"], "bundle_id": "b1",
                 "promotion": "DRY_RUN_PASSED", "acceptance_exit": 0}), encoding="utf-8")
            manual = root / "m.md"
            manual.write_text(MANUAL, encoding="utf-8")
            approvals = []

            def runner(argv, **kwargs):
                Path(argv[argv.index("-o") + 1]).write_text(
                    json.dumps({"verdict": "APPROVE", "bundle_id": "b1", "evidence": ["x"]}), encoding="utf-8")
                return Done(b'{"type": "thread.started", "thread_id": "t"}', returncode=1)

            record = judge.run_judge(task_id="T1", work_dir=work, source=source, manual_path=manual, project=root,
                                     judge="codex", budget=50_000, runner=runner,
                                     approver=lambda cmd, **k: approvals.append(cmd) or Done(b"APPLIED"),
                                     desk={"codex": {"state": "ACTIVE"}})
        self.assertEqual("UNUSABLE", record["verdict"])
        self.assertEqual("JUDGE_FAILED:codex exit 1", record["error"])
        self.assertFalse(record["applied"])
        self.assertEqual([], approvals)


class LeaseRaceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_ordered_interleaving_keeps_the_lease(self):
        checked, release = threading.Event(), threading.Event()
        original = presence._live_lease

        def gated(target, moment, state):
            result = original(target, moment, state)
            if threading.current_thread().name == "heartbeat":
                checked.set()
                release.wait(5)
            return result

        presence._live_lease = gated
        try:
            heartbeat = threading.Thread(name="heartbeat", target=presence.mark,
                                         args=(self.project, "antigravity", "ACTIVE"),
                                         kwargs={"ttl_s": 3600, "now": 1_001.0})
            heartbeat.start()
            self.assertTrue(checked.wait(5))
            lease = threading.Thread(name="lease", target=presence.mark,
                                     args=(self.project, "antigravity", "LIMITED"),
                                     kwargs={"ttl_s": 500, "now": 1_000.0, "lease": True})
            lease.start()
            lease.join(0.2)
            release.set()
            heartbeat.join(10)
            lease.join(10)
        finally:
            presence._live_lease = original
        self.assertFalse(heartbeat.is_alive() or lease.is_alive())
        self.assertEqual("LIMITED", presence.read(self.project, "antigravity", now=1_003.0)["state"])

    def test_parallel_processes_never_replace_a_live_lease(self):
        # 4 processes x 150 heartbeats run while the lease lands; each one after it must be dropped.
        procs = [subprocess.Popen([sys.executable, "-c", HEARTBEATS, str(ROOT), str(self.project), "150"])
                 for _ in range(4)]
        presence.mark(self.project, "antigravity", "ACTIVE", ttl_s=3600)
        presence.mark(self.project, "antigravity", "LIMITED", ttl_s=3600, lease=True)
        for proc in procs:
            self.assertEqual(0, proc.wait(120))
        self.assertEqual("LIMITED", presence.read(self.project, "antigravity")["state"])
        self.assertEqual([], [p.name for p in (self.project / ".coord" / "presence").iterdir()
                              if p.name != "antigravity.json"])


if __name__ == "__main__":
    unittest.main()
===END===

===FILE: tests/test_u47_rw1d_counterexamples.py===
"""U47-RW1d red-first counterexamples for the rejected RW1c stage."""

import json
import tempfile
import unittest
from pathlib import Path

from tests import test_u47_j6_codex_judge as j6_tests
from v7_harness import judge
from v7_harness.coord.presence import mark, read
from v7_harness.review import MAX_DIFF_CHARS


APPROVE = {"verdict": "APPROVE", "bundle_id": "b1", "evidence": ["x"]}


class Rw1dCounterexamplesTest(unittest.TestCase):
    def test_failed_event_blocks_valid_approve_even_with_zero_exit(self):
        case = j6_tests.CodexJudgeTest(methodName="test_failed_call_fails_closed")
        case.setUp()
        try:
            events = [
                {"type": "thread.started", "thread_id": "th-failed"},
                {"type": "turn.failed", "error": {"message": "quota"}},
            ]
            record = case.run_codex(APPROVE, returncode=0, events=events)
            self.assertEqual("UNUSABLE", record["verdict"])
            self.assertIn("JUDGE_FAILED:codex", record["error"])
            self.assertIn("quota", record["provider_message"])
            self.assertFalse(record.get("applied"))
            self.assertEqual([], case.approvals)
        finally:
            case.tearDown()

    def test_same_state_heartbeat_cannot_shorten_live_quota_lease(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            original_expiry = 1_000.0 + 162 * 3600
            mark(project, "antigravity", "LIMITED", ttl_s=162 * 3600, now=1_000.0, lease=True)
            mark(project, "antigravity", "LIMITED", ttl_s=3600, now=1_001.0)
            desk = read(project, "antigravity", now=5_000.0)
            self.assertEqual("LIMITED", desk["state"])
            self.assertEqual(original_expiry, desk["expires_at"])
            mark(project, "antigravity", "ACTIVE", ttl_s=3600, now=5_001.0)
            self.assertEqual("LIMITED", read(project, "antigravity", now=5_002.0)["state"])

    def test_oversized_complete_diff_is_refused_before_judge_call(self):
        case = j6_tests.CodexJudgeTest(methodName="test_failed_call_fails_closed")
        case.setUp()
        try:
            summary = json.loads((case.runs / "summary.json").read_text(encoding="utf-8"))
            stage_file = Path(summary["agy_workspace"]) / "a.py"
            stage_file.write_text("X = 2\n" * (MAX_DIFF_CHARS // 6 + 100), encoding="utf-8")
            with self.assertRaisesRegex(judge.JudgeRefused, "DIFF_TOO_LARGE"):
                case.run_codex(APPROVE)
            self.assertEqual([], case.calls)
            self.assertEqual([], case.approvals)
        finally:
            case.tearDown()


if __name__ == "__main__":
    unittest.main()
===END===

## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
