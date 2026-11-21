"""U331-FF: a companion card `<ID>.<tool>` must never overwrite or fall back onto the primary card `<ID>` window.

Reproduces Antigravity's exact-head finding on PR #297 (6ee29c10) with the real, unmocked `agy_dispatch._send_reply`.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import agy_dispatch, windows


class CompanionNeverClobbersPrimary(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.p = Path(self._tmp.name) / "proj"
        (self.p / ".coord" / "mailbox").mkdir(parents=True)
        windows.record_window(self.p, "U329", "antigravity", "primary-conv-0")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _primary(self) -> dict:
        return json.loads((self.p / ".coord" / "windows" / "U329.json").read_text(encoding="utf-8"))

    def test_topic_key_keeps_companion_distinct(self) -> None:
        for tool in ("agy", "codex", "claude", "antigravity"):
            self.assertEqual(windows.normalize_topic_key(f"U329.{tool}"), f"U329.{tool}")
        self.assertEqual(windows.normalize_topic_key("U329-R2"), "U329")

    def test_real_send_reply_for_companion_leaves_primary_window_untouched(self) -> None:
        sent = mock.Mock(reason="", message_id="relay_x")
        with mock.patch("v7_harness.coord.deliver.deliver", return_value=sent):
            agy_dispatch._send_reply(
                self.p, now=1.0, message_id="relay_in", actor="codex", envelope={"response": "ok"}, runner=None,
                card="U329.agy", usage={"input_tokens": 5}, conversation_id="comp-conv-1", reservation=None)
        self.assertEqual(self._primary()["tools"]["antigravity"]["id"], "primary-conv-0")
        self.assertEqual(windows.window_for(self.p, "U329.agy", "antigravity"), "comp-conv-1")

    def test_released_companion_does_not_fall_back_to_primary(self) -> None:
        windows.record_window(self.p, "U329.agy", "antigravity", "comp-conv-1")
        windows.release_window(self.p, "U329.agy", "antigravity", reason="companion_done")
        self.assertIsNone(windows.window_for(self.p, "U329.agy", "antigravity"))
        self.assertEqual(windows.window_for(self.p, "U329", "antigravity"), "primary-conv-0")
        card, entry = windows.window_entry_for_topic(self.p, "U329.agy", "antigravity")
        self.assertEqual(card, "U329.agy")
        self.assertNotEqual(entry.get("id"), "primary-conv-0")

    def test_codex_companion_turn_leases_the_companion_window_not_the_primary(self) -> None:
        from v7_harness.coord import presence
        from v7_harness.coord.deliver import deliver
        presence.mark(self.p, "codex", "ACTIVE")
        seen: list[str] = []

        def spy(_project, card, _tool):
            seen.append(card)
            raise TimeoutError("stop here: only the lease target matters")

        fake = {"window": "thread-9", "companion": "U329.codex"}
        with mock.patch("v7_harness.coord.card_nav.ensure_companion_window", return_value=fake),                 mock.patch("v7_harness.coord.windows.acquire_window_lease", side_effect=spy):
            deliver(self.p, message="counterexample please", actor="claude", target="codex", card="U329",
                    runner=lambda *a, **k: mock.Mock(returncode=0, stdout="", stderr=""))
        self.assertEqual(["U329.codex"], seen)

    def test_failed_companion_send_is_not_redelivered_to_another_cards_window(self) -> None:
        from v7_harness.coord import presence
        from v7_harness.coord.deliver import DeliverResult, deliver
        presence.mark(self.p, "codex", "ACTIVE")
        windows.record_window(self.p, "U329.codex", "codex", "thread-329")
        sent: list[str] = []

        def fail(_envelope, thread, **_kw):
            sent.append(thread)
            return DeliverResult(False, "codex", "DELIVERY_FAILED:rc=1", (), "")

        fake = {"window": "thread-329", "companion": "U329.codex"}
        with mock.patch("v7_harness.coord.card_nav.ensure_companion_window", return_value=fake),                 mock.patch("v7_harness.coord.deliver._verify_thread", return_value="DISPATCH"),                 mock.patch("v7_harness.coord.deliver._newest_verified_thread", return_value="thread-330"),                 mock.patch("v7_harness.coord.deliver._deliver_to_codex", side_effect=fail):
            deliver(self.p, message="counterexample please", actor="claude", target="codex", card="U329")
        self.assertEqual(["thread-329"], sent)
        self.assertEqual("thread-329", windows.window_for(self.p, "U329.codex", "codex"))


if __name__ == "__main__":
    unittest.main()
