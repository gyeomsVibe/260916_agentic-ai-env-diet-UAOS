"""Root-discovered native metadata regression; frozen contract is untouched."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import sqlite3

from v7_harness.usage_accounting import collect, report


class NativeMetadataTests(unittest.TestCase):
    def test_malformed_payload_does_not_abort_and_synthetic_is_not_inference(self):
        with tempfile.TemporaryDirectory() as d:
            home=Path(d);log=home/'.codex/sessions/a.jsonl';log.parent.mkdir(parents=True)
            rows=[dict(type='event_msg',payload=['unsupported']),
                  dict(type='event_msg',payload=None),
                  dict(type='token_usage_record',timestamp='2026-10-22T01:00:00Z',payload=dict(
                    response_id='valid',usage=dict(input_tokens=4,output_tokens=2)))]
            log.write_text('\n'.join(json.dumps(r) for r in rows)+'\n',encoding='utf-8')
            claude=home/'.claude/projects/p/a.jsonl';claude.parent.mkdir(parents=True)
            rows=[dict(type='assistant',timestamp='2026-10-22T01:00:00Z',message=dict(
                id=model,model=model,usage=dict(input_tokens=0,output_tokens=0)))
                for model in ('<synthetic>','real-zero-model')]
            claude.write_text('\n'.join(json.dumps(r) for r in rows)+'\n',encoding='utf-8')
            db=home/'db.sqlite3';collect(home,db);data=report(db)
            totals=data['windows']['all_time']['providers']
            self.assertEqual(totals['codex']['total_tokens'],6)
            self.assertEqual(data['sources']['malformed_rows'],2)
            self.assertEqual(totals['claude']['calls'],1)
            self.assertEqual(data['coverage']['claude']['non_inference_rows'],1)

    def test_old_parser_revision_forces_rebuild_without_log_changes(self):
        with tempfile.TemporaryDirectory() as d:
            home=Path(d);log=home/'.codex/sessions/a.jsonl';log.parent.mkdir(parents=True)
            row=dict(type='token_usage_record',timestamp='2026-10-22T01:00:00Z',payload=dict(
                response_id='one',usage=dict(input_tokens=4,output_tokens=2)))
            log.write_text(json.dumps(row)+'\n',encoding='utf-8')
            db=home/'db.sqlite3';collect(home,db)
            with sqlite3.connect(db) as con:
                con.execute("UPDATE sources SET state='{}'")
                con.execute('UPDATE contributions SET uncached_input=999999')
            con.close()
            result=collect(home,db)
            self.assertEqual(result['files_parsed'],1)
            self.assertEqual(result['files_incremental'],0)
            self.assertEqual(report(db)['windows']['all_time']['providers']['codex']['total_tokens'],6)

    def test_native_response_and_legacy_counter_have_independent_baselines(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            log = home/'.codex/sessions/a.jsonl'
            log.parent.mkdir(parents=True)
            rows = []
            # Actual counter relationship: global legacy cumulative retains 61M,
            # while native thread cumulative begins again at 143k in same source.
            for index, (inp, cache, out, reason) in enumerate([
                    (143246,3968,374,170), (144534,143232,153,109), (145611,144512,59,26)]):
                use = dict(input_tokens=inp,cached_input_tokens=cache,
                           cache_write_input_tokens=0,output_tokens=out,reasoning_output_tokens=reason)
                rows.append(dict(type='token_usage_record', timestamp=f'2026-10-22T01:40:{index*10:02d}Z',
                    payload=dict(response_id=f'r{index}', session_id='s', usage=use,
                                 thread_token_usage=dict(input_tokens=143246+index*144000))))
                total = dict(input_tokens=61213974+sum(x[0] for x in [(144534,143232,153,109),(145611,144512,59,26)][:index]),
                    cached_input_tokens=58744320+sum(x[1] for x in [(144534,143232,153,109),(145611,144512,59,26)][:index]),
                    output_tokens=198470+sum(x[2] for x in [(144534,143232,153,109),(145611,144512,59,26)][:index]),
                    reasoning_output_tokens=53437+sum(x[3] for x in [(144534,143232,153,109),(145611,144512,59,26)][:index]))
                rows.append(dict(type='event_msg', timestamp=f'2026-10-22T01:40:{index*10+1:02d}Z',
                    payload=dict(type='token_count', info=dict(total_token_usage=total,last_token_usage=use))))
            log.write_text('\n'.join(json.dumps(r) for r in rows)+'\n',encoding='utf-8')
            # Copy/fork repeats the same response identities and must not double count.
            copy=home/'.codex/archived_sessions/copy.jsonl'
            copy.parent.mkdir(parents=True)
            copy.write_bytes(log.read_bytes())
            db=home/'db.sqlite3'
            collect(home,db)
            result=report(db)['windows']['all_time']['providers']['codex']
            self.assertEqual(result['calls'],3)
            self.assertEqual(result['total_tokens'],143246+374+144534+153+145611+59)
            self.assertEqual(result['reasoning'],305)

    def test_native_response_ids_distinguish_same_timestamp_same_counters(self):
        with tempfile.TemporaryDirectory() as d:
            home=Path(d);log=home/'.codex/sessions/a.jsonl';log.parent.mkdir(parents=True)
            rows=[dict(type='token_usage_record',timestamp='2026-10-22T01:00:00Z',payload=dict(
                response_id=rid,session_id=rid,usage=dict(input_tokens=4,output_tokens=2))) for rid in ('one','two')]
            log.write_text('\n'.join(json.dumps(r) for r in rows)+'\n',encoding='utf-8')
            db=home/'db.sqlite3';collect(home,db)
            self.assertEqual(report(db)['windows']['all_time']['providers']['codex']['calls'],2)

    def test_native_quota_snapshot_allowlist_changed_only_and_cli_dispatch(self):
        with tempfile.TemporaryDirectory() as d:
            home=Path(d);log=home/'.codex/sessions/a.jsonl';log.parent.mkdir(parents=True)
            rows=[]
            for n,percent in enumerate((95.0,95.0,100.0)):
                rows.append(dict(type='event_msg',timestamp=f'2026-10-22T01:00:0{n}Z',
                    payload=dict(type='token_count',info=None,rate_limits=dict(
                        private_text='PRIVATE-QUOTA-SENTINEL',primary=dict(used_percent=percent,
                        window_minutes=300,resets_at=1792634400,secret='PRIVATE-QUOTA-SENTINEL')))))
            log.write_text('\n'.join(json.dumps(r) for r in rows)+'\n',encoding='utf-8')
            db=home/'db.sqlite3'
            cmd=[sys.executable,'-m','v7_harness.cli','usage','collect','--home',str(home),'--db',str(db)]
            run=subprocess.run(cmd,capture_output=True,text=True,timeout=30)
            self.assertEqual(run.returncode,0,run.stderr)
            collect(home,db)
            data=report(db)
            self.assertEqual(len(data['quota_snapshots']),2)
            self.assertEqual(data['quota_snapshots'][0]['origin'],'native_transcript')
            self.assertEqual(data['quota_snapshots'][0]['observed_at'],'2026-10-22T01:00:00Z')
            self.assertEqual(data['quota_snapshots'][-1]['used_percent'],100.0)
            self.assertIsNone(data['windows']['all_time']['providers']['antigravity']['calls'])
            self.assertIsNone(data['windows']['all_time']['providers']['antigravity']['sessions'])
            self.assertNotIn(b'PRIVATE-QUOTA-SENTINEL',db.read_bytes())


if __name__=='__main__':
    unittest.main()
