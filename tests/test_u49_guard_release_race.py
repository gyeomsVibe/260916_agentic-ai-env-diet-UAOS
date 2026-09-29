"""U49-G1R: guard release and stale-guard recovery cannot interleave (Codex REJECT of U49-G1, 2026-09-27).

Counterexample from the verdict: a recovery that lands after the releasing dispatcher decided to remove the guard but
before the unlink took the guard over, and the unlink then deleted the new holder's guard. The test injects a real
recovery (`_acquire_guard` by a second dispatcher, with the guard aged past GUARD_STALE_S) at the moment the releasing
dispatcher unlinks the guard. It must either be refused or keep its new guard.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from v7_harness.coord import deliver as deliver_module
from v7_harness.coord.deliver import deliver
from v7_harness.coord.mailbox import Mailbox

OTHER = {"message_id": "x", "owner": "recoverer"}


class _Runner:
    def __call__(self, argv, **kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps({"result": "accepted", "type": "result"}), stderr="")


class GuardReleaseRaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name)
        (self.project / ".coord" / "mailbox").mkdir(parents=True)
        self.guards = self.project.resolve() / ".coord" / "mailbox" / "delivery" / "guards"

    def test_recovery_injected_at_unlink_never_loses_the_new_guard(self) -> None:
        real_unlink = Path.unlink
        outcome: dict[str, object] = {}

        def unlink(path: Path, missing_ok: bool = False) -> None:
            if path.suffix == ".lock" and path.parent.name == "guards" and "recovered" not in outcome:
                old = time.time() - deliver_module.GUARD_STALE_S - 10
                os.utime(path, (old, old))  # the releasing dispatcher looks crashed to a second dispatcher
                box = Mailbox(self.project / ".coord" / "mailbox")
                fd = deliver_module._acquire_guard(path, box, path.stem, "d" * 64)
                outcome["recovered"] = fd is not None
                if fd is not None:
                    with os.fdopen(fd, "wb") as handle:
                        handle.write(json.dumps(OTHER).encode("utf-8"))
            real_unlink(path, missing_ok=missing_ok)

        with patch("v7_harness.coord.deliver.shutil.which", return_value="claude"), \
                patch.object(Path, "unlink", unlink):
            result = deliver(self.project, message="U49-G1R race", actor="codex", target="claude", runner=_Runner())
        self.assertEqual("DISPATCHED", result.reason)
        self.assertIn("recovered", outcome, "the injection point was never reached")
        guards = list(self.guards.glob("*.lock"))
        if outcome["recovered"]:
            self.assertEqual(1, len(guards), "new_guard_survived=false: the recoverer's guard was deleted")
            self.assertEqual(OTHER, json.loads(guards[0].read_text(encoding="utf-8")))
        else:
            self.assertEqual([], guards)

    def test_own_guard_is_removed_and_recover_lock_is_released(self) -> None:
        with patch("v7_harness.coord.deliver.shutil.which", return_value="claude"):
            result = deliver(self.project, message="U49-G1R plain", actor="codex", target="claude", runner=_Runner())
        self.assertEqual("DISPATCHED", result.reason)
        self.assertEqual([], list(self.guards.glob("*.lock")))
        self.assertEqual([], list(self.guards.glob("*.recover.stale-*")))  # U83: the lock file stays; never stolen
        for recover in self.guards.glob("*.recover"):
            with deliver_module._recover_lock(recover.with_suffix(""), 0.0) as held:
                self.assertTrue(held, "the recovery lock was left held")

    def test_replaced_guard_is_left_to_its_new_owner(self) -> None:
        class _Replace(_Runner):
            def __call__(inner, argv, **kwargs):
                (guard,) = self.guards.glob("*.lock")
                guard.write_text(json.dumps(OTHER), encoding="utf-8")
                return super().__call__(argv, **kwargs)

        with patch("v7_harness.coord.deliver.shutil.which", return_value="claude"):
            deliver(self.project, message="U49-G1R replaced", actor="codex", target="claude", runner=_Replace())
        (guard,) = self.guards.glob("*.lock")
        self.assertEqual(OTHER, json.loads(guard.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
