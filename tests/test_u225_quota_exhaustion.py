"""Independent quota exhaustion counterexamples; never require cloud credit for local work."""
import unittest
from v7_harness.worker_routing import plan


class ExhaustedCloudQuota(unittest.TestCase):
    def task(self, kind):
        return dict(caller='antigravity', kind=kind, input_tokens=100, output_tokens=128,
                    changed_lines=0, local_qualified=True, local_failures=0,
                    allow_remote=False, budget_tokens=0, budget_usd=0, timeout_s=10)

    def test_zero_paid_budget_keeps_deterministic_and_local_running(self):
        for kind, worker in [('count', 'deterministic'), ('transform', 'local'),
                             ('final_approval', 'conductor')]:
            with self.subTest(kind=kind):
                r = plan(self.task(kind), {'local': True, 'haiku': False})
                self.assertEqual(r['status'], 'READY')
                self.assertEqual(r['worker'], worker)

    def test_semantic_classification_can_use_exact_bounded_haiku(self):
        task = self.task('classify')
        task.update(local_qualified=False, allow_remote=True, budget_tokens=1000, budget_usd=.02)
        r = plan(task, {'local': False, 'haiku': True})
        self.assertEqual(r['status'], 'READY')
        self.assertEqual(r['model'], 'claude-haiku-5-5')


if __name__ == '__main__':
    unittest.main()
