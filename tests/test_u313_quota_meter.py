"""U313 independent fixed acceptance; authored before the implementation."""
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord.native_meter import MeterStore, normalize


def agy(weekly=.06, five=1.0, reset7=20000, reset5=10000):
    return {'model': {'id': 'Gemini 3.8 Flash', 'effort': 'high'}, 'quota': {
        'gemini-weekly': {'remaining_fraction': weekly, 'reset_time': reset7},
        'gemini-five-hour': {'remaining_fraction': five, 'reset_time': reset5}}}


class NativeAdapters(unittest.TestCase):
    def test_three_native_payloads_keep_distinct_pools_and_windows(self):
        cases = {
            'antigravity': agy(),
            'codex': {'rate_limits': {
                'primary': {'used_percent': 20, 'window_minutes': 300, 'resets_at': 10000},
                'secondary': {'used_percent': 30, 'window_minutes': 10080, 'resets_at': 20000}}},
            'claude': {'rate_limits': {
                'five_hour': {'used_percentage': 40, 'resets_at': 10000},
                'seven_day': {'used_percentage': 50, 'resets_at': 20000}}}}
        expected = {'antigravity': {'5h': 100, '7d': 6},
                    'codex': {'5h': 80, '7d': 70}, 'claude': {'5h': 60, '7d': 50}}
        for tool, payload in cases.items():
            rows = normalize(tool, payload, account='opaque-a', observed_at=1000, received_at=1000)
            self.assertEqual(expected[tool], {r['window']: r['remaining_pct'] for r in rows})
            self.assertTrue(all(r['tool'] == tool and r['account'] == 'opaque-a' for r in rows))

    def test_no_raw_payload_or_personal_fields_persisted(self):
        payload = agy(); payload.update(email='private@example.invalid', token='SENTINEL_SECRET', transcript_path='private')
        rendered = json.dumps(normalize('antigravity', payload, account='opaque-a', observed_at=1000, received_at=1000))
        for forbidden in ('private@example.invalid', 'SENTINEL_SECRET', 'transcript_path', 'capacity_tokens'):
            self.assertNotIn(forbidden, rendered)

    def test_missing_observation_time_is_not_receipt_time(self):
        rows = normalize('antigravity', agy(), account='opaque-a', received_at=1000)
        self.assertTrue(rows)
        self.assertTrue(all(r['observed_at'] is None for r in rows))

    def test_invalid_numbers_and_shapes_fail_closed(self):
        for invalid in (True, float('nan'), float('inf'), -1, 1.01, [], {}):
            with self.subTest(value=str(invalid)):
                with self.assertRaises(ValueError):
                    normalize('antigravity', agy(weekly=invalid), account='opaque-a', observed_at=1000, received_at=1000)
        with self.assertRaises(ValueError):
            normalize('antigravity', [], account='opaque-a', observed_at=1000, received_at=1000)

    def test_future_source_time_rejected(self):
        with self.assertRaises(ValueError):
            normalize('antigravity', agy(), account='opaque-a', observed_at=1100, received_at=1000)

    def test_remaining_amount_is_not_percent(self):
        rows = normalize('antigravity', {'quota': {'gemini-weekly': {'remaining_amount': 200, 'reset_time': 20000}}},
                         account='opaque-a', observed_at=1000, received_at=1000)
        self.assertTrue(all(r.get('remaining_pct') is None for r in rows))


class MeterReceipts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'meter.sqlite3'; self.store = MeterStore(self.path)

    def put(self, payload=None, at=1000, account='opaque-a', received=None):
        return self.store.ingest('antigravity', payload if payload is not None else agy(), account=account,
                                 observed_at=at, received_at=at if received is None else received)

    def route(self, **kw):
        args = dict(now=1001, max_age_s=10, requested_points=.1, reserve_points=1)
        args.update(kw)
        return self.store.route('antigravity', 'opaque-a', 'gemini', **args)

    def test_idempotency_and_fresh_bounded_admission(self):
        self.assertEqual(2, self.put()); self.assertEqual(0, self.put())
        self.assertEqual(2, len(self.store.observations()))
        self.assertEqual('ALLOW_BOUNDED', self.route()['action'])

    def test_missing_stale_unobserved_and_exhausted_never_admit(self):
        self.assertNotEqual('ALLOW_BOUNDED', self.route()['action'])
        self.put(); self.assertNotEqual('ALLOW_BOUNDED', self.route(now=1100)['action'])
        self.put(agy(weekly=0), at=1100)
        self.assertNotEqual('ALLOW_BOUNDED', self.route(now=1101)['action'])

    def test_received_time_does_not_rejuvenate_old_source(self):
        self.put(at=1000, received=2000)
        self.assertNotEqual('ALLOW_BOUNDED', self.route(now=2001)['action'])

    def test_wrong_account_pool_and_missing_window_never_admit(self):
        self.put(account='opaque-b'); self.assertNotEqual('ALLOW_BOUNDED', self.route()['action'])
        self.assertNotEqual('ALLOW_BOUNDED', self.store.route('antigravity', 'opaque-b', 'claude_gpt', now=1001,
                            max_age_s=10, requested_points=.1, reserve_points=1)['action'])
        only = agy(); del only['quota']['gemini-five-hour']
        other = MeterStore(Path(self.tmp.name) / 'other.sqlite3')
        other.ingest('antigravity', only, account='opaque-a', observed_at=1000, received_at=1000)
        self.assertNotEqual('ALLOW_BOUNDED', other.route('antigravity', 'opaque-a', 'gemini', now=1001,
                            max_age_s=10, requested_points=.1, reserve_points=1)['action'])

    def test_elapsed_reset_does_not_refill_and_bad_budget_rejected(self):
        self.put(agy(reset5=1001))
        self.assertNotEqual('ALLOW_BOUNDED', self.route(now=1002)['action'])
        for value in (float('nan'), float('inf'), -1, True):
            with self.assertRaises(ValueError):
                self.route(requested_points=value)

    def test_pair_receipt_computes_points_not_tokens(self):
        self.put(); self.assertTrue(self.store.begin('w1', 'antigravity', 'opaque-a', 'gemini', now=1001, max_age_s=10)['ok'])
        self.put(agy(weekly=.055, five=.995), at=1002)
        receipt = self.store.end('w1', now=1003, max_age_s=10)
        self.assertTrue(receipt['ok']); self.assertAlmostEqual(.5, receipt['delta_pct_points']['7d'])
        self.assertAlmostEqual(.5, receipt['delta_pct_points']['5h'])
        self.assertEqual('POOL_INTERVAL', receipt['attribution'])
        self.assertNotIn('capacity_tokens', json.dumps(receipt))
        self.assertEqual(receipt, self.store.end('w1', now=1004, max_age_s=10))

    def test_missing_after_or_reset_change_cannot_fake_zero(self):
        self.put(); self.store.begin('w1', 'antigravity', 'opaque-a', 'gemini', now=1001, max_age_s=10)
        self.assertFalse(self.store.end('w1', now=1002, max_age_s=10)['ok'])
        self.put(agy(reset7=30000), at=1003)
        self.assertFalse(self.store.end('w1', now=1004, max_age_s=10)['ok'])

    def test_concurrent_jobs_cannot_claim_exclusive_task_cost(self):
        self.put()
        for name in ('one', 'two'):
            self.assertTrue(self.store.begin(name, 'antigravity', 'opaque-a', 'gemini', now=1001, max_age_s=10)['ok'])
        self.put(agy(weekly=.05), at=1002)
        for name in ('one', 'two'):
            self.assertEqual('POOL_INTERVAL', self.store.end(name, now=1003, max_age_s=10)['attribution'])

    def test_real_parallel_writers_lose_no_observations(self):
        code = "from pathlib import Path; from v7_harness.coord.native_meter import MeterStore; import sys; s=MeterStore(Path(sys.argv[1])); [(s.ingest('antigravity', {'quota': {'gemini-weekly': {'remaining_fraction': .5, 'reset_time': 20000}}},account=sys.argv[2],observed_at=1000+i,received_at=1000+i)) for i in range(12)]"
        workers = [subprocess.Popen([sys.executable, '-c', code, str(self.path), account], stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True) for account in ('parallel-a', 'parallel-b')]
        for proc in workers:
            out, err = proc.communicate(timeout=30)
            self.assertEqual(0, proc.returncode, out + err)
        self.assertEqual(24, len(self.store.observations()))

    def test_operating_guard_blocks_before_calling_provider(self):
        calls = []
        result = self.store.run_bounded('blocked', 'antigravity', 'opaque-a', 'gemini', lambda: calls.append('paid'),
                                       now=1001, after_now=1003, max_age_s=10, requested_points=.1, reserve_points=1)
        self.assertFalse(result['ok']); self.assertEqual([], calls)
        self.put()
        def operation():
            calls.append('bounded'); self.put(agy(weekly=.055), at=1002); return 'finished'
        result = self.store.run_bounded('bounded', 'antigravity', 'opaque-a', 'gemini', operation,
                                       now=1001, after_now=1003, max_age_s=10, requested_points=.1, reserve_points=1)
        self.assertTrue(result['ok']); self.assertEqual(['bounded'], calls)
        self.assertEqual('finished', result['value']); self.assertTrue(result['receipt']['ok'])


class OperatingCli(unittest.TestCase):
    def test_native_cli_ingests_without_printing_raw_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            cmd = [sys.executable, '-m', 'v7_harness.cli', 'coord', 'meter', 'ingest', '--tool', 'antigravity',
                   '--account', 'opaque-a', '--observed-at', '1000', '--received-at', '1000', '--db', str(Path(tmp)/'live.db')]
            payload = agy(); payload['token'] = 'NEVER_ECHO_SENTINEL'
            cp = subprocess.run(cmd, input=json.dumps(payload), text=True, capture_output=True, timeout=30)
            self.assertEqual(0, cp.returncode, cp.stdout + cp.stderr)
            self.assertNotIn('NEVER_ECHO_SENTINEL', cp.stdout + cp.stderr)


if __name__ == '__main__':
    unittest.main()
