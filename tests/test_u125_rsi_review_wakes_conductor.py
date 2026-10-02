"""U125: an RSI review letter wakes the acting conductor and names the runs that carry each cause.

Receipts (2026-10-02):
- The sentinel published 15 `rsi_review_*` letters (e.g. "pass 0.2" for ollama) with no `requested_target`, so
  `coord watch --target claude --wakes-session` never woke for them (`watch._addressed`) and none was ever handled.
- `rsi propose` gave every cause of a worker the same evidence, the worker's last five work_ids: the ollama
  UNREQUESTED_DELETION proposal listed U124-L2, a PASS run.
Fixed acceptance written by the judge (claude) before the run.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness import rsi
from v7_harness.coord import presence
from v7_harness.coord.mailbox import Mailbox
from v7_harness.coord.sentinel import run_sentinel_cycle
from v7_harness.coord.watch import _addressed


def _row(work_id: str, outcome: str, error_class: str | None = None, ts: float = 0.0) -> dict:
    return {"schema": "uaos-usage-v2", "kind": "pilot", "work_id": work_id, "worker": "ollama", "outcome": outcome,
            "ts": ts, "input_tokens": 1000, "error_class": error_class}


# Ten runs: SYNTAX_ERROR twice (recurring), CODE once, seven PASS.
ROWS = [_row("A", "REWORK", "SYNTAX_ERROR", 1), _row("B", "PASS", ts=2), _row("C", "REWORK", "SYNTAX_ERROR", 3),
        _row("D", "REWORK", "CODE", 4)] + [_row(f"P{i}", "PASS", ts=10 + i) for i in range(6)]


def _ledger(root: Path, rows: list[dict]) -> None:
    path = root / ".coord" / "usage" / "runs.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


class EvidencePerCauseTest(unittest.TestCase):
    def test_each_proposal_names_only_the_runs_with_its_cause(self) -> None:
        proposals = {p["cause"]: p for p in rsi.propose(rsi.analyze(ROWS))}
        self.assertEqual(["A", "C"], proposals["SYNTAX_ERROR"]["cause_evidence"])
        self.assertEqual(["D"], proposals["CODE"]["cause_evidence"])

    def test_gate_baseline_stays_the_whole_window(self) -> None:
        # Dissent from relay_a51f9ad6 (agy PASS on D1): candidate_template copies `evidence` into the gate's
        # before_work_ids, so a failures-only list would make every candidate look better. It must not change.
        proposal = next(p for p in rsi.propose(rsi.analyze(ROWS)) if p["cause"] == "SYNTAX_ERROR")
        self.assertEqual(["P1", "P2", "P3", "P4", "P5"], proposal["evidence"])
        self.assertEqual(proposal["evidence"], rsi.candidate_template(proposal, "claude")["before_work_ids"])


class ReviewLetterTest(unittest.TestCase):
    def test_letter_for_a_target_carries_it_and_the_recurring_proposals(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            [(message_id, payload)] = rsi.rsi_review_messages(Path(d), rsi.analyze(ROWS), target="claude")
        self.assertEqual("rsi_review_ollama_10x1", message_id)
        self.assertEqual("claude", payload["requested_target"])
        self.assertTrue(_addressed(payload, ("claude",)))
        [proposal] = payload["proposals"]  # only the recurring cause; CODE happened once
        self.assertEqual("SYNTAX_ERROR", proposal["cause"])
        self.assertEqual(["A", "C"], proposal["evidence"])
        self.assertTrue(proposal["id"].startswith("rsi_"))
        self.assertTrue(proposal["action"])

    def test_letter_without_a_target_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            [(_id, payload)] = rsi.rsi_review_messages(Path(d), rsi.analyze(ROWS))
        self.assertNotIn("requested_target", payload)
        self.assertFalse(_addressed(payload, ("claude", "codex", "antigravity")))


class SentinelRoutesReviewTest(unittest.TestCase):
    def _cycle(self, desk: dict[str, str]) -> dict:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".coord" / "mailbox").mkdir(parents=True)
            box = Mailbox(root / ".coord" / "mailbox")
            for tool, state in desk.items():
                presence.mark(root, tool, state, ttl_s=600)
            _ledger(root, ROWS)
            result = run_sentinel_cycle(root, box)
            self.assertEqual(["rsi_review_ollama_10x1"], result["rsi_review_published"])
            self.assertIsNone(result["rsi_error"])
            letter = json.loads((root / ".coord" / "mailbox" / "inbox" / "rsi_review_ollama_10x1.json")
                                .read_text(encoding="utf-8"))
            return letter["payload"]

    def test_review_goes_to_the_acting_conductor(self) -> None:
        payload = self._cycle({"codex": "LIMITED", "claude": "ACTIVE", "antigravity": "ACTIVE"})
        self.assertEqual("claude", payload["requested_target"])
        self.assertEqual("RSI_REVIEW", payload["kind"])

    def test_unknown_desk_fails_closed_to_mailbox_only(self) -> None:
        payload = self._cycle({})
        self.assertNotIn("requested_target", payload)


if __name__ == "__main__":
    unittest.main()
