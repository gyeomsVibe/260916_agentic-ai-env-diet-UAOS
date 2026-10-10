```contract
work_id: U180S-A6
worker: apply
apply_after: U180S-L2
goal: U180S one lifetime OS lease for every sentinel launcher; a stale pid file whose pid was reused does not block it
inputs:
- v7_harness/cli.py sha256=d8dd4d9472e1cbffb0d01aa9dbb686a621e0612b4903a90ac33d6ee1fe2aa0ee
allow:
- v7_harness/coord/sentinel_lease.py
- v7_harness/cli.py
context_allow:
- v7_harness/cli.py
acceptance: python -m unittest tests.test_u180s_pid_reuse tests.test_u180s_lifetime_lease tests.test_u180s_lease_counter tests.test_u180s_cli_lease tests.test_u180s_cli_legacy tests.test_u37_install_everywhere
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: antigravity
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Card U180S. Codex designed the lease (bundles 1650cd21, 46b5927e, 835b05a5); Claude's rework adds the reused-pid rule
(ledger BLOCKED 20261010T2206-claude-0001). Dictation: write the one new file and copy the one edit block below
exactly. Change nothing else.

===FILE: v7_harness/coord/sentinel_lease.py===
"""Shared lifetime exclusion for the sentinel; no heartbeat age grants ownership."""
import os
from contextlib import contextmanager
from pathlib import Path

from .stream import _try_lock, _unlock

# A live pid is the legacy owner unless its process was created this long after the pid file was last written: then
# Windows reused the pid and the file is stale (ledger BLOCKED 20261010T2206-claude-0001: after a reboot both
# launchers answered ALREADY_RUNNING for ever). 2 s is the coarsest file-time step on a Windows volume (FAT).
REUSE_MARGIN_S = 2.0
QUERY_LIMITED = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION: read-only, can never terminate
STILL_ACTIVE = 259
INVALID_PARAMETER = 87  # OpenProcess: no such pid
FILETIME_EPOCH = 116444736000000000  # 100 ns steps between 1601-01-01 and 1970-01-01


class LeaseUnavailable(RuntimeError):
    """Busy or uncertain ownership must never start a second operator."""


def _kernel():
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    return ctypes, wintypes, kernel


def pid_state(pid):
    if type(pid) is not int or not 0 < pid < 2**32:
        return 'UNKNOWN'
    if os.name == 'nt':
        ctypes, wintypes, kernel = _kernel()
        handle = kernel.OpenProcess(QUERY_LIMITED, False, pid)
        if not handle:
            return 'DEAD' if ctypes.get_last_error() == INVALID_PARAMETER else 'UNKNOWN'
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                return 'UNKNOWN'
            return 'ALIVE' if code.value == STILL_ACTIVE else 'DEAD'
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)  # existence probe, not a termination signal
        return 'ALIVE'
    except ProcessLookupError:
        return 'DEAD'
    except OSError:
        return 'UNKNOWN'


def created_at(pid):
    """Epoch seconds at which the live process was created, or None when it cannot be read (then: fail closed)."""
    if os.name != 'nt' or type(pid) is not int or not 0 < pid < 2**32:
        return None
    ctypes, wintypes, kernel = _kernel()
    handle = kernel.OpenProcess(QUERY_LIMITED, False, pid)
    if not handle:
        return None
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
            return None
        ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        return (ticks - FILETIME_EPOCH) / 10_000_000
    finally:
        kernel.CloseHandle(handle)


@contextmanager
def lease(project):
    directory = Path(project).resolve() / '.work' / 'sentinel'
    directory.mkdir(parents=True, exist_ok=True)
    # Stable file is never unlinked: changing its identity would split exclusion.
    fd = os.open(directory / 'loop.lock', os.O_CREAT | os.O_RDWR, 0o600)
    locked = False
    try:
        locked = _try_lock(fd)
        if not locked:
            raise LeaseUnavailable('LEASE_BUSY_OR_LOCK_ERROR')
        try:
            with (directory / 'loop.pid').open(encoding='utf-8') as handle:
                raw = handle.read(65)
                written = os.fstat(handle.fileno()).st_mtime
                if len(raw) > 64:
                    raise LeaseUnavailable('LEGACY_UNKNOWN')
                raw = raw.strip()
        except FileNotFoundError:
            raw = None
        except (OSError, UnicodeError) as exc:
            raise LeaseUnavailable('LEGACY_UNKNOWN') from exc
        if raw is not None:
            if not raw or len(raw) > 10 or not raw.isascii() or not raw.isdecimal():
                raise LeaseUnavailable('LEGACY_UNKNOWN')
            state = pid_state(int(raw))
            if state == 'ALIVE':
                created = created_at(int(raw))
                if created is None or created <= written + REUSE_MARGIN_S:
                    raise LeaseUnavailable('LEGACY_ALIVE')
            elif state != 'DEAD':
                raise LeaseUnavailable('LEGACY_UNKNOWN')
        yield  # once, loop and exceptions remain inside the same lifetime lease
    finally:
        try:
            if locked:
                _unlock(fd)
        finally:
            os.close(fd)

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
def cmd_coord_sentinel(args: argparse.Namespace) -> int:
    """U23 S4 / U32b: 0-token sentinel (deterministic rules, no model call) — one cycle or a resident loop."""
=======
def cmd_coord_sentinel(args: argparse.Namespace) -> int:
    """U180S: every launcher kind holds one OS lease for the whole synchronous command."""
    from .coord.sentinel_lease import LeaseUnavailable, lease
    try:
        with lease(Path(args.project)):
            return _cmd_coord_sentinel(args)
    except LeaseUnavailable as exc:
        duplicate = str(exc) == "LEGACY_ALIVE"  # a live old-runtime loop: the U37 answer, never an adoption
        record = ({"ok": True, "skipped": "ALREADY_RUNNING", "operator_verified": False} if duplicate
                  else {"ok": False, "error": str(exc)})
        line = json.dumps(record, ensure_ascii=False)
        print(line, flush=True)
        if log := getattr(args, "log", None):
            path = Path(log)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        return 0 if duplicate else 3


def _cmd_coord_sentinel(args: argparse.Namespace) -> int:
    """U23 S4 / U32b: 0-token sentinel (deterministic rules, no model call) — one cycle or a resident loop."""
>>>>>>> REPLACE

## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
