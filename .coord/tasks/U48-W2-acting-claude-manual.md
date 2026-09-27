```contract
work_id: U48-W2
worker: apply
goal: The pilot judge resolves the codex binary through PATH/PATHEXT so `codex exec` starts on Windows (npm shim codex.cmd) instead of raising FileNotFoundError.
inputs:
- v7_harness/judge.py sha256=d3e7613ed3845af59a6b5f26bfceb834ef0f92b2a59271a3a3b16b8c76c1e335
allow:
- v7_harness/judge.py
- tests/test_u48_w2_codex_binary.py
acceptance: C:/Python314/python.exe -m unittest tests.test_u48_w2_codex_binary tests.test_u47_j6_codex_judge tests.test_u46_pilot_judge tests.test_u47_j5_judge_budget
forbidden: design changes; edits outside allow; weakening or deleting existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Card: PLAN U48-W2, raised as a side note in the U48-W1 row. Reproduction: `subprocess.run(['codex','--version'])`
raises `FileNotFoundError [WinError 2]` while `shutil.which('codex')` returns `...\npm\codex.CMD`.
The fix changes only the default runner, so the injected fake runners in the existing tests see the same argv.

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
import shutil
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


def run_resolved(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
    """subprocess.run with argv[0] resolved through PATH and PATHEXT first.

    On Windows `codex` is an npm shim (codex.cmd); CreateProcess does not apply PATHEXT, so the bare name raised
    FileNotFoundError and every codex judgement failed before starting (U48-W1 note). shutil.which finds the shim, and
    a missing binary keeps its bare name so the error still names what was looked for.
    """
    return subprocess.run([shutil.which(argv[0]) or argv[0], *argv[1:]], **kwargs)


def run_judge(*, task_id: str, work_dir: Path, source: Path, manual_path: Path, project: Path | None = None,
              judge: str = "agy", budget: int | None = None, timeout_s: int = 600, apply: bool = True,
              runner: Any = run_resolved, approver: Any = subprocess.run,
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
        "applied": False, "acceptance_exit": summary.get("acceptance_exit"),
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
    # U48-J1: the ledger entry is written first so the receipt on disk names it (or why it was skipped or failed).
    record["usage_ledger"] = _record_usage(source, task_id, usage, record, out, judge)
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    record["judge_path"] = str(out)
    return record


def _record_usage(source: Path, task_id: str, usage: dict[str, int], record: dict, receipt: Path,
                  judge: str = "agy") -> dict[str, str]:
    """Append the judge's usage row; return the receipt's ledger reference (path and work id, or why none)."""
    if not ((source / ".git").exists() or (source / ".coord" / "PLAN.md").is_file()):
        return {"skipped": "NOT_A_PROJECT"}
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
        path = record_usage(source, entry)
    except Exception as exc:  # noqa: BLE001 - judge_agy.json is the receipt; the ledger is best effort
        record["usage_ledger_error"] = f"{type(exc).__name__}: {exc}"[:200]
        return {"work_id": entry["work_id"], "error": record["usage_ledger_error"]}
    return {"work_id": entry["work_id"], "path": str(path)}
===END===

===FILE: tests/test_u48_w2_codex_binary.py===
"""U48-W2: the pilot judge finds the codex npm shim on Windows instead of failing with FileNotFoundError."""

from __future__ import annotations

import inspect
import shutil
import subprocess
import unittest
from unittest import mock

from v7_harness import judge


class CodexBinaryResolution(unittest.TestCase):
    def test_run_judge_default_runner_resolves_the_binary(self) -> None:
        self.assertIs(judge.run_resolved, inspect.signature(judge.run_judge).parameters["runner"].default)

    def test_run_resolved_uses_the_path_lookup_and_keeps_the_arguments(self) -> None:
        with mock.patch.object(judge.shutil, "which", return_value=r"C:\npm\codex.CMD") as which, \
             mock.patch.object(judge.subprocess, "run", return_value="done") as run:
            self.assertEqual("done", judge.run_resolved(["codex", "exec", "-"], input=b"x", timeout=5))
        which.assert_called_once_with("codex")
        run.assert_called_once_with([r"C:\npm\codex.CMD", "exec", "-"], input=b"x", timeout=5)

    def test_missing_binary_keeps_its_bare_name(self) -> None:
        with mock.patch.object(judge.shutil, "which", return_value=None), \
             mock.patch.object(judge.subprocess, "run", side_effect=FileNotFoundError("codex")) as run:
            with self.assertRaises(FileNotFoundError):
                judge.run_resolved(["codex", "--version"])
        self.assertEqual(["codex", "--version"], run.call_args.args[0])

    @unittest.skipUnless(shutil.which(judge.CODEX_BINARY), "codex CLI not installed")
    def test_real_codex_version_starts(self) -> None:
        # `--version` makes no model call. Before the fix a bare "codex" raised FileNotFoundError on Windows.
        done = judge.run_resolved([judge.CODEX_BINARY, "--version"], capture_output=True, timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)


if __name__ == "__main__":
    unittest.main()
===END===

## Output

- Reply with ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.
