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

    def test_4_argon_brain_transcript_ingestion_and_ultra_heavy_lifter_routing(self) -> None:
        now = 1800000000.0
        mark_presence(self.root, "codex", "LIMITED", now=now)
        mark_presence(self.root, "claude", "ACTIVE", now=now)
        mark_presence(self.root, "antigravity", "ACTIVE", now=now)

        brain_log = self.home / ".gemini/antigravity/brain/1e097d46-test/.system_generated/logs/transcript.jsonl"
        brain_log.parent.mkdir(parents=True, exist_ok=True)
        brain_log.write_text(json.dumps({
            "step_index": 1,
            "type": "PLANNER_RESPONSE",
            "created_at": "2027-01-15T07:55:00Z",
            "input_tokens": 500000,
            "cache_read_tokens": 4000000,
            "output_tokens": 50000,
            "content": "SECRET_PROMPT_TEXT_NEVER_STORED_sk-12345",
        }) + "\n", encoding="utf-8")

        (self.root / ".coord/usage").mkdir(parents=True, exist_ok=True)
        (self.root / ".coord/usage/capacity_policy.json").write_text(json.dumps({
            "tool_caps_5h": {"codex": 7000000, "claude": 8000000, "antigravity": 30000000, "haiku": 3000000, "ollama": None},
            "tool_caps_source": {"origin": "test_argon_ultra_envelope", "policy_docs": ["docs/27_token-budget-routing-policy.md"]},
        }), encoding="utf-8")
        (self.root / ".coord/master_schedule.json").write_text(json.dumps({
            "phases": [
                {"phase_id": "U258", "state": "READY", "owner_tool": "codex", "estimated_tokens": 80000},
            ]
        }), encoding="utf-8")

        snap = CP.collect_capacity_snapshot(self.root, home=self.home, now=now, persist=True)
        agy = snap["engines"]["antigravity"]
        # 500,000 + 0.1*4,000,000 + 3.0*50,000 = 1,050,000 effective tokens
        self.assertEqual(agy["used_5h_effective_tokens"], 1050000)
        self.assertEqual(agy["usable_remaining_5h_tokens"], 28950000)
        rec = snap["schedule_recommendation"]
        self.assertEqual(rec["argon_tier_mode"], "GOOGLE_AI_ULTRA_5X_GEMINI_4_ARGON")
        self.assertEqual(rec["argon_used_5h_share_pct"], 100.0)
        self.assertEqual(rec["phase_assignments"][0]["assigned_owner"], "antigravity")
        self.assertEqual(rec["phase_assignments"][0]["assigned_reviewer"], "claude")
        snap_raw = (self.root / ".coord/usage/capacity_snapshot.json").read_text(encoding="utf-8")
        self.assertNotIn("SECRET_PROMPT_TEXT_NEVER_STORED", snap_raw)

    def test_5_deduplicates_antigravity_events_across_sources_and_unknown_share_not_zero(self) -> None:
        now = 1800000000.0
        # 1. With no usage and unmeasured caps, shares must be UNKNOWN (never 0.0)
        empty_snap = CP.collect_capacity_snapshot(self.root, home=self.home, now=now, persist=False)
        empty_rec = empty_snap["schedule_recommendation"]
        self.assertEqual(empty_rec["argon_used_5h_share_pct"], "UNKNOWN")
        self.assertEqual(empty_rec["argon_remaining_5h_share_pct"], "UNKNOWN")

        # 2. Same Antigravity run present in runs.jsonl, agy_auto.jsonl, and brain transcript is counted ONCE
        conv_id = "896a2a2a-0c25-4068-88c7-e666a8a65be0"
        record_usage(self.root, {
            "schema": "uaos-usage-v2",
            "work_id": "U259-agy-dup",
            "actor": "antigravity",
            "worker": "antigravity",
            "model": "gemini-2.5-pro",
            "kind": "pilot",
            "collection_mode": "measured",
            "conversation_id": conv_id,
            "input_tokens": 10000,
            "output_tokens": 2000,
            "wall_time_s": 1.5,
            "outcome": "PASS",
            "receipt": conv_id,
            "independent_verifier": "claude",
            "rsi_eligible": False,
            "exclusion_reason": "TEST",
            "ts": now - 600,
        })
        auto_dir = self.root / ".coord" / "mailbox" / "delivery"
        auto_dir.mkdir(parents=True, exist_ok=True)
        (auto_dir / "agy_auto.jsonl").write_text(
            json.dumps({
                "ts": now - 600,
                "card": "U259",
                "conversation_id": conv_id,
                "tokens": 12000,
                "state": "ANSWERED",
            }) + "\n",
            encoding="utf-8",
        )
        b_dir = self.home / ".gemini" / "antigravity" / "brain" / conv_id / ".system_generated" / "logs"
        b_dir.mkdir(parents=True, exist_ok=True)
        (b_dir / "transcript.jsonl").write_text(
            json.dumps({
                "type": "PLANNER_RESPONSE",
                "step_index": 1,
                "created_at": "2027-01-15T07:50:05Z",
                "input_tokens": 10000,
                "output_tokens": 2000,
            }) + "\n",
            encoding="utf-8",
        )
        dup_snap = CP.collect_capacity_snapshot(self.root, home=self.home, now=now, persist=False)
        agy_5h = dup_snap["engines"]["antigravity"]["window_5h"]
        self.assertEqual(agy_5h["calls"], 1)
        self.assertEqual(agy_5h["uncached_input_tokens"], 10000)
        self.assertEqual(agy_5h["output_tokens"], 2000)

    def test_6_incremental_brain_watermark_compact_head_and_debounced_zero_token_refresh(self) -> None:
        now = 1800000000.0
        mark_presence(self.root, "codex", "LIMITED", now=now)
        mark_presence(self.root, "claude", "ACTIVE", now=now)
        mark_presence(self.root, "antigravity", "ACTIVE", now=now)

        # Verify official Google AI Ultra 5x · Gemini 4 Argon naming
        self.assertEqual(
            CP.DEFAULT_POLICY["tool_roles"]["antigravity"],
            "Google AI Ultra (Pro 대비 5x 사용량) · Gemini 4 Argon",
        )
        self.assertNotIn("12만원", CP.DEFAULT_POLICY["tool_roles"]["antigravity"])
        self.assertNotIn("120k", CP.DEFAULT_POLICY["tool_roles"]["antigravity"])

        (self.root / ".coord/usage").mkdir(parents=True, exist_ok=True)
        (self.root / ".coord/usage/capacity_policy.json").write_text(json.dumps({
            "tool_caps_5h": {"codex": 7000000, "claude": 8000000, "antigravity": 30000000, "haiku": 3000000, "ollama": None},
            "tool_caps_source": {"origin": "test_argon_ultra_envelope", "policy_docs": ["docs/27_token-budget-routing-policy.md"]},
        }), encoding="utf-8")

        brain_log = self.home / ".gemini/antigravity/brain/conv-wm-1/.system_generated/logs/transcript.jsonl"
        brain_log.parent.mkdir(parents=True, exist_ok=True)
        line1 = json.dumps({
            "step_index": 1,
            "type": "PLANNER_RESPONSE",
            "created_at": "2027-01-15T07:50:00Z",
            "input_tokens": 10000,
            "output_tokens": 1000,
        }) + "\n"
        brain_log.write_text(line1, encoding="utf-8")
        import os
        os.utime(brain_log, (now - 10.0, now - 10.0))
        os.utime(self.root / ".coord/usage/capacity_policy.json", (now - 10.0, now - 10.0))

        res1 = CP.refresh_capacity_zero_token(self.root, home=self.home, now=now, min_interval_s=60.0)
        self.assertTrue(res1["ok"])
        self.assertFalse(res1["debounced"])
        self.assertEqual(res1["paid_tokens_used"], 0)

        head_file = self.root / ".coord/usage/capacity_head.json"
        self.assertTrue(head_file.is_file())
        self.assertLessEqual(len(head_file.read_bytes()), 320)

        # Second call within 60s with no schedule/ledger/transcript change is debounced (0 disk scan)
        res2 = CP.refresh_capacity_zero_token(self.root, home=self.home, now=now + 10.0, min_interval_s=60.0)
        self.assertTrue(res2["debounced"])
        self.assertEqual(res2["paid_tokens_used"], 0)

        # Partial trailing line without newline is NOT consumed until completed, preventing permanent under-counting
        line2_full = json.dumps({
            "step_index": 2,
            "type": "PLANNER_RESPONSE",
            "created_at": "2027-01-15T07:51:00Z",
            "input_tokens": 20000,
            "output_tokens": 2000,
        }) + "\n"
        half = len(line2_full) // 2
        with brain_log.open("a", encoding="utf-8") as fh:
            fh.write(line2_full[:half])
        os.utime(brain_log, (now + 15.0, now + 15.0))
        snap_partial = CP.collect_capacity_snapshot(self.root, home=self.home, now=now + 20.0, persist=True)
        self.assertEqual(snap_partial["engines"]["antigravity"]["window_5h"]["calls"], 1)

        # Complete the partial line with trailing newline -> incremental seek now parses line2_full completely
        with brain_log.open("a", encoding="utf-8") as fh:
            fh.write(line2_full[half:])
        os.utime(brain_log, (now + 25.0, now + 25.0))
        # Also verify refresh_capacity_zero_token detects brain transcript mtime > last_ts even within 60s window
        res3 = CP.refresh_capacity_zero_token(self.root, home=self.home, now=now + 30.0, min_interval_s=60.0)
        self.assertFalse(res3["debounced"])

        snap3 = CP.collect_capacity_snapshot(self.root, home=self.home, now=now + 70.0, persist=True)
        agy_5h = snap3["engines"]["antigravity"]["window_5h"]
        self.assertEqual(agy_5h["calls"], 2)
        self.assertEqual(agy_5h["uncached_input_tokens"], 30000)
        self.assertEqual(agy_5h["output_tokens"], 3000)

        # File rewrite / rotation with different prefix_sha triggers full re-parse instead of stale tail append
        rewritten = json.dumps({
            "step_index": 99,
            "type": "PLANNER_RESPONSE",
            "created_at": "2027-01-15T07:52:00Z",
            "input_tokens": 5000,
            "output_tokens": 500,
            "pad": "X" * 400,
        }) + "\n"
        brain_log.write_text(rewritten, encoding="utf-8")
        os.utime(brain_log, (now + 80.0, now + 80.0))
        snap4 = CP.collect_capacity_snapshot(self.root, home=self.home, now=now + 85.0, persist=True)
        self.assertEqual(snap4["engines"]["antigravity"]["window_5h"]["calls"], 1)
        self.assertEqual(snap4["engines"]["antigravity"]["window_5h"]["uncached_input_tokens"], 5000)

        compact_line = CP.render_compact_status_line(snap3)
        self.assertLessEqual(len(compact_line), 200)
        self.assertIn("GOOGLE_AI_ULTRA_5X_GEMINI_4_ARGON", compact_line)

        # CLI --format head and --format compact
        rc_head = cli_main(["coord", "capacity", "--project", str(self.root), "--format", "head", "--debounce", "60"])
        self.assertEqual(rc_head, 0)
        rc_comp = cli_main(["coord", "capacity", "--project", str(self.root), "--format", "compact"])
        self.assertEqual(rc_comp, 0)


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

    def test_u265_codex_counterexamples_partial_eof_replacement_wait_and_concurrent_watermark(self):
        import os
        import threading

        home = self.root / "home"
        tf = home / ".gemini/antigravity/brain/conv-cx/.system_generated/logs/transcript.jsonl"
        tf.parent.mkdir(parents=True, exist_ok=True)
        wm = home / ".uaos/usage/brain_transcript_watermark.json"

        # 1) Partial EOF completed later: warm vs cold must match (101 + 201)
        ev1 = json.dumps({"step_index": 1, "type": "PLANNER_RESPONSE", "created_at": "2027-01-15T07:50:00Z", "input_tokens": 100, "output_tokens": 1}) + "\n"
        ev2 = json.dumps({"step_index": 2, "type": "PLANNER_RESPONSE", "created_at": "2027-01-15T07:51:00Z", "input_tokens": 200, "output_tokens": 1}) + "\n"
        tf.write_text(ev1 + ev2[: len(ev2) // 2], encoding="utf-8")
        os.utime(tf, (1000.0, 1000.0))
        first = C._scan_agy_brain_transcripts(home, cutoff_ts=0.0, watermark_path=wm)
        self.assertEqual([e["raw_total"] for e in first], [101])
        tf.write_text(ev1 + ev2, encoding="utf-8")
        os.utime(tf, (1005.0, 1005.0))
        warm = C._scan_agy_brain_transcripts(home, cutoff_ts=0.0, watermark_path=wm)
        cold = C._scan_agy_brain_transcripts(home, cutoff_ts=0.0, watermark_path=home / "cold_wm.json")
        self.assertEqual([e["raw_total"] for e in warm], [101, 201])
        self.assertEqual([e["raw_total"] for e in warm], [e["raw_total"] for e in cold])

        # 2) Larger same-path replacement: warm vs cold must match (1000 + 889), not keep stale step 1
        ev9 = json.dumps({"step_index": 9, "type": "PLANNER_RESPONSE", "created_at": "2027-01-15T07:52:00Z", "input_tokens": 999, "output_tokens": 1, "pad": "A" * 300}) + "\n"
        ev8 = json.dumps({"step_index": 8, "type": "PLANNER_RESPONSE", "created_at": "2027-01-15T07:53:00Z", "input_tokens": 888, "output_tokens": 1, "pad": "B" * 300}) + "\n"
        tf.write_text(ev9 + ev8, encoding="utf-8")
        os.utime(tf, (1010.0, 1010.0))
        warm_rep = C._scan_agy_brain_transcripts(home, cutoff_ts=0.0, watermark_path=wm)
        cold_rep = C._scan_agy_brain_transcripts(home, cutoff_ts=0.0, watermark_path=home / "cold_rep.json")
        self.assertEqual([e["raw_total"] for e in warm_rep], [1000, 889])
        self.assertEqual([e["raw_total"] for e in warm_rep], [e["raw_total"] for e in cold_rep])

        # 3) Wait transparency fail-closed on empty/malformed/missing-id schedule
        sched_file = self.root / ".coord/master_schedule.json"
        for bad_phases in (
            [],
            [{"phase_id": "U259", "state": "DONE"}, "ACTIVE"],
            [{"state": "DONE"}],
            [{"phase_id": "", "state": "DONE"}],
            [{"phase_id": "U259", "state": "BOGUS"}],
        ):
            sched_file.write_text(json.dumps({"phases": bad_phases}), encoding="utf-8")
            wt_res = C.extract_wait_transparency(self.root)
            self.assertEqual("UNKNOWN", wt_res["status"], bad_phases)

        # 4) Concurrent scans serialized by lock so watermark does not regress
        tf.write_text(ev1 + ev2, encoding="utf-8")
        os.utime(tf, (1020.0, 1020.0))
        wm_conc = home / "conc_wm.json"
        results = []
        threads = [
            threading.Thread(target=lambda: results.append(len(C._scan_agy_brain_transcripts(home, cutoff_ts=0.0, watermark_path=wm_conc))))
            for _ in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results, [2, 2, 2, 2])
        persisted = json.loads(wm_conc.read_text(encoding="utf-8"))
        self.assertEqual(len(persisted["files"][str(tf)]["events"]), 2)
        self.assertEqual(len(persisted["files"][str(tf)]["prefix_sha"]), 16)

        # 5) Worst-case compact status line is naturally <= 200 chars and ends with '상태=' without truncation
        worst_line = C.render_compact_status_line({
            "compact_head": {
                "conductor": "ANTIGRAVITY_LONG_NAME",
                "mode": "GOOGLE_AI_ULTRA_5X_GEMINI_4_ARGON_EXTRA",
                "rem_5h": {"antigravity": 999999999999, "claude": 999999999999, "codex": 999999999999},
                "cards_5h": {"antigravity": 999999, "claude": 999999, "codex": 999999},
                "offload_pct": 100.0,
                "wait_status": "WAITING_LONG_STATUS",
            }
        })
        self.assertLessEqual(len(worst_line), 200)
        self.assertIn("| 상태=WAITING_LONG", worst_line)
        self.assertTrue(worst_line.endswith("WAITING_LONG"))


if __name__ == "__main__":
    unittest.main()
