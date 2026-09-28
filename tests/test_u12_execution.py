"""Test suite for U12 durable execution: claim/ack lifecycle, lease/fence, budgets/circuits, launcher."""

from __future__ import annotations

import os
import multiprocessing
import sqlite3
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any

from multiprocessing.connection import Client

from v7_harness.broker import BrokerClient, ForegroundBroker, make_local_pipe_name
from v7_harness.broker.core import BrokerCore, BrokerOwnershipError
from v7_harness.contracts.database import MIGRATIONS, MigrationError, apply_migrations
from v7_harness.execution import (
    BoundedDispatcher,
    CircuitBreakerManager,
    CircuitOpenError,
    DrainInProgressError,
    DuplicateDeliveryError,
    DurableExecutionEngine,
    ExecutionError,
    MockSubprocessLauncher,
    QueueSaturationError,
    QuotaFailClosedError,
    RetryBudget,
    StaleFenceError,
    WorkerExecutionError,
    assert_fence,
    build_worker_script,
    bump_fence,
    check_quota,
    claim_lease,
    ensure_attempt,
    ensure_plan,
    ensure_resource,
    expire_lease,
    record_checkpoint,
    record_effect,
    record_receipt,
    renew_lease,
    reserve_retry_budget,
    revoke_lease,
    set_quota_state,
    validate_promotion,
)

H = "a" * 64


def run_u12_broker(db: str, address: str, authkey: bytes, ready: Any) -> None:
    # B59: 이 픽스처는 동시 8건으로 선두 차단(head-of-line) 여부만 본다. 용량 4는 8건 중
    # 일부를 재시도 가능한 QUEUE_SATURATED로 되돌려 간헐 실패를 만들었다. 포화 동작 자체는
    # test_dispatcher_saturation... 에서 따로 검사한다.
    ForegroundBroker(Path(db), address, authkey, request_timeout=1.0, dispatcher_capacity=8).serve_forever(ready)


def make_command(
    command_id: str = "c1",
    idempotency_key: str = "idem-1",
    task_id: str = "U12",
    scope_id: str = "default-scope",
    provider: str = "mock-provider",
    failure_class: str = "WORKER_CRASH",
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "command_id": command_id,
        "task_id": task_id,
        "card_revision": 1,
        "acceptance_hash": H,
        "idempotency_key": idempotency_key,
        "operation": "VERIFY",
        "payload_ref": "artifact:payload",
        "scope_id": scope_id,
        "provider": provider,
        "failure_class": failure_class,
        "resource_id": f"res-{task_id}",
        "attempt_id": f"att-{command_id}",
        "owner": "worker-1",
    }


class DurableExecutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "execution.db"
        self.core = BrokerCore(self.db_path)
        self.core.start()
        self.conn: sqlite3.Connection = self.core.connection
        # Set default quota AVAILABLE for tests
        set_quota_state(self.conn, scope_id="default-scope", provider="mock-provider", quota_state="AVAILABLE")

    def tearDown(self) -> None:
        self.core.close()
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # Counterexample 1: duplicate delivery 10회 attempt / effect 1회
    # -------------------------------------------------------------------------
    def test_counterexample_1_duplicate_delivery_10_attempts_one_effect(self) -> None:
        engine = DurableExecutionEngine(self.core)
        cmd = make_command("cmd-dedupe-1", "idem-dedupe-1")
        effect_counter = 0

        def on_effect() -> None:
            nonlocal effect_counter
            effect_counter += 1

        results = []
        for i in range(10):
            res = engine.execute(cmd, effect_callback=on_effect)
            results.append(res)

        # 1st execution ran effect and acknowledged
        self.assertTrue(results[0]["ok"])
        self.assertFalse(results[0]["replayed"])
        self.assertEqual(results[0]["state"], "ACKED")

        # 2nd through 10th executions were replays of committed result
        for i in range(1, 10):
            self.assertTrue(results[i]["ok"])
            self.assertTrue(results[i]["replayed"])
            self.assertEqual(results[i]["state"], "ACKED")
            self.assertEqual(results[i]["result_hash"], results[0]["result_hash"])

        # Side-effect executed EXACTLY ONCE
        self.assertEqual(effect_counter, 1, "Effect must run exactly once across 10 delivery attempts")

        # DB invariant checks
        deliv_row = self.conn.execute("SELECT state, count(*) FROM deliveries WHERE delivery_id='cmd-dedupe-1'").fetchone()
        self.assertEqual(deliv_row[0], "ACKED")
        self.assertEqual(deliv_row[1], 1)

        receipts_count = self.conn.execute("SELECT count(*) FROM receipts WHERE attempt_id='att-cmd-dedupe-1'").fetchone()[0]
        self.assertEqual(receipts_count, 1)

        effects_count = self.conn.execute("SELECT count(*) FROM effects WHERE attempt_id='att-cmd-dedupe-1'").fetchone()[0]
        self.assertEqual(effects_count, 1)

    # -------------------------------------------------------------------------
    # Counterexample 2: stale fence writes / promotions 0
    # -------------------------------------------------------------------------
    def test_counterexample_2_stale_fence_zero_writes_and_zero_promotions(self) -> None:
        task_id = "U12-fence"
        res_id = "res-fence"
        att_id = "att-fence-1"
        ensure_plan(self.conn, task_id=task_id, acceptance_hash=H)
        ensure_attempt(self.conn, attempt_id=att_id, task_id=task_id, idempotency_key="idem-fence-1")

        # Claim initial lease with fence F1
        f1 = claim_lease(self.conn, lease_id="lease-1", attempt_id=att_id, resource_id=res_id, owner="worker-1")
        self.assertEqual(f1, 1)

        # Bump fence to F2 (e.g. lease revoked / expired / new claim)
        f2 = bump_fence(self.conn, resource_id=res_id)
        self.assertEqual(f2, 2)
        # F1 is now stale!

        # 1. Stale checkpoint write rejected
        with self.assertRaises(StaleFenceError):
            record_checkpoint(
                self.conn,
                checkpoint_id="chk-1",
                attempt_id=att_id,
                resource_id=res_id,
                fence=f1,
                base_manifest_hash=H,
                artifact_set_hash=H,
            )
        chk_count = self.conn.execute("SELECT count(*) FROM checkpoints WHERE resource_id=?", (res_id,)).fetchone()[0]
        self.assertEqual(chk_count, 0, "Stale fence checkpoint write must be 0")

        # 2. Stale receipt write rejected
        with self.assertRaises(StaleFenceError):
            record_receipt(
                self.conn,
                receipt_id="rcpt-1",
                attempt_id=att_id,
                resource_id=res_id,
                fencing_token=f1,
                acceptance_hash=H,
                checks_ref="ref:1",
                verdict="PASS",
                signer="signer-1",
            )
        rcpt_count = self.conn.execute("SELECT count(*) FROM receipts WHERE resource_id=?", (res_id,)).fetchone()[0]
        self.assertEqual(rcpt_count, 0, "Stale fence receipt write must be 0")

        # 3. Stale effect write rejected
        with self.assertRaises(StaleFenceError):
            record_effect(
                self.conn,
                effect_id="eff-1",
                attempt_id=att_id,
                resource_id=res_id,
                fencing_token=f1,
                kind="MUTATION",
                idempotency_key="idem-eff-1",
                provider_ref="ref:1",
                state="CONFIRMED",
                retryable=False,
            )
        eff_count = self.conn.execute("SELECT count(*) FROM effects WHERE resource_id=?", (res_id,)).fetchone()[0]
        self.assertEqual(eff_count, 0, "Stale fence effect write must be 0")

        # 4. Stale promotion rejected
        with self.assertRaises(StaleFenceError):
            validate_promotion(
                self.conn,
                attempt_id=att_id,
                resource_id=res_id,
                fencing_token=f1,
                acceptance_hash=H,
            )

        # 5. Engine execution with fence bump during worker wait
        engine = DurableExecutionEngine(self.core)
        cmd = make_command("cmd-fence-bump", "idem-fence-bump", task_id=task_id)

        def bump_during_wait() -> None:
            # Another worker or lease expiration bumps fence while worker is running
            bump_fence(self.conn, resource_id=f"res-{task_id}")

        with self.assertRaises(StaleFenceError):
            engine.execute(cmd, on_wait_hook=bump_during_wait)

        # Verify delivery is NOT ACKed and no success was recorded
        deliv = self.conn.execute("SELECT state FROM deliveries WHERE delivery_id='cmd-fence-bump'").fetchone()
        self.assertNotEqual(deliv[0], "ACKED")
        att_state = self.conn.execute("SELECT state FROM attempts WHERE attempt_id='att-cmd-fence-bump'").fetchone()
        self.assertNotEqual(att_state[0], "SUCCEEDED")

    # -------------------------------------------------------------------------
    # Counterexample 3: crash/timeout false ACK / success 0
    # -------------------------------------------------------------------------
    def test_counterexample_3_crash_timeout_partial_result_zero_false_ack_and_zero_false_success(self) -> None:
        engine = DurableExecutionEngine(self.core)

        # 1. Crash mode (worker exits non-zero)
        cmd_crash = make_command("cmd-crash", "idem-crash")
        with self.assertRaises(WorkerExecutionError) as cm:
            engine.execute(cmd_crash, mode="crash")
        self.assertEqual(cm.exception.error_class, "WORKER_CRASH")

        crash_deliv = self.conn.execute("SELECT state FROM deliveries WHERE delivery_id='cmd-crash'").fetchone()[0]
        crash_att = self.conn.execute("SELECT state FROM attempts WHERE attempt_id='att-cmd-crash'").fetchone()[0]
        self.assertNotEqual(crash_deliv, "ACKED", "Crash must not produce false ACK")
        self.assertNotEqual(crash_att, "SUCCEEDED", "Crash must not produce false SUCCEEDED")
        self.assertEqual(crash_att, "FAILED")

        # 2. Timeout mode (subprocess times out and is terminated)
        cmd_timeout = make_command("cmd-timeout", "idem-timeout")
        with self.assertRaises(WorkerExecutionError) as cm:
            engine.execute(cmd_timeout, mode="timeout", timeout_sec=0.2)
        self.assertEqual(cm.exception.error_class, "TIMEOUT")

        timeout_deliv = self.conn.execute("SELECT state FROM deliveries WHERE delivery_id='cmd-timeout'").fetchone()[0]
        timeout_att = self.conn.execute("SELECT state FROM attempts WHERE attempt_id='att-cmd-timeout'").fetchone()[0]
        self.assertNotEqual(timeout_deliv, "ACKED", "Timeout must not produce false ACK")
        self.assertNotEqual(timeout_att, "SUCCEEDED", "Timeout must not produce false SUCCEEDED")
        self.assertEqual(timeout_att, "NEEDS_RECONCILIATION")

        # 3. Partial result mode (exit 0 with malformed / incomplete envelope)
        cmd_partial = make_command("cmd-partial", "idem-partial")
        with self.assertRaises(WorkerExecutionError) as cm:
            engine.execute(cmd_partial, mode="partial_result")
        self.assertEqual(cm.exception.error_class, "VALIDATION")

        partial_deliv = self.conn.execute("SELECT state FROM deliveries WHERE delivery_id='cmd-partial'").fetchone()[0]
        partial_att = self.conn.execute("SELECT state FROM attempts WHERE attempt_id='att-cmd-partial'").fetchone()[0]
        self.assertNotEqual(partial_deliv, "ACKED", "Partial result must not produce false ACK")
        self.assertNotEqual(partial_att, "SUCCEEDED", "Partial result must not produce false SUCCEEDED")
        self.assertEqual(partial_att, "FAILED")

        # Check aggregate false ACKs and false successes
        total_false_acks = self.conn.execute("SELECT count(*) FROM deliveries WHERE state='ACKED'").fetchone()[0]
        total_false_succeeded = self.conn.execute("SELECT count(*) FROM attempts WHERE state='SUCCEEDED'").fetchone()[0]
        self.assertEqual(total_false_acks, 0, "False ACKs must be strictly 0")
        self.assertEqual(total_false_succeeded, 0, "False SUCCEEDED must be strictly 0")

    # -------------------------------------------------------------------------
    # Counterexample 4: UNKNOWN effect auto retry 0
    # -------------------------------------------------------------------------
    def test_counterexample_4_unknown_effect_zero_auto_retries(self) -> None:
        engine = DurableExecutionEngine(self.core)
        cmd = make_command("cmd-unk-effect", "idem-unk-effect")

        with self.assertRaises(WorkerExecutionError) as cm:
            engine.execute(cmd, mode="unknown_effect")
        self.assertEqual(cm.exception.error_class, "SIDE_EFFECT_UNKNOWN")
        self.assertFalse(cm.exception.retryable)

        # Check DB state
        att_state = self.conn.execute("SELECT state FROM attempts WHERE attempt_id='att-cmd-unk-effect'").fetchone()[0]
        self.assertEqual(att_state, "NEEDS_RECONCILIATION")

        eff_row = self.conn.execute(
            "SELECT state, retryable FROM effects WHERE attempt_id='att-cmd-unk-effect'"
        ).fetchone()
        self.assertEqual(eff_row[0], "UNKNOWN")
        self.assertEqual(eff_row[1], 0, "UNKNOWN effect retryable flag must be strictly 0")

        # Delivery is NOT ACKed
        deliv_state = self.conn.execute("SELECT state FROM deliveries WHERE delivery_id='cmd-unk-effect'").fetchone()[0]
        self.assertNotEqual(deliv_state, "ACKED")

        # Re-execution / auto-retry must be rejected because attempt is in NEEDS_RECONCILIATION
        with self.assertRaises(DuplicateDeliveryError):
            engine.execute(cmd, mode="unknown_effect")

        # Confirm 0 auto retries occurred
        attempts_count = self.conn.execute(
            "SELECT count(*) FROM attempts WHERE idempotency_key='idem-unk-effect'"
        ).fetchone()[0]
        self.assertEqual(attempts_count, 1, "UNKNOWN effect auto retry count must be 0")

    # -------------------------------------------------------------------------
    # Counterexample 5: saturation infinite wait / DB bypass 0
    # -------------------------------------------------------------------------
    def test_counterexample_5_saturation_zero_infinite_wait_and_zero_db_bypass(self) -> None:
        dispatcher = BoundedDispatcher(self.core, capacity=2, default_enqueue_timeout=0.05)
        # Close self.core so dispatcher can own it
        self.core.close()
        dispatcher.start()

        client_thread_ids = set()

        try:
            # Block the worker thread with a slow task on a separate thread
            block_event = threading.Event()
            blocker_started = threading.Event()

            def blocking_task(core: BrokerCore) -> None:
                blocker_started.set()
                block_event.wait(timeout=2.0)

            blocker = threading.Thread(target=lambda: dispatcher.submit_and_wait(blocking_task, timeout=3.0))
            blocker.start()
            self.assertTrue(blocker_started.wait(timeout=1.0), "Worker did not pick up blocker task")

            # Fill the 2 slots in queue
            fill1 = threading.Thread(
                target=lambda: dispatcher.submit_and_wait(lambda c: time.sleep(0.5), timeout=2.0)
            )
            fill2 = threading.Thread(
                target=lambda: dispatcher.submit_and_wait(lambda c: time.sleep(0.5), timeout=2.0)
            )
            fill1.start()
            fill2.start()
            time.sleep(0.05)

            # Now queue is saturated (capacity 2 is full). Submit 3rd item with bounded timeout (0.05s)
            start_time = time.monotonic()
            client_thread_ids.add(threading.get_ident())
            with self.assertRaises(QueueSaturationError) as cm:
                dispatcher.submit_and_wait(lambda c: "never-runs", enqueue_timeout=0.05)
            elapsed = time.monotonic() - start_time

            # Verify fast failure (NOT infinite wait)
            self.assertLess(elapsed, 0.25, "Queue saturation must fail fast without infinite wait")
            self.assertTrue(cm.exception.retryable)

            # Release block and finish
            block_event.set()
            blocker.join(timeout=2.0)
            fill1.join(timeout=2.0)
            fill2.join(timeout=2.0)

            # Verify client thread NEVER bypassed queue to touch DB directly
            self.assertTrue(client_thread_ids.isdisjoint(dispatcher.writer_thread_ids))
            self.assertEqual(
                dispatcher.writer_thread_ids,
                {dispatcher.owner_thread_id},
                "DB bypass must be 0: only broker owner thread touched DB",
            )
        finally:
            dispatcher.stop()
            self.core.start()
            self.conn = self.core.connection

    # -------------------------------------------------------------------------
    # Counterexample 6: concurrent clients writable owner 하나
    # -------------------------------------------------------------------------
    def test_counterexample_6_concurrent_clients_writable_owner_exactly_one(self) -> None:
        dispatcher = BoundedDispatcher(self.core, capacity=64)
        self.core.close()
        dispatcher.start()

        num_clients = 10
        errors = []

        def client_worker(client_idx: int) -> None:
            try:
                # Direct DB access attempt from client thread must fail
                try:
                    self.core.connection.execute("SELECT 1")
                    errors.append(f"Client {client_idx} bypassed writer ownership!")
                    return
                except BrokerOwnershipError:
                    pass  # Correctly rejected!

                # Legitimate submission through bounded queue
                def work(core: BrokerCore) -> str:
                    with core.connection:
                        core.connection.execute(
                            "INSERT OR IGNORE INTO resources(resource_id, kind, canonical_value, next_fencing_token) "
                            "VALUES(?, 'PORT', ?, 0)",
                            (f"port-{client_idx}", f"800{client_idx}"),
                        )
                    return "ok"

                res = dispatcher.submit_and_wait(work, timeout=5.0)
                if res != "ok":
                    errors.append(f"Client {client_idx} unexpected result: {res}")
            except Exception as exc:
                errors.append(f"Client {client_idx} exception: {exc}")

        threads = [threading.Thread(target=client_worker, args=(i,)) for i in range(num_clients)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        dispatcher.stop()
        self.core.start()
        self.conn = self.core.connection

        self.assertEqual(errors, [], f"Concurrent client errors: {errors}")
        self.assertEqual(
            len(dispatcher.writer_thread_ids),
            1,
            f"Exactly one thread must own SQLite writes; got {dispatcher.writer_thread_ids}",
        )
        self.assertEqual(dispatcher.writer_thread_ids, {dispatcher.owner_thread_id})

    # -------------------------------------------------------------------------
    # Counterexample 7: half-open canary 외 재개 금지
    # -------------------------------------------------------------------------
    def test_counterexample_7_half_open_canary_only_resumption(self) -> None:
        cb = CircuitBreakerManager(failure_threshold=3, default_cooldown_sec=60.0)
        provider = "canary-prov"
        failure_class = "WORKER_CRASH"

        # Record 2 failures: circuit should still be CLOSED
        cb.record_failure(self.conn, provider, failure_class)
        cb.record_failure(self.conn, provider, failure_class)
        self.assertEqual(cb.failure_count(provider, failure_class), 2)
        cb.check_circuit(self.conn, provider, failure_class)  # Allowed

        # 3rd failure of the same root-cause: circuit moves to OPEN!
        cb.record_failure(self.conn, provider, failure_class, cooldown_sec=60.0)
        self.assertEqual(cb.failure_count(provider, failure_class), 3)

        circuit_state = self.conn.execute(
            "SELECT state FROM circuits WHERE provider=? AND failure_class=?",
            (provider, failure_class),
        ).fetchone()[0]
        self.assertEqual(circuit_state, "OPEN")

        # While OPEN, any request is rejected
        with self.assertRaises(CircuitOpenError):
            cb.check_circuit(self.conn, provider, failure_class, is_canary=False)
        with self.assertRaises(CircuitOpenError):
            cb.check_circuit(self.conn, provider, failure_class, is_canary=True)

        # Fast-forward cooldown by updating retry_after to the past
        self.conn.execute(
            "UPDATE circuits SET retry_after=datetime('now', '-5 seconds') WHERE provider=? AND failure_class=?",
            (provider, failure_class),
        )

        # In HALF_OPEN: Ordinary (non-canary) work MUST be rejected!
        with self.assertRaises(CircuitOpenError) as cm:
            cb.check_circuit(self.conn, provider, failure_class, is_canary=False)
        self.assertIn("CANARY_REQUIRED_IN_HALF_OPEN", str(cm.exception))

        # In HALF_OPEN: ONLY a canary request is permitted!
        cb.check_circuit(self.conn, provider, failure_class, is_canary=True)  # Allowed!

        # If canary fails: circuit returns to OPEN immediately
        cb.record_failure(self.conn, provider, failure_class, cooldown_sec=60.0)
        state_after_fail = self.conn.execute(
            "SELECT state FROM circuits WHERE provider=? AND failure_class=?",
            (provider, failure_class),
        ).fetchone()[0]
        self.assertEqual(state_after_fail, "OPEN")

        # Fast-forward again to HALF_OPEN
        self.conn.execute(
            "UPDATE circuits SET retry_after=datetime('now', '-5 seconds') WHERE provider=? AND failure_class=?",
            (provider, failure_class),
        )
        cb.check_circuit(self.conn, provider, failure_class, is_canary=True)

        # Canary succeeds: circuit moves to CLOSED
        cb.record_success(self.conn, provider, failure_class, was_canary=True)
        state_after_success = self.conn.execute(
            "SELECT state FROM circuits WHERE provider=? AND failure_class=?",
            (provider, failure_class),
        ).fetchone()[0]
        self.assertEqual(state_after_success, "CLOSED")

        # Now ordinary work is allowed to resume
        cb.check_circuit(self.conn, provider, failure_class, is_canary=False)  # Allowed!

    # -------------------------------------------------------------------------
    # Additional Verification: Subprocess wait occurs outside DB transaction
    # -------------------------------------------------------------------------
    def test_subprocess_wait_occurs_outside_db_transaction(self) -> None:
        engine = DurableExecutionEngine(self.core)
        cmd = make_command("cmd-tx-check", "idem-tx-check")
        tx_states = []

        def wait_hook() -> None:
            # Check transaction state of connection during subprocess wait
            tx_states.append(self.conn.in_transaction)
            # Concurrent read should succeed immediately without SQLITE_BUSY
            row = self.conn.execute("SELECT count(*) FROM plans").fetchone()
            tx_states.append(row[0] >= 0)

        res = engine.execute(cmd, on_wait_hook=wait_hook)
        self.assertTrue(res["ok"])
        self.assertEqual(tx_states[0], False, "Subprocess wait must occur outside any SQLite transaction")
        self.assertEqual(tx_states[1], True, "Concurrent read during subprocess wait must succeed")

    def test_timeout_effectful_worker_is_unknown_not_retryable(self) -> None:
        launcher = MockSubprocessLauncher(default_timeout_sec=0.1)
        effectful = launcher.launch(
            attempt_id="timeout-effectful",
            acceptance_hash=H,
            mode="timeout",
            worker_capability="effectful",
        )
        self.assertEqual(
            (effectful.result_status, effectful.effect_state, effectful.retryable),
            ("NEEDS_RECONCILIATION", "UNKNOWN", False),
        )
        read_only = launcher.launch(
            attempt_id="timeout-readonly",
            acceptance_hash=H,
            mode="timeout",
            worker_capability="read_only",
        )
        self.assertEqual((read_only.effect_state, read_only.retryable), ("NONE", True))

    def test_launcher_heartbeats_repeatedly_while_worker_is_running(self) -> None:
        heartbeats = []
        script = "import time; time.sleep(0.6); " + build_worker_script(
            "success", attempt_id="heartbeat-loop", acceptance_hash=H
        )
        decision = MockSubprocessLauncher(default_timeout_sec=2).launch(
            attempt_id="heartbeat-loop",
            acceptance_hash=H,
            custom_script=script,
            worker_capability="read_only",
            heartbeat=lambda: heartbeats.append(time.monotonic_ns()) or True,
            heartbeat_interval_sec=0.1,
        )
        self.assertTrue(decision.successful)
        self.assertGreaterEqual(len(heartbeats), 3)

    @unittest.skipUnless(os.name == "nt", "Windows Job Object process-tree test")
    def test_timeout_kills_worker_process_tree(self) -> None:
        pid_file = Path(self.temp_dir.name) / "child.pid"
        child_script = "import time; time.sleep(30)"
        parent_script = (
            "import pathlib,subprocess,sys,time; "
            f"p=subprocess.Popen([sys.executable,'-c',{child_script!r}]); "
            f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid)); "
            "time.sleep(30)"
        )
        # U82: the kill must land after the child exists. Measured 2026-09-29 on 12 busy cores, the parent needs up to
        # 0.44 s (median 0.34) to start, spawn the child and write its pid; the old 0.3 s killed it first in 2 of 15
        # loaded runs (FileNotFoundError on child.pid). 3.0 s is about 7x that worst case; the parent then sleeps 30 s,
        # so the timeout still fires.
        decision = MockSubprocessLauncher(default_timeout_sec=3.0).launch(
            attempt_id="tree-timeout",
            acceptance_hash=H,
            custom_script=parent_script,
            worker_capability="read_only",
        )
        self.assertEqual(decision.error_class, "TIMEOUT")
        self.assertTrue(pid_file.is_file(), "the parent was killed before it spawned the child: premise not met")
        child_pid = int(pid_file.read_text())
        probe = subprocess.run(
            ["tasklist", "/FI", f"PID eq {child_pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertNotIn(f'"{child_pid}"', probe.stdout, f"child PID {child_pid} survived timeout")

    def test_expired_lease_state_persists_after_rejection(self) -> None:
        ensure_plan(self.conn, task_id="expiry", acceptance_hash=H)
        ensure_attempt(self.conn, attempt_id="att-expiry", task_id="expiry", idempotency_key="idem-expiry")
        fence = claim_lease(
            self.conn,
            lease_id="lease-expiry",
            attempt_id="att-expiry",
            resource_id="res-expiry",
            owner="owner-a",
            duration_sec=0,
        )
        self.conn.execute("BEGIN IMMEDIATE")
        with self.assertRaises(StaleFenceError):
            assert_fence(self.conn, attempt_id="att-expiry", resource_id="res-expiry", token=fence)
        if self.conn.in_transaction:
            self.conn.rollback()
        self.assertEqual(
            self.conn.execute("SELECT state FROM leases WHERE lease_id='lease-expiry'").fetchone()[0],
            "EXPIRED",
        )

    def test_late_stale_result_records_unknown_reconciliation_without_success(self) -> None:
        engine = DurableExecutionEngine(self.core)
        cmd = make_command("cmd-late-stale", "idem-late-stale")

        def supersede_fence() -> None:
            bump_fence(self.conn, resource_id=cmd["resource_id"])

        with self.assertRaisesRegex(WorkerExecutionError, "LATE_RESULT_NEEDS_RECONCILIATION"):
            engine.execute(cmd, on_wait_hook=supersede_fence)
        self.assertEqual(self.conn.execute(
            "SELECT state FROM attempts WHERE attempt_id='att-cmd-late-stale'"
        ).fetchone()[0], "NEEDS_RECONCILIATION")
        self.assertEqual(self.conn.execute(
            "SELECT count(*) FROM effects WHERE attempt_id='att-cmd-late-stale' AND state='UNKNOWN' AND retryable=0"
        ).fetchone()[0], 1)
        self.assertEqual(self.conn.execute(
            "SELECT count(*) FROM receipts WHERE attempt_id='att-cmd-late-stale' AND verdict='PASS'"
        ).fetchone()[0], 0)
        self.assertEqual(self.conn.execute(
            "SELECT count(*) FROM deliveries WHERE delivery_id='cmd-late-stale' AND state='ACKED'"
        ).fetchone()[0], 0)
        with self.assertRaises(DuplicateDeliveryError):
            engine.execute(cmd)

    def test_lease_heartbeat_renews_conditionally_and_failed_renew_reconciles_late_result(self) -> None:
        class HeartbeatLauncher:
            def __init__(self, before_heartbeat=None):
                self.before_heartbeat = before_heartbeat

            def launch(self, **kwargs):
                if self.before_heartbeat:
                    self.before_heartbeat()
                kwargs["heartbeat"]()
                from v7_harness.contracts.execution import WorkerDecision
                return WorkerDecision(True, "SUCCEEDED", "CONFIRMED", False, "NONE")

        ok_engine = DurableExecutionEngine(self.core, launcher=HeartbeatLauncher(), default_lease_duration=30)
        ok = ok_engine.execute(make_command("cmd-renew-ok", "idem-renew-ok"), heartbeat_duration=5)
        self.assertTrue(ok["ok"])

        stale_cmd = make_command("cmd-renew-stale", "idem-renew-stale", task_id="renew-stale")
        def change_owner_and_fence() -> None:
            self.conn.execute(
                "UPDATE leases SET owner='other-owner' WHERE resource_id=? AND state='ACTIVE'",
                (stale_cmd["resource_id"],),
            )
            bump_fence(self.conn, resource_id=stale_cmd["resource_id"])

        failed_engine = DurableExecutionEngine(
            self.core,
            launcher=HeartbeatLauncher(change_owner_and_fence),
            default_lease_duration=30,
        )
        with self.assertRaisesRegex(WorkerExecutionError, "LATE_RESULT_NEEDS_RECONCILIATION"):
            failed_engine.execute(stale_cmd, heartbeat_duration=5)
        self.assertEqual(self.conn.execute(
            "SELECT state FROM attempts WHERE attempt_id='att-cmd-renew-stale'"
        ).fetchone()[0], "NEEDS_RECONCILIATION")

    # -------------------------------------------------------------------------
    # Additional Verification: Quota fail-closed
    # -------------------------------------------------------------------------
    def test_quota_fail_closed(self) -> None:
        engine = DurableExecutionEngine(self.core)

        # 1. Missing quota record -> fail closed
        cmd_missing = make_command("cmd-q-missing", "idem-q-missing", scope_id="unknown-scope")
        with self.assertRaises(QuotaFailClosedError) as cm:
            engine.execute(cmd_missing)
        self.assertIn("QUOTA_UNKNOWN", str(cm.exception))

        # 2. Quota UNKNOWN -> fail closed
        set_quota_state(self.conn, scope_id="unk-scope", provider="mock-provider", quota_state="UNKNOWN")
        cmd_unk = make_command("cmd-q-unk", "idem-q-unk", scope_id="unk-scope")
        with self.assertRaises(QuotaFailClosedError) as cm:
            engine.execute(cmd_unk)
        self.assertIn("QUOTA_UNKNOWN", str(cm.exception))

        # 3. Quota EXHAUSTED -> fail closed
        set_quota_state(self.conn, scope_id="exh-scope", provider="mock-provider", quota_state="EXHAUSTED")
        cmd_exh = make_command("cmd-q-exh", "idem-q-exh", scope_id="exh-scope")
        with self.assertRaises(QuotaFailClosedError) as cm:
            engine.execute(cmd_exh)
        self.assertIn("QUOTA_EXHAUSTED", str(cm.exception))

    # -------------------------------------------------------------------------
    # Additional Verification: Graceful drain
    # -------------------------------------------------------------------------
    def test_graceful_drain(self) -> None:
        dispatcher = BoundedDispatcher(self.core, capacity=16)
        self.core.close()
        dispatcher.start()
        engine = DurableExecutionEngine(dispatcher)

        try:
            # Drain stops accepting new work immediately with fast failure
            engine.drain(timeout=2.0)
            cmd = make_command("cmd-drain", "idem-drain")
            with self.assertRaises(DrainInProgressError):
                engine.execute(cmd)
        finally:
            self.core.start()
            self.conn = self.core.connection

    def test_commit_before_response_loss_replays_without_second_effect(self) -> None:
        engine = DurableExecutionEngine(self.core)
        cmd = make_command("cmd-lost-response", "idem-lost-response")
        effects = []

        def lose_response() -> None:
            raise ConnectionError("simulated response loss")

        with self.assertRaises(ConnectionError):
            engine.execute(cmd, effect_callback=lambda: effects.append("once"), after_commit_hook=lose_response)
        replay = engine.execute(cmd, effect_callback=lambda: effects.append("twice"))
        self.assertTrue(replay["replayed"])
        self.assertEqual(effects, ["once"], "Callback success exactly once; replay remains callback once total")
        self.assertEqual(self.conn.execute("SELECT state FROM deliveries WHERE delivery_id='cmd-lost-response'").fetchone()[0], "ACKED")
        self.assertEqual(self.conn.execute("SELECT count(*) FROM deliveries WHERE state='ACKED'").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM attempts WHERE state='SUCCEEDED'").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM receipts WHERE verdict='PASS'").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM effects WHERE state='CONFIRMED'").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM effects WHERE state='UNKNOWN'").fetchone()[0], 0)

    def test_effect_callback_failure_is_unknown_without_false_success(self) -> None:
        engine = DurableExecutionEngine(self.core)
        cmd = make_command("cmd-effect-fails", "idem-effect-fails")
        tx_during_callback: list[bool] = []

        def fail_after_observable_boundary() -> None:
            tx_during_callback.append(self.conn.in_transaction)
            raise RuntimeError("provider disconnected before effect receipt")

        with self.assertRaisesRegex(WorkerExecutionError, "UNKNOWN_EFFECT_NEEDS_RECONCILIATION"):
            engine.execute(cmd, effect_callback=fail_after_observable_boundary)

        # 1) Callback executed outside DB transaction
        self.assertEqual(tx_during_callback, [False], "effect_callback must execute outside DB transaction")

        # 2) DB state: ACK 0, SUCCEEDED 0, PASS 0, CONFIRMED 0, UNKNOWN 1
        self.assertEqual(self.conn.execute("SELECT count(*) FROM deliveries WHERE state='ACKED'").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM attempts WHERE state='SUCCEEDED'").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM receipts WHERE verdict='PASS'").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM effects WHERE state='CONFIRMED'").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM effects WHERE state='UNKNOWN'").fetchone()[0], 1)

        # Explicit delivery and attempt entity states
        self.assertEqual(
            self.conn.execute("SELECT state FROM deliveries WHERE delivery_id='cmd-effect-fails'").fetchone()[0],
            "CLAIMED",
        )
        self.assertEqual(
            self.conn.execute("SELECT state FROM attempts WHERE attempt_id='att-cmd-effect-fails'").fetchone()[0],
            "NEEDS_RECONCILIATION",
        )
        self.assertEqual(
            self.conn.execute("SELECT count(*) FROM effects WHERE attempt_id='att-cmd-effect-fails' AND state='UNKNOWN' AND retryable=0").fetchone()[0],
            1,
        )

        # 3) Second execute cannot auto-retry and does NOT run callback again
        second_callback_ran = False

        def should_not_run() -> None:
            nonlocal second_callback_ran
            second_callback_ran = True

        with self.assertRaises(DuplicateDeliveryError):
            engine.execute(cmd, effect_callback=should_not_run)
        self.assertFalse(second_callback_ran, "Second execute / replay must not run callback again")

    def test_proven_not_applied_effect_failure_is_the_only_retryable_callback_mode(self) -> None:
        engine = DurableExecutionEngine(self.core)
        cmd = make_command("cmd-effect-not-applied", "idem-effect-not-applied")

        with self.assertRaises(WorkerExecutionError) as raised:
            engine.execute(
                cmd,
                effect_callback=lambda: (_ for _ in ()).throw(RuntimeError("provider rejected before apply")),
                effect_failure_mode="not_applied",
            )
        self.assertTrue(raised.exception.retryable)
        self.assertEqual(raised.exception.error_class, "EFFECT_NOT_APPLIED")
        self.assertEqual(self.conn.execute(
            "SELECT count(*) FROM effects WHERE attempt_id='att-cmd-effect-not-applied' AND state='UNKNOWN'"
        ).fetchone()[0], 0)
        self.assertEqual(self.conn.execute(
            "SELECT count(*) FROM effects WHERE attempt_id='att-cmd-effect-not-applied' AND state='FAILED'"
        ).fetchone()[0], 1)
        self.assertEqual(self.conn.execute(
            "SELECT count(*) FROM deliveries WHERE delivery_id='cmd-effect-not-applied' AND state='ACKED'"
        ).fetchone()[0], 0)
        observed = []
        retried = engine.execute(cmd, effect_callback=lambda: observed.append("applied"))
        self.assertTrue(retried["ok"])
        self.assertEqual(observed, ["applied"])
        self.assertEqual(self.conn.execute(
            "SELECT count(*) FROM effects WHERE attempt_id='att-cmd-effect-not-applied' AND state='CONFIRMED'"
        ).fetchone()[0], 1)

    def test_stage_events_capture_ordered_monotonic_latency_evidence_without_payloads(self) -> None:
        engine = DurableExecutionEngine(self.core)
        cmd = make_command("cmd-stage-evidence", "idem-stage-evidence")
        engine.execute(cmd, effect_callback=lambda: None)
        rows = self.conn.execute(
            "SELECT stage,state,monotonic_ns FROM execution_stage_events "
            "WHERE delivery_id=? ORDER BY stage_event_id",
            (cmd["command_id"],),
        ).fetchall()
        self.assertEqual([row[0] for row in rows], ["SUBMITTED", "CLAIMED", "WORKER_FINISHED", "ACKED"])
        ticks = [row[2] for row in rows]
        self.assertEqual(ticks, sorted(ticks))
        self.assertGreaterEqual(ticks[1] - ticks[0], 0)  # queue submit -> claim
        self.assertGreaterEqual(ticks[2] - ticks[1], 0)  # claim -> worker/effect finish
        self.assertGreaterEqual(ticks[3] - ticks[0], 0)  # end-to-end submit -> ack
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(execution_stage_events)")}
        self.assertTrue({"stage", "state", "monotonic_ns", "created_at"} <= columns)
        self.assertTrue({"prompt", "output", "payload"}.isdisjoint(columns))

    def test_stage_events_on_unknown_effect_records_monotonic_evidence_without_payload(self) -> None:
        engine = DurableExecutionEngine(self.core)
        cmd = make_command("cmd-stage-unk", "idem-stage-unk")
        with self.assertRaises(WorkerExecutionError):
            engine.execute(cmd, effect_callback=lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        rows = self.conn.execute(
            "SELECT stage,state,monotonic_ns FROM execution_stage_events "
            "WHERE delivery_id=? ORDER BY stage_event_id",
            (cmd["command_id"],),
        ).fetchall()
        self.assertEqual([row[0] for row in rows], ["SUBMITTED", "CLAIMED", "WORKER_FINISHED", "NEEDS_RECONCILIATION"])
        ticks = [row[2] for row in rows]
        self.assertEqual(ticks, sorted(ticks))
        self.assertGreaterEqual(ticks[1] - ticks[0], 0)
        self.assertGreaterEqual(ticks[2] - ticks[1], 0)
        self.assertGreaterEqual(ticks[3] - ticks[2], 0)
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(execution_stage_events)")}
        self.assertTrue({"stage", "state", "monotonic_ns", "created_at"} <= columns)
        self.assertTrue({"prompt", "output", "payload"}.isdisjoint(columns))

    def test_retry_budget_is_durable_and_multidimensional(self) -> None:
        engine = DurableExecutionEngine(
            self.core,
            retry_budget=RetryBudget(max_attempts=1, max_elapsed_ms=10, max_turns=1, max_tokens=5, max_tool_calls=1),
        )
        first = make_command("cmd-budget-1", "idem-budget-1")
        first.update({"tokens": 5, "elapsed_ms": 10})
        self.assertTrue(engine.execute(first)["ok"])
        second = make_command("cmd-budget-2", "idem-budget-2")
        with self.assertRaisesRegex(CircuitOpenError, "RETRY_BUDGET_EXHAUSTED"):
            engine.execute(second)

        # A new manager/engine still observes the SQLite-backed reservation.
        restarted = DurableExecutionEngine(
            self.core,
            retry_budget=RetryBudget(max_attempts=1, max_elapsed_ms=10, max_turns=1, max_tokens=5, max_tool_calls=1),
        )
        with self.assertRaisesRegex(CircuitOpenError, "RETRY_BUDGET_EXHAUSTED"):
            restarted.execute(make_command("cmd-budget-3", "idem-budget-3"))

    def test_circuit_failure_count_survives_manager_restart_and_single_canary_slot(self) -> None:
        provider, failure = "durable-provider", "ROOT"
        manager = CircuitBreakerManager(failure_threshold=3, default_cooldown_sec=1)
        for _ in range(3):
            manager.record_failure(self.conn, provider, failure, cooldown_sec=1)
        restarted = CircuitBreakerManager(failure_threshold=3, default_cooldown_sec=1)
        self.assertEqual(restarted.durable_failure_count(self.conn, provider, failure), 3)
        self.conn.execute(
            "UPDATE circuits SET retry_after=datetime('now','-1 second') WHERE provider=? AND failure_class=?",
            (provider, failure),
        )
        restarted.check_circuit(self.conn, provider, failure, is_canary=True)
        with self.assertRaises(CircuitOpenError):
            restarted.check_circuit(self.conn, provider, failure, is_canary=True)

    def test_circuit_counts_consecutive_failures_after_durable_success_reset(self) -> None:
        provider, failure = "reset-provider", "ROOT"
        manager = CircuitBreakerManager(failure_threshold=3)
        manager.record_failure(self.conn, provider, failure)
        manager.record_failure(self.conn, provider, failure)
        manager.record_success(self.conn, provider, failure)
        restarted = CircuitBreakerManager(failure_threshold=3)
        restarted.record_failure(self.conn, provider, failure)
        self.assertEqual(restarted.durable_failure_count(self.conn, provider, failure), 1)
        row = self.conn.execute(
            "SELECT state FROM circuits WHERE provider=? AND failure_class=?", (provider, failure)
        ).fetchone()
        self.assertTrue(row is None or row[0] == "CLOSED")

    def test_ipc_concurrency_does_not_let_silent_client_block_dispatcher(self) -> None:
        # Use a separate DB/process because this test exercises the real IPC-to-
        # dispatcher boundary rather than the in-process engine fixture.
        self.core.close()
        address = make_local_pipe_name(f"u12-{os.getpid()}-{time.time_ns()}")
        authkey = b"u12-concurrent-auth-key-32bytes!"
        ready = multiprocessing.Event()
        process = multiprocessing.Process(target=run_u12_broker, args=(str(self.db_path), address, authkey, ready))
        process.start()
        self.assertTrue(ready.wait(10))
        family = "AF_PIPE" if os.name == "nt" else "AF_UNIX"
        silent = Client(address, family=family, authkey=None)
        try:
            started = time.monotonic()
            results: list[dict[str, Any]] = []
            failures: list[BaseException] = []

            def enqueue(index: int) -> None:
                try:
                    ipc_command = {
                        key: value
                        for key, value in make_command(f"ipc-{index}", f"ipc-idem-{index}").items()
                        if key in {"schema_version", "command_id", "task_id", "card_revision", "acceptance_hash", "idempotency_key", "operation", "payload_ref"}
                    }
                    # B59: 응답 제한시간은 부하 여유분일 뿐이다. 선두 차단(head-of-line) 여부는
                    # 아래 0.9초 벽시계 단언이 판정하므로 여유분을 늘려도 검사 강도는 같다.
                    results.append(BrokerClient(address, authkey, response_timeout=10).request({
                        "protocol_version": 1,
                        "kind": "ENQUEUE",
                        "command": ipc_command,
                    }))
                except BaseException as exc:
                    failures.append(exc)

            clients = [threading.Thread(target=enqueue, args=(index,)) for index in range(8)]
            for client in clients:
                client.start()
            for client in clients:
                client.join(3)
            self.assertLess(time.monotonic() - started, 0.9, "silent peer caused head-of-line wait")
            self.assertEqual(failures, [])
            self.assertEqual(len(results), 8)
            self.assertTrue(all(result["ok"] for result in results))
        finally:
            silent.close()
            try:
                BrokerClient(address, authkey).request({"protocol_version": 1, "kind": "STOP"})
            except (EOFError, OSError):
                pass
            process.join(5)
            if process.is_alive():
                process.terminate()
                process.join(5)
            self.assertEqual(process.exitcode, 0)
            self.core.start()
            self.conn = self.core.connection


class MigrationV2ExecutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "migration_test.db"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_fresh_db_has_v2_and_budget_table(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            apply_migrations(conn)
            versions = conn.execute("SELECT version, checksum FROM schema_migrations ORDER BY version").fetchall()
            self.assertEqual(versions, [(1, MIGRATIONS[0].checksum), (2, MIGRATIONS[1].checksum)])
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("execution_budget_usage", tables)
            self.assertIn("execution_stage_events", tables)
            # reserve_retry_budget works on fresh DB without hot-path CREATE TABLE
            reserve_retry_budget(
                conn,
                scope_id="scope-fresh",
                provider="prov-fresh",
                budget=RetryBudget(max_attempts=3),
            )
            usage = conn.execute(
                "SELECT attempts FROM execution_budget_usage WHERE scope_id='scope-fresh' AND provider='prov-fresh'"
            ).fetchone()[0]
            self.assertEqual(usage, 1)
        finally:
            conn.close()

    def test_v1_to_v2_upgrade_is_idempotent_and_checksum_pinned(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            # Setup legacy v1 DB
            conn.executescript(MIGRATIONS[0].sql)
            conn.execute(
                "INSERT INTO schema_migrations(version,checksum,applied_at,app_version) VALUES(1,?,'now','legacy-0.1.0')",
                (MIGRATIONS[0].checksum,),
            )
            conn.commit()
            # Verify execution_budget_usage does not exist in v1
            v1_tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertNotIn("execution_budget_usage", v1_tables)

            # Upgrade v1 -> v2
            apply_migrations(conn)
            versions = conn.execute("SELECT version, checksum FROM schema_migrations ORDER BY version").fetchall()
            self.assertEqual(versions, [(1, MIGRATIONS[0].checksum), (2, MIGRATIONS[1].checksum)])
            v2_tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("execution_budget_usage", v2_tables)
            self.assertIn("execution_stage_events", v2_tables)

            # Idempotent re-run
            apply_migrations(conn)
            self.assertEqual(conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0], 2)

            # Checksum mismatch on v2 is refused
            conn.execute("UPDATE schema_migrations SET checksum=? WHERE version=2", ("f" * 64,))
            conn.commit()
            with self.assertRaises(MigrationError):
                apply_migrations(conn)
        finally:
            conn.close()

    def test_newer_schema_refusal(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            apply_migrations(conn)
            conn.execute(
                "INSERT INTO schema_migrations(version,checksum,applied_at,app_version) VALUES(999,?,'now','future-999')",
                ("e" * 64,),
            )
            conn.commit()
            with self.assertRaisesRegex(MigrationError, "newer"):
                apply_migrations(conn)
        finally:
            conn.close()

    def test_no_dynamic_create_table_in_hot_path(self) -> None:
        # If execution_budget_usage does not exist (unmigrated connection), reserve_retry_budget
        # MUST fail with OperationalError rather than dynamically creating the table.
        raw_conn = sqlite3.connect(":memory:")
        try:
            with self.assertRaises(sqlite3.OperationalError):
                reserve_retry_budget(
                    raw_conn,
                    scope_id="unmigrated",
                    provider="prov",
                    budget=RetryBudget(),
                )
        finally:
            raw_conn.close()


if __name__ == "__main__":
    unittest.main()
