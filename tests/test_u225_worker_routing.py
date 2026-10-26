"""Judge-owned route gates: useful offload never means unbounded paid escalation."""
import unittest


class WorkerRoutingAcceptance(unittest.TestCase):
    def task(self, **kw):
        task = dict(caller='codex', kind='transform', input_tokens=500, output_tokens=128,
                    changed_lines=1, local_qualified=True, local_failures=0,
                    allow_remote=False, budget_tokens=1000, budget_usd=.02, timeout_s=45)
        task.update(kw)
        return task

    def route(self, **kw):
        from v7_harness.worker_routing import plan
        return plan(self.task(**kw), {'local': True, 'haiku': True})

    def test_all_three_callers_use_same_local_first_gate(self):
        for caller in ('codex', 'claude', 'antigravity'):
            with self.subTest(caller=caller):
                r = self.route(caller=caller)
                self.assertEqual(r['worker'], 'local')

    def test_exact_operations_need_no_model(self):
        for kind in ('count', 'hash', 'validate', 'extract_exact'):
            self.assertEqual(self.route(kind=kind)['worker'], 'deterministic')

    def test_final_judgment_never_goes_to_haiku_or_ollama(self):
        for kind in ('final_approval', 'security_judgment', 'concurrency_judgment'):
            self.assertEqual(self.route(kind=kind, allow_remote=True)['worker'], 'conductor')

    def test_two_failed_local_slices_need_explicit_paid_authority(self):
        r = self.route(local_failures=2)
        self.assertEqual(r['status'], 'BLOCKED')

    def test_explicit_bounded_haiku_keeps_exact_requested_model(self):
        r = self.route(local_failures=2, allow_remote=True)
        self.assertEqual(r['worker'], 'claude')
        self.assertEqual(r['model'], 'claude-haiku-5-5')
        self.assertEqual(r['status'], 'READY')

    def test_haiku_cannot_run_without_every_finite_cap(self):
        for key, value in (('budget_tokens', 0), ('budget_usd', 0),
                           ('budget_usd', float('inf')), ('timeout_s', 0),
                           ('output_tokens', 0), ('budget_tokens', True)):
            with self.subTest(key=key, value=value):
                r = self.route(local_failures=2, allow_remote=True, **{key: value})
                self.assertEqual(r['status'], 'BLOCKED')

    def test_no_silent_model_fallback_under_haiku_quota(self):
        from v7_harness.worker_routing import plan
        r = plan(self.task(local_failures=2, allow_remote=True),
                 {'local': True, 'haiku': False})
        self.assertEqual(r['status'], 'BLOCKED')

    def test_unknown_caller_and_oversized_local_edits_fail_closed(self):
        self.assertEqual(self.route(caller='unknown')['status'], 'BLOCKED')
        self.assertNotEqual(self.route(changed_lines=21)['worker'], 'local')

    def test_remote_token_cap_includes_input_and_output(self):
        r = self.route(local_failures=2, allow_remote=True, budget_tokens=600)
        self.assertEqual(r['status'], 'BLOCKED')

    def test_cost_forecast_is_explicit_scenario_not_quota_claim(self):
        from v7_harness.worker_routing import forecast
        r = forecast(calls=1000, input_tokens=976, output_tokens=22,
                     cache_read_tokens=0, cache_write_tokens=974)
        self.assertAlmostEqual(r['estimated_usd'], .206, places=6)
        self.assertEqual(r['quota_saving'], 'UNMEASURED')
        r = forecast(calls=1000, input_tokens=976, output_tokens=22,
                     cache_read_tokens=974, cache_write_tokens=0)
        self.assertAlmostEqual(r['estimated_usd'], .02094, places=6)


if __name__ == '__main__':
    unittest.main()
