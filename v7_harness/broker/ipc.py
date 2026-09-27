"""Authenticated, bounded Windows Named Pipe request/response transport."""

from __future__ import annotations

import getpass
import hashlib
import hmac
import json
import os
import threading
import re
import secrets
import socket
import stat
import tempfile
import time
from multiprocessing.connection import Client, Listener
from pathlib import Path
from typing import Any

from v7_harness.contracts.schemas import SchemaValidationError
from v7_harness.execution.dispatcher import BoundedDispatcher
from v7_harness.execution.errors import ExecutionError, QueueSaturationError

from .core import BrokerCore, BrokerError


MAX_FRAME_BYTES = 16 * 1024
DEFAULT_REQUEST_TIMEOUT = 1.0
DEFAULT_RESPONSE_TIMEOUT = 2.0
# 연결 작업자를 기다리느라 종료 기한을 다 쓰면 디스패처에 0.1초만 남아, 부하 중 SQLite 를 닫는
# 소유 스레드가 못 끝나 DISPATCHER_STOP_TIMEOUT 으로 자식이 exit 1 했다(B64, 2026-09-22 회귀 로그).
# 정상 STOP 이 실패로 끝나지 않도록 디스패처 정리에는 따로 최소 시간을 준다.
DRAIN_FLOOR_S = 2.0


def drain_budget(deadline: float, now: float) -> float:
    return max(DRAIN_FLOOR_S, deadline - now)



def _reclaim_stale_unix_socket(address: str) -> bool:
    """B75: a crashed POSIX broker leaves its socket file behind and the restart failed with EADDRINUSE.

    Only a socket that refuses a connection is removed. A live broker answers the probe and keeps its
    file (the bind then fails as before), and a path that is not a socket is never touched. Two brokers
    racing here on one database cannot happen: the dispatcher takes the single-writer lock first.
    Windows named pipes vanish with their process and never reach this function.
    """
    try:
        if not stat.S_ISSOCK(os.lstat(address).st_mode):
            return False
    except FileNotFoundError:
        return False
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    probe.settimeout(0.5)
    try:
        probe.connect(address)
    except (ConnectionRefusedError, FileNotFoundError):
        pass
    except OSError:
        return False  # busy or unknown: leave it and let the bind report the real state
    else:
        return False  # a live listener owns it
    finally:
        probe.close()
    try:
        os.unlink(address)
    except FileNotFoundError:
        pass
    return True

class BrokerProtocolError(RuntimeError):
    def __init__(self, error_code: str, *, retryable: bool = False) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.retryable = retryable


class BrokerResponseTimeout(BrokerProtocolError):
    def __init__(self) -> None:
        super().__init__("BROKER_RESPONSE_TIMEOUT", retryable=True)


def _current_user_slug() -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", getpass.getuser()) or "user"


def make_local_pipe_name(nonce: str | None = None) -> str:
    """Return a local, current-user-namespaced endpoint candidate.

    The namespace is defense in depth, not an ACL claim; authentication remains
    mandatory because multiprocessing does not expose an explicit pipe DACL.
    """
    user = _current_user_slug()
    suffix = nonce or secrets.token_hex(12)
    if os.name == "nt":
        return rf"\\.\pipe\coordd-{user}-{suffix}"
    # POSIX has no TEMP by default, so the old fallback "." put sockets into the project, where a crashed broker
    # left them behind (B75) and the source manifest then failed on them.
    return str(Path(tempfile.gettempdir()) / f"coordd-{user}-{suffix}.sock")


def _validate_endpoint(address: str) -> None:
    if os.name == "nt":
        expected = rf"\\.\pipe\coordd-{_current_user_slug()}-"
        if not address.startswith(expected):
            raise ValueError("UNSAFE_PIPE_ENDPOINT")


def _encode(document: dict[str, Any]) -> bytes:
    payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_FRAME_BYTES:
        raise ValueError("FRAME_TOO_LARGE")
    return payload


def _canonical(document: dict[str, Any]) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _tag(authkey: bytes, nonce: str, document: dict[str, Any]) -> str:
    return hmac.new(authkey, nonce.encode("ascii") + b"\0" + _canonical(document), hashlib.sha256).hexdigest()


def _request_frame(request: dict[str, Any], authkey: bytes) -> dict[str, Any]:
    nonce = secrets.token_hex(16)
    return {
        "transport_version": 1,
        "nonce": nonce,
        "request": request,
        "auth_tag": _tag(authkey, nonce, request),
    }


def _unwrap_request(frame: dict[str, Any], authkey: bytes) -> tuple[dict[str, Any], str]:
    if set(frame) != {"transport_version", "nonce", "request", "auth_tag"} or frame.get("transport_version") != 1:
        raise BrokerProtocolError("INVALID_TRANSPORT_FRAME")
    nonce, request, supplied = frame.get("nonce"), frame.get("request"), frame.get("auth_tag")
    if not isinstance(nonce, str) or not isinstance(request, dict) or not isinstance(supplied, str):
        raise BrokerProtocolError("INVALID_TRANSPORT_FRAME")
    if not hmac.compare_digest(supplied, _tag(authkey, nonce, request)):
        raise BrokerProtocolError("AUTHENTICATION_FAILED")
    return request, nonce


def _response_frame(response: dict[str, Any], authkey: bytes, nonce: str) -> dict[str, Any]:
    return {
        "transport_version": 1,
        "nonce": nonce,
        "response": response,
        "auth_tag": _tag(authkey, nonce, response),
    }


def _unwrap_response(frame: dict[str, Any], authkey: bytes, nonce: str) -> dict[str, Any]:
    if set(frame) != {"transport_version", "nonce", "response", "auth_tag"} or frame.get("transport_version") != 1:
        raise BrokerProtocolError("INVALID_TRANSPORT_FRAME")
    response, supplied = frame.get("response"), frame.get("auth_tag")
    if frame.get("nonce") != nonce or not isinstance(response, dict) or not isinstance(supplied, str):
        raise BrokerProtocolError("INVALID_TRANSPORT_FRAME")
    if not hmac.compare_digest(supplied, _tag(authkey, nonce, response)):
        raise BrokerProtocolError("AUTHENTICATION_FAILED")
    return response


def _decode(payload: bytes) -> dict[str, Any]:
    if len(payload) > MAX_FRAME_BYTES:
        raise ValueError("FRAME_TOO_LARGE")
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SchemaValidationError("$: invalid JSON") from exc
    if not isinstance(document, dict):
        raise SchemaValidationError("$: object required")
    return document


class ForegroundBroker:
    """One foreground listener and one broker-owned writable SQLite handle."""

    def __init__(
        self,
        database_path: Path,
        address: str,
        authkey: bytes,
        *,
        crash_after_commit: bool = False,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
        dispatcher_capacity: int = 16,
        max_connections: int = 16,
    ) -> None:
        if not authkey or len(authkey) < 16:
            raise ValueError("AUTHKEY_TOO_SHORT")
        _validate_endpoint(address)
        if request_timeout <= 0:
            raise ValueError("INVALID_REQUEST_TIMEOUT")
        self._core = BrokerCore(database_path)
        self.address = address
        self._authkey = bytes(authkey)
        self._listener: Listener | None = None
        self._stopping = False
        self._crash_after_commit = crash_after_commit
        self._request_timeout = request_timeout
        self._dispatcher = BoundedDispatcher(self._core, capacity=dispatcher_capacity)
        self._connection_slots = threading.BoundedSemaphore(max_connections)
        self._workers: set[threading.Thread] = set()
        self._workers_lock = threading.Lock()

    @staticmethod
    def _error_response(error_code: str, *, retryable: bool) -> dict[str, Any]:
        return {
            "protocol_version": 1,
            "ok": False,
            "error": {"error_code": error_code, "retryable": retryable},
        }

    def serve_forever(self, ready: Any = None) -> None:
        self._dispatcher.start()
        family = "AF_PIPE" if os.name == "nt" else "AF_UNIX"
        try:
            # Authentication is inside the bounded frame. multiprocessing's
            # built-in challenge has no public deadline and can block accept().
            if family == "AF_UNIX":
                _reclaim_stale_unix_socket(self.address)
            self._listener = Listener(self.address, family=family, authkey=None)
            if ready is not None:
                ready.set()
            while not self._stopping:
                try:
                    connection = self._listener.accept()
                except (OSError, EOFError):
                    if self._stopping:
                        break
                    continue
                if not self._connection_slots.acquire(blocking=False):
                    try:
                        self._serve_connection(connection, saturated=True)
                    finally:
                        connection.close()
                    continue
                worker = threading.Thread(target=self._connection_worker, args=(connection,), daemon=True)
                with self._workers_lock:
                    self._workers.add(worker)
                worker.start()
        finally:
            if self._listener is not None:
                self._listener.close()
            deadline = time.monotonic() + max(1.0, self._request_timeout * 2)
            while True:
                with self._workers_lock:
                    workers = list(self._workers)
                if not workers or time.monotonic() >= deadline:
                    break
                for worker in workers:
                    worker.join(timeout=0.05)
            self._dispatcher.drain(timeout=drain_budget(deadline, time.monotonic()))

    def _connection_worker(self, connection: Any) -> None:
        try:
            self._serve_connection(connection)
        finally:
            connection.close()
            self._connection_slots.release()
            with self._workers_lock:
                self._workers.discard(threading.current_thread())

    def _serve_connection(self, connection: Any, *, saturated: bool = False) -> None:
        nonce = ""
        try:
            if not connection.poll(self._request_timeout):
                response = self._error_response("REQUEST_READ_TIMEOUT", retryable=True)
                connection.send_bytes(_encode(_response_frame(response, self._authkey, nonce)))
                return
            payload = connection.recv_bytes(MAX_FRAME_BYTES)
            frame = _decode(payload)
            if isinstance(frame.get("nonce"), str):
                nonce = frame["nonce"]
            request, nonce = _unwrap_request(frame, self._authkey)
            if saturated:
                raise QueueSaturationError()
            result = self._dispatcher.submit_and_wait(
                lambda core: core.handle(request),
                timeout=max(self._request_timeout, 0.1),
            )
            if self._crash_after_commit and request.get("kind") == "ENQUEUE":
                os._exit(91)
            response = {"protocol_version": 1, "ok": True, "result": result}
            connection.send_bytes(_encode(_response_frame(response, self._authkey, nonce)))
            if request.get("kind") == "STOP":
                self._stopping = True
                # Listener.accept() has no public cancellation primitive on
                # Windows.  A local wake connection lets the owner loop
                # observe _stopping without leaving an unbounded accept wait.
                family = "AF_PIPE" if os.name == "nt" else "AF_UNIX"
                wake = Client(self.address, family=family, authkey=None)
                wake.close()
        except (EOFError, OSError):
            return
        except (BrokerError, BrokerProtocolError, SchemaValidationError, ExecutionError, ValueError) as exc:
            try:
                code = str(exc) if str(exc).isupper() and " " not in str(exc) else "INVALID_REQUEST"
                response = self._error_response(code, retryable=bool(getattr(exc, "retryable", False)))
                connection.send_bytes(_encode(_response_frame(response, self._authkey, nonce)))
            except (EOFError, OSError):
                pass


class BrokerClient:
    """IPC-only client; deliberately has no database handle or mutation API."""

    def __init__(self, address: str, authkey: bytes, *, response_timeout: float = DEFAULT_RESPONSE_TIMEOUT) -> None:
        _validate_endpoint(address)
        if not authkey or len(authkey) < 16:
            raise ValueError("AUTHKEY_TOO_SHORT")
        if response_timeout <= 0:
            raise ValueError("INVALID_RESPONSE_TIMEOUT")
        self.address = address
        self._authkey = bytes(authkey)
        self._response_timeout = response_timeout

    @staticmethod
    def _validate_response(document: dict[str, Any]) -> None:
        if document.get("protocol_version") != 1 or not isinstance(document.get("ok"), bool):
            raise BrokerProtocolError("INVALID_BROKER_RESPONSE")
        if document["ok"]:
            if set(document) != {"protocol_version", "ok", "result"} or not isinstance(document["result"], dict):
                raise BrokerProtocolError("INVALID_BROKER_RESPONSE")
            return
        if set(document) != {"protocol_version", "ok", "error"} or not isinstance(document["error"], dict):
            raise BrokerProtocolError("INVALID_BROKER_RESPONSE")
        error = document["error"]
        if set(error) != {"error_code", "retryable"} or not isinstance(error["error_code"], str) or not isinstance(error["retryable"], bool):
            raise BrokerProtocolError("INVALID_BROKER_RESPONSE")

    def request(self, document: dict[str, Any]) -> dict[str, Any]:
        family = "AF_PIPE" if os.name == "nt" else "AF_UNIX"
        connection = Client(self.address, family=family, authkey=None)
        try:
            frame = _request_frame(document, self._authkey)
            nonce = frame["nonce"]
            connection.send_bytes(_encode(frame))
            if not connection.poll(self._response_timeout):
                raise BrokerResponseTimeout()
            try:
                raw_frame = _decode(connection.recv_bytes(MAX_FRAME_BYTES))
                response = _unwrap_response(raw_frame, self._authkey, nonce)
            except (SchemaValidationError, ValueError) as exc:
                raise BrokerProtocolError("INVALID_BROKER_RESPONSE") from exc
            self._validate_response(response)
            return response
        finally:
            connection.close()
