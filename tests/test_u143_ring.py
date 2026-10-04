"""U143: a real OS sound when a letter that asks for a turn is published (frozen acceptance).

Receipt: .coord/notes/U134R_U143_MIA_TOTAL_ARCHITECTURE_PROPOSAL.md §1 (2026-10-03): letters reached the desk but no
sound played, so 윤겸스 could not tell that work had finished or a letter had arrived; `sentinel.ring_bell` only queues
text. Carved out of P1-COMMS by agreement (relay_0cf580f1 + Antigravity PASS relay_c221d748, 2026-10-05).
Stage 0: `winsound.MessageBeep` is Windows only and raises RuntimeError on a system error
(https://docs.python.org/3/library/winsound.html); Win32 MessageBeep queues the sound and returns at once
(https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-messagebeep), so a delivery never waits on it.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from tests.test_u141b_producer_wake import ORDINARY, Base
from v7_harness.coord import ring as R
from v7_harness.coord.deliver import deliver

ON = {"UAOS_RING": "1"}


class Player:
    def __init__(self, error=None):
        self.calls, self.error = 0, error

    def __call__(self):
        self.calls += 1
        if self.error:
            raise self.error


class Ring(Base):
    def test_rings_once_then_coalesces_a_burst(self):
        play = Player()
        first = R.ring(self.root, reason="relay_a", env=ON, player=play, now=1000.0)
        second = R.ring(self.root, reason="relay_b", env=ON, player=play, now=1000.0 + R.RING_GAP_S - 1)
        self.assertEqual((True, False), (first["rung"], second["rung"]))
        self.assertEqual("COALESCED", second["reason"])
        self.assertEqual(1, play.calls)

    def test_rings_again_after_the_gap(self):
        play = Player()
        R.ring(self.root, reason="a", env=ON, player=play, now=1000.0)
        self.assertTrue(R.ring(self.root, reason="b", env=ON, player=play, now=1000.0 + R.RING_GAP_S)["rung"])
        self.assertEqual(2, play.calls)

    def test_a_worker_or_ring_off_is_silent_and_writes_nothing(self):
        play = Player()
        for env, reason in (({"UAOS_WORKER": "1", "UAOS_RING": "1"}, "WORKER"), ({"UAOS_RING": "0"}, "RING_OFF")):
            out = R.ring(self.root, reason="x", env=env, player=play, now=1000.0)
            self.assertEqual((False, reason), (out["rung"], out["reason"]))
        self.assertEqual(0, play.calls)
        self.assertFalse((self.root / R.STAMP).exists())

    def test_a_sound_error_never_raises(self):
        out = R.ring(self.root, reason="x", env=ON, player=Player(RuntimeError("no device")), now=1000.0)
        self.assertFalse(out["rung"])
        self.assertIn("RuntimeError", out["reason"])

    def test_a_broken_stamp_does_not_block_the_sound(self):
        stamp = self.root / R.STAMP
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text("not json", encoding="utf-8")
        play = Player()
        self.assertTrue(R.ring(self.root, reason="x", env=ON, player=play, now=1000.0)["rung"])
        self.assertEqual(1000.0, json.loads(stamp.read_text(encoding="utf-8"))["ts"])

    def test_without_winsound_it_reports_and_does_not_raise(self):
        with mock.patch.dict("sys.modules", {"winsound": None}):
            out = R.ring(self.root, reason="x", env=ON, now=1000.0)
        self.assertEqual((False, "NO_SOUND_DEVICE"), (out["rung"], out["reason"]))

    def test_the_default_player_is_the_windows_exclamation_sound(self):
        fake = mock.Mock(MB_ICONEXCLAMATION=0x30)
        with mock.patch.dict("sys.modules", {"winsound": fake}):
            self.assertTrue(R.ring(self.root, reason="x", env=ON, now=1000.0)["rung"])
        fake.MessageBeep.assert_called_once_with(0x30)


class DeliverRings(Base):
    def test_a_letter_that_asks_for_a_turn_rings_with_its_id(self):
        with mock.patch.object(R, "ring") as ring:
            result = deliver(self.root, actor="claude", message=ORDINARY, target="codex")
        ring.assert_called_once()
        self.assertEqual(Path(self.root).resolve(), Path(ring.call_args.args[0]).resolve())
        self.assertIn(result.message_id, ring.call_args.kwargs["reason"])

    def test_an_ack_or_notice_letter_is_silent(self):
        with mock.patch.object(R, "ring") as ring:
            deliver(self.root, actor="claude", message="ACK_ONLY alive", target="codex")
            deliver(self.root, actor="claude", message="status line", target="codex", wake_class="NOTICE")
        ring.assert_not_called()

    def test_a_ring_failure_never_fails_the_delivery(self):
        with mock.patch.object(R, "ring", side_effect=OSError("disk")):
            result = deliver(self.root, actor="claude", message=ORDINARY, target="codex")
        self.assertTrue(result.message_id)
        self.assertTrue((self.box.inbox_dir / f"{result.message_id}.json").is_file())


class SuiteIsQuiet(unittest.TestCase):
    def test_the_test_env_guard_turns_the_ring_off(self):
        import os

        self.assertEqual("0", os.environ.get("UAOS_RING"))


if __name__ == "__main__":
    unittest.main()
