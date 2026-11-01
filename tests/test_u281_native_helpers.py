"""Independent fixed acceptance for opt-in subscription helper registration/routing."""
import pathlib
import tomllib
import unittest
from v7_harness.worker_routing import select_pool_worker

class NativeHelperAcceptance(unittest.TestCase):
    def task(self, **overrides):
        result = dict(caller='codex', kind='transform', input_tokens=100, output_tokens=40,
                      changed_lines=0, local_qualified=False, local_failures=0, allow_remote=True,
                      budget_tokens=1000, budget_usd=.02, timeout_s=60)
        result.update(overrides)
        return result

    def test_native_profiles(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        luna = tomllib.loads((root/'.codex/agents/uaos-luna-worker.toml').read_text())
        self.assertEqual(luna['model'], 'gpt-6-luna')
        self.assertTrue(all(v is False for v in luna['features'].values()))
        flash = (root/'.agents/agents/uaos-flash-worker.md').read_text()
        self.assertIn('model: gemini-3.8-flash-low', flash)
        self.assertIn('tools: []', flash)

    def test_all_callers_and_exact_pins(self):
        for caller in ('codex','claude','antigravity'):
            for model, seat, agent in [('gpt-6-luna','codex','uaos-luna-worker'), ('gemini-3.8-flash-low','agy','uaos-flash-worker')]:
                with self.subTest(caller=caller, model=model):
                    result = select_pool_worker(self.task(caller=caller, remote_model=model), {seat:True})
                    self.assertEqual((result['worker'],result['model'],result['subagent']), (seat,model,agent))
                    self.assertTrue(result['require_exact_model'])
                    self.assertFalse(result['execution_authorized'])

    def test_no_fallback_or_missing_caps(self):
        for model, seat in [('gpt-6-luna','codex'), ('gemini-3.8-flash-low','agy')]:
            for changes, available in [({},False),({'allow_remote':False},True),({'budget_tokens':0},True),({'budget_usd':float('inf')},True),({'timeout_s':0},True),({'budget_tokens':120},True)]:
                with self.subTest(model=model,changes=changes,available=available):
                    result = select_pool_worker(self.task(remote_model=model,**changes), {seat:available,'haiku':True})
                    self.assertEqual(result['status'],'BLOCKED')
                    self.assertIsNone(result['worker'])

    def test_local_and_deterministic_stay_first(self):
        for model in ('gpt-6-luna','gemini-3.8-flash-low'):
            result = select_pool_worker(self.task(remote_model=model,local_qualified=True), {'local':True,'codex':True,'agy':True})
            self.assertEqual(result['worker'],'local')
            result = select_pool_worker(self.task(remote_model=model,kind='extract_exact'), {})
            self.assertEqual(result['worker'],'deterministic')

    def test_unknown_model_is_blocked(self):
        result = select_pool_worker(self.task(remote_model='auto'), {'codex':True,'agy':True,'haiku':True})
        self.assertEqual(result['status'],'BLOCKED')

if __name__ == '__main__': unittest.main()
