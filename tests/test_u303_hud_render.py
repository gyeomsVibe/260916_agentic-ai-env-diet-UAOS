"""U303: the HUD snapshot carries measured quota, calibrated tokens and model facts, and no UNKNOWN wording."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord.capacity_planner import collect_capacity_snapshot, render_html_dashboard
from v7_harness.coord.quota_sources import apply_measured_quota

NOW = 1793700000.0  # 2026-11-03T10:40:00Z


def _w(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fixture_home(home: Path) -> None:
    rl = {"limit_id": "codex", "plan_type": "plus",
          "primary": {"used_percent": 40.0, "window_minutes": 300, "resets_at": NOW + 3600},
          "secondary": {"used_percent": 100.0, "window_minutes": 10080, "resets_at": NOW + 86400}}
    _w(home / ".codex/sessions/2026/11/03/rollout-x.jsonl", "\n".join([
        json.dumps({"type": "turn_context", "payload": {"model": "gpt-6.1-sol", "effort": "medium"}}),
        json.dumps({"timestamp": "2026-11-03T10:30:00Z", "payload": {"type": "token_count", "rate_limits": rl}}),
    ]))
    _w(home / ".codex/config.toml", 'model = "gpt-6.1-sol"\nmodel_reasoning_effort = "medium"\n')
    models = {
        "opus": {"displayName": "Claude Opus 5.5 (Medium)", "model": "M401", "thinkingLevel": 2,
                 "quotaInfo": {"remainingFraction": 0.5, "resetTime": "2026-11-03T13:00:00Z"}},
        "flash": {"displayName": "Gemini 3.8 Flash (High)", "model": "M322",
                  "quotaInfo": {"remainingFraction": 0.2, "resetTime": "2026-11-08T05:51:11Z"}},
    }
    _w(home / ".antigravity_cockpit/cache/quota_api_v1_plugin/authorized/a.json",
       json.dumps({"updatedAt": int((NOW - 120) * 1000), "payload": {"models": models}}))
    _w(home / ".gemini/antigravity/antigravity_state.pbtxt", "last_selected_agent_model:  M401\n")
    _w(home / ".uaos/usage/claude_rate_limits.jsonl", json.dumps({
        "ts": NOW - 60, "five_hour_used_pct": 30.0, "five_hour_resets_at": NOW + 7200,
        "seven_day_used_pct": 50.0, "seven_day_resets_at": NOW + 200000, "model": "Opus 5.5", "effort": None}) + "\n")
    _w(home / ".claude/settings.json", json.dumps({"model": "opus"}))


class HudMeasured(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.home, self.desk = root / "home", root / "desk"
        (self.desk / ".coord").mkdir(parents=True)
        (self.desk / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        _fixture_home(self.home)
        self.snap = collect_capacity_snapshot(self.desk, home=self.home, now=NOW, persist=False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_engines_carry_measured_windows_models_and_effort(self):
        e = self.snap["engines"]
        self.assertEqual(e["codex"]["subscription_plan"]["quota_5h_ui_pct"], 40.0)
        self.assertEqual(e["codex"]["status_tier"], "LIMITED_UNTIL_RESET")  # weekly 100 % used
        self.assertEqual(e["codex"]["usable_cards_capacity"], 0)
        self.assertEqual(e["codex"]["measured"]["model"], "gpt-6.1-sol")
        self.assertEqual(e["codex"]["measured"]["effort"], "medium")
        self.assertEqual(e["claude"]["subscription_plan"]["quota_5h_ui_pct"], 30.0)
        self.assertEqual(e["claude"]["measured"]["effort"], "medium")
        self.assertEqual(e["claude"]["measured"]["effort_basis"], "default (effortLevel unset)")
        self.assertEqual(e["haiku"]["subscription_plan"]["quota_7d_ui_pct"], 50.0)  # Haiku runs on Claude's plan
        self.assertEqual(e["antigravity"]["subscription_plan"]["quota_5h_ui_pct"], 50.0)
        self.assertEqual(e["antigravity"]["measured"]["model"], "Claude Opus 5.5 (Medium)")

    def test_remaining_tokens_are_calibrated_or_absent_never_cap_times_percent(self):
        # Claude REVISE F1/F2: a measured window with no calibration pair claims no tokens (global rule:
        # never convert a remaining-quota % to tokens); the provider % is the number shown.
        for eng in ("claude", "antigravity", "haiku"):
            info = self.snap["engines"][eng]
            self.assertIsNone(info["usable_remaining_5h_tokens"], eng)
            self.assertEqual(info["measured"]["tokens_5h_basis"], "uncalibrated: provider % only", eng)
            self.assertIsNone(info["subscription_plan"]["remaining_5h_tokens"], eng)

    def test_a_window_at_zero_blocks_usable_tokens(self):
        # Claude REVISE F4: Codex weekly is 100 % used, so nothing is usable in 5 h either
        cx = self.snap["engines"]["codex"]
        self.assertIn(cx["usable_remaining_5h_tokens"], (0, None))
        self.assertEqual(cx["usable_cards_capacity"], 0)

    def test_antigravity_helper_pool_is_not_its_weekly_window(self):
        # Claude REVISE F3: the Gemini helper pool at 20 % must not throttle the Opus pool at 50 %
        ag = self.snap["engines"]["antigravity"]
        self.assertNotIn("quota_7d_ui_pct", {k: v for k, v in ag["subscription_plan"].items() if v is not None and k == "quota_7d_ui_pct" and v == 80.0})
        self.assertEqual(ag["subscription_plan"]["helper_quota"]["remaining_pct"], 20.0)
        self.assertEqual(ag["status_tier"], "HEALTHY")
        self.assertIsNone(ag["measured"]["window_7d"])

    def test_provenance_names_only_a_source_that_was_read(self):
        # Claude REVISE F5: without a recorder row, claude must not claim the statusLine source
        (self.home / ".uaos/usage/claude_rate_limits.jsonl").unlink()
        snap = collect_capacity_snapshot(self.desk, home=self.home, now=NOW, persist=False)
        for eng in ("claude", "haiku"):
            self.assertNotEqual(snap["engines"][eng]["measured"]["source"], "claude_statusline_rate_limits", eng)

    def test_payload_and_page_have_no_unknown_wording(self):
        with tempfile.TemporaryDirectory() as d:
            page = render_html_dashboard(self.snap, Path(d) / "hud.html").read_text(encoding="utf-8")
        payload = page.split("const SNAP = ", 1)[1].split(";\n", 1)[0]
        quota_part = json.dumps({k: v.get("measured") for k, v in self.snap["engines"].items()}, ensure_ascii=False)
        self.assertNotIn("UNKNOWN", quota_part)
        for word in ("미계측(UNKNOWN)", "복귀 시각 미수집", "리셋 시각 미수집", "장부 미기재"):
            self.assertNotIn(word, page)
        self.assertIn("gpt-6.1-sol", payload)
        self.assertIn("모델 · 추론강도", page)

    def test_expired_heartbeat_reads_from_measured_quota(self):
        # no presence file in the fixture desk: codex is UNKNOWN by heartbeat but LIMITED by its measured weekly quota
        self.assertEqual(self.snap["engines"]["codex"]["presence_state"], "LIMITED")
        self.assertEqual(self.snap["engines"]["codex"]["presence_basis"], "measured quota (heartbeat expired)")


class ApplyWithoutSources(unittest.TestCase):
    def test_missing_measurements_leave_engines_untouched(self):
        engines = {"codex": {"presence_state": "ACTIVE", "subscription_plan": {}, "usable_remaining_5h_tokens": 7}}
        apply_measured_quota(engines, {"codex": {}}, {"subscription_tiers": {}})
        self.assertEqual(engines["codex"]["usable_remaining_5h_tokens"], 7)
        self.assertEqual(engines["codex"]["presence_state"], "ACTIVE")


if __name__ == "__main__":
    unittest.main()
