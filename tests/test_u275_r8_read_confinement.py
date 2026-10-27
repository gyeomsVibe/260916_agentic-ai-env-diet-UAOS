"""U275-R8: opened-object read confinement for rea_bridge (ordinary files and mocked os calls only).

Per Codex PR244-R7: no directory-race fixture here; identity changes are simulated with mocked stat results.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness import rea_bridge as RB


class _FakeStat:
    def __init__(self, base: os.stat_result, *, ino: int | None = None, mode: int | None = None, attrs: int | None = None):
        self.st_mode = base.st_mode if mode is None else mode
        self.st_dev = base.st_dev
        self.st_ino = base.st_ino if ino is None else ino
        self.st_file_attributes = getattr(base, "st_file_attributes", 0) if attrs is None else attrs


class TestU275R8ReadConfinement(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.file = self.root / "sample.py"
        self.file.write_bytes(b"def alpha():\n    return 1\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _recording(self, *, fstat_ino=None, post_lstat_ino=None, lstat_attrs=None, lstat_mode=None):
        calls: list[str] = []
        opened_fds: list[int] = []
        closed_fds: list[int] = []
        real_lstat, real_open, real_fstat, real_read, real_close = os.lstat, os.open, os.fstat, os.read, os.close
        state = {"lstat_n": 0}

        def lstat(p, *a, **k):
            st = real_lstat(p, *a, **k)
            if Path(p) != self.file:
                return st
            calls.append("lstat")
            state["lstat_n"] += 1
            if state["lstat_n"] == 1 and (lstat_attrs is not None or lstat_mode is not None):
                return _FakeStat(st, attrs=lstat_attrs, mode=lstat_mode)
            if state["lstat_n"] == 2 and post_lstat_ino is not None:
                return _FakeStat(st, ino=post_lstat_ino)
            return st

        def open_(p, flags, *a, **k):
            calls.append("open")
            fd = real_open(p, flags, *a, **k)
            opened_fds.append(fd)
            return fd

        def fstat(fd):
            calls.append("fstat")
            st = real_fstat(fd)
            return _FakeStat(st, ino=fstat_ino) if fstat_ino is not None else st

        def read(fd, n):
            calls.append("read")
            return real_read(fd, n)

        def close(fd):
            closed_fds.append(fd)
            return real_close(fd)

        def ancestor(p, r=None):
            # Recorded separately: pathlib's own lstat calls inside the real ancestor check would otherwise be
            # counted as the helper's lstat gates (os is one module object, so the patch is process-wide).
            calls.append("ancestor")
            return False

        patches = [
            mock.patch.object(RB, "has_symlink_or_junction_ancestor", side_effect=ancestor),
            mock.patch.object(RB.os, "lstat", side_effect=lstat),
            mock.patch.object(RB.os, "open", side_effect=open_),
            mock.patch.object(RB.os, "fstat", side_effect=fstat),
            mock.patch.object(RB.os, "read", side_effect=read),
            mock.patch.object(RB.os, "close", side_effect=close),
        ]
        return calls, opened_fds, closed_fds, patches

    def _run(self, patches):
        for p in patches:
            p.start()
        try:
            return RB._read_confined_bytes(self.file, self.root)
        finally:
            for p in reversed(patches):
                p.stop()

    def test_call_order_lstat_open_fstat_lstat_read(self) -> None:
        calls, opened, closed, patches = self._recording()
        data = self._run(patches)
        self.assertEqual(data, self.file.read_bytes())
        first_read = calls.index("read")
        self.assertEqual(calls[:first_read], ["ancestor", "lstat", "open", "fstat", "ancestor", "lstat"])
        self.assertEqual(opened, closed)

    def test_fstat_identity_mismatch_reads_nothing_and_closes(self) -> None:
        calls, opened, closed, patches = self._recording(fstat_ino=987654321)
        with self.assertRaises(RB.ConfinementError) as ctx:
            self._run(patches)
        self.assertEqual(ctx.exception.code, "HANDLE_IDENTITY_MISMATCH")
        self.assertNotIn("read", calls)
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened, closed)

    def test_post_open_lstat_change_reads_nothing_and_closes(self) -> None:
        calls, opened, closed, patches = self._recording(post_lstat_ino=123456789)
        with self.assertRaises(RB.ConfinementError) as ctx:
            self._run(patches)
        self.assertEqual(ctx.exception.code, "HANDLE_IDENTITY_MISMATCH")
        self.assertNotIn("read", calls)
        self.assertEqual(opened, closed)

    def test_reparse_attribute_never_opens(self) -> None:
        calls, opened, _closed, patches = self._recording(lstat_attrs=RB.FILE_ATTRIBUTE_REPARSE_POINT)
        with self.assertRaises(RB.ConfinementError) as ctx:
            self._run(patches)
        self.assertEqual(ctx.exception.code, "NOT_REGULAR_FILE")
        self.assertNotIn("open", calls)
        self.assertEqual(opened, [])

    def test_non_regular_mode_never_opens(self) -> None:
        import stat as _stat
        calls, opened, _closed, patches = self._recording(lstat_mode=_stat.S_IFDIR | 0o755)
        with self.assertRaises(RB.ConfinementError) as ctx:
            self._run(patches)
        self.assertEqual(ctx.exception.code, "NOT_REGULAR_FILE")
        self.assertNotIn("open", calls)

    def test_outside_root_refused_before_lstat(self) -> None:
        with tempfile.TemporaryDirectory() as other:
            outside = Path(other) / "x.py"
            outside.write_bytes(b"secret")
            with mock.patch.object(RB.os, "open", side_effect=AssertionError("must not open")):
                with self.assertRaises(RB.ConfinementError) as ctx:
                    RB._read_confined_bytes(outside, self.root)
            self.assertEqual(ctx.exception.code, "SYMLINK_OR_JUNCTION_ESCAPE")

    def test_opened_handle_outside_root_reads_nothing(self) -> None:
        # rev2 (Claude P2): names can be raced; the OS path of the opened object decides.
        calls, opened, closed, patches = self._recording()
        patches.append(mock.patch.object(RB, "_opened_final_path", return_value=str(Path(tempfile.gettempdir()).parent / "outside.py")))
        with self.assertRaises(RB.ConfinementError) as ctx:
            self._run(patches)
        self.assertEqual(ctx.exception.code, "HANDLE_PATH_OUTSIDE_ROOT")
        self.assertNotIn("read", calls)
        self.assertEqual(opened, closed)

    def test_handle_path_api_failure_fails_closed(self) -> None:
        calls, opened, closed, patches = self._recording()
        patches.append(mock.patch.object(RB, "_opened_final_path", side_effect=RB.ConfinementError("HANDLE_PATH_UNKNOWN", "fd")))
        with self.assertRaises(RB.ConfinementError) as ctx:
            self._run(patches)
        self.assertEqual(ctx.exception.code, "HANDLE_PATH_UNKNOWN")
        self.assertNotIn("read", calls)
        self.assertEqual(opened, closed)

    def test_real_opened_handle_path_is_inside_root(self) -> None:
        fd = os.open(self.file, os.O_RDONLY)
        try:
            self.assertTrue(RB._within(RB._opened_final_path(fd), self.root))
        finally:
            os.close(fd)

    def test_happy_path_inspections_still_pass(self) -> None:
        (self.root / "app.exe").write_bytes(b"MZ\x00https://example.com/api src-tauri/main.rs")
        db = self.root / "state.sqlite"
        con = sqlite3.connect(str(db))
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE t1 (id INT)")
        con.commit()
        res = RB.inspect_static_target(self.root)
        con.close()
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["failed_files"], [])
        names = {s["name"] for s in res["symbols"]}
        self.assertIn("alpha", names)
        self.assertIn("url:https://example.com/api", names)
        self.assertIn("sqlite_table:t1", names)

    def test_confinement_error_surfaces_in_failed_files(self) -> None:
        with mock.patch.object(RB, "_read_confined_bytes", side_effect=RB.ConfinementError("HANDLE_IDENTITY_MISMATCH", self.file)):
            res = RB.inspect_static_target(self.root)
        self.assertIn({"file": "sample.py", "error": "HANDLE_IDENTITY_MISMATCH"}, res["failed_files"])
        self.assertFalse(res["source_complete"])


if __name__ == "__main__":
    unittest.main()
