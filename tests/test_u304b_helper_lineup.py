"""U304-B fixed acceptance: one common 3-tool rule (main + Ollama + exactly one helper, 1:1) and the HUD helper data."""

from __future__ import annotations

import inspect
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from v7_harness.coord import helper_telemetry as HT
from v7_harness.coord import quota_sources as Q
from v7_harness.coord.helper_thinking_router import (
    COMMON_HELPER_RULE,
    OFFICIAL_TOOL_MODEL_LINEUP,
    PROCESS_LANES,
    SUB_PROCESS_STAGES,
    select_optimal_helper_and_thinking,
)

TOOLS = ("codex", "antigravity", "claude")
EXPECTED = {"codex": ("gpt-6.1-sol", "gpt-6-luna"), "antigravity": ("gemini-4-argon", "gemini-3.8-flash"),
            "claude": ("claude-opus-5-5", "claude-haiku-5-5")}


def _all_selections(tool: str):
    for stage in ("",) + SUB_PROCESS_STAGES:
        for lane in (None,) + PROCESS_LANES:
            for keypoint in (False, True):
                for risk in ("SAFE", "PRE_HANDOFF_WARNING", "IMMINENT_EXHAUSTION"):
                    yield select_optimal_helper_and_thinking(
                        tool, lane_id=lane, sub_stage=stage, is_keypoint=keypoint, exhaustion_risk=risk,
                        multi_file=keypoint, changed_lines=40, prefer_claude_thinking_on_agy=True,
                        prefer_open_source_on_agy=True, purpose="oss bulk claude_thinking")


class OneHelperPerTool(unittest.TestCase):
    def test_each_tool_has_main_ollama_and_exactly_one_helper(self) -> None:
        for tool in TOOLS:
            cat = OFFICIAL_TOOL_MODEL_LINEUP[tool]
            main, helper = EXPECTED[tool]
            self.assertEqual(cat["main_model"], main)
            self.assertEqual(cat["calculator_model"], "qwen2.5-coder:7b")
            self.assertEqual(cat["designated_helper_models"], (helper,))
            self.assertEqual(cat["primary_helper_model"], helper)

    def test_rule_is_identical_across_tools(self) -> None:
        shapes = {tool: sorted(OFFICIAL_TOOL_MODEL_LINEUP[tool]) for tool in TOOLS}
        self.assertEqual(shapes["codex"], shapes["antigravity"])
        self.assertEqual(shapes["codex"], shapes["claude"])
        for tool in TOOLS:
            cat = OFFICIAL_TOOL_MODEL_LINEUP[tool]
            self.assertEqual(cat["target_parallel_ratio"], COMMON_HELPER_RULE["target_parallel_ratio"])
            self.assertEqual(cat["helper_preflight_cap_tokens"], 12000)
            self.assertEqual(cat["usage_method"], COMMON_HELPER_RULE["usage_method"])

    def test_sonnet_is_never_a_claude_helper_or_selection(self) -> None:
        cat = OFFICIAL_TOOL_MODEL_LINEUP["claude"]
        self.assertNotIn("claude-sonnet-5-5", cat["designated_helper_models"])
        self.assertNotIn("claude-sonnet-5-5", cat["all_reasoning_models"])
        for sel in _all_selections("claude"):
            self.assertNotIn("sonnet", sel["designated_helper_model"] + sel["designated_reasoning_model"])

    def test_every_selection_uses_the_one_helper_and_the_main_model(self) -> None:
        for tool in TOOLS:
            main, helper = EXPECTED[tool]
            for sel in _all_selections(tool):
                self.assertEqual(sel["designated_helper_model"], helper)
                self.assertIn(sel["designated_reasoning_model"], OFFICIAL_TOOL_MODEL_LINEUP[tool]["all_reasoning_models"])
                if sel["designated_reasoning_model"] != main:
                    self.assertEqual((tool, sel["designated_reasoning_model"]), ("codex", "gpt-6-astra"))

    def test_effort_levels_are_the_same_for_every_tool(self) -> None:
        levels = {tool: [(s["helper_thinking_level"], s["reasoning_thinking_level"]) for s in _all_selections(tool)]
                  for tool in TOOLS}
        self.assertEqual(levels["codex"], levels["antigravity"])
        self.assertEqual(levels["codex"], levels["claude"])

    def test_astra_only_for_a_codex_keypoint_without_pressure(self) -> None:
        kp = select_optimal_helper_and_thinking("codex", lane_id="ARCH_DESIGN", is_keypoint=True)
        self.assertEqual((kp["designated_reasoning_model"], kp["reasoning_thinking_level"]), ("gpt-6-astra", "High"))
        plain = select_optimal_helper_and_thinking("codex", lane_id="ARCH_DESIGN")
        self.assertEqual(plain["designated_reasoning_model"], "gpt-6.1-sol")
        tight = select_optimal_helper_and_thinking("codex", lane_id="ARCH_DESIGN", is_keypoint=True,
                                                   exhaustion_risk="IMMINENT_EXHAUSTION")
        self.assertEqual((tight["designated_reasoning_model"], tight["reasoning_thinking_level"]),
                         ("gpt-6.1-sol", "Medium"))
        self.assertEqual(kp["native_config"]["codex_flags"]["config_key"], "model_reasoning_effort")

    def test_public_signature_is_stable_for_u304c(self) -> None:
        params = list(inspect.signature(select_optimal_helper_and_thinking).parameters)
        self.assertEqual(params, ["tool", "card", "role", "lane_id", "purpose", "sub_stage", "is_keypoint",
                                  "utilization_5h_pct", "exhaustion_risk", "changed_lines", "multi_file",
                                  "prefer_claude_thinking_on_agy", "prefer_open_source_on_agy"])


class TelemetryAgreesWithRouter(unittest.TestCase):
    def test_telemetry_pin_matches_router_helper(self) -> None:
        for tool in TOOLS:
            cat = OFFICIAL_TOOL_MODEL_LINEUP[tool]
            helper = HT.designated_helper(tool)
            self.assertEqual(helper["model"], cat["primary_helper_model"])
            self.assertEqual(helper["lane"], cat["helper_telemetry_lane"])
        self.assertEqual(sorted(HT.TOOL_HELPER_LANE.values()), sorted(set(HT.LANES) - {"ollama"}))

    def test_view_shows_only_the_designated_helper(self) -> None:
        rows = [{"model": "claude-opus-5-5", "calls": 4127}, {"model": "claude-sonnet-5-5", "calls": 317},
                {"model": "claude-haiku-5-5", "calls": 159, "output_tokens": 134154}]
        view = HT.designated_helper_view("claude", rows)
        self.assertEqual(view, [{"model": "claude-haiku-5-5", "lane": "haiku", "designated": True, "calls": 159,
                                 "basis": "measured", "output_tokens": 134154}])
        agy = HT.designated_helper_view("antigravity", [{"model": "Gemini 3.8 Flash (Low)", "calls": 3},
                                                        {"model": "Gemini 3.8 Flash (High)", "calls": 9}])
        self.assertEqual([(v["model"], v["calls"]) for v in agy], [("gemini-3.8-flash", 3)])
        empty = HT.designated_helper_view("codex")
        self.assertEqual((len(empty), empty[0]["calls"], empty[0]["basis"]), (1, None, "designated_only"))
        with self.assertRaises(ValueError):
            HT.designated_helper("ollama")

    def test_s4_flash_lane_pins_38_flash_and_rejects_flash_lite(self) -> None:
        # S4: the agy CLI rejects gemini-3.5-flash-lite, so a ledger row naming it can only be a stale U304-B pin.
        kw = dict(work_id="S4-T", lane="flash", caller="antigravity", project="p", input_hash="a" * 64,
                  input_tokens=1, output_tokens=1, wall_time_s=1.0, outcome="PASS", receipt="r")
        self.assertEqual(HT.build_helper_record(model="gemini-3.8-flash", **kw)["model"], "gemini-3.8-flash")
        for stale in ("gemini-3.5-flash-lite", "gemini-3.8-flash-low"):
            with self.assertRaises(HT.UsageRejected):
                HT.build_helper_record(model=stale, **kw)


class HudDataSource(unittest.TestCase):
    def test_measured_accounts_reports_one_helper_per_tool(self) -> None:
        now = time.time()
        stamp = datetime.fromtimestamp(now - 3600, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            db = home / ".uaos" / "usage" / "ledger.sqlite3"
            db.parent.mkdir(parents=True)
            con = sqlite3.connect(str(db))
            con.execute("CREATE TABLE contributions (source, provider, event_key, session_key, timestamp, model, "
                        "category, uncached_input, cache_read, cache_write, output, reasoning)")
            data = [("claude", "claude-opus-5-5", 5), ("claude", "claude-sonnet-5-5", 3),
                    ("claude", "claude-haiku-5-5", 2), ("codex", "gpt-6.1-sol", 4), ("codex", "gpt-6.1-terra", 3),
                    ("codex", "gpt-6-luna", 1)]
            for prov, model, n in data:
                for i in range(n):
                    con.execute("INSERT INTO contributions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                                ("t", prov, f"{model}-{i}", "s", stamp, model, "c", 1, 0, 0, 10, 0))
            con.commit()
            con.close()
            pools = [{"models": ["Gemini 3.8 Flash (Low)", "Gemini 3.8 Flash (High)"], "remaining_pct": 23.0},
                     {"models": ["Claude Opus 5.5 (High)", "GPT-OSS 120B (Medium)"], "remaining_pct": 72.0}]
            fake_ag = {"pools": pools, "selected_pool": None, "selected_model": "Gemini 4 Argon"}
            with mock.patch.object(Q, "antigravity_quota", return_value=fake_ag):
                out = Q.measured_accounts(home, now)
        self.assertEqual([h["model"] for h in out["claude"]["helpers"]], ["claude-haiku-5-5"])
        self.assertEqual(out["claude"]["helpers"][0]["calls"], 2)
        self.assertEqual([h["model"] for h in out["codex"]["helpers"]], ["gpt-6-luna"])
        self.assertEqual([h["model"] for h in out["antigravity"]["helpers"]], ["gemini-3.8-flash"])
        self.assertIs(out["antigravity"]["helper_pool"], pools[0])
        # A snapshot without the helper's Low display name falls back to the Gemini family pool, never the Claude/GPT pool.
        pools[0]["models"] = ["Gemini 3.8 Flash (High)"]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(Q, "antigravity_quota", return_value=fake_ag):
            self.assertIs(Q.measured_accounts(Path(tmp), now)["antigravity"]["helper_pool"], pools[0])


if __name__ == "__main__":
    unittest.main()
