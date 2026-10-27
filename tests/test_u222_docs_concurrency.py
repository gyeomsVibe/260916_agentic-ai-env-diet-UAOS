"""U222 fixed acceptance: docs_manager counterexamples (numbering width, overwrite, real processes, lock, slugs).

Every case runs in a tempdir; the real docs/ folder is never touched. Counterexamples come from
the U222 red-team record (width limit, overwrite, lost update under two real OS processes).
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from v7_harness import docs_manager as dm  # noqa: E402

# One child process: wait until the barrier file exists, then create one doc. Two of these race for real.
CHILD = (
    "import sys, time\n"
    "from pathlib import Path\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "from v7_harness import docs_manager as dm\n"
    "barrier = Path(sys.argv[3])\n"
    "deadline = time.time() + 30\n"
    "while not barrier.exists() and time.time() < deadline:\n"
    "    time.sleep(0.005)\n"
    "p = dm.register_new_doc(Path(sys.argv[2]), 'T ' + sys.argv[4], slug='s' + sys.argv[4], content='body ' + sys.argv[4])\n"
    "print(p.name)\n"
)


class NumberingPast999(unittest.TestCase):
    def test_numbers_continue_past_999_and_never_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs"
            docs.mkdir()
            (docs / "999_last.md").write_text("# last\n", encoding="utf-8")
            first = dm.register_new_doc(root, "First", slug="first", content="FIRST")
            second = dm.register_new_doc(root, "Second", slug="second", content="SECOND")
            third = dm.register_new_doc(root, "Third", slug="third", content="THIRD")
            self.assertEqual([first.name, second.name, third.name],
                             ["1000_first.md", "1001_second.md", "1002_third.md"])
            self.assertEqual(first.read_text(encoding="utf-8"), "FIRST")
            self.assertEqual(second.read_text(encoding="utf-8"), "SECOND")


class RealProcessRace(unittest.TestCase):
    def test_two_processes_get_distinct_numbers_and_keep_both_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            barrier = root / "go.flag"
            procs = [subprocess.Popen([sys.executable, "-c", CHILD, str(ROOT), str(root), str(barrier), tag],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                     for tag in ("a", "b")]
            time.sleep(0.5)
            barrier.write_text("go", encoding="utf-8")
            outs = [p.communicate(timeout=60) for p in procs]
            self.assertEqual([p.returncode for p in procs], [0, 0], outs)
            names = sorted(o[0].strip() for o in outs)
            self.assertEqual(len(set(names)), 2, names)
            self.assertEqual(sorted(n.split("_")[0] for n in names), ["01", "02"])
            for tag in ("a", "b"):
                body = next((root / "docs" / n).read_text(encoding="utf-8") for n in names if n.endswith(f"s{tag}.md"))
                self.assertEqual(body, f"body {tag}")
            index = (root / "docs" / dm.INDEX_FILENAME).read_text(encoding="utf-8")
            for n in names:
                self.assertEqual(index.count(f"[{n}]"), 1, index)


class CollisionAndLock(unittest.TestCase):
    def test_forced_collision_raises_and_keeps_original_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            victim = root / "docs" / "01_dup.md"
            victim.write_bytes(b"ORIGINAL")
            real = dm.allocate_next_doc_number
            dm.allocate_next_doc_number = lambda *a, **k: (1, "01_")
            try:
                with self.assertRaises(FileExistsError):
                    dm.register_new_doc(root, "Dup", slug="dup", content="NEW")
            finally:
                dm.allocate_next_doc_number = real
            self.assertEqual(victim.read_bytes(), b"ORIGINAL")

    def test_lock_is_released_after_an_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                dm.register_new_doc(root, "Bad", slug="a/b")
            self.assertFalse(getattr(dm._DOC_LOCKS, "owned", set()))
            done = dm.register_new_doc(root, "Good", slug="good")
            self.assertTrue(done.is_file())


class SlugSafety(unittest.TestCase):
    def test_path_like_slugs_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for bad in ("../x", "a/b", "a\\b", "x:y"):
                with self.subTest(slug=bad):
                    with self.assertRaises(ValueError):
                        dm.register_new_doc(root, "T", slug=bad)
            self.assertEqual([p.name for p in (root / "docs").iterdir()], [dm.INDEX_FILENAME])

    def test_reserved_device_name_slug_stays_inside_docs_with_number_prefix(self):
        # "CON" alone is a Windows device name, but the NN_ prefix makes the file name ordinary.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            made = dm.register_new_doc(root, "T", slug="CON", content="x")
            self.assertEqual(made.parent, root / "docs")
            self.assertEqual(made.name, "01_CON.md")
            self.assertEqual(made.read_text(encoding="utf-8"), "x")


if __name__ == "__main__":
    unittest.main()
