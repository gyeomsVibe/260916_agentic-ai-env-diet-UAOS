"""U54-S2: every CALLER_INPUT site has a human review in docs/51; a new or moved one fails until it is reviewed.

Counts per file, not line numbers: an unrelated edit above a call shifts its line without changing what can run.
"""

from __future__ import annotations

import unittest
from collections import Counter
from pathlib import Path

from v7_harness.firewall_audit import audit

ROOT = Path(__file__).resolve().parents[1]
REVIEW_DOC = ROOT / "docs" / "51_u54-s2-caller-input-review.md"
# The 21 CALLER_INPUT sites reviewed in docs/51 on 1685100 (verdicts: DATA_ARG 9, FIXED_PLAN 9, OPERATOR_COMMAND 3).
REVIEWED = {
    "v7_harness/adapters/claude_worker.py": 1,
    "v7_harness/adapters/lane_worker.py": 1,
    "v7_harness/coord/deliver.py": 2,
    "v7_harness/coord/notify.py": 1,
    "v7_harness/deploy_pc.py": 2,
    "v7_harness/execution/agy_launcher.py": 1,
    "v7_harness/execution/launcher.py": 2,
    "v7_harness/global_install.py": 1,
    "v7_harness/isolation/git_worktree.py": 1,
    "v7_harness/judge.py": 2,
    "v7_harness/olla.py": 3,
    "v7_harness/proof_receipt.py": 1,
    "v7_harness/review.py": 2,
    "v7_harness/rsi_release.py": 1,
}
VERDICTS = ("DATA_ARG", "FIXED_PLAN", "OPERATOR_COMMAND")


class CallerInputReviewTest(unittest.TestCase):
    def test_every_caller_input_site_is_reviewed(self):
        found = Counter(s.path for s in audit(ROOT) if s.status == "CALLER_INPUT")
        self.assertEqual(REVIEWED, dict(found),
                         "a CALLER_INPUT site was added, moved or removed: review it in docs/51, then update REVIEWED")

    def test_review_doc_has_one_verdict_row_per_site(self):
        rows = [ln for ln in REVIEW_DOC.read_text(encoding="utf-8").splitlines()
                if ln.startswith("| `") and any(f"| {v} |" in ln for v in VERDICTS)]
        per_file = Counter("v7_harness/" + ln.split("`")[1].rsplit(":", 1)[0] for ln in rows)
        self.assertEqual(REVIEWED, dict(per_file))
        self.assertEqual({"DATA_ARG": 9, "FIXED_PLAN": 9, "OPERATOR_COMMAND": 3},
                         dict(Counter(v for ln in rows for v in VERDICTS if f"| {v} |" in ln)))

    def test_no_command_injection_verdict_and_no_gap(self):
        self.assertEqual([], [s for s in audit(ROOT) if s.status == "GAP"])


if __name__ == "__main__":
    unittest.main()
