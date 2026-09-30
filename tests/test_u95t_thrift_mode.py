"""U95-T: token-thrift is the runtime's default mode; a card over its share keeps the next card closed."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from v7_harness.coord import card_cost
from v7_harness.coord.hook_context import agy_line, brief_line
from v7_harness.coord.mode import MODE_FILE, NORMAL, SHARE_LIMIT, THRIFT, current_mode, mode_phrase

DESK = {"codex": {"state": "ABSENT"}, "claude": {"state": "ACTIVE"}, "antigravity": {"state": "ACTIVE"}}


def _row(work_id: str, inp: int, out: int) -> dict:
    return {"work_id": work_id, "kind": "session", "input_tokens": inp, "output_tokens": out}


class ThriftModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "260916_agentic-ai-env-diet"
        (self.root / ".coord" / "usage").mkdir(parents=True)
        (self.root / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _mode(self, data) -> None:
        text = data if isinstance(data, str) else json.dumps(data)
        (self.root / MODE_FILE).write_text(text, encoding="utf-8")

    def test_default_and_every_invalid_file_is_token_thrift(self) -> None:
        self.assertEqual({"mode": THRIFT, "source": "default"}, current_mode(self.root))
        for data in ("{bad", [1], {"mode": NORMAL}, {"mode": NORMAL, "set_by": "claude", "reason": "x"},
                     {"mode": NORMAL, "set_by": "user", "reason": "  "}, {"mode": "fast", "set_by": "user"}):
            self._mode(data)
            self.assertEqual(THRIFT, current_mode(self.root)["mode"], data)

    def test_only_an_explicit_user_switch_is_normal(self) -> None:
        self._mode({"mode": NORMAL, "set_by": "user", "reason": "one-off deep audit"})
        self.assertEqual({"mode": NORMAL, "source": ".coord/mode.json", "reason": "one-off deep audit"},
                         current_mode(self.root))
        self.assertIn("normal, set by 윤겸스 (one-off deep audit)", mode_phrase(self.root))

    def test_share_is_one_average_card_and_the_3x_rule_stays(self) -> None:
        self.assertEqual(1.0, SHARE_LIMIT)
        self.assertEqual(3.0, card_cost.RATIO_LIMIT)

    def _ledger(self, rows) -> None:
        path = self.root / ".coord" / "usage" / "runs.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    def test_a_card_over_its_share_is_split_in_thrift_mode_only(self) -> None:
        self._ledger([_row("B", 1000, 100), _row("C", 2000, 200), _row("D", 900, 90)])
        (self.root / ".coord" / "card_baseline.json").write_text(
            json.dumps({"baseline": "B", "baseline_cards": 1}), encoding="utf-8")
        over = card_cost.report(self.root, card="C", baseline="B", baseline_cards=1)
        self.assertEqual(("PASS", THRIFT, False), (over["status"], over["mode"], over["next_card_allowed"]))
        self.assertEqual(["total_tokens", "output_tokens"], over["over_share"])
        self.assertIn("split the card", over["reason"])
        within = card_cost.report(self.root, card="D", baseline="B", baseline_cards=1)
        self.assertEqual(([], True), (within["over_share"], within["next_card_allowed"]))
        with patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(1, card_cost.main(["--project", str(self.root), "--card", "C"]))
            self.assertEqual(0, card_cost.main(["--project", str(self.root), "--card", "D"]))
            self._mode({"mode": NORMAL, "set_by": "user", "reason": "measured A/B"})
            self.assertEqual(0, card_cost.main(["--project", str(self.root), "--card", "C"]))
        normal = card_cost.report(self.root, card="C", baseline="B", baseline_cards=1)
        self.assertEqual((NORMAL, [], True), (normal["mode"], normal["over_share"], normal["next_card_allowed"]))

    def test_the_session_briefing_names_the_mode_without_losing_its_tail(self) -> None:
        line = brief_line(self.root, DESK)
        self.assertIn("Mode: token-thrift (default)", line)
        self.assertTrue(line.endswith("never via the user."), line)
        self._mode({"mode": NORMAL, "set_by": "user", "reason": "measured A/B"})
        self.assertIn("Mode: normal", brief_line(self.root, DESK))

    def test_antigravity_briefing_names_the_mode_and_repeats_when_it_changes(self) -> None:
        event = json.dumps({"invocationNum": 0, "conversationId": "c1"})
        self.assertIn("Mode: token-thrift (default)", agy_line(self.root, DESK, event))
        self.assertEqual("", agy_line(self.root, DESK, event))  # unchanged desk: silent
        self._mode({"mode": NORMAL, "set_by": "user", "reason": "measured A/B"})
        self.assertIn("Mode: normal", agy_line(self.root, DESK, event))


if __name__ == "__main__":
    unittest.main()
