from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HANGUL = re.compile(r"[가-힣]")  # One Hangul syllable marks a Korean line, even with English terms in it.
LATIN_WORD = re.compile(r"[A-Za-z]{2,}")
ENGLISH_MIN_WORDS = 4  # Fewer Latin words is a label, path or ID, not English prose.


def lint_text(text: str) -> dict:
    counts = {"lines": 0, "korean": 0, "english": 0}
    in_fence = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not stripped:
            continue
        counts["lines"] += 1
        if HANGUL.search(stripped):
            counts["korean"] += 1
        elif len(LATIN_WORD.findall(stripped)) >= ENGLISH_MIN_WORDS:
            counts["english"] += 1
    return counts


def lint_transcript(path: Path) -> dict:
    totals = {"messages": 0, "lines": 0, "korean": 0, "english": 0}
    if Path(path).is_file():
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict) or row.get("type") != "assistant":
                continue
            # The client stores its own notices (usage limit, API error) as assistant rows; they are not Claude's words.
            if row.get("isApiErrorMessage") or (row.get("message") or {}).get("model") == "<synthetic>":
                continue
            content = (row.get("message") or {}).get("content")
            if isinstance(content, str):
                texts = [content]
            elif isinstance(content, list):
                texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
            else:
                texts = []
            if not texts:
                continue
            totals["messages"] += 1
            for text in texts:
                text_counts = lint_text(text)
                totals["lines"] += text_counts["lines"]
                totals["korean"] += text_counts["korean"]
                totals["english"] += text_counts["english"]
    totals["english_share"] = totals["english"] / totals["lines"] if totals["lines"] else 0.0
    return totals


def main(argv: list[str] | None = None) -> int:
    for path in argv if argv is not None else sys.argv[1:]:
        print(json.dumps({"path": path, **lint_transcript(Path(path))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
