"""OS card summaries keep purpose and current work visible, without recurring translation."""
import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord import card_summary as cs
from v7_harness import card_pipeline as cards
from v7_harness.coord import schedule_planner as schedules


class CardSummaries(unittest.TestCase):
    def test_bilingual_user_and_english_agent(self):
        row = {"phase_id": "U900", "title_ko": "카드 목적 표시", "title_en": "Card purpose labels",
               "action_ko": "결과 경로 검증", "action_en": "Verify result path", "state": "REVIEW"}
        user = cs.format_card_summary(row)
        self.assertIn("U900", user)
        for part in ("카드 목적 표시", "Card purpose labels", "결과 경로 검증", "Verify result path"):
            self.assertIn(part, user)
        agent = cs.format_card_summary(row, audience="agent")
        self.assertIn("Card purpose labels", agent)
        self.assertIn("Verify result path", agent)
        self.assertFalse(any("가" <= ch <= "힣" for ch in agent))

    def test_child_parent_receipt_and_role_are_recorded_without_writing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".coord/cards").mkdir(parents=True)
            receipt = root / ".coord/cards/U900.json"
            receipt.write_text(json.dumps({"card": "U900", "title": "카드 목적 표시 / Card purpose labels"}), encoding="utf-8")
            before = receipt.read_bytes()
            for role, ko, en in (("VERIFY", "독립 검증", "Independent verification"),
                                 ("RELEASE", "릴리스", "Release")):
                text = cs.format_card_summary({"phase_id": "U900-" + role, "title": "U900-" + role}, project=root)
                for part in ("카드 목적 표시", "Card purpose labels", ko, en):
                    self.assertIn(part, text)
            self.assertEqual(before, receipt.read_bytes())

    def test_missing_language_and_purpose_are_honest_and_bounded(self):
        text = cs.format_card_summary({"phase_id": "U900", "title": "U900"})
        self.assertIn("작업 목적 미등록", text)
        self.assertIn("Purpose not recorded", text)
        text = cs.format_card_summary({"phase_id": "U900", "title_ko": "가" * 1000,
                                      "title_en": "title " * 1000, "action_en": "do " * 1000})
        self.assertLessEqual(len(text), 600)
        self.assertEqual(1, len(text.splitlines()))

    def test_explicit_id_titles_are_not_a_purpose(self):
        for identity in ("U900", "u900", "U900 (PR #1)", "U900 / U901 (PR #22)"):
            text = cs.format_card_summary({"phase_id": "U900", "title_ko": identity, "title_en": identity})
            self.assertIn("작업 목적 미등록", text)
            self.assertIn("Purpose not recorded", text)

    def test_summary_total_cap_keeps_identity_pr_and_all_four_narrative_fields(self):
        row = {"card_id": "X" * 60, "state": "R" * 24, "pr": "9" * 140,
               "title_ko": "가" * 100, "title_en": "t" * 100,
               "action_ko": "나" * 100, "action_en": "a" * 100}
        before = dict(row)
        user = cs.format_card_summary(row)
        self.assertLessEqual(len(user), 600)
        for required in (row["card_id"], row["state"], row["pr"], "가" * 24, "t" * 24, "나" * 24, "a" * 24):
            self.assertIn(required, user)
        self.assertIn("…", user)
        agent = cs.format_card_summary(row, audience="agent")
        self.assertLessEqual(len(agent), 600)
        self.assertFalse(cs.HANGUL.search(agent))
        self.assertEqual(row, before)

    def test_generic_id_and_pr_title_falls_back_to_recorded_parent_purpose(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".coord/cards").mkdir(parents=True)
            (root / ".coord/cards/U900.json").write_text(json.dumps({"card": "U900", "title": "실제 목적 / Actual purpose"}), encoding="utf-8")
            (root / ".coord/master_schedule.json").write_text(json.dumps({"phases": [{"phase_id": "U900", "title": "U900 (PR #1)"}]}), encoding="utf-8")
            text = cs.format_card_summary({"phase_id": "U900-VERIFY", "title": "U900-VERIFY (PR #1)"}, root)
            self.assertIn("실제 목적", text)
            self.assertIn("Actual purpose", text)

    def test_id_only_master_title_cannot_erase_receipt_purpose(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".coord/cards").mkdir(parents=True)
            (root / ".coord/cards/U900.json").write_text(json.dumps({"card": "U900", "title": "카드 목적 / Card purpose"}), encoding="utf-8")
            (root / ".coord/master_schedule.json").write_text(json.dumps({"phases": [{"phase_id": "U900", "title": "U900"}]}), encoding="utf-8")
            text = cs.format_card_summary({"phase_id": "U900-VERIFY"}, root)
            self.assertIn("Card purpose", text)

    def test_result_user_line_preserves_machine_result_contract(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cards.new_manual(root, "U900", "카드 목적 표시 / Card purpose labels", now=100)
            result = cards.write_result(root, "U900", "https://github.com/example/repo/pull/1", "yes", "8/0", "none")
            self.assertTrue(result["line"].startswith("RESULT U900 | PR "))
            for part in ("카드 목적 표시", "Card purpose labels", "U900"):
                self.assertIn(part, result["user_line"])
            self.assertIn("Await independent review", result["agent_summary"])
            self.assertIn("Card purpose labels", cards.collect_results(root)[0]["user_line"])

    def test_schedule_show_enriches_master_and_detail_without_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".coord").mkdir()
            phase = {"phase_id": "U900", "title": "카드 목적 표시 / Card purpose labels", "state": "ACTIVE",
                     "model_assignment": {"tool": "codex"}}
            driver = {"cards": {"U900": {"card_id": "U900", "title": phase["title"], "steps": [
                {"sub_id": "U900:SP3_CODE_EXECUTION", "stage": "SP3_CODE_EXECUTION", "step_index": 3,
                 "state": "ACTIVE", "assignment": {"tool": "codex"}}]}}}
            path = root / ".coord/master_schedule.json"
            path.write_text(json.dumps({"phases": [phase], "sub_schedule_driver": driver}), encoding="utf-8")
            before = path.read_bytes()
            master = schedules.show_master(root)
            self.assertIn("Card purpose labels", master["phases"][0]["user_summary"])
            detail = schedules.show_sub(root)
            self.assertIn("Card purpose labels", detail["cards"]["U900"][0]["user_summary"])
            self.assertIn("구현 / Implementation", detail["cards"]["U900"][0]["user_summary"])
            self.assertIn("U900", detail["cards"]["U900"][0]["agent_summary"])
            self.assertEqual(before, path.read_bytes())

    def test_result_roundtrip_keeps_recorded_bilingual_fields_after_long_heading(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            title = "카드 목적을 알아보기 쉽게 표시하는 개선 작업" * 2 + " / Preserve recorded bilingual purpose"
            cards.new_manual(root, "U900", title, now=100)
            made = cards.write_result(root, "U900", "https://github.com/example/repo/pull/1", "yes", "8/0", "none")
            read = cards.collect_results(root)[0]
            self.assertIn("Preserve recorded bilingual purpose", made["user_line"])
            self.assertEqual(made["user_line"], read["user_line"])
            self.assertEqual(made["agent_summary"], read["agent_summary"])

    def test_explicit_result_title_overrides_old_receipt_language_fields(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cards.new_manual(root, "U900", "이전 목적 / Old purpose", now=100)
            made = cards.write_result(root, "U900", "https://github.com/example/repo/pull/1", "yes", "8/0", "none",
                                      title="새 목적 / New purpose")
            self.assertIn("New purpose", made["user_line"])
            self.assertNotIn("Old purpose", made["user_line"])

    def test_completion_report_has_bilingual_purpose_and_current_result(self):
        report = cards.done_report("UAOS", "U900", "목적 표시 검증 완료 / Purpose display verified",
                                   "https://github.com/example/repo/pull/1", "a" * 40,
                                   title="카드 목적 표시 / Card purpose labels")
        for part in ("카드 목적 표시", "Card purpose labels", "목적 표시 검증 완료", "Purpose display verified", "U900"):
            self.assertIn(part, report)
        self.assertEqual([], cards.compact_report_problems(report))
        self.assertEqual(3, len(report.splitlines()))

    def test_completion_bounds_preserve_evidence_and_required_action(self):
        url = "https://github.com/example/" + "repo" * 10 + "/pull/1"
        action = "승인 대기 / Await authorization " + "check " * 10
        runtime = "0.6.0-" + "a" * 80
        report = cards.done_report("UAOS", "U900", "가" * 70 + " / " + "word " * 16,
                                   url, "a" * 40, runtime=runtime, user_action=action,
                                   title="가" * 70 + " / " + "title " * 13)
        self.assertLessEqual(len(report), 600)
        self.assertIn(url, report)
        self.assertIn(action.strip(), report)
        self.assertIn(runtime, report)
        self.assertEqual([], cards.compact_report_problems(report))

    def test_completion_refuses_to_cut_oversized_required_evidence(self):
        with self.assertRaisesRegex(ValueError, "REPORT_OVER_CHARS"):
            cards.done_report("UAOS", "U900", "검증 / Verification",
                              "https://github.com/example/" + "repository" * 80 + "/pull/1",
                              "a" * 40, user_action="승인 대기 / Await authorization", title="목적 / Purpose")

    def test_completion_without_title_does_not_invent_purpose(self):
        report = cards.done_report("UAOS", "U900", "기록 확인 / Record checked",
                                   "https://github.com/example/repo/pull/1", "a" * 40)
        self.assertIn("작업 목적 미등록", report)
        self.assertIn("Purpose not recorded", report)

    def test_human_action_line_remains_exact_and_missing_translation_is_elsewhere(self):
        report = cards.done_report("UAOS", "U900", "기록 확인 / Record checked",
                                   "https://github.com/example/repo/pull/1", "a" * 40,
                                   title="목적 표시 / Purpose display", user_action="새 세션을 여세요")
        self.assertEqual(report.splitlines()[2], "- **남은 일**: 새 세션을 여세요")
        self.assertIn("Remaining action translation not recorded", report.splitlines()[1])
        self.assertEqual([], cards.compact_report_problems(report))


if __name__ == "__main__":
    unittest.main()
