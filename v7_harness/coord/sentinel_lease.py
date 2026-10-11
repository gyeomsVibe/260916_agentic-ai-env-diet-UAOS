"""Shared lifetime exclusion for the sentinel; only the kernel grants or frees ownership, never a file time."""
import os
from contextlib import contextmanager
from pathlib import Path

QUERY_LIMITED = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION: read-only, can never terminate
STILL_ACTIVE = 259
INVALID_PARAMETER = 87  # OpenProcess: no such pid
# ERROR_LOCK_VIOLATION is the only answer that proves another handle holds the byte. Measured with two real processes
# (U183, 2026-10-11): 33 whether the holder locked through LockFileEx or through the older msvcrt.locking.
LOCK_VIOLATION = 33
LOCK_NOW = 0x3  # LOCKFILE_EXCLUSIVE_LOCK (2) | LOCKFILE_FAIL_IMMEDIATELY (1)


class LeaseUnavailable(RuntimeError):
    """Busy or uncertain ownership must never start a second operator."""

    def __init__(self, reason, kind=None):
        super().__init__(reason)
        self.kind = kind or reason  # HELD, LOCK_ERROR, LEGACY_ALIVE or LEGACY_UNKNOWN


def _kernel():
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.LockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p]
    kernel.LockFileEx.restype = wintypes.BOOL
    kernel.UnlockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    kernel.UnlockFileEx.restype = wintypes.BOOL
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


def _range(ctypes, wintypes):
    """Start of the locked range: byte 0, the byte every launcher of every runtime version locks."""
    class Overlapped(ctypes.Structure):
        _fields_ = [('Internal', ctypes.c_void_p), ('InternalHigh', ctypes.c_void_p), ('Offset', wintypes.DWORD),
                    ('OffsetHigh', wintypes.DWORD), ('hEvent', wintypes.HANDLE)]
    return ctypes.byref(Overlapped())


def _try_lock(fd):
    """'OK', 'HELD' (the kernel reports another holder of the byte) or 'LOCK_ERROR' (any other failure: no evidence)."""
    if os.name == 'nt':
        import msvcrt
        ctypes, wintypes, kernel = _kernel()
        if kernel.LockFileEx(msvcrt.get_osfhandle(fd), LOCK_NOW, 0, 1, 0, _range(ctypes, wintypes)):
            return 'OK'
        return 'HELD' if ctypes.get_last_error() == LOCK_VIOLATION else 'LOCK_ERROR'
    import fcntl
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return 'OK'
    except BlockingIOError:
        return 'HELD'
    except OSError:
        return 'LOCK_ERROR'


def _unlock(fd):
    if os.name == 'nt':
        import msvcrt
        ctypes, wintypes, kernel = _kernel()
        kernel.UnlockFileEx(msvcrt.get_osfhandle(fd), 0, 1, 0, _range(ctypes, wintypes))
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def lease(project):
    directory = Path(project).resolve() / '.work' / 'sentinel'
    directory.mkdir(parents=True, exist_ok=True)
    # Stable file is never unlinked: changing its identity would split exclusion.
    fd = os.open(directory / 'loop.lock', os.O_CREAT | os.O_RDWR, 0o600)
    locked = False
    try:
        answer = _try_lock(fd)
        if answer != 'OK':
            raise LeaseUnavailable('LEASE_BUSY_OR_LOCK_ERROR', answer)
        locked = True
        try:
            with (directory / 'loop.pid').open(encoding='utf-8') as handle:
                raw = handle.read(65)
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
            # A live pid is never handed over: no file time and no creation time can tell a reused pid from the
            # operator that wrote it (U183). Only a pid the kernel reports dead frees the legacy file.
            state = pid_state(int(raw))
            if state == 'ALIVE':
                raise LeaseUnavailable('LEGACY_ALIVE')
            if state != 'DEAD':
                raise LeaseUnavailable('LEGACY_UNKNOWN')
        yield  # once, loop and exceptions remain inside the same lifetime lease
    finally:
        try:
            if locked:
                _unlock(fd)
        finally:
            os.close(fd)
