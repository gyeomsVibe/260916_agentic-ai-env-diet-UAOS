```contract
work_id: U68-L
worker: apply
goal: The lane, apply and local Ollama workers print their JSON envelopes with ASCII escapes, as U68 did for the Claude worker
inputs:
- v7_harness/adapters/lane_worker.py sha256=0295df2427a5d2aea97850ada229f206159f981e40d8e41f80d78de1b294755e
- v7_harness/adapters/apply_worker.py sha256=a2c571607d86230e2ec7bd169c45b0c7a1be56c858adeec92b9eb753134069b2
- v7_harness/adapters/ollama_worker.py sha256=ae2587daf4291edb95a0ad93f32ef84c537ea75bcffcf9957cc1af99ec811aee
allow:
- v7_harness/adapters/lane_worker.py
- v7_harness/adapters/apply_worker.py
- v7_harness/adapters/ollama_worker.py
- tests/test_u68l_worker_envelopes_ascii.py
acceptance: python -m unittest tests.test_u68l_worker_envelopes_ascii tests.test_u68_claude_worker_utf8 tests.test_u17_lane_worker tests.test_u38_cost_gate_and_claude_worker tests.test_u44_long_prompt tests.test_u54_s2_caller_review
forbidden: design changes; edits outside allow; weakening or deleting existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Card U68-L (found during U68): the same ensure_ascii=False envelope print remains in three workers. New tests are 3/3 red on e271293 (UnicodeEncodeError on cp949). Judge claude (ACTING while Codex is LIMITED); Codex re-reviews. Write the three FILE blocks exactly and apply the one EDIT to ollama_worker.py (its own text holds ===FILE markers, so it cannot travel as a FILE block).

===EDIT: v7_harness/adapters/ollama_worker.py===
<<<<<<< SEARCH
    def envelope(status: str, response: str, usage: dict[str, int], error: str = "") -> int:
        print(json.dumps(
            {"status": status, "response": response, "usage": usage, "conversation_id": "ollama-local", "error": error},
            ensure_ascii=False,
=======
    def envelope(status: str, response: str, usage: dict[str, int], error: str = "") -> int:
        # U68-L: ASCII escapes; a cp949 pilot pipe raised UnicodeEncodeError on U+2014 and lost the envelope (U67-C1).
        print(json.dumps(
            {"status": status, "response": response, "usage": usage, "conversation_id": "ollama-local", "error": error},
            ensure_ascii=True,
>>>>>>> REPLACE
===FILE: v7_harness/adapters/lane_worker.py===
"""Local lane: the pilot's worker runs Claude Code's own tool loop on a local Ollama model.

The old local worker (ollama_worker.py) asks qwen2.5-coder:7b for whole files in one shot. This one lets the
model read and edit step by step. Bench (2026-09-23, .coord/runs/U17/rethink_local_lane_20260923.md): with the
harness prompt cut to ~2k tokens (--bare) and test files write-protected, qwen3.5:4b passed 5/6 toy tasks;
unprotected tests dropped it to 1/3 because it edited the test. Judgment stays with the pilot's acceptance gate.

Same contract as ollama_worker: `-p <prompt> --add-dir <workspace> --print-timeout Ns`, one JSON envelope out.
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

# Started by path from the pilot (no PYTHONPATH); make the package importable for pilot_holds.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from v7_harness.adapters.long_prompt import resolve_prompt, split_for_stdin  # noqa: E402

HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
# qwen3.5:4b with num_ctx 32768 (Modelfile). qwen2.5-coder emits tool calls as plain text, so it cannot drive a loop.
MODEL = os.environ.get("LANE_MODEL", "qwen3.5-32k")
MAX_TURNS = os.environ.get("LANE_MAX_TURNS", "20")  # bench passes took 8-14 turns
# No Bash: the lane edits a staged copy and the pilot runs the acceptance command itself. Shell access would let
# the model touch things outside the workspace.
TOOLS = "Read,Edit,Write,Glob,Grep"
# Test tampering was the main failure in the bench. Acceptance lives with the pilot; tests in the copy stay read-only.
PROTECTED = ["Edit(test_*)", "Edit(**/test_*)", "Edit(tests/**)", "Write(test_*)", "Write(**/test_*)", "Write(tests/**)"]
SYSTEM = ("You are a coding agent working in the current directory. Read the files you need, then edit them to "
          "complete the task. Do not edit tests. Stop when the change is done. Be brief.")
# Credentials for the paid API must never reach the local endpoint.
STRIP_ENV = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN")


def lane_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in STRIP_ENV}
    env.update(ANTHROPIC_BASE_URL=HOST, ANTHROPIC_AUTH_TOKEN="ollama", CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1")
    return env


def lane_command(prompt: str, model: str) -> list[str]:
    return [shutil.which("claude") or "claude", "-p", prompt, "--bare", "--tools", TOOLS, "--strict-mcp-config",
            "--disable-slash-commands", "--system-prompt", SYSTEM, "--model", model, "--max-turns", MAX_TURNS,
            "--permission-mode", "acceptEdits", "--allowedTools", TOOLS, "--disallowedTools", *PROTECTED,
            "--output-format", "json"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--prompt", required=True)
    parser.add_argument("--output-format", default="json")
    parser.add_argument("--print-timeout", default="600s")
    parser.add_argument("--add-dir", dest="workspace", required=True)
    parser.add_argument("--model", default=MODEL)
    args, _unknown = parser.parse_known_args(argv)
    args.prompt = resolve_prompt(args.prompt)
    timeout_s = int(str(args.print_timeout).rstrip("s") or 600)

    def envelope(status: str, response: str, usage: dict, error: str = "") -> int:
        # U68-L: ASCII escapes; a cp949 pilot pipe raised UnicodeEncodeError on U+2014 and lost the envelope (U67-C1).
        print(json.dumps({"status": status, "response": response, "usage": usage, "conversation_id": "ollama-lane",
                          "error": error}, ensure_ascii=True))
        return 0 if status == "SUCCESS" else 1

    empty = {"input_tokens": 0, "output_tokens": 0}
    started = time.monotonic()
    try:
        from v7_harness.adapters.gpu_priority import pilot_holds

        with pilot_holds(timeout_s):
            argv_prompt, stdin = split_for_stdin(args.prompt)
            done = subprocess.run(lane_command(argv_prompt, args.model), cwd=args.workspace, env=lane_env(),
                                  capture_output=True, timeout=timeout_s, input=stdin)
    except subprocess.TimeoutExpired:
        return envelope("ERROR", "", empty, f"lane timed out after {timeout_s}s")
    except OSError as exc:
        return envelope("ERROR", "", empty, f"lane could not start: {exc}")
    try:
        result = json.loads(done.stdout.decode("utf-8", errors="replace"))
    except ValueError:
        return envelope("ERROR", "", empty, f"lane returned no JSON (rc={done.returncode})")
    usage = {k: (result.get("usage") or {}).get(k, 0) for k in ("input_tokens", "output_tokens")}
    # Whole numbers only: the pilot's validate_usage rejects fractional counts and then blocks the run
    # (every lane run in the first e2e ended BLOCKED/VALIDATION because of elapsed_s=25.1).
    usage["elapsed_s"] = int(time.monotonic() - started)
    usage["turns"] = int(result.get("num_turns") or 0)
    # Hitting max turns still counts as work done; the pilot's acceptance gate decides pass or fail.
    if result.get("is_error") and result.get("subtype") not in ("error_max_turns",):
        return envelope("ERROR", "", usage, str(result.get("subtype") or "lane error"))
    # The pilot treats an empty response as invalid; the model sometimes ends on a tool call with no closing text.
    # The acceptance gate, not this text, decides the verdict.
    return envelope("SUCCESS", str(result.get("result") or "").strip()[:2000] or "(lane ended without a summary)", usage)


if __name__ == "__main__":
    sys.exit(main())
===FILE: v7_harness/adapters/apply_worker.py===
"""Deterministic pilot worker: applies the ===FILE / ===EDIT blocks written in the prompt itself. No model, 0 tokens.

When the commander has already written the exact code (P08 and P09 dictated 100% of the added lines), a model can
only copy it or damage it: P08's local run also deleted 41 lines nobody asked to remove. Applying the dictated blocks
directly is free and cannot hallucinate. The same guards as the local worker apply (_apply: atomic write, syntax
check, no unrequested deletion), and the pilot's acceptance gate still decides the verdict.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# The pilot starts workers by path without PYTHONPATH (see ollama_worker.py).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from v7_harness.adapters import ollama_worker  # noqa: E402
from v7_harness.adapters.long_prompt import resolve_prompt  # noqa: E402

NO_USAGE = {"input_tokens": 0, "output_tokens": 0}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--prompt", required=True)
    parser.add_argument("--add-dir", dest="workspace", required=True)
    args, _unknown = parser.parse_known_args(argv)
    args.prompt = resolve_prompt(args.prompt)

    def envelope(status: str, response: str, error: str = "") -> int:
        # U68-L: ASCII escapes; a cp949 pilot pipe raised UnicodeEncodeError on U+2014 and lost the envelope (U67-C1).
        print(json.dumps(
            {"status": status, "response": response, "usage": NO_USAGE, "conversation_id": "apply-deterministic",
             "error": error},
            ensure_ascii=True,
        ))
        return 0 if status == "SUCCESS" else 1

    if not ollama_worker.dictated_paths(args.prompt):
        return envelope("ERROR", "", "NO_BLOCKS_IN_PROMPT: write ===FILE or ===EDIT blocks, or use --worker local")
    try:
        written = ollama_worker._apply(args.prompt, Path(args.workspace), task=args.prompt)
    except ValueError as exc:
        return envelope("ERROR", "", str(exc))
    if not written:
        return envelope("ERROR", "", "no file written")
    return envelope("SUCCESS", f"wrote: {', '.join(written)}")


if __name__ == "__main__":
    sys.exit(main())
===FILE: tests/test_u68l_worker_envelopes_ascii.py===
"""U68-L: every pilot worker prints its envelope so a cp949 stdout cannot lose it.

U68 fixed the Claude worker after U67-C1 lost its envelope to UnicodeEncodeError on U+2014. The lane, apply and local
Ollama workers printed their envelopes the same way (`ensure_ascii=False`). Each test swaps stdout for a cp949 text
stream, drives the worker to an envelope that holds U+2014, and reads the bytes back as ASCII JSON.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import unittest
from contextlib import nullcontext
from unittest import mock

from v7_harness.adapters import apply_worker, lane_worker, ollama_worker

DASH = "—"


def _cp949_run(fn) -> tuple[int, dict]:
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp949", newline="\n")
    with mock.patch.object(sys, "stdout", stream):
        rc = fn()
        stream.flush()
    return rc, json.loads(raw.getvalue().decode("ascii"))


class WorkerEnvelopeCp949Tests(unittest.TestCase):
    def test_lane_worker(self) -> None:
        done = subprocess.CompletedProcess([], 0, stdout=json.dumps({"result": f"done {DASH}", "num_turns": 2},
                                                                    ensure_ascii=False).encode("utf-8"), stderr=b"")
        with mock.patch("v7_harness.adapters.gpu_priority.pilot_holds", lambda t: nullcontext()), \
                mock.patch.object(lane_worker.subprocess, "run", return_value=done):
            rc, env = _cp949_run(lambda: lane_worker.main(["-p", "x", "--add-dir", ".", "--print-timeout", "5s"]))
        self.assertEqual((0, "SUCCESS", f"done {DASH}"), (rc, env["status"], env["response"]))

    def test_apply_worker(self) -> None:
        with mock.patch.object(ollama_worker, "dictated_paths", return_value=["a.txt"]), \
                mock.patch.object(ollama_worker, "_apply", return_value=[f"a{DASH}b.txt"]):
            rc, env = _cp949_run(lambda: apply_worker.main(["-p", "x", "--add-dir", "."]))
        self.assertEqual((0, "SUCCESS", f"wrote: a{DASH}b.txt"), (rc, env["status"], env["response"]))

    def test_ollama_worker(self) -> None:
        with mock.patch("v7_harness.adapters.gpu_priority.pilot_holds", lambda t: nullcontext()), \
                mock.patch.object(ollama_worker, "_log"), \
                mock.patch.object(ollama_worker, "_generate", side_effect=OSError(f"down {DASH}")):
            rc, env = _cp949_run(lambda: ollama_worker.main(["-p", "x", "--add-dir", ".", "--print-timeout", "5s"]))
        self.assertEqual((1, "ERROR"), (rc, env["status"]))
        self.assertIn(f"down {DASH}", env["error"])


if __name__ == "__main__":
    unittest.main()
===END===

## Output

- Reply with ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.
