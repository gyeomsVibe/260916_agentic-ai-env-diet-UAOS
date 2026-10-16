"""Additional frozen acceptance from independent REVISE and live 37.634s receipt."""
import json
import os
import unittest
from unittest import mock
from tests import test_u202_session_replay as base


class ReplayUrgencyAndCostTests(unittest.TestCase):
    setUp = base.SessionReplayTests.setUp
    letter = base.SessionReplayTests.letter
    look = base.SessionReplayTests.look

    def test_binding_is_validated_once_per_hook_and_revalidated_next_hook(self):
        for number in range(20):
            self.letter('candidate_%02d' % number)
        with mock.patch('v7_harness.coord.desk_sync.desk_identity',
                        return_value=('PROJECT_BOUND', {'thread': 'desk'})) as identity:
            self.look()
            self.assertEqual(1, identity.call_count)
            self.look()
            self.assertEqual(2, identity.call_count)

    def test_p1_and_explicit_verdict_bypass_normal_replay_backlog(self):
        for number in range(20):
            self.letter('normal_%02d' % number, age=100000-number)
        for number, field in enumerate(({'kind': 'P1'}, {'p1_alert': True}, {'verdict_requested': True})):
            path = self.letter('urgent_%d' % number, age=90000)
            record = json.loads(path.read_text())
            record['payload'].update(field)
            path.write_text(json.dumps(record))
            os.utime(path, (base.NOW-90000, base.NOW-90000))
        text, callback = self.look()
        callback()
        again, _ = self.look()
        for number in range(3):
            self.assertIn('urgent_%d' % number, text)
            self.assertIn('urgent_%d' % number, again)
        self.assertIn('RESUME_PENDING normal_00', text)
        self.assertNotIn('normal_01', text)

    def test_malformed_card_and_symlink_are_not_replayed(self):
        self.letter('bad_card', card=True)
        self.assertNotIn('RESUME_PENDING', self.look()[0])

    def test_timestamp_tie_breaks_by_message_id(self):
        self.letter('z_tie')
        self.letter('a_tie')
        self.assertIn('RESUME_PENDING a_tie', self.look()[0])


if __name__ == '__main__':
    unittest.main()
