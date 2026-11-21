"""U333 RC2-R2-R1 pinned acceptance suite (Codex relay_8b5a9e3d ruling).

Pins all 5 required behaviors on clean 5fd1739 vs post-GO target:
1. Actionable non-terminal audit blocker (no verdict/outcome) via agy_dispatch(audit=True):
   wakes requester once, correlates via in_reply_to, and preserves request OPEN.
2. Direct actionable non-terminal blocker letter (no verdict/outcome, in_reply_to=req_id):
   wakes requester once and preserves request OPEN.
3. Informational status NOTICE with open request:
   remains legal across claude/codex/antigravity, never wakes, and preserves request OPEN.
4. Actual terminal verdict (VERDICT: PASS):
   wakes requester once and transitions OPEN -> ANSWER_OBSERVED (outcome="PASS").
5. Legacy controls: audit=False non-verdict stays NOTICE; U188 explicit NOTICE stays ("NOTICE", "").
"""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from v7_harness.coord import agy_dispatch, presence, requests
from v7_harness.coord import watch as W
from v7_harness.coord.deliver import deliver

HEAD_SHA = "5fd17396455a939d7a4568635ec948911c4318d3"


class TestU333RC2R2Rev1OpenBlockerPinned(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord" / "presence").mkdir(parents=True, exist_ok=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")

    def _enable_live_claude_watcher(self) -> None:
        beat = W.watch_file(self.project, "claude")
        beat.parent.mkdir(parents=True, exist_ok=True)
        beat.write_text(
            json.dumps(
                {"tool": "claude", "token": "t", "pid": 1, "expires_at": time.time() + 300, "wakes_session": True}
            ),
            encoding="utf-8",
        )
        presence.mark(self.project, "claude", "ACTIVE", ttl_s=3600)

    def _register_open_request(self, req_id: str, *, now: float) -> None:
        requests.register(
            self.project,
            request_id=req_id,
            requester="claude",
            target="antigravity",
            card="U333",
            subject="U333 verdict request",
            head=HEAD_SHA,
            requester_session="s-claude",
            now=now - 10,
        )
        requests.mark_delivered(self.project, req_id, "DISPATCHED")

    def _watch_once(self, target: str) -> dict | None:
        return W.watch(
            self.project,
            (target,),
            timeout_s=0.05,
            interval_s=0.01,
            policy="structured",
            wakes_session=True,
        )

    def test_rc2_actionable_non_terminal_blocker_from_audit_wakes_once_and_preserves_open(self) -> None:
        self._enable_live_claude_watcher()
        req_id = "relay_00001111222233334444555566667777"
        now = time.time()
        self._register_open_request(req_id, now=now)

        def runner(_argv, **_kwargs):
            env = {
                "status": "SUCCESS",
                "conversation_id": "conv-audit-blocker",
                "response": "Blocked: missing exact commit hash in review packet.",
                "usage": {"input_tokens": 12, "output_tokens": 9},
            }
            return SimpleNamespace(returncode=0, stdout=json.dumps(env).encode("utf-8"), stderr=b"")

        with mock.patch("v7_harness.coord.deliver.shutil.which", side_effect=lambda name: name):
            row = agy_dispatch.dispatch(
                self.project,
                message_id=req_id,
                actor="claude",
                message="Please review U333",
                runner=runner,
                audit=True,
                now=now,
            )

        self.assertEqual(row["state"], "ANSWERED")
        payload = json.loads(
            (self.project / ".coord" / "mailbox" / "inbox" / f"{row['reply_id']}.json").read_text(encoding="utf-8")
        )["payload"]
        self.assertEqual(payload.get("wake_class"), "ACTIONABLE")
        self.assertIsNone(payload.get("verdict"))
        self.assertEqual(payload.get("in_reply_to"), req_id)

        woken1 = self._watch_once("claude")
        self.assertEqual(woken1 and woken1.get("id"), row["reply_id"])
        self.assertIsNone(self._watch_once("claude"))

        self.assertEqual(requests.scan(self.project, now=now + 1), [])
        req_row = requests.get(self.project, req_id)
        self.assertEqual(req_row["state"], requests.OPEN)
        self.assertEqual(req_row["answer_ref"], "")

    def test_rc2_direct_actionable_non_terminal_blocker_letter_preserves_open(self) -> None:
        self._enable_live_claude_watcher()
        req_id = "relay_11112222333344445555666677778888"
        now = time.time()
        self._register_open_request(req_id, now=now)

        with mock.patch("v7_harness.coord.deliver.shutil.which", side_effect=lambda name: name):
            res = deliver(
                self.project,
                actor="antigravity",
                target="claude",
                message="Blocked: missing review artifact; please supply packet.",
                wake_class="ACTIONABLE",
                delta="audit blocker needs packet",
                in_reply_to=req_id,
            )

        self.assertEqual(res.reason, "QUEUED_INTERACTIVE")
        woken1 = self._watch_once("claude")
        self.assertEqual(woken1 and woken1.get("id"), res.message_id)
        self.assertIsNone(self._watch_once("claude"))

        self.assertEqual(requests.scan(self.project, now=now + 1), [])
        req_row = requests.get(self.project, req_id)
        self.assertEqual(req_row["state"], requests.OPEN)
        self.assertEqual(req_row["answer_ref"], "")

    def test_rc2_informational_status_notice_with_open_request_is_legal_no_wake_and_preserves_open(self) -> None:
        self._enable_live_claude_watcher()
        presence.mark(self.project, "codex", "ACTIVE", ttl_s=3600)
        req_id = "relay_aaaa1111222233334444555566667777"
        now = time.time()
        self._register_open_request(req_id, now=now)

        with mock.patch("v7_harness.coord.deliver.shutil.which", side_effect=lambda name: name):
            res_claude = deliver(
                self.project,
                actor="antigravity",
                target="claude",
                message="Status update: running baseline tests now.",
                wake_class="NOTICE",
                in_reply_to=req_id,
            )
            res_codex = deliver(
                self.project,
                actor="antigravity",
                target="codex",
                message="Status update: preparing packet.",
                wake_class="NOTICE",
                in_reply_to=req_id,
            )
            res_agy = deliver(
                self.project,
                actor="codex",
                target="antigravity",
                message="Status update: queue acknowledged.",
                wake_class="NOTICE",
                in_reply_to=req_id,
            )

        self.assertEqual(res_claude.reason, "QUEUED_INTERACTIVE")
        self.assertEqual(res_codex.reason, "QUEUED_NOTICE")
        self.assertEqual(res_agy.reason, "PUBLISHED")
        for mid in (res_claude.message_id, res_codex.message_id, res_agy.message_id):
            payload = json.loads(
                (self.project / ".coord" / "mailbox" / "inbox" / f"{mid}.json").read_text(encoding="utf-8")
            )["payload"]
            self.assertEqual(payload.get("wake_class"), "NOTICE")
            self.assertEqual(payload.get("in_reply_to"), req_id)

        for target_tool in ("claude", "codex", "antigravity"):
            self.assertIsNone(self._watch_once(target_tool))

        self.assertEqual(requests.scan(self.project, now=now + 1), [])
        row = requests.get(self.project, req_id)
        self.assertEqual(row["state"], requests.OPEN)
        self.assertEqual(row["answer_ref"], "")

    def test_rc2_actual_terminal_verdict_wakes_once_and_observes_pass(self) -> None:
        self._enable_live_claude_watcher()
        req_id = "relay_bbbb1111222233334444555566667777"
        now = time.time()
        self._register_open_request(req_id, now=now)

        def runner(_argv, **_kwargs):
            env = {
                "status": "SUCCESS",
                "conversation_id": "conv-audit-verdict",
                "response": f"VERDICT: PASS on head {HEAD_SHA}",
                "usage": {"input_tokens": 12, "output_tokens": 9},
            }
            return SimpleNamespace(returncode=0, stdout=json.dumps(env).encode("utf-8"), stderr=b"")

        with mock.patch("v7_harness.coord.deliver.shutil.which", side_effect=lambda name: name):
            row = agy_dispatch.dispatch(
                self.project,
                message_id=req_id,
                actor="claude",
                message="Please review U333",
                runner=runner,
                audit=True,
                now=now,
            )

        self.assertEqual(row["state"], "ANSWERED")
        payload = json.loads(
            (self.project / ".coord" / "mailbox" / "inbox" / f"{row['reply_id']}.json").read_text(encoding="utf-8")
        )["payload"]
        self.assertEqual(payload.get("wake_class"), "ACTIONABLE")
        self.assertEqual(payload.get("verdict"), "PASS")

        woken1 = self._watch_once("claude")
        self.assertEqual(woken1 and woken1.get("id"), row["reply_id"])
        self.assertIsNone(self._watch_once("claude"))

        requests.scan(self.project, now=now + 1)
        req_row = requests.get(self.project, req_id)
        self.assertEqual(req_row["state"], requests.ANSWER_OBSERVED)
        self.assertEqual(req_row["outcome"], "PASS")
        self.assertEqual(req_row["answer_ref"], row["reply_id"])

    def test_rc2_legacy_non_audit_notice_and_u188_explicit_notice_preserved(self) -> None:
        self._enable_live_claude_watcher()
        req_id = "relay_cccc1111222233334444555566667777"

        def runner(_argv, **_kwargs):
            env = {
                "status": "SUCCESS",
                "conversation_id": "conv-non-audit",
                "response": "Noted, nothing to judge.",
                "usage": {"input_tokens": 8, "output_tokens": 6},
            }
            return SimpleNamespace(returncode=0, stdout=json.dumps(env).encode("utf-8"), stderr=b"")

        with mock.patch("v7_harness.coord.deliver.shutil.which", side_effect=lambda name: name):
            row = agy_dispatch.dispatch(
                self.project,
                message_id=req_id,
                actor="claude",
                message="FYI status note",
                runner=runner,
                audit=False,
            )
        self.assertEqual(row["state"], "ANSWERED")
        payload_non_audit = json.loads(
            (self.project / ".coord" / "mailbox" / "inbox" / f"{row['reply_id']}.json").read_text(encoding="utf-8")
        )["payload"]
        self.assertEqual(payload_non_audit.get("wake_class"), "NOTICE")
        self.assertIsNone(self._watch_once("claude"))

        res_u188 = deliver(
            self.project,
            actor="codex",
            target="antigravity",
            message="U188 bundle 1: PASS",
            wake_class="NOTICE",
        )
        self.assertEqual(res_u188.reason, "PUBLISHED")
        payload_u188 = json.loads(
            (self.project / ".coord" / "mailbox" / "inbox" / f"{res_u188.message_id}.json").read_text(encoding="utf-8")
        )["payload"]
        self.assertEqual(("NOTICE", ""), W.classify(payload_u188))


if __name__ == "__main__":
    unittest.main()
