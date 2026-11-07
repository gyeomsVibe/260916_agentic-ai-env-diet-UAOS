"""S1 acceptance (A1-A8): native-unit quota freshness/provenance, no percent-to-token conversion.

Contract: .work/sustain_20261107/S1_contract.md (author Claude, reviewer Antigravity pins this file's SHA256
before any source change; Codex fail-closed audit). Written before the implementation (test-first).
"""

from __future__ import annotations

import json

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from v7_harness.coord import quota_sources as qs  # noqa: E402
from v7_harness.coord import claude_statusline as rec  # noqa: E402

NOW = 1_800_000_000.0
H = 3600.0


def wf(used, resets_in_s, window_min, age_s):
    return qs.window_fact(used, NOW + resets_in_s, window_min, NOW - age_s, NOW)


class A1ResetUnobserved(unittest.TestCase):
    def test_passed_reset_without_new_observation_is_unknown_not_zero(self):
        w = wf(79, -60, qs.SEVEN_DAY_MIN, 2 * H)
        self.assertEqual(w["state"], "RESET_UNOBSERVED")
        self.assertIsNone(w["used_pct"])
        self.assertIsNone(w["remaining_pct"])
        self.assertEqual(w["observed_used_pct"], 79.0)
        self.assertFalse(w["admit_paid"])


class A2FreshAfterReset(unittest.TestCase):
    def test_observation_after_reset_carries_next_reset_and_is_fresh(self):
        w = wf(3, 4 * H, qs.FIVE_HOUR_MIN, 60)
        self.assertEqual(w["state"], "FRESH")
        self.assertEqual(w["used_pct"], 3.0)
        self.assertTrue(w["admit_paid"])


class A3Staleness(unittest.TestCase):
    def test_five_hour_window_max_age_15_minutes(self):
        self.assertEqual(wf(20, H, qs.FIVE_HOUR_MIN, 14 * 60)["state"], "FRESH")
        stale = wf(20, H, qs.FIVE_HOUR_MIN, 16 * 60)
        self.assertEqual(stale["state"], "STALE")
        self.assertFalse(stale["admit_paid"])

    def test_seven_day_window_max_age_6_hours(self):
        self.assertEqual(wf(20, 50 * H, qs.SEVEN_DAY_MIN, 5 * H)["state"], "FRESH")
        self.assertEqual(wf(20, 50 * H, qs.SEVEN_DAY_MIN, 7 * H)["state"], "STALE")

    def test_unknown_observation_time_is_stale(self):
        w = qs.window_fact(20, NOW + H, qs.FIVE_HOUR_MIN, None, NOW)
        self.assertEqual(w["state"], "STALE")
        self.assertFalse(w["admit_paid"])

    def test_every_max_age_has_a_reason(self):
        for minutes in (qs.FIVE_HOUR_MIN, qs.SEVEN_DAY_MIN):
            entry = qs.MAX_OBSERVATION_AGE[minutes]
            self.assertGreater(entry["seconds"], 0)
            self.assertTrue(entry["reason"].strip())


class A4BoundariesAndBothWindows(unittest.TestCase):
    def test_extremes_are_fresh_values(self):
        self.assertEqual(wf(0, H, qs.FIVE_HOUR_MIN, 0)["remaining_pct"], 100.0)
        self.assertEqual(wf(100, H, qs.FIVE_HOUR_MIN, 0)["remaining_pct"], 0.0)

    def test_both_windows_bind_independently(self):
        fresh5 = wf(10, H, qs.FIVE_HOUR_MIN, 60)
        stale7 = wf(10, 50 * H, qs.SEVEN_DAY_MIN, 7 * H)
        ev = qs.VERIFIED_EVIDENCE
        self.assertFalse(qs.admit_paid({"evidence": ev, "five_hour": fresh5, "seven_day": stale7}))
        self.assertFalse(qs.admit_paid({"evidence": ev, "five_hour": fresh5, "seven_day": None}))
        fresh7 = wf(10, 50 * H, qs.SEVEN_DAY_MIN, 60)
        self.assertTrue(qs.admit_paid({"evidence": ev, "five_hour": fresh5, "seven_day": fresh7}))

    def test_missing_account_is_not_admitted(self):
        self.assertFalse(qs.admit_paid({}))
        self.assertFalse(qs.admit_paid(None))
        self.assertEqual(qs.window_state(None), "MISSING")


# A5 (no percent-to-token conversion) moved to S2 by decision D11: the schedule's token allowance must be replaced
# by the percent-native governor in the same change, or schedule writing fails closed with nothing in its place.
# Pinned text: .work/sustain_20261107/S2_A5_carryover_test.py.txt
class A5ResetUnobservedYieldsNoTokens(unittest.TestCase):
    def test_unknown_remaining_percent_gives_no_remaining_tokens(self):
        w = wf(40, -60, qs.FIVE_HOUR_MIN, 2 * H)
        events = [{"engine": "claude", "ts": NOW - 3 * H, "raw_total": 50_000}]
        cal = qs.calibrate(w, events, NOW) or {}
        self.assertIsNone(cal.get("remaining_tokens"))


def write_claude_rows(home: Path, rows: list[dict]) -> None:
    path = home / qs.CLAUDE_LIMITS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


class A6Provenance(unittest.TestCase):
    def test_claude_windows_carry_source_and_observed_at(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            write_claude_rows(home, [{"ts": NOW - 60, "five_hour_used_pct": 19, "five_hour_resets_at": NOW + H,
                                      "seven_day_used_pct": 2, "seven_day_resets_at": NOW + 100 * H,
                                      "source": "claude_desktop_get_usage"}])
            acct = qs.claude_quota(home, NOW)
            self.assertEqual(acct["source"], "claude_desktop_get_usage")
            for key in ("five_hour", "seven_day"):
                self.assertEqual(acct[key]["source"], "claude_desktop_get_usage")
                self.assertIsNotNone(acct[key]["observed_at"])
            # Codex REVISE relay_19bd9932/relay_5f05bc5d: an operator-typed CLI label is advisory, never admits
            self.assertFalse(qs.admit_paid(acct))
            self.assertFalse(qs.admit_paid(acct, pool=acct["account_pool"]))
            with self.assertRaises(TypeError):  # no override parameter exists
                qs.admit_paid(acct, allow_operator_reported=True)

    def test_statusline_provider_row_admits(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            write_claude_rows(home, [{"ts": NOW - 60, "five_hour_used_pct": 19, "five_hour_resets_at": NOW + H,
                                      "seven_day_used_pct": 2, "seven_day_resets_at": NOW + 100 * H,
                                      "source": "claude_statusline_rate_limits"}])
            acct = qs.claude_quota(home, NOW)
            self.assertEqual(acct["evidence"], "provider_payload")
            self.assertTrue(qs.admit_paid(acct, pool=qs.pool_id("claude", "subscription", "all-models", home)))

    def test_unknown_or_missing_producer_stays_advisory(self):
        # Codex REVISE relay_acd9ea77: only an allowlisted producer is provider evidence
        for src in ("untrusted_unknown_feed", None):
            with tempfile.TemporaryDirectory() as d:
                home = Path(d)
                row = {"ts": NOW - 60, "five_hour_used_pct": 19, "five_hour_resets_at": NOW + H,
                       "seven_day_used_pct": 2, "seven_day_resets_at": NOW + 100 * H}
                if src:
                    row["source"] = src
                write_claude_rows(home, [row])
                acct = qs.claude_quota(home, NOW)
                self.assertNotEqual(acct["evidence"], "provider_payload", src)
                self.assertFalse(qs.admit_paid(acct, pool=acct["account_pool"]), src)

    def test_statusline_recorder_names_its_producer(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            out = home / qs.CLAUDE_LIMITS_FILE
            payload = {"rate_limits": {"five_hour": {"used_percentage": 19, "resets_at": NOW + H},
                                       "seven_day": {"used_percentage": 2, "resets_at": NOW + 100 * H}}}
            self.assertTrue(rec.record(payload, out, now=NOW - 60))
            self.assertTrue(qs.admit_paid(qs.claude_quota(home, NOW), pool=qs.pool_id("claude", "subscription", "all-models", home)))

    def test_measured_quota_without_dispatch_pool_fails_closed(self):
        # Codex REVISE relay_acd9ea77: apply_measured_quota binds the pool the dispatch really uses
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            write_claude_rows(home, [{"ts": NOW - 60, "five_hour_used_pct": 19, "five_hour_resets_at": NOW + H,
                                      "seven_day_used_pct": 2, "seven_day_resets_at": NOW + 100 * H,
                                      "source": "claude_statusline_rate_limits"}])
            m = qs.claude_quota(home, NOW)
            for pools, want in ((None, False), ({"claude": "claude:other:all-models:00000000"}, False),
                                ({"claude": m["account_pool"]}, True)):
                engines = {"claude": {}}
                qs.apply_measured_quota(engines, {"claude": m}, {"subscription_tiers": {}}, dispatch_pools=pools)
                self.assertIs(engines["claude"]["subscription_plan"]["quota_admit_paid"], want, pools)

    def test_missing_evidence_is_unverified(self):
        acct = {"five_hour": wf(10, H, qs.FIVE_HOUR_MIN, 60), "seven_day": wf(10, 50 * H, qs.SEVEN_DAY_MIN, 60)}
        self.assertFalse(qs.admit_paid(acct))

    def test_no_source_file_is_missing(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(qs.claude_quota(Path(d), NOW))
            self.assertEqual(qs.window_state(None), "MISSING")

    def test_cli_label_is_marked_unverified(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            write_claude_rows(home, [{"ts": NOW - 60, "five_hour_used_pct": 19, "five_hour_resets_at": NOW + H,
                                      "seven_day_used_pct": 2, "seven_day_resets_at": NOW + 100 * H,
                                      "source": "claude_desktop_get_usage"}])
            self.assertIn("not verified", qs.claude_quota(home, NOW)["evidence"])


class A9CodexRevise(unittest.TestCase):
    """Codex REVISE relay_aa3020e3 (2026-11-07): negatives FRESH alone must not pass."""

    def test_fresh_but_exhausted_denies(self):
        full = wf(100, H, qs.FIVE_HOUR_MIN, 60)
        self.assertEqual(full["state"], "FRESH")
        self.assertFalse(full["admit_paid"])
        self.assertFalse(qs.admit_paid({"five_hour": full, "seven_day": wf(10, 50 * H, qs.SEVEN_DAY_MIN, 60)}))

    def test_non_finite_or_out_of_range_is_invalid(self):
        for bad in (float("nan"), float("inf"), -1, 100.5, "abc"):
            w = wf(bad, H, qs.FIVE_HOUR_MIN, 60)
            self.assertEqual(w["state"], "INVALID", bad)
            self.assertFalse(w["admit_paid"])

    def test_future_observation_is_invalid(self):
        w = qs.window_fact(10, NOW + 2 * H, qs.FIVE_HOUR_MIN, NOW + 600, NOW)
        self.assertEqual(w["state"], "INVALID")

    def test_reset_not_after_observation_is_invalid(self):
        # a local re-record after the reset that still carries the old reset is not new provider evidence
        w = qs.window_fact(10, NOW - 60, qs.FIVE_HOUR_MIN, NOW - 30, NOW)
        self.assertEqual(w["state"], "INVALID")
        self.assertFalse(w["admit_paid"])

    def test_reset_further_than_window_is_invalid(self):
        w = qs.window_fact(10, NOW + 6 * H, qs.FIVE_HOUR_MIN, NOW - 60, NOW)
        self.assertEqual(w["state"], "INVALID")

    def test_other_pool_reading_never_admits(self):
        home_a, home_b = Path("/acct_a_home"), Path("/acct_b_home")
        mine = qs.pool_id("codex", "plus", "codex", home_a)
        acct = {"account_pool": mine, "evidence": qs.VERIFIED_EVIDENCE,
                "five_hour": wf(10, H, qs.FIVE_HOUR_MIN, 60), "seven_day": wf(10, 50 * H, qs.SEVEN_DAY_MIN, 60)}
        self.assertTrue(qs.admit_paid(acct, pool=mine))
        self.assertFalse(qs.admit_paid(acct, pool=qs.pool_id("claude", "subscription", "all-models", home_a)))
        # Codex REVISE relay_19bd9932: same provider, other plan must not admit
        self.assertFalse(qs.admit_paid(acct, pool=qs.pool_id("codex", "pro", "codex", home_a)))
        # Codex REVISE relay_5f05bc5d: same provider+plan, other account or other model pool must not admit
        self.assertFalse(qs.admit_paid(acct, pool=qs.pool_id("codex", "plus", "codex", home_b)))
        self.assertFalse(qs.admit_paid(acct, pool=qs.pool_id("codex", "plus", "premium", home_a)))
        self.assertFalse(qs.admit_paid({**acct, "account_pool": qs.pool_id("codex", None, "codex", home_a)}, pool=mine))

    def test_codex_reading_carries_its_own_home_pool(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            row = json.dumps({"timestamp": "2026-11-07T00:00:00Z", "payload": {"type": "token_count", "rate_limits": {
                "limit_id": "codex", "plan_type": "plus",
                "primary": {"used_percent": 10, "window_minutes": 300, "resets_at": NOW + H},
                "secondary": {"used_percent": 10, "window_minutes": 10080, "resets_at": NOW + 50 * H}}}})
            p = home / ".codex/sessions/2026/11/07/rollout-x.jsonl"
            p.parent.mkdir(parents=True)
            p.write_text(row + "\n", encoding="utf-8")
            acct = qs.codex_quota(home, NOW)
            self.assertEqual(acct["account_pool"], qs.pool_id("codex", "plus", "codex", home))
            self.assertNotIn(str(home), acct["account_pool"])  # a hash tag, not the path

    def test_replayed_older_row_does_not_win(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            new = {"ts": NOW - 60, "five_hour_used_pct": 40, "five_hour_resets_at": NOW + H,
                   "seven_day_used_pct": 30, "seven_day_resets_at": NOW + 100 * H}
            old = {**new, "ts": NOW - 3 * H, "five_hour_used_pct": 5, "five_hour_resets_at": NOW - 3 * H + 4 * H}
            future = {**new, "ts": NOW + 3600, "five_hour_used_pct": 1}
            write_claude_rows(home, [new, old, future])
            self.assertEqual(qs.claude_quota(home, NOW)["five_hour"]["used_pct"], 40.0)


def run_cli(home: Path, *args: str) -> subprocess.CompletedProcess:
    env = {"HOME": str(home), "USERPROFILE": str(home), "PYTHONIOENCODING": "utf-8", "SYSTEMROOT": "C:\\Windows"}
    return subprocess.run([sys.executable, "-m", "v7_harness.cli", "coord", "quota-feed-claude", *args],
                          cwd=str(ROOT), env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)


class A7DesktopFeed(unittest.TestCase):
    def test_feed_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            r = run_cli(home, "--five-hour-pct", "19", "--five-hour-resets", "2026-11-07T08:49:59Z",
                        "--week-pct", "2", "--week-resets", "2026-11-13T19:59:59Z")
            self.assertEqual(r.returncode, 0, r.stderr)
            rows = [json.loads(x) for x in (home / qs.CLAUDE_LIMITS_FILE).read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows[-1]["source"], "claude_desktop_get_usage")
            self.assertEqual(rows[-1]["five_hour_used_pct"], 19.0)
            self.assertEqual(rows[-1]["seven_day_used_pct"], 2.0)


class A8ParallelFeed(unittest.TestCase):
    def test_four_real_processes_lose_no_row(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            env = {"HOME": str(home), "USERPROFILE": str(home), "PYTHONIOENCODING": "utf-8", "SYSTEMROOT": "C:\\Windows"}
            procs = [subprocess.Popen([sys.executable, "-m", "v7_harness.cli", "coord", "quota-feed-claude",
                                       "--five-hour-pct", str(10 + i), "--five-hour-resets", "2026-11-07T08:49:59Z",
                                       "--week-pct", str(i), "--week-resets", "2026-11-13T19:59:59Z"],
                                      cwd=str(ROOT), env=env) for i in range(4)]
            for p in procs:
                self.assertEqual(p.wait(timeout=120), 0)
            rows = [json.loads(x) for x in (home / qs.CLAUDE_LIMITS_FILE).read_text(encoding="utf-8").splitlines()]
            self.assertEqual(sorted(r["five_hour_used_pct"] for r in rows), [10.0, 11.0, 12.0, 13.0])


if __name__ == "__main__":
    unittest.main()
