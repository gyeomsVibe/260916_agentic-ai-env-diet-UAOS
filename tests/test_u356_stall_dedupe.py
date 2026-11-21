"""U356: the U166 stall hook prints a step only when the step changed, not every minute its age ticks.

Receipt (real use, 2026-11-22): `hook_lines` put `{age_s // 60} min` into the text it compared with
`.coord/stall/shown_<tool>.txt`, so the equality check failed every 60 s and all 28 lines (10 REROUTED +
18 WAIT IS FAILURE) were re-sent on every prompt. The display keeps the age; the dedupe compares an age-free signature.
"""

from __future__ import annotations

import copy
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v7_harness.coord import stall  # noqa: E402


def _stalled(item: str, age: int, owner: str = "claude", voters=("claude",)) -> dict:
    return {"item": item, "age_s": age, "waiting_on": "codex", "owner": owner, "action": "implement",
            "voters": list(voters), "present": ["claude", "antigravity"]}


def _blocked(item: str, age: int) -> dict:
    return {"item": item, "age_s": age, "waiting_on": "codex"}


def _settled(item: str, owner: str = "antigravity") -> dict:
    return {"item": item, "owner": owner, "phase_id": f"P-{item}"}


def _adopted(source: str, owner: str = "claude") -> dict:
    return {"source": source, "owner_tool": owner, "phase_id": f"A-{source}", "agreed_by": ["claude", "antigravity"]}


def _result(stalled=(), adopted=(), settled=(), blocked=()) -> dict:
    return {"stalled": list(stalled), "adopted": list(adopted), "settled": list(settled), "blocked": list(blocked)}


class StallDedupeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="u356_"))
        (self.root / ".git").mkdir()  # coord_root(): a worktree top folder holds .git
        (self.root / ".coord").mkdir()
        self.addCleanup(shutil.rmtree, self.root, True)

    def show(self, result: dict) -> str:
        with mock.patch.object(stall, "scan", return_value=copy.deepcopy(result)):
            return stall.hook_lines(self.root, "claude", now=0.0)

    def test_ticking_age_alone_is_shown_once(self) -> None:
        first = self.show(_result(stalled=[_stalled("U1", 600)], blocked=[_blocked("U2", 1200)]))
        self.assertIn("10 min", first)
        self.assertIn("20 min", first)
        for extra in (60, 600, 6000):
            with self.subTest(extra=extra):
                self.assertEqual("", self.show(_result(stalled=[_stalled("U1", 600 + extra)],
                                                       blocked=[_blocked("U2", 1200 + extra)])))

    def test_a_real_change_is_shown_at_once(self) -> None:
        base = _result(stalled=[_stalled("U1", 600)], blocked=[_blocked("U2", 600)])
        self.assertTrue(self.show(base))
        changes = {
            "added": _result(stalled=[_stalled("U1", 660)], blocked=[_blocked("U2", 660), _blocked("U3", 60)]),
            "removed": _result(stalled=[_stalled("U1", 720)]),
            "voters": _result(stalled=[_stalled("U1", 780, voters=("claude", "antigravity"))]),
            "owner": _result(stalled=[_stalled("U1", 840, owner="antigravity", voters=("claude", "antigravity"))]),
            "adopted": _result(stalled=[_stalled("U1", 900)], adopted=[_adopted("U1")]),
            "settled": _result(settled=[_settled("U1")]),
        }
        for name, result in changes.items():
            with self.subTest(change=name):
                self.assertTrue(self.show(result), f"{name} must be shown")
                self.assertEqual("", self.show(result), f"{name} unchanged must be quiet")

    def test_clearing_resets_so_a_recurrence_is_shown(self) -> None:
        stalled = _result(blocked=[_blocked("U2", 600)])
        self.assertTrue(self.show(stalled))
        self.assertEqual("", self.show(_result()))
        marker = self.root / ".coord" / "stall" / "shown_claude.txt"
        self.assertFalse(marker.exists(), "an empty scan must clear the marker")
        self.assertTrue(self.show(_result(blocked=[_blocked("U2", 60)])), "a recurrence must be shown again")

    def test_settled_reroutes_are_not_reprinted_while_blocked_ages_tick(self) -> None:
        settled = [_settled(f"S{i}") for i in range(10)]
        blocked = [_blocked(f"B{i}", 600 + i) for i in range(18)]
        text = self.show(_result(settled=settled, blocked=blocked))
        self.assertEqual(10, text.count("REROUTED (U166)"))
        self.assertEqual(18, text.count("WAIT IS FAILURE (U166)"))
        for tick in range(1, 6):
            aged = [_blocked(f"B{i}", 600 + i + 60 * tick) for i in range(18)]
            self.assertEqual("", self.show(_result(settled=settled, blocked=aged)))


if __name__ == "__main__":
    unittest.main()
