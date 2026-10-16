"""Frozen judge acceptance: a displayed wake is not a processed letter."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import desk_delta as D
from v7_harness.coord.mailbox import Mailbox

NOW = 1800000000


class SessionReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.boxroot = self.root / '.coord/mailbox'
        self.boxroot.mkdir(parents=True)
        self.box = Mailbox(self.boxroot)
        for target, replacement in (
            ('v7_harness.coord.desk_sync.desk_identity', ('PROJECT_BOUND', {'thread': 'desk'})),
            ('v7_harness.coord.desk_sync.prepare_notice', ('', lambda: None)),
            ('v7_harness.coord.desk_delta.absence_items', []),
        ):
            patcher = mock.patch(target, return_value=replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def letter(self, name, tool='codex', age=90000, card=None):
        body = {'actor': 'claude' if tool != 'claude' else 'codex',
                'requested_target': tool, 'message': 'payload-' + name}
        if card is not None:
            body['card'] = card
        path = self.box.publish(name, body)
        os.utime(path, (NOW-age, NOW-age))
        return path

    def look(self, tool='codex', session='desk'):
        return D.prepare_delta(self.root, tool, session, now=NOW)

    def test_old_messages_replay_for_all_tools(self):
        for tool in D.TOOLS:
            with self.subTest(tool=tool):
                path = self.letter('old_' + tool, tool)
                text, acknowledge_display = self.look(tool)
                self.assertIn('RESUME_PENDING ' + path.stem, text)
                acknowledge_display()
                self.assertTrue(path.exists())
                self.assertFalse((self.box.ack_dir / path.name).exists())

    def test_arrival_order_beats_hash_order_and_head_blocks_next(self):
        self.letter('z_first', age=90000)
        self.letter('a_second', age=80000)
        text, _ = self.look()
        self.assertIn('RESUME_PENDING z_first', text)
        self.assertNotIn('a_second', text)

    def test_display_cursor_and_session_restart_do_not_consume(self):
        self.letter('retained')
        text, flush_receipt = self.look()
        self.assertIn('retained', text)
        flush_receipt()
        self.assertIn('RESUME_PENDING retained', self.look()[0])
        with mock.patch('v7_harness.coord.desk_sync.desk_identity',
                        return_value=('PROJECT_BOUND', {'thread': 'replacement'})):
            self.assertIn('RESUME_PENDING retained', self.look(session='replacement')[0])

    def test_crash_before_flush_keeps_head(self):
        self.letter('not_flushed')
        self.look()  # no output-completion callback
        self.assertIn('RESUME_PENDING not_flushed', self.look()[0])
        self.assertFalse(D.cursor_path(self.root, 'codex', 'desk').exists())

    def test_explicit_processing_ack_advances_one_head(self):
        self.letter('z_first', age=90000)
        self.letter('a_second', age=80000)
        claim = self.box.claim('z_first', 'judge')
        self.box.ack(claim)
        text, _ = self.look()
        self.assertNotIn('z_first', text)
        self.assertIn('RESUME_PENDING a_second', text)

    def test_wrong_target_and_session_fail_closed(self):
        self.letter('foreign', 'claude')
        self.letter('ours')
        self.assertNotIn('RESUME_PENDING foreign', self.look()[0])
        self.assertNotIn('RESUME_PENDING', self.look(session='stranger')[0])
        self.assertNotIn('RESUME_PENDING', self.look(session=None)[0])

    def test_unknown_desk_fails_closed(self):
        self.letter('ours')
        for status in ('ABSENT', 'CORRUPT', 'UNBOUND_EXISTS', 'UNVERIFIED'):
            with mock.patch('v7_harness.coord.desk_sync.desk_identity', return_value=(status, {})):
                self.assertNotIn('RESUME_PENDING', self.look()[0], status)

    def test_card_replay_only_in_bound_window_for_all_tools(self):
        for tool in D.TOOLS:
            with self.subTest(tool=tool):
                self.letter('card_' + tool, tool, card='U202')
                with mock.patch('v7_harness.coord.windows.window_for', return_value='worker'):
                    self.assertNotIn('RESUME_PENDING card_' + tool, self.look(tool)[0])
                    self.assertIn('RESUME_PENDING card_' + tool, self.look(tool, 'worker')[0])

    def test_ack_duplicate_is_excluded(self):
        path = self.letter('already_done')
        (self.box.ack_dir / path.name).write_bytes(path.read_bytes())
        self.assertNotIn('RESUME_PENDING', self.look()[0])

    def test_overflow_keeps_oldest_and_remaining_on_disk(self):
        for number in range(D.MAX_LINES + 4):
            self.letter('backlog_%02d' % number, age=90000-number)
        text, callback = self.look()
        self.assertIn('RESUME_PENDING backlog_00', text)
        self.assertNotIn('backlog_01', text)
        callback()
        self.assertEqual(D.MAX_LINES+4, len(self.box.list_inbox()))

    def test_read_only_preparation_and_no_dispatch(self):
        self.letter('untouched')
        before = {str(p.relative_to(self.root)): p.read_bytes()
                  for p in self.root.rglob('*') if p.is_file()}
        with mock.patch('v7_harness.coord.deliver.deliver', side_effect=AssertionError('dispatch forbidden')):
            self.look()
        after = {str(p.relative_to(self.root)): p.read_bytes()
                 for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
