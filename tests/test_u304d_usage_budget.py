"""U304-D: budget ledger (real parallel appends), pacing, split allocator, flagship gate, fail-closed snapshot."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord import usage_budget as ub
from v7_harness.coord.quota_sources import _iso, window_fact

NOW = 1793700000.0  # 2026-11-03T10:40:00Z
REPO = Path(__file__).resolve().parents[1]
H = 3600.0


def _window(used, reset_in_h, window_min, observed_ago_s=0):
    return window_fact(used, NOW + reset_in_h * H, window_min, NOW - observed_ago_s, NOW)


class ParallelLedger(unittest.TestCase):
    def test_eight_processes_append_without_losing_rows(self):
        procs, per = 8, 40
        code = (
            "import sys; from pathlib import Path; from v7_harness.coord import usage_budget as ub\n"
            "home, n = Path(sys.argv[1]), int(sys.argv[2])\n"
            "for i in range(int(sys.argv[3])):\n"
            "    ub.record_observation('claude', '5h', i % 100, 1793710000 + n, 1793700000 + n * 1000 + i,"
            " 'test', home=home)\n")
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, PYTHONPATH=str(REPO))
            running = [subprocess.Popen([sys.executable, "-c", code, d, str(n), str(per)], cwd=str(REPO), env=env)
                       for n in range(procs)]
            self.assertEqual([p.wait(timeout=120) for p in running], [0] * procs)
            con = sqlite3.connect(str(ub.ledger_path(Path(d))))
            try:
                total, distinct = con.execute(
                    "SELECT COUNT(*), COUNT(DISTINCT observed_at) FROM observations").fetchone()
            finally:
                con.close()
            self.assertEqual((total, distinct), (procs * per, procs * per))

    def test_same_reading_is_recorded_once(self):
        with tempfile.TemporaryDirectory() as d:
            args = ("codex", "7d", 40.0, NOW + 9 * H, NOW, "rollout")
            self.assertTrue(ub.record_observation(*args, home=Path(d)))
            self.assertFalse(ub.record_observation(*args, home=Path(d)))
            self.assertEqual(len(ub.read_observations("codex", "7d", home=Path(d))), 1)

    def test_unknown_tool_is_refused(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(ValueError):
            ub.record_observation("gemini", "5h", 1, NOW, NOW, "x", home=Path(d))


class Pacing(unittest.TestCase):
    def test_window_average_and_headroom(self):
        # weekly: 50 % used after 84 h open, 84 h left -> burn 0.595 %/h, sustainable 0.595 %/h -> headroom 1
        p = ub.pace(_window(50, 84, 10080), [], NOW)
        self.assertEqual(p["burn_basis"], "window_average")
        self.assertAlmostEqual(p["headroom"], 1.0, places=2)
        self.assertEqual(p["state"], "OK")

    def test_slope_needs_three_points_rise(self):
        reset = NOW + 74 * H
        hist = [{"ts": NOW - 660, "used_pct": 82.0, "resets_at": reset},
                {"ts": NOW, "used_pct": 83.0, "resets_at": reset}]
        p = ub.pace(window_fact(83, reset, 10080, NOW, NOW), hist, NOW)
        self.assertEqual(p["burn_basis"], "window_average")  # 1 point in 11 min is rounding noise
        hist[0]["used_pct"] = 70.0
        p = ub.pace(window_fact(83, reset, 10080, NOW, NOW), hist, NOW)
        self.assertTrue(p["burn_basis"].startswith("ledger_slope"))
        self.assertAlmostEqual(p["burn_pct_per_h"], 13 / (660 / H), places=1)

    def test_old_reading_uses_its_own_open_time(self):
        # read 12 h ago at 76.9 % with 120.7 h then left: the window had been open 47.3 h at the reading
        p = ub.pace(window_fact(76.9, NOW + 108.7 * H, 10080, NOW - 12 * H, NOW), [], NOW)
        self.assertAlmostEqual(p["burn_pct_per_h"], 76.9 / (168 - 120.7), places=2)

    def test_exhausted_and_refilled_windows(self):
        self.assertEqual(ub.pace(_window(100, 20, 10080), [], NOW)["state"], "LIMITED")
        refilled = window_fact(40, NOW - 60, 300, NOW - 3 * H, NOW)
        p = ub.pace(refilled, [], NOW)
        self.assertEqual((p["used_pct"], p["burn_basis"], p["headroom"]), (0.0, "no_reading", None))
        self.assertEqual(ub.binding_headroom([ub.pace(_window(100, 2, 300), [], NOW), p]), 0.0)
        self.assertIsNone(ub.binding_headroom([p]))


class Split(unittest.TestCase):
    def test_on_pace_keeps_measured_mix(self):
        s = ub.derive_split({"local": 10, "helper": 20, "core": 70}, 0.4, 1.3)
        self.assertEqual(s["shares"], {"local": 0.1, "helper": 0.2, "core": 0.7})
        self.assertEqual(s["paid_step_rate"], 1.0)

    def test_behind_pace_moves_core_to_helper_then_local_within_bounds(self):
        s = ub.derive_split({"local": 0, "helper": 0, "core": 100}, 0.5, 0.6)
        self.assertEqual(s["moves"][0].split()[0], "core->helper")
        self.assertLessEqual(s["shares"]["helper"], ub.HELPER_CEIL)
        self.assertLessEqual(s["shares"]["local"], ub.LOCAL_CEIL)
        self.assertGreaterEqual(s["shares"]["core"], ub.CORE_FLOOR - 1e-9)
        self.assertAlmostEqual(s["paid_cost_per_step"], 0.6, places=3)
        self.assertEqual(s["paid_step_rate"], 1.0)

    def test_deep_deficit_slows_pace_instead_of_cutting_quality(self):
        s = ub.derive_split({"local": 0, "helper": 0, "core": 100}, None, 0.1)
        self.assertEqual(s["shares"], {"local": 0.5, "helper": 0.0, "core": 0.5})
        self.assertAlmostEqual(s["paid_step_rate"], 0.2, places=3)  # 0.1 target / 0.5 remaining paid cost

    def test_over_ceiling_mix_returns_to_core(self):
        s = ub.derive_split({"local": 80, "helper": 0, "core": 20}, None, None)
        self.assertEqual(s["shares"]["local"], ub.LOCAL_CEIL)

    def test_shares_always_sum_to_one_within_bounds(self):
        # agy audit relay_2a325145 #2: capping local/helper must never leave the shares short of 1 or out of bounds
        grid = (0, 5, 20, 45, 60, 100)
        for loc in grid:
            for hlp in grid:
                for core in grid:
                    for cost in (None, 0.0, 0.3, 1.0, 1.5):
                        for head in (None, 0.0, 0.2, 0.7, 1.0, 3.0):
                            sh = ub.derive_split({"local": loc, "helper": hlp, "core": core}, cost, head)["shares"]
                            case = (loc, hlp, core, cost, head, sh)
                            self.assertAlmostEqual(sum(sh.values()), 1.0, delta=0.002, msg=case)
                            self.assertLessEqual(sh["local"], ub.LOCAL_CEIL + 1e-9, case)
                            self.assertLessEqual(sh["helper"], ub.HELPER_CEIL + 1e-9, case)
                            self.assertGreaterEqual(sh["core"], ub.CORE_FLOOR - 1e-9, case)
                            self.assertGreaterEqual(min(sh.values()), 0.0, case)


def _paces(rem7, h7, rem5=None):
    p7 = ub.pace(_window(100 - rem7, h7, 10080), [], NOW)
    p5 = ub.pace(_window(100 - rem5, 2, 300), [], NOW) if rem5 is not None else None
    return {"7d": p7, "5h": p5}


class Flagship(unittest.TestCase):
    def test_ultra_main_route_frequency_from_burn_per_step(self):
        # 7d pool: 50 % used after 84 h open -> burn 0.595 %/h; 336 paid steps in 7 d -> 2 steps/h -> 0.298 %/step
        paces, mix = _paces(50, 84), {"core": 300, "helper": 36}
        fl = ub.main_route_allowance("antigravity", paces, mix, None, [ub.ULTRA_ARGON_HIGH_RECEIPT])
        pct_step = (50 / 84) / 2.0
        freq = (50 - ub.WEEKLY_RESERVE_PCT) / pct_step / 84
        self.assertEqual(fl["route"], "main")
        self.assertAlmostEqual(fl["steps_per_h"], freq, places=2)  # burn is reported to 3 decimals
        self.assertAlmostEqual(fl["share"], freq / 2.0, places=2)
        self.assertEqual(fl["max_steps_5h"], int(freq * 5))
        self.assertTrue(fl["meets_5x_target"])  # 0.8 >= 5 x 10 %
        self.assertGreaterEqual(fl["share"], ub.ULTRA_TARGET_MULTIPLE *
                                ub.flagship_allowance("codex", paces, 1.5, 3.5, [], 30)["share"])
        self.assertIn("receipt_duty", fl)

    def test_ultra_main_route_token_form_and_reserve(self):
        paces = _paces(50, 84)
        mix = {"core": 300, "helper": 36, "tokens_per_step": 500}
        fl = ub.main_route_allowance("antigravity", paces, mix, {"tokens_per_pct": 1000, "samples": 4}, [])
        self.assertEqual(fl["basis"], "calibrated_tokens(n=4)")  # 0.5 %/step is costlier than burn's 0.298
        self.assertEqual(len(fl["cost_measurements"]), 2)
        self.assertAlmostEqual(fl["steps_per_h"], round(40 / 0.5 / 84, 3), places=3)  # remaining / step / hours
        cheap = ub.main_route_allowance("antigravity", paces, {**mix, "tokens_per_step": 100},
                                        {"tokens_per_pct": 1000, "samples": 1}, [])
        self.assertTrue(cheap["basis"].startswith("window_burn/steps_7d"))  # the costlier measurement paces
        self.assertFalse(fl["meets_5x_target"])
        self.assertIn("below 5x target", fl["note"])
        low = ub.main_route_allowance("antigravity", _paces(8, 84), mix, None, [])
        self.assertEqual(low["share"], 0.0)
        self.assertTrue(any("reserve" in r for r in low["blocked_by"]))
        none = ub.main_route_allowance("antigravity", {"7d": None, "5h": None}, mix, None, [])
        self.assertEqual(none["share"], 0.0)

    def test_ultra_boundaries_fail_closed(self):
        # agy audit relay_2a325145 #1: at the reserve, at/past the reset, or with a zero step cost -> share 0, no
        # division by zero and never a negative frequency
        mix = {"core": 300, "helper": 36}
        at_reserve = ub.main_route_allowance("antigravity", _paces(ub.WEEKLY_RESERVE_PCT, 84), mix, None, [])
        past_reset = ub.main_route_allowance("antigravity", _paces(50, -1), mix, None, [])
        no_burn = ub.main_route_allowance("antigravity", _paces(100, 84), mix, None, [])  # 0 % used: burn 0
        zero_cal = ub.main_route_allowance("antigravity", {"7d": {**_paces(50, 84)["7d"], "burn_pct_per_h": 0.0},
                                                           "5h": None},
                                           {**mix, "tokens_per_step": 0}, {"tokens_per_pct": 0, "samples": 1}, [])
        for fl in (at_reserve, past_reset, no_burn, zero_cal):
            self.assertEqual((fl["share"], fl["max_steps_5h"]), (0.0, 0), fl)
            self.assertTrue(fl["blocked_by"], fl)
            self.assertTrue(fl["steps_per_h"] is None or fl["steps_per_h"] >= 0, fl)

    def test_ultra_gate_skips_scarce_rules(self):
        snap = {"schema": ub.SCHEMA, "id": "x", "timestamp": NOW, "tools": {
            "antigravity": {"flagship": {"route": "main", "share": 0.6, "max_steps_5h": 8, "blocked_by": []}}}}
        ok = ub.flagship_gate(snap, "antigravity", importance=2, difficulty=3, now=NOW)
        self.assertEqual((ok["allow"], ok["model"], ok["effort"]), (True, "gemini-4-argon", "high"))
        cap = ub.flagship_gate(snap, "antigravity", importance=5, difficulty=5, used_steps_5h=8, now=NOW)
        self.assertEqual((cap["allow"], cap["effort"]), (False, "medium"))

    def test_pro_plan_ratio_path_is_capped_at_ten_percent(self):
        fl = ub.flagship_allowance("codex", _paces(60, 40), 1.5, 3.5, [], 30)
        self.assertEqual(fl["share"], 0.1)
        self.assertEqual(fl["basis"], "spare_headroom/ratio")

    def test_blocks(self):
        self.assertEqual(ub.flagship_allowance("codex", _paces(60, 40), 0.9, 3.5, [], 30)["share"], 0.0)
        self.assertEqual(ub.flagship_allowance("codex", _paces(60, 40, rem5=15), 2.0, 3.5, [], 30)["share"], 0.0)
        self.assertEqual(ub.flagship_allowance("codex", _paces(8, 40), 2.0, 3.5, [], 30)["share"], 0.0)
        self.assertEqual(ub.flagship_allowance("claude", _paces(60, 40), None, 3.5, [], 30)["share"], 0.0)

    def test_gate_rules(self):
        snap = {"schema": ub.SCHEMA, "id": "x", "timestamp": NOW, "tools": {
            "codex": {"flagship": {"share": 0.1, "max_steps_5h": 2, "blocked_by": []}}}}
        ok = ub.flagship_gate(snap, "codex", importance=4, difficulty=4, keypoint_class="final_verdict", now=NOW)
        self.assertTrue(ok["allow"])
        self.assertEqual(ok["model"], "gpt-6-astra")
        low = ub.flagship_gate(snap, "codex", importance=3, difficulty=5, keypoint_class="final_verdict", now=NOW)
        self.assertEqual((low["allow"], low["model"]), (False, "gpt-6.1-sol"))
        no_reason = ub.flagship_gate(snap, "codex", importance=5, difficulty=5, now=NOW)
        self.assertTrue(any(r.startswith("R2") for r in no_reason["failed_rules"]))
        used = ub.flagship_gate(snap, "codex", importance=5, difficulty=5, cheaper_route_failed="wid-1",
                                used_steps_5h=2, now=NOW)
        self.assertTrue(any(r.startswith("R3") for r in used["failed_rules"]))
        with self.assertRaises(ub.BudgetSnapshotError):
            ub.flagship_gate(snap, "codex", importance=5, difficulty=5, now=NOW + ub.FRESH_S + 1)


class FailClosed(unittest.TestCase):
    def test_schedule_without_or_with_stale_snapshot_fails(self):
        with self.assertRaises(ub.BudgetSnapshotError) as e:
            ub.validate_schedule_budget({"steps": []}, now=NOW)
        self.assertEqual(e.exception.code, "BUDGET_SNAPSHOT_MISSING")
        with self.assertRaises(ub.BudgetSnapshotError) as e:
            ub.require_fresh_snapshot(None, now=NOW)
        self.assertEqual(e.exception.code, "BUDGET_SNAPSHOT_MISSING")
        stale = {"schema": ub.SCHEMA, "id": "s", "timestamp": NOW - ub.FRESH_S - 5, "tools": {}}
        with self.assertRaises(ub.BudgetSnapshotError) as e:
            ub.stamp_schedule({}, stale, now=NOW)
        self.assertEqual(e.exception.code, "BUDGET_SNAPSHOT_STALE")


def _capacity():
    return {
        "generated_at": _iso(NOW),
        "measured_accounts": {
            "codex": {"source": "codex_rollout_rate_limits", "five_hour": _window(30, 3, 300, 60),
                      "seven_day": _window(40, 100, 10080, 60),
                      "calibration_5h": {"basis": "pairs_median", "samples": 5, "tokens_per_pct": 1000,
                                         "capacity_tokens": 100000},
                      "model_mix_7d": [{"model": "gpt-6.1-sol", "calls": 100, "output_tokens": 50000},
                                       {"model": "gpt-6-luna", "calls": 50, "output_tokens": 9000}]},
            "claude": {"model_mix_7d": [{"model": "claude-opus-5-5", "calls": 200, "output_tokens": 100000}]},
            "antigravity": {"pools": [{**_window(60, 80, 10080, 60), "models": ["Gemini 3.8 Flash (High)"]},
                                      {**_window(10, 2, 300, 60), "models": ["Claude Opus 5.5 (High)"]}]},
        },
        "engines": {"antigravity": {"window_7d": {"calls": 300}}},
        "antigravity_accounts": {"accounts": [{"email": "someone@example.com", "plan": "Google AI Ultra",
                                               "kind": "subscription"}]},
    }


class Snapshot(unittest.TestCase):
    def test_build_from_fixtures_records_ledger_and_reads_claude_observation(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            ub.record_observation("claude", "5h", 50, NOW + 2 * H, NOW - 120, "ccd_get_usage", home=home)
            snap = ub.budget_snapshot(home, home=home, now=NOW, capacity=_capacity(), persist=False)
            self.assertEqual(set(snap["tools"]), set(ub.TOOLS))
            cl = snap["tools"]["claude"]
            self.assertEqual(cl["windows"]["5h"]["used_pct"], 50.0)
            self.assertEqual(cl["windows"]["5h"]["burn_basis"], "window_average")
            cx = snap["tools"]["codex"]
            self.assertEqual(cx["windows"]["5h"]["remaining_tokens"], 70000)  # 1000 tokens/% x 70 % (n=5)
            self.assertLess(cx["split"]["helper_cost"], 0.1)  # Luna vs Sol, official estimate
            ag = snap["tools"]["antigravity"]
            self.assertEqual(ag["windows"]["7d"]["used_pct"], 60.0)  # Gemini pool, not the Claude pool
            self.assertIsNone(ag["windows"]["5h"])
            self.assertEqual(ag["accounts"][0]["account"], "so***ne@example.com")
            self.assertEqual(len(ub.read_observations("codex", "7d", home=home)), 1)
            self.assertTrue(ub.read_burn_receipts("antigravity", home=home))
            sched = ub.stamp_schedule({"steps": []}, snap, now=NOW + 10)
            self.assertEqual(ub.validate_schedule_budget(sched, now=NOW + 20)["id"], snap["id"])
            text = ub.render_text(snap)
            for tool in ub.TOOLS:
                self.assertIn(f"[{tool}]", text)
            self.assertNotIn("someone@", text)

    def test_cli_observe_writes_the_ledger(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, PYTHONPATH=str(REPO), USERPROFILE=d, HOME=d)
            r = subprocess.run([sys.executable, "-m", "v7_harness.cli", "coord", "budget", "--action", "observe",
                                "--tool", "claude", "--window", "7d", "--used-pct", "83",
                                "--resets-at", "2026-11-06T19:59:59Z", "--observed-at", "2026-11-03T17:06:56Z",
                                "--source", "ccd_get_usage"], cwd=str(REPO), env=env, capture_output=True, text=True,
                               timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(ub.read_observations("claude", "7d", home=Path(d))[0]["used_pct"], 83.0)


class RouterRatio(unittest.TestCase):
    """The helper router's 50/30/20 is a labelled prior; a snapshot's measured split replaces it."""

    def test_prior_is_labelled_and_snapshot_split_replaces_it(self):
        from v7_harness.coord import helper_thinking_router as R
        prior = {"ollama_pct": 50.0, "helper_pct": 30.0, "reasoning_core_pct": 20.0}
        self.assertEqual(R.select_optimal_helper_and_thinking("claude")["target_532_ratio"],
                         {**prior, "ratio_source": "static_prior"})
        self.assertEqual(R.COMMON_HELPER_RULE["target_parallel_ratio"], prior)
        snap = {"id": "s1", "tools": {"antigravity": {"split": {"shares": {"local": 0.5, "helper": 0.01,
                                                                            "core": 0.49}}}}}
        self.assertEqual(R.parallel_ratio("agy", snap), {"ollama_pct": 50.0, "helper_pct": 1.0,
                                                         "reasoning_core_pct": 49.0,
                                                         "ratio_source": "budget_snapshot:s1"})
        self.assertEqual(R.parallel_ratio("codex", snap)["ratio_source"], "static_prior")

    def test_real_allocator_output_feeds_the_router(self):
        from v7_harness.coord import helper_thinking_router as R
        split = ub.derive_split({"local": 10, "helper": 30, "core": 60}, 0.2, 1.0)
        got = R.parallel_ratio("claude", {"id": "x", "tools": {"claude": {"split": split}}})
        self.assertAlmostEqual(got["ollama_pct"] + got["helper_pct"] + got["reasoning_core_pct"], 100.0, delta=0.3)
        self.assertLessEqual(got["ollama_pct"], ub.LOCAL_CEIL * 100)
        self.assertGreaterEqual(got["reasoning_core_pct"], ub.CORE_FLOOR * 100)


if __name__ == "__main__":
    unittest.main()
