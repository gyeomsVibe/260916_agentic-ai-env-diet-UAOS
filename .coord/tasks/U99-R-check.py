"""U99-R fixed check: the Antigravity research note has sourced rows for every question and one verdict per hypothesis.

Format only, not truth: the judge (claude) re-opens key sources before any finding is used.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

NOTE = Path(".coord/notes/U99_uaos_rsi_research.md")
# A row: | id | H1..H6 | finding | https-source | quote | ; a URL per row lets the judge re-open every claim.
ROW_RE = re.compile(r"^\| *R\d+ *\| *(H[1-6]) *\|[^|]+\| *https?://\S+ *\|[^|]+\|", re.M)
# One verdict line per hypothesis keeps the result machine-readable for the Review step.
VERDICT_RE = re.compile(r"^- (H[1-6]): (SUPPORTED|REFUTED|MIXED|UNKNOWN)\b", re.M)
# 12 rows is the cap given to the worker: the last two review runs overran their token caps (10.5x, 1.8x).
MAX_ROWS = 12


def main() -> int:
    """Return 0 when rows cite URLs, stay within the cap, and each of H1-H6 has exactly one verdict."""
    if not NOTE.is_file():
        print(f"MISSING {NOTE}")
        return 1
    text = NOTE.read_text(encoding="utf-8")
    rows = ROW_RE.findall(text)
    if not 1 <= len(rows) <= MAX_ROWS:
        print(f"ROWS={len(rows)} (need 1..{MAX_ROWS})")
        return 1
    verdicts = VERDICT_RE.findall(text)
    names = [name for name, _ in verdicts]
    missing = [f"H{i}" for i in range(1, 7) if names.count(f"H{i}") != 1]
    if missing:
        print(f"VERDICTS_MISSING_OR_DUPLICATE={missing}")
        return 1
    print(f"PASS rows={len(rows)} verdicts={len(verdicts)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
