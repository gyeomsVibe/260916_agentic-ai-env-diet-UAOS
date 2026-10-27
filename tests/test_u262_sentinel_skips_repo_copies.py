"""U262: the reconciliation sentinel skips repo copies under `.work/` but never a live pilot dir.

Seen 2026-10-27: every P1 wake still carried `NEEDS_RECONCILIATION: P01` after U260/U261. `pilot_dirs.discover`
scans `.work/<a>` and `.work/<a>/<b>`; about 90 of those are git checkouts (`.work/wt_u257`, `.work/u75`) whose
`.coord/runs/P01/summary.json` is the git-tracked historical summary, with no ledger row of their own to clear it.
They are other checkouts, not this project's pilot work, so the sentinel must ignore them unless their own ledger
holds an open attempt. Fixed acceptance written by the judge (claude) first.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.broker.core import BrokerCore
from v7_harness.coord.sentinel import check_all_pilot_dirs

H = "a" * 64
STALE = {"state": "FAILED", "error_class": "NEEDS_RECONCILIATION", "effect_state": "UNKNOWN"}


def _summary(pilot: Path, task: str) -> None:
    run = pilot / "runs" / task
    run.mkdir(parents=True)
    (run / "summary.json").write_text(json.dumps(STALE), encoding="utf-8")


def _attempt(pilot: Path, task: str, state: str) -> None:
    core = BrokerCore(pilot / "coord.sqlite3")
    core.start()
    try:
        core.connection.execute(
            "INSERT INTO plans(task_id,card_revision,status,depends_json,acceptance_hash) VALUES(?,0,'ACTIVE','[]',?)",
            (task, H),
        )
        core.connection.execute(
            "INSERT INTO attempts(attempt_id,task_id,max_hops,state,idempotency_key) VALUES(?,?,1,?,?)",
            (f"{task}-a001", task, state, f"{task}:a001"),
        )
    finally:
        core.close()


def _copy(project: Path, name: str, marker: str) -> Path:
    """A repo copy under .work: a git checkout (`.git` file or dir) or a project copy (`.coord/PLAN.md`)."""
    root = project / ".work" / name
    (root / ".coord").mkdir(parents=True)
    if marker == "git_dir":
        (root / ".git").mkdir()
    elif marker == "git_file":
        (root / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    else:
        (root / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
    return root


class SentinelSkipsRepoCopiesTests(unittest.TestCase):
    def test_historical_summary_in_repo_copies_is_ignored(self) -> None:
        for marker in ("git_dir", "git_file", "plan"):
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as d:
                project = Path(d)
                root = _copy(project, "wt_u257", marker)
                _summary(root / ".coord", "P01")
                self.assertEqual([], check_all_pilot_dirs(project))

    def test_copy_with_settled_ledger_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            project = Path(d)
            root = _copy(project, "u197", "git_dir")
            _summary(root / ".coord", "P01")
            _attempt(root / ".coord", "P01", "FAILED")
            self.assertEqual([], check_all_pilot_dirs(project))

    def test_copy_with_open_attempt_is_still_reported(self) -> None:
        for state in ("RUNNING", "PENDING", "VERIFYING", "NEEDS_RECONCILIATION"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as d:
                project = Path(d)
                root = _copy(project, "wt_u300", "git_dir")
                _summary(root / ".coord", "U300-L1")
                _attempt(root / ".coord", "U300-L1", state)
                self.assertEqual(["U300-L1"], check_all_pilot_dirs(project))

    def test_live_work_pilot_dirs_are_still_reported(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            project = Path(d)
            _summary(project / ".work" / "u262", "U262-L1")
            _summary(project / ".work" / "eval" / "run_x", "EVAL-x")
            _summary(project / ".coord", "P02")
            self.assertEqual(["EVAL-x", "P02", "U262-L1"], check_all_pilot_dirs(project))

    def test_project_root_itself_is_never_treated_as_a_copy(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            project = Path(d)
            (project / ".git").mkdir()
            (project / ".coord").mkdir()
            (project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
            _summary(project / ".coord", "P01")
            self.assertEqual(["P01"], check_all_pilot_dirs(project))


if __name__ == "__main__":
    unittest.main()
