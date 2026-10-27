"""U212: the commit gate also accepts a native judge verdict recorded under the project's .coord/reviews/.

Receipts: U209-R2B and U209-R2C were refused at commit although Codex had judged the exact bundle natively
(.coord/reviews/U209-R2C-current-native-codex-verdict-261018.json, APPROVE_SCOPED_SOURCE_PROMOTION, bundle 907a1e15);
the workaround was an extra paid agy pilot review. A native verdict counts only when it names this task and bundle,
approves, comes from an independent judge that is not the author, and its recorded hashes match the run's identity.
Also U210: pilot_dirs.discover missed nested work dirs `.work/<a>/<b>`.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness import calculator_gate, pilot_dirs

BUNDLE = "907a1e15" + "0" * 56
SOURCE = "sha256:" + "1" * 64
FAILED_LOCAL = {"work_id": "U212-T0", "worker": "local", "outcome": "FAILED", "input_tokens": 900}


class NativeVerdict(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.work = root / ".work" / "u212"
        self.task = self.work / "runs" / "U212-T1"
        self.task.mkdir(parents=True)
        self.reviews = root / ".coord" / "reviews"
        self.reviews.mkdir(parents=True)
        (self.task / "worker").write_text("apply\n", encoding="utf-8")
        (self.task / "identity.json").write_text(json.dumps(
            {"task_id": "U212-T1", "source_hash": SOURCE, "bundle_id": BUNDLE}), encoding="utf-8")
        (self.task / "summary.json").write_text(json.dumps(
            {"promotion": "APPLIED", "bundle_id": BUNDLE, "changed_files": ["v7_harness/x.py"]}), encoding="utf-8")
        stage = self.work / "stage" / "U212-T1" / "v7_harness"
        stage.mkdir(parents=True)
        (stage / "x.py").write_bytes(b"X = 1\n")

    def tearDown(self):
        self._tmp.cleanup()

    def verdict(self, name="U212-T1-native-codex-verdict.json", **fields):
        record = {"task": "U212-T1", "bundle_id": BUNDLE, "verdict": "APPROVE_SCOPED_SOURCE_PROMOTION",
                  "judge": "codex", "author_worker": "apply", "independent": True}
        record.update(fields)
        (self.reviews / name).write_text(json.dumps(record), encoding="utf-8")

    def ok(self, rows=(FAILED_LOCAL,)) -> bool:
        return calculator_gate._review_ok(self.task, BUNDLE, list(rows), reviews_dir=self.reviews)

    def test_1_a_native_codex_approve_on_the_same_bundle_passes(self):
        self.verdict()
        self.assertTrue(self.ok())

    def test_2_the_commit_gate_accepts_the_staged_file(self):
        self.verdict()
        staged = {"v7_harness/x.py": b"X = 1\n"}
        self.assertEqual(calculator_gate.check(staged, "", self.work, ledger_rows=[FAILED_LOCAL],
                                               reviews_dir=self.reviews), [])
        self.assertTrue(calculator_gate.check(staged, "", self.work, ledger_rows=[FAILED_LOCAL]))

    def test_3_a_verdict_on_another_bundle_fails(self):
        self.verdict(bundle_id="f" * 64)
        self.assertFalse(self.ok())

    def test_4_a_revise_or_reject_verdict_fails(self):
        for verdict in ("REVISE", "REJECT", "REWORK", "", "NOT_APPROVED"):
            with self.subTest(verdict=verdict):
                self.verdict(verdict=verdict)
                self.assertFalse(self.ok())

    def test_5_the_author_never_judges_its_own_bundle(self):
        (self.task / "worker").write_text("codex\n", encoding="utf-8")
        self.verdict(author_worker="codex")
        self.assertFalse(self.ok())
        (self.task / "worker").write_text("antigravity\n", encoding="utf-8")
        self.verdict(judge="antigravity", author_worker="antigravity")
        self.assertFalse(self.ok())

    def test_6_a_relabeled_author_does_not_hide_the_real_author(self):
        (self.task / "worker").write_text("codex\n", encoding="utf-8")
        self.verdict(author_worker="apply")
        self.assertFalse(self.ok())

    def test_7_recorded_hashes_must_match_the_run_identity(self):
        self.verdict(source_hash="sha256:" + "2" * 64)
        self.assertFalse(self.ok())
        (self.task / "identity.json").write_text(json.dumps({"bundle_id": "e" * 64}), encoding="utf-8")
        self.verdict()
        self.assertFalse(self.ok())
        (self.task / "identity.json").unlink()
        self.assertFalse(self.ok())

    def test_8_weaker_records_fail_closed(self):
        cases = ({"task": "U212-T2"}, {"judge": "claude"}, {"judge": None}, {"independent": False},
                 {"error": "JUDGE_FAILED"})
        for fields in cases:
            with self.subTest(fields=fields):
                self.verdict(**fields)
                self.assertFalse(self.ok())

    def test_9_a_non_local_author_still_needs_a_failed_local_run(self):
        self.verdict()
        self.assertFalse(self.ok(rows=()))

    def test_10_no_reviews_dir_keeps_the_old_rule(self):
        self.verdict()
        self.assertFalse(calculator_gate._review_ok(self.task, BUNDLE, [FAILED_LOCAL]))


class NestedWorkDirs(unittest.TestCase):
    def test_11_discover_finds_work_a_b(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".work" / "u210" / "run6" / "runs").mkdir(parents=True)
            (root / ".work" / "u211_c" / "runs").mkdir(parents=True)
            found = pilot_dirs.discover(root)
            self.assertIn(root / ".work" / "u210" / "run6", found)
            self.assertIn(root / ".work" / "u211_c", found)


if __name__ == "__main__":
    unittest.main()
