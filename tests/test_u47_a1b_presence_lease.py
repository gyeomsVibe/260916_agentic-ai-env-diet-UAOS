"""U47-A1b frozen acceptance (written by Claude): a quota lease is not overwritten by a later session heartbeat.

Codex's re-review of U47-A1 (2026-09-27): `pilot judge` marked antigravity LIMITED from agy's 429 "Resets in 162h",
but the next ACTIVE session hook (presence.mark) replaced it, so routing again sent work to a tool that could not
answer. A lease holds until it expires; a heartbeat of the same state, a later lease, or expiry ends it.
"""

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord.presence import mark, read

T0 = 1_000_000.0


class PresenceLeaseTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_active_heartbeat_does_not_overwrite_live_lease(self):
        mark(self.project, "antigravity", "LIMITED", ttl_s=585_882, now=T0, lease=True)
        mark(self.project, "antigravity", "ACTIVE", ttl_s=3600, now=T0 + 60)
        desk = read(self.project, "antigravity", now=T0 + 120)
        self.assertEqual("LIMITED", desk["state"])
        self.assertEqual(T0 + 585_882, desk["expires_at"])

    def test_heartbeat_writes_again_after_the_lease_expires(self):
        mark(self.project, "antigravity", "LIMITED", ttl_s=100, now=T0, lease=True)
        mark(self.project, "antigravity", "ACTIVE", ttl_s=3600, now=T0 + 101)
        self.assertEqual("ACTIVE", read(self.project, "antigravity", now=T0 + 102)["state"])

    def test_a_new_lease_replaces_the_old_one(self):
        mark(self.project, "antigravity", "LIMITED", ttl_s=585_882, now=T0, lease=True)
        mark(self.project, "antigravity", "ACTIVE", ttl_s=3600, now=T0 + 10, lease=True)
        self.assertEqual("ACTIVE", read(self.project, "antigravity", now=T0 + 20)["state"])

    def test_plain_heartbeats_still_replace_each_other(self):
        mark(self.project, "codex", "LIMITED", ttl_s=3600, now=T0)
        mark(self.project, "codex", "ACTIVE", ttl_s=3600, now=T0 + 10)
        self.assertEqual("ACTIVE", read(self.project, "codex", now=T0 + 20)["state"])

    def test_lease_is_recorded_and_the_heartbeat_file_is_untouched(self):
        path = mark(self.project, "antigravity", "LIMITED", ttl_s=500, now=T0, lease=True)
        before = path.read_bytes()
        mark(self.project, "antigravity", "ACTIVE", ttl_s=3600, now=T0 + 1)
        self.assertEqual(before, path.read_bytes())
        self.assertIs(True, json.loads(before)["lease"])


if __name__ == "__main__":
    unittest.main()
