"""U203: a stalled step is rerouted even while an ACTIVE tool sits idle, and the new owner can really take it.

Receipt (2026-10-16): Codex parked U202 BLOCKED at 02:28; the U166 reroute needed a vote from every ACTIVE tool, and
Claude (ACTIVE, session idle, no watcher) cast none until 09:38, so the step waited 7 hours. The reroute then kept
Codex's `owner_session`, so the transition wake was bound to Codex's thread and Claude could not ack it. Stage 0:
Raft elects on a timeout instead of waiting for silent peers (https://raft.github.io/raft.pdf, section 5.2).
"""
from __future__ import annotations

import inspect
import json
import os
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord import sentinel, stall

NOW = 2_000_000_000.0


def _desk(**states):
    return {tool: {"state": state} for tool, state in states.items()}


class QuorumTimeout(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / ".coord").mkdir()
        (self.root / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        path = self.root / ".coord" / "master_schedule.json"
        path.write_text(json.dumps({"schedule_id": "T", "phases": [
            {"phase_id": "U1-X", "state": "BLOCKED", "owner_tool": "codex", "owner_session": "codex-thread-1"}]}),
            encoding="utf-8")
        os.utime(path, (NOW, NOW))  # the phase has waited since NOW at the latest

    def tearDown(self):
        self._tmp.cleanup()

    def phase(self):
        data = json.loads((self.root / ".coord" / "master_schedule.json").read_text(encoding="utf-8"))
        return data["phases"][0]

    def test_under_the_timeout_every_active_tool_must_still_agree(self):
        desk = _desk(codex="ACTIVE", claude="ACTIVE")
        result = stall.scan(self.root, "codex", now=NOW + stall.MAX_WAIT_S + 60, desk=desk)
        self.assertEqual([], result["adopted"])
        self.assertEqual("codex", self.phase()["owner_tool"])

    def opened_then(self, tool, *, later):
        """A first scan opens the ballot after the wait limit; a second one `later` seconds on decides."""
        desk = _desk(codex="ACTIVE", claude="ACTIVE")
        start = NOW + stall.MAX_WAIT_S + 60
        first = stall.scan(self.root, tool, now=start, desk=desk)
        return first, stall.scan(self.root, tool, now=start + later, desk=desk)

    def test_past_the_timeout_a_silent_active_tool_no_longer_blocks_the_reroute(self):
        first, result = self.opened_then("codex", later=stall.QUORUM_TIMEOUT_S)
        self.assertEqual([], first["adopted"])
        self.assertEqual(1, len(result["adopted"]), result)
        self.assertEqual("claude", self.phase()["owner_tool"])
        self.assertEqual("READY", self.phase()["state"])

    def test_the_timeout_is_longer_than_the_wait_limit(self):
        self.assertGreater(stall.QUORUM_TIMEOUT_S, stall.MAX_WAIT_S)

    def test_a_ballot_open_less_than_the_timeout_still_waits(self):
        _, result = self.opened_then("codex", later=stall.QUORUM_TIMEOUT_S - 60)
        self.assertEqual([], result["adopted"])

    def test_a_scan_without_a_tool_casts_no_vote_but_still_reroutes_past_the_timeout(self):
        early, late = self.opened_then(None, later=stall.QUORUM_TIMEOUT_S)
        self.assertEqual([], early["adopted"])
        for entry in early["stalled"]:
            self.assertEqual([], entry["voters"])
        self.assertEqual(1, len(late["adopted"]), late)

    def test_the_reroute_drops_the_old_owner_session(self):
        self.opened_then("codex", later=stall.QUORUM_TIMEOUT_S)
        phase = self.phase()
        self.assertNotIn("owner_session", phase)
        self.assertEqual("codex-thread-1", phase["rerouted_from"]["owner_session"])

    def test_the_sentinel_cycle_runs_the_scan(self):
        source = inspect.getsource(sentinel.run_sentinel_cycle)
        self.assertIn("stall", source)
        self.assertIn("scan(", source)


if __name__ == "__main__":
    unittest.main()
