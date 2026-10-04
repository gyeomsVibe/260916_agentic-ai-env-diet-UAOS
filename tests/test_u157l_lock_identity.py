"""U157-L: the RSI scheduler lock never takes a live holder's lock.

Receipt: `run_scheduler_cycle` reclaimed any lock older than `lock_ttl_seconds` (3600 s) even while its holder was
running, judged liveness by PID alone (a reused PID kept a dead lock), and two recoverers could both unlink and
re-create the lock. Contract: .work/u157l/contract_v1.md (v2). Holder identity is PID + OS process creation time;
unknown counts as alive; the TTL only alerts; reclaim happens under an OS-held byte-range guard that a crash releases.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from v7_harness import rsi_release

NOW = 2_000_000_000.0
CONFIG = {"lock_ttl_seconds": 3600, "stale_lock_grace_seconds": 30, "sources": []}


def _lock(root: Path) -> Path:
    return root / ".work" / "rsi-scheduler.lock"


def _plant(root: Path, *, pid: int, created, started_at: float, token: str = "old-token",
           name: str = "rsi-scheduler.lock") -> Path:
    path = root / ".work" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pid": pid, "created": created, "started_at": started_at, "token": token}),
                    encoding="utf-8")
    return path


def _exited_pid() -> int:
    done = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True,
                          check=True)
    return int(done.stdout.strip())


def _race_worker(root: str, barrier, receipts: str, index: int, losers: int) -> None:
    """One competitor. The winner's cycle body (fetch) holds the lock until every loser has written its receipt,
    so no loser can arrive after the winner released. Each process writes its own receipt file (no shared append)."""
    out = Path(receipts)

    def fetch(source, timeout):
        (out / f"{index}.ran").write_text("RAN", encoding="ascii")
        deadline = time.monotonic() + 90
        while len(list(out.glob("*.locked"))) < losers and time.monotonic() < deadline:
            time.sleep(0.05)
        return {"url": source["url"], "content_sha256": "a"}

    barrier.wait()
    result = rsi_release.run_scheduler_cycle(Path(root), dict(CONFIG, sources=[{"url": "u"}]), now=NOW,
                                             fetch=fetch)
    if result["status"] == "LOCKED":
        (out / f"{index}.locked").write_text("LOCKED", encoding="ascii")


def _hold_guard_then_wait(root: str, ready: str) -> None:
    """A reclaimer that takes the OS-held takeover guard and then hangs (killed by the test)."""
    with rsi_release._takeover_guard(Path(root) / ".work"):
        Path(ready).write_text("held", encoding="ascii")
        time.sleep(120)


def _run_race(test, root: Path, competitors: int, losers: int) -> tuple[list[str], list[str]]:
    receipts = root / "receipts"
    receipts.mkdir(parents=True)
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(competitors)
    procs = [ctx.Process(target=_race_worker, args=(str(root), barrier, str(receipts), i, losers))
             for i in range(competitors)]
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join(150)
        test.assertEqual(0, proc.exitcode)
    return sorted(p.name for p in receipts.glob("*.ran")), sorted(p.name for p in receipts.glob("*.locked"))


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.events = []

    def tearDown(self):
        self._tmp.cleanup()

    def cycle(self, holder_alive):
        return rsi_release.run_scheduler_cycle(self.root, dict(CONFIG), now=NOW, holder_alive=holder_alive,
                                               record=self.events.append)

    def kinds(self):
        return [event.get("event") for event in self.events]


class LiveHolderIsNeverReclaimed(Base):
    def test_live_holder_past_ttl_keeps_its_lock_and_raises_one_overdue_alert(self):
        lock = _plant(self.root, pid=4242, created=111.0, started_at=NOW - 5 * 3600)
        before = lock.read_bytes()
        result = self.cycle(lambda pid, created: True)
        self.assertEqual("LOCKED", result["status"])
        self.assertEqual(before, lock.read_bytes())
        self.assertEqual(["LOCK_OVERDUE"], self.kinds())
        self.assertEqual(4242, self.events[0]["pid"])

    def test_unverifiable_holder_is_never_reclaimed_at_any_age(self):
        lock = _plant(self.root, pid=4242, created=111.0, started_at=NOW - 30 * 86400)
        before = lock.read_bytes()
        result = self.cycle(lambda pid, created: None)
        self.assertEqual("LOCKED", result["status"])
        self.assertEqual(before, lock.read_bytes())
        self.assertIn("LOCK_HOLDER_UNVERIFIABLE", self.kinds())
        self.assertNotIn("STALE_LOCK_RECOVERED", self.kinds())


class DeadHolderIsReclaimed(Base):
    def test_reused_pid_with_another_creation_time_is_dead(self):
        _plant(self.root, pid=os.getpid(), created=1.0, started_at=NOW - 120)  # this PID, not this process
        result = self.cycle(None)  # the default reader compares the real creation time
        self.assertNotEqual("LOCKED", result["status"], self.events)
        recovered = [e for e in self.events if e.get("event") == "STALE_LOCK_RECOVERED"]
        self.assertEqual("PID_REUSED", recovered[0]["reason"])

    def test_dead_pid_past_grace_is_reclaimed(self):
        _plant(self.root, pid=4242, created=111.0, started_at=NOW - 120)
        result = self.cycle(lambda pid, created: False)
        self.assertNotEqual("LOCKED", result["status"])
        recovered = [e for e in self.events if e.get("event") == "STALE_LOCK_RECOVERED"]
        self.assertEqual("DEAD", recovered[0]["reason"])
        self.assertFalse(_lock(self.root).exists())  # released by the token check after the cycle

    def test_dead_pid_inside_grace_is_locked(self):
        lock = _plant(self.root, pid=4242, created=111.0, started_at=NOW - 5)
        before = lock.read_bytes()
        self.assertEqual("LOCKED", self.cycle(lambda pid, created: False)["status"])
        self.assertEqual(before, lock.read_bytes())

    def test_new_lock_records_the_creation_time_of_this_process(self):
        held = {}

        def fetch(source, timeout):  # runs while the cycle holds the lock
            held.update(json.loads(_lock(self.root).read_text(encoding="utf-8")))
            return {"url": source["url"], "content_sha256": "a"}

        rsi_release.run_scheduler_cycle(self.root, dict(CONFIG, sources=[{"url": "u"}]), now=NOW, fetch=fetch)
        created = rsi_release._process_created(os.getpid())
        self.assertIsNotNone(created)
        self.assertEqual(created, rsi_release._process_created(os.getpid()))  # stable, not a clock reading
        self.assertEqual((os.getpid(), created), (held["pid"], held["created"]))


class TakeoverIsSerialized(Base):
    """Codex relay_63103325: reclaim is serialized by an OS-held guard (msvcrt/fcntl byte lock) that a crash
    releases and that is never itself reclaimed or unlinked."""

    def _guard_holder(self):
        ready = self.root / "guard_ready.txt"
        ctx = multiprocessing.get_context("spawn")
        proc = ctx.Process(target=_hold_guard_then_wait, args=(str(self.root), str(ready)))
        proc.start()
        deadline = time.monotonic() + 60
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(ready.exists())
        return proc

    def test_a_held_guard_blocks_a_reclaim(self):
        lock = _plant(self.root, pid=4242, created=111.0, started_at=NOW - 120)
        before = lock.read_bytes()
        holder = self._guard_holder()
        try:
            self.assertEqual("LOCKED", self.cycle(lambda pid, created: False)["status"])
            self.assertEqual(before, lock.read_bytes())
        finally:
            holder.kill()
            holder.join(30)

    def test_claimant_death_during_takeover_releases_the_guard(self):
        _plant(self.root, pid=4242, created=111.0, started_at=NOW - 120)
        holder = self._guard_holder()
        holder.kill()  # dies while holding the guard, mid-takeover
        holder.join(30)
        result = self.cycle(lambda pid, created: False)
        self.assertNotEqual("LOCKED", result["status"], self.events)
        self.assertTrue((self.root / ".work").is_dir())

    def test_real_parallel_recovery_has_exactly_one_owner(self):
        for round_no in range(20):
            with self.subTest(round=round_no):
                root = self.root / f"r{round_no}"
                _plant(root, pid=_exited_pid(), created=1.0, started_at=NOW - 120)
                ran, locked = _run_race(self, root, competitors=8, losers=7)
                self.assertEqual(1, len(ran), (ran, locked))
                self.assertEqual(7, len(locked), (ran, locked))

    def test_two_simultaneous_reclaimers_of_a_dead_holder(self):
        for round_no in range(20):
            with self.subTest(round=round_no):
                root = self.root / f"two{round_no}"
                _plant(root, pid=_exited_pid(), created=1.0, started_at=NOW - 120)
                ran, locked = _run_race(self, root, competitors=2, losers=1)
                self.assertEqual((1, 1), (len(ran), len(locked)), (ran, locked))


class Fencing(Base):
    def test_an_owner_that_lost_its_lock_writes_no_state(self):
        state = self.root / ".work" / "rsi-scheduler-state.json"

        def fetch(source, timeout):  # another owner replaces the lock while this cycle runs
            _plant(self.root, pid=4242, created=111.0, started_at=NOW, token="usurper")
            return {"url": source["url"], "content_sha256": "a"}

        result = rsi_release.run_scheduler_cycle(self.root, dict(CONFIG, sources=[{"url": "u"}]), now=NOW,
                                                 fetch=fetch, record=self.events.append)
        self.assertEqual("LOCKED_OUT", result["status"])
        self.assertFalse(state.exists())
        self.assertIn("LOCK_LOST", self.kinds())
        self.assertEqual("usurper", json.loads(_lock(self.root).read_text(encoding="utf-8"))["token"])


class RealProcesses(Base):
    """Codex relay_0970eeeb: real competing processes against a real live holder older than the TTL."""

    def test_two_real_competitors_leave_a_live_overdue_holder_its_lock(self):
        holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        try:
            created = rsi_release._process_created(holder.pid)
            self.assertIsNotNone(created)
            lock = _plant(self.root, pid=holder.pid, created=created, started_at=NOW - 5 * 3600, token="holder")
            before = lock.read_bytes()
            ran, locked = _run_race(self, self.root, competitors=2, losers=2)
            self.assertEqual(([], ["0.locked", "1.locked"]), (ran, locked))
            self.assertEqual(before, lock.read_bytes())
        finally:
            holder.kill()
            holder.wait()

    def test_malformed_lock_fails_closed_at_any_age(self):
        lock = _lock(self.root)
        lock.parent.mkdir(parents=True)
        for body in (b"", b"{not json", b"[]", b'{"pid": "x"}'):
            with self.subTest(body=body):
                lock.write_bytes(body)
                os.utime(lock, (NOW - 30 * 86400, NOW - 30 * 86400))
                self.events.clear()
                self.assertEqual("LOCKED", self.cycle(lambda pid, created: False)["status"])
                self.assertEqual(body, lock.read_bytes())
                self.assertIn("LOCK_MALFORMED", self.kinds())


class OldKeywordStillWorks(Base):
    def old(self, answer):
        return rsi_release.run_scheduler_cycle(self.root, dict(CONFIG), now=NOW, pid_alive=lambda pid: answer,
                                               record=self.events.append)

    def test_pid_alive_keyword_is_still_consulted(self):
        # A true identity (this process) so the OS check passes; the old keyword then decides.
        created = rsi_release._process_created(os.getpid())
        lock = _plant(self.root, pid=os.getpid(), created=created, started_at=NOW - 120)
        before = lock.read_bytes()
        self.assertEqual("LOCKED", self.old(True)["status"])
        self.assertEqual(before, lock.read_bytes())
        self.events.clear()
        self.assertNotEqual("LOCKED", self.old(False)["status"], self.events)
        recovered = [e for e in self.events if e.get("event") == "STALE_LOCK_RECOVERED"]
        self.assertEqual("DEAD", recovered[0]["reason"])

    def test_pid_alive_true_cannot_vouch_for_a_reused_pid(self):
        # Codex relay_63103325: the old adapter sees only the PID, so it may not authenticate a reused one.
        # This process's PID with a wrong creation time is dead whatever pid_alive says.
        _plant(self.root, pid=os.getpid(), created=1.0, started_at=NOW - 120)
        result = rsi_release.run_scheduler_cycle(self.root, dict(CONFIG), now=NOW, pid_alive=lambda pid: True,
                                                 record=self.events.append)
        self.assertNotEqual("LOCKED", result["status"], self.events)
        recovered = [e for e in self.events if e.get("event") == "STALE_LOCK_RECOVERED"]
        self.assertEqual("PID_REUSED", recovered[0]["reason"])


if __name__ == "__main__":
    unittest.main()
