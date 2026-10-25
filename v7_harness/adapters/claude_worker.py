"""Claude Code as a UAOS pilot worker (U38): `claude -p` on the paid account, inside the staged copy.

This is lane_worker's benchmarked call pointed back at Anthropic instead of the local model. Same contract as the other
workers: `-p <prompt> --add-dir <workspace> --print-timeout Ns [--model M]` in, one JSON envelope out. docs/40 §2-1.

What keeps it inside its lane:
- no Bash, and tests are write-protected: the pilot runs the acceptance itself (lane bench: test tampering was the
  main failure);
- `.coord/**` is write-protected too. The staged copy holds `.coord/PLAN.md`, so a presence hook firing there would
  write into the copy and turn a good run into a SCOPE_VIOLATION; UAOS_WORKER makes the UAOS hooks write nothing;
- `--safe-mode --restricted --permission-prompts none`, not `--bare`: Codex checked Claude Code 2.1.281 on the user's
  PC, where `--bare` never reads the OAuth login (a claude.ai / Pro subscription) and needs an API key, which UAOS will
  not read or inject. The safe/restricted pair is a hypothesis for hook suppression and root confinement until one
  approved real call proves it (docs/40);
- `--max-budget-usd` from the contract's `remote_budget_usd` is a spending threshold that can overshoot, not a
  pre-spend hard cap; without it the worker refuses to start (NO_USD_CAP). Dollars are never inferred from tokens;
- the parent session's markers are removed and UAOS_WORKER=claude is set, so hooks and logs never take the worker
  for the commander;
- every token kind and the dollar cost are reported, so the pilot's cost gate (B85) sees the whole spend.
The judge of a `worker: claude` run is Codex or the user (manual lint: SELF_JUDGE).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# The pilot starts workers by path without PYTHONPATH (see ollama_worker.py).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from v7_harness.adapters.long_prompt import resolve_prompt, split_for_stdin  # noqa: E402
import hashlib
import math

DEFAULT_MODEL = os.environ.get("CLAUDE_WORKER_MODEL", "sonnet")
MAX_TURNS = os.environ.get("CLAUDE_WORKER_MAX_TURNS", "30")
TOOLS = "Read,Edit,Write,Glob,Grep"
PROTECTED = [
    "Edit(test_*)", "Edit(**/test_*)", "Edit(tests/**)", "Write(test_*)", "Write(**/test_*)", "Write(tests/**)",
    "Edit(.coord/**)", "Write(.coord/**)", "Edit(.claude/**)", "Write(.claude/**)",
]
SYSTEM = ("You are a UAOS worker editing a staged copy of a project. Follow the contract in the prompt exactly: change "
          "only the files it allows, do not edit tests, do not run commands. Make the change with the Edit or Write "
          "tool: the harness reads the files, not your reply, so if the contract asks for ===FILE / ===EDIT blocks, "
          "apply them to the files instead of printing them. Stop when the change is done. Be brief.")
# Markers of the parent Claude Code session. Inherited, they would make the worker look like the commander.
PARENT_MARKERS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION_ID", "CLAUDE_PROJECT_DIR")
USAGE_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def worker_env(environ: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if environ is None else environ)
    for key in PARENT_MARKERS:
        env.pop(key, None)
    # lane points the CLI at the local Ollama endpoint; a paid worker must not inherit that redirect.
    base = env.get("ANTHROPIC_BASE_URL", "")
    ollama = env.get("OLLAMA_HOST", "127.0.0.1:11434").replace("http://", "").replace("https://", "")
    if base and (":11434" in base or ollama in base):
        env.pop("ANTHROPIC_BASE_URL", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
    env["UAOS_WORKER"] = "claude"
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    return env


def claude_executable() -> list[str]:
    """The claude CLI, or CLAUDE_WORKER_CMD as a JSON list (a non-standard install, or a stand-in for tests; a JSON
    list rather than a shell string so Windows paths need no quoting)."""
    override = os.environ.get("CLAUDE_WORKER_CMD")
    if override:
        value = json.loads(override)
        if isinstance(value, list) and value and all(isinstance(part, str) for part in value):
            return value
        raise ValueError("CLAUDE_WORKER_CMD must be a JSON list of strings")
    return [shutil.which("claude") or "claude"]


ISOLATION = ["--safe-mode", "--restricted", "--permission-prompts", "none"]


def _usd(value: float) -> str:
    return f"{float(value):.2f}"


def worker_command(prompt: str, model: str, max_budget_usd: float) -> list[str]:
    return [*claude_executable(), "-p", prompt, *ISOLATION, "--tools", TOOLS, "--strict-mcp-config",
            "--disable-slash-commands", "--system-prompt", SYSTEM, "--model", model, "--max-turns", MAX_TURNS,
            "--max-budget-usd", _usd(max_budget_usd), "--permission-mode", "acceptEdits", "--allowedTools", TOOLS,
            "--disallowedTools", *PROTECTED, "--output-format", "json"]


REVIEW_TOOLS = "Read,Glob,Grep"
# A review gets the full diff in its prompt, so it needs few turns. Each turn re-reads the cached prompt and the gate
# counts cache reads, so turns multiply the counted tokens: U44-FIX took 14 turns / 578k tokens, U44-FIX3 6 turns /
# 218k with no verdict. 4 reading turns plus one forced final answer (review.py) keeps a review near 150-200k tokens.
REVIEW_MAX_TURNS = os.environ.get("CLAUDE_REVIEW_MAX_TURNS", "4")
REVIEW_SYSTEM = ("You are an independent UAOS reviewer. You may only read. Look for counterexamples: requirements of the "
                 "contract the change misses, deletions it did not ask for, edits outside its scope, tests it weakens. "
                 "Answer with one JSON object and nothing else.")


def review_command(prompt: str, model: str, max_budget_usd: float, resume: str | None = None) -> list[str]:
    """Read-only: no Edit, Write or Bash, so the reviewer cannot change what it judges. Same dollar cap as a worker.

    With *resume*, one more turn in that review session: the forced final answer after the reviewer ran out of turns.
    """
    return [*claude_executable(), "-p", prompt, *ISOLATION, "--tools", REVIEW_TOOLS, "--strict-mcp-config",
            "--disable-slash-commands", "--system-prompt", REVIEW_SYSTEM, "--model", model,
            "--max-turns", "1" if resume else REVIEW_MAX_TURNS,
            "--max-budget-usd", _usd(max_budget_usd), "--allowedTools", REVIEW_TOOLS,
            "--disallowedTools", "Edit", "Write", "Bash", "--output-format", "json",
            *(["--resume", resume] if resume else [])]


def usage_from(result: dict) -> dict[str, int]:
    raw = result.get("usage") or {}
    usage = {key: int(raw[key]) for key in USAGE_KEYS if isinstance(raw.get(key), (int, float)) and not isinstance(raw.get(key), bool)}
    cost = result.get("total_cost_usd")
    if isinstance(cost, (int, float)) and not isinstance(cost, bool):
        # The pilot accepts whole numbers only; micro-dollars keep the precision.
        usage["cost_microusd"] = int(round(float(cost) * 1_000_000))
    usage["turns"] = int(result.get("num_turns") or 0)
    return usage


def cap_overshoot(usage: dict, cap_usd: float) -> int | None:
    """U45-F6: claude checks --max-budget-usd after a turn, so a run can end above it (U45-G7 a001: $0.319 on a $0.30
    cap, +6%). The overshoot in micro-dollars is recorded as a gate result instead of being lost."""
    cost = usage.get("cost_microusd")
    if not isinstance(cost, int) or isinstance(cost, bool):
        return None
    over = cost - int(round(cap_usd * 1_000_000))
    return over if over > 0 else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--prompt", required=True)
    parser.add_argument("--output-format", default="json")
    parser.add_argument("--print-timeout", default="600s")
    parser.add_argument("--add-dir", dest="workspace", required=True)
    parser.add_argument("--model", default=None)
    parser.add_argument("--max-budget-usd", dest="max_budget_usd", default=None)
    parser.add_argument("--require-model", dest="require_model", default=None)
    args, _unknown = parser.parse_known_args(argv)
    args.prompt = resolve_prompt(args.prompt)
    timeout_s = int(str(args.print_timeout).rstrip("s") or 600)
    model = args.model or DEFAULT_MODEL
    attempt, journal_result, journal_failure = None, {}, None

    def envelope(status: str, response: str, usage: dict, error: str = "", extra: dict | None = None) -> int:
        try:
            _journal_finish(attempt, status, journal_result, journal_failure)
        except Exception:  # durable terminal-write failure cannot be reported as worker success
            status, response, error = "ERROR", "", "INVOCATION_JOURNAL_TERMINAL_FAILED"
        # U68: ASCII escapes, not ensure_ascii=False. On Windows the pilot's pipe is cp949, and an answer holding
        # U+2014 raised UnicodeEncodeError after the paid call (U67-C1), leaving no envelope. JSON escapes decode back
        # to the same text under any stdout encoding.
        payload = {"status": status, "response": response, "usage": usage, "conversation_id": "claude-worker",
                   "error": error}
        payload.update(extra or {})
        print(json.dumps(payload, ensure_ascii=True))
        return 0 if status == "SUCCESS" else 1

    try:
        cap = float(args.max_budget_usd) if args.max_budget_usd is not None else 0.0
    except ValueError:
        cap = 0.0
    if not cap > 0:
        return envelope("ERROR", "", {}, "NO_USD_CAP: a paid Claude call needs --max-budget-usd > 0 "
                                         "(the contract's remote_budget_usd)")

    try:
        attempt = _journal_start(args, model)
    except Exception:  # fail closed before command construction/provider dispatch; no diagnostic body
        return envelope("ERROR", "", {}, "INVOCATION_JOURNAL_START_FAILED")

    # Nothing reported means UNKNOWN to the cost gate, which blocks the run: a failed start is not a free run.
    started = time.monotonic()
    try:
        argv_prompt, stdin = split_for_stdin(args.prompt)
        done = subprocess.run(worker_command(argv_prompt, model, cap), cwd=args.workspace, env=worker_env(),
                              capture_output=True, timeout=timeout_s, input=stdin)
    except subprocess.TimeoutExpired:
        journal_failure = "TIMEOUT"
        return envelope("ERROR", "", {}, f"claude worker timed out after {timeout_s}s")
    except (OSError, ValueError) as exc:
        journal_failure = "PROCESS_ERROR"
        return envelope("ERROR", "", {}, f"claude worker could not start: {exc}")
    except BaseException as exc:
        _journal_abort(attempt, exc)
        raise
    try:
        result = json.loads(done.stdout.decode("utf-8", errors="replace"))
    except ValueError:
        journal_failure = "PARSE_ERROR"
        return envelope("ERROR", "", {}, f"claude returned no JSON (rc={done.returncode}): "
                                         f"{done.stderr.decode('utf-8', errors='replace')[:200]}")
    except BaseException as exc:
        _journal_abort(attempt, exc)
        raise
    if not isinstance(result, dict):
        journal_failure = "RESPONSE_FORMAT"
        return envelope("ERROR", "", {}, "claude returned a JSON value that is not an object")
    journal_result = result
    try:
        usage = usage_from(result)
    except Exception:
        journal_failure = "USAGE_FORMAT"
        return envelope("ERROR", "", {}, "claude returned invalid usage metadata")
    usage["elapsed_s"] = int(time.monotonic() - started)
    overshoot = cap_overshoot(usage, cap)
    if overshoot is not None:
        usage["usd_cap_overshoot_microusd"] = overshoot
    if result.get("is_error") and result.get("subtype") not in ("error_max_turns",):
        journal_failure = "PROVIDER_ERROR"
        return envelope("ERROR", "", usage, str(result.get("subtype") or result.get("result") or "claude error")[:300])
    extra = None
    if args.require_model:
        mismatch = model_mismatch(result, args.require_model)
        if mismatch:
            journal_failure = "MODEL_MISMATCH"
            return envelope("FAILED", "", usage, mismatch)
        extra = {"resolved_models": sorted(str(key) for key in (result.get("modelUsage") or {}))}
    return envelope("SUCCESS", str(result.get("result") or "").strip()[:2000] or "(claude ended without a summary)", usage,
                    extra=extra)




def model_mismatch(result: dict, pinned: str) -> str:
    """U236a: under --require-model every modelUsage key must be the pinned full id; anything else fails closed."""
    keys = sorted(str(key) for key in (result.get("modelUsage") or {}))
    return "" if keys == [pinned] else f"MODEL_MISMATCH: expected {pinned}, got {keys}"




def _journal_start(args, model: str) -> str:
    from v7_harness.invocation import start_attempt
    from v7_harness.olla import _caller

    return start_attempt(caller=os.environ.get("UAOS_CALLER") or _caller(),
                         project=str(Path(args.workspace).resolve()),
                         work_id=os.environ.get("UAOS_WORK_ID", "UNSCOPED"),
                         purpose=os.environ.get("UAOS_PURPOSE", "claude_worker"), model=model,
                         input_sha256=hashlib.sha256(args.prompt.encode("utf-8")).hexdigest(),
                         db=os.environ.get("UAOS_INVOCATION_DB"))




def _journal_usage(result: dict) -> dict:
    raw = result.get("usage")
    raw = raw if isinstance(raw, dict) else {}
    counts = {key: value if type(value := raw.get(key)) is int and value >= 0 else None
              for key in USAGE_KEYS}
    inputs = [counts[key] for key in USAGE_KEYS if key != "output_tokens"]
    values = {"input_tokens": sum(inputs) if all(v is not None for v in inputs) else None,
              "output_tokens": counts["output_tokens"], "cache_creation_input_tokens": counts["cache_creation_input_tokens"],
              "cache_read_input_tokens": counts["cache_read_input_tokens"], "provider": "claude_cli_unverified"}
    cost = result.get("total_cost_usd")
    if type(cost) in (int, float) and math.isfinite(cost) and cost >= 0:
        values["cost_usd"] = cost  # provider-reported list estimate; no OAuth/billing assertion
    return values




def _journal_finish(attempt: str | None, status: str, result: dict, failure: str | None) -> None:
    if attempt is None:
        return
    from v7_harness.invocation import finish_attempt

    finish_attempt(attempt, outcome="SUCCEEDED" if status == "SUCCESS" else "FAILED",
                   error_class=failure, db=os.environ.get("UAOS_INVOCATION_DB"), **_journal_usage(result))




def _journal_abort(attempt: str | None, exc: BaseException) -> None:
    from v7_harness.invocation import _exception

    _journal_finish(attempt, "ERROR", {}, _exception(exc))


if __name__ == "__main__":
    sys.exit(main())
