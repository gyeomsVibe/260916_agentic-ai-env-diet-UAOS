"""Independent P1 receipt: a READY label must not erase a recorded blocking gate."""
import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord import next_card


class ProtectedReady(unittest.TestCase):
    def project(self, directory, phases):
        root = Path(directory)
        (root/'.coord').mkdir(exist_ok=True)
        (root/'.coord/PLAN.md').write_text('# fixed fixture', encoding='utf-8')
        (root/'.coord/master_schedule.json').write_text(json.dumps({'phases': phases}), encoding='utf-8')
        return root

    def test_protected_own_candidate_does_not_starve_executable_work(self):
        for tool in ('codex', 'claude', 'antigravity'):
            for state in ('READY', 'PLANNED'):
                for marker in ({'blocker_kind': 'SAFETY_GATE'}, {'gate_failed': 'cost'}, {'human': 'fresh approval'}):
                    with self.subTest(tool=tool, state=state, marker=marker), tempfile.TemporaryDirectory() as d:
                        blocked = dict(phase_id='OLD_HOLD', state=state, owner_tool=tool, depends_on=[], **marker)
                        ready = dict(phase_id='EXECUTABLE', state='READY', owner_tool=tool, depends_on=[])
                        root = self.project(d, [blocked, ready])
                        result = next_card.next_step(root, tool)
                        self.assertEqual(('NEXT', 'EXECUTABLE'), (result.get('state'), result.get('card')))

    def test_foreign_protected_candidate_does_not_create_false_handoff(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.project(d, [dict(phase_id='U191-U185-FREEZE', state='READY',
                owner_tool='antigravity', depends_on=[], blocker_kind='SAFETY_GATE')])
            result = next_card.next_step(root, 'codex')
            self.assertEqual('WAIT', result['state'])
            self.assertFalse((root/'.coord/next/claims').exists())

    def test_new_blocker_between_selection_and_claim_refuses_claim(self):
        with tempfile.TemporaryDirectory() as d:
            original = dict(phase_id='RACE', state='READY', owner_tool='codex', depends_on=[])
            root = self.project(d, [dict(original, blocker_kind='SAFETY_GATE')])
            claims = root/'.coord/next/claims'
            accepted = next_card._claim(claims, 'RACE', 'codex', 'native-test-session', 100,
                schedule=root/'.coord/master_schedule.json', expected=original)
            self.assertFalse(accepted)
            self.assertFalse((claims/'RACE.json').exists())


if __name__ == '__main__':
    unittest.main()
