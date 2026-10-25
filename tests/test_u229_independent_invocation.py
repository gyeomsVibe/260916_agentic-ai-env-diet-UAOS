"""Root-owned invocation journal gates. No implementation worker may edit."""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from v7_harness import invocation as inv


class Journal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / 'usage.sqlite3'

    def begin(self, caller='codex'):
        return inv.start_attempt(caller=caller, project=str(self.root), work_id='U229',
                                 purpose='bounded extraction', model='claude-haiku-5-5',
                                 input_sha256=hashlib.sha256(b'private prompt never stored').hexdigest(),
                                 db=self.db)

    def rows(self):
        with closing(sqlite3.connect(self.db)) as con:
            con.row_factory = sqlite3.Row
            return [dict(r) for r in con.execute('SELECT * FROM attempts')]

    def test_all_callers_start_and_terminal_are_committed(self):
        for caller in ('codex', 'claude', 'antigravity'):
            ident = self.begin(caller)
            row = next(r for r in self.rows() if r['id'] == ident)
            self.assertEqual(caller, row['caller'])
            inv.finish_attempt(ident, outcome='TIMEOUT', error_class='TimeoutExpired', db=self.db)
        rows = self.rows()
        self.assertEqual(3, len(rows))
        self.assertTrue(all(r['outcome'] == 'TIMEOUT' for r in rows))
        self.assertTrue(all(r['input_tokens'] is None and r['output_tokens'] is None for r in rows))

    def test_unknown_usage_and_raw_prompt_are_not_fabricated(self):
        ident = self.begin()
        inv.finish_attempt(ident, outcome='SUCCESS', input_tokens=9, output_tokens=3, db=self.db)
        blob = json.dumps(self.rows())
        self.assertNotIn('private prompt never stored', blob)
        self.assertIn('claude-haiku-5-5', blob)
        self.assertEqual(9, self.rows()[0]['input_tokens'])
        self.assertIn('UNVERIFIED', blob)

    def test_invalid_identity_and_unwritable_journal_fail_before_provider(self):
        with self.assertRaises((ValueError, TypeError)):
            self.begin('foreign')
        directory = self.root / 'directory'
        directory.mkdir()
        with self.assertRaises(Exception):
            inv.start_attempt(caller='codex', project=str(self.root), work_id='U229', purpose='draft',
                              model='qwen2.5-coder:7b', input_sha256='x' * 64, db=directory)

    def test_four_actual_processes_do_not_drop_attempts(self):
        code = '''import sys
from v7_harness import invocation as i
for n in range(12):
 x=i.start_attempt(caller='codex',project=sys.argv[2],work_id='U229',purpose='parallel writer',
 model='claude-haiku-5-5',input_sha256='a'*64,db=sys.argv[1])
 i.finish_attempt(x,outcome='SUCCESS',input_tokens=1,output_tokens=2,db=sys.argv[1])
'''
        children = [subprocess.Popen([sys.executable, '-B', '-c', code, str(self.db), str(self.root)],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(4)]
        results = []
        for child in children:
            out, err = child.communicate(timeout=30)
            results.append((child.returncode, err.decode(errors='replace')))
        self.assertTrue(all(code == 0 for code, _ in results), str(results))
        rows = self.rows()
        self.assertEqual(48, len(rows))
        self.assertEqual(48, len({r['id'] for r in rows}))
        self.assertTrue(all(r['outcome'] == 'SUCCESS' for r in rows))

    def test_review_is_evidence_only_and_repeatable(self):
        ident = self.begin()
        inv.finish_attempt(ident, outcome='TIMEOUT', db=self.db)
        target = self.root / 'proposal.json'
        first = inv.review(db=self.db, output=target)
        second = inv.review(db=self.db, output=target)
        self.assertEqual(first['fingerprint'], second['fingerprint'])
        self.assertEqual('UNMEASURED', first['quota_saving'])
        self.assertFalse(first['auto_adopt'])
        self.assertTrue(target.is_file())


if __name__ == '__main__':
    unittest.main()
