from __future__ import annotations

import json
import multiprocessing
import os
import sqlite3
import tempfile
import time
import unittest
from multiprocessing.connection import Client, Listener
from pathlib import Path

from v7_harness.broker import (
    BrokerAlreadyRunning,
    BrokerClient,
    BrokerCore,
    BrokerProtocolError,
    BrokerResponseTimeout,
    ForegroundBroker,
    MAX_FRAME_BYTES,
    make_local_pipe_name,
)
from v7_harness.broker.ipc import _decode, _unwrap_response


H = "a" * 64


def command(command_id: str = "c1", idempotency_key: str = "idem-1") -> dict:
    return {
        "schema_version": 1,
        "command_id": command_id,
        "task_id": "U11",
        "card_revision": 1,
        "acceptance_hash": H,
        "idempotency_key": idempotency_key,
        "operation": "VERIFY",
        "payload_ref": "artifact:payload",
    }


def run_broker(db: str, address: str, authkey: bytes, ready, crash_after_commit: bool = False, request_timeout: float = 1.0) -> None:
    ForegroundBroker(
        Path(db), address, authkey, crash_after_commit=crash_after_commit, request_timeout=request_timeout
    ).serve_forever(ready)


def run_unresponsive_server(address: str, authkey: bytes, ready) -> None:
    family = "AF_PIPE" if os.name == "nt" else "AF_UNIX"
    listener = Listener(address, family=family, authkey=None)
    ready.set()
    connection = listener.accept()
    try:
        connection.recv_bytes(MAX_FRAME_BYTES)
        time.sleep(5)
    finally:
        connection.close()
        listener.close()


def try_second_writer(db: str, result) -> None:
    core = BrokerCore(Path(db))
    try:
        core.start()
    except Exception as exc:
        result.put(f"{type(exc).__name__}:{exc}")
    else:
        result.put("STARTED")
        core.close()


class CoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "broker.db"
        self.core = BrokerCore(self.db_path)
        self.core.start()

    def tearDown(self):
        self.core.close()
        self.temp.cleanup()

    def test_second_broker_is_rejected_and_client_has_no_db_api(self):
        with self.assertRaisesRegex(BrokerAlreadyRunning, "BROKER_ALREADY_RUNNING"):
            BrokerCore(self.db_path).start()
        client = BrokerClient(make_local_pipe_name("api"), b"a" * 32)
        self.assertFalse(hasattr(client, "database_path"))
        self.assertFalse(hasattr(client, "connection"))
        self.assertFalse(hasattr(client, "execute"))

    @unittest.skipUnless(os.name == "nt", "Windows pipe namespace test")
    def test_unscoped_pipe_endpoint_and_short_auth_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "UNSAFE_PIPE_ENDPOINT"):
            ForegroundBroker(self.db_path, r"\\.\pipe\coordd-unscoped", b"a" * 32)
        with self.assertRaisesRegex(ValueError, "AUTHKEY_TOO_SHORT"):
            BrokerClient(make_local_pipe_name("short-auth"), b"short")

    def test_second_process_cannot_acquire_writer_ownership(self):
        result = multiprocessing.Queue()
        contender = multiprocessing.Process(target=try_second_writer, args=(str(self.db_path), result))
        contender.start()
        contender.join(5)
        self.assertFalse(contender.is_alive())
        self.assertEqual(contender.exitcode, 0)
        self.assertEqual(result.get(timeout=1), "BrokerAlreadyRunning:BROKER_ALREADY_RUNNING")

    def test_schema_rejection_and_dedupe_are_atomic(self):
        request = {"protocol_version": 1, "kind": "ENQUEUE", "command": command()}
        first = self.core.handle(request)
        duplicate = self.core.handle(request)
        self.assertEqual((first["duplicate"], duplicate["duplicate"]), (False, True))
        self.assertEqual(self.core.counts(), {"deliveries": 1, "acked": 0, "succeeded": 0})
        conflicting = {"protocol_version": 1, "kind": "ENQUEUE", "command": command("c2")}
        with self.assertRaisesRegex(RuntimeError, "DEDUPE_CONFLICT"):
            self.core.handle(conflicting)
        reused_id = {"protocol_version": 1, "kind": "ENQUEUE", "command": command("c1", "different-idem")}
        with self.assertRaisesRegex(RuntimeError, "COMMAND_ID_CONFLICT"):
            self.core.handle(reused_id)
        malformed = command("bad", "bad-idem")
        malformed["schema_version"] = 2
        with self.assertRaises(ValueError):
            self.core.handle({"protocol_version": 1, "kind": "ENQUEUE", "command": malformed})
        self.assertEqual(self.core.counts(), {"deliveries": 1, "acked": 0, "succeeded": 0})

    def test_disconnect_equivalent_never_acks_or_succeeds(self):
        self.core.handle({"protocol_version": 1, "kind": "ENQUEUE", "command": command()})
        self.assertEqual(self.core.delivery("c1")["state"], "PENDING")
        self.assertEqual(self.core.counts()["acked"], 0)
        self.assertEqual(self.core.counts()["succeeded"], 0)


class NamedPipeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "broker.db"
        self.address = make_local_pipe_name(f"{os.getpid()}-{time.time_ns()}")
        self.authkey = b"u11-test-auth-key-material-32bytes"
        self.ready = multiprocessing.Event()
        self.process = multiprocessing.Process(
            target=run_broker,
            args=(str(self.db_path), self.address, self.authkey, self.ready),
        )
        self.process.start()
        self.assertTrue(self.ready.wait(10), "broker did not become ready")

    def tearDown(self):
        if self.process.is_alive():
            try:
                BrokerClient(self.address, self.authkey).request({"protocol_version": 1, "kind": "STOP"})
            except (OSError, EOFError):
                pass
            self.process.join(5)
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(5)
        self.temp.cleanup()

    def test_authenticated_roundtrip_and_graceful_stop(self):
        client = BrokerClient(self.address, self.authkey)
        response = client.request({"protocol_version": 1, "kind": "ENQUEUE", "command": command()})
        self.assertTrue(response["ok"])
        self.assertEqual(response["result"]["state"], "PENDING")
        stopped = client.request({"protocol_version": 1, "kind": "STOP"})
        self.assertTrue(stopped["ok"])
        self.process.join(5)
        self.assertFalse(self.process.is_alive())
        self.assertEqual(self.process.exitcode, 0)

    @unittest.skipUnless(os.name == "nt", "AF_PIPE authentication test is Windows-specific")
    def test_bad_auth_is_rejected(self):
        with self.assertRaisesRegex(BrokerProtocolError, "AUTHENTICATION_FAILED"):
            BrokerClient(self.address, b"wrong-auth-key-material-32bytes!!").request({"protocol_version": 1, "kind": "COUNTS"})
        counts = BrokerClient(self.address, self.authkey).request({"protocol_version": 1, "kind": "COUNTS"})
        self.assertEqual(counts["result"], {"deliveries": 0, "acked": 0, "succeeded": 0})

    def test_oversize_and_broken_schema_are_rejected_without_write(self):
        family = "AF_PIPE" if os.name == "nt" else "AF_UNIX"
        raw = Client(self.address, family=family, authkey=None)
        raw.send_bytes(b"x" * (MAX_FRAME_BYTES + 1))
        with self.assertRaises((EOFError, OSError)):
            raw.recv_bytes(MAX_FRAME_BYTES)
        raw.close()
        bad = BrokerClient(self.address, self.authkey).request({"protocol_version": 1, "kind": "ENQUEUE", "command": {}})
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["error"], {"error_code": "INVALID_REQUEST", "retryable": False})
        counts = BrokerClient(self.address, self.authkey).request({"protocol_version": 1, "kind": "COUNTS"})
        self.assertEqual(counts["result"]["deliveries"], 0)

    def test_silent_authenticated_client_is_evicted_and_broker_remains_usable(self):
        family = "AF_PIPE" if os.name == "nt" else "AF_UNIX"
        silent = Client(self.address, family=family, authkey=None)
        started = time.monotonic()
        counts = BrokerClient(self.address, self.authkey, response_timeout=3).request(
            {"protocol_version": 1, "kind": "COUNTS"}
        )
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 2.5)
        self.assertEqual(counts["result"], {"deliveries": 0, "acked": 0, "succeeded": 0})
        timeout_response = _unwrap_response(_decode(silent.recv_bytes(MAX_FRAME_BYTES)), self.authkey, "")
        self.assertEqual(
            timeout_response,
            {
                "protocol_version": 1,
                "ok": False,
                "error": {"error_code": "REQUEST_READ_TIMEOUT", "retryable": True},
            },
        )
        silent.close()
        stopped = BrokerClient(self.address, self.authkey).request({"protocol_version": 1, "kind": "STOP"})
        self.assertTrue(stopped["ok"])
        self.process.join(5)
        self.assertFalse(self.process.is_alive())
        self.assertEqual(self.process.exitcode, 0)

    def test_client_response_timeout_and_strict_response_validation(self):
        address = make_local_pipe_name(f"unresponsive-{os.getpid()}-{time.time_ns()}")
        ready = multiprocessing.Event()
        process = multiprocessing.Process(target=run_unresponsive_server, args=(address, self.authkey, ready))
        process.start()
        self.assertTrue(ready.wait(10))
        started = time.monotonic()
        try:
            with self.assertRaisesRegex(BrokerResponseTimeout, "BROKER_RESPONSE_TIMEOUT") as raised:
                BrokerClient(address, self.authkey, response_timeout=0.2).request(
                    {"protocol_version": 1, "kind": "COUNTS"}
                )
            self.assertTrue(raised.exception.retryable)
            self.assertLess(time.monotonic() - started, 1.5)
        finally:
            process.terminate()
            process.join(5)

        with self.assertRaisesRegex(BrokerProtocolError, "INVALID_BROKER_RESPONSE"):
            BrokerClient._validate_response({"protocol_version": 1, "ok": True, "result": {}, "extra": True})
        with self.assertRaisesRegex(BrokerProtocolError, "INVALID_BROKER_RESPONSE"):
            BrokerClient._validate_response({"protocol_version": 1, "ok": False, "error": {"error_code": "ERR"}})
        with self.assertRaisesRegex(BrokerProtocolError, "INVALID_BROKER_RESPONSE"):
            BrokerClient._validate_response({"protocol_version": 1, "ok": False, "error": {"error_code": "ERR", "retryable": "not-a-bool"}})
        with self.assertRaisesRegex(BrokerProtocolError, "INVALID_BROKER_RESPONSE"):
            BrokerClient._validate_response({"protocol_version": 1, "ok": False, "error": {"error_code": "ERR", "retryable": True}, "extra": True})

    def test_half_frame_disconnect_and_crash_replay_have_no_false_success(self):
        family = "AF_PIPE" if os.name == "nt" else "AF_UNIX"
        half = Client(self.address, family=family, authkey=None)
        if os.name == "nt":
            import _winapi

            _winapi.WriteFile(half.fileno(), (100).to_bytes(4, "big") + b"{\"protocol_version\":1")
        else:
            os.write(half.fileno(), (100).to_bytes(4, "big") + b"{\"protocol_version\":1")
        half.close()
        counts = BrokerClient(self.address, self.authkey).request({"protocol_version": 1, "kind": "COUNTS"})
        self.assertEqual(counts["result"], {"deliveries": 0, "acked": 0, "succeeded": 0})

        self.process.terminate()
        self.process.join(5)
        self.ready = multiprocessing.Event()
        self.process = multiprocessing.Process(
            target=run_broker,
            args=(str(self.db_path), self.address, self.authkey, self.ready, True),
        )
        self.process.start()
        self.assertTrue(self.ready.wait(10))
        request = {"protocol_version": 1, "kind": "ENQUEUE", "command": command()}
        with self.assertRaises((EOFError, OSError)):
            BrokerClient(self.address, self.authkey).request(request)
        self.process.join(5)
        self.assertEqual(self.process.exitcode, 91)

        self.ready = multiprocessing.Event()
        self.process = multiprocessing.Process(target=run_broker, args=(str(self.db_path), self.address, self.authkey, self.ready))
        self.process.start()
        self.assertTrue(self.ready.wait(10))
        replay = BrokerClient(self.address, self.authkey).request(request)
        self.assertTrue(replay["result"]["duplicate"])
        counts = BrokerClient(self.address, self.authkey).request({"protocol_version": 1, "kind": "COUNTS"})
        self.assertEqual(counts["result"], {"deliveries": 1, "acked": 0, "succeeded": 0})



@unittest.skipIf(os.name == "nt", "named pipes vanish with their process; B75 is POSIX only")
class StaleSocketReclaimTest(unittest.TestCase):
    """B75: only a socket that refuses connections is removed before the broker binds."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "b.sock")

    def tearDown(self):
        self.temp.cleanup()

    def test_a_dead_socket_is_removed_and_a_live_one_is_kept(self):
        import socket as _socket

        from v7_harness.broker.ipc import _reclaim_stale_unix_socket

        live = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        live.bind(self.path)
        live.listen(1)
        self.assertFalse(_reclaim_stale_unix_socket(self.path))
        self.assertTrue(os.path.exists(self.path))
        live.close()  # the file stays behind, exactly like a crashed broker
        self.assertTrue(os.path.exists(self.path))
        self.assertTrue(_reclaim_stale_unix_socket(self.path))
        self.assertFalse(os.path.exists(self.path))
        self.assertFalse(_reclaim_stale_unix_socket(self.path))  # nothing there: no-op

    def test_a_path_that_is_not_a_socket_is_never_touched(self):
        from v7_harness.broker.ipc import _reclaim_stale_unix_socket

        Path(self.path).write_text("not a socket", encoding="utf-8")
        self.assertFalse(_reclaim_stale_unix_socket(self.path))
        self.assertEqual("not a socket", Path(self.path).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
