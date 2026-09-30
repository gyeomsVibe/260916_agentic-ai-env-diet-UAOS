"""U95-R fixed acceptance (judge-owned; the worker may not edit it): the research table is complete and sourced.

Exit 0 only when .coord/notes/U95_token_thrift_research.md holds a table with the fixed header, at least 2 rows per
question Q1-Q6 (18 rows at least), an https source and a short quote on every row, known tool and enforce values, and
a Recommendation section. Content truth is checked separately: Claude re-opens 5 sources by hand.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DOC = Path(".coord/notes/U95_token_thrift_research.md")
HEADER = ["id", "question", "finding", "source", "quote", "tool", "enforce"]
TOOLS = {"claude", "codex", "antigravity", "all"}
ENFORCE = {"rule", "config", "hook", "code", "none"}
QUESTIONS = [f"Q{n}" for n in range(1, 7)]
MIN_ROWS_PER_QUESTION = 2  # one source per claim is an anecdote; two let the judge compare
MAX_QUOTE_WORDS = 25  # quotes stay short: evidence, not reproduction


def main() -> int:
    if not DOC.is_file():
        print(f"FAIL missing {DOC}")
        return 1
    text = DOC.read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if line.strip().startswith("|")]
    cells = [[c.strip() for c in line.strip().strip("|").split("|")] for line in rows]
    if not cells or [c.lower() for c in cells[0]] != HEADER:
        print(f"FAIL header must be {HEADER}")
        return 1
    body = [c for c in cells[1:] if not all(set(x) <= set("-: ") for x in c)]
    errors: list[str] = []
    counts = {q: 0 for q in QUESTIONS}
    for n, row in enumerate(body, 1):
        if len(row) != len(HEADER):
            errors.append(f"row {n}: {len(row)} cells")
            continue
        rid, _question, finding, source, quote, tool, enforce = row
        question = rid.split("-")[0].upper()
        if question in counts:
            counts[question] += 1
        else:
            errors.append(f"row {n}: id {rid!r} is not Q1-Q6")
        if not finding:
            errors.append(f"row {n}: empty finding")
        if not re.match(r"^https://\S+$", source):
            errors.append(f"row {n}: source is not one https URL")
        if not quote or len(quote.split()) > MAX_QUOTE_WORDS:
            errors.append(f"row {n}: quote empty or over {MAX_QUOTE_WORDS} words")
        if tool.lower() not in TOOLS:
            errors.append(f"row {n}: tool {tool!r}")
        if enforce.lower() not in ENFORCE:
            errors.append(f"row {n}: enforce {enforce!r}")
    for question, count in counts.items():
        if count < MIN_ROWS_PER_QUESTION:
            errors.append(f"{question}: {count} rows < {MIN_ROWS_PER_QUESTION}")
    if not re.search(r"(?m)^## Recommendation", text):
        errors.append("no '## Recommendation' section")
    if errors:
        print("FAIL\n" + "\n".join(errors[:40]))
        return 1
    print(f"PASS rows={len(body)} per_question={counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
