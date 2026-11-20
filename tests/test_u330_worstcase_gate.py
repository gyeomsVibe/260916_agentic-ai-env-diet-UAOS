"""U330: `uaos card audit` refuses a new card whose manual lacks a filled failure-mode table; old cards are grandfathered."""
import json
import tempfile
import unittest
from pathlib import Path

from v7_harness import card_pipeline as cp

ROOT = Path(__file__).resolve().parents[1]
NEW = cp.WORSTCASE_GATE_EPOCH + 3600
OLD = cp.WORSTCASE_GATE_EPOCH - 3600
ROWS = ("peer silent limit", "message flood", "wait cycle deadlock", "crash mid-write",
        "duplicate delivery", "stale state", "conductor down", "user absent")


def table(rows=ROWS, test="tests/test_x.py::test_y"):
    lines = ["## Failure modes", "| Worst case | Detection | Fallback | Test |", "|---|---|---|---|"]
    lines += [f"| {r} | detect | abstain | {test} |" for r in rows]
    return "\n".join(lines) + "\n\n## Contract\n"


class WorstcaseGate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.desk = Path(self._tmp.name)
        (self.desk / "tests").mkdir()
        (self.desk / "tests" / "test_x.py").write_text("def test_y():" + chr(10) + "    pass" + chr(10), encoding="utf-8")

    def run_audit(self, card, now, body=None):
        out = cp.new_manual(self.desk, card, "Demo", now=now)
        if body is not None:
            Path(out["manual"]).write_text(body, encoding="utf-8")
        ledger = cp._ledger(self.desk)
        ledger.parent.mkdir(parents=True, exist_ok=True)
        rows = [{"work_id": f"{card}-L1", "worker": "local", "input_tokens": 5},
                {"work_id": f"{card}-A1", "worker": "agy", "input_tokens": 5}]
        ledger.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        return cp.audit(self.desk, card)

    def test_1_missing_table_fails(self):
        r = self.run_audit("U901", NEW, "# manual\n\n## Contract\n")
        self.assertFalse(r["ok"])
        self.assertIn("failure-mode table missing", " ".join(r["missing"]))

    def test_2_missing_row_fails(self):
        r = self.run_audit("U902", NEW, table(ROWS[:-1]))
        self.assertFalse(r["ok"])
        self.assertIn("row missing: user absent", " ".join(r["missing"]))

    def test_3_missing_test_reference_fails(self):
        r = self.run_audit("U903", NEW, table(test="TODO"))
        self.assertFalse(r["ok"])
        self.assertIn("test empty", " ".join(r["missing"]))

    def test_3b_nonexistent_test_target_fails(self):
        for ref in ("tests/test_nope.py::test_y", "tests/test_x.py::test_missing_name"):
            r = self.run_audit("U910", NEW, table(test=ref))
            self.assertFalse(r["ok"], ref)
            self.assertIn("test ", " ".join(r["missing"]))

    def test_3c_na_needs_a_real_reason(self):
        for bad in ("N/A", "N/A: none", "N/A: -", "n/a: tbd"):
            self.assertTrue(cp.worstcase_problems(table(test=bad), [self.desk]), bad)
        self.assertEqual([], cp.worstcase_problems(table(test="N/A: user absence is a human boundary, no code path"), [self.desk]))

    def test_3d_reference_bypasses_are_refused(self):
        (self.desk / "README.md").write_text("x", encoding="utf-8")
        (self.desk / "tests" / "test_c.py").write_text("class TestK:" + chr(10) + "    def test_m(self): pass" + chr(10)
                                                      + "# def test_commented" + chr(10), encoding="utf-8")
        bad = [";", ",", "`", " ; ,", "tests/test_x.py::", "tests/test_x.py::test_", "tests/test_x.py::y",
               "tests/test_c.py::test_commented", "tests/test_c.py::TestK::test_nope", "tests/test_c.py::TestNo::test_m",
               "README.md", "../README.md", "/etc/passwd", str(self.desk / "tests" / "test_x.py"), "tests/test_x.py::a::b::c"]
        for ref in bad:
            self.assertTrue(cp.worstcase_problems(table(test=ref), [self.desk]), ref)
        for good in ("tests/test_x.py::test_y", "tests/test_c.py::TestK::test_m", "tests/test_x.py; tests/test_c.py::TestK",
                     "`tests/test_x.py::test_y`"):
            self.assertEqual([], cp.worstcase_problems(table(test=good), [self.desk]), good)

    def test_3g_second_root_with_the_test_is_not_hidden_by_first(self):
        other = self.desk / "wt"
        (other / "tests").mkdir(parents=True)
        (other / "tests" / "test_x.py").write_text("def test_y(): pass" + chr(10) + "def test_new(): pass" + chr(10), encoding="utf-8")
        ref = table(test="tests/test_x.py::test_new")
        self.assertTrue(cp.worstcase_problems(ref, [self.desk]))
        self.assertEqual([], cp.worstcase_problems(ref, [self.desk, other]))
        self.assertEqual([], cp.worstcase_problems(ref, [other, self.desk]))

    def test_3e_na_marker_is_exact(self):
        self.assertTrue(cp.worstcase_problems(table(test="NA: user absence is a human boundary, no code path"), [self.desk]))

    def test_3f_one_row_cannot_satisfy_two_worst_cases(self):
        rows = ["peer silent, message flood, wait cycle, crash, duplicate, stale, conductor, user absent"]
        self.assertTrue(cp.worstcase_problems(table(rows), [self.desk]))

    def test_4_complete_table_passes(self):
        r = self.run_audit("U904", NEW, table())
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["worstcase"]["ok"])

    def test_5_old_card_is_grandfathered(self):
        r = self.run_audit("U905", OLD, "# manual without a table\n")
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["worstcase"]["grandfathered"])

    def test_6_template_emits_empty_table_that_fails_until_filled(self):
        text = cp.TEMPLATE.format(card="U906", title="t")
        self.assertIn("## Failure modes", text)
        self.assertEqual(8, len([ln for ln in text.splitlines() if ln.startswith("| ") and "Worst case" not in ln]))
        problems = cp.worstcase_problems(text)
        self.assertTrue(problems and not any("missing" in p and "table" in p for p in problems), problems)
        r = self.run_audit("U906", NEW)  # untouched template written by new_manual
        self.assertFalse(r["ok"])

    def test_6b_commit_gate_and_ship_pass_the_worktree_as_test_root(self):
        from unittest import mock
        from v7_harness import calculator_gate as cg

        seen = {}

        def fake(desk, card, **kw):
            seen.update(kw)
            return {"missing": []}

        with mock.patch.object(cp, "audit", fake):
            cg.card_errors("Card: U999\n", ["v7_harness/x.py"], self.desk, [], branch="claude/u999-x")
        self.assertEqual([Path(".")], seen.get("test_roots"))
        self.assertIn("test_roots=[Path(project)]", (ROOT / "v7_harness" / "cli.py").read_text(encoding="utf-8"))

    def test_7_rules_text_in_every_tool_file(self):
        for doc in ("AGENTS.md", "CLAUDE.md", "GEMINI.md", "uaos_everywhere/uaos_global_rule_block.md",
                    ".agents/rules/unified-codex-antigravity.md"):
            self.assertIn("U330", (ROOT / doc).read_text(encoding="utf-8"), doc)

    def test_8_every_rules_source_has_all_11_core_keys(self):
        for doc in ("AGENTS.md", "CLAUDE.md", "GEMINI.md", "uaos_everywhere/uaos_global_rule_block.md",
                    ".agents/rules/unified-codex-antigravity.md"):
            text = (ROOT / doc).read_text(encoding="utf-8")
            for n in range(1, 12):
                self.assertIn(f"[CORE-{n}]", text, f"{doc} lacks CORE-{n}")


if __name__ == "__main__":
    unittest.main()
