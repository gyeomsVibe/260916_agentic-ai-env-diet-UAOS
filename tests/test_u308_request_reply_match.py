"""U308 regression tests: verdict letter matching without in_reply_to & stop_gate _request_hold release."""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from v7_harness.coord import requests, stop_gate

PR = "https://github.com/gyeomsVibe/260916_agentic-ai-env-diet-UAOS/pull/282"
SHA = "671669c33057a4e38ca2f0652ae7b5b8a384a54c"


def _project() -> tuple[tempfile.TemporaryDirectory[str], Path]:
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    (root / ".coord").mkdir()
    return tmp, root


def _write_letter(root: Path, folder: str, letter_id: str, payload: dict) -> Path:
    box = root / ".coord" / "mailbox" / folder
    box.mkdir(parents=True, exist_ok=True)
    path = box / f"{letter_id}.json"
    path.write_text(json.dumps({"id": letter_id, "payload": payload}), encoding="utf-8")
    return path


class U308RequestReplyMatchTests(unittest.TestCase):
    def test_verdict_letter_matches_by_head_card_or_reply_to_without_in_reply_to(self) -> None:
        tmp, root = _project()
        with tmp:
            now = time.time()
            r1 = requests.register(
                root,
                request_id="relay_c161162e4e2bb975d621afb73689e76a",
                requester="antigravity",
                target="claude",
                card="U307",
                subject=PR,
                head=SHA,
                requester_session="sA",
                now=now - 10,
            )
            requests.mark_delivered(root, r1["request_id"], "DISPATCHED")
            _write_letter(
                root,
                "ack",
                "relay_ce0f6c327cd9213b6b0aeb906308a2b1",
                {
                    "actor": "claude",
                    "target": "antigravity",
                    "card": "U307",
                    "verdict": "PASS",
                    "message": f"U307 PR #282 (head {SHA}) independent review PASS.",
                },
            )
            transitions = requests.scan(root, now=now)
            self.assertEqual(len(transitions), 1)
            row = requests.get(root, r1["request_id"])
            self.assertEqual(row["state"], requests.ANSWER_OBSERVED)
            self.assertEqual(row["outcome"], "PASS")
            self.assertEqual(row["answer_ref"], "relay_ce0f6c327cd9213b6b0aeb906308a2b1")

    def test_unrelated_verdict_letter_mentioning_relay_prefix_or_pr_never_closes_request(self) -> None:
        """Claude P1 counterexample (relay_3d06e22e258c81ed27178e1408d78b3b): a verdict letter for U304-D / PR #281
        that mentions 'Answering your relay_28443f39 question' in prose must NEVER close request relay_28443f39ffffffff
        belonging to card U999."""
        tmp, root = _project()
        with tmp:
            now = time.time()
            r1 = requests.register(
                root,
                request_id="relay_28443f39ffffffff",
                requester="claude",
                target="antigravity",
                card="U999",
                subject="U999 unrelated",
                head="0000000",
                requester_session="sA",
                now=now - 20,
            )
            requests.mark_delivered(root, r1["request_id"], "QUEUED")
            _write_letter(
                root,
                "inbox",
                "relay_07582b8a3a031691508b8589cb6d8ae3",
                {
                    "actor": "antigravity",
                    "target": "claude",
                    "card": "U304-D",
                    "verdict": "PASS",
                    "message": (
                        "[U304-D follow-up PR #281 PASS] head=cfc64dac4595b85854b15ff89883feefa4db5876 "
                        "Answering your relay_28443f39 question: I ran install_uaos_everywhere.py --apply."
                    ),
                },
            )
            transitions = requests.scan(root, now=now)
            self.assertEqual(transitions, [])
            self.assertEqual(requests.get(root, r1["request_id"])["state"], requests.OPEN)

    def test_non_verdict_or_wrong_actor_letter_without_in_reply_to_does_not_close_request(self) -> None:
        tmp, root = _project()
        with tmp:
            now = time.time()
            r1 = requests.register(
                root,
                request_id="relay_aaaa1111222233334444555566667777",
                requester="claude",
                target="antigravity",
                card="U308",
                subject=PR,
                head=SHA,
                requester_session="sA",
                now=now - 10,
            )
            requests.mark_delivered(root, r1["request_id"], "DISPATCHED")
            _write_letter(
                root,
                "inbox",
                "relay_wrong_actor",
                {
                    "actor": "codex",
                    "target": "claude",
                    "card": "U308",
                    "verdict": "PASS",
                    "message": "PR #282 PASS",
                },
            )
            _write_letter(
                root,
                "inbox",
                "relay_no_verdict",
                {
                    "actor": "antigravity",
                    "target": "claude",
                    "card": "U308",
                    "verdict": "NONE",
                    "message": "Looking at PR #282 now",
                },
            )
            requests.scan(root, now=now)
            self.assertEqual(requests.get(root, r1["request_id"])["state"], requests.OPEN)

    def test_request_hold_scans_and_releases_once_verdict_letter_arrives(self) -> None:
        tmp, root = _project()
        with tmp:
            now = time.time()
            sha281 = "200c887ef59c0000000000000000000000000000"
            r1 = requests.register(
                root,
                request_id="relay_65911cbe32cc716208bb01cf5b47702c",
                requester="claude",
                target="antigravity",
                card="U304-D",
                subject="https://github.com/gyeomsVibe/260916_agentic-ai-env-diet-UAOS/pull/281",
                head=sha281,
                requester_session="sA",
                now=now - 20,
            )
            requests.mark_delivered(root, r1["request_id"], "QUEUED")
            _write_letter(
                root,
                "inbox",
                "relay_1360280f1de30c7b4de0b9ff67128588",
                {
                    "actor": "antigravity",
                    "target": "claude",
                    "card": "U304-D2",
                    "verdict": "PASS",
                    "message": f"PR #281 (head {sha281}) independent review PASS",
                },
            )
            hold = stop_gate._request_hold(root, "claude", "sA", now=now)
            self.assertIsNone(hold)
            self.assertEqual(requests.get(root, r1["request_id"])["state"], requests.ANSWER_OBSERVED)


if __name__ == "__main__":
    unittest.main()
