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

JUDGE_TOOL = {"agy": "antigravity"}
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
    if budget is None:
        budget = judge_budget(len(diff))  # U47-J5: the cap follows what the judge must read
    request = runs / "judge_agy_request.md"
    request.write_text(judge_prompt(task_id, bundle_id, manual_text, diff,
                                    summary.get("acceptance_exit"), tail), encoding="utf-8")
    schema = runs / "judge_verdict.schema.json"
    schema.write_text(json.dumps(VERDICT_SCHEMA), encoding="utf-8")
    short = (f"Read {request.name} in this folder: a judge request with the contract, the acceptance result and the "
             "complete diff. Do not edit any file. Answer with the JSON verdict it asks for.")
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
        done = runner(argv, cwd=str(runs), env={**os.environ, "UAOS_WORKER": "1"}, capture_output=True,
                      timeout=timeout_s + 60)
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
                     ttl_s=quota_ttl(provider_message), now=marked_at)
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
        "task_id": task_id, "judge": JUDGE_TOOL[judge], "acting_for": "codex", "codex_state": why,
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
    _record_usage(source, task_id, usage, record, out)
    return record


def _record_usage(source: Path, task_id: str, usage: dict[str, int], record: dict, receipt: Path) -> None:
    if not ((source / ".git").exists() or (source / ".coord" / "PLAN.md").is_file()):
        return
    from .coord.usage_ledger import record_usage

    entry = {
        "schema": "uaos-usage-v2", "work_id": f"{task_id}-judge-agy", "actor": "antigravity", "model": "agy-default",
        "kind": "judge", "collection_mode": "automatic",
        "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
        "wall_time_s": record["elapsed_s"], "outcome": record["verdict"], "receipt": str(receipt.resolve()),
        "independent_verifier": "antigravity", "rsi_eligible": False, "exclusion_reason": "JUDGEMENT",
        "worker": "agy", "cost_gate": record["cost_gate"],
    }
    if "thinking_tokens" in usage:
        entry["thinking_tokens"] = usage["thinking_tokens"]
    try:
        record_usage(source, entry)
    except Exception as exc:  # noqa: BLE001 - judge_agy.json is the receipt; the ledger is best effort
        record["usage_ledger_error"] = f"{type(exc).__name__}: {exc}"[:200]
