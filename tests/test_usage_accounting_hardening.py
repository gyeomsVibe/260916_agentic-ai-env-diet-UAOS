"""Additional source-discovered schema checks; original acceptance hash unchanged."""
import concurrent.futures
import json
from pathlib import Path
import tempfile
import unittest

from v7_harness.usage_accounting import collect, report


class HistoricalSchemaTests(unittest.TestCase):
    def test_codex_alternate_view_and_nonzero_write_cache(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            log = home/'.codex/sessions/a.jsonl'
            log.parent.mkdir(parents=True)
            usage = dict(input_tokens=100, cached_input_tokens=20, cache_write_input_tokens=10,
                         output_tokens=10, reasoning_output_tokens=3)
            rows = [dict(type='token_usage_record', timestamp='2026-10-23T00:00:00Z',
                         payload=dict(thread_token_usage=usage, usage=usage)),
                    dict(type='event_msg', timestamp='2026-10-23T00:00:01Z',
                         payload=dict(type='token_count', info=dict(total_token_usage=usage)))]
            log.write_text('\n'.join(json.dumps(r) for r in rows)+'\n', encoding='utf-8')
            db = home/'db.sqlite3'
            collect(home, db)
            total = report(db)['windows']['all_time']['providers']['codex']
            self.assertEqual(total['calls'], 1)
            self.assertEqual(total['uncached_input'], 70)
            self.assertEqual(total['cache_write'], 10)
            self.assertEqual(total['total_tokens'], 110)

    def test_legacy_olla_timestamps_and_failed_fake_pilot_excluded(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            log = home / '.cache/olla/usage.jsonl'
            log.parent.mkdir(parents=True)
            rows = [
                dict(ts='2026-10-23T01:00:00', event='ask', caller='codex', input_tokens=20, output_tokens=3),
                dict(ts='2026-10-23T02:00:00', event='pilot_local', status='FAKE', model='m', elapsed_s=1, input_tokens=999, output_tokens=999),
                dict(ts='2026-10-23T03:00:00', event='pilot_local', status='PASS', model='m', elapsed_s=1, input_tokens=4, output_tokens=5),
                dict(ts='2026-10-23T04:00:00', event='digest', cached=False, paid_tokens_if_read=999),
                dict(ts='2026-10-23T05:00:00', event='review', input_tokens=999, output_tokens=999),
            ]
            log.write_text('\n'.join(json.dumps(r) for r in rows)+'\n', encoding='utf-8')
            db = home/'db.sqlite3'
            collect(home, db)
            data = report(db, now='2026-10-24T00:00:00Z')
            total = data['windows']['all_time']['providers']['ollama']
            self.assertEqual(total['calls'], 2)
            self.assertEqual(total['total_tokens'], 32)
            self.assertEqual(data['sources']['naive_timestamps_kst_assumed'], 2)
            self.assertEqual(data['coverage']['ollama']['non_inference_rows'], 3)

    def test_parallel_process_cli_collect(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            log = home/'.claude/projects/a/s.jsonl'
            log.parent.mkdir(parents=True)
            row = dict(type='assistant', timestamp='2026-10-23T00:00:00Z', sessionId='s',
                       message=dict(id='m', model='claude', usage=dict(input_tokens=7, output_tokens=4)))
            log.write_text(json.dumps(row)+'\n', encoding='utf-8')
            db = home/'db.sqlite3'
            commands = [[sys.executable, '-m', 'v7_harness.usage_accounting', 'collect', '--home', str(home), '--db', str(db)]]*4
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda cmd: subprocess.run(cmd, capture_output=True, text=True, timeout=30), commands))
            self.assertTrue(all(r.returncode == 0 for r in results), [(r.returncode, r.stderr) for r in results])
            self.assertEqual(report(db)['windows']['all_time']['providers']['claude']['calls'], 1)


if __name__ == '__main__':
    unittest.main()
