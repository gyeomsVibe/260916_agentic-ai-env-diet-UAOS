"""U287 fixed acceptance: one helper telemetry contract read by the RSI ledger and coord capacity, not by HUD layout."""
import ast
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord import capacity_planner as CP
from v7_harness.coord import helper_telemetry as HT
from v7_harness.coord.usage_ledger import UsageRejected, ledger_file
from v7_harness import rsi

H = hashlib.sha256(b"fixed input").hexdigest()
PINS = {"ollama": "qwen2.5-coder:7b", "haiku": "claude-haiku-5-5", "luna": "gpt-6-luna",
        "flash": "gemini-3.5-flash-lite"}
ENGINES = {"ollama": "ollama", "haiku": "haiku", "luna": "codex", "flash": "antigravity"}


class HelperTelemetryAcceptance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "proj"
        self.home = Path(self.tmp.name) / "home"
        (self.root / ".coord").mkdir(parents=True)
        (self.root / ".coord" / "PLAN.md").write_text("# Plan\n", encoding="utf-8")
        self.home.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def kw(self, **over):
        base = dict(work_id="U287-T", lane="luna", model="gpt-6-luna", caller="claude", project="proj",
                    input_hash=H, input_tokens=100, output_tokens=40, wall_time_s=1.5, outcome="PASS",
                    receipt=".work/u287/r.json", ts=1800000000.0)
        base.update(over)
        return base

    def test_every_lane_and_caller_round_trips_through_the_one_ledger(self):
        for lane, model in PINS.items():
            for caller in ("codex", "claude", "antigravity"):
                HT.record_helper(self.root, **self.kw(lane=lane, model=model, caller=caller))
        rows = HT.read_helper_records(self.root)
        self.assertEqual(len(rows), 12)
        for row in rows:
            self.assertEqual(row["schema"], "uaos-usage-v2")
            self.assertEqual(row["telemetry"], HT.TELEMETRY)
            self.assertEqual(row["kind"], "helper")
            self.assertEqual(row["budget_engine"], ENGINES[row["helper_lane"]])
            self.assertEqual(row["token_status"], "MEASURED")
        self.assertEqual(ledger_file(self.root).parent.name, "usage")

    def test_pinned_model_mismatch_unknown_lane_and_caller_are_rejected(self):
        bad = [dict(lane="luna", model="gpt-6"), dict(lane="flash", model="gemini-3.8-flash"),
               dict(lane="haiku", model="claude-sonnet-5-5"), dict(lane="ollama", model=""),
               dict(lane="gpt", model="gpt-6-luna"), dict(caller="user"), dict(caller="")]
        for over in bad:
            with self.subTest(over=over), self.assertRaises(UsageRejected):
                HT.build_helper_record(**self.kw(**over))

    def test_prompt_text_and_bad_hash_never_reach_the_ledger(self):
        for key in ("prompt", "messages", "content", "completion", "response_text"):
            with self.subTest(key=key), self.assertRaises(UsageRejected):
                HT.record_helper(self.root, **self.kw(**{key: "secret plan text"}))
        for value in ("", "abc", H.upper(), H[:-1] + "g", None):
            with self.subTest(value=value), self.assertRaises(UsageRejected):
                HT.build_helper_record(**self.kw(input_hash=value))
        self.assertFalse(ledger_file(self.root).is_file() and ledger_file(self.root).read_text(encoding="utf-8"))

    def test_unknown_tokens_are_kept_unknown(self):
        row = HT.build_helper_record(**self.kw(input_tokens=None, output_tokens=None))
        self.assertEqual(row["token_status"], "UNKNOWN")
        self.assertIsNone(row["input_tokens"])
        for value in (-1, True, 1.5, "10"):
            with self.subTest(value=value), self.assertRaises(UsageRejected):
                HT.build_helper_record(**self.kw(input_tokens=value))

    def test_rsi_eligibility_requires_a_different_independent_verifier(self):
        self.assertFalse(HT.build_helper_record(**self.kw())["rsi_eligible"])
        self.assertFalse(HT.build_helper_record(**self.kw(independent_verifier="claude"))["rsi_eligible"])
        row = HT.build_helper_record(**self.kw(independent_verifier="antigravity"))
        self.assertTrue(row["rsi_eligible"])
        self.assertIsNone(row["exclusion_reason"])

    def test_capacity_uses_the_contract_engine_not_label_guessing(self):
        for lane, model in PINS.items():
            row = HT.build_helper_record(**self.kw(lane=lane, model=model, caller="codex"))
            row["worker"] = "claude"  # a misleading label must not move the budget
            self.assertEqual(CP._classify_engine(row), ENGINES[lane])

    def test_summary_counts_lanes_inside_the_window_only(self):
        now = 1800000000.0
        HT.record_helper(self.root, **self.kw(ts=now - 10))
        HT.record_helper(self.root, **self.kw(ts=now - 20, input_tokens=None, output_tokens=None))
        HT.record_helper(self.root, **self.kw(ts=now - 30, lane="ollama", model="qwen2.5-coder:7b", outcome="FAIL",
                                              error="PROMPT_TOO_LARGE"))
        HT.record_helper(self.root, **self.kw(ts=now - 90000))
        summary = HT.summarize(HT.read_helper_records(self.root), now=now)
        self.assertEqual(summary["schema"], HT.TELEMETRY + "-summary")
        self.assertEqual(summary["total_calls"], 3)
        self.assertEqual(summary["lanes"]["luna"], {"calls": 2, "input_tokens": 100, "output_tokens": 40,
                                                    "unknown_token_calls": 1, "failures": 0})
        self.assertEqual(summary["lanes"]["ollama"]["failures"], 1)
        self.assertEqual(summary["lanes"]["flash"]["calls"], 0)
        self.assertEqual(summary["lanes"]["haiku"]["calls"], 0)

    def test_capacity_snapshot_carries_the_helper_summary(self):
        now = 1800000000.0
        HT.record_helper(self.root, **self.kw(ts=now - 10))
        HT.record_helper(self.root, **self.kw(ts=now - 20, lane="flash", model="gemini-3.5-flash-lite"))
        snap = CP.collect_capacity_snapshot(self.root, home=self.home, now=now, persist=False)
        self.assertEqual(snap["helper_telemetry"]["total_calls"], 2)
        self.assertEqual(snap["helper_telemetry"]["lanes"]["flash"]["calls"], 1)

    def test_rsi_pilot_metrics_exclude_helper_rows(self):
        HT.record_helper(self.root, **self.kw())
        self.assertEqual(rsi.load_rows(self.root), [])
        self.assertEqual(len(HT.read_helper_records(self.root)), 1)

    def test_contract_module_is_independent_of_hud(self):
        source = Path(HT.__file__).read_text(encoding="utf-8")
        imported = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
            elif isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
        for banned in ("capacity_planner", "agy_accounts", "hud"):
            self.assertFalse(any(banned in name for name in imported), (banned, imported))
        json.dumps(HT.summarize([], now=0.0))


if __name__ == "__main__":
    unittest.main()
