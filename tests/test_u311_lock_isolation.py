"""U311: independent lock paths must progress while same-path writes exclude."""

import queue
import tempfile
import threading
import unittest
from pathlib import Path

from v7_harness.coord.nonstop_orchestrator import (
    acquire_sequential_input_lease,
    release_sequential_input_lease,
)
from v7_harness.coord.stream import _exclusive


class LockIsolation(unittest.TestCase):
    def run_overlapping_lock_attempts(self, same_path):
        with tempfile.TemporaryDirectory() as tmp:
            path_a = Path(tmp) / "lane-a.lock"
            path_b = path_a if same_path else Path(tmp) / "lane-b.lock"
            holder_entered = threading.Event()
            release_holder = threading.Event()
            contender_started = threading.Event()
            contender_entered = threading.Event()
            failures = queue.Queue()
            state = {"holder_active": False, "overlap": None}

            def holder():
                try:
                    with _exclusive(path_a):
                        state["holder_active"] = True
                        holder_entered.set()
                        if not release_holder.wait(5):
                            raise AssertionError("test did not release its lock holder")
                        state["holder_active"] = False
                except BaseException as exc:
                    failures.put(exc)

            def contender():
                try:
                    contender_started.set()
                    with _exclusive(path_b):
                        state["overlap"] = state["holder_active"]
                        contender_entered.set()
                except BaseException as exc:
                    failures.put(exc)

            first = threading.Thread(target=holder, daemon=True)
            second = threading.Thread(target=contender, daemon=True)
            first.start()
            try:
                self.assertTrue(holder_entered.wait(2), "holder never acquired lane A")
                second.start()
                self.assertTrue(contender_started.wait(2), "contender never started")
                # Start is event-synchronized; this bound tests progress while A remains held.
                entered_before_release = contender_entered.wait(0.5 if same_path else 2)
                if same_path:
                    self.assertFalse(entered_before_release, "same-path critical sections overlapped")
                else:
                    self.assertTrue(entered_before_release, "lane A blocked independent lane B")
                    self.assertTrue(state["overlap"], "independent progress was only sequential")
            finally:
                release_holder.set()
                first.join(3)
                if second.ident is not None:
                    second.join(3)
            self.assertFalse(first.is_alive(), "holder did not finish")
            self.assertFalse(second.is_alive(), "contender did not finish")
            if not failures.empty():
                raise failures.get()
            self.assertTrue(contender_entered.is_set())
            if same_path:
                self.assertFalse(state["overlap"])

    def test_distinct_paths_enter_before_long_holder_releases(self):
        self.run_overlapping_lock_attempts(same_path=False)

    def test_same_path_waits_for_holder_release(self):
        self.run_overlapping_lock_attempts(same_path=True)

    def test_atomic_sequential_input_lease_concurrency_and_ttl_expiry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            barrier = threading.Barrier(6)
            results = []
            res_lock = threading.Lock()

            def worker(idx: int):
                barrier.wait(timeout=5)
                r = acquire_sequential_input_lease(
                    root,
                    resource_id="shared_merge_queue",
                    owner_tool=f"tool_{idx}",
                    card_id=f"U31{idx}",
                    ttl_s=300.0,
                    now=1000.0,
                )
                with res_lock:
                    results.append(r)

            threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(5)

            winners = [r for r in results if r.get("ok")]
            losers = [r for r in results if not r.get("ok")]
            self.assertEqual(len(winners), 1, f"expected exactly 1 atomic lease winner, got {len(winners)}")
            self.assertEqual(len(losers), 5)
            for l in losers:
                self.assertEqual(l["status"], "LEASE_HELD_BY_PEER")

            # After TTL expires (now=1305.0 > 1000.0 + 300.0), a new caller cleanly recovers the expired lease
            recovered = acquire_sequential_input_lease(
                root,
                resource_id="shared_merge_queue",
                owner_tool="claude",
                card_id="U316",
                ttl_s=60.0,
                now=1305.0,
            )
            self.assertTrue(recovered["ok"])
            self.assertEqual(recovered["lease"]["owner_tool"], "claude")

            # Explicit release allows immediate acquisition by another tool before TTL
            rel = release_sequential_input_lease(
                root,
                resource_id="shared_merge_queue",
                owner_tool="claude",
                card_id="U316",
            )
            self.assertTrue(rel["ok"])
            reacquired = acquire_sequential_input_lease(
                root,
                resource_id="shared_merge_queue",
                owner_tool="codex",
                card_id="U315",
                ttl_s=60.0,
                now=1310.0,
            )
            self.assertTrue(reacquired["ok"])
            self.assertEqual(reacquired["lease"]["owner_tool"], "codex")

    def test_atomic_sequential_input_lease_stress_15_runs(self):
        for run_idx in range(15):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                barrier = threading.Barrier(6)
                results = []
                errors = []
                res_lock = threading.Lock()

                def worker(idx: int):
                    try:
                        barrier.wait(timeout=5)
                        r = acquire_sequential_input_lease(
                            root,
                            resource_id="shared_merge_queue",
                            owner_tool=f"tool_{idx}",
                            card_id=f"U31{idx}",
                            ttl_s=300.0,
                            now=1000.0 + run_idx,
                        )
                        with res_lock:
                            results.append(r)
                    except BaseException as exc:
                        with res_lock:
                            errors.append(exc)

                threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(6)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join(5)

                self.assertEqual(errors, [], f"run {run_idx} raised worker exceptions: {errors}")
                winners = [r for r in results if r.get("ok")]
                losers = [r for r in results if not r.get("ok")]
                self.assertEqual(len(winners), 1, f"run {run_idx}: expected 1 winner, got {len(winners)}")
                self.assertEqual(len(losers), 5, f"run {run_idx}: expected 5 losers, got {len(losers)}")
                for l in losers:
                    self.assertEqual(l["status"], "LEASE_HELD_BY_PEER")


if __name__ == "__main__":
    unittest.main()
