"""Additional frozen counterexamples; original lifetime acceptance stays unchanged."""
import ctypes
import os
import sys
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).parent))
from tests.test_u180s_lifetime_lease import LifetimeLease, lease, LeaseUnavailable
from v7_harness.coord.sentinel_lease import pid_state

class Counterexamples(LifetimeLease):
    def test_trailing_corruption_cannot_hide_past_bounded_read(self):
        path=self.pid('12345'+' '*59+'CORRUPT')
        original=path.read_bytes()
        with mock.patch('v7_harness.coord.sentinel_lease.pid_state',return_value='DEAD'):
            with self.assertRaisesRegex(LeaseUnavailable,'LEGACY_UNKNOWN'):
                with lease(self.root): self.fail('trailing corruption admitted')
        self.assertEqual(original,path.read_bytes())

    def test_legacy_io_error_releases_os_lock(self):
        with mock.patch.object(Path,'open',side_effect=PermissionError('denied')):
            with self.assertRaisesRegex(LeaseUnavailable,'LEGACY_UNKNOWN'):
                with lease(self.root): self.fail('IO denial admitted')
        with lease(self.root): pass

    def test_lock_exception_still_closes_descriptor(self):
        with mock.patch('v7_harness.coord.sentinel_lease._try_lock',side_effect=OSError('lock failed')):
            with self.assertRaisesRegex(OSError,'lock failed'):
                with lease(self.root): self.fail('bad lock admitted')
        with lease(self.root): pass

    def test_windows_denied_probe_is_unknown(self):
        if os.name!='nt': self.skipTest('Windows-only probe')
        kernel=mock.MagicMock()
        kernel.OpenProcess.return_value=None
        with mock.patch.object(ctypes,'WinDLL',return_value=kernel),mock.patch.object(ctypes,'get_last_error',return_value=5):
            self.assertEqual('UNKNOWN',pid_state(12345))

if __name__=='__main__':
    import unittest
    unittest.main()
