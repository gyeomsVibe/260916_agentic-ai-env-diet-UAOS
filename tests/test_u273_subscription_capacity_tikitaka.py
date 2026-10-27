from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from v7_harness.coord import capacity_planner as CP
from v7_harness.coord.presence import mark as mark_presence
from v7_harness.coord.usage_ledger import record_usage


class TestU272SubscriptionCapacityAndParallelTikiTaka(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "proj"
        self.home = Path(self.tmp.name) / "home"
        (self.root / ".coord" / "usage").mkdir(parents=True)
        (self.root / ".coord" / "PLAN.md").write_text("# Plan\n", encoding="utf-8")
        self.home.mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _iso(self, ts: float) -> str:
        return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")

    def test_1_subscription_plan_5h_24h_7d_totals_and_realtime_quantification(self) -> None:
        now = 1800000000.0
        mark_presence(self.root, "codex", "ACTIVE", now=now)
        mark_presence(self.root, "claude", "ACTIVE", now=now)
        mark_presence(self.root, "antigravity", "ACTIVE", now=now)

        (self.root / ".coord/usage/capacity_policy.json").write_text(
            json.dumps({
                "tool_caps_5h": {
                    "codex": 7000000,
                    "claude": 15000000,
                    "antigravity": 75000000,
                    "haiku": 6000000,
                    "ollama": None,
                },
                "tool_caps_7d": {
                    "codex": 175000000,
                    "claude": 180000000,
                    "antigravity": 600000000,
                    "haiku": 60000000,
                    "ollama": None,
                },
                "tool_caps_source": {
                    "origin": "measured_3tool_subscription_envelope_u272",
                    "policy_docs": ["docs/27_token-budget-routing-policy.md"],
                },
            }),
            encoding="utf-8",
        )

        record_usage(self.root, {
            "schema": "uaos-usage-v2",
            "work_id": "U272-codex-1",
            "actor": "codex",
            "worker": "codex",
            "model": "gpt-5.4-codex",
            "kind": "judge",
            "collection_mode": "measured",
            "input_tokens": 500000,
            "output_tokens": 50000,
            "wall_time_s": 3.0,
            "outcome": "PASS",
            "receipt": "rc1",
            "independent_verifier": "claude",
            "rsi_eligible": False,
            "exclusion_reason": "TEST",
            "ts": now - 1000,
        })
        record_usage(self.root, {
            "schema": "uaos-usage-v2",
            "work_id": "U272-agy-7d",
            "actor": "antigravity",
            "worker": "antigravity",
            "model": "gemini-4-argon",
            "kind": "pilot",
            "collection_mode": "measured",
            "input_tokens": 2000000,
            "output_tokens": 100000,
            "wall_time_s": 5.0,
            "outcome": "PASS",
            "receipt": "ra1",
            "independent_verifier": "claude",
            "rsi_eligible": False,
            "exclusion_reason": "TEST",
            "ts": now - 3 * 86400,
        })

        snap = CP.collect_capacity_snapshot(self.root, home=self.home, now=now, persist=True)
        codex_sub = snap["engines"]["codex"]["subscription_plan"]
        self.assertEqual(codex_sub["total_5h_tokens"], 7000000)
        self.assertEqual(codex_sub["total_7d_tokens"], 175000000)
        self.assertEqual(codex_sub["used_5h_effective_tokens"], 650000)
        self.assertEqual(codex_sub["remaining_5h_tokens"], 6350000)

        agy_sub = snap["engines"]["antigravity"]["subscription_plan"]
        self.assertEqual(agy_sub["total_5h_tokens"], 75000000)
        self.assertEqual(agy_sub["total_7d_tokens"], 600000000)
        self.assertEqual(agy_sub["used_5h_effective_tokens"], 0)
        self.assertEqual(agy_sub["used_7d_effective_tokens"], 2300000)
        self.assertEqual(agy_sub["remaining_7d_tokens"], 597700000)

    def test_2_stale_quota_snapshot_filtering_and_separate_5h_7d_windows(self) -> None:
        now = 1800000000.0
        db_path = self.home / ".uaos" / "usage" / "ledger.sqlite3"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(db_path))
        try:
            con.executescript("""
                CREATE TABLE contributions (
                    source TEXT, provider TEXT, event_key TEXT, session_key TEXT,
                    timestamp TEXT, model TEXT, category TEXT,
                    uncached_input INTEGER, cache_read INTEGER, cache_write INTEGER,
                    output INTEGER, reasoning INTEGER,
                    PRIMARY KEY(source, provider, event_key)
                );
                CREATE TABLE quota_snapshots (
                    id TEXT PRIMARY KEY, provider TEXT, observed_at TEXT, used_percent REAL,
                    window_minutes INTEGER, resets_at TEXT, origin TEXT
                );
            """)
            # 1) Stale 4-day-old user_report with resets_at=None for claude & antigravity -> must be filtered out!
            con.execute(
                "INSERT INTO quota_snapshots VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("q_stale_claude", "claude", self._iso(now - 4 * 86400), 100.0, 10080, None, "user_report"),
            )
            con.execute(
                "INSERT INTO quota_snapshots VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("q_stale_agy", "antigravity", self._iso(now - 4 * 86400), 100.0, 10080, None, "user_report"),
            )
            # 2) Codex has BOTH 5h (300m, 99%) and 7d (10080m, 47%) native transcript quotas
            con.execute(
                "INSERT INTO quota_snapshots VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("q_codex_5h", "codex", self._iso(now - 600), 99.0, 300, self._iso(now + 3600), "native_transcript"),
            )
            con.execute(
                "INSERT INTO quota_snapshots VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("q_codex_7d", "codex", self._iso(now - 500), 47.0, 10080, self._iso(now + 5 * 86400), "native_transcript"),
            )
            con.commit()
        finally:
            con.close()

        snap = CP.collect_capacity_snapshot(self.root, home=self.home, now=now, persist=False)
        self.assertIsNone(snap["engines"]["claude"]["provider_quota_snapshot"])
        self.assertIsNone(snap["engines"]["antigravity"]["provider_quota_snapshot"])

        codex_q = snap["engines"]["codex"]["provider_quota_snapshot"]
        self.assertIsNotNone(codex_q)
        self.assertEqual(codex_q["used_percent"], 99.0)
        self.assertEqual(codex_q["window_5h_quota"]["used_percent"], 99.0)
        self.assertEqual(codex_q["window_7d_quota"]["used_percent"], 47.0)
        self.assertEqual(snap["engines"]["codex"]["subscription_plan"]["quota_5h_ui_pct"], 99.0)
        self.assertEqual(snap["engines"]["codex"]["subscription_plan"]["quota_7d_ui_pct"], 47.0)

    def test_3_soft_cap_burst_reserve_and_parallel_tikitaka_no_blocked_reviewer(self) -> None:
        now = 1800000000.0
        mark_presence(self.root, "codex", "LIMITED", now=now)
        mark_presence(self.root, "claude", "ACTIVE", now=now)
        mark_presence(self.root, "antigravity", "ACTIVE", now=now)

        # Simulate both claude and antigravity exceeding a tight 5h cap while still ACTIVE
        (self.root / ".coord/usage/capacity_policy.json").write_text(
            json.dumps({
                "tool_caps_5h": {
                    "codex": 7000000,
                    "claude": 1000000,
                    "antigravity": 1000000,
                    "haiku": 3000000,
                    "ollama": None,
                },
                "tool_caps_source": {
                    "origin": "test_soft_cap_overdrive",
                    "policy_docs": ["docs/27_token-budget-routing-policy.md"],
                },
            }),
            encoding="utf-8",
        )
        record_usage(self.root, {
            "schema": "uaos-usage-v2", "work_id": "U272-c1", "actor": "claude", "worker": "claude",
            "model": "claude-sonnet-4-6", "kind": "pilot", "collection_mode": "measured",
            "input_tokens": 1200000, "output_tokens": 50000, "wall_time_s": 2.0, "outcome": "PASS",
            "receipt": "rc", "independent_verifier": "antigravity", "rsi_eligible": False, "exclusion_reason": "TEST",
            "ts": now - 300,
        })
        record_usage(self.root, {
            "schema": "uaos-usage-v2", "work_id": "U272-a1", "actor": "antigravity", "worker": "antigravity",
            "model": "gemini-4-argon", "kind": "pilot", "collection_mode": "measured",
            "input_tokens": 1200000, "output_tokens": 50000, "wall_time_s": 2.0, "outcome": "PASS",
            "receipt": "ra", "independent_verifier": "claude", "rsi_eligible": False, "exclusion_reason": "TEST",
            "ts": now - 300,
        })

        (self.root / ".coord/master_schedule.json").write_text(
            json.dumps({
                "phases": [
                    {"phase_id": "P1", "state": "READY", "owner_tool": "claude", "estimated_tokens": 45000},
                    {"phase_id": "P2", "state": "READY", "owner_tool": "antigravity", "estimated_tokens": 45000},
                    {"phase_id": "P3", "state": "READY", "owner_tool": "claude", "estimated_tokens": 45000},
                    {"phase_id": "P4", "state": "READY", "owner_tool": "antigravity", "estimated_tokens": 45000},
                ]
            }),
            encoding="utf-8",
        )

        snap = CP.collect_capacity_snapshot(self.root, home=self.home, now=now, persist=False)
        self.assertEqual(snap["engines"]["claude"]["status_tier"], "THRIFT_OVERDRIVE")
        self.assertEqual(snap["engines"]["antigravity"]["status_tier"], "THRIFT_OVERDRIVE")
        self.assertGreater(snap["engines"]["claude"]["active_burst_reserve_tokens"], 0)
        self.assertGreater(snap["engines"]["antigravity"]["active_burst_reserve_tokens"], 0)

        assigns = snap["schedule_recommendation"]["phase_assignments"]
        self.assertEqual(len(assigns), 4)
        owners = {a["assigned_owner"] for a in assigns}
        # Parallel load-balancing distributes work across BOTH active tools (claude and antigravity)
        self.assertEqual(owners, {"claude", "antigravity"})
        for a in assigns:
            self.assertNotEqual(a["assigned_reviewer"], "BLOCKED")
            self.assertNotEqual(a["assigned_owner"], a["assigned_reviewer"])
            self.assertIn("ollama:code_patch_30line_v7_harness", a["local_offload"])

    def test_4_agy_auto_usage_dict_and_dashboard_subscription_quantification(self) -> None:
        now = 1800000000.0
        mark_presence(self.root, "codex", "ACTIVE", now=now)
        mark_presence(self.root, "claude", "ACTIVE", now=now)
        mark_presence(self.root, "antigravity", "ACTIVE", now=now)

        auto_dir = self.root / ".coord" / "mailbox" / "delivery"
        auto_dir.mkdir(parents=True, exist_ok=True)
        (auto_dir / "agy_auto.jsonl").write_text(
            json.dumps({
                "ts": now - 120,
                "message_id": "relay_test_u272",
                "state": "ANSWERED",
                "conversation_id": "conv-u272-auto",
                "usage": {
                    "input_tokens": 18000,
                    "output_tokens": 500,
                    "thinking_tokens": 200,
                    "cache_read_tokens": 2000,
                    "total_tokens": 20500,
                },
            }) + "\n",
            encoding="utf-8",
        )

        snap = CP.collect_capacity_snapshot(self.root, home=self.home, now=now, persist=False)
        agy_5h = snap["engines"]["antigravity"]["window_5h"]
        self.assertEqual(agy_5h["calls"], 1)
        self.assertEqual(agy_5h["uncached_input_tokens"], 18000)
        self.assertEqual(agy_5h["cache_read_tokens"], 2000)
        self.assertEqual(agy_5h["output_tokens"], 500)

        term = CP.render_terminal_dashboard(snap)
        self.assertIn("[구독요금제]", term)
        self.assertIn("Plus $20 (Astra)", term)
        self.assertIn("AI Ultra 5x (Argon)", term)

        html_out = self.root / ".work" / "u272_dash.html"
        CP.render_html_dashboard(snap, html_out)
        html_text = html_out.read_text(encoding="utf-8")
        self.assertIn("5h 총한도 대비:", html_text)
        self.assertIn("7d 주간 총량 대비:", html_text)


if __name__ == "__main__":
    unittest.main()
