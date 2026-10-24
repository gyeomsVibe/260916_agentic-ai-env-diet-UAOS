"""Bounded native hook listener; provider-free and never auto-ACKs."""
import hashlib
import json
import math
import os
import time
from pathlib import Path

from . import hook_context, sentinel_lease
from .stop_gate import hook_session

# Provider-free scan windows rearm inside one native host-owned command lifetime.
SCAN_WINDOW_S = 300.0
DEFAULT_TIMEOUT_S = 86400.0  # Explicit 24-hour host bound, never a perpetual guarantee.
DEFAULT_INTERVAL_S = 2.0


def _locked_listen(project, session, timeout_s, interval_s, watch_fn):
    directory = project / '.coord/presence/continuity'
    directory.mkdir(parents=True, exist_ok=True)
    # Never unlink this inode: the kernel owns exclusion until this process exits.
    fd = os.open(directory / 'claude.native.lock', os.O_CREAT | os.O_RDWR, 0o600)
    locked = False
    deadline = time.monotonic() + timeout_s
    try:
        locked = _acquire_native(fd, project, session, deadline, interval_s)
        if not locked:
            return 0, None
        from .watch import _write_atomic
        _write_atomic(directory / 'claude.native.owner.json', {'session': session, 'pid': os.getpid()})
        _state(project, session, 'LISTENING')
        return _listen(project, session, max(0, deadline-time.monotonic()), interval_s, watch_fn)
    finally:
        if locked:
            sentinel_lease._unlock(fd)
        os.close(fd)


def _acquire_native(fd, project, session, deadline, interval_s):
    """Same-session events coalesce; a new desk waits for kernel-owned handoff."""
    owner = project / '.coord/presence/continuity/claude.native.owner.json'
    while _desk_matches(project, session) and time.monotonic() < deadline:
        answer = sentinel_lease._try_lock(fd)
        if answer == 'OK':
            return True
        if answer != 'HELD':
            return False
        try:
            if json.loads(owner.read_text(encoding='utf-8')).get('session') == session:
                return False
        except (OSError, ValueError, AttributeError):
            pass
        time.sleep(max(0, min(interval_s, deadline-time.monotonic())))
    return False


def _desk_matches(project, session):
    try:
        record = json.loads((project / '.coord/presence/user_desk_claude.json').read_text(encoding='utf-8'))
        return isinstance(record, dict) and record.get('thread') == session
    except (OSError, ValueError):
        return False


def _state(project, session, state):
    directory = project / '.coord/presence/continuity'
    directory.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(session.encode()).hexdigest()
    from .watch import _write_atomic
    _write_atomic(directory / f'{name}.json', {'state': state, 'tool': 'claude',
                  'session': session, 'at': time.time(), 'capability': 'native_asyncRewake'})


def _listen(project, session, timeout_s, interval_s, watch_fn):
    from .watch import watch
    deadline = time.monotonic() + timeout_s
    while _desk_matches(project, session) and time.monotonic() < deadline:
        found = (watch_fn or watch)(project, ('claude',), timeout_s=min(SCAN_WINDOW_S, deadline-time.monotonic()),
            interval_s=interval_s, wakes_session=True, policy='structured', native_session=session)
        if found is not None:
            return _result(project, session, found)
        # Avoid spinning if an adapter returns before its requested scan window.
        time.sleep(max(0, min(interval_s, deadline-time.monotonic())))
    _state(project, session, 'EXPIRED_NEEDS_NATIVE_REARM')
    return 0, None


def _result(project, session, found):
    valid = (isinstance(found, dict) and found.get('wake_class') == 'ACTIONABLE'
             and found.get('requested_target') == 'claude' and bool(found.get('id'))
             and _desk_matches(project, session))
    # This proves only a local claim and native exit signal, never receiver processing.
    _state(project, session, 'CLAIMED_NOT_RECEIVER_ACK' if valid else 'NO_ACTION')
    return (2, found) if valid else (0, None)


def run_hook(payload: dict, tool: str, *, timeout_s=DEFAULT_TIMEOUT_S,
             interval_s=DEFAULT_INTERVAL_S, watch_fn=None):
    """Exit 2 is exclusively Claude's documented asyncRewake hook signal."""
    if tool != 'claude' or os.environ.get('UAOS_WORKER') or not isinstance(payload, dict):
        return 0, None
    session = hook_session(payload)
    project = hook_context.find_project(hook_context.payload_candidates(json.dumps(payload)))
    if not session or project is None or not _desk_matches(project, session):
        return 0, None
    if payload.get('hook_event_name') not in ('SessionStart', 'Stop'):
        return 0, None
    # SessionStart has a first-response context barrier, even for background hooks.
    # Only bootstrap here; the first Stop owns the long-running native listener.
    if payload.get('hook_event_name') == 'SessionStart':
        _state(project, session, 'BOOTSTRAP_COMPLETE')
        return 0, None
    if not all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0
               for v in (timeout_s, interval_s)):
        return 0, None
    return _locked_listen(project, session, min(timeout_s, DEFAULT_TIMEOUT_S),
                          min(interval_s, DEFAULT_INTERVAL_S), watch_fn)
