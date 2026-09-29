"""U85: an acceptance error raised as the project's own exception is CODE, not UNKNOWN.

Seen 2026-09-29: U83 (`v7_harness.coord.mailbox.MailboxRejected`) and U84-F1 (`v7_harness.coord.stream.StreamRejected`)
failed their acceptance with a project exception, both from a wrong test fixture. Triage called them UNKNOWN, so the RSI
window for apply reported "recurring UNKNOWN" with no remedy on file. The exception is defined in a staged module, so it
comes from the code under test or its test, which is CODE. Library and environment exceptions stay UNKNOWN.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from v7_harness.accept_triage import classify

# Tails of the real U83 and U84-F1 acceptance logs (paths shortened).
U83 = ('ERROR: test_x (tests.test_u83_recover_lock.RecoverLockTests.test_x)\nTraceback (most recent call last):\n'
       '  File "stage\\U83\\v7_harness\\coord\\mailbox.py", line 95, in __init__\n'
       '    raise MailboxRejected("root must exist and be a directory")\n'
       'v7_harness.coord.mailbox.MailboxRejected: root must exist and be a directory\n\nFAILED (errors=4)\n')
U84F1 = ('ERROR: test_y (tests.test_u84_stream_desk.StreamDeskTest.test_y)\nTraceback (most recent call last):\n'
         '  File "stage\\U84-F1\\v7_harness\\coord\\stream.py", line 179, in _validate\n'
         '    raise StreamRejected("MISSING_EVIDENCE_CMD")\n'
         'v7_harness.coord.stream.StreamRejected: MISSING_EVIDENCE_CMD\n\nFAILED (errors=1)\n')
SQLITE = ('ERROR: test_z (tests.t.T.test_z)\nTraceback (most recent call last):\n'
          '  File "stage\\X\\v7_harness\\db.py", line 9, in put\n    conn.execute(sql)\n'
          'sqlite3.OperationalError: database is locked\n\nFAILED (errors=1)\n')


class ProjectExceptionTriageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.staging = Path(self.tmp.name)
        for module in ("v7_harness/coord/mailbox.py", "v7_harness/coord/stream.py", "v7_harness/db.py"):
            (self.staging / module).parent.mkdir(parents=True, exist_ok=True)
            (self.staging / module).write_text("", encoding="utf-8")
        (self.staging / "v7_harness" / "__init__.py").write_text("", encoding="utf-8")

    def test_real_u83_and_u84f1_logs_are_code(self) -> None:
        self.assertEqual(("CODE", "v7_harness.coord.mailbox.MailboxRejected:"),
                         classify(U83, 1, staging=self.staging))
        self.assertEqual(("CODE", "v7_harness.coord.stream.StreamRejected:"),
                         classify(U84F1, 1, staging=self.staging))

    def test_a_package_level_exception_is_code(self) -> None:
        log = "ERROR: t\nv7_harness.WorkerFailed: boom\n\nFAILED (errors=1)\n"
        self.assertEqual("CODE", classify(log, 1, staging=self.staging)[0])

    def test_library_and_environment_exceptions_stay_unknown(self) -> None:
        self.assertEqual("UNKNOWN", classify(SQLITE, 1, staging=self.staging)[0])
        log = "ERROR: t\nsubprocess.TimeoutExpired: Command 'x' timed out after 5 seconds\n\nFAILED (errors=1)\n"
        self.assertEqual("UNKNOWN", classify(log, 1, staging=self.staging)[0])

    def test_without_staging_nothing_changes(self) -> None:
        self.assertEqual("UNKNOWN", classify(U83, 1)[0])

    def test_infra_signals_still_win_over_a_bare_project_name_elsewhere(self) -> None:
        log = "'agy' is not recognized as an internal or external command\n"
        self.assertEqual("INFRA", classify(log, 1, staging=self.staging)[0])


if __name__ == "__main__":
    unittest.main()
