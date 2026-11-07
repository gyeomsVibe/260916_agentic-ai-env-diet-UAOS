"""Frozen acceptance for local usage metadata accounting, USAGE-261023."""
import concurrent.futures
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from v7_harness.usage_accounting import collect, report, record_quota


class AccountingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.db = self.home / 'ledger.sqlite3'

    def log(self, name, rows, append=False):
        p = self.home / name
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open('a' if append else 'w', encoding='utf-8') as f:
            for row in rows:
                f.write((json.dumps(row) if isinstance(row, dict) else row) + '\n')
        return p

    def token(self, n, cached=0, output=10, reasoning=3, ts='2026-10-22T16:00:00Z', last=None):
        info = {'total_token_usage': {'input_tokens': n, 'cached_input_tokens': cached,
                'output_tokens': output, 'reasoning_output_tokens': reasoning}}
        if last is not None:
            info['last_token_usage'] = last
        return {'timestamp': ts, 'type': 'event_msg', 'payload': {'type': 'token_count', 'info': info}}

    def meta(self, sid='s1'):
        return {'type': 'session_meta', 'payload': {'id': sid}}

    def summary(self, **kwargs):
        return report(self.db, now='2026-10-23T12:00:00Z', **kwargs)

    def total(self, provider='codex', **kwargs):
        return self.summary(**kwargs)['windows']['all_time']['providers'][provider]

    def test_codex_cumulative_copies_forks_and_cache_subset(self):
        rows = [self.meta(), self.token(100, 40), self.token(100, 40),
                self.token(160, 60, 20, 7, '2026-10-22T16:02:00Z')]
        self.log('.codex/sessions/a.jsonl', rows)
        self.log('.codex/archived_sessions/copy.jsonl', rows)
        self.log('.codex/sessions/fork.jsonl', [self.meta('fork'), *rows[1:]])
        first = collect(self.home, self.db)
        self.assertEqual(first['files_parsed'], 3)
        total = self.total()
        self.assertEqual(total['calls'], 2)
        self.assertEqual(total['uncached_input'], 100)
        self.assertEqual(total['cache_read'], 60)
        self.assertEqual(total['cache_write'], 0)
        self.assertEqual(total['output'], 20)
        self.assertEqual(total['reasoning'], 7)
        self.assertEqual(total['total_tokens'], 180)
        self.assertEqual(collect(self.home, self.db)['files_parsed'], 0)

    def test_reset_missing_optional_fields_and_invalid_counter(self):
        self.log('.codex/sessions/a.jsonl', [self.meta(), self.token(100),
            self.token(20, output=2, reasoning=0, ts='2026-10-22T16:01:00Z'),
            self.token(25, output=3, reasoning=0, ts='2026-10-22T16:02:00Z'),
            self.token(-3, output=4, reasoning=0, ts='2026-10-22T16:03:00Z')])
        collect(self.home, self.db)
        self.assertEqual(self.total()['uncached_input'], 105)
        self.assertGreaterEqual(self.summary()['sources']['errors'], 2)

    def test_claude_repeated_blocks_late_update_and_separate_provider(self):
        def row(out):
            return {'type': 'assistant', 'sessionId': 'c1', 'timestamp': '2026-10-22T16:00:00Z',
                    'message': {'id': 'm1', 'model': 'claude-test', 'content': 'PRIVATE-SENTINEL',
                    'usage': {'input_tokens': 100, 'cache_read_input_tokens': 50,
                              'cache_creation_input_tokens': 20, 'output_tokens': out}}}
        self.log('.claude/projects/proj/a.jsonl', [row(2), row(4)])
        collect(self.home, self.db)
        self.assertEqual(self.total('claude')['total_tokens'], 174)
        self.log('.claude/projects/proj/a.jsonl', [row(9)], append=True)
        inc = collect(self.home, self.db)
        self.assertEqual(inc['files_incremental'], 1)
        self.assertEqual(self.total('claude')['calls'], 1)
        self.assertEqual(self.total('claude')['output'], 9)
        self.assertEqual(self.total('codex')['calls'], 0)
        self.assertNotIn('PRIVATE-SENTINEL', json.dumps(self.summary()))
        self.assertNotIn(b'PRIVATE-SENTINEL', self.db.read_bytes())

    def test_corrupt_rows_missing_opaque_provider_and_no_credentials(self):
        self.log('.codex/sessions/a.jsonl', ['{broken', self.meta(), self.token(10)])
        self.log('.claude/sessions/credentials.key', ['PRIVATE-CREDENTIAL'])
        self.log('.gemini/antigravity/conversations/opaque.pb', ['PRIVATE-OPAQUE'])
        collect(self.home, self.db)
        result = self.summary()
        self.assertEqual(result['sources']['malformed_rows'], 1)
        self.assertEqual(result['coverage']['antigravity']['status'], 'UNKNOWN')
        self.assertEqual(result['coverage']['antigravity']['opaque_files'], 1)
        self.assertIsNone(result['windows']['all_time']['providers']['antigravity']['total_tokens'])
        self.assertIsNone(result['windows']['all_time']['providers']['claude']['total_tokens'])
        self.assertNotIn(b'PRIVATE-CREDENTIAL', self.db.read_bytes())

    def test_kst_day_utc_window_and_date_range(self):
        self.log('.codex/sessions/a.jsonl', [self.meta(), self.token(10, ts='2026-10-22T16:00:00Z')])
        collect(self.home, self.db)
        kst = self.summary(timezone_name='Asia/Seoul')
        self.assertEqual(kst['windows']['all_time']['daily'][0]['day'], '2026-10-23')
        utc = self.summary(timezone_name='UTC')
        self.assertEqual(utc['windows']['all_time']['daily'][0]['day'], '2026-10-22')
        self.assertEqual(self.total(start='2026-10-24')['calls'], 0)
        self.assertEqual(kst['windows']['last7']['providers']['codex']['calls'], 1)

    def test_parallel_collect_and_rewrite(self):
        self.log('.codex/sessions/a.jsonl', [self.meta(), self.token(10)])
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: collect(self.home, self.db), range(4)))
        self.assertEqual(self.total()['calls'], 1)
        self.log('.codex/sessions/a.jsonl', [self.meta(), self.token(50)])
        collect(self.home, self.db)
        self.assertEqual(self.total()['uncached_input'], 50)

    def test_ollama_inference_only_and_unknown_values(self):
        self.log('.cache/olla/usage.jsonl', [
            {'ts': '2026-10-23T00:00:00Z', 'event': 'draft', 'caller': 'codex',
             'input_tokens': 11, 'output_tokens': 7},
            {'ts': '2026-10-23T00:01:00Z', 'event': 'cache_hit', 'input_tokens': 900},
            {'ts': '2026-10-23T00:02:00Z', 'event': 'hook', 'input_tokens': 900},
            {'ts': '2026-10-23T00:03:00Z', 'event': 'draft', 'caller': 'claude'}])
        collect(self.home, self.db)
        total = self.total('ollama')
        self.assertEqual(total['calls'], 1)
        self.assertEqual(total['total_tokens'], 18)
        self.assertEqual(self.summary()['coverage']['ollama']['non_inference_rows'], 3)

    def test_partial_row_resume_and_quota_validation(self):
        p = self.log('.codex/sessions/a.jsonl', [self.meta()])
        partial = json.dumps(self.token(10))
        with p.open('a', encoding='utf-8') as f:
            f.write(partial[:20])
        collect(self.home, self.db)
        self.assertEqual(self.total()['calls'], 0)
        with p.open('a', encoding='utf-8') as f:
            f.write(partial[20:] + '\n')
        collect(self.home, self.db)
        self.assertEqual(self.total()['calls'], 1)
        record_quota(self.db, provider='claude', used_percent=100, window_minutes=10080,
                     observed_at='2026-10-23T00:00:00Z', origin='user_report')
        self.assertEqual(self.summary()['quota_snapshots'][0]['origin'], 'user_report')
        with self.assertRaises(ValueError):
            record_quota(self.db, provider='claude', used_percent=101)
        with self.assertRaises(ValueError):
            record_quota(self.db, provider='claude', used_percent=True)


if __name__ == '__main__':
    unittest.main()
