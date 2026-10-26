from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.cli import main as cli_main
from v7_harness.coord import capacity_planner as CP
from v7_harness.coord.presence import mark as mark_presence
from v7_harness.coord.usage_ledger import record_usage


class TestU256CapacityPlannerAndDashboard(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "proj"
        self.home = Path(self.tmp.name) / "home"
        (self.root / ".coord").mkdir(parents=True)
        (self.root / ".coord" / "PLAN.md").write_text("# Plan\n", encoding="utf-8")
        self.home.mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_1_collect_snapshot_persists_project_and_global_registry(self) -> None:
        now = 1800000000.0
        mark_presence(self.root, "codex", "LIMITED", now=now)
        mark_presence(self.root, "claude", "ACTIVE", now=now)
        mark_presence(self.root, "antigravity", "ACTIVE", now=now)

        record_usage(self.root, {
            "schema": "uaos-usage-v2", "work_id": "U255-agy-1", "actor": "antigravity", "worker": "antigravity",
            "model": "gemini-2.5-pro", "kind": "pilot", "collection_mode": "measured",
            "input_tokens": 30000, "output_tokens": 5000, "wall_time_s": 4.2, "outcome": "PASS",
            "receipt": "r1", "independent_verifier": "claude", "rsi_eligible": False, "exclusion_reason": "TEST",
            "ts": now - 600,
        })
        record_usage(self.root, {
            "schema": "uaos-usage-v2", "work_id": "U255-olla-1", "actor": "antigravity", "worker": "ollama",
            "model": "qwen2.5-coder:7b", "kind": "pilot", "collection_mode": "measured",
            "input_tokens": 12000, "output_tokens": 3000, "wall_time_s": 1.1, "outcome": "PASS",
            "receipt": "r2", "independent_verifier": "claude", "rsi_eligible": False, "exclusion_reason": "TEST",
            "ts": now - 300,
        })
        record_usage(self.root, {
            "schema": "uaos-usage-v2", "work_id": "U255-haiku-1", "actor": "antigravity", "worker": "haiku",
            "model": "claude-haiku-5-5", "kind": "moderator", "collection_mode": "measured",
            "input_tokens": 4000, "output_tokens": 1000, "wall_time_s": 0.8, "outcome": "PASS",
            "receipt": "r3", "independent_verifier": None, "rsi_eligible": False, "exclusion_reason": "TEST",
            "ts": now - 200,
        })

        snap = CP.collect_capacity_snapshot(self.root, home=self.home, now=now, persist=True)
        self.assertTrue((self.root / ".coord/usage/capacity_snapshot.json").is_file())
        self.assertTrue((self.home / ".uaos/usage/global_capacity_registry.json").is_file())

        eng = snap["engines"]
        self.assertEqual(eng["codex"]["presence_state"], "LIMITED")
        self.assertEqual(eng["codex"]["usable_cards_capacity"], 0)
        self.assertGreater(eng["antigravity"]["used_5h_effective_tokens"], 0)
        self.assertEqual(eng["antigravity"]["usable_remaining_5h_tokens"], "UNKNOWN")
        self.assertIsNone(eng["ollama"]["usable_remaining_5h_tokens"])
        self.assertEqual(eng["ollama"]["status_tier"], "UNLIMITED_LOCAL")
        self.assertAlmostEqual(snap["offload_efficiency_24h"]["offload_share_pct"], 66.7, places=1)

    def test_2_capacity_aware_schedule_routes_around_limited_and_enforces_non_author_judge(self) -> None:
        now = 1800000000.0
        mark_presence(self.root, "codex", "LIMITED", now=now)
        mark_presence(self.root, "claude", "ACTIVE", now=now)
        mark_presence(self.root, "antigravity", "ACTIVE", now=now)

        (self.root / ".coord/usage").mkdir(parents=True, exist_ok=True)
        (self.root / ".coord/usage/capacity_policy.json").write_text(json.dumps({
            "tool_caps_5h": {"codex": 1500000, "claude": 1200000, "antigravity": 2000000, "haiku": 3000000, "ollama": None},
            "tool_caps_source": {"origin": "test_measured_fixture", "policy_docs": ["docs/27_token-budget-routing-policy.md"]},
        }), encoding="utf-8")
        sched = {
            "phases": [
                {"phase_id": "U253", "state": "REVIEW", "author_tool": "antigravity", "owner_tool": "antigravity"},
                {"phase_id": "U256", "state": "READY", "owner_tool": "codex", "estimated_tokens": 60000},
            ]
        }
        (self.root / ".coord/master_schedule.json").write_text(json.dumps(sched), encoding="utf-8")

        snap = CP.collect_capacity_snapshot(self.root, home=self.home, now=now, persist=True)
        rec = snap["schedule_recommendation"]
        self.assertEqual(rec["recommended_conductor"], "claude")
        by_id = {a["phase_id"]: a for a in rec["phase_assignments"]}
        # U253 authored by antigravity while codex is LIMITED must route review to claude (author != judge)
        self.assertEqual(by_id["U253"]["assigned_reviewer"], "claude")
        # U256 ready phase routes to highest remaining ACTIVE tool (antigravity has 2.0M > claude 1.2M)
        self.assertEqual(by_id["U256"]["assigned_owner"], "antigravity")
        self.assertEqual(by_id["U256"]["assigned_reviewer"], "claude")

    def test_3_terminal_and_html_dashboard_rendering_and_cli(self) -> None:
        now = 1800000000.0
        mark_presence(self.root, "codex", "ACTIVE", now=now)
        mark_presence(self.root, "claude", "ACTIVE", now=now)
        mark_presence(self.root, "antigravity", "ACTIVE", now=now)

        html_out = self.root / ".work/dashboard/test_dash.html"
        rc = cli_main(["coord", "capacity", "--project", str(self.root), "--html", str(html_out)])
        self.assertEqual(rc, 0)
        self.assertTrue(html_out.is_file())
        html_text = html_out.read_text(encoding="utf-8")
        self.assertIn("tailwindcss.min.js", html_text)
        self.assertIn("UAOS-RSI 3대 도구 실시간 토큰", html_text)


C = CP

def engines(**rem):
    return {t: {"presence_state": "ACTIVE" if rem.get(t, 0) > 0 else "LIMITED", "usable_remaining_5h_tokens": rem.get(t, 0)}
            for t in C.PAID_TOOLS}


class U256Counter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".coord").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self, phases, eng):
        (self.root / ".coord" / "master_schedule.json").write_text(json.dumps({"phases": phases}), encoding="utf-8")
        out = C.build_capacity_aware_schedule(self.root, eng)
        return {r.get("phase_id"): r for r in out["phase_assignments"]}

    def test_review_never_assigned_to_its_author(self):
        # Only the author has capacity: the fallback must not make the author judge its own work.
        rows = self.plan([{"phase_id": "R1", "state": "REVIEW", "author_tool": "claude"}], engines(claude=500000))
        self.assertNotEqual("claude", rows["R1"]["assigned_reviewer"])

    def test_review_owner_is_the_author_not_the_judge(self):
        # A REVIEW phase's owner stays the author; giving the judge ownership lets the judge edit what it judges.
        rows = self.plan([{"phase_id": "R3", "state": "REVIEW", "owner": "antigravity", "reviewer": "claude"}],
                         engines(claude=900000, antigravity=100000))
        self.assertNotEqual(rows["R3"]["assigned_owner"], rows["R3"]["assigned_reviewer"])

    def test_recorded_reviewer_is_kept(self):
        # U254: a verdict owed by the recorded reviewer is that reviewer's next step; capacity must not silently swap judges.
        rows = self.plan([{"phase_id": "R2", "state": "REVIEW", "owner": "antigravity", "reviewer": "claude"}],
                         engines(claude=100000, antigravity=900000, codex=0))
        self.assertEqual("claude", rows["R2"]["assigned_reviewer"])

    def test_tool_caps_have_a_recorded_source(self):
        # Global rule: an unexplained number is a defect; caps that drive routing need a measured source in the policy.
        caps = C.DEFAULT_POLICY["tool_caps_5h"]
        src = C.DEFAULT_POLICY.get("tool_caps_source") or C.DEFAULT_POLICY.get("sources")
        self.assertTrue(src, f"tool_caps_5h {caps} carry no recorded source")

    def test_cited_policy_docs_are_committed_and_state_the_caps(self):
        # A source is evidence only if it ships in the tree (git ls-files) and states the number it is cited for.
        import subprocess
        src = C.DEFAULT_POLICY.get("tool_caps_source") or {}
        docs = src.get("policy_docs") or []
        tracked = set(subprocess.run(["git", "ls-files"], capture_output=True, text=True, encoding="utf-8").stdout.splitlines())
        for d in docs:
            self.assertTrue(d in tracked, f"cited {d} is not a committed file")
        text = "".join(Path(d).read_text(encoding="utf-8") for d in docs if d in tracked).replace(",", "").replace("_", "")
        for tool, cap in C.DEFAULT_POLICY["tool_caps_5h"].items():
            if cap is not None:
                self.assertIn(str(cap), text, f"{tool} cap {cap} is stated in no cited doc")

    def test_paid_tool_remaining_is_unknown_by_default(self):
        # Never convert a quota guess to tokens: with no measured ledger, remaining capacity must be UNKNOWN, not a cap.
        snap = C.collect_capacity_snapshot(self.root)
        for tool in C.PAID_TOOLS:
            rem = (snap.get("engines", snap).get(tool) or {}).get("usable_remaining_5h_tokens")
            self.assertIn(rem, (None, "UNKNOWN"), f"{tool} remaining {rem} with no ledger")


if __name__ == "__main__":
    unittest.main()
