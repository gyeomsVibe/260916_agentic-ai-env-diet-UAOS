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
