"""U346-MICRO: Antigravity letter priority and the legacy split-window fallback.

Receipts (U346 delta note, section 2B): a flood of newer passive NOTICE letters pushed an older ACTIONABLE verdict
request out of the five letters `agy_line` shows (AGY_SHOWN), and a card whose window lived only in a legacy per-tool
split record `<card>.<tool>.json` resolved to no window at all. Fixed acceptance: ACTIONABLE > LEGACY > NOTICE, newest
first inside a tier; the split record is a last-resort fallback that never overrides a real (even released) record and
never applies to a U331-FF companion card.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord import windows
from v7_harness.coord.hook_context import AGY_SHOWN, _agy_priority, agy_letters

ACTIONABLE = {"actor": "claude", "requested_target": "antigravity", "wake_class": "ACTIONABLE", "delta": "new bundle",
              "verdict_requested": True}
NOTICE = {"actor": "claude", "requested_target": "antigravity", "wake_class": "NOTICE", "delta": "fyi"}
LEGACY = {"actor": "claude", "to": "antigravity", "message": "old style letter"}


class AgyPriorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        self.inbox = self.project / ".coord" / "mailbox" / "inbox"
        self.inbox.mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _letter(self, name: str, payload: dict, mtime: float) -> None:
        path = self.inbox / f"{name}.json"
        path.write_text(json.dumps({"message_id": name, "payload": payload}), encoding="utf-8")
        os.utime(path, (mtime, mtime))

    def test_priority_values(self) -> None:
        self.assertEqual(_agy_priority(ACTIONABLE), 2)
        self.assertEqual(_agy_priority({**ACTIONABLE, "wake_class": None, "verdict_requested": None}), 0)
        self.assertEqual(_agy_priority({"actor": "claude", "requested_target": "antigravity", "verdict": "PASS",
                                        "delta": "verdict"}), 2)
        self.assertEqual(_agy_priority(LEGACY), 1)
        self.assertEqual(_agy_priority(NOTICE), 0)

    def test_notice_flood_does_not_starve_actionable(self) -> None:
        self._letter("relay_old_actionable", ACTIONABLE, 1_000.0)
        for index in range(AGY_SHOWN + 3):
            self._letter(f"relay_notice_{index:02d}", NOTICE, 2_000.0 + index)
        letters = agy_letters(self.project)
        self.assertEqual(letters[0], "relay_old_actionable")
        self.assertIn("relay_old_actionable", letters[:AGY_SHOWN])
        self.assertEqual(len(letters), AGY_SHOWN + 4)

    def test_legacy_ranks_between_actionable_and_notice(self) -> None:
        self._letter("relay_notice_new", NOTICE, 3_000.0)
        self._letter("relay_legacy_mid", LEGACY, 2_000.0)
        self._letter("relay_actionable_old", ACTIONABLE, 1_000.0)
        self.assertEqual(agy_letters(self.project),
                         ["relay_actionable_old", "relay_legacy_mid", "relay_notice_new"])

    def test_newest_first_within_a_tier_and_stem_breaks_ties(self) -> None:
        self._letter("relay_a", NOTICE, 1_000.0)
        self._letter("relay_b", NOTICE, 2_000.0)
        self._letter("relay_c", NOTICE, 2_000.0)
        self.assertEqual(agy_letters(self.project), ["relay_c", "relay_b", "relay_a"])

    def test_letters_to_other_tools_and_evt_files_stay_out(self) -> None:
        self._letter("relay_codex", {**ACTIONABLE, "requested_target": "codex"}, 5_000.0)
        self._letter("evt_0001", ACTIONABLE, 6_000.0)
        self._letter("relay_agy", NOTICE, 1_000.0)
        self.assertEqual(agy_letters(self.project), ["relay_agy"])


class SplitWindowFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.p = Path(self._tmp.name) / "proj"
        (self.p / ".coord" / "windows").mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _split(self, base: str, tool: str, entry: dict) -> None:
        card = f"{base}.{tool}"
        (self.p / ".coord" / "windows" / f"{card}.json").write_text(
            json.dumps({"card": card, "title": f"[{card}]", "tools": {tool: entry}}), encoding="utf-8")

    def _both(self, card: str, tool: str) -> tuple:
        return windows.window_for(self.p, card, tool), windows.window_for_topic(self.p, card, tool)

    def test_split_record_resolves_when_card_has_no_record(self) -> None:
        self._split("U346", "claude", {"id": "split-claude-1"})
        self.assertEqual(self._both("U346", "claude"), ("split-claude-1", "split-claude-1"))
        self.assertEqual(self._both("U346", "codex"), (None, None))

    def test_sub_card_reaches_topic_split_record(self) -> None:
        self._split("U346", "codex", {"id": "split-codex-1"})
        self.assertEqual(self._both("U346-R2-L1", "codex"), ("split-codex-1", "split-codex-1"))

    def test_real_record_wins_over_split(self) -> None:
        windows.record_window(self.p, "U346", "claude", "primary-claude-0")
        self._split("U346", "claude", {"id": "split-claude-1"})
        self.assertEqual(self._both("U346", "claude"), ("primary-claude-0", "primary-claude-0"))

    def test_released_real_record_does_not_fall_back_to_split(self) -> None:
        windows.record_window(self.p, "U346", "claude", "primary-claude-0")
        windows.release_window(self.p, "U346", "claude", reason="done")
        self._split("U346", "claude", {"id": "split-claude-1"})
        self.assertEqual(self._both("U346", "claude"), (None, None))

    def test_inactive_split_record_is_ignored(self) -> None:
        self._split("U346", "claude", {"id": "split-claude-1", "released_at": "2026-11-22T00:00:00Z"})
        self.assertEqual(self._both("U346", "claude"), (None, None))
        self._split("U346", "codex", {"id": "split-codex-1", "state": "RESERVING"})
        self.assertEqual(self._both("U346", "codex"), (None, None))

    def test_unknown_tool_has_no_split(self) -> None:
        self._split("U346", "ollama", {"id": "split-ollama"})
        self.assertEqual(windows._split_window_entry(self.p, "U346", "ollama"), {})


class CompanionNonRegressionTests(unittest.TestCase):
    """U331-FF: a companion card `<ID>.<tool>` keeps its own window; no split lookup runs for it or onto it."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.p = Path(self._tmp.name) / "proj"
        (self.p / ".coord" / "windows").mkdir(parents=True)
        windows.record_window(self.p, "U329", "codex", "primary-codex-0")
        windows.record_window(self.p, "U329.codex", "codex", "companion-codex-0")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_companion_and_primary_stay_distinct(self) -> None:
        self.assertEqual(windows.normalize_topic_key("U329.codex"), "U329.codex")
        self.assertEqual(windows.window_for(self.p, "U329.codex", "codex"), "companion-codex-0")
        self.assertEqual(windows.window_for_topic(self.p, "U329.codex", "codex"), "companion-codex-0")
        self.assertEqual(windows.window_for(self.p, "U329", "codex"), "primary-codex-0")

    def test_companion_card_never_uses_a_split_name(self) -> None:
        self.assertEqual(windows._split_window_entry(self.p, "U329.codex", "codex"), {})
        (self.p / ".coord" / "windows" / "U329.agy.antigravity.json").write_text(
            json.dumps({"tools": {"antigravity": {"id": "nested-split"}}}), encoding="utf-8")
        self.assertIsNone(windows.window_for(self.p, "U329.agy", "antigravity"))
        self.assertIsNone(windows.window_for_topic(self.p, "U329.agy", "antigravity"))

    def test_released_companion_does_not_fall_back(self) -> None:
        windows.release_window(self.p, "U329.codex", "codex", reason="companion_done")
        self.assertIsNone(windows.window_for(self.p, "U329.codex", "codex"))
        self.assertIsNone(windows.window_for_topic(self.p, "U329.codex", "codex"))
        self.assertEqual(windows.window_for(self.p, "U329", "codex"), "primary-codex-0")


if __name__ == "__main__":
    unittest.main()
