"""Tests for v7_harness.docs_manager."""

import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta

from v7_harness.docs_manager import (
    ensure_docs_dir,
    ensure_doc_index,
    parse_doc_filename,
    allocate_next_doc_number,
    register_new_doc,
    scan_docs,
    sync_doc_index,
    INDEX_FILENAME
)

KST = timezone(timedelta(hours=9))


class TestDocsManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_ensure_docs_and_index(self):
        docs_dir = ensure_docs_dir(self.project)
        self.assertTrue(docs_dir.is_dir())
        self.assertEqual(docs_dir.name, "docs")

        index_path = ensure_doc_index(self.project)
        self.assertTrue(index_path.is_file())
        self.assertEqual(index_path.name, INDEX_FILENAME)
        text = index_path.read_text(encoding="utf-8")
        self.assertIn("전체 문서 전수 매핑 테이블", text)

    def test_parse_doc_filename(self):
        num, prefix, base = parse_doc_filename("01_test_doc.md")
        self.assertEqual(num, 1)
        self.assertEqual(prefix, "01_")
        self.assertEqual(base, "test_doc.md")

        num2, prefix2, base2 = parse_doc_filename("84_auto_init.md")
        self.assertEqual(num2, 84)
        self.assertEqual(prefix2, "84_")
        self.assertEqual(base2, "auto_init.md")

        num3, prefix3, base3 = parse_doc_filename("README.md")
        self.assertIsNone(num3)
        self.assertEqual(prefix3, "")
        self.assertEqual(base3, "README.md")

    def test_allocate_next_doc_number_empty(self):
        next_num, prefix = allocate_next_doc_number(self.project)
        self.assertEqual(next_num, 1)
        self.assertEqual(prefix, "01_")

    def test_register_new_doc_and_sequential_numbering(self):
        # Register doc 1
        doc1 = register_new_doc(
            self.project,
            title="First Architecture Decision",
            slug="first-architecture-decision"
        )
        self.assertTrue(doc1.is_file())
        self.assertEqual(doc1.name, "01_first-architecture-decision.md")

        # Register doc 2
        doc2 = register_new_doc(
            self.project,
            title="Second Decision",
            slug="second-decision"
        )
        self.assertTrue(doc2.is_file())
        self.assertEqual(doc2.name, "02_second-decision.md")

        # Check index contents
        index_text = (self.project / "docs" / INDEX_FILENAME).read_text(encoding="utf-8")
        self.assertIn("01_first-architecture-decision.md", index_text)
        self.assertIn("02_second-decision.md", index_text)
        self.assertIn("First Architecture Decision", index_text)
        self.assertIn("Second Decision", index_text)

        # Allocate next
        next_num, prefix = allocate_next_doc_number(self.project)
        self.assertEqual(next_num, 3)
        self.assertEqual(prefix, "03_")

    def test_sync_doc_index(self):
        # Manually create doc files
        docs_dir = ensure_docs_dir(self.project)
        (docs_dir / "01_foo.md").write_text("# Foo Title\nBody", encoding="utf-8")
        (docs_dir / "02_bar.md").write_text("# Bar Title\nBody", encoding="utf-8")
        
        count = sync_doc_index(self.project)
        self.assertEqual(count, 2)
        index_text = (docs_dir / INDEX_FILENAME).read_text(encoding="utf-8")
        self.assertIn("01_foo.md", index_text)
        self.assertIn("Foo Title", index_text)
        self.assertIn("02_bar.md", index_text)
        self.assertIn("Bar Title", index_text)


if __name__ == "__main__":
    unittest.main()
