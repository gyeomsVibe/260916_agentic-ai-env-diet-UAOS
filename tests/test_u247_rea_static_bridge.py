import sqlite3
import tempfile
import unittest
from pathlib import Path

from v7_harness.rea_bridge import (
    build_reconstruction_obligation_ledger,
    generate_contract_manual_from_rea,
    inspect_static_target,
)


class TestU247ReaStaticBridge(unittest.TestCase):
    def test_forbids_execution_or_mutation(self):
        res = inspect_static_target(".", allow_execution=True)
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "MUTATION_OR_EXECUTION_FORBIDDEN")

    def test_static_source_and_sqlite_inspection_and_contract_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sample.py").write_text("def compute_pan(x):\n    return x * 2\n", encoding="utf-8")
            src_res = inspect_static_target(root)
            self.assertTrue(src_res["ok"])
            self.assertEqual(src_res["symbol_count"], 1)
            self.assertEqual(src_res["symbols"][0]["name"], "compute_pan")

            db_file = root / "state.db"
            conn = sqlite3.connect(db_file)
            conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, state TEXT)")
            conn.commit()
            conn.close()

            db_res = inspect_static_target(db_file)
            self.assertTrue(db_res["ok"])
            self.assertEqual(db_res["mode"], "STATIC_ONLY_SQLITE")
            self.assertEqual(db_res["tables"][0]["name"], "sessions")

            ledger = build_reconstruction_obligation_ledger(
                target_id="DXBALL-PAN",
                claims=[{"symbol": "compute_pan", "expected_behavior": "match x86 pan curve", "oracle_cases": 3205}],
            )
            self.assertFalse(ledger["global_equivalence_claimed"])
            manual = generate_contract_manual_from_rea(
                work_id="U247",
                obligation_ledger=ledger,
                allowed_files=["v7_harness/rea_bridge.py"],
                accept_cmd="python -m unittest tests.test_u247_rea_static_bridge",
                primary_sources=["https://zdnet.co.kr/view/?no=20261019165618", "https://github.com/morluto/rea"],
            )
            self.assertIn("DXBALL-PAN-OBL-001", manual)
            self.assertIn("https://github.com/morluto/rea", manual)


if __name__ == "__main__":
    unittest.main()
