"""U275/U276: Unit & Integration Tests for Automatic REA Reverse-Engineering Pipeline & Cockpit Tools Transplant."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from v7_harness.benchmark_logic_transplant import (
    collect_live_five_chip_telemetry,
    select_rea_analysis_tier,
)
from v7_harness.coord.capacity_planner import (
    atomic_write_if_hash_matches,
    collect_capacity_snapshot,
    parse_json_with_auto_restore,
    render_contextual_hud_widget,
    render_html_dashboard,
    scan_cockpit_sqlite_telemetry,
)
from v7_harness.rea_bridge import (
    execute_auto_reverse_engineering_pipeline,
    inspect_static_target,
)


class TestU275AutoReaReverseEngineering(unittest.TestCase):
    def test_select_rea_analysis_tier_activates_on_cockpit_and_binary_dir(self) -> None:
        r_lib = select_rea_analysis_tier(".work/library/cockpit-tools")
        self.assertEqual(r_lib["selected_tier"], "TIER_2_ON_DEMAND_REVERSE_ENGINEERING")
        self.assertTrue(r_lib["tier2_on_demand_active"])

        r_prog = select_rea_analysis_tier(r"D:\D_Program Files (x86)\Cockpit Tools")
        self.assertEqual(r_prog["selected_tier"], "TIER_2_ON_DEMAND_REVERSE_ENGINEERING")
        self.assertTrue(r_prog["tier2_on_demand_active"])

        r_sqlite = select_rea_analysis_tier(r"C:\Users\test\.antigravity_cockpit\codex_session_usage.sqlite")
        self.assertEqual(r_sqlite["selected_tier"], "TIER_2_ON_DEMAND_REVERSE_ENGINEERING")

        r_src = select_rea_analysis_tier("v7_harness/cli.py")
        self.assertEqual(r_src["selected_tier"], "TIER_1_DEFAULT_CORE_ONLY")
        self.assertFalse(r_src["tier2_on_demand_active"])

    def test_inspect_static_target_binary_and_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_exe = root / "sample.exe"
            fake_exe.write_bytes(
                b"MZ\x90\x00https://github.com/jlcodes99/cockpit-tools\x00cockpit_tools::floating_card\x00"
            )
            bin_res = inspect_static_target(fake_exe)
            self.assertTrue(bin_res["ok"])
            self.assertEqual(bin_res["mode"], "STATIC_ONLY_BINARY")
            self.assertIn("https://github.com/jlcodes99/cockpit-tools", bin_res["urls"])
            self.assertGreaterEqual(bin_res["symbol_count"], 2)

            db_file = root / "usage.sqlite"
            con = sqlite3.connect(str(db_file))
            con.execute("CREATE TABLE session_usage_events (request_id TEXT PRIMARY KEY, input_tokens INTEGER)")
            con.commit()
            con.close()

            db_res = inspect_static_target(db_file)
            self.assertTrue(db_res["ok"])
            self.assertEqual(db_res["mode"], "STATIC_ONLY_SQLITE")
            self.assertEqual(len(db_res["tables"]), 1)
            self.assertEqual(db_res["tables"][0]["name"], "session_usage_events")

    def test_auto_reverse_engineering_pipeline_and_live_telemetry_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            desk = Path(tmp)
            (desk / ".coord").mkdir(parents=True, exist_ok=True)
            ext_dir = desk / ".work" / "library" / "sample-rust-app"
            ext_dir.mkdir(parents=True, exist_ok=True)
            (ext_dir / "lib.rs").write_text(
                "pub fn ensure_floating_card_window() {}\npub struct FloatingCardAppearance {}\n",
                encoding="utf-8",
            )

            res = execute_auto_reverse_engineering_pipeline(desk, ext_dir)
            self.assertTrue(res["ok"])
            self.assertTrue(res["auto_triggered"])
            self.assertEqual(res["total_extracted_items"], 2)
            self.assertIn("parent_evidence_id", res["bundle_summary"])
            self.assertTrue(res["first_page_preview"]["ok"])
            self.assertEqual(res["epistemic_evidence"]["tier"], "OBSERVED")
            self.assertEqual(res["obligation_ledger"]["total_obligations"], 2)

            bundle = collect_live_five_chip_telemetry(desk, target_path=str(ext_dir))
            rea_tier = bundle["rea_tier_routing"]
            self.assertEqual(rea_tier["selected_tier"], "TIER_2_ON_DEMAND_REVERSE_ENGINEERING")
            self.assertIn("auto_executed_result", rea_tier)
            self.assertTrue(rea_tier["auto_executed_result"]["ok"])
            self.assertEqual(rea_tier["auto_executed_result"]["total_extracted_items"], 2)

    def test_cockpit_tools_cas_atomic_write_and_auto_restore(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "state.json"
            r1 = atomic_write_if_hash_matches(state_file, {"v": 1})
            self.assertTrue(r1["ok"])
            self.assertIsNone(r1["previous_sha256"])

            # Mismatched expected hash is rejected
            r_bad = atomic_write_if_hash_matches(state_file, {"v": 2}, expected_sha256="deadbeef")
            self.assertFalse(r_bad["ok"])
            self.assertEqual(r_bad["error"], "CAS_HASH_MISMATCH")

            # Matching expected hash succeeds and creates .bak
            r2 = atomic_write_if_hash_matches(state_file, {"v": 2}, expected_sha256=r1["new_sha256"])
            self.assertTrue(r2["ok"])
            self.assertTrue(Path(r2["backup_path"]).is_file())

            # Corrupt primary file -> auto-restores from .bak (which has {"v": 1})
            state_file.write_text("{corrupt_json", encoding="utf-8")
            restored = parse_json_with_auto_restore(state_file)
            self.assertEqual(restored, {"v": 1})

    def test_cockpit_sqlite_telemetry_and_dual_tier_hud_widget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            cockpit_dir = home / ".antigravity_cockpit"
            cockpit_dir.mkdir(parents=True, exist_ok=True)
            db_path = cockpit_dir / "codex_session_usage.sqlite"
            con = sqlite3.connect(str(db_path))
            con.execute(
                "CREATE TABLE session_usage_events ("
                "request_id TEXT PRIMARY KEY, input_tokens INTEGER, cached_input_tokens INTEGER, output_tokens INTEGER)"
            )
            con.execute("CREATE TABLE session_log_sync (file_path TEXT PRIMARY KEY)")
            con.execute("INSERT INTO session_usage_events VALUES ('r1', 100000, 90000, 2000)")
            con.execute("INSERT INTO session_log_sync VALUES ('session1.jsonl')")
            con.commit()
            con.close()

            tel = scan_cockpit_sqlite_telemetry(home)
            self.assertTrue(tel["available"])
            self.assertEqual(tel["synced_files"], 1)
            self.assertEqual(tel["total_events"], 1)
            self.assertEqual(tel["cache_hit_pct"], 90.0)

            desk = home / "proj"
            (desk / ".coord").mkdir(parents=True, exist_ok=True)
            snap = collect_capacity_snapshot(desk, home=home, persist=False)
            self.assertIn("cockpit_telemetry", snap)
            self.assertIn("contextual_hud_widget", snap)
            hud = render_contextual_hud_widget(snap)
            self.assertIn("[HUD 위젯]", hud)
            self.assertIn("품질게이트:PASS", hud)
            self.assertIn("캐시90.0%", hud)
            self.assertLessEqual(len(hud), 200)

            html_path = desk / "dashboard.html"
            render_html_dashboard(snap, html_path)
            html_text = html_path.read_text(encoding="utf-8")
            self.assertIn("hud-toggle-btn", html_text)
            self.assertIn("contextual-hud-bar", html_text)


    def test_codex_counterexamples_security_concurrency_and_unknown_hud(self) -> None:
        import threading
        from v7_harness.library_store import inspect_library_repo

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # 1. Unsafe .git/HEAD ref traversal is rejected
            evil_repo = root / ".work" / "library" / "evil"
            (evil_repo / ".git").mkdir(parents=True)
            (evil_repo / ".git" / "HEAD").write_text("ref: ../../../outside.txt\n", encoding="utf-8")
            info = inspect_library_repo(evil_repo)
            self.assertFalse(info["ok"])
            self.assertEqual(info["error"], "UNSAFE_GIT_HEAD_REF")

            # 2. SQLite filename with '#' and WAL-mode sha256 sensitivity
            weird_db = root / "literal#fixture.sqlite"
            con = sqlite3.connect(str(weird_db))
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("CREATE TABLE t1 (id INT)")
            con.commit()
            r1 = inspect_static_target(weird_db)
            con.execute("CREATE TABLE t2 (id INT)")
            con.commit()
            r2 = inspect_static_target(weird_db)
            con.close()
            self.assertTrue(r1["ok"])
            self.assertNotEqual(r1["sha256"], r2["sha256"])
            self.assertFalse((root / "literal").exists())

            # 3. CAS missing target & parallel CAS serialization
            missing_res = atomic_write_if_hash_matches(root / "missing.json", {"v": 1}, expected_sha256="f" * 64)
            self.assertFalse(missing_res["ok"])
            self.assertEqual(missing_res["error"], "CAS_TARGET_MISSING")

            # 4. Unverified HUD snapshot renders UNKNOWN(품질증거미확인)
            hud_unknown = render_contextual_hud_widget({
                "compact_head": {"conductor": "NONE", "wait_status": "UNKNOWN", "cards_5h": {}, "offload_pct": 0.0},
                "five_chip_telemetry": {"chips": {"1_todos_schedule": {"blocked": 0, "remaining": 0, "total": 0}}},
            })
            self.assertIn("UNKNOWN(품질증거미확인)", hud_unknown)


if __name__ == "__main__":
    unittest.main()
