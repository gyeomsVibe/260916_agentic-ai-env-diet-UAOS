"""Fixed acceptance: missing execution schedule is not coordinated completion."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from v7_harness.coord.next_card import next_step

class ScheduleBoundary(unittest.TestCase):
    def test_coordinated_missing_schedule_is_visible_for_all_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'.coord').mkdir()
            (root/'.coord/PLAN.md').write_text('Active authorized recovery', encoding='utf-8')
            for tool in ('codex','claude','antigravity'):
                with self.subTest(tool=tool):
                    result = next_step(root,tool)
                    self.assertEqual('WAIT',result['state'])
                    self.assertEqual('SCHEDULE_MISSING',result['code'])
                    self.assertIn('master_schedule.json',result['action'])
                    self.assertFalse((root/'.coord/next').exists())

    def test_legacy_uncoordinated_still_done(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual('DONE', next_step(Path(directory),'codex')['state'])

    def test_one_block_does_not_hide_other_ready_work(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'.coord').mkdir()
            phases = [dict(phase_id='release',state='HUMAN',owner_tool='codex',depends_on=[]),
                      dict(phase_id='design',state='READY',owner_tool='codex',depends_on=[])]
            (root/'.coord/master_schedule.json').write_text(json.dumps({'phases':phases}),encoding='utf-8')
            result = next_step(root,'codex')
            self.assertEqual(('NEXT','design'),(result['state'],result['card']))

if __name__ == '__main__':
    unittest.main()
