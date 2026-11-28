"""U403-LAND: the commit gate accepts SOLO evidence only with a live regime admission, a different-session reference
judge bound to the staged bytes, and a queued deferred Codex re-review letter. Every missing piece fails closed."""

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from v7_harness import calculator_gate as gate

CARD = "U403"
CODE = {"v7_harness/x.py": b"print('solo')\n"}
ADMITTED = {"ready": True, "route": {"action": "SOLO_EMERGENCY_FINISH", "author": "claude"},
            "admission": {"reason": "EXECUTOR_ADMITTED"}}
MSG = f"feat: solo\n\nCard: {CARD}\nSolo-Evidence: {CARD}\n"


class SoloGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.desk = Path(self._tmp.name)
        self.record = {"card": CARD, "author_tool": "claude", "author_session": "local_author",
                       "judge_tool": "claude", "judge_session": "agent_judge", "verdict": "PASS",
                       "reference_only": True, "deferred_review_id": "evt_defer_1",
                       "files": {p: gate._digest(b) for p, b in CODE.items()}}
        self.letter = {"message_id": "evt_defer_1", "payload": {"actor": "claude", "requested_target": "codex",
                                                                  "card": CARD, "verdict_requested": True}}

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self) -> None:
        (self.desk / gate.SOLO_DIR).mkdir(parents=True, exist_ok=True)
        (self.desk / gate.SOLO_DIR / f"{CARD}.json").write_text(json.dumps(self.record), encoding="utf-8")
        if self.letter is not None:
            box = self.desk / ".coord" / "mailbox" / "inbox"
            box.mkdir(parents=True, exist_ok=True)
            (box / "evt_defer_1.json").write_text(json.dumps(self.letter), encoding="utf-8")

    def _errors(self, admission=ADMITTED, author="claude", message=MSG):
        self._write()
        return gate.solo_errors(message, CODE, self.desk, author, admission=admission)

    def test_complete_solo_evidence_is_accepted(self) -> None:
        self.assertEqual(self._errors(), [])

    def test_no_solo_line_leaves_the_normal_gate(self) -> None:
        self.assertIsNone(gate.solo_errors("feat: x\n", CODE, self.desk, "claude", admission=ADMITTED))

    def test_regime_not_admitting_or_unknown_fails_closed(self) -> None:
        for admission in ({"ready": False, "route": {"action": "SOLO_EMERGENCY_FINISH", "author": "claude"},
                           "admission": {"reason": "AUTHOR_UNKNOWN"}},
                          {"ready": True, "route": {"action": "RUN", "author": "claude"}},  # a peer is alive: not SOLO
                          {"ready": True, "route": {"action": "SOLO_EMERGENCY_FINISH", "author": "codex"}},
                          {}, {"ready": "yes"}):
            errs = self._errors(admission=admission)
            self.assertTrue(any("does not admit" in e for e in errs), (admission, errs))

    def test_sole_active_tool_with_unverified_quota_is_admitted_for_solo_only(self) -> None:
        solo = {"action": "SOLO_EMERGENCY_FINISH", "author": "claude"}
        for reason in ("HALT", "AUTHOR_JUDGE_ONLY"):
            ok = {"ready": False, "route": solo, "admission": {"author_role": "JUDGE_ONLY", "reason": reason}}
            self.assertEqual(self._errors(admission=ok), [], reason)
        for role, reason in (("UNKNOWN", "HALT"), ("OFFLINE", "AUTHOR_OFFLINE"), ("JUDGE_ONLY", "DECISION_EXPIRED"),
                             ("JUDGE_ONLY", "ADMISSION_ERROR:OSError")):
            bad = {"ready": False, "route": solo, "admission": {"author_role": role, "reason": reason}}
            self.assertTrue(any("does not admit" in e for e in self._errors(admission=bad)), (role, reason))
        peer = {"ready": False, "route": {"action": "WAIT_FOR_JUDGE", "author": "claude"},
                "admission": {"author_role": "JUDGE_ONLY", "reason": "HALT"}}
        self.assertTrue(any("does not admit" in e for e in self._errors(admission=peer)))

    def test_live_regime_with_unknown_presence_fails_closed(self) -> None:
        now = time.time()
        desk = {t: {"state": "UNKNOWN", "observed_at": now} for t in ("codex", "claude", "antigravity")}
        self._write()
        with mock.patch("v7_harness.coord.presence.read_all", return_value=desk):
            errs = gate.solo_errors(MSG, CODE, self.desk, "claude", now=now)
        self.assertTrue(any("does not admit" in e for e in errs), errs)

    def test_admission_error_fails_closed(self) -> None:
        self._write()
        with mock.patch("v7_harness.coord.presence.read_all", side_effect=OSError("desk gone")):
            errs = gate.solo_errors(MSG, CODE, self.desk, "claude", now=time.time())
        self.assertTrue(any("does not admit" in e for e in errs), errs)

    def test_author_equal_to_judge_session_is_rejected(self) -> None:
        self.record["judge_session"] = "local_author"
        self.assertTrue(any("self-approval" in e for e in self._errors()))

    def test_empty_sessions_are_rejected(self) -> None:
        self.record["judge_session"] = ""
        self.assertTrue(any("self-approval" in e for e in self._errors()))

    def test_judge_from_other_tool_or_user_is_not_solo_evidence(self) -> None:
        for judge in ("codex", "antigravity", "user"):
            self.record["judge_tool"] = judge
            self.assertTrue(any("judge must be another session" in e for e in self._errors()), judge)

    def test_reference_only_and_pass_are_required(self) -> None:
        self.record["reference_only"] = False
        self.assertTrue(any("reference_only" in e for e in self._errors()))
        self.record.update(reference_only=True, verdict="REVISE")
        self.assertTrue(any("reference_only" in e for e in self._errors()))

    def test_missing_deferred_review_entry_is_rejected(self) -> None:
        self.letter = None
        self.assertTrue(any("deferred re-review" in e for e in self._errors()))

    def test_deferred_letter_must_target_codex_with_verdict_requested_for_this_card(self) -> None:
        for change in ({"requested_target": "antigravity"}, {"verdict_requested": False}, {"card": "U999"}):
            self.letter = {"message_id": "evt_defer_1",
                           "payload": dict({"requested_target": "codex", "card": CARD, "verdict_requested": True},
                                           **change)}
            self.assertTrue(any("deferred re-review" in e for e in self._errors()), change)

    def test_deferred_letter_queued_for_inactive_codex_is_accepted(self) -> None:
        self.letter = None
        queued = self.desk / ".coord" / "mailbox" / "delivery" / "queued" / "codex"
        queued.mkdir(parents=True)
        flat = {"actor": "claude", "card": CARD, "verdict_requested": True, "message_id": "evt_defer_1"}
        (queued / "evt_defer_1.json").write_text(json.dumps(flat), encoding="utf-8")
        self.assertEqual(self._errors(), [])
        flat["card"] = "U999"
        (queued / "evt_defer_1.json").write_text(json.dumps(flat), encoding="utf-8")
        self.assertTrue(any("deferred re-review" in e for e in self._errors()))

    def test_deferred_letter_from_another_sender_is_rejected(self) -> None:
        self.letter["payload"]["actor"] = "antigravity"
        self.assertTrue(any("deferred re-review" in e for e in self._errors()))

    def test_solo_waives_only_peer_review_violations(self) -> None:
        waived = ["v7_harness/x.py: not an APPLIED pilot bundle with an independent PASS review (Ollama author, ...)",
                  "AUDIT_FIRST: add an `Audit: relay_<id>` line naming the answered peer audit reply",
                  "CARD_AUDIT: U403 has no agy evidence; use it"]
        kept = ["CARD_AUDIT: name the card with a `Card: U##` line (or commit on a u<digits> branch)",
                "AUDIT_FIRST: author provenance CONFLICT (branch prefix and commit trailers disagree); no peer letter",
                "SOME_FUTURE_CHECK: blocked"]
        self.assertTrue(all(gate.solo_waivable(v) for v in waived))
        self.assertFalse(any(gate.solo_waivable(v) for v in kept))

    def test_changed_bytes_after_judging_are_rejected(self) -> None:
        self.record["files"] = {"v7_harness/x.py": gate._digest(b"other\n")}
        self.assertTrue(any("differ from what" in e for e in self._errors()))

    def test_missing_record_and_unknown_author_fail_closed(self) -> None:
        self.assertTrue(any("no readable record" in e
                            for e in gate.solo_errors(MSG, CODE, self.desk, "claude", admission=ADMITTED)))
        for author in (None, "CONFLICT"):
            self.assertTrue(gate.solo_errors(MSG, CODE, self.desk, author, admission=ADMITTED))

    def test_record_for_another_author_tool_is_rejected(self) -> None:
        self.record["author_tool"] = "codex"
        self.assertTrue(any("record names card" in e for e in self._errors()))


if __name__ == "__main__":
    unittest.main()
