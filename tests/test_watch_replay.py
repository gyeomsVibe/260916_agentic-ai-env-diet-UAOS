"""WATCH-REPLAY: an answered request whose wake the consumer received must not wake a re-armed watcher again.

Receipt (2026-11-21, BLOCKED 20261121T1358-claude-0001): every re-armed `coord watch --wakes-session` exited at once
with REQUEST_ANSWERED for a request handled hours earlier, because a WAKE_PENDING claim whose waker had exited was
reclaimable by any later-started watcher. The CLI now writes a producer receipt (`surfaced_at`) only after the wake
line was written and flushed; a claim without a receipt (watcher died, broken pipe) stays reclaimable (at-least-once).
Rev4 (Codex REVISE on rev3): a flush is not a read, so a surfaced but unacked wake is held only for its claim window,
then recovered as a new generation (bounded by WAKE_MAX_GENERATIONS) until the requester's `coord ack` settles it.
"""

from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.test_u277_request_wake import _answer, _project, _register  # noqa: E402


class _BrokenOut(io.StringIO):
    def write(self, text):  # the consumer went away
        raise BrokenPipeError("consumer closed")


def _run_cli(root: Path, out: io.StringIO) -> int:
    from v7_harness import cli

    args = argparse.Namespace(project=str(root), target=["claude"], timeout=5.0, interval=0.05,
                              wakes_session=True, policy="structured", session="sA")
    with mock.patch("sys.stdout", out):
        return cli.cmd_coord_watch(args)


class WatchReplayTests(unittest.TestCase):
    def test_received_wake_does_not_replay_but_a_new_answer_still_wakes(self) -> None:
        from v7_harness.coord import requests

        tmp, root = _project()
        with tmp:
            _register(root, "relay_old")
            _answer(root, "relay_old")
            first = io.StringIO()
            self.assertEqual(_run_cli(root, first), 0)
            self.assertIn("relay_old", first.getvalue())
            row = requests.get(root, "relay_old")
            self.assertTrue(row.get("surfaced_at"))
            # Re-armed watcher inside the claim window: the waker is gone, the old answer must stay quiet (receipt).
            inside = row["waker"]["lease_until"] - 1.0
            self.assertFalse(requests.claim_wake(root, "relay_old", session="sA", now=inside, started_at=inside))
            self.assertEqual(requests.get(root, "relay_old")["rev"], row["rev"])  # refused without a write
            self.assertEqual(row["state"], "WAKE_PENDING")
            # A newly answered request still wakes.
            _register(root, "relay_new")
            _answer(root, "relay_new")
            second = io.StringIO()
            self.assertEqual(_run_cli(root, second), 0)
            self.assertIn("relay_new", second.getvalue())
            self.assertNotIn("relay_old", second.getvalue())

    def test_broken_output_leaves_the_claim_reclaimable(self) -> None:
        from v7_harness.coord import requests

        tmp, root = _project()
        with tmp:
            _register(root, "relay_bp")
            _answer(root, "relay_bp")
            with self.assertRaises(BrokenPipeError):
                _run_cli(root, _BrokenOut())
            self.assertFalse(requests.get(root, "relay_bp").get("surfaced_at"))
            # Lease over: a later watcher recovers the unobserved wake.
            self.assertTrue(requests.claim_wake(root, "relay_bp", session="sA", now=1.0e12, started_at=1.0e12))

    def test_coord_ack_of_a_request_id_is_the_consumer_confirmation(self) -> None:
        # Codex rev2: surfaced_at only proves the producer flushed. The session's own `coord ack` settles the request.
        from v7_harness import cli
        from v7_harness.coord import requests

        tmp, root = _project()
        with tmp:
            _register(root, "relay_ackme")
            _answer(root, "relay_ackme")
            self.assertEqual(_run_cli(root, io.StringIO()), 0)
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                rc = cli.cmd_coord_ack(argparse.Namespace(project=str(root), message_id="relay_ackme",
                                                          consumer="sA"))
            self.assertEqual(rc, 0, out.getvalue())
            self.assertEqual(requests.get(root, "relay_ackme")["state"], "ACKED")

    def test_coord_ack_from_another_session_cannot_settle_the_request(self) -> None:
        # Antigravity P1: the stored owner session is never substituted for the caller's own identity.
        from v7_harness import cli
        from v7_harness.coord import requests

        tmp, root = _project()
        with tmp:
            _register(root, "relay_imp")
            _answer(root, "relay_imp")
            self.assertEqual(_run_cli(root, io.StringIO()), 0)
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                rc = cli.cmd_coord_ack(argparse.Namespace(project=str(root), message_id="relay_imp",
                                                          consumer="someone-else"))
            self.assertEqual(rc, 1, out.getvalue())
            self.assertEqual(requests.get(root, "relay_imp")["state"], "WAKE_PENDING")

    def test_real_unread_pipe_recovers_after_the_claim_window_until_ack(self) -> None:
        # Codex rev3 REVISE: a real child watcher flushes into a pipe its parent never reads (child exit 0, parent
        # bytes 0). The flush is not a read, so the request must stay WAKE_PENDING and recover after the claim window;
        # inside the window nothing replays; the requester's own `coord ack` stops every later wake.
        from v7_harness import cli
        from v7_harness.coord import requests, watch

        tmp, root = _project()
        with tmp:
            _register(root, "relay_pipe")
            _answer(root, "relay_pipe")
            code = "import sys; sys.path.insert(0, sys.argv[1]); from v7_harness.cli import main; " \
                   "sys.exit(main(sys.argv[2:]))"
            child = subprocess.Popen([sys.executable, "-c", code, str(ROOT), "coord", "watch", "--project", str(root),
                                      "--target", "claude", "--wakes-session", "--session", "sA",
                                      "--timeout", "30", "--interval", "0.05"],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            try:
                self.assertEqual(child.wait(timeout=60), 0)  # exit 0 with its line still unread in the pipe
            finally:
                child.stdout.close()  # parent read 0 bytes
            row = requests.get(root, "relay_pipe")
            self.assertEqual(row["state"], "WAKE_PENDING")
            self.assertTrue(row.get("surfaced_at"))
            self.assertEqual(row["wake_generation"], 1)
            lease = row["waker"]["lease_until"]
            # Inside the claim window a re-armed watcher stays quiet (no duplicate storm).
            self.assertIsNone(watch._request_wake(root, ("claude",), "sA", lease - 1.0, lease - 1.0))
            # After the window one later watcher recovers it as generation 2; a sibling at the same moment does not.
            woken = watch._request_wake(root, ("claude",), "sA", lease + 1.0, lease + 1.0)
            self.assertEqual((woken or {}).get("request_id"), "relay_pipe")
            self.assertEqual(woken["wake_generation"], 2)
            self.assertIsNone(watch._request_wake(root, ("claude",), "sA", lease + 1.0, lease + 1.0))
            # The requester's explicit ack settles it; no watcher wakes for it again, however late.
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                rc = cli.cmd_coord_ack(argparse.Namespace(project=str(root), message_id="relay_pipe", consumer="sA"))
            self.assertEqual(rc, 0, out.getvalue())
            self.assertEqual(requests.get(root, "relay_pipe")["state"], "ACKED")
            self.assertIsNone(watch._request_wake(root, ("claude",), "sA", 1.0e12, 1.0e12))
            self.assertFalse(requests.claim_wake(root, "relay_pipe", session="sA", now=1.0e12, started_at=1.0e12))

    def test_unacked_replay_is_bounded_per_generation(self) -> None:
        from v7_harness.coord import requests

        tmp, root = _project()
        with tmp:
            _register(root, "relay_cap")
            _answer(root, "relay_cap")
            requests.scan(root)
            moment = 1000.0
            for generation in range(1, requests.WAKE_MAX_GENERATIONS + 1):
                self.assertTrue(requests.claim_wake(root, "relay_cap", session="sA", now=moment, started_at=moment))
                self.assertEqual(requests.get(root, "relay_cap")["wake_generation"], generation)
                # A receipt from an older generation is refused; the current claimant's is kept.
                self.assertFalse(requests.mark_surfaced(root, "relay_cap", pid=os.getpid(), generation=generation - 1))
                self.assertTrue(requests.mark_surfaced(root, "relay_cap", pid=os.getpid(), generation=generation))
                moment += requests.WAKE_LEASE_S + 1.0
            # Out of generations: a never-acking consumer is not woken again.
            self.assertFalse(requests.claim_wake(root, "relay_cap", session="sA", now=1.0e12, started_at=1.0e12))
            self.assertEqual(requests.get(root, "relay_cap")["state"], "WAKE_PENDING")

    def test_only_the_claimant_can_write_the_receipt(self) -> None:
        from v7_harness.coord import requests

        tmp, root = _project()
        with tmp:
            _register(root, "relay_f")
            _answer(root, "relay_f")
            requests.scan(root)
            self.assertTrue(requests.claim_wake(root, "relay_f", session="sA"))
            self.assertFalse(requests.mark_surfaced(root, "relay_f", pid=os.getpid() + 1))
            self.assertTrue(requests.mark_surfaced(root, "relay_f", pid=os.getpid()))


if __name__ == "__main__":
    unittest.main()
