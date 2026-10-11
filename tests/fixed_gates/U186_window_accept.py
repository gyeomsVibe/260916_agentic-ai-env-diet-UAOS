"""Judge-owned fixed acceptance: Windows delete-pending and three-tool claims."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

source = Path(sys.argv.pop(1)).resolve()
sys.path.insert(0, str(source))
from v7_harness.coord import user_window as uw, stream


class WindowLock(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / '.coord').mkdir()

    def test_delete_pending_open_retries_without_losing_claim(self):
        original = os.open
        denied = []
        def opening(path, flags, *args, **kwargs):
            if Path(path).name == 'user_windows.lock' and not denied:
                denied.append(True)
                raise PermissionError(13, 'delete pending')
            return original(path, flags, *args, **kwargs)
        with patch.object(os, 'open', opening):
            got = uw.claim(self.root, 'codex', 'fresh')
        self.assertTrue(got['new'])
        self.assertEqual([True], denied)

    def test_abandoned_lock_file_is_not_an_active_owner(self):
        folder = self.root / '.coord/presence'
        folder.mkdir(parents=True)
        (folder / 'user_windows.lock').write_bytes(b'')
        with patch.object(uw, 'LOCK_WAIT_S', .03):
            self.assertTrue(uw.claim(self.root, 'claude', 'fresh')['new'])

    def test_persistent_access_denial_does_not_grant_ownership(self):
        original = os.open
        def opening(path, flags, *args, **kwargs):
            if Path(path).name == 'user_windows.lock':
                raise PermissionError(13, 'denied')
            return original(path, flags, *args, **kwargs)
        with patch.object(os, 'open', opening), patch.object(stream, 'LOCK_TIMEOUT_S', .03):
            with self.assertRaises((PermissionError, stream.StreamBusy, TimeoutError)):
                uw.claim(self.root, 'antigravity', 'fresh')
        self.assertFalse((self.root / '.coord/presence/user_windows.json').exists())

    def test_three_tools_real_parallel_processes_get_unique_numbers(self):
        script = "import sys,json;sys.path.insert(0,sys.argv[1]);from pathlib import Path;from v7_harness.coord.user_window import claim;print(json.dumps(claim(Path(sys.argv[2]),sys.argv[3],sys.argv[4])))"
        children = [(tool, subprocess.Popen([sys.executable, '-c', script, str(source), str(self.root), tool, str(i)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
                    for tool in ('codex', 'claude', 'antigravity') for i in range(4)]
        results = {}
        try:
            for tool, child in children:
                out, err = child.communicate(timeout=15)
                self.assertEqual(0, child.returncode, err)
                results.setdefault(tool, []).append(json.loads(out)['title'])
            for tool in ('codex', 'claude', 'antigravity'):
                self.assertEqual(4, len(set(results[tool])), results)
        finally:
            for _, child in children:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
