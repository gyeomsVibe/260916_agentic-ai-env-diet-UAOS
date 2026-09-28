"""U73: an acting Claude session's own tokens reach the usage ledger, once per call.

Seen 2026-09-28 (U72): the cards U68-U72-L showed 0 paid pilot tokens while the acting session that built them
left no ledger row, so the "no 3x cost regression" gate was UNKNOWN.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from v7_harness.admission import admit, ledger_rows
from v7_harness.coord.session_usage import record_session
from v7_harness.coord.usage_ledger import UsageRejected
from v7_harness.rsi import load_rows

REPO = Path(__file__).resolve().parents[1]


def _call(message_id: str, stamp: str, out: int, *, model: str = "claude-opus-5-5", read: int = 1000) -> str:
    usage = {"input_tokens": 2, "output_tokens": out, "cache_read_input_tokens": read,
             "cache_creation_input_tokens": 10}
    return json.dumps({"type": "assistant", "timestamp": stamp,
                       "message": {"id": message_id, "model": model, "usage": usage}})


class SessionUsageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / ".coord").mkdir()
        self.transcript = self.root / "sess-1.jsonl"
        self._write([
            json.dumps({"type": "user", "timestamp": "2026-09-28T00:00:00.000Z"}),
            _call("m1", "2026-09-28T00:00:01.000Z", 100),
            _call("m1", "2026-09-28T00:00:01.500Z", 100),  # the same call repeated for its next content block
            _call("m2", "2026-09-28T00:00:11.000Z", 50),
            _call("s1", "2026-09-28T00:00:12.000Z", 999, model="<synthetic>"),  # a local notice, not an API call
            "not json",
        ])

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, lines: list[str], mode: str = "w") -> None:
        with open(self.transcript, mode, encoding="utf-8") as handle:
            handle.write("".join(line + "\n" for line in lines))

    def _session_rows(self) -> list[dict]:
        path = self.root / ".coord" / "usage" / "runs.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

    def test_each_call_counts_once_and_dry_run_writes_nothing(self) -> None:
        dry = record_session(self.root, self.transcript, work_id="U73-A")
        self.assertEqual(("DRY_RUN", 0, 2), (dry["mode"], dry["appended"], dry["api_calls"]))
        self.assertEqual((150, 4, 2000, 20), (dry["output_tokens"], dry["input_tokens"],
                                              dry["cache_read_input_tokens"], dry["cache_creation_input_tokens"]))
        self.assertEqual(10.0, dry["wall_time_s"])
        self.assertEqual([], self._session_rows())

    def test_recording_is_incremental_per_session(self) -> None:
        self.assertEqual(1, record_session(self.root, self.transcript, work_id="U73-A", apply=True)["appended"])
        self.assertEqual("NOTHING_NEW", record_session(self.root, self.transcript, work_id="U73-B", apply=True)["mode"])
        self._write([_call("m3", "2026-09-28T00:01:00.000Z", 7)], mode="a")
        second = record_session(self.root, self.transcript, work_id="U73-B", apply=True)
        self.assertEqual((1, 7), (second["api_calls"], second["output_tokens"]))
        rows = self._session_rows()
        self.assertEqual([("U73-A", 150), ("U73-B", 7)], [(r["work_id"], r["output_tokens"]) for r in rows])
        self.assertEqual({"session"}, {r["kind"] for r in rows})

    def test_session_rows_do_not_enter_rsi_or_admission_floors(self) -> None:
        record_session(self.root, self.transcript, work_id="U73-A", apply=True)
        self.assertEqual([], load_rows(self.root))
        self.assertEqual(1, len(ledger_rows(self.root)))  # the row is on the desk ledger ...
        for kind in ("pilot", "review"):  # ... but a whole-session spend is no floor for one Claude call
            self.assertEqual("ADMIT_UNMEASURED", admit(self.root, worker="claude", kind=kind, budget_tokens=1)["decision"])

    def test_missing_transcript_and_empty_work_id_are_refused(self) -> None:
        with self.assertRaises(UsageRejected):
            record_session(self.root, self.root / "missing.jsonl", work_id="U73-A")
        with self.assertRaises(UsageRejected):
            record_session(self.root, self.transcript, work_id="  ")

    def test_parallel_recorders_count_the_window_once(self) -> None:
        code = ("import sys; from pathlib import Path; from v7_harness.coord.session_usage import record_session; "
                "record_session(Path(sys.argv[1]), Path(sys.argv[2]), work_id='U73-P', apply=True)")
        argv = [sys.executable, "-c", code, str(self.root), str(self.transcript)]
        env = {**os.environ, "PYTHONPATH": str(REPO)}
        procs = [subprocess.Popen(argv, cwd=REPO, env=env, stderr=subprocess.PIPE, text=True) for _ in range(6)]
        for proc in procs:
            _, err = proc.communicate(timeout=120)
            self.assertEqual(0, proc.returncode, err)
        rows = self._session_rows()
        self.assertEqual(1, len(rows))
        self.assertEqual(150, rows[0]["output_tokens"])

    def test_cli_dry_run_reports_the_window(self) -> None:
        proc = subprocess.run([sys.executable, "-m", "v7_harness.cli", "coord", "usage-session", "--project",
                               str(self.root), "--transcript", str(self.transcript), "--work-id", "U73-C"],
                              cwd=REPO, capture_output=True, text=True, timeout=120,
                              env={**os.environ, "PYTHONPATH": str(REPO)})
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertEqual(("DRY_RUN", 2), (json.loads(proc.stdout)["mode"], json.loads(proc.stdout)["api_calls"]))


if __name__ == "__main__":
    unittest.main()
