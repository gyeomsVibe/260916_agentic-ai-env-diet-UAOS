"""Judge-owned acceptance: idle wake is a native capability, not a detached PID."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness import global_install


class NativeListenerAcceptance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / '.coord/presence').mkdir(parents=True)
        (self.root / '.coord/PLAN.md').write_text('# test plan', encoding='utf-8')
        (self.root / '.coord/presence/user_desk_claude.json').write_text(
            json.dumps({'thread': 'native-a', 'generation': 1, 'source': 'UserPromptSubmit'}),
            encoding='utf-8')
        self.payload = {'session_id': 'native-a', 'cwd': str(self.root),
                        'hook_event_name': 'Stop'}

    def run_listener(self, found, payload=None, tool='claude'):
        from v7_harness.coord import continuity
        watcher = mock.Mock(return_value=found)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('UAOS_WORKER', None)
            result = continuity.run_hook(self.payload if payload is None else payload, tool,
                                         timeout_s=1, interval_s=.05, watch_fn=watcher)
        return result, watcher

    def test_claimed_actionable_exits_two_for_native_claude(self):
        result, watcher = self.run_listener({'id': 'relay_abc', 'wake_class': 'ACTIONABLE',
                                             'requested_target': 'claude'})
        self.assertEqual(result[0], 2)
        self.assertTrue(watcher.called)

    def test_timeout_is_silent_and_never_wakes(self):
        result, _ = self.run_listener(None)
        self.assertEqual(result[0], 0)

    def test_notice_is_not_promoted_to_paid_wake(self):
        result, _ = self.run_listener({'id': 'notice', 'wake_class': 'NOTICE',
                                      'requested_target': 'claude'})
        self.assertEqual(result[0], 0)

    def test_no_native_session_never_arms(self):
        result, watcher = self.run_listener(None, {'cwd': str(self.root)})
        self.assertEqual(result[0], 0)
        watcher.assert_not_called()

    def test_foreign_desk_cannot_consume_current_desk_wake(self):
        payload = {**self.payload, 'session_id': 'native-foreign'}
        result, watcher = self.run_listener(None, payload)
        self.assertEqual(result[0], 0)
        watcher.assert_not_called()

    def test_existing_watcher_does_not_create_paid_retry(self):
        result, _ = self.run_listener({'state': 'ALREADY_WATCHING', 'tool': 'claude'})
        self.assertEqual(result[0], 0)

    def test_other_platforms_do_not_invent_async_rewake(self):
        for tool in ('codex', 'antigravity'):
            with self.subTest(tool=tool):
                result, watcher = self.run_listener(None, tool=tool)
                self.assertEqual(result[0], 0)
                watcher.assert_not_called()

    def test_worker_does_not_arm_a_commander_listener(self):
        from v7_harness.coord import continuity
        watcher = mock.Mock()
        with mock.patch.dict(os.environ, {'UAOS_WORKER': 'local'}):
            result = continuity.run_hook(self.payload, 'claude', watch_fn=watcher)
        self.assertEqual(result[0], 0)
        watcher.assert_not_called()

    def test_installer_arms_native_listener_even_with_project_stop_gate(self):
        home = self.root / 'home'
        for folder in ('.claude', '.codex', '.gemini/config'):
            (home / folder).mkdir(parents=True)
        changes = global_install.plan(home, 'python', rules=False, enable_codex_hooks=False)
        settings = next(c for c in changes if c.path == home / '.claude/settings.json')
        hooks = json.loads(settings.new_text)['hooks']
        for event in ('SessionStart', 'Stop'):
            listeners = [h for group in hooks[event] for h in group.get('hooks', [])
                         if 'coord listen' in h.get('command', '')]
            self.assertEqual(len(listeners), 1, event)
            self.assertIs(listeners[0].get('asyncRewake'), True)
            self.assertNotEqual(listeners[0].get('async'), True)
        # Never remove the existing safety/next-card Stop gate to make the listener work.
        self.assertTrue(any('coord stop-gate' in h.get('command', '')
                            for g in hooks['Stop'] for h in g.get('hooks', [])))


if __name__ == '__main__':
    unittest.main()
