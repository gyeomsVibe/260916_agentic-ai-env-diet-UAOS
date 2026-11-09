"""Unit tests for WiseCare365 reverse-engineered UAOS cleaner module."""

import unittest
from pathlib import Path
import tempfile
import time
from v7_harness.coord import cleaner

class TestCleaner(unittest.TestCase):
    def test_cleaner_dry_run_and_safe_defaults(self):
        res = cleaner.run_system_cleanup(dry_run=True)
        self.assertIn("zombies_killed", res)
        self.assertIn("textinput_action", res)
        self.assertIn("trimmed_procs", res)
        self.assertIn("temp_files_cleaned", res)
        self.assertTrue(res["dry_run"])
        self.assertEqual(res["console_shield"]["action"], "SKIPPED_DRY_RUN")
        self.assertEqual(res["temp_files_cleaned"], 0)
        for z in res["zombies_killed"]:
            self.assertEqual(z["status"], "DRY_RUN")

        # Default call without arguments is also dry_run=True and opt-out of side effects
        res_default = cleaner.run_system_cleanup()
        self.assertTrue(res_default["dry_run"])
        self.assertEqual(res_default["console_shield"]["action"], "SKIPPED_DRY_RUN")

        # Even with dry_run=False, destructive/daemon actions require explicit opt-in flags
        res_no_optin = cleaner.run_system_cleanup(dry_run=False)
        self.assertEqual(res_no_optin["console_shield"]["action"], "SKIPPED_OPT_OUT")
        self.assertEqual(res_no_optin["temp_files_cleaned"], 0)
        for z in res_no_optin["zombies_killed"]:
            self.assertEqual(z["status"], "DRY_RUN")
        self.assertFalse(cleaner.enforce_zero_console_registry(dry_run=True, enable_console_shield=True))
        self.assertFalse(cleaner.enforce_zero_console_registry(dry_run=False, enable_console_shield=False))

    def test_temp_cleanup_with_age(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir)
            f_old = p / "old.tmp"
            f_old.write_text("old", encoding="utf-8")
            f_new = p / "new.tmp"
            f_new.write_text("new", encoding="utf-8")
            
            # Artificially age f_old to 3 days ago
            old_time = time.time() - (86400 * 3)
            import os
            os.utime(f_old, (old_time, old_time))
            
            cleaned = cleaner.clean_temp_directory(p, max_age_hours=24, dry_run=False)
            self.assertEqual(cleaned, 1)
            self.assertFalse(f_old.exists())
            self.assertTrue(f_new.exists())

if __name__ == "__main__":
    unittest.main()
