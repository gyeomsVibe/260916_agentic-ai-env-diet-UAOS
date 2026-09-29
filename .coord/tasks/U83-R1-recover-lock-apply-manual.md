```contract
work_id: U83-R1
worker: apply
goal: Replace the mtime-stolen, unconditionally unlinked guard recovery lock with a crash-released OS lock.
inputs:
- .coord/PLAN.md sha256=3a0d2b5d90be257eb2b3638227790d2be430c318420c5ed5cfddabb421998e6a
- v7_harness/coord/deliver.py sha256=d0b253a495582b5dbc25661db61b8aab2938e40a42af513220ec596066ca85ad
- tests/test_u48_deliver.py sha256=54fa2c074065a7fc077e7a8677bdb2bd16341e275954761cdf6f56dbe5fceea6
- tests/test_u49_guard_release_race.py sha256=fb47e0c5ba00bd52a219cc1917ed3fa94b1b541dbecd87cbbdcdb55cef34c34e
allow:
- v7_harness/coord/deliver.py
- tests/test_u48_deliver.py
- tests/test_u49_guard_release_race.py
- tests/test_u83_recover_lock.py
- .coord/PLAN.md
acceptance: python -m unittest tests.test_u83_recover_lock tests.test_u49_guard_release_race tests.test_u48_deliver
forbidden: design changes; edits outside allow; weakening or deleting existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the EDIT blocks exactly. Codex's REJECT counterexample becomes tests/test_u83_recover_lock.py.

===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
# The recovery lock is held only for a stat, a rename and an open (milliseconds); 60 s means its holder crashed.
RECOVER_STALE_S = 60.0

=======
# U83 (Codex REJECT of U49-G1R, 2026-09-29): the recovery lock is an OS byte-range lock on `<guard>.recover`, not an
# exclusively created file aged by mtime. The OS drops it when its holder exits or crashes, so nothing ever steals it by
# age: a holder paused for any length of time keeps it, and the file itself is never unlinked, so no caller can delete
# another holder's lock.

>>>>>>> REPLACE
===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
# Release waits for the recovery lock at most 5 s: recovery holds it for milliseconds, so 5 s only runs out when a
# recoverer crashed inside it; the guard is then left for stale recovery, which can delay but never double-dispatch.

=======
# Release waits for the recovery lock at most 5 s: recovery holds it for milliseconds, so 5 s only runs out when a
# recoverer is paused inside it; the guard is then left for stale recovery, which can delay but never double-dispatch.

>>>>>>> REPLACE
===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
def _acquire_guard(guard: Path, box: Mailbox, message_id: str, digest: str) -> int | None:
    """Take the per-message dispatch guard, recovering one left by a crashed dispatcher. None means IN_FLIGHT.

    Recovery runs under a second exclusive lock so the age check and the rename cannot interleave with another
    recoverer (otherwise one could rename a guard that another had just re-created). The stale guard is renamed,
    not deleted, and an attempt receipt records the recovery.
    """
    fd = _open_excl(guard)
    if fd is not None:
        return fd
    try:
        if time.time() - guard.stat().st_mtime < GUARD_STALE_S:
            return None
    except OSError:
        pass  # released since (or delete pending on Windows); the exclusive open below decides
    recover = guard.with_name(guard.name + ".recover")
    rfd = _open_excl(recover)
    if rfd is None:
        try:
            if time.time() - recover.stat().st_mtime >= RECOVER_STALE_S:
                os.rename(recover, recover.with_name(f"{recover.name}.stale-{uuid.uuid4().hex}"))
        except OSError:
            pass
        return None  # another recoverer is working now; this caller's message is already published
    os.close(rfd)
    try:
        try:
            age = time.time() - guard.stat().st_mtime
        except OSError:
            age = None
        if age is not None:
            if age < GUARD_STALE_S:
                return None  # a live dispatcher re-created it between our checks
            stale = guard.with_name(f"{guard.name}.stale-{uuid.uuid4().hex}")
            os.rename(guard, stale)
            _write_receipt(box.root / "delivery" / "attempts" / f"{message_id}_{uuid.uuid4().hex}.json",
                           {"message_id": message_id, "digest": digest, "state": "GUARD_RECOVERED",
                            "stale_guard": str(stale), "age_s": round(age, 1), "timestamp_ns": time.time_ns()})
        return _open_excl(guard)
    finally:
        recover.unlink(missing_ok=True)


def _release_guard(guard: Path, owner: str) -> None:
    """Remove the dispatch guard only if this dispatcher still owns it, under the same lock recovery uses.

    U49-G1R (Codex REJECT of G1, 2026-09-27): an unconditional unlink by a dispatcher that outlived GUARD_STALE_S removed
    the new holder's guard, and G1's owner check alone still let a recovery land between the read and the unlink.
    Holding `<guard>.recover` across compare and unlink makes release and recovery mutually exclusive, because recovery
    ages, renames and re-creates the guard only while holding that lock too.
    """
    recover = guard.with_name(guard.name + ".recover")
    deadline = time.monotonic() + RELEASE_WAIT_S
    rfd = _open_excl(recover)
    while rfd is None and time.monotonic() < deadline:
        try:
            if time.time() - recover.stat().st_mtime >= RECOVER_STALE_S:
                os.rename(recover, recover.with_name(f"{recover.name}.stale-{uuid.uuid4().hex}"))
        except OSError:
            pass
        time.sleep(CLAIM_SLEEP_S)
        rfd = _open_excl(recover)
    if rfd is None:
        return  # left for stale recovery: a delay, never a second dispatcher
    os.close(rfd)
    try:
        data = None
        for _ in range(CLAIM_TRIES):  # a Windows sharing violation is transient; do not strand our own guard
            try:
                data = json.loads(guard.read_text(encoding="utf-8"))
                break
            except PermissionError:
                time.sleep(CLAIM_SLEEP_S)
            except (OSError, ValueError):
                return
        if isinstance(data, dict) and data.get("owner") == owner:
            guard.unlink(missing_ok=True)
    finally:
        recover.unlink(missing_ok=True)

=======
if os.name == "nt":
    import msvcrt

    def _try_lock(fd: int) -> bool:
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)  # non-blocking; locks are per handle, so a second open conflicts
            return True
        except OSError:
            return False

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # flock, not lockf: it conflicts across opens in one process
            return True
        except OSError:
            return False

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def _recover_lock(guard: Path, wait_s: float):
    """Yield True while holding the OS lock on `<guard>.recover`, or False if it was not taken within wait_s."""
    path = guard.with_name(guard.name + ".recover")
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        yield False
        return
    try:
        deadline = time.monotonic() + wait_s
        while not _try_lock(fd):
            if time.monotonic() >= deadline:
                yield False
                return
            time.sleep(CLAIM_SLEEP_S)
        try:
            yield True
        finally:
            try:
                _unlock(fd)
            except OSError:
                pass  # close below releases it anyway
    finally:
        os.close(fd)


def _acquire_guard(guard: Path, box: Mailbox, message_id: str, digest: str) -> int | None:
    """Take the per-message dispatch guard, recovering one left by a crashed dispatcher. None means IN_FLIGHT.

    Recovery runs under the OS recovery lock so the age check and the rename cannot interleave with another
    recoverer (otherwise one could rename a guard that another had just re-created). The stale guard is renamed,
    not deleted, and an attempt receipt records the recovery.
    """
    fd = _open_excl(guard)
    if fd is not None:
        return fd
    try:
        if time.time() - guard.stat().st_mtime < GUARD_STALE_S:
            return None
    except OSError:
        pass  # released since (or delete pending on Windows); the exclusive open below decides
    with _recover_lock(guard, 0.0) as held:
        if not held:
            return None  # another recoverer or releaser is working now; this caller's message is already published
        try:
            age = time.time() - guard.stat().st_mtime
        except OSError:
            age = None
        if age is not None:
            if age < GUARD_STALE_S:
                return None  # a live dispatcher re-created it between our checks
            stale = guard.with_name(f"{guard.name}.stale-{uuid.uuid4().hex}")
            os.rename(guard, stale)
            _write_receipt(box.root / "delivery" / "attempts" / f"{message_id}_{uuid.uuid4().hex}.json",
                           {"message_id": message_id, "digest": digest, "state": "GUARD_RECOVERED",
                            "stale_guard": str(stale), "age_s": round(age, 1), "timestamp_ns": time.time_ns()})
        return _open_excl(guard)


def _release_guard(guard: Path, owner: str) -> None:
    """Remove the dispatch guard only if this dispatcher still owns it, under the same lock recovery uses.

    U49-G1R (Codex REJECT of G1, 2026-09-27): an unconditional unlink by a dispatcher that outlived GUARD_STALE_S removed
    the new holder's guard, and G1's owner check alone still let a recovery land between the read and the unlink.
    Holding the recovery lock across compare and unlink makes release and recovery mutually exclusive, because recovery
    ages, renames and re-creates the guard only while holding that lock too.
    """
    with _recover_lock(guard, RELEASE_WAIT_S) as held:
        if not held:
            return  # left for stale recovery: a delay, never a second dispatcher
        data = None
        for _ in range(CLAIM_TRIES):  # a Windows sharing violation is transient; do not strand our own guard
            try:
                data = json.loads(guard.read_text(encoding="utf-8"))
                break
            except PermissionError:
                time.sleep(CLAIM_SLEEP_S)
            except (OSError, ValueError):
                return
        if isinstance(data, dict) and data.get("owner") == owner:
            guard.unlink(missing_ok=True)

>>>>>>> REPLACE
===EDIT: tests/test_u48_deliver.py===
<<<<<<< SEARCH
            self.assertEqual([], list(guards.glob("*.recover")))

=======
            self.assertEqual([], list(guards.glob("*.recover.stale-*")))  # U83: the lock file stays; never stolen
            with deliver_module._recover_lock(guard, 0.0) as held:
                self.assertTrue(held, "the recovery lock was left held")

>>>>>>> REPLACE
===EDIT: tests/test_u48_deliver.py===
<<<<<<< SEARCH
from v7_harness.coord.mailbox import Mailbox

=======
from v7_harness.coord import deliver as deliver_module
from v7_harness.coord.mailbox import Mailbox

>>>>>>> REPLACE
===EDIT: tests/test_u49_guard_release_race.py===
<<<<<<< SEARCH
        self.assertEqual([], list(self.guards.glob("*.recover")))

=======
        self.assertEqual([], list(self.guards.glob("*.recover.stale-*")))  # U83: the lock file stays; never stolen
        for recover in self.guards.glob("*.recover"):
            with deliver_module._recover_lock(recover.with_suffix(""), 0.0) as held:
                self.assertTrue(held, "the recovery lock was left held")

>>>>>>> REPLACE
===EDIT: .coord/PLAN.md===
<<<<<<< SEARCH
| U82 | DONE-DELEGATED (Codex LIMITED 중 Claude 권한대행 2026-09-29 — Codex 복귀 시 재검토) | claude(대행 설계·판정) · apply(0토큰) | 불안정 테스트 근본 수정: `test_timeout_kills_worker_process_tree`의 0.3초 제한이 부모 프로세스의 자식 생성·pid 기록(부하 시 최대 0.44초, 중앙 0.34초)보다 짧아, 자식이 생기기 전에 종료되어 child.pid가 없었다(12코어 부하 15회 중 2회 재현). 제한을 3.0초(최악의 약 7배)로 올리고 전제 미충족을 명시적으로 실패시킨다. — `tests/test_u12_execution.py` |

=======
| U82 | DONE-DELEGATED (Codex LIMITED 중 Claude 권한대행 2026-09-29 — Codex 복귀 시 재검토) | claude(대행 설계·판정) · apply(0토큰) | 불안정 테스트 근본 수정: `test_timeout_kills_worker_process_tree`의 0.3초 제한이 부모 프로세스의 자식 생성·pid 기록(부하 시 최대 0.44초, 중앙 0.34초)보다 짧아, 자식이 생기기 전에 종료되어 child.pid가 없었다(12코어 부하 15회 중 2회 재현). 제한을 3.0초(최악의 약 7배)로 올리고 전제 미충족을 명시적으로 실패시킨다. — `tests/test_u12_execution.py` |
| U83 | DONE-DELEGATED (Codex LIMITED 중 Claude 권한대행 2026-09-29 — Codex 복귀 시 재검토) | claude(대행 설계) · apply(0토큰) · codex(반례 제공) | 복구 잠금 경쟁 근본 수정(Codex REJECT of U49-G1R, `.work/u49g1r_verdict/verdict.txt`): 60초 넘게 멈춘 보유자의 `.recover` 파일을 다른 호출자가 나이(mtime)로 빼앗고, 재개한 보유자가 무조건 unlink로 새 보유자의 잠금을 지웠다(G1과 같은 원인 2회째). 잠금을 OS 바이트 잠금(Windows msvcrt.locking, POSIX flock)으로 바꿔 보유자 종료·충돌 시 OS가 풀고, 나이 기반 탈취와 unlink를 없앴다. — `v7_harness/coord/deliver.py`, `tests/test_u83_recover_lock.py` |

>>>>>>> REPLACE
===FILE: tests/test_u83_recover_lock.py===
"""U83: the guard recovery lock is never stolen by age (Codex REJECT of U49-G1R, 2026-09-29).

Counterexample from the verdict: a holder paused beyond RECOVER_STALE_S (60 s) had its `.recover` file renamed away by
the next caller, which then created its own; on resume the first holder mutated the guard concurrently and its
unconditional `finally` unlinked the new holder's lock. The lock is now an OS lock, released by the OS on exit or crash,
with no age-based stealing and no unlink. These tests hold the lock, age everything far past every threshold, and
check that no other caller takes, renames or deletes it; and that a crashed holder's lock frees itself.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from v7_harness.coord import deliver as deliver_module
from v7_harness.coord.mailbox import Mailbox

REPO = Path(__file__).resolve().parents[1]
# One hour: far past the old 60 s steal threshold and the 300 s guard threshold, so only the lock itself can refuse.
AGE_S = 3600


def _age(path: Path, seconds: float) -> None:
    old = time.time() - seconds
    os.utime(path, (old, old))


class RecoverLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / ".coord" / "mailbox").mkdir(parents=True)
        self.box = Mailbox(root / ".coord" / "mailbox")
        self.guards = root / "guards"
        self.guards.mkdir()
        self.guard = self.guards / "m1.lock"
        self.guard.write_text(json.dumps({"message_id": "m1", "owner": "crashed"}), encoding="utf-8")
        _age(self.guard, AGE_S)

    def test_paused_holder_keeps_the_lock_however_old(self) -> None:
        with deliver_module._recover_lock(self.guard, 0.0) as held:
            self.assertTrue(held)
            _age(self.guard.with_name(self.guard.name + ".recover"), AGE_S)  # the holder looks paused for an hour
            for _ in range(3):  # the old code stole on the first call and took over on the second
                self.assertIsNone(deliver_module._acquire_guard(self.guard, self.box, "m1", "d" * 64))
            self.assertEqual([], list(self.guards.glob("*.stale-*")), "the aged guard or the held lock was renamed")
            self.assertTrue(self.guard.is_file())
            self.assertTrue((self.guards / "m1.lock.recover").is_file(), "the held lock file was removed")

    def test_release_while_another_holds_the_lock_leaves_the_guard(self) -> None:
        self.guard.write_text(json.dumps({"message_id": "m1", "owner": "me"}), encoding="utf-8")
        with deliver_module._recover_lock(self.guard, 0.0) as held, \
                patch.object(deliver_module, "RELEASE_WAIT_S", 0.2):
            self.assertTrue(held)
            _age(self.guard.with_name(self.guard.name + ".recover"), AGE_S)
            deliver_module._release_guard(self.guard, "me")
            self.assertTrue(self.guard.is_file(), "release mutated the guard without the lock")
            self.assertTrue((self.guards / "m1.lock.recover").is_file(), "release removed another holder's lock")
        deliver_module._release_guard(self.guard, "me")  # once the holder is done, release proceeds
        self.assertFalse(self.guard.exists())

    def test_crashed_holder_lock_is_freed_by_the_os(self) -> None:
        holder = (
            "import sys, os\n"
            "from pathlib import Path\n"
            "from v7_harness.coord import deliver\n"
            "cm = deliver._recover_lock(Path(sys.argv[1]), 0.0)\n"
            "assert cm.__enter__() is True\n"
            "os._exit(0)  # dies holding the lock: no unlock, no cleanup\n"
        )
        done = subprocess.run([sys.executable, "-c", holder, str(self.guard)], cwd=REPO, capture_output=True,
                              text=True, timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)
        fd = deliver_module._acquire_guard(self.guard, self.box, "m1", "d" * 64)
        self.assertIsNotNone(fd, "a crashed holder's lock must not block recovery")
        os.close(fd)
        self.assertEqual(1, len(list(self.guards.glob("m1.lock.stale-*"))))

    def test_lock_is_exclusive_within_one_process(self) -> None:
        with deliver_module._recover_lock(self.guard, 0.0) as first:
            with deliver_module._recover_lock(self.guard, 0.1) as second:
                self.assertEqual((True, False), (first, second))
        with deliver_module._recover_lock(self.guard, 0.0) as again:
            self.assertTrue(again, "the lock was not released on exit")


if __name__ == "__main__":
    unittest.main()
===END===

## Output

- Reply with ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.
