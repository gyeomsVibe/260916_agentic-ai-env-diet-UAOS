"""U303: measured quota sources, calibration, Claude statusLine recorder (fixtures only, no real home)."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord import quota_sources as q
from v7_harness.coord import claude_statusline as rec

NOW = 1793700000.0  # 2026-11-03T10:40:00Z


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _codex_row(ts_iso: str, used5: float, reset5: float, used7: float, reset7: float, limit_id: str = "codex") -> str:
    return json.dumps({"timestamp": ts_iso, "type": "event_msg", "payload": {"type": "token_count", "rate_limits": {
        "limit_id": limit_id, "primary": {"used_percent": used5, "window_minutes": 300, "resets_at": reset5},
        "secondary": {"used_percent": used7, "window_minutes": 10080, "resets_at": reset7}, "plan_type": "plus"}}})


class CodexQuota(unittest.TestCase):
    def test_newest_codex_row_wins_and_premium_null_rows_are_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            old = _codex_row("2026-11-03T08:00:00Z", 10.0, NOW + 3600, 40.0, NOW + 86400)
            new = _codex_row("2026-11-03T09:00:00Z", 30.0, NOW + 3600, 45.0, NOW + 86400)
            premium = json.dumps({"timestamp": "2026-11-03T10:00:00Z", "payload": {"rate_limits": {
                "limit_id": "premium", "primary": None, "secondary": None}}})
            ctx = json.dumps({"type": "turn_context", "payload": {"model": "gpt-6.1-sol", "effort": "high"}})
            _write(home / ".codex/sessions/2026/11/03/rollout-a.jsonl", "\n".join([ctx, old, new, premium]))
            out = q.codex_quota(home, NOW)
            self.assertEqual(out["five_hour"]["used_pct"], 30.0)
            self.assertEqual(out["five_hour"]["remaining_pct"], 70.0)
            self.assertEqual(out["seven_day"]["remaining_pct"], 55.0)
            self.assertEqual(out["five_hour"]["reset_in_s"], 3600)
            self.assertEqual(out["last_effort"], "high")
            self.assertEqual(out["plan_type"], "plus")

    def test_elapsed_reset_reads_as_unobserved_not_refilled(self):
        # S1: a passed reset with no newer reading is unknown (None), never assumed refilled to 100 %
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            # reading 2 h before NOW (10:00Z): the old 11-01 stamp put the 5h reset 45 h out, now INVALID
            _write(home / ".codex/sessions/x/rollout-b.jsonl", _codex_row("2026-11-03T08:00:00Z", 21.0, NOW - 10, 100.0, NOW + 50))
            out = q.codex_quota(home, NOW)
            self.assertTrue(out["five_hour"]["reset_elapsed"])
            self.assertIsNone(out["five_hour"]["remaining_pct"])
            self.assertEqual(out["five_hour"]["state"], "RESET_UNOBSERVED")
            self.assertEqual(out["five_hour"]["observed_used_pct"], 21.0)
            self.assertEqual(out["seven_day"]["remaining_pct"], 0.0)

    def test_config_reads_top_level_model_and_effort_only(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            _write(home / ".codex/config.toml", 'model = "gpt-6.1-sol"\nmodel_reasoning_effort = "medium"\n[profiles.x]\nmodel = "other"\n')
            self.assertEqual(q.codex_config(home), {"model": "gpt-6.1-sol", "model_reasoning_effort": "medium"})


class AntigravityQuota(unittest.TestCase):
    def _cache(self, home: Path):
        models = {
            "opus-med": {"displayName": "Claude Opus 5.5 (Medium)", "model": "MODEL_PLACEHOLDER_M401", "thinkingLevel": 2,
                         "quotaInfo": {"remainingFraction": 0.6, "resetTime": "2026-11-03T12:00:00Z"}},
            "sonnet": {"displayName": "Claude Sonnet 5.5 (Low)", "model": "M403", "thinkingLevel": 1,
                       "quotaInfo": {"remainingFraction": 0.6, "resetTime": "2026-11-03T12:00:00Z"}},
            "flash": {"displayName": "Gemini 3.8 Flash (High)", "model": "M322",
                      "quotaInfo": {"remainingFraction": 0.25, "resetTime": "2026-11-08T05:51:11Z"}},
            "internal": {"model": "CHAT", "quotaInfo": {"remainingFraction": 1}},
        }
        _write(home / ".antigravity_cockpit/cache/quota_api_v1_plugin/authorized/h.json",
               json.dumps({"updatedAt": int((NOW - 600) * 1000), "payload": {"models": models}}))
        _write(home / ".gemini/antigravity/antigravity_state.pbtxt", "last_selected_agent_model:  MODEL_PLACEHOLDER_M401\n")

    def test_pools_selected_model_and_effort(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            self._cache(home)
            out = q.antigravity_quota(home, NOW)
            self.assertEqual(len(out["pools"]), 2)
            self.assertEqual(out["selected_model"], "Claude Opus 5.5 (Medium)")
            self.assertEqual(out["selected_effort"], "medium")
            sel = out["selected_pool"]
            self.assertEqual(sel["remaining_pct"], 60.0)
            self.assertEqual(sel["window_min"], 300)
            self.assertEqual(sel["age_s"], 600)
            flash = [p for p in out["pools"] if "Gemini 3.8 Flash (High)" in p["models"]][0]
            self.assertEqual(flash["window_min"], 10080)
            self.assertEqual(flash["remaining_pct"], 25.0)


class Calibration(unittest.TestCase):
    def test_window_integral_known_answer(self):
        window = q.window_fact(20.0, NOW + 3 * 3600, 300, NOW, NOW)  # opened 2 h ago
        events = [{"ts": NOW - 3600, "raw_total": 600_000}, {"ts": NOW - 60, "raw_total": 400_000},
                  {"ts": NOW - 3 * 3600, "raw_total": 9_999_999}]  # before the window opened: excluded
        cal = q.calibrate(window, events, NOW)
        self.assertEqual(cal["basis"], "window_integral")
        self.assertEqual(cal["tokens_per_pct"], 50_000)
        self.assertEqual(cal["capacity_tokens"], 5_000_000)
        self.assertEqual(cal["remaining_tokens"], 4_000_000)

    def test_pairs_median_needs_three_pairs(self):
        window = q.window_fact(40.0, NOW + 3600, 300, NOW, NOW)
        hist = [{"ts": NOW - 400 + i * 100, "used_pct": 10.0 * i, "resets_at": NOW + 3600} for i in range(5)]
        events = [{"ts": NOW - 350, "raw_total": 100_000}, {"ts": NOW - 250, "raw_total": 200_000},
                  {"ts": NOW - 150, "raw_total": 300_000}, {"ts": NOW - 50, "raw_total": 400_000}]
        cal = q.calibrate(window, events, NOW, hist)
        self.assertEqual(cal["basis"], "pairs_median")
        self.assertEqual(cal["samples"], 4)
        self.assertEqual(cal["tokens_per_pct"], 25_000)  # median of 10k,20k,30k,40k per 1 %
        self.assertEqual(cal["remaining_tokens"], 25_000 * 60)

    def test_no_tokens_is_reported_as_a_basis_not_a_number(self):
        window = q.window_fact(20.0, NOW + 3600, 300, NOW, NOW)
        cal = q.calibrate(window, [], NOW)
        self.assertEqual(cal["basis"], "no_paired_tokens")
        self.assertIsNone(cal["remaining_tokens"])


class ClaudeRecorder(unittest.TestCase):
    PAYLOAD = {"model": {"id": "claude-opus-5-5", "display_name": "Opus 5.5"},
               "rate_limits": {"five_hour": {"used_percentage": 23.5, "resets_at": NOW + 7200},
                               "seven_day": {"used_percentage": 41.2, "resets_at": NOW + 86400}}}

    def test_record_dedup_and_read_back(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            out = home / ".uaos/usage/claude_rate_limits.jsonl"
            self.assertTrue(rec.record(self.PAYLOAD, out, now=NOW - 30))
            self.assertFalse(rec.record(self.PAYLOAD, out, now=NOW - 20))  # unchanged values: no new row
            self.assertEqual(len(out.read_text(encoding="utf-8").splitlines()), 1)
            got = q.claude_quota(home, NOW)
            self.assertEqual(got["five_hour"]["remaining_pct"], 76.5)
            self.assertEqual(got["seven_day"]["used_pct"], 41.2)
            self.assertEqual(got["last_model"], "Opus 5.5")
            self.assertEqual(got["five_hour"]["age_s"], 30)

    def test_parallel_sessions_lose_no_row(self):
        # Claude REVISE F7: 8 threads x 5 distinct rows really run at once; every row must survive
        import threading
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "rl.jsonl"
            barrier = threading.Barrier(8)

            def worker(i):
                barrier.wait()
                for j in range(5):
                    p = {"rate_limits": {"five_hour": {"used_percentage": i * 10 + j, "resets_at": NOW}}}
                    rec.record(p, out, now=NOW + i * 10 + j)
            ts = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
            [t.start() for t in ts]
            [t.join() for t in ts]
            rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(sorted(r["five_hour_used_pct"] for r in rows), sorted(float(i * 10 + j) for i in range(8) for j in range(5)))

    def test_payload_without_rate_limits_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "x.jsonl"
            self.assertFalse(rec.record({"model": {"display_name": "Opus"}}, out, now=NOW))
            self.assertFalse(out.exists())

    def test_status_text(self):
        self.assertEqual(rec.status_text(self.PAYLOAD), "Opus 5.5 · 5h 24% · 7d 41%")


if __name__ == "__main__":
    unittest.main()
