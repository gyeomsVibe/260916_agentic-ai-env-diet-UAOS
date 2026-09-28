"""U74: close the ledger gaps U72/U73 left open.

Seen 2026-09-28 (U72/U73): every pilot row had wall_time_s null, the U70/U71 qualification calls left no ledger row,
and a Codex session's tokens could not be recorded because its rollout format differs from a Claude transcript.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness import model_qualification as mq
from v7_harness.admission import ledger_rows, observed_floor
from v7_harness.coord.deliver import deliver
from v7_harness.coord.session_usage import record_session
from v7_harness.rsi import load_rows

from tests.test_u38_cost_gate_and_claude_worker import _run
from tests.test_u51_model_qualification import SOURCES, FakeProvider


def _ledger(root: Path) -> list[dict]:
    path = root / ".coord" / "usage" / "runs.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class PilotWallTimeTests(unittest.TestCase):
    def test_the_pilot_row_records_a_measured_wall_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _run(root, {"input_tokens": 1, "output_tokens": 1}, None, task="U74_WALL")
            row = _ledger(root / "proj")[-1]
            wall = row["wall_time_s"]
            self.assertIsInstance(wall, float)
            self.assertGreater(wall, 0.0)
            self.assertLess(wall, 600.0)


def _token_count(stamp: str, total_input: int, cached: int, output: int) -> str:
    total = {"input_tokens": total_input, "cached_input_tokens": cached, "cache_write_input_tokens": 0,
             "output_tokens": output, "reasoning_output_tokens": 0, "total_tokens": total_input + output}
    return json.dumps({"timestamp": stamp, "type": "event_msg",
                       "payload": {"type": "token_count", "info": {"total_token_usage": total}}})


class CodexRolloutTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / ".coord").mkdir()
        self.rollout = self.root / "rollout-2026-09-27-x.jsonl"
        lines = [
            json.dumps({"timestamp": "2026-09-27T00:00:00.000Z", "type": "turn_context",
                        "payload": {"model": "gpt-5.5-codex"}}),
            _token_count("2026-09-27T00:00:01.000Z", 1000, 800, 50),
            _token_count("2026-09-27T00:00:02.000Z", 1000, 800, 50),  # repeated without a new call
            json.dumps({"timestamp": "2026-09-27T00:00:03.000Z", "type": "event_msg",
                        "payload": {"type": "token_count", "info": None}}),  # rate-limit-only event
            _token_count("2026-09-27T00:00:11.000Z", 2500, 2000, 80),
        ]
        self.rollout.write_text("".join(line + "\n" for line in lines), encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_cumulative_totals_become_per_call_deltas_with_the_cached_part_split(self) -> None:
        dry = record_session(self.root, self.rollout, work_id="U74-CODEX")
        self.assertEqual(("DRY_RUN", 2, "gpt-5.5-codex"), (dry["mode"], dry["api_calls"], dry["model"]))
        # input 2500 of which cached 2000 -> uncached 500; output 80; no cache writes.
        self.assertEqual((500, 80, 2000, 0), (dry["input_tokens"], dry["output_tokens"],
                                              dry["cache_read_input_tokens"], dry["cache_creation_input_tokens"]))
        self.assertEqual(10.0, dry["wall_time_s"])

    def test_the_row_names_codex_and_stays_out_of_rsi_and_admission(self) -> None:
        record_session(self.root, self.rollout, work_id="U74-CODEX", apply=True)
        rows = _ledger(self.root)
        self.assertEqual([("codex", "codex", "session")], [(r["actor"], r["worker"], r["kind"]) for r in rows])
        self.assertEqual([], load_rows(self.root))
        self.assertIsNone(observed_floor(ledger_rows(self.root), "codex", "review"))
        self.assertEqual("NOTHING_NEW", record_session(self.root, self.rollout, work_id="U74-X", apply=True)["mode"])


class QualificationLedgerTests(unittest.TestCase):
    def test_a_project_store_gets_one_qualification_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = mq.qualify(root / mq.QUALIFICATION_STORE, FakeProvider(["sha256:abc123def4567890"]), "m", SOURCES)
            rows = _ledger(root)
            self.assertEqual(1, len(rows))
            row = rows[0]
            self.assertEqual(("qualification", "ollama", "m", len(SOURCES)),
                             (row["kind"], row["worker"], row["model"], row["calls"]))
            self.assertEqual("QUALIFY-m-sha256:abc12", row["work_id"])
            self.assertGreater(row["input_tokens"] + row["output_tokens"], 0)
            self.assertEqual(Path(result["usage_ledger"]).resolve(),
                             (root / ".coord" / "usage" / "runs.jsonl").resolve())
            # A measurement row never becomes an RSI attempt or a pilot/review admission floor.
            self.assertEqual([], load_rows(root))
            self.assertIsNone(observed_floor(ledger_rows(root), "ollama", "pilot"))

    def test_a_store_outside_a_project_writes_no_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = mq.qualify(root / "scratch", FakeProvider(["sha256:abc123def4567890"]), "m", SOURCES)
            self.assertIsNone(result["usage_ledger"])
            self.assertEqual([], _ledger(root))


class _Completed:
    returncode = 0
    stdout = json.dumps({"result": "processed", "is_error": False})
    stderr = ""


class AckOnlyNeverPaidTests(unittest.TestCase):
    """U74-D. Seen 2026-09-28: the U71 E2E failed once under full-suite load with an ACK_ONLY letter DISPATCHED to a
    paid `claude -p` turn. The watcher had already returned on the published letter and cleared its file, so a later
    racer saw no watcher and dispatched (measured by instrumenting watcher_live: 3 of 4 parallel runs)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        (self.project / ".coord" / "mailbox").mkdir(parents=True)
        self.calls: list = []

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _deliver(self, message: str):
        def runner(argv, **kwargs):
            self.calls.append(argv)
            return _Completed()

        with mock.patch("v7_harness.coord.deliver.shutil.which", return_value="claude"):
            return deliver(self.project, message=message, actor="codex", target="claude", runner=runner)

    def test_an_ack_only_letter_without_a_watcher_is_queued_not_dispatched(self) -> None:
        result = self._deliver("ACK_ONLY liveness: U74 unchanged")
        self.assertEqual(("QUEUED_ACK_ONLY", []), (result.reason, self.calls))
        self.assertTrue((self.project / ".coord" / "mailbox" / "inbox" / f"{result.message_id}.json").is_file())

    def test_a_real_delta_without_a_watcher_is_still_dispatched(self) -> None:
        result = self._deliver("ACTIONABLE_DELTA verdict_requested=yes: U74 check")
        self.assertEqual(("DISPATCHED", 1), (result.reason, len(self.calls)))


if __name__ == "__main__":
    unittest.main()
