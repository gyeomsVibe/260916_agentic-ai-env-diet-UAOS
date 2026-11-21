"""U355: an answered request whose answer letter was already acked by its receiver must not wake the requester again.

Receipt (2026-11-22, BLOCKED 20261122T0450-claude-0001): a re-armed `coord watch --target claude --wakes-session`
exited three times in five minutes with REQUEST_ANSWERED for old requests (relay_097f -> relay_afc461ab, relay_0d75
-> relay_360a101d, relay_166f), whose answer letters had already been read and moved to mailbox/ack/. The desk held
135 such unacked request rows, each worth up to WAKE_MAX_GENERATIONS paid wakes.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.test_u277_request_wake import _answer, _project, _register  # noqa: E402


def _answered_by_letter(root: Path, request_id: str, letter_id: str, *, acked: bool) -> None:
    """Answer the request, then point its answer at a mailbox letter (inbox if unread, ack/ if read)."""
    from v7_harness.coord import requests

    _register(root, request_id, session="")
    _answer(root, request_id)
    requests.scan(root, now=None)

    def fn(cur):
        cur["answer_ref"] = letter_id
        return cur

    requests._mutate(root, request_id, fn)
    box = root / ".coord" / "mailbox" / ("ack" if acked else "inbox")
    box.mkdir(parents=True, exist_ok=True)
    (box / f"{letter_id}.json").write_text("{}", encoding="utf-8")


class StaleAnswerReplayTests(unittest.TestCase):
    def test_three_acked_answers_wake_zero_times(self) -> None:
        from v7_harness.coord import requests, watch

        tmp, root = _project()
        with tmp:
            for n in range(3):
                _answered_by_letter(root, f"relay_req{n}", f"relay_ans{n}", acked=True)
            self.assertEqual(len(requests.answered(root)), 3)
            for _ in range(3):  # three re-arms, as in the receipt
                self.assertIsNone(watch._request_wake(root, ("claude",), "", 1.0e12, 1.0e12))
            self.assertTrue(all(row.get("wake_generation") in (None, 0) for row in requests.answered(root)))

    def test_unread_answer_still_wakes_once(self) -> None:
        from v7_harness.coord import watch

        tmp, root = _project()
        with tmp:
            _answered_by_letter(root, "relay_req", "relay_ans", acked=False)
            woken = watch._request_wake(root, ("claude",), "", 1.0e12, 1.0e12)
            self.assertEqual((woken or {}).get("request_id"), "relay_req")

    def test_coord_log_answer_is_never_treated_as_consumed(self) -> None:
        from v7_harness.coord import requests

        tmp, root = _project()
        with tmp:
            for ref in ("20261120T1842-claude-0001", "relay_../x", "", None):
                self.assertFalse(requests.answer_consumed(root, {"answer_ref": ref}))


if __name__ == "__main__":
    unittest.main()
