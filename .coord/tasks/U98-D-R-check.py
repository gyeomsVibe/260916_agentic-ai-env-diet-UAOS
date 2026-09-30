"""U98-D-R fixed check: the Antigravity review exists, states a verdict and grounds each finding in a file and line.

Format only, not truth: the judge (claude) re-runs every attack the review claims.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REVIEW = Path(".coord/notes/U98-D-agy-review.md")
# One verdict line keeps the result machine-readable for the judge and the ledger.
VERDICT_RE = re.compile(r"^VERDICT: (PASS|FAIL)$", re.M)
# A finding row: | P1..P3 | file:line | attack | expected vs observed |. Grounding each finding in a line lets the judge re-run it.
FINDING_RE = re.compile(r"^\| *P[123] *\| *[\w./-]+\.(py|md):\d+ *\|", re.M)


def main() -> int:
    """Return 0 when the review has one verdict and, for FAIL, at least one grounded finding."""
    if not REVIEW.is_file():
        print(f"MISSING {REVIEW}")
        return 1
    text = REVIEW.read_text(encoding="utf-8")
    verdicts = VERDICT_RE.findall(text)
    if len(verdicts) != 1:
        print(f"VERDICT_LINES={len(verdicts)} (need exactly 1)")
        return 1
    findings = len(FINDING_RE.findall(text))
    if verdicts[0] == "FAIL" and findings == 0:
        print("FAIL_WITHOUT_FINDINGS")
        return 1
    print(f"PASS verdict={verdicts[0]} findings={findings}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
