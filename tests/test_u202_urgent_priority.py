"""Independent P1 counterexample: diagnostic overflow cannot hide urgent mail."""
import json
import os
import unittest
from unittest import mock
from tests import test_u202_session_replay as base


class UrgentPriorityTests(unittest.TestCase):
    setUp = base.SessionReplayTests.setUp
    letter = base.SessionReplayTests.letter
    look = base.SessionReplayTests.look

    def test_diagnostic_overflow_cannot_hide_an_urgent_replayed_letter(self):
        self.letter('normal_head', age=100000)
        path = self.letter('urgent_p1', age=90000)
        record = json.loads(path.read_text())
        record['payload']['kind'] = 'P1'
        path.write_text(json.dumps(record))
        os.utime(path, (base.NOW-90000, base.NOW-90000))
        with mock.patch('v7_harness.coord.desk_delta._receipt_findings',
                        return_value=(['bad_receipt'] * (base.D.MAX_LINES+5), {})):
            text, _ = self.look()
        self.assertIn('RESUME_PENDING normal_head', text)
        self.assertIn('letter urgent_p1:', text)


if __name__ == '__main__':
    unittest.main()
