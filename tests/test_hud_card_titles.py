"""Card labels describe their purpose without inventing missing schedule facts."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord import capacity_planner as cp


class HudCardTitles(unittest.TestCase):
    def test_explicit_title_wins_and_whitespace_is_compacted(self):
        row = {"phase_id": "U900-VERIFY", "title": "  HUD 제목\n 표시 개선  ", "goal": "other"}
        self.assertEqual(cp.resolve_card_title(row, {}), "HUD 제목 표시 개선")

    def test_id_only_title_uses_purpose(self):
        row = {"phase_id": "U900-VERIFY", "title": "U900-VERIFY", "purpose": "HUD 카드 이름 개선"}
        self.assertEqual(cp.resolve_card_title(row, {}), "HUD 카드 이름 개선")

    def test_parent_title_and_suffix_make_child_purpose_clear(self):
        parent = {"phase_id": "U900", "title": "HUD 카드 이름 개선"}
        rows = {"U900": parent}
        self.assertEqual(cp.resolve_card_title({"phase_id": "U900-VERIFY"}, rows), "HUD 카드 이름 개선 · 독립 검증")
        self.assertEqual(cp.resolve_card_title({"phase_id": "U900-RELEASE"}, rows), "HUD 카드 이름 개선 · 병합·런타임 반영")

    def test_missing_context_does_not_invent_purpose_or_use_action_as_title(self):
        row = {"phase_id": "U900-VERIFY", "title": "U900-VERIFY", "action": "request independent verdict"}
        self.assertEqual(cp.resolve_card_title(row, {}), "작업 목적 미등록 · 독립 검증")

    def test_explicit_parent_and_cycles_are_safe(self):
        rows = {"PARENT": {"phase_id": "PARENT", "goal": "쿼터 표시 개선"}}
        self.assertEqual(cp.resolve_card_title({"phase_id": "CUSTOM", "parent_phase_id": "PARENT"}, rows), "쿼터 표시 개선")
        self.assertEqual(cp.resolve_card_title({"phase_id": "U900", "parent_phase_id": "U900"}, {}), "작업 목적 미등록")

    def test_card_receipt_supplies_purpose_without_parent_phase(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".coord/cards").mkdir(parents=True)
            (root / ".coord/cards/U900.json").write_text(
                json.dumps({"card": "U900", "title": "긴 작업 중 독립 진행"}), encoding="utf-8")
            self.assertEqual(cp.resolve_card_title({"phase_id": "U900-VERIFY"}, {}, root),
                             "긴 작업 중 독립 진행 · 독립 검증")
            (root / ".coord/cards/U900.json").write_text("{bad", encoding="utf-8")
            self.assertEqual(cp.resolve_card_title({"phase_id": "U900-RELEASE"}, {}, root),
                             "작업 목적 미등록 · 병합·런타임 반영")

    def test_snapshot_carries_titles_into_both_schedules_without_mutating_master(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".coord").mkdir()
            master = {"phases": [
                {"phase_id": "U900", "title": "HUD <카드> 이름 개선", "state": "DONE"},
                {"phase_id": "U900-VERIFY", "title": "U900-VERIFY", "state": "READY",
                 "owner_tool": "codex", "judge": "claude", "action": "렌더링 결과 대조"},
            ]}
            path = root / ".coord/master_schedule.json"
            path.write_text(json.dumps(master, ensure_ascii=False), encoding="utf-8")
            before = path.read_bytes()
            engines = {tool: {"presence_state": "ACTIVE", "usable_remaining_5h_tokens": 1000000}
                       for tool in ("codex", "claude", "antigravity")}
            plan = cp.build_capacity_aware_schedule(root, engines)
            detail = cp.build_sub_process_schedule(root, engines, copy.deepcopy(plan))
            title = "HUD <카드> 이름 개선 · 독립 검증"
            self.assertEqual(plan["phase_assignments"][0]["plan_detail"]["title"], title)
            card = detail["card_sub_schedules"][0]
            self.assertEqual(card["card_title"], title)
            self.assertTrue(all(node["card_title"] == title for node in card["sub_processes"]))
            self.assertEqual(path.read_bytes(), before)

    def test_html_escapes_titles_and_shows_action_and_card_context(self):
        with tempfile.TemporaryDirectory() as td:
            page = cp.render_html_dashboard({}, Path(td) / "hud.html").read_text(encoding="utf-8")
            self.assertIn('esc(view.title_primary)', page)
            self.assertIn('esc(view.title_secondary)', page)
            self.assertIn('현재 작업 / Current work', page)
            self.assertIn('Confirm goal and evidence', page)
            self.assertNotIn('대상: ${esc(sp.card_title', page)
            self.assertNotIn('class="flex-1 truncate">${esc(pd.title', page)

    def test_bilingual_presentation_keeps_identity_out_of_purpose(self):
        row = {"phase_id": "U900-VERIFY", "title": "U900-VERIFY", "state": "REVIEW",
               "action_ko": "인수 결과 대조", "action_en": "Check acceptance evidence"}
        parent = {"phase_id": "U900", "title_ko": "카드 목적 표시", "title_en": "Card purpose labels"}
        view = cp.hud_card_presentation(row, {"U900": parent})
        self.assertEqual(view["title_primary"], "카드 목적 표시 · 독립 검증")
        self.assertEqual(view["title_secondary"], "Card purpose labels · Independent verification")
        self.assertNotIn("U900", view["title_primary"])
        self.assertEqual(view["action_primary"], "인수 결과 대조")

    def test_english_only_purpose_is_visible_without_a_fake_translation(self):
        view = cp.hud_card_presentation({"phase_id": "U900", "title": "Card purpose labels"}, {})
        self.assertEqual(view["title_primary"], "Card purpose labels")
        self.assertEqual(view["title_secondary"], "")

    def test_detail_preserves_supplied_purpose_when_master_is_missing(self):
        with tempfile.TemporaryDirectory() as td:
            plan = {"phase_assignments": [{"phase_id": "U900-VERIFY", "state": "READY",
                    "assigned_owner": "codex", "assigned_reviewer": "claude",
                    "plan_detail": {"title": "HUD 제목 검증"}}]}
            detail = cp.build_sub_process_schedule(Path(td), {}, plan)
            self.assertEqual(detail["card_sub_schedules"][0]["card_title"], "HUD 제목 검증")

    def test_script_payload_cannot_be_terminated_by_a_card_title(self):
        title = "</script><script>window.injected=1</script>"
        snapshot = {"schedule_recommendation": {"phase_assignments": [
            {"phase_id": "U900", "plan_detail": {"title": title}}]}}
        with tempfile.TemporaryDirectory() as td:
            page = cp.render_html_dashboard(snapshot, Path(td) / "hud.html").read_text(encoding="utf-8")
        payload = page.split("const SNAP = ", 1)[1].split(";\n", 1)[0]
        self.assertNotIn("</script>", payload)
        self.assertIn("\\u003c/script>", payload)
        self.assertEqual(json.loads(payload)["schedule_recommendation"]["phase_assignments"][0]["plan_detail"]["title"], title)


if __name__ == "__main__":
    unittest.main()
