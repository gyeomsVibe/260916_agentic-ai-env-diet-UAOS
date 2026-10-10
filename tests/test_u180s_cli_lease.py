"""Frozen integration gate: CLI owns the lease across once/loop and exceptions."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
sys.path.insert(0,str(Path.cwd()))
from v7_harness import cli
from v7_harness.coord.sentinel_lease import lease, LeaseUnavailable

class CLILease(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.args=SimpleNamespace(project=str(self.root),loop=False,log=str(self.root/'report/log.jsonl'))

    def test_all_adapters_once_and_loop_callback_inside_lease(self):
        def operation(args):
            with self.assertRaises(LeaseUnavailable):
                with lease(self.root): self.fail('body is not protected')
            return 0
        for tool in ('codex','claude','antigravity'):
            for loop in (False,True):
                self.args.loop=loop
                with self.subTest(tool=tool,loop=loop),mock.patch.object(cli,'_cmd_coord_sentinel',side_effect=operation,create=True) as run:
                    self.assertEqual(0,cli.cmd_coord_sentinel(self.args))
                    run.assert_called_once_with(self.args)

    def test_busy_never_calls_operation_and_records_reason(self):
        output=io.StringIO()
        with lease(self.root),mock.patch.object(cli,'_cmd_coord_sentinel',create=True) as run,contextlib.redirect_stdout(output):
            self.assertEqual(3,cli.cmd_coord_sentinel(self.args))
            run.assert_not_called()
        record=json.loads(output.getvalue())
        self.assertFalse(record['ok'])
        self.assertEqual('LEASE_BUSY_OR_LOCK_ERROR',record['error'])
        self.assertEqual(record,json.loads(Path(self.args.log).read_text()))

    def test_body_exception_releases_lease(self):
        with mock.patch.object(cli,'_cmd_coord_sentinel',side_effect=RuntimeError('body'),create=True):
            with self.assertRaisesRegex(RuntimeError,'body'):
                cli.cmd_coord_sentinel(self.args)
        with lease(self.root): pass

if __name__=='__main__': unittest.main()
