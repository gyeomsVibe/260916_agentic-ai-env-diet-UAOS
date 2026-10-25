"""Root-owned fixed gates for U229-C; no provider calls or production vote fixtures."""
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


class ConsensusAcceptance(unittest.TestCase):
    def setUp(self):
        self.api = importlib.import_module('v7_harness.coord.title_consensus')
        self.reader = importlib.import_module('v7_harness.coord.desk_title')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / '.coord').mkdir()
        self.path = self.root / '.coord/master_schedule.json'
        self.schedule = dict(phases=[dict(phase_id='U229', title='Desk and usage', state='ACTIVE', owner_tool='codex')])
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.schedule, ensure_ascii=False), encoding='utf-8')

    def vote(self, tool, topic='창구·호출기록 개선', expected=None):
        return self.api.cast_vote(self.root, tool, topic, expected or self.api.schedule_digest(self.root))

    def agree(self, topic='창구·호출기록 개선'):
        for tool in ('codex', 'claude', 'antigravity'):
            self.vote(tool, topic)

    def test_three_votes_feed_existing_all_tool_title_path_without_master_write(self):
        before = self.path.read_bytes()
        self.agree()
        self.assertEqual(self.reader._schedule_topic(self.root), '창구·호출기록 개선')
        for tool in ('codex', 'claude', 'antigravity'):
            entry = dict(title='[사용자 대화창구-261024-1]', tool=tool)
            self.assertEqual(self.reader._desired_title(self.root, entry, None), '[사용자 대화창구-261024-1] 창구·호출기록 개선')
        self.assertEqual(self.path.read_bytes(), before)

    def test_two_votes_duplicate_and_invalid_callers_cannot_create_quorum(self):
        self.vote('codex')
        self.vote('codex')
        self.vote('claude')
        self.assertIsNone(self.reader._schedule_topic(self.root))
        for tool, topic in [('unknown', 'valid'), ('antigravity', ' bad'), ('antigravity', 'x' * 17), ('antigravity', '[bad]')]:
            with self.assertRaises(ValueError):
                self.vote(tool, topic)
        self.assertIsNone(self.reader._schedule_topic(self.root))

    def test_state_owner_and_timestamp_changes_preserve_digest_and_topic(self):
        self.agree()
        original = self.api.schedule_digest(self.root)
        self.schedule['phases'][0].update(state='DONE', owner_tool='antigravity', updated_at='later', receipt='new receipt')
        self.save()
        self.assertEqual(self.api.schedule_digest(self.root), original)
        self.assertEqual(self.reader._schedule_topic(self.root), '창구·호출기록 개선')

    def test_topic_and_semantic_changes_require_real_fresh_quorum(self):
        self.agree()
        old_hash = self.api.schedule_digest(self.root)
        self.vote('codex', '새 일정')
        self.vote('claude', '새 일정')
        self.assertEqual(self.reader._schedule_topic(self.root), '창구·호출기록 개선')
        self.vote('antigravity', '새 일정')
        self.assertEqual(self.reader._schedule_topic(self.root), '새 일정')
        self.schedule['phases'][0]['title'] = 'Changed meaningful scope'
        self.save()
        self.assertNotEqual(self.api.schedule_digest(self.root), old_hash)
        self.assertIsNone(self.reader._schedule_topic(self.root))
        with self.assertRaises(ValueError):
            self.vote('codex', '새 일정', expected=old_hash)
        entry = dict(title='[사용자 대화창구-261024-1]', desired_title='[사용자 대화창구-261024-1] 새 일정')
        self.assertEqual(self.reader._desired_title(self.root, entry, None), entry['desired_title'])
        self.agree('새 일정')
        self.assertEqual(self.reader._schedule_topic(self.root), '새 일정')

    def test_three_synchronized_real_processes_do_not_lose_votes(self):
        source = str(Path(self.api.__file__).resolve().parents[2])
        expected = self.api.schedule_digest(self.root)
        code = (
            "import pathlib,sys,time;sys.path.insert(0,sys.argv[1]);"
            "from v7_harness.coord.title_consensus import cast_vote;"
            "p=pathlib.Path(sys.argv[2]);(p/(sys.argv[3]+'.ready')).write_text('ready');"
            "end=time.monotonic()+10\n"
            "while not (p/'GO').exists():\n"
            " if time.monotonic()>end: raise TimeoutError('parent barrier')\n"
            " time.sleep(.01)\n"
            "cast_vote(p,sys.argv[3],'parallel topic',sys.argv[4])\n"
        )
        children = [subprocess.Popen([sys.executable, '-c', code, source, str(self.root), tool, expected],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={**os.environ, 'PYTHONUTF8': '1'})
                    for tool in ('codex', 'claude', 'antigravity')]
        try:
            deadline = time.monotonic() + 10
            while len(list(self.root.glob('*.ready'))) < 3 and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(len(list(self.root.glob('*.ready'))), 3, 'All children must reach the barrier')
            self.assertTrue(all(p.poll() is None for p in children), 'All three OS processes must overlap')
            (self.root / 'GO').write_text('go', encoding='utf-8')
            for child in children:
                stdout, stderr = child.communicate(timeout=10)
                self.assertEqual(child.returncode, 0, (stdout + stderr).decode('utf-8', errors='replace'))
            self.assertEqual(self.reader._schedule_topic(self.root), 'parallel topic')
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=5)


if __name__ == '__main__':
    unittest.main()
