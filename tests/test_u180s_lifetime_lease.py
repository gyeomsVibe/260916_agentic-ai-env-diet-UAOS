"""Frozen isolated gate: lifetime lease, legacy safety, real process crash recovery."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path.cwd()))
from v7_harness.coord.sentinel_lease import lease, LeaseUnavailable

class LifetimeLease(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def pid(self,value):
        path=self.root/'.work/sentinel/loop.pid'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(value,encoding='utf-8')
        return path

    def test_normal_and_exception_release_stable_lock(self):
        with lease(self.root):
            self.assertTrue((self.root/'.work/sentinel/loop.lock').is_file())
            with self.assertRaises(LeaseUnavailable):
                with lease(self.root): pass
        with self.assertRaisesRegex(RuntimeError,'operation'):
            with lease(self.root): raise RuntimeError('operation')
        with lease(self.root): pass

    def test_live_legacy_preserved_without_any_heartbeat(self):
        # Amended 2026-10-10 (.work/cards/U180S_rework_claude.md): the first fixture dated the file at epoch 1, older
        # than the process that wrote it, which no real owner can produce and which is exactly a reused pid. A real
        # stalled owner wrote the file once, after it started, and never again: no heartbeat age may free its lease.
        import time
        child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        written=time.time()  # after the child exists, as an owner's first write is
        path=self.pid(str(child.pid))
        os.utime(path,(written,written))
        with self.assertRaisesRegex(LeaseUnavailable,'LEGACY_ALIVE'):
            with lease(self.root): self.fail('entered')
        self.assertEqual(str(child.pid),path.read_text())

    def test_corrupt_legacy_and_probe_unknown_fail_closed(self):
        path=self.pid('corrupt')
        with self.assertRaisesRegex(LeaseUnavailable,'LEGACY_UNKNOWN'):
            with lease(self.root): self.fail('entered')
        path.write_text('12345')
        with mock.patch('v7_harness.coord.sentinel_lease.pid_state',return_value='UNKNOWN'):
            with self.assertRaisesRegex(LeaseUnavailable,'LEGACY_UNKNOWN'):
                with lease(self.root): self.fail('entered')
        self.assertEqual('12345',path.read_text())

    def test_verified_dead_legacy_not_deleted(self):
        path=self.pid('12345')
        with mock.patch('v7_harness.coord.sentinel_lease.pid_state',return_value='DEAD'):
            with lease(self.root): pass
        self.assertEqual('12345',path.read_text())

    def test_real_child_hold_once_loop_and_crash_release(self):
        script='''import os,sys,time
from pathlib import Path
from v7_harness.coord.sentinel_lease import lease
root=Path(sys.argv[1])
with lease(root):
 (root/'ready').write_text('held')
 while not (root/'crash').exists(): time.sleep(.01)
 os._exit(0)
'''
        child=subprocess.Popen([sys.executable,'-c',script,str(self.root)])
        self.addCleanup(lambda: child.kill() if child.poll() is None else None)
        import time
        deadline=time.monotonic()+10
        while not (self.root/'ready').exists():
            if child.poll() is not None or time.monotonic()>deadline: self.fail('child failed to hold')
            time.sleep(.01)
        for caller in ('once','loop','boot','startup'):
            with self.subTest(caller=caller),self.assertRaises(LeaseUnavailable):
                with lease(self.root): self.fail('double entry')
        (self.root/'crash').write_text('1')
        self.assertEqual(0,child.wait(timeout=10))
        with lease(self.root): pass

if __name__=='__main__': unittest.main()
