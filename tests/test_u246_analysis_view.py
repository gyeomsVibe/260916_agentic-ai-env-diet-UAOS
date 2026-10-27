import tempfile
import unittest
from pathlib import Path

from v7_harness.analysis_view import inspect_analysis_view, retain_analysis_bundle


class TestU246AnalysisView(unittest.TestCase):
    def test_summary_first_and_paginated_field_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            items = [
                {"name": f"fn_{i}", "address": f"0x40{i:02x}", "pseudocode": f"int fn_{i}() {{ return {i}; }}"}
                for i in range(10)
            ]
            summary = retain_analysis_bundle(
                tmp,
                kind="native-inventory",
                target_path="dxball.exe",
                items=items,
                source_complete=False,
            )
            self.assertEqual(summary["detail"], "summary")
            self.assertEqual(summary["total_items"], 10)
            pid = summary["parent_evidence_id"]

            page = inspect_analysis_view(tmp, parent_evidence_id=pid, offset=2, limit=3, fields=["name"])
            self.assertTrue(page["ok"])
            self.assertEqual(len(page["rows"]), 3)
            self.assertEqual(page["rows"][0]["name"], "fn_2")
            self.assertEqual(page["rows"][0]["source_index"], 2)
            self.assertEqual(page["rows"][0]["address"], "0x4002")
            self.assertNotIn("pseudocode", page["rows"][0])
            self.assertEqual(page["coverage"]["next_offset"], 5)
            self.assertFalse(page["coverage"]["absence_established"])

            empty_filtered = inspect_analysis_view(tmp, parent_evidence_id=pid, names=["missing_symbol"])
            # Because source_complete is False, empty page does NOT establish absence
            self.assertFalse(empty_filtered["coverage"]["absence_established"])


if __name__ == "__main__":
    unittest.main()
