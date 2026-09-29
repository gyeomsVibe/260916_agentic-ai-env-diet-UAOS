"""U83: the guard recovery lock is never stolen by age (Codex REJECT of U49-G1R, 2026-09-29).

Counterexample from the verdict: a holder paused beyond RECOVER_STALE_S (60 s) had its `.recover` file renamed away by
the next caller, which then created its own; on resume the first holder mutated the guard concurrently and its
unconditional `finally` unlinked the new holder's lock. The lock is now an OS lock, released by the OS on exit or crash,
with no age-based stealing and no unlink. These tests hold the lock, age everything far past every threshold, and
check that no other caller takes, renames or deletes it; and that a crashed holder's lock frees itself.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from v7_harness.coord import deliver as deliver_module
from v7_harness.coord.mailbox import Mailbox

REPO = Path(__file__).resolve().parents[1]
# One hour: far past the old 60 s steal threshold and the 300 s guard threshold, so only the lock itself can refuse.
AGE_S = 3600


def _age(path: Path, seconds: float) -> None:
    old = time.time() - seconds
    os.utime(path, (old, old))


class RecoverLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / ".coord" / "mailbox").mkdir(parents=True)
        self.box = Mailbox(root / ".coord" / "mailbox")
        self.guards = root / "guards"
        self.guards.mkdir()
        self.guard = self.guards / "m1.lock"
        self.guard.write_text(json.dumps({"message_id": "m1", "owner": "crashed"}), encoding="utf-8")
        _age(self.guard, AGE_S)

    def test_paused_holder_keeps_the_lock_however_old(self) -> None:
        with deliver_module._recover_lock(self.guard, 0.0) as held:
            self.assertTrue(held)
            _age(self.guard.with_name(self.guard.name + ".recover"), AGE_S)  # the holder looks paused for an hour
            for _ in range(3):  # the old code stole on the first call and took over on the second
                self.assertIsNone(deliver_module._acquire_guard(self.guard, self.box, "m1", "d" * 64))
            self.assertEqual([], list(self.guards.glob("*.stale-*")), "the aged guard or the held lock was renamed")
            self.assertTrue(self.guard.is_file())
            self.assertTrue((self.guards / "m1.lock.recover").is_file(), "the held lock file was removed")

    def test_release_while_another_holds_the_lock_leaves_the_guard(self) -> None:
        self.guard.write_text(json.dumps({"message_id": "m1", "owner": "me"}), encoding="utf-8")
        with deliver_module._recover_lock(self.guard, 0.0) as held, \
                patch.object(deliver_module, "RELEASE_WAIT_S", 0.2):
            self.assertTrue(held)
            _age(self.guard.with_name(self.guard.name + ".recover"), AGE_S)
            deliver_module._release_guard(self.guard, "me")
            self.assertTrue(self.guard.is_file(), "release mutated the guard without the lock")
            self.assertTrue((self.guards / "m1.lock.recover").is_file(), "release removed another holder's lock")
        deliver_module._release_guard(self.guard, "me")  # once the holder is done, release proceeds
        self.assertFalse(self.guard.exists())

    def test_crashed_holder_lock_is_freed_by_the_os(self) -> None:
        holder = (
            "import sys, os\n"
            "from pathlib import Path\n"
            "from v7_harness.coord import deliver\n"
            "cm = deliver._recover_lock(Path(sys.argv[1]), 0.0)\n"
            "assert cm.__enter__() is True\n"
            "os._exit(0)  # dies holding the lock: no unlock, no cleanup\n"
        )
        done = subprocess.run([sys.executable, "-c", holder, str(self.guard)], cwd=REPO, capture_output=True,
                              text=True, timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)
        fd = deliver_module._acquire_guard(self.guard, self.box, "m1", "d" * 64)
        self.assertIsNotNone(fd, "a crashed holder's lock must not block recovery")
        os.close(fd)
        self.assertEqual(1, len(list(self.guards.glob("m1.lock.stale-*"))))

    def test_lock_is_exclusive_within_one_process(self) -> None:
        with deliver_module._recover_lock(self.guard, 0.0) as first:
            with deliver_module._recover_lock(self.guard, 0.1) as second:
                self.assertEqual((True, False), (first, second))
        with deliver_module._recover_lock(self.guard, 0.0) as again:
            self.assertTrue(again, "the lock was not released on exit")


if __name__ == "__main__":
    unittest.main()
