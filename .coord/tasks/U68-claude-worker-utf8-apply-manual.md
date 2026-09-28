```contract
work_id: U68
worker: apply
goal: The Claude worker prints its JSON envelope with ASCII escapes so a cp949 stdout never loses the envelope after a paid call
inputs:
- v7_harness/adapters/claude_worker.py sha256=1f5fa8ce418e6a2ee01aa74c029dbd3b17499e885d979faf7345cedfd6feee49
allow:
- v7_harness/adapters/claude_worker.py
- tests/test_u68_claude_worker_utf8.py
acceptance: python -m unittest tests.test_u68_claude_worker_utf8 tests.test_u38_cost_gate_and_claude_worker tests.test_u44_claude_contract
forbidden: design changes; edits outside allow; weakening or deleting existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

U67-C1 failed with UNKNOWN_EFFECT_NEEDS_RECONCILIATION: the worker printed an answer holding U+2014 with ensure_ascii=False to a cp949 pipe. Write the two files below exactly.

===FILE: v7_harness/adapters/claude_worker.py===
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
- `--max-budget-usd` from the contract's `remote_budget_usd` is a hard cap before spending; without it the worker
  refuses to start (NO_USD_CAP). Dollars are never inferred from tokens;
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
    args, _unknown = parser.parse_known_args(argv)
    args.prompt = resolve_prompt(args.prompt)
    timeout_s = int(str(args.print_timeout).rstrip("s") or 600)
    model = args.model or DEFAULT_MODEL

    def envelope(status: str, response: str, usage: dict, error: str = "") -> int:
        # U68: ASCII escapes, not ensure_ascii=False. On Windows the pilot's pipe is cp949, and an answer holding
        # U+2014 raised UnicodeEncodeError after the paid call (U67-C1), leaving no envelope. JSON escapes decode back
        # to the same text under any stdout encoding.
        print(json.dumps({"status": status, "response": response, "usage": usage, "conversation_id": "claude-worker",
                          "error": error}, ensure_ascii=True))
        return 0 if status == "SUCCESS" else 1

    try:
        cap = float(args.max_budget_usd) if args.max_budget_usd is not None else 0.0
    except ValueError:
        cap = 0.0
    if not cap > 0:
        return envelope("ERROR", "", {}, "NO_USD_CAP: a paid Claude call needs --max-budget-usd > 0 "
                                         "(the contract's remote_budget_usd)")

    # Nothing reported means UNKNOWN to the cost gate, which blocks the run: a failed start is not a free run.
    started = time.monotonic()
    try:
        argv_prompt, stdin = split_for_stdin(args.prompt)
        done = subprocess.run(worker_command(argv_prompt, model, cap), cwd=args.workspace, env=worker_env(),
                              capture_output=True, timeout=timeout_s, input=stdin)
    except subprocess.TimeoutExpired:
        return envelope("ERROR", "", {}, f"claude worker timed out after {timeout_s}s")
    except (OSError, ValueError) as exc:
        return envelope("ERROR", "", {}, f"claude worker could not start: {exc}")
    try:
        result = json.loads(done.stdout.decode("utf-8", errors="replace"))
    except ValueError:
        return envelope("ERROR", "", {}, f"claude returned no JSON (rc={done.returncode}): "
                                         f"{done.stderr.decode('utf-8', errors='replace')[:200]}")
    if not isinstance(result, dict):
        return envelope("ERROR", "", {}, "claude returned a JSON value that is not an object")
    usage = usage_from(result)
    usage["elapsed_s"] = int(time.monotonic() - started)
    overshoot = cap_overshoot(usage, cap)
    if overshoot is not None:
        usage["usd_cap_overshoot_microusd"] = overshoot
    if result.get("is_error") and result.get("subtype") not in ("error_max_turns",):
        return envelope("ERROR", "", usage, str(result.get("subtype") or result.get("result") or "claude error")[:300])
    return envelope("SUCCESS", str(result.get("result") or "").strip()[:2000] or "(claude ended without a summary)", usage)


if __name__ == "__main__":
    sys.exit(main())
===FILE: tests/test_u68_claude_worker_utf8.py===
"""U68: the Claude worker must report its envelope even when its own stdout is a cp949 pipe.

U67-C1 (2026-09-28) failed on Windows: the reviewer's answer held U+2014 (em dash), the worker printed its envelope
with `ensure_ascii=False`, and the cp949 stdout raised UnicodeEncodeError. The pilot then saw no envelope and recorded
UNKNOWN_EFFECT_NEEDS_RECONCILIATION although the paid call had already happened. The worker is started by path in a
child process, so the test runs it the same way with PYTHONIOENCODING=cp949 instead of calling main() in-process.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

WORKER = Path(__file__).resolve().parents[1] / "v7_harness" / "adapters" / "claude_worker.py"
# Characters seen in real answers: em dash (the U67-C1 case), a Korean word, and an emoji outside the BMP.
ANSWER = "done — 한글 \U0001F600"


class Cp949StdoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        fake = self.root / "fake_claude.py"
        fake.write_text(textwrap.dedent(f"""
            import json, sys
            out = {{"result": {ANSWER!r}, "num_turns": 1, "total_cost_usd": 0.01,
                    "usage": {{"input_tokens": 3, "output_tokens": 2}}}}
            sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode("utf-8"))
        """), encoding="utf-8")
        self.env = {**os.environ, "CLAUDE_WORKER_CMD": json.dumps([sys.executable, str(fake)]),
                    "PYTHONIOENCODING": "cp949", "PYTHONUTF8": "0"}

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _run(self) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(WORKER), "-p", "review", "--add-dir", str(self.root),
                               "--max-budget-usd", "0.10", "--print-timeout", "60s"],
                              env=self.env, capture_output=True, timeout=120)

    def test_non_cp949_answer_still_yields_one_envelope(self) -> None:
        done = self._run()
        self.assertEqual(0, done.returncode, done.stderr.decode("utf-8", errors="replace")[-400:])
        envelope = json.loads(done.stdout.decode("ascii"))
        self.assertEqual("SUCCESS", envelope["status"])
        self.assertEqual(ANSWER, envelope["response"])
        self.assertEqual(10_000, envelope["usage"]["cost_microusd"])

    def test_error_envelope_survives_cp949_too(self) -> None:
        self.env["CLAUDE_WORKER_CMD"] = json.dumps([sys.executable, "-c",
                                                    "import sys; sys.stderr.buffer.write('\\u2014 boom'.encode('utf-8')); sys.exit(3)"])
        done = self._run()
        envelope = json.loads(done.stdout.decode("ascii"))
        self.assertEqual("ERROR", envelope["status"])
        self.assertIn("— boom", envelope["error"])


if __name__ == "__main__":
    unittest.main()
===END===

## Output

- Reply with ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.
