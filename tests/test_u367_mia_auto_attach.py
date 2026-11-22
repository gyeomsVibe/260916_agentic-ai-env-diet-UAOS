"""U367: the zero-token MIA tier (mia_triage.classify_mia_tier) rides on every auto-attach card.

Receipt: U354-A shipped the Stage 0-R tier router, but auto_attach cards carried no tier, so a companion window had
to guess its depth. Each test maps one row of the U367 contract section 5 failure-mode table. All fixtures live in a
temporary project; no model, network or subprocess is used.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v7_harness.coord import auto_attach  # noqa: E402

INVARIANTS = ["author!=judge", "fixed_acceptance_exit_0", "backup_before_overwrite", "safety_7_human_only"]


class TestU367MiaAutoAttach(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord").mkdir(parents=True, exist_ok=True)
        self.now = 1_700_000_000.0

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _presence(self, states: dict[str, str]) -> None:
        folder = self.project / ".coord" / "presence"
        folder.mkdir(parents=True, exist_ok=True)
        for tool, state in states.items():
            (folder / f"{tool}.json").write_text(json.dumps({"tool": tool, "state": state}), encoding="utf-8")

    def _card(self, card_id: str) -> dict:
        card = auto_attach.read_card(self.project, card_id)
        self.assertIsNotNone(card)
        return card

    def _queue_item(self, card_id: str) -> dict:
        items = [i for i in auto_attach.read_queue(self.project) if i.get("card_id") == card_id]
        self.assertEqual(len(items), 1)
        return items[0]

    def test_peer_silent_limit_exhausted_regime(self) -> None:
        self._presence({"codex": "LIMITED", "antigravity": "ABSENT", "claude": "ACTIVE"})
        res = auto_attach.hook_on_prompt(self.project, "claude", "Fix pkg/mod.py", session="s1", event_id="e1",
                                         now=self.now)
        self.assertEqual(res["action"], "ENQUEUED")
        self.assertEqual(res["mia_tier"], "MIA-Fast")
        self.assertEqual(res["mia_profile"]["tier"], "MIA-Fast")
        self.assertEqual(res["mia_profile"]["invariants"], INVARIANTS)
        card = self._card(res["card_id"])
        self.assertEqual(card["mia_tier"], "MIA-Fast")
        self.assertEqual(card["mia_profile"], res["mia_profile"])
        self.assertEqual(self._queue_item(res["card_id"])["mia_tier"], "MIA-Fast")
        self.assertEqual(res["peers"], ["codex", "antigravity"])

    def test_message_flood_session_reuse(self) -> None:
        first = auto_attach.enqueue_from_prompt(self.project, "claude", "Fix pkg/mod_0.py", session="flood",
                                                now=self.now)
        self.assertEqual(first["mia_tier"], "MIA-Fast")
        tiers = {}
        for i in range(1, 60):
            res = auto_attach.enqueue_from_prompt(self.project, "claude", f"Fix pkg/mod_{i}.py", session="flood",
                                                  now=self.now + i)
            self.assertEqual(res["action"], "REUSED")
            self.assertEqual(res["card_id"], first["card_id"])
            tiers[i + 1] = res["mia_tier"]
        self.assertEqual(tiers[2], "MIA-Fast")
        self.assertEqual(tiers[3], "MIA-Standard")
        self.assertEqual(tiers[6], "MIA-Full")
        queue = auto_attach.read_queue(self.project)
        self.assertEqual(len(queue), 1)
        card = self._card(first["card_id"])
        self.assertEqual(card["mia_tier"], "MIA-Full")
        self.assertEqual(card["mia_profile"]["file_count"], 60)
        self.assertEqual(queue[0]["mia_tier"], "MIA-Full")

    def test_wait_cycle_deadlock_overlap(self) -> None:
        a = auto_attach.enqueue_from_prompt(self.project, "antigravity", "Fix pkg/shared.py", session="sa",
                                            now=self.now)
        b = auto_attach.enqueue_from_prompt(self.project, "codex", "Fix pkg/shared.py", session="sb",
                                            now=self.now + 1)
        self.assertEqual(b["state"], "WAITING")
        self.assertEqual(b["blocked_by"], a["card_id"])
        self.assertEqual(b["mia_tier"], "MIA-Fast")
        self.assertEqual(self._card(b["card_id"])["mia_profile"]["tier"], "MIA-Fast")
        self.assertEqual(self._queue_item(b["card_id"])["mia_tier"], "MIA-Fast")
        fin = auto_attach.finish_card(self.project, a["card_id"], "antigravity", "merged", now=self.now + 2)
        self.assertIn(b["card_id"], fin["unblocked"])
        self.assertEqual(self._card(b["card_id"])["state"], "PENDING")
        self.assertEqual(self._queue_item(b["card_id"])["mia_tier"], "MIA-Fast")
        self.assertEqual(self._queue_item(a["card_id"])["mia_tier"], "MIA-Fast")

    def test_crash_mid_write_triage_fallback(self) -> None:
        with mock.patch("v7_harness.coord.mia_triage.classify_mia_tier", side_effect=RuntimeError("torn")):
            res = auto_attach.hook_on_prompt(self.project, "claude", "Fix pkg/mod.py", session="s1", now=self.now)
        self.assertTrue(res["ok"])
        self.assertEqual(res["action"], "ENQUEUED")
        self.assertEqual(res["mia_tier"], "MIA-Standard")
        profile = res["mia_profile"]
        self.assertEqual(profile["escalation_reason"], "triage_exception_fallback")
        self.assertEqual(profile["invariants"], INVARIANTS)
        self.assertEqual(profile["file_count"], 1)
        self.assertNotIn("file_count", auto_attach._MIA_FALLBACK)
        self.assertEqual(self._card(res["card_id"])["mia_tier"], "MIA-Standard")

    def test_duplicate_delivery_idempotence(self) -> None:
        one = auto_attach.enqueue_from_prompt(self.project, "claude", "Fix a/x.py b/y.py c/z.py", event_id="e1",
                                              now=self.now)
        self.assertEqual(one["mia_tier"], "MIA-Standard")
        two = auto_attach.enqueue_from_prompt(self.project, "claude", "Fix a/x.py b/y.py c/z.py", event_id="e1",
                                              now=self.now + 1)
        self.assertEqual(two["action"], "DUPLICATE")
        self.assertEqual(two["card_id"], one["card_id"])
        self.assertEqual(two["mia_tier"], one["mia_tier"])
        self.assertEqual(two["mia_profile"], one["mia_profile"])
        self.assertEqual(len(auto_attach.read_queue(self.project)), 1)

    def test_stale_state_fresh_card_generation(self) -> None:
        old = auto_attach.enqueue_from_prompt(self.project, "claude", "Fix pkg/mod.py", session="s1", now=self.now)
        auto_attach.finish_card(self.project, old["card_id"], "claude", "merged", now=self.now + 1)
        later = self.now + 86_400 + 1
        new = auto_attach.enqueue_from_prompt(self.project, "claude", "Fix a/x.py b/y.py c/z.py", session="s1",
                                              now=later)
        self.assertEqual(new["action"], "ENQUEUED")
        self.assertNotEqual(new["card_id"], old["card_id"])
        self.assertEqual(new["mia_tier"], "MIA-Standard")
        self.assertEqual([i["card_id"] for i in auto_attach.read_queue(self.project)],
                         [old["card_id"], new["card_id"]])
        self.assertEqual(self._card(old["card_id"])["mia_tier"], "MIA-Fast")

    def test_conductor_down_peer_assignment(self) -> None:
        self._presence({"codex": "ABSENT", "claude": "ACTIVE", "antigravity": "ACTIVE"})
        res = auto_attach.hook_on_prompt(self.project, "antigravity", "Fix pkg/mod.py", session="s1", now=self.now)
        self.assertEqual(res["action"], "ENQUEUED")
        self.assertNotIn("antigravity", res["peers"])
        self.assertEqual(set(res["peers"]), {"codex", "claude"})
        self.assertIn("author!=judge", res["mia_profile"]["invariants"])
        self.assertEqual(self._card(res["card_id"])["owner"], "antigravity")

    def test_user_absent_high_risk_escalation(self) -> None:
        ko = auto_attach.hook_on_prompt(self.project, "claude", "pkg/db.py 오래된 행 삭제", session="k",
                                        now=self.now)
        self.assertEqual(ko["mia_tier"], "MIA-Full")
        self.assertIn("high_risk_keyword:삭제", ko["mia_profile"]["reasons"])
        self.assertIn("safety_7_human_only", ko["mia_profile"]["invariants"])
        en = auto_attach.hook_on_prompt(self.project, "codex", "Fix the security check in pkg/auth.py",
                                        session="e", now=self.now + 1)
        self.assertEqual(en["mia_tier"], "MIA-Full")
        self.assertIn("high_risk_keyword:security", en["mia_profile"]["reasons"])
        self.assertEqual(self._queue_item(en["card_id"])["mia_tier"], "MIA-Full")


if __name__ == "__main__":
    unittest.main()
