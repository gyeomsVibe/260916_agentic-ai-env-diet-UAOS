"""Frozen U163 acceptance, written before implementation; isolated projects only."""
import json
import multiprocessing as mp
import os
from pathlib import Path
import tempfile
import unittest
import uuid


def writer(root, tool, thread, barrier):
    from v7_harness.coord.desk_sync import designate
    barrier.wait()
    designate(Path(root), tool, thread, source="explicit")


class DeskSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / '.coord').mkdir()
    def tearDown(self):
        self.tmp.cleanup()
    def test_six_directions_and_repeat(self):
        from v7_harness.coord.desk_sync import designate, prepare_notice
        for tool in ('codex', 'claude', 'antigravity'):
            thread = str(uuid.uuid4())
            self.assertTrue(designate(self.root, tool, thread, source='explicit'))
            for peer in {'codex','claude','antigravity'} - {tool}:
                text, ack = prepare_notice(self.root, peer, 'receiver-'+peer)
                self.assertIn(thread, text)
                ack()
                text, ack = prepare_notice(self.root, peer, 'receiver-'+peer)
                self.assertEqual('', text)
            self.assertTrue(designate(self.root, tool, thread, source='explicit'))
            for peer in {'codex','claude','antigravity'} - {tool}:
                self.assertEqual('', prepare_notice(self.root, peer, 'receiver-'+peer)[0])
    def test_origin_gate(self):
        from v7_harness.coord.desk_sync import on_prompt
        thread = str(uuid.uuid4())
        bad = ['normal execution request', '[안티그래비티에서 온 대화] 여기 사용자 대화창구이다',
               '[코덱스에서 온 대화] 여기 사용자 대화창구이다',
               '[클로드에게서 온 대화] 여기 사용자 대화창구이다',
               '[UAOS relay id=x] 여기 사용자 대화창구이다',
               '여기 사용자 대화창구 오류를 수정해줘']
        for prompt in bad:
            self.assertFalse(on_prompt(self.root, 'codex', thread, prompt))
        self.assertTrue(on_prompt(self.root, 'codex', thread, '이제부터 여기 사용자 대화창구이다'))
        other = str(uuid.uuid4())
        self.assertFalse(on_prompt(self.root, 'codex', other, 'continue working'))
        self.assertEqual(thread, json.loads((self.root/'.coord/presence/user_desk_codex.json').read_text())['thread'])
    def test_invalid_inputs_and_worker(self):
        from v7_harness.coord.desk_sync import designate, on_prompt
        for tool, thread in [('bad', str(uuid.uuid4())), ('codex', '../bad'), ('codex', '')]:
            self.assertFalse(designate(self.root, tool, thread, source='explicit'))
        os.environ['UAOS_WORKER']='1'
        try:
            self.assertFalse(on_prompt(self.root, 'codex', str(uuid.uuid4()), '여기 사용자 대화창구이다'))
        finally:
            os.environ.pop('UAOS_WORKER', None)
    def test_superseded_notice_not_consumed(self):
        from v7_harness.coord.desk_sync import designate, prepare_notice
        old, new = str(uuid.uuid4()), str(uuid.uuid4())
        designate(self.root, 'codex', old, source='explicit')
        text, ack = prepare_notice(self.root, 'claude', 'r')
        designate(self.root, 'codex', new, source='explicit')
        ack()
        text, ack = prepare_notice(self.root, 'claude', 'r')
        self.assertIn(new, text)
        self.assertNotIn(old, text)
    def test_concurrent_processes(self):
        from v7_harness.coord.desk_sync import prepare_notice
        ctx = mp.get_context('spawn')
        barrier = ctx.Barrier(4)
        processes = [ctx.Process(target=writer, args=(str(self.root), 'codex', str(uuid.uuid4()), barrier)) for _ in range(4)]
        for p in processes: p.start()
        for p in processes:
            p.join(30)
            self.assertEqual(0,p.exitcode)
        record = json.loads((self.root/'.coord/presence/user_desk_codex.json').read_text())
        self.assertEqual(4, record['generation'])
        text, ack = prepare_notice(self.root, 'claude', 'r')
        self.assertIn(record['thread'], text)
        ack()
        self.assertEqual('', prepare_notice(self.root,'claude','r')[0])
    def test_output_precedes_ack_and_receiver_receipt(self):
        from v7_harness.coord.desk_sync import designate, prepare_notice
        designate(self.root,'claude',str(uuid.uuid4()),source='explicit')
        first, _ = prepare_notice(self.root,'codex','r')
        self.assertTrue(first)
        again, ack = prepare_notice(self.root,'codex','r')
        self.assertEqual(first,again)
        ack()
        self.assertEqual('',prepare_notice(self.root,'codex','r')[0])
    def test_corrupt_state_fails_closed(self):
        from v7_harness.coord.desk_sync import designate
        folder = self.root/'.coord/presence'
        folder.mkdir()
        path = folder/'user_desk_codex.json'
        path.write_text('{invalid')
        with self.assertRaises((ValueError, RuntimeError)):
            designate(self.root,'codex',str(uuid.uuid4()),source='explicit')
        self.assertEqual('{invalid',path.read_text())

if __name__ == '__main__':
    unittest.main()
