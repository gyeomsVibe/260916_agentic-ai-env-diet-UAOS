"""U365: the live situational regime in every session briefing line (pure, 0 tokens).

Receipt: U355-B shipped `situational_ops.detect_regime`, but no hook line showed the live regime, so each tool had to
re-derive who is alive from the raw desk. `brief_line` now says `Regime: <REGIME>.` right after the desk, fails closed
to LOCAL_ONLY on broken presence, and keeps its 400-character cap without ever clipping the mandatory tail.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v7_harness.coord.hook_context import BRIEF_MAX, BRIEF_TAIL, brief_line, situational_line  # noqa: E402

NOW = 1_800_000_000.0
TAIL_END = "never via the user."


def _rec(state: str, age: float = 10.0) -> dict:
    return {"state": state, "observed_at": NOW - age}


def _desk(codex: str, claude: str, agy: str, age: float = 10.0) -> dict:
    return {"codex": _rec(codex, age), "claude": _rec(claude, age), "antigravity": _rec(agy, age)}


class U365SituationalHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _assert_budget(self, line: str) -> None:
        self.assertLessEqual(len(line), BRIEF_MAX, line)
        self.assertTrue(line.endswith(TAIL_END), line)
        self.assertTrue(line.endswith(BRIEF_TAIL), line)

    def test_peer_silent_limit_exhausted_regime(self) -> None:
        self.assertEqual("Regime: DUO_CLAUDE_AGY",
                         situational_line(self.project, _desk("LIMITED", "ACTIVE", "ACTIVE"), now=NOW))
        self.assertEqual("Regime: SOLO_CLAUDE",
                         situational_line(self.project, _desk("ABSENT", "ACTIVE", "LIMITED"), now=NOW))
        silent = {"codex": _rec("ACTIVE", age=61.0), "claude": _rec("ACTIVE"), "antigravity": _rec("ACTIVE")}
        self.assertEqual("Regime: DUO_CLAUDE_AGY", situational_line(self.project, silent, now=NOW))
        line = brief_line(self.project, _desk("LIMITED", "ACTIVE", "ACTIVE"), now=NOW)
        self.assertIn("antigravity=ACTIVE. Regime: DUO_CLAUDE_AGY. Mode:", line)
        self._assert_budget(line)

    def test_message_flood_inbox_counting(self) -> None:
        inbox = self.project / ".coord" / "mailbox" / "inbox"
        inbox.mkdir(parents=True)
        for index in range(600):
            (inbox / f"wake_{index:04d}.json").write_text("{}", encoding="utf-8")
        for index in range(500):
            (inbox / f"rsi_review_{index:04d}.json").write_text("{}", encoding="utf-8")
        (inbox / "relay_x.json").write_text("{}", encoding="utf-8")
        line = brief_line(self.project, _desk("ACTIVE", "ACTIVE", "ACTIVE"), now=NOW)
        self.assertIn("inbox 1101 (P1 600, RSI reviews 500); desk codex=ACTIVE", line)
        self.assertIn("Regime: TRIO.", line)
        self._assert_budget(line)

    def test_wait_cycle_deadlock_fail_closed(self) -> None:
        cyclic: dict = {"codex": {"state": "ACTIVE", "observed_at": NOW}}
        cyclic["claude"] = cyclic  # a self-referencing desk, no observed_at on that record
        with mock.patch("v7_harness.coord.situational_ops.detect_regime", side_effect=RecursionError("cycle")):
            self.assertEqual("Regime: LOCAL_ONLY", situational_line(self.project, cyclic, now=NOW))
        for broken in ({}, {"codex": {"state": "ACTIVE"}}, {"claude": {"state": "ACTIVE", "observed_at": None}}):
            with self.subTest(broken=broken):
                self.assertEqual("Regime: LOCAL_ONLY", situational_line(self.project, broken, now=NOW))

    def test_crash_mid_write_corrupted_presence(self) -> None:
        for corrupt in (None, "{\"codex\": {\"state\": \"ACT", ["codex"], 42, {"codex": "ACTIVE"}):
            with self.subTest(corrupt=corrupt):
                self.assertEqual("Regime: LOCAL_ONLY", situational_line(self.project, corrupt, now=NOW))  # type: ignore[arg-type]
        self.assertEqual("Regime: LOCAL_ONLY",
                         situational_line(self.project, {"claude": {"state": "ACTIVE", "observed_at": "not-a-time"}},
                                          now=NOW))
        with mock.patch("v7_harness.coord.situational_ops.detect_regime", side_effect=ValueError("torn")):
            self.assertEqual("Regime: LOCAL_ONLY",
                             situational_line(self.project, _desk("ACTIVE", "ACTIVE", "ACTIVE"), now=NOW))
        self.assertEqual("Regime: LOCAL_ONLY", situational_line(self.project, _desk("ACTIVE", "ACTIVE", "ACTIVE"),
                                                                now="garbage"))  # type: ignore[arg-type]

    def test_duplicate_delivery_idempotence(self) -> None:
        desk = _desk("ACTIVE", "ACTIVE", "LIMITED")
        first = brief_line(self.project, desk, now=NOW)
        second = brief_line(self.project, dict(desk), now=NOW)
        self.assertEqual(first, second)
        self.assertIn("Regime: DUO_CODEX_CLAUDE.", first)
        self.assertEqual(situational_line(self.project, desk, now=NOW), situational_line(self.project, desk, now=NOW))
        self.assertEqual(desk, _desk("ACTIVE", "ACTIVE", "LIMITED"))  # the desk is not mutated

    def test_stale_state_age_formatting_and_regime(self) -> None:
        old = datetime.fromtimestamp(NOW - 720 * 3600, tz=timezone.utc).isoformat()  # live presence.mark() format
        stale = {"codex": {"state": "UNKNOWN", "observed_at": old},
                 "claude": _rec("ACTIVE"),
                 "antigravity": {"state": "ACTIVE", "observed_at": old}}
        self.assertEqual("Regime: SOLO_CLAUDE", situational_line(self.project, stale, now=NOW))
        with mock.patch("v7_harness.coord.presence.time.time", return_value=NOW):
            line = brief_line(self.project, stale, now=NOW)
        self.assertIn("codex=IDLE(720h)", line)
        self.assertIn("Regime: SOLO_CLAUDE.", line)
        self._assert_budget(line)

    def test_conductor_down_duo_claude_agy(self) -> None:
        for codex in ({"state": "ABSENT", "observed_at": NOW - 5}, {"state": "ACTIVE", "observed_at": NOW - 3600}):
            desk = {"codex": codex, "claude": _rec("ACTIVE"), "antigravity": _rec("ACTIVE")}
            with self.subTest(codex=codex):
                self.assertEqual("Regime: DUO_CLAUDE_AGY", situational_line(self.project, desk, now=NOW))
                self.assertIn("Regime: DUO_CLAUDE_AGY.", brief_line(self.project, desk, now=NOW))

    def test_user_absent_tail_and_budget_preservation(self) -> None:
        old = datetime.fromtimestamp(NOW - 720 * 3600, tz=timezone.utc).isoformat()
        idle = {tool: {"state": "UNKNOWN", "observed_at": old} for tool in ("codex", "claude", "antigravity")}
        rsi = {"session_id": "f" * 40}
        korean = "Mode: normal, set by 윤겸스 (" + "사용자 부재 중 장문 사유 " * 6 + ")."
        with mock.patch("v7_harness.coord.process_lanes.latest_rsi_upgrade_session", return_value=rsi), \
                mock.patch("v7_harness.coord.mode.mode_phrase", return_value=korean), \
                mock.patch("v7_harness.coord.presence.time.time", return_value=NOW):
            line = brief_line(self.project, idle, now=NOW)
        self.assertEqual(BRIEF_MAX, len(line))
        self.assertIn(korean, line)
        self.assertTrue(line.startswith(f"UAOS project proj [RSI:{'f' * 40}]: inbox"), line)
        self.assertIn("... " + korean, line)
        self._assert_budget(line)
        for size in (300, 5000):  # a mode phrase that alone overflows: only its middle is cut, the tail stays whole
            huge = "Mode: " + "x" * size + " END."
            with self.subTest(size=size), mock.patch("v7_harness.coord.mode.mode_phrase", return_value=huge):
                line = brief_line(self.project, idle, now=NOW)
                self.assertEqual(BRIEF_MAX, len(line))
                self.assertTrue(line.startswith("Mode: "), line)
                self.assertIn("END. " + BRIEF_TAIL, line)
                self._assert_budget(line)
        plain = brief_line(self.project, {"codex": {"state": "ACTIVE"}}, now=NOW)
        self.assertIn("inbox 0 (P1 0, RSI reviews 0); desk codex=ACTIVE. Regime: LOCAL_ONLY. Mode:", plain)
        self._assert_budget(plain)


if __name__ == "__main__":
    unittest.main()
