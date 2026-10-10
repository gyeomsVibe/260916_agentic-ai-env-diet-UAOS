"""A skipped live legacy PID is not a verified supervisor or a new entry."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from v7_harness import cli

class LegacyCompatibility(unittest.TestCase):
    def test_live_legacy_duplicate_skips_without_takeover(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            pid=root/'.work/sentinel/loop.pid'
            pid.parent.mkdir(parents=True)
            pid.write_text(str(os.getpid()),encoding='utf-8')
            original=pid.read_bytes()
            args=SimpleNamespace(project=directory,loop=True,log=str(root/'log'))
            output=io.StringIO()
            with contextlib.redirect_stdout(output),mock.patch.object(cli,'_cmd_coord_sentinel') as operation:
                code=cli.cmd_coord_sentinel(args)
            self.assertEqual(0,code)
            operation.assert_not_called()
            result=json.loads(output.getvalue())
            self.assertEqual('ALREADY_RUNNING',result['skipped'])
            self.assertIs(False,result['operator_verified'])
            self.assertEqual(original,pid.read_bytes())
            self.assertEqual(result,json.loads(Path(args.log).read_text()))

if __name__=='__main__': unittest.main()
