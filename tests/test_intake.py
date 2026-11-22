"""U350: the ideas intake queue (`.coord/intake/ideas.jsonl`).

C33: P0 is deterministic (explicit user flag or emergency keyword); a model hint never promotes, ambiguity is P1.
C34: concurrent appends from real OS processes lose no line; a full queue sheds with an audited QUEUE_SHED row.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord import intake

REPO = Path(__file__).resolve().parents[1]


class ClassifierTest(unittest.TestCase):
    def test_explicit_user_flag_is_p0(self) -> None:
        self.assertEqual("P0", intake.classify("tidy the readme", user_p0=True))

    def test_emergency_keyword_is_p0(self) -> None:
        for text in ("P0: desk is down", "긴급 장애 발생", "EMERGENCY stop the workers", "outage in mailbox"):
            self.assertEqual("P0", intake.classify(text), text)

    def test_model_hint_never_promotes_to_p0(self) -> None:
        self.assertEqual("P1", intake.classify("maybe speed up the radar", model_hint="P0"))

    def test_model_hint_never_demotes_either(self) -> None:
        self.assertEqual("P1", intake.classify("maybe speed up the radar", model_hint="P2"))

    def test_ambiguous_defaults_to_p1(self) -> None:
        self.assertEqual("P1", intake.classify("rework the radar thresholds"))
        self.assertEqual("P1", intake.classify(""))

    def test_explicit_low_marker_is_p2(self) -> None:
        self.assertEqual("P2", intake.classify("someday: nicer colours"))
        self.assertEqual("P2", intake.classify("나중에 색상 정리"))

    def test_p0_wins_over_p2_marker(self) -> None:
        self.assertEqual("P0", intake.classify("나중에 말고 긴급: 장애"))

    def test_keyword_inside_word_does_not_match(self) -> None:
        self.assertEqual("P1", intake.classify("the AP0 module name"))


class QueueTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_append_writes_one_valid_row(self) -> None:
        row = intake.append_idea(self.project, "긴급 장애", source="claude", now=10.0)
        self.assertEqual("P0", row["priority"])
        self.assertFalse(row.get("shed"))
        rows = intake.read_ideas(self.project)
        self.assertEqual(1, len(rows))
        self.assertEqual([], intake.validate(rows[0]))
        self.assertEqual("긴급 장애", rows[0]["text"])
        self.assertEqual(1, rows[0]["seq"])

    def test_model_hint_is_recorded_but_not_used(self) -> None:
        row = intake.append_idea(self.project, "an idea", source="agy", model_hint="P0")
        self.assertEqual("P1", row["priority"])
        self.assertEqual("P0", row["model_hint"])

    def test_validate_rejects_bad_rows(self) -> None:
        self.assertIn("priority", " ".join(intake.validate({"seq": 1, "text": "x", "source": "a", "priority": "P9", "at": 1.0})))
        self.assertTrue(intake.validate({"text": "x"}))
        self.assertTrue(intake.validate("not a dict"))  # type: ignore[arg-type]

    def test_cap_sheds_with_audit_row_not_silent(self) -> None:
        for i in range(3):
            intake.append_idea(self.project, f"idea {i}", source="claude", cap=3)
        shed = intake.append_idea(self.project, "one too many", source="claude", cap=3)
        self.assertTrue(shed["shed"])
        self.assertEqual("QUEUE_SHED", shed["event"])
        self.assertEqual(3, len(intake.read_ideas(self.project)))
        audit = intake.read_shed(self.project)
        self.assertEqual(1, len(audit))
        self.assertEqual("QUEUE_SHED", audit[0]["event"])
        self.assertEqual("one too many", audit[0]["text"])
        self.assertEqual(3, audit[0]["cap"])

    def test_torn_last_line_does_not_swallow_next_row(self) -> None:
        intake.append_idea(self.project, "first", source="claude")
        path = self.project / intake.IDEAS_REL
        with open(path, "ab") as handle:
            handle.write(b'{"seq": 2, "text": "tor')
        intake.append_idea(self.project, "after tear", source="claude")
        texts = [r["text"] for r in intake.read_ideas(self.project)]
        self.assertEqual(["first", "after tear"], texts)

    def test_empty_source_rejected(self) -> None:
        with self.assertRaises(ValueError):
            intake.append_idea(self.project, "x", source="")


class ParallelWriteTest(unittest.TestCase):
    """C34 proof with real OS processes: Windows loses lines on unlocked concurrent appends."""

    PROCS = 4
    PER_PROC = 25

    def test_ideas_parallel_write_no_loss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            code = ("import sys; from pathlib import Path; from v7_harness.coord import intake\n"
                    "for n in range(int(sys.argv[3])):\n"
                    "    intake.append_idea(Path(sys.argv[1]), f'w{sys.argv[2]}-{n}', source='w' + sys.argv[2], cap=100000)\n")
            env = {**os.environ, "PYTHONPATH": str(REPO)}
            procs = [subprocess.Popen([sys.executable, "-c", code, str(project), str(i), str(self.PER_PROC)], cwd=REPO,
                                      env=env, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
                     for i in range(self.PROCS)]
            pids = {p.pid for p in procs}
            self.assertEqual(self.PROCS, len(pids))
            for proc in procs:
                _, err = proc.communicate(timeout=120)
                self.assertEqual(0, proc.returncode, err)
            raw = (project / intake.IDEAS_REL).read_bytes()
            lines = raw.decode("utf-8").splitlines()
            written = {f"w{i}-{n}" for i in range(self.PROCS) for n in range(self.PER_PROC)}
            persisted = [json.loads(line) for line in lines]
            self.assertEqual(len(written), len(persisted))
            self.assertEqual(written, {r["text"] for r in persisted})
            self.assertEqual(list(range(1, len(written) + 1)), [r["seq"] for r in persisted])
            self.assertTrue(raw.endswith(b"\n"))
            self.assertTrue(all(intake.validate(r) == [] for r in persisted))


if __name__ == "__main__":
    unittest.main()
