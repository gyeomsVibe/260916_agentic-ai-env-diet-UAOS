"""U165: a pilot circuit that cooled down admits one canary run instead of refusing every run forever.

Receipt (2026-10-05 00:11 KST, overnight R13): three local Ollama refusals opened provider=antigravity/WORKER_CRASH in
the work dir's coord.sqlite3. After the 60 s cooldown the circuit turned HALF_OPEN, and `pilot run` never passed
is_canary=True, so every later run in that work dir failed CANARY_REQUIRED_IN_HALF_OPEN. The local refusals were also
booked to provider antigravity, so an Ollama failure blocked Antigravity work.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from v7_harness.pilot import PilotConfig, run_pilot

FIXTURE = Path(__file__).parent / "fixtures" / "fake_agy.py"
ORIGINAL = "def mul(a, b):\n    return a * b\n"


class CircuitCanaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "sample"
        self.source.mkdir()
        (self.source / "calc.py").write_text(ORIGINAL, encoding="utf-8")
        self.home = self.root / "home"
        self.home.mkdir()
        self.work = self.root / "work"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _run(self, task_id: str, mode: str, command: list[str] | None = None) -> dict:
        config = PilotConfig(task_id=task_id, title="u165", prompt="Add add().", source_dir=self.source,
                             work_dir=self.work, agy_command=command or [sys.executable, str(FIXTURE)],
                             watch_roots=[self.home], print_timeout_s=60)
        with mock.patch.dict(os.environ, {"FAKE_AGY_MODE": mode, "FAKE_AGY_OUTSIDE_DIR": str(self.home)}):
            return run_pilot(config)

    def _sql(self, statement: str) -> list[tuple]:
        # closing(): sqlite3's own context manager commits but leaves the file open, and Windows then cannot delete it.
        with closing(sqlite3.connect(self.work / "coord.sqlite3")) as connection, connection:
            return connection.execute(statement).fetchall()

    def _circuits(self) -> list[tuple[str, str, str]]:
        return self._sql("SELECT provider, failure_class, state FROM circuits")

    def _open_and_cool(self, command: list[str] | None = None) -> None:
        for n in range(3):
            self.assertNotEqual("SUCCEEDED", self._run(f"U165-F{n}", "error503_write", command)["state"])
        self.assertIn("OPEN", [state for _p, _f, state in self._circuits()])
        self._sql("UPDATE circuits SET retry_after=datetime('now', '-1 seconds')")

    def test_cooled_circuit_admits_a_canary_and_closes(self) -> None:
        self._open_and_cool()
        self.assertEqual("SUCCEEDED", self._run("U165-C1", "success")["state"])
        self.assertEqual({"CLOSED"}, {state for _p, _f, state in self._circuits()})
        self.assertEqual("SUCCEEDED", self._run("U165-C2", "success")["state"])

    def test_half_open_circuit_left_by_a_refused_run_admits_a_canary(self) -> None:
        self._open_and_cool()
        self._sql("UPDATE circuits SET state='HALF_OPEN'")
        self.assertEqual("SUCCEEDED", self._run("U165-H1", "success")["state"])
        self.assertEqual({"CLOSED"}, {state for _p, _f, state in self._circuits()})

    def test_circuit_still_open_before_cooldown_refuses(self) -> None:
        for n in range(3):
            self._run(f"U165-F{n}", "error503_write")
        summary = self._run("U165-R1", "success")
        self.assertNotEqual("SUCCEEDED", summary["state"])
        self.assertIn("CIRCUIT_OPEN", str(summary.get("error_class")) + str(summary.get("error_detail")))

    def test_a_local_worker_trips_its_own_circuit_not_antigravity(self) -> None:
        local = self.root / "ollama_fake.py"
        shutil.copyfile(FIXTURE, local)
        self._open_and_cool([sys.executable, str(local)])
        providers = {provider for provider, _f, _s in self._circuits()}
        self.assertNotIn("antigravity", providers)
        self.assertIn("ollama", providers)


if __name__ == "__main__":
    unittest.main()
