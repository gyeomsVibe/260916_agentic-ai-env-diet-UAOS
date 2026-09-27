"""U49-M2: an ack file that stays locked must not be read as "absent" (that would publish an acked id again)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import mailbox as mailbox_module
from v7_harness.coord.mailbox import Mailbox, MailboxRejected

PAYLOAD = {"kind": "HANDOFF", "message": "hello"}


class LockedAckTests(unittest.TestCase):
    def _acked_box(self, directory: str) -> tuple[Mailbox, Path]:
        box = Mailbox(Path(directory))
        box.publish("m1", PAYLOAD)
        claim = box.claim("m1", "reader")
        box.ack(claim)
        ack = box.ack_dir / "m1.json"
        self.assertTrue(ack.is_file())
        return box, ack

    def test_locked_ack_fails_closed_instead_of_republishing(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            box, ack = self._acked_box(d)
            real = Path.read_bytes

            def locked(path: Path) -> bytes:
                if path == ack:
                    raise PermissionError(13, "locked", str(path))
                return real(path)

            with mock.patch.object(Path, "read_bytes", locked), mock.patch.object(mailbox_module.time, "sleep"):
                with self.assertRaises(MailboxRejected):
                    box.publish("m1", PAYLOAD)
            self.assertFalse((box.inbox_dir / "m1.json").exists())

    def test_readable_ack_still_dedupes(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            box, ack = self._acked_box(d)
            self.assertEqual(ack, box.publish("m1", PAYLOAD))
            self.assertFalse((box.inbox_dir / "m1.json").exists())

    def test_vanished_file_is_still_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            box = Mailbox(Path(d))
            path = box.inbox_dir / "m2.json"
            self.assertIsNone(mailbox_module._read_settled(path))
            box.publish("m2", PAYLOAD)
            self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()
