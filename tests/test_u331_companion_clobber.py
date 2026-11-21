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

    def test_hyphenated_and_non_numeric_companions_stay_isolated(self) -> None:
        from v7_harness.coord.deliver import _is_companion_card

        for comp in ("U331-FF.agy", "U335-DH.agy", "U331-FF.codex", "PCO.codex", "u331-ff.AGY"):
            expected = f"{comp.rsplit('.', 1)[0].upper()}.{comp.rsplit('.', 1)[1].lower()}"
            self.assertEqual(windows.normalize_topic_key(comp), expected)
            self.assertTrue(_is_companion_card(comp), comp)
        for non_comp, expected_topic in (("U331-FF", "U331"), ("U335-DH", "U335"), ("PCO", "PCO"), ("U329-R2", "U329")):
            self.assertEqual(windows.normalize_topic_key(non_comp), expected_topic)
            self.assertFalse(_is_companion_card(non_comp), non_comp)

    def test_real_send_reply_for_hyphenated_companion_leaves_primary_untouched(self) -> None:
        for base, comp, cid in (("U331", "U331-FF.agy", "comp-u331ff-1"), ("U335", "U335-DH.agy", "comp-u335dh-1")):
            windows.record_window(self.p, base, "antigravity", f"primary-{base}-0")
            sent = mock.Mock(reason="", message_id=f"relay_{base}")
            with mock.patch("v7_harness.coord.deliver.deliver", return_value=sent):
                agy_dispatch._send_reply(
                    self.p, now=1.0, message_id=f"relay_in_{base}", actor="codex", envelope={"response": "ok"},
                    runner=None, card=comp, usage={"input_tokens": 5}, conversation_id=cid, reservation=None)
            primary = json.loads((self.p / ".coord" / "windows" / f"{base}.json").read_text(encoding="utf-8"))
            self.assertEqual(primary["tools"]["antigravity"]["id"], f"primary-{base}-0")
            self.assertEqual(windows.window_for(self.p, comp, "antigravity"), cid)
            windows.release_window(self.p, comp, "antigravity", reason="companion_done")
            self.assertIsNone(windows.window_for(self.p, comp, "antigravity"))
            self.assertEqual(windows.window_for(self.p, base, "antigravity"), f"primary-{base}-0")
            card, entry = windows.window_entry_for_topic(self.p, comp, "antigravity")
            self.assertEqual(card, comp)
            self.assertNotEqual(entry.get("id"), f"primary-{base}-0")

    def test_failed_hyphenated_companion_send_does_not_failover_or_clobber(self) -> None:
        from v7_harness.coord import presence
        from v7_harness.coord.deliver import DeliverResult, deliver

        presence.mark(self.p, "codex", "ACTIVE")
        windows.record_window(self.p, "U331", "codex", "primary-u331-codex")
        for base, comp, tid in (("U331-FF", "U331-FF.codex", "thread-u331ff"), ("PCO", "PCO.codex", "thread-pco")):
            windows.record_window(self.p, comp, "codex", tid)
            sent: list[str] = []

            def fail(_envelope, thread, **_kw):
                sent.append(thread)
                return DeliverResult(False, "codex", "DELIVERY_FAILED:rc=1", (), "")

            fake = {"window": tid, "companion": comp}
            with mock.patch("v7_harness.coord.card_nav.ensure_companion_window", return_value=fake), \
                    mock.patch("v7_harness.coord.deliver._verify_thread", return_value="DISPATCH"), \
                    mock.patch("v7_harness.coord.deliver._newest_verified_thread", return_value="thread-other"), \
                    mock.patch("v7_harness.coord.deliver._deliver_to_codex", side_effect=fail):
                deliver(self.p, message="counterexample please", actor="claude", target="codex", card=base)
                deliver(self.p, message="direct companion card", actor="claude", target="codex", card=comp)
            self.assertEqual([tid, tid], sent)
            self.assertEqual(tid, windows.window_for(self.p, comp, "codex"))
        self.assertEqual("primary-u331-codex", windows.window_for(self.p, "U331", "codex"))


if __name__ == "__main__":
    unittest.main()
