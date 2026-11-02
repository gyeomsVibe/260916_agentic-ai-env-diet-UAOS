from __future__ import annotations

import inspect
import json
import os
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord import capacity_planner as CP
from v7_harness.coord.presence import mark as mark_presence
from v7_harness.coord.usage_ledger import record_usage


class TestU267Pr229WatermarkCounterexamples(unittest.TestCase):
    """Comprehensive counterexample suite for PR #229 watermark, U259 Argon brain transcript ingestion, and 6:3:1 WDRR routing."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "proj"
        self.home = Path(self.tmp.name) / "home"
        (self.root / ".coord").mkdir(parents=True)
        (self.root / ".coord" / "PLAN.md").write_text("# Plan\n", encoding="utf-8")
        self.home.mkdir(parents=True)
        self.conv_id = "u267-conv-0001"
        self.tf = (
            self.home
            / ".gemini"
            / "antigravity"
            / "brain"
            / self.conv_id
            / ".system_generated"
            / "logs"
            / "transcript.jsonl"
        )
        self.tf.parent.mkdir(parents=True, exist_ok=True)
        self.wm = self.home / ".uaos" / "usage" / "brain_transcript_watermark.json"
        self.wm.parent.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @staticmethod
    def _row(step: int, inp: int, out: int = 1, ts: str = "2027-01-15T07:50:00Z", pad: str = "") -> str:
        payload = {
            "step_index": step,
            "type": "PLANNER_RESPONSE",
            "created_at": ts,
            "input_tokens": inp,
            "output_tokens": out,
        }
        if pad:
            payload["pad"] = pad
        return json.dumps(payload) + "\n"

    def test_p1_1_incomplete_jsonl_tail_warm_equals_cold(self) -> None:
        """P1-1 (pr229_4d_independent_review.json): Incomplete JSONL tail does not advance offset past last newline."""
        ev1 = self._row(1, 100, 1, "2027-01-15T07:50:00Z")
        ev2 = self._row(2, 200, 1, "2027-01-15T07:51:00Z")
        half = len(ev2) // 2

        self.tf.write_text(ev1 + ev2[:half], encoding="utf-8", newline="\n")
        os.utime(self.tf, (1000.0, 1000.0))

        first = CP._scan_agy_brain_transcripts(self.home, cutoff_ts=0.0, watermark_path=self.wm)
        self.assertEqual([e["raw_total"] for e in first], [101])

        wm_state = json.loads(self.wm.read_text(encoding="utf-8"))
        cached_entry = wm_state["files"][str(self.tf)]
        self.assertEqual(cached_entry["offset"], len(ev1.encode("utf-8")))

        # Append remainder of ev2
        with self.tf.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(ev2[half:])
        os.utime(self.tf, (1005.0, 1005.0))

        warm = CP._scan_agy_brain_transcripts(self.home, cutoff_ts=0.0, watermark_path=self.wm)
        cold = CP._scan_agy_brain_transcripts(self.home, cutoff_ts=0.0, watermark_path=self.home / "cold_p1_1.json")
        self.assertEqual([e["raw_total"] for e in warm], [101, 201])
        self.assertEqual([e["raw_total"] for e in warm], [e["raw_total"] for e in cold])

    def test_p1_2_growing_same_path_replacement_rescans_from_zero(self) -> None:
        """P1-2 (pr229_4d_independent_review.json): Growing same-path replacement invalidates prefix_sha and discards stale events."""
        ev1 = self._row(1, 100, 1, "2027-01-15T07:50:00Z")
        self.tf.write_text(ev1, encoding="utf-8", newline="\n")
        os.utime(self.tf, (1010.0, 1010.0))

        initial = CP._scan_agy_brain_transcripts(self.home, cutoff_ts=0.0, watermark_path=self.wm)
        self.assertEqual([e["raw_total"] for e in initial], [101])

        ev9 = self._row(9, 999, 1, "2027-01-15T07:52:00Z", pad="A" * 300)
        ev8 = self._row(8, 888, 1, "2027-01-15T07:53:00Z", pad="B" * 300)
        self.tf.write_text(ev9 + ev8, encoding="utf-8", newline="\n")
        os.utime(self.tf, (1015.0, 1015.0))

        warm = CP._scan_agy_brain_transcripts(self.home, cutoff_ts=0.0, watermark_path=self.wm)
        cold = CP._scan_agy_brain_transcripts(self.home, cutoff_ts=0.0, watermark_path=self.home / "cold_p1_2.json")
        self.assertEqual([e["raw_total"] for e in warm], [1000, 889])
        self.assertEqual([e["raw_total"] for e in warm], [e["raw_total"] for e in cold])

    def test_f1_corrupt_non_int_and_negative_offset_falls_back_cleanly(self) -> None:
        """F1 (pr229_b440579_review.json): Non-int ('abc', True) or negative offset in watermark falls back to full rescan."""
        ev1 = self._row(1, 100, 1, "2027-01-15T07:50:00Z")
        ev2 = self._row(2, 200, 1, "2027-01-15T07:51:00Z")
        self.tf.write_text(ev1 + ev2, encoding="utf-8", newline="\n")
        os.utime(self.tf, (1020.0, 1020.0))
        f_size = self.tf.stat().st_size

        for bad_offset in ("abc", -10, True, {"bad": 1}):
            self.wm.parent.mkdir(parents=True, exist_ok=True)
            self.wm.write_text(
                json.dumps({
                    "schema": "uaos-brain-watermark-v1",
                    "files": {
                        str(self.tf): {
                            "offset": bad_offset,
                            "file_size": f_size,
                            "mtime": 1020.0,
                            "prefix_sha": "deadbeefdeadbeef",
                            "events": [{"ts": 999999999.0, "raw_total": 99999}],
                        }
                    },
                }),
                encoding="utf-8",
            )
            res = CP._scan_agy_brain_transcripts(self.home, cutoff_ts=0.0, watermark_path=self.wm)
            self.assertEqual([e["raw_total"] for e in res], [101, 201], f"failed on bad_offset={bad_offset!r}")

    def test_f2_corrupt_cached_events_including_bool_ts_falls_back_cleanly(self) -> None:
        """F2 (pr229_b440579_review.json): Malformed cached events including boolean ts ({'ts': True}) force full rescan."""
        ev1 = self._row(1, 100, 1, "2027-01-15T07:50:00Z")
        ev2 = self._row(2, 200, 1, "2027-01-15T07:51:00Z")
        self.tf.write_text(ev1 + ev2, encoding="utf-8", newline="\n")
        os.utime(self.tf, (1030.0, 1030.0))
        f_size = self.tf.stat().st_size

        # Discriminating case 1: cached event with boolean ts (isinstance(True, (int, float)) is True in Python!)
        # When file_size and mtime match, origin/main e030527 blindly trusted {"ts": True, "raw_total": 77777}!
        self.wm.parent.mkdir(parents=True, exist_ok=True)
        self.wm.write_text(
            json.dumps({
                "schema": "uaos-brain-watermark-v1",
                "files": {
                    str(self.tf): {
                        "offset": f_size,
                        "file_size": f_size,
                        "mtime": 1030.0,
                        "prefix_sha": "deadbeefdeadbeef",
                        "events": [{"ts": True, "raw_total": 77777}],
                    }
                },
            }),
            encoding="utf-8",
        )
        res_bool_ts = CP._scan_agy_brain_transcripts(self.home, cutoff_ts=0.0, watermark_path=self.wm)
        self.assertEqual([e["raw_total"] for e in res_bool_ts], [101, 201])

        # Case 2: non-dict events list ['garbage'] with both matching and non-matching mtime
        for mtime_val in (0.0, 1030.0):
            self.wm.write_text(
                json.dumps({
                    "schema": "uaos-brain-watermark-v1",
                    "files": {
                        str(self.tf): {
                            "offset": 10,
                            "file_size": f_size,
                            "mtime": mtime_val,
                            "prefix_sha": "deadbeefdeadbeef",
                            "events": ["garbage", 123, {"ts": "not-a-float"}],
                        }
                    },
                }),
                encoding="utf-8",
            )
            res = CP._scan_agy_brain_transcripts(self.home, cutoff_ts=0.0, watermark_path=self.wm)
            self.assertEqual([e["raw_total"] for e in res], [101, 201])

    def test_f3_mid_file_rewrite_after_256_bytes_rescans_full_file(self) -> None:
        """F3 (pr229_b440579_review.json): Rewrite after byte 256 with same row length invalidates full-prefix hash."""
        r0 = self._row(0, 10, 1, "2027-01-15T07:50:00Z", pad="P" * 300)
        r1_old = self._row(1, 11, 1, "2027-01-15T07:51:00Z")
        r1_new = self._row(1, 98, 1, "2027-01-15T07:51:00Z")
        r2_new = self._row(2, 4, 1, "2027-01-15T07:52:00Z")
        self.assertEqual(len(r1_old.encode("utf-8")), len(r1_new.encode("utf-8")))
        self.assertGreater(len(r0.encode("utf-8")), 256)

        self.tf.write_text(r0 + r1_old, encoding="utf-8", newline="\n")
        os.utime(self.tf, (1040.0, 1040.0))
        first = CP._scan_agy_brain_transcripts(self.home, cutoff_ts=0.0, watermark_path=self.wm)
        self.assertEqual([e["raw_total"] for e in first], [11, 12])

        self.tf.write_text(r0 + r1_new + r2_new, encoding="utf-8", newline="\n")
        os.utime(self.tf, (1045.0, 1045.0))
        second = CP._scan_agy_brain_transcripts(self.home, cutoff_ts=0.0, watermark_path=self.wm)
        self.assertEqual(sorted(e["raw_total"] for e in second), [5, 11, 99])

    def test_f4_future_timestamp_in_capacity_head_forces_refresh(self) -> None:
        """F4 (pr229_b440579_review.json): Future ts in capacity_head.json (last_ts > now) is treated as stale and forces refresh."""
        usage_dir = self.root / ".coord" / "usage"
        usage_dir.mkdir(parents=True, exist_ok=True)
        head_path = usage_dir / "capacity_head.json"
        snap_path = usage_dir / "capacity_snapshot.json"
        head_path.write_text(json.dumps({"ts": 4_000_000_000}), encoding="utf-8")
        snap_path.write_text(json.dumps({"engines": {}, "schedule_recommendation": {}}), encoding="utf-8")

        t0 = 1_800_000_000.0
        res_1h = CP.refresh_capacity_zero_token(self.root, home=self.home, now=t0 + 3600, min_interval_s=60.0)
        self.assertFalse(res_1h["debounced"])
        self.assertEqual(res_1h["head"]["ts"], int(t0 + 3600))

        # Force future ts again and test at t0 + 86400
        head_path.write_text(json.dumps({"ts": 4_000_000_000}), encoding="utf-8")
        res_1d = CP.refresh_capacity_zero_token(self.root, home=self.home, now=t0 + 86400, min_interval_s=60.0)
        self.assertFalse(res_1d["debounced"])
        self.assertEqual(res_1d["head"]["ts"], int(t0 + 86400))

    def test_f5_debounced_refresh_overwrites_existing_stale_html_and_creates_missing_html(self) -> None:
        """F5 (pr229_b440579_review.json): When html_out is requested during a debounced window, even an existing stale HTML file is overwritten."""
        t0 = 1_800_000_000.0
        html_out = self.root / ".work" / "dash_u267.html"
        res1 = CP.refresh_capacity_zero_token(self.root, home=self.home, now=t0, min_interval_s=60.0, html_out=html_out)
        self.assertFalse(res1["debounced"])
        self.assertTrue(html_out.is_file())

        # Discriminating case: overwrite html_out with STALE_HTML (file still exists on disk!)
        # On origin/main e030527, `if html_out is not None and not Path(html_out).is_file():` skipped existing files!
        html_out.write_text("STALE_HTML", encoding="utf-8")
        self.assertEqual(html_out.read_text(encoding="utf-8"), "STALE_HTML")

        res2 = CP.refresh_capacity_zero_token(
            self.root, home=self.home, now=t0 + 10.0, min_interval_s=60.0, html_out=html_out
        )
        self.assertTrue(res2["debounced"])
        fresh_html = html_out.read_text(encoding="utf-8")
        self.assertNotEqual(fresh_html, "STALE_HTML")
        self.assertIn("<!DOCTYPE html>", fresh_html)

    def test_f6_capacity_head_written_atomically_via_atomic_write_json(self) -> None:
        """F6 (pr229_b440579_review.json): capacity_head.json is persisted via _atomic_write_json(compact=True) with fsync and stays <=320 bytes."""
        src = inspect.getsource(CP.collect_capacity_snapshot)
        self.assertIn("_atomic_write_json(local_head, head_summary, compact=True)", src)
        self.assertNotIn("local_head.write_text(", src)

        snap = CP.collect_capacity_snapshot(self.root, home=self.home, now=1_800_000_000.0, persist=True)
        head_path = self.root / ".coord" / "usage" / "capacity_head.json"
        self.assertTrue(head_path.is_file())
        raw_head = head_path.read_bytes()
        self.assertLessEqual(len(raw_head), 320)
        self.assertEqual(json.loads(raw_head.decode("utf-8"))["ts"], int(snap["timestamp"]))

    def test_u259_argon_brain_transcript_ingestion_and_deduplication_invariants(self) -> None:
        """U259: Argon brain transcript ingestion, cross-source deduplication, and secret non-persistence."""
        now = 1_800_000_000.0
        mark_presence(self.root, "codex", "LIMITED", now=now)
        mark_presence(self.root, "claude", "ACTIVE", now=now)
        mark_presence(self.root, "antigravity", "ACTIVE", now=now)

        # Write brain transcript with secret prompt content and cache_read_tokens
        self.tf.write_text(
            json.dumps({
                "step_index": 1,
                "type": "PLANNER_RESPONSE",
                "created_at": "2027-01-15T07:55:00Z",
                "input_tokens": 200000,
                "cache_read_tokens": 1000000,
                "output_tokens": 20000,
                "content": "NEVER_PERSIST_SECRET_TOKEN_XYZ_98765",
            }) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        # Duplicate entry in runs.jsonl for the same conversation_id must be deduplicated
        record_usage(self.root, {
            "schema": "uaos-usage-v2",
            "work_id": "U259-dup-check",
            "actor": "antigravity",
            "worker": "antigravity",
            "model": "gemini-2.5-pro",
            "kind": "pilot",
            "collection_mode": "measured",
            "conversation_id": self.conv_id,
            "input_tokens": 200000,
            "cache_read_input_tokens": 1000000,
            "output_tokens": 20000,
            "wall_time_s": 2.0,
            "outcome": "PASS",
            "receipt": self.conv_id,
            "independent_verifier": "claude",
            "rsi_eligible": False,
            "exclusion_reason": "TEST",
            "ts": now - 300,
        })

        snap = CP.collect_capacity_snapshot(self.root, home=self.home, now=now, persist=True)
        agy_5h = snap["engines"]["antigravity"]["window_5h"]
        self.assertEqual(agy_5h["calls"], 1)
        # 200,000 + 0.1 * 1,000,000 + 3.0 * 20,000 = 360,000 effective tokens
        self.assertEqual(agy_5h["effective_budget_tokens"], 360000)

        snap_text = (self.root / ".coord" / "usage" / "capacity_snapshot.json").read_text(encoding="utf-8")
        wm_text = self.wm.read_text(encoding="utf-8")
        self.assertNotIn("NEVER_PERSIST_SECRET_TOKEN_XYZ_98765", snap_text)
        self.assertNotIn("NEVER_PERSIST_SECRET_TOKEN_XYZ_98765", wm_text)

    def test_u259_wdrr_6_3_1_heavy_lifter_routing_and_limited_failover(self) -> None:
        """U259 P1: 6:3:1 Weighted Deficit Round-Robin (WDRR) distributes 6:3:1 over 10 dispatches and fails over when LIMITED."""
        all_active = {
            "antigravity": {"presence_state": "ACTIVE", "usable_remaining_5h_tokens": 30_000_000},
            "codex": {"presence_state": "ACTIVE", "usable_remaining_5h_tokens": 7_000_000},
            "claude": {"presence_state": "ACTIVE", "usable_remaining_5h_tokens": 8_000_000},
        }
        sim = CP.simulate_wdrr_sequence(all_active, steps=10)
        self.assertEqual(sim["policy"], "WDRR_6_3_1")
        self.assertEqual(sim["weights"], {"antigravity": 6, "codex": 3, "claude": 1})
        self.assertEqual(sim["counts"], {"antigravity": 6, "codex": 3, "claude": 1})
        self.assertEqual(sim["next_recommended_heavy_lifter"], "antigravity")

        # When codex is LIMITED, WDRR skips codex (0 dispatches) and distributes between antigravity (6) and claude (1)
        codex_limited = {
            "antigravity": {"presence_state": "ACTIVE", "usable_remaining_5h_tokens": 30_000_000},
            "codex": {"presence_state": "LIMITED", "usable_remaining_5h_tokens": 0},
            "claude": {"presence_state": "ACTIVE", "usable_remaining_5h_tokens": 8_000_000},
        }
        sim_failover = CP.simulate_wdrr_sequence(codex_limited, steps=7)
        self.assertEqual(sim_failover["counts"]["codex"], 0)
        self.assertEqual(sim_failover["counts"]["antigravity"], 6)
        self.assertEqual(sim_failover["counts"]["claude"], 1)
        self.assertIn("codex", sim_failover["skipped_tools"])

        # Verify build_capacity_aware_schedule surfaces argon_routing and wdrr_heavy_lifter
        sched_plan = CP.build_capacity_aware_schedule(self.root, codex_limited)
        self.assertIn("argon_routing", sched_plan)
        self.assertEqual(sched_plan["argon_routing"]["policy"], "WDRR_6_3_1")
        self.assertEqual(sched_plan["wdrr_heavy_lifter"]["selected_tool"], "antigravity")


if __name__ == "__main__":
    unittest.main()
