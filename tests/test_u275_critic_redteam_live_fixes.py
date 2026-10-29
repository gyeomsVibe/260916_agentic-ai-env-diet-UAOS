from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from v7_harness.coord import capacity_planner as CP
from v7_harness.coord import desk_delta
from v7_harness.coord.presence import mark as mark_presence
from v7_harness.coord.usage_ledger import record_usage


class TestU275CriticRedteamLiveFixes(unittest.TestCase):
    def test_1_desk_delta_uncommitted_mtime_filter_prevents_repeating_stale_dirty_files(self) -> None:
        now = 1_800_000_000.0
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".coord" / "mailbox" / "inbox").mkdir(parents=True)
            (root / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
            env = dict(
                os.environ,
                GIT_AUTHOR_DATE=f"@{int(now - 100)} +0000",
                GIT_COMMITTER_DATE=f"@{int(now - 100)} +0000",
                GIT_AUTHOR_NAME="t",
                GIT_AUTHOR_EMAIL="t@t",
                GIT_COMMITTER_NAME="t",
                GIT_COMMITTER_EMAIL="t@t",
            )
            subprocess.run(["git", "-C", str(root), "init", "-q"], check=True, capture_output=True, env=env)
            tracked = root / "dirty.txt"
            tracked.write_text("v1\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "dirty.txt"], check=True, capture_output=True, env=env)
            subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "init"], check=True, capture_output=True, env=env)

            # Modify dirty.txt at now - 10
            tracked.write_text("v2\n", encoding="utf-8")
            os.utime(tracked, (now - 10, now - 10))

            # First look at `now`: dirty.txt is reported once
            first = desk_delta.delta_text(root, "antigravity", "s1", now=now)
            self.assertIn("uncommitted M dirty.txt", first)

            # Second look at `now + 5` without touching dirty.txt: MUST BE EMPTY (no 179-item repeat flood!)
            second = desk_delta.delta_text(root, "antigravity", "s1", now=now + 5)
            self.assertEqual("", second)

            # Touch dirty.txt again at `now + 8`: third look at `now + 10` reports the new edit
            tracked.write_text("v3\n", encoding="utf-8")
            os.utime(tracked, (now + 8, now + 8))
            third = desk_delta.delta_text(root, "antigravity", "s1", now=now + 10)
            self.assertIn("uncommitted M dirty.txt", third)

    def test_2_idle_unknown_tool_with_quota_reset_ready_is_wake_ready_not_online_conductor(self) -> None:
        now = 1_800_000_000.0
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "proj"
            home = Path(td) / "home"
            (root / ".coord" / "usage").mkdir(parents=True)
            (root / ".coord" / "presence").mkdir(parents=True)
            home.mkdir(parents=True)

            # Codex is UNKNOWN (expired heartbeat), Claude & Antigravity are ACTIVE
            mark_presence(root, "claude", "ACTIVE", now=now)
            mark_presence(root, "antigravity", "ACTIVE", now=now)

            db_path = home / ".uaos" / "usage" / "ledger.sqlite3"
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
                past_iso = datetime.fromtimestamp(now - 60, timezone.utc).isoformat().replace("+00:00", "Z")
                obs_iso = datetime.fromtimestamp(now - 600, timezone.utc).isoformat().replace("+00:00", "Z")
                con.execute(
                    "INSERT INTO quota_snapshots VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("q_codex_reset", "codex", obs_iso, 100.0, 300, past_iso, "native_transcript"),
                )
                con.commit()
            finally:
                con.close()

            snap = CP.collect_capacity_snapshot(root, home=home, now=now, persist=False)
            self.assertTrue(snap["engines"]["codex"]["quota_reset_ready"])
            self.assertTrue(snap["engines"]["codex"]["wake_on_reset_ready"])
            # Because Codex is UNKNOWN (not ACTIVE), Claude conducts and Codex is listed in wake_ready_tools
            self.assertEqual(snap["schedule_recommendation"]["recommended_conductor"], "claude")
            self.assertIn("codex", snap["schedule_recommendation"]["wake_ready_tools"])

    def test_3_sub_process_schedule_shows_recent_completed_dag_when_all_master_phases_done(self) -> None:
        now = 1_800_000_000.0
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "proj"
            home = Path(td) / "home"
            (root / ".coord" / "usage").mkdir(parents=True)
            (root / ".coord" / "presence").mkdir(parents=True)
            home.mkdir(parents=True)
            for t in ("codex", "claude", "antigravity"):
                mark_presence(root, t, "ACTIVE", now=now)
            (root / ".coord" / "master_schedule.json").write_text(
                json.dumps({
                    "phases": [
                        {"phase_id": "U273", "state": "DONE", "owner": "antigravity", "reviewer": "claude"},
                        {"phase_id": "U274", "state": "DONE", "owner": "antigravity", "reviewer": "claude"},
                    ]
                }),
                encoding="utf-8",
            )
            snap = CP.collect_capacity_snapshot(root, home=home, now=now, persist=True)
            sub = snap["sub_process_schedule"]
            self.assertTrue(sub["showing_recent_completed_dag"])
            self.assertEqual(sub["total_active_cards"], 2)
            self.assertEqual(sub["total_sub_processes"], 10)
            term = CP.render_terminal_dashboard(snap)
            self.assertIn("[세부스케줄]", term)
            self.assertIn("SP5:antigravity(DONE)", term)

    def test_4_offload_efficiency_24h_groups_brain_steps_by_conversation_work_unit(self) -> None:
        now = 1_800_000_000.0
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "proj"
            home = Path(td) / "home"
            (root / ".coord" / "usage").mkdir(parents=True)
            (root / ".coord" / "presence").mkdir(parents=True)
            home.mkdir(parents=True)
            for t in ("codex", "claude", "antigravity"):
                mark_presence(root, t, "ACTIVE", now=now)

            # 10 PLANNER_RESPONSE steps inside a single brain conversation conv-1
            b_log = home / ".gemini" / "antigravity" / "brain" / "conv-1" / ".system_generated" / "logs" / "transcript.jsonl"
            b_log.parent.mkdir(parents=True, exist_ok=True)
            iso_now = datetime.fromtimestamp(now - 100, timezone.utc).isoformat().replace("+00:00", "Z")
            lines = [
                json.dumps({"step_index": i, "type": "PLANNER_RESPONSE", "created_at": iso_now, "input_tokens": 1000, "output_tokens": 100})
                for i in range(10)
            ]
            b_log.write_text("\n".join(lines) + "\n", encoding="utf-8")

            record_usage(root, {
                "schema": "uaos-usage-v2", "work_id": "U275-olla-1", "actor": "antigravity", "worker": "ollama",
                "model": "qwen2.5-coder:7b", "kind": "olla_mcp", "collection_mode": "measured",
                "input_tokens": 5000, "output_tokens": 200, "wall_time_s": 1.0, "outcome": "PASS",
                "receipt": "ro1", "independent_verifier": "claude", "rsi_eligible": False, "exclusion_reason": "TEST",
                "ts": now - 50,
            })
            record_usage(root, {
                "schema": "uaos-usage-v2", "work_id": "U275-haiku-1", "actor": "claude", "worker": "haiku",
                "model": "claude-haiku-4-5-20251001", "kind": "moderator", "collection_mode": "measured",
                "input_tokens": 3000, "output_tokens": 100, "wall_time_s": 0.5, "outcome": "PASS",
                "receipt": "rh1", "independent_verifier": None, "rsi_eligible": False, "exclusion_reason": "TEST",
                "ts": now - 40,
            })

            snap = CP.collect_capacity_snapshot(root, home=home, now=now, persist=False)
            # Raw window_24h["calls"] for antigravity stays 10 so watermark step tests pass
            self.assertEqual(snap["engines"]["antigravity"]["window_24h"]["calls"], 10)
            # Offload efficiency groups the 10 steps of conv-1 into 1 conversation work unit -> 2 / (1 + 2) = 66.7%
            off = snap["offload_efficiency_24h"]
            self.assertEqual(off["raw_step_calls_24h"], 12)
            self.assertEqual(off["total_calls_24h"], 3)
            self.assertEqual(off["ollama_plus_haiku_calls_24h"], 2)
            self.assertAlmostEqual(off["offload_share_pct"], 66.7, places=1)


if __name__ == "__main__":
    unittest.main()
