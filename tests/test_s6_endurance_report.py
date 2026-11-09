"""S6: weekly three-tool endurance report (deterministic, 0 paid tokens, written by the scheduled rsi watch).

Receipt (2026-11-07 sustain plan): the user asked for monitoring, audit and records of whether Antigravity, Claude
Code and Codex last across their 5h and weekly quotas; no report existed. Every test runs in a temp project and a
temp home, so the live desk and the real quota files are never read or written.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from v7_harness import cli
from v7_harness.coord import endurance_report as er
from v7_harness.coord import quota_sources as qs

NOW = 1794000000.0  # fixed clock: 2026-11-06 UTC


def win(used, reset_in_s, window_min, age_s=60, reset_elapsed=False):
    return {"used_pct": used, "window_min": window_min, "reset_in_s": reset_in_s, "age_s": age_s,
            "resets_at": qs._iso(NOW + reset_in_s), "reset_elapsed": reset_elapsed}


MEASURED = {
    "claude": {"five_hour": win(60.0, 3600, 300), "seven_day": win(30.0, 5 * 86400, 10080, age_s=7200)},
    "codex": {"five_hour": None, "seven_day": win(79.0, 4 * 86400, 10080)},
    "antigravity": {"selected_pool": {**win(10.0, 9000, 300), "models": ["Claude Opus"]}},
}

ROWS = [
    {"kind": "pilot", "worker": "ollama", "actor": "claude", "outcome": "PASS", "ts": NOW - 100},
    {"kind": "olla_mcp", "worker": "ollama", "actor": "claude", "outcome": "FAIL", "ts": NOW - 200},
    {"kind": "helper", "caller": "claude", "actor": "claude", "helper_lane": "haiku", "model": "claude-haiku-5-5",
     "outcome": "PASS", "ts": NOW - 300},
    {"kind": "session", "worker": "claude", "actor": "claude", "outcome": "PASS", "ts": NOW - 400},
    {"kind": "review", "worker": "agy", "actor": "agy", "outcome": "REWORK", "ts": NOW - 500},
    {"kind": "review", "worker": "agy", "actor": "antigravity", "outcome": "PASS", "ts": NOW - 600},
    {"kind": "helper", "caller": "antigravity", "actor": "antigravity", "helper_lane": "flash",
     "model": "gemini-3.5-flash-lite", "outcome": "PASS", "ts": NOW - 700},
    {"kind": "judge", "worker": "codex", "actor": "codex", "outcome": "PASS", "ts": NOW - 800},
    {"kind": "pilot", "worker": "apply", "actor": "coordinator", "outcome": "PASS", "ts": NOW - 900},
    {"kind": "pilot", "worker": "claude", "actor": "claude", "outcome": "PASS", "ts": NOW - 8 * 86400},  # too old
    {"kind": "pilot", "worker": "claude", "actor": "claude", "ts": NOW - 50},  # no outcome recorded
]


class WindowMath(unittest.TestCase):
    def test_delta_is_used_minus_elapsed_with_freshness(self):
        w = er.tool_windows(MEASURED)
        # Claude 5h: 4 h of 5 elapsed (80 %), 60 % used → Δ −20 (headroom at reset); age 60 s → FRESH
        self.assertEqual((w["claude"]["5h"]["elapsed_pct"], w["claude"]["5h"]["delta_pct"]), (80.0, -20.0))
        self.assertEqual(w["claude"]["5h"]["freshness"], "FRESH")
        # Claude weekly: 2 of 7 days elapsed (28.6 %), age 2 h → STALE
        self.assertEqual(w["claude"]["weekly"]["elapsed_pct"], 28.6)
        self.assertEqual(w["claude"]["weekly"]["freshness"], "STALE")
        # Codex weekly: 3 of 7 days elapsed (42.9 %), 79 % used → Δ +36.1 (burns faster than the clock)
        self.assertEqual(w["codex"]["weekly"]["delta_pct"], 36.1)
        self.assertEqual(w["codex"]["5h"]["freshness"], "MISSING")
        # Antigravity's selected pool is a 300-minute pool → its 5h window; weekly missing
        self.assertEqual(w["antigravity"]["5h"]["used_pct"], 10.0)
        self.assertEqual(w["antigravity"]["weekly"]["freshness"], "MISSING")

    def test_a_reset_after_the_reading_is_reset_elapsed_without_a_delta(self):
        v = er._window_view(win(0.0, 0, 300, reset_elapsed=True))
        self.assertEqual((v["freshness"], v["delta_pct"]), ("RESET_ELAPSED", None))


class StepMix(unittest.TestCase):
    def test_classes_tools_and_pass_rates(self):
        mix = er.step_mix(ROWS, NOW)
        c = mix["claude"]
        self.assertEqual((c["ollama"]["steps"], c["ollama"]["pass_rate"]), (2, 0.5))
        self.assertEqual((c["helper"]["steps"], c["helper"]["pass_rate"]), (1, 1.0))
        # the 8-day-old row is out of the window; the outcome-less row counts as a step but not in the pass rate
        self.assertEqual((c["main"]["steps"], c["main"]["with_outcome"], c["main"]["pass_rate"]), (2, 1, 1.0))
        a = mix["antigravity"]  # actor "agy" maps to antigravity
        self.assertEqual((a["main"]["steps"], a["main"]["pass_rate"], a["helper"]["steps"]), (2, 0.5, 1))
        self.assertEqual(mix["codex"]["main"]["steps"], 1)
        self.assertEqual(mix["unattributed"]["main"]["steps"], 1)  # coordinator owns no single tool
        self.assertEqual(c["ollama"]["share"], 0.4)


class IdleHours(unittest.TestCase):
    def test_exhausted_until_reset_merged_and_clipped(self):
        start, end = NOW - 7 * 86400, NOW
        samples = [
            {"ts": NOW - 10 * 3600, "used_pct": 100.0, "resets_at": NOW - 8 * 3600},  # 2 h
            {"ts": NOW - 9 * 3600, "used_pct": 100.0, "resets_at": NOW - 7 * 3600},  # overlaps → +1 h
            {"ts": NOW - 5 * 3600, "used_pct": 50.0, "resets_at": NOW - 1 * 3600},  # not exhausted
            {"ts": NOW - 8 * 86400, "used_pct": 100.0, "resets_at": NOW - 7 * 86400 + 1800},  # clipped → 0.5 h
        ]
        self.assertEqual(er.limit_idle_hours([samples], start, end), 3.5)

    def test_no_reset_time_lasts_until_the_next_reading_below_the_limit(self):
        samples = [{"ts": NOW - 3 * 3600, "used_pct": 99.6, "resets_at": None},
                   {"ts": NOW - 2 * 3600, "used_pct": 99.9, "resets_at": None},
                   {"ts": NOW - 1 * 3600, "used_pct": 5.0, "resets_at": None}]
        self.assertEqual(er.limit_idle_hours([samples], NOW - 86400, NOW), 2.0)

    def test_an_early_refill_ends_the_interval_before_the_printed_reset(self):
        samples = [{"ts": NOW - 4 * 3600, "used_pct": 100.0, "resets_at": NOW + 86400},
                   {"ts": NOW - 3 * 3600, "used_pct": 3.0, "resets_at": NOW + 7 * 86400}]
        self.assertEqual(er.limit_idle_hours([samples], NOW - 86400, NOW), 1.0)

    def test_a_5h_limit_inside_an_exhausted_week_is_counted_once(self):
        weekly = [{"ts": NOW - 10 * 3600, "used_pct": 100.0, "resets_at": NOW - 4 * 3600}]  # 6 h
        five = [{"ts": NOW - 8 * 3600, "used_pct": 100.0, "resets_at": NOW - 6 * 3600},  # inside: +0
                {"ts": NOW - 3 * 3600, "used_pct": 100.0, "resets_at": NOW - 2 * 3600}]  # outside: +1 h
        self.assertEqual(er.limit_idle_hours([five, weekly], NOW - 86400, NOW), 7.0)

    def test_still_exhausted_at_the_last_reading_runs_to_now(self):
        self.assertEqual(er.limit_idle_hours([[{"ts": NOW - 1800, "used_pct": 100, "resets_at": None}]],
                                             NOW - 86400, NOW), 0.5)


class Report(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.project, self.home = base / "proj", base / "home"
        (self.project / ".coord" / "usage").mkdir(parents=True)
        self.home.mkdir()
        self.inputs = {"measured": MEASURED, "rows": ROWS,
                       "series": {"codex": [[{"ts": NOW - 3600, "used_pct": 100.0, "resets_at": NOW}]]}}

    def tearDown(self):
        self._tmp.cleanup()

    def test_report_is_written_once_a_week_and_is_deterministic(self):
        first = er.maybe_write_weekly(self.project, self.home, NOW, **self.inputs)
        self.assertEqual(first["status"], "WRITTEN")
        path = Path(first["path"])
        self.assertEqual(path, self.project / ".coord" / "reports" / f"endurance_{datetime.fromtimestamp(NOW):%Y-%m-%d}.md")
        text = path.read_text(encoding="utf-8")
        for needle in ("| codex | weekly | 79.0 | 42.9 | +36.1 | FRESH |", "| claude | 5h | 60.0 | 80.0 | -20.0 | FRESH |",
                       "| claude | ollama | 2 | 0.4 | 2 | 1 | 0.5 |", "| codex | 1.0 |", "| unattributed | main | 1 |"):
            self.assertIn(needle, text)
        # 6 days later: not due, file untouched; 7 days later: a new dated report
        self.assertEqual(er.maybe_write_weekly(self.project, self.home, NOW + 6 * 86400, **self.inputs)["status"], "NOT_DUE")
        self.assertEqual(er.maybe_write_weekly(self.project, self.home, NOW + 7 * 86400, **self.inputs)["status"], "WRITTEN")
        # same inputs + same now → same bytes (force rewrites the first date)
        er.maybe_write_weekly(self.project, self.home, NOW, force=True, **self.inputs)
        self.assertEqual(path.read_text(encoding="utf-8"), text)
        self.assertEqual(sorted(p.name for p in path.parent.glob("*.tmp")), [])

    def test_real_home_layout_is_read_without_injected_inputs(self):
        rec = self.home / qs.CLAUDE_LIMITS_FILE
        rec.parent.mkdir(parents=True)
        rec.write_text(json.dumps({"ts": NOW - 30, "five_hour_used_pct": 100, "five_hour_resets_at": NOW + 3600,
                                   "seven_day_used_pct": 40, "seven_day_resets_at": NOW + 86400}) + "\n", encoding="utf-8")
        (self.project / ".coord" / "usage" / "runs.jsonl").write_text(json.dumps(ROWS[0]) + "\n", encoding="utf-8")
        rep = er.build_report(self.project, self.home, NOW)
        self.assertEqual(rep["tools"]["claude"]["windows"]["5h"]["used_pct"], 100.0)
        self.assertEqual(rep["tools"]["claude"]["windows"]["5h"]["freshness"], "FRESH")
        self.assertEqual(rep["tools"]["claude"]["idle_limit_hours"], 0.01)  # exhausted 30 s before now
        self.assertEqual(rep["tools"]["claude"]["steps"]["ollama"]["steps"], 1)
        self.assertEqual(rep["tools"]["codex"]["windows"]["weekly"]["freshness"], "MISSING")

    def test_cli_endurance_and_the_scheduled_watch_write_the_report(self):
        with mock.patch.object(Path, "home", return_value=self.home):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = cli.main(["rsi", "watch", "--project", str(self.project)])
            out = json.loads(buf.getvalue())
            self.assertEqual(rc, 0)
            self.assertEqual(out["endurance_report"]["status"], "WRITTEN")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(cli.main(["rsi", "endurance", "--project", str(self.project)]), 0)
            self.assertEqual(json.loads(buf.getvalue())["status"], "NOT_DUE")
        self.assertEqual(len(list((self.project / ".coord" / "reports").glob("endurance_*.md"))), 1)


if __name__ == "__main__":
    unittest.main()
