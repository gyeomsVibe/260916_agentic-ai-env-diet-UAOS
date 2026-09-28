"""U72-L: a run inside a linked worktree lands in the desk ledger, and rows stranded in worktree copies come back.

Seen 2026-09-28: U68-U71 ran their pilots in `.work/<id>` worktrees. Each appended to that worktree's copy of the
tracked `runs.jsonl`, which is never committed, so the desk ledger that admission (U69) and RSI read stopped at
U44-FIX6B. The U72 gate "no ledger omission" could not pass.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from v7_harness.admission import ledger_rows
from v7_harness.coord.usage_ledger import collect, linked_worktrees, record_usage

REPO = Path(__file__).resolve().parents[1]


def _entry(work_id: str) -> dict:
    return {"schema": "uaos-usage-v2", "work_id": work_id, "actor": "coordinator", "model": "deterministic",
            "kind": "pilot", "collection_mode": "automatic", "input_tokens": 0, "output_tokens": 0,
            "wall_time_s": 1.5, "outcome": "PASS", "receipt": "r.json", "independent_verifier": None,
            "rsi_eligible": False, "exclusion_reason": "PENDING_INDEPENDENT_VERIFICATION", "ts": 1.0}


def _line(work_id: str) -> str:
    return json.dumps(_entry(work_id), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _ledger(root: Path) -> Path:
    return root / ".coord" / "usage" / "runs.jsonl"


def _write(root: Path, *work_ids: str, crlf: bool = False) -> None:
    path = _ledger(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    end = "\r\n" if crlf else "\n"
    path.write_bytes("".join(_line(w) + end for w in work_ids).encode("utf-8"))


def _ids(root: Path) -> list[str]:
    return [json.loads(line)["work_id"] for line in _ledger(root).read_text(encoding="utf-8").splitlines() if line]


class DeskFixture(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.desk = base / "main"
        (self.desk / ".coord").mkdir(parents=True)
        (self.desk / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        self.trees = []
        for name in ("w1", "w2"):
            (self.desk / ".git" / "worktrees" / name).mkdir(parents=True)
            tree = base / name
            (tree / ".coord").mkdir(parents=True)
            (tree / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
            (tree / ".git").write_text(f"gitdir: {(self.desk / '.git' / 'worktrees' / name).as_posix()}\n",
                                       encoding="utf-8")
            # Git's own back-pointer: the linked worktree's `.git` file path.
            (self.desk / ".git" / "worktrees" / name / "gitdir").write_text(f"{(tree / '.git').as_posix()}\n",
                                                                           encoding="utf-8")
            self.trees.append(tree)

    def tearDown(self) -> None:
        self._tmp.cleanup()


class DeskRoutingTests(DeskFixture):
    def test_a_worktree_run_is_recorded_and_read_on_the_desk(self) -> None:
        written = record_usage(self.trees[0], _entry("U72L-A"))
        self.assertEqual(_ledger(self.desk).resolve(), written.resolve())
        self.assertFalse(_ledger(self.trees[0]).exists())
        # Admission inside the worktree sees the desk floor it just added to.
        self.assertEqual(["U72L-A"], [r["work_id"] for r in ledger_rows(self.trees[1])])

    def test_a_plain_folder_keeps_its_own_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(_ledger(Path(d)).resolve(), record_usage(Path(d), _entry("U72L-P")).resolve())


class CollectTests(DeskFixture):
    def test_stranded_rows_come_back_once_and_only_with_apply(self) -> None:
        _write(self.desk, "BASE1", "BASE2", crlf=True)  # a CRLF checkout of the same rows is not a new row
        _write(self.trees[0], "BASE1", "BASE2", "U68", "U70")
        _write(self.trees[1], "BASE1", "U70", "U71")
        dry = collect(self.desk, trees=self.trees)
        self.assertEqual((3, 0, "DRY_RUN"), (dry["orphans"], dry["appended"], dry["mode"]))
        self.assertEqual(["BASE1", "BASE2"], _ids(self.desk))
        done = collect(self.desk, trees=self.trees, apply=True)
        self.assertEqual(3, done["appended"])
        self.assertEqual(["BASE1", "BASE2", "U68", "U70", "U71"], _ids(self.desk))
        # The appended bytes are the worktree's own line, not a re-stamped record.
        self.assertIn(_line("U68"), _ledger(self.desk).read_text(encoding="utf-8").splitlines())
        self.assertEqual(0, collect(self.desk, trees=self.trees, apply=True)["appended"])

    def test_worktrees_are_found_from_git_records_without_a_subprocess(self) -> None:
        (self.desk / ".git" / "worktrees" / "gone").mkdir()
        (self.desk / ".git" / "worktrees" / "gone" / "gitdir").write_text("/nowhere/.git\n", encoding="utf-8")
        self.assertEqual([t.resolve() for t in self.trees], [t.resolve() for t in linked_worktrees(self.desk)])
        _write(self.desk, "BASE1")
        _write(self.trees[1], "BASE1", "U71")
        self.assertEqual(1, collect(self.trees[0], apply=True)["appended"])  # from inside a worktree, too
        self.assertEqual(["BASE1", "U71"], _ids(self.desk))

    def test_parallel_collectors_append_each_row_once(self) -> None:
        _write(self.desk, "BASE1")
        for i, tree in enumerate(self.trees):
            _write(tree, "BASE1", *[f"T{i}-{n}" for n in range(20)])
        code = ("import sys; from pathlib import Path; from v7_harness.coord.usage_ledger import collect; "
                "collect(Path(sys.argv[1]), trees=[Path(p) for p in sys.argv[2:]], apply=True)")
        argv = [sys.executable, "-c", code, str(self.desk), *map(str, self.trees)]
        env = {**os.environ, "PYTHONPATH": str(REPO)}
        procs = [subprocess.Popen(argv, cwd=REPO, env=env, stderr=subprocess.PIPE, text=True) for _ in range(6)]
        for proc in procs:
            _, err = proc.communicate(timeout=120)
            self.assertEqual(0, proc.returncode, err)
        ids = _ids(self.desk)
        self.assertEqual(41, len(ids))
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
