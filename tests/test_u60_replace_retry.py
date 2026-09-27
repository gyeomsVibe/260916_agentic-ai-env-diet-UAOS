"""U60 frozen acceptance (written by Claude): a Windows replace refusal does not kill a watch or lose a heartbeat.

Seen 2026-09-28: `coord watch` exited with PermissionError [WinError 5] from os.replace on claude.watch.json while
another process had the file open.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import presence
from v7_harness.coord.mailbox import Mailbox
from v7_harness.coord.presence import mark, read
from v7_harness.coord.watch import watch, watch_file

REAL_REPLACE = os.replace


def refuse(times):
    calls = {"n": 0}

    def fake(src, dst):
        # os.replace is patched module-wide; only desk files are refused so the mailbox still publishes.
        if Path(dst).parent.name != "presence":
            return REAL_REPLACE(src, dst)
        calls["n"] += 1
        if times is None or calls["n"] <= times:
            raise PermissionError(5, "Access is denied")
        return REAL_REPLACE(src, dst)

    return fake, calls


class ReplaceRetryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        (self.project / ".coord").mkdir()
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def leftovers(self):
        return sorted(p.name for p in (self.project / ".coord" / "presence").glob("*.tmp"))

    def test_heartbeat_waits_out_a_short_refusal(self):
        fake, calls = refuse(3)
        with mock.patch.object(presence.os, "replace", fake), mock.patch.object(presence, "REPLACE_WAIT_S", 0):
            mark(self.project, "claude", "ACTIVE", ttl_s=3600)
        self.assertEqual(4, calls["n"])
        self.assertEqual("ACTIVE", read(self.project, "claude")["state"])
        self.assertEqual([], self.leftovers())

    def test_heartbeat_that_never_lands_raises_and_leaves_no_temp_file(self):
        fake, _ = refuse(None)
        with mock.patch.object(presence.os, "replace", fake), mock.patch.object(presence, "REPLACE_WAIT_S", 0):
            with self.assertRaises(PermissionError):
                mark(self.project, "claude", "ACTIVE", ttl_s=3600)
        self.assertEqual([], self.leftovers())

    def test_watch_survives_a_refused_beat_and_still_finds_the_letter(self):
        (self.project / ".coord" / "mailbox").mkdir(parents=True)

        def sleep(_s):
            Mailbox(self.project / ".coord" / "mailbox").publish(
                "m1", {"kind": "NOTE", "actor": "codex", "requested_target": "claude", "message": "x"})

        fake, _ = refuse(None)
        with mock.patch.object(presence.os, "replace", fake), mock.patch.object(presence, "REPLACE_WAIT_S", 0):
            found = watch(self.project, ("claude",), timeout_s=60, interval_s=1, sleep=sleep)
        self.assertIsNotNone(found)
        self.assertEqual("m1", found["id"])
        self.assertFalse(watch_file(self.project, "claude").exists())
        self.assertEqual([], self.leftovers())


if __name__ == "__main__":
    unittest.main()
