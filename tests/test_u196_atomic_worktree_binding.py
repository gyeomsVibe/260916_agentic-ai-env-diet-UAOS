"""U196: real concurrent worktree reassignment must be refused at the claim lock."""
import contextlib, json, tempfile, threading, unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from v7_harness.coord import next_card as candidate
from v7_harness.coord import stream

class BindingReassignment(unittest.TestCase):
    def test_binding_changed_under_claim_lock_is_refused(self):
        for tool in ('codex', 'claude', 'antigravity'):
            with self.subTest(tool=tool), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); claims = root / '.coord/next/claims'; claims.mkdir(parents=True)
                other = root / 'different-checkout'; other.mkdir()
                schedule = root / '.coord/master_schedule.json'
                phase = dict(phase_id='U196', state='READY', owner_tool=tool,
                             owner_session='assigned', worktree=str(root), depends_on=[])
                schedule.write_text(json.dumps({'phases': [phase]}), encoding='utf-8')
                held, attempting = threading.Event(), threading.Event()
                original = stream._exclusive
                def writer():
                    with original(claims / '.lock'):
                        held.set()
                        if not attempting.wait(5):
                            raise TimeoutError('claimant never reached lock')
                        phase['worktree'] = str(other)
                        schedule.write_text(json.dumps({'phases': [phase]}), encoding='utf-8')
                @contextlib.contextmanager
                def observed(*args, **kwargs):
                    attempting.set()
                    with original(*args, **kwargs):
                        yield
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(writer)
                    self.assertTrue(held.wait(5))
                    with patch.object(stream, '_exclusive', observed):
                        got = candidate.next_step(root, tool, claim=True, session='assigned')
                    future.result(timeout=5)
                self.assertNotEqual('NEXT', got.get('state'), got)
                self.assertFalse((claims / 'U196.json').exists())

if __name__ == '__main__':
    unittest.main(verbosity=2)
