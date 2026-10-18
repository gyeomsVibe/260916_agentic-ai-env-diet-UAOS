"""Fake `agy` CLI for M2 pilot tests. Behaviour is selected by FAKE_AGY_MODE.

success         : append a function to calc.py (or FAKE_AGY_TARGET) in --add-dir, print SUCCESS envelope
error503_write  : same write, then print status=ERROR 503 with a "DONE" claim (local evidence E1/E2)
outside_write   : write inside --add-dir AND a file into FAKE_AGY_OUTSIDE_DIR, print SUCCESS
partial_timeout : same write, SUCCESS envelope, stderr partial-timeout warning
no_change       : print SUCCESS without writing
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    mode = os.environ.get("FAKE_AGY_MODE", "success")
    workspace = Path(argv[argv.index("--add-dir") + 1])
    conversation = argv[argv.index("--conversation") + 1] if "--conversation" in argv else "fake-conv-0001"
    envelope = {
        "conversation_id": conversation,
        "status": "SUCCESS",
        "response": "DONE",
        "duration_seconds": 0.1,
        "num_turns": 1,
        "usage": {"input_tokens": 1000, "output_tokens": 100, "thinking_tokens": 50, "cache_read_tokens": 0, "total_tokens": 1150},
    }
    if mode != "no_change":
        target = workspace / os.environ.get("FAKE_AGY_TARGET", "calc.py")
        with target.open("a", encoding="utf-8") as stream:
            stream.write("\n\ndef add(a, b):\n    return a + b\n")
    if mode == "outside_write":
        outside = Path(os.environ["FAKE_AGY_OUTSIDE_DIR"])
        (outside / "escaped.txt").write_text("side effect", encoding="utf-8")
    if mode == "error503_write":
        envelope.update(status="ERROR", error="API error (attempt 1): UNAVAILABLE (code 503): No capacity available")
    if mode == "partial_timeout":
        sys.stderr.write("[agy] print timed out after 600s with turn in progress; returning partial output\n")
    sys.stdout.write(json.dumps(envelope))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
