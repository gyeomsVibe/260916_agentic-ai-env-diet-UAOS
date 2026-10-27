"""U200: the zero-paid sentinel drains Antigravity letters parked at an earlier Seoul day's cap; a `pilot judge`
APPROVE on the same bundle counts as the independent review at the calculator gate.

Receipt A (coord log 20261016T0106-claude-0001, .work/midnight_idle_261016.md): letters parked in agy_backlog at the
daily cap were drained only by presence.mark(dispatch=True), the hook-turn path. The CLI `coord presence` and the
sentinel loop never drained, so after midnight the parked letters waited 40 minutes for a human turn.
Receipt B (seen twice, U192 and U199): calculator_gate._review_ok read only review_<reviewer>.json from `pilot review`,
not judge_<reviewer>.json APPROVE from `pilot judge`, so a binding judge approval did not pass the commit gate.
Independence stays: the judge must not be the bundle's author, the bundle id must match, and a non-local author still
needs a failed local run of the same card.
"""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.test_u164_agy_backlog import Base
from v7_harness import calculator_gate
from v7_harness.coord import agy_dispatch, presence
from v7_harness.coord.mailbox import Mailbox
from v7_harness.coord.sentinel import run_sentinel_cycle

YESTERDAY = time.time() - 86400  # always the previous Seoul day, whatever the clock says now


class SentinelDrain(Base):
    def box(self) -> Mailbox:
        folder = self.project / ".coord" / "mailbox"
        folder.mkdir(parents=True, exist_ok=True)
        return Mailbox(folder)

    def park_at(self, ts: float) -> None:
        self.fill_cap(ts)
        row = agy_dispatch.dispatch(self.project, message_id="relay_u200parked01", actor="claude",
                                    message="ACTIONABLE_DELTA audit U200", runner=self.runner, now=ts)
        self.assertEqual(row["state"], "CAP_REACHED_BACKLOG")
        self.assertEqual(self.parked(), ["relay_u200parked01.json"])
        self.assertEqual(self.calls, [])

    def test_1_a_sentinel_cycle_on_the_next_day_answers_the_parked_letter(self):
        self.park_at(YESTERDAY)
        result = run_sentinel_cycle(self.project, self.box(), drain_runner=self.runner)
        self.assertIs(result["agy_backlog"], True)
        self.assertEqual(result["paid_api_calls"], 0)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.parked(), [])

    def test_2_a_sentinel_cycle_on_the_capped_day_starts_nothing(self):
        self.park_at(time.time())
        result = run_sentinel_cycle(self.project, self.box(), drain_runner=self.runner)
        self.assertIs(result["agy_backlog"], False)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.parked(), ["relay_u200parked01.json"])

    def test_3_the_resident_loop_drains_in_a_detached_process(self):
        self.park_at(YESTERDAY)
        with mock.patch.object(presence, "_spawn_detached") as spawn:
            result = run_sentinel_cycle(self.project, self.box())
        spawn.assert_called_once_with(presence.AGY_DRAIN_CODE, str(self.project))
        self.assertIs(result["agy_backlog"], True)
        self.assertEqual(self.calls, [])

    def test_4_an_empty_backlog_spawns_nothing(self):
        with mock.patch.object(presence, "_spawn_detached") as spawn:
            result = run_sentinel_cycle(self.project, self.box())
        spawn.assert_not_called()
        self.assertIs(result["agy_backlog"], False)


class JudgeCountsAsReview(unittest.TestCase):
    BUNDLE = "bundle-u200"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.task = Path(self._tmp.name) / "U200-T1"
        self.task.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name: str, **record) -> None:
        base = {"judge": "antigravity", "author_worker": "local", "bundle_id": self.BUNDLE, "verdict": "APPROVE",
                "error": None}
        base.update(record)
        (self.task / name).write_text(json.dumps(base), encoding="utf-8")

    def ok(self, ledger_rows=()) -> bool:
        return calculator_gate._review_ok(self.task, self.BUNDLE, list(ledger_rows))

    def test_5_a_judge_approve_on_the_same_bundle_passes(self):
        self.write("judge_agy.json")
        self.assertTrue(self.ok())

    def test_6_a_judge_approve_on_another_bundle_fails(self):
        self.write("judge_agy.json", bundle_id="bundle-other")
        self.assertFalse(self.ok())

    def test_7_a_judge_that_did_not_approve_fails(self):
        for verdict in ("REWORK", "REJECT", "UNUSABLE", "PASS"):
            with self.subTest(verdict=verdict):
                self.write("judge_agy.json", verdict=verdict)
                self.assertFalse(self.ok())

    def test_8_a_judge_of_its_own_bundle_fails(self):
        for author in ("agy", "antigravity"):
            with self.subTest(author=author):
                self.write("judge_agy.json", author_worker=author)
                self.assertFalse(self.ok())
        self.write("judge_codex.json", judge="codex", author_worker="codex")
        self.assertFalse(self.ok())

    def test_9_a_judge_record_with_an_error_fails(self):
        self.write("judge_agy.json", error="JUDGE_FAILED:agy exit 1")
        self.assertFalse(self.ok())

    def test_10_a_non_local_author_still_needs_a_failed_local_run(self):
        self.write("judge_agy.json", author_worker="claude")
        self.assertFalse(self.ok())
        failed = {"work_id": "U200-T0", "worker": "local", "outcome": "FAILED", "input_tokens": 1200}
        self.assertTrue(self.ok([failed]))

    def test_11_a_review_pass_still_passes(self):
        self.write("review_agy.json", reviewer="agy", verdict="PASS")
        self.assertTrue(self.ok())

    def test_12_a_review_approve_is_not_a_pass(self):
        self.write("review_agy.json", reviewer="agy", verdict="APPROVE")
        self.assertFalse(self.ok())


if __name__ == "__main__":
    unittest.main()
