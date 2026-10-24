"""Root-owned fixed U229 acceptance; implementation workers may not edit this file."""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import user_window as uw
from v7_harness.coord import desk_title as dt


class NativeTitle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = Path(self.tmp.name)
        (self.p / '.coord').mkdir()
        self.prefix = '[사용자 대화창구-261024-1]'
        for tool in ('codex', 'claude', 'antigravity'):
            uw.claim(self.p, tool, tool + '-desk', current=self.prefix)

    def event(self, tool='claude', **fields):
        return dict(hook_event_name='UserPromptSubmit', session_id=tool + '-desk', **fields)

    def agreed(self):
        phases = [{'phase_id': 'U229', 'title': 'Native desk repair', 'state': 'ACTIVE'}]
        digest = hashlib.sha256(json.dumps(phases, sort_keys=True, separators=(',', ':'),
                                          ensure_ascii=False).encode()).hexdigest()
        schedule = dict(phases=phases, desk_title=dict(topic='창구·호출기록 개선',
                        agreed_by=['codex', 'claude', 'antigravity'], schedule_sha256=digest))
        (self.p / '.coord/master_schedule.json').write_text(json.dumps(schedule), encoding='utf-8')
        return schedule

    def check(self, tool='claude', **fields):
        return dt.reconcile_title(self.p, tool, tool + '-desk', self.event(tool, **fields))

    def test_real_blocked_registry_uses_new_native_adapter_once(self):
        uw._entry_change(self.p, 'claude', 'claude-desk',
                         lambda e: e.update(emits=3, title_state='BLOCKED', converged=False))
        first = self.check(session_title='사용자 대상 대화창 설정')
        self.assertEqual(self.prefix, first['title'])
        self.assertNotIn('set_session_title', first.get('instruction', ''))
        for _ in range(8):
            self.check(session_title='old')
        entry = json.loads((self.p / '.coord/presence/user_windows.json').read_text(encoding='utf-8'))['claude'][0]
        self.assertLessEqual(entry['native_emits'], 3)

    def test_native_input_readback_converges_exact_session(self):
        self.assertEqual('CONVERGED', self.check(session_title=self.prefix)['state'])
        bad = self.event(session_title=self.prefix)
        bad['session_id'] = 'different-session'
        self.assertIsNone(dt.reconcile_title(self.p, 'claude', 'claude-desk', bad).get('title'))

    def test_schedule_suffix_changes_even_previously_converged(self):
        self.check(session_title=self.prefix)
        self.agreed()
        result = self.check(session_title=self.prefix)
        self.assertEqual(self.prefix + ' 창구·호출기록 개선', result['title'])
        self.assertEqual('CONVERGED', self.check(session_title=result['title'])['state'])

    def test_all_three_tools_share_the_same_approved_schedule_suffix(self):
        self.agreed()
        for tool in ('codex', 'claude', 'antigravity'):
            with self.subTest(tool=tool), mock.patch.object(uw, '_current_title', return_value='old'):
                self.assertEqual(self.prefix + ' 창구·호출기록 개선', self.check(tool)['title'])

    def test_stale_or_incomplete_consensus_never_changes_topic(self):
        schedule = self.agreed()
        schedule['phases'][0]['state'] = 'DONE'
        (self.p / '.coord/master_schedule.json').write_text(json.dumps(schedule), encoding='utf-8')
        self.assertEqual(self.prefix, self.check(session_title='old')['title'])
        schedule = self.agreed()
        schedule['desk_title']['agreed_by'] = ['claude']
        (self.p / '.coord/master_schedule.json').write_text(json.dumps(schedule), encoding='utf-8')
        self.assertEqual(self.prefix, self.check(session_title='old')['title'])

    def test_worker_non_desk_foreign_event_and_handed_off_fail_closed(self):
        with mock.patch.dict(os.environ, {'UAOS_WORKER': '1'}):
            self.assertIsNone(self.check().get('title'))
        self.assertIsNone(dt.reconcile_title(self.p, 'claude', 'nondesk', self.event()).get('title'))
        event = self.event()
        event['hook_event_name'] = 'PostToolUse'
        self.assertIsNone(dt.reconcile_title(self.p, 'claude', 'claude-desk', event).get('title'))
        uw.claim(self.p, 'claude', 'new-desk', current='[사용자 대화창구-261025-1]')
        self.assertIsNone(self.check().get('title'))


if __name__ == '__main__':
    unittest.main()
