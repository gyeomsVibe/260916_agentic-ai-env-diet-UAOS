"""U53-F1: a delete-pending Claude turn lock (Windows PermissionError on O_EXCL) is waited out, not raised.

Seen 1 of 30 real eight-process runs of test_u48_deliver_d1 on 0633dd1: `_claude_turn` caught only FileExistsError, so
the worker process died with PermissionError and its letter was never dispatched.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from v7_harness.coord.deliver import deliver


class _Runner:
    def __call__(self, argv, **kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps({"type": "result", "result": "ok"}), stderr="")


class TurnLockDeletePendingTests(unittest.TestCase):
    def test_permission_error_on_turn_lock_is_retried(self) -> None:
        real_open = os.open
        raised: list[str] = []

        def flaky_open(path, flags, *args):
            if str(path).endswith("claude-session.turn.lock") and not raised:
                raised.append(str(path))
                raise PermissionError(13, "delete pending", str(path))
            return real_open(path, flags, *args)

        with tempfile.TemporaryDirectory() as d:
            project = Path(d)
            (project / ".coord" / "mailbox").mkdir(parents=True)
            with patch("v7_harness.coord.deliver.shutil.which", return_value="claude"), \
                    patch("v7_harness.coord.deliver.os.open", flaky_open):
                result = deliver(project, message="u53 f1", actor="codex", target="claude", runner=_Runner())
        self.assertEqual(1, len(raised), "the injection point was never reached")
        self.assertEqual("DISPATCHED", result.reason)


if __name__ == "__main__":
    unittest.main()
