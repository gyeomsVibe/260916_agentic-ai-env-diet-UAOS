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
