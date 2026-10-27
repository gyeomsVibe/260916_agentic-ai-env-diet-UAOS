import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from v7_harness import rea_bridge
from v7_harness.rea_bridge import (
    ConfinementError,
    _inspect_binary_static,
    _inspect_sqlite_static,
    _read_confined_bytes,
)


class ReadConfinementTests(unittest.TestCase):
    def test_happy_path_returns_exact_bytes(self):
        payload = b"alpha\x00beta\xff gamma"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "sample.bin"
            target.write_bytes(payload)
            self.assertEqual(_read_confined_bytes(target, root), payload)

    def test_fstat_identity_mismatch_raises_and_closes_fd(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "sample.bin"
            target.write_bytes(b"data")
            real_fstat = rea_bridge.os.fstat

            def fake_fstat(fd):
                real = real_fstat(fd)
                return type("FakeStat", (), {
                    "st_mode": real.st_mode,
                    "st_dev": real.st_dev,
                    "st_ino": real.st_ino + 1,
                })()

            with patch("v7_harness.rea_bridge.os.fstat", side_effect=fake_fstat), \
                    patch("v7_harness.rea_bridge.os.close", wraps=rea_bridge.os.close) as close_mock:
                with self.assertRaises(ConfinementError) as ctx:
                    _read_confined_bytes(target, root)
            self.assertEqual(ctx.exception.code, "HANDLE_IDENTITY_MISMATCH")
            self.assertTrue(close_mock.called)

    def test_directory_is_not_regular_and_open_never_called(self):
        with tempfile.TemporaryDirectory() as tmp:
            subdir = Path(tmp) / "folder"
            subdir.mkdir()
            with patch("v7_harness.rea_bridge.os.open") as open_mock:
                with self.assertRaises(ConfinementError) as ctx:
                    _read_confined_bytes(subdir)
            self.assertEqual(ctx.exception.code, "NOT_REGULAR_FILE")
            open_mock.assert_not_called()

    def test_binary_inspect_real_file_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "tool.wasm"
            target.write_bytes(b"\x00https://example.com/api\x00src-tauri/main.rs\x00")
            res = _inspect_binary_static(target)
            self.assertTrue(res["ok"])
            self.assertIn("https://example.com/api", res["urls"])

    def test_sqlite_inspect_real_db_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "sample.db"
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
            conn.commit()
            conn.close()
            res = _inspect_sqlite_static(db)
            self.assertTrue(res["ok"], res)
            self.assertEqual([t["name"] for t in res["tables"]], ["items"])

    def test_binary_inspect_identity_mismatch_returns_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "tool.dll"
            target.write_bytes(b"MZ-binary-bytes")
            real_fstat = rea_bridge.os.fstat

            def fake_fstat(fd):
                real = real_fstat(fd)
                return type("FakeStat", (), {
                    "st_mode": real.st_mode,
                    "st_dev": real.st_dev,
                    "st_ino": real.st_ino + 1,
                })()

            with patch("v7_harness.rea_bridge.os.fstat", side_effect=fake_fstat):
                res = _inspect_binary_static(target)
            self.assertFalse(res["ok"])
            self.assertEqual(res["error"], "HANDLE_IDENTITY_MISMATCH")


if __name__ == "__main__":
    unittest.main()
