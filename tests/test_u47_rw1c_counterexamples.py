"""U47-RW1c frozen acceptance (written by Claude): Codex's two counterexamples to bundle U47-RW1 (2026-09-27).

1. `codex exec` exited 1 but left a valid APPROVE file; `pilot judge --judge codex` approved and applied it.
2. A heartbeat passed the lease check, a quota lease was written, and the heartbeat then replaced it (ACTIVE while
   the LIMITED lease was live). Reproduced with ordered threads and checked again with real parallel processes.
"""

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from v7_harness import judge
from v7_harness.coord import presence

ROOT = Path(__file__).resolve().parents[1]
MANUAL = """```contract
work_id: T1
worker: apply
goal: g
allow:
- a.py
acceptance: python -c "pass"
judge: codex
remote_budget_tokens: 0
```
"""
HEARTBEATS = """
import sys
sys.path.insert(0, sys.argv[1])
from v7_harness.coord.presence import mark
for _ in range(int(sys.argv[3])):
    mark(sys.argv[2], "antigravity", "ACTIVE", ttl_s=3600)
"""


class Done:
    def __init__(self, stdout=b"", returncode=0):
        self.stdout = stdout
        self.stderr = b""
        self.returncode = returncode


class NonzeroExitTest(unittest.TestCase):
    def test_failed_codex_call_with_valid_approve_file_is_not_a_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work, source, stage = root / "work", root / "src", root / "stage"
            runs = work / "runs" / "T1"
            for folder in (runs, source, stage):
                folder.mkdir(parents=True)
            (source / "a.py").write_text("X = 1\n", encoding="utf-8")
            (stage / "a.py").write_text("X = 2\n", encoding="utf-8")
            (runs / "worker").write_text("apply", encoding="utf-8")
            (runs / "summary.json").write_text(json.dumps(
                {"agy_workspace": str(stage), "changed_files": ["a.py"], "bundle_id": "b1",
                 "promotion": "DRY_RUN_PASSED", "acceptance_exit": 0}), encoding="utf-8")
            manual = root / "m.md"
            manual.write_text(MANUAL, encoding="utf-8")
            approvals = []

            def runner(argv, **kwargs):
                Path(argv[argv.index("-o") + 1]).write_text(
                    json.dumps({"verdict": "APPROVE", "bundle_id": "b1", "evidence": ["x"]}), encoding="utf-8")
                return Done(b'{"type": "thread.started", "thread_id": "t"}', returncode=1)

            record = judge.run_judge(task_id="T1", work_dir=work, source=source, manual_path=manual, project=root,
                                     judge="codex", budget=50_000, runner=runner,
                                     approver=lambda cmd, **k: approvals.append(cmd) or Done(b"APPLIED"),
                                     desk={"codex": {"state": "ACTIVE"}})
        self.assertEqual("UNUSABLE", record["verdict"])
        self.assertEqual("JUDGE_FAILED:codex exit 1", record["error"])
        self.assertFalse(record["applied"])
        self.assertEqual([], approvals)


class LeaseRaceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_ordered_interleaving_keeps_the_lease(self):
        checked, release = threading.Event(), threading.Event()
        original = presence._live_lease

        def gated(target, moment, state):
            result = original(target, moment, state)
            if threading.current_thread().name == "heartbeat":
                checked.set()
                release.wait(5)
            return result

        presence._live_lease = gated
        try:
            heartbeat = threading.Thread(name="heartbeat", target=presence.mark,
                                         args=(self.project, "antigravity", "ACTIVE"),
                                         kwargs={"ttl_s": 3600, "now": 1_001.0})
            heartbeat.start()
            self.assertTrue(checked.wait(5))
            lease = threading.Thread(name="lease", target=presence.mark,
                                     args=(self.project, "antigravity", "LIMITED"),
                                     kwargs={"ttl_s": 500, "now": 1_000.0, "lease": True})
            lease.start()
            lease.join(0.2)
            release.set()
            heartbeat.join(10)
            lease.join(10)
        finally:
            presence._live_lease = original
        self.assertFalse(heartbeat.is_alive() or lease.is_alive())
        self.assertEqual("LIMITED", presence.read(self.project, "antigravity", now=1_003.0)["state"])

    def test_parallel_processes_never_replace_a_live_lease(self):
        # 4 processes x 150 heartbeats run while the lease lands; each one after it must be dropped.
        procs = [subprocess.Popen([sys.executable, "-c", HEARTBEATS, str(ROOT), str(self.project), "150"])
                 for _ in range(4)]
        presence.mark(self.project, "antigravity", "ACTIVE", ttl_s=3600)
        presence.mark(self.project, "antigravity", "LIMITED", ttl_s=3600, lease=True)
        for proc in procs:
            self.assertEqual(0, proc.wait(120))
        self.assertEqual("LIMITED", presence.read(self.project, "antigravity")["state"])
        self.assertEqual([], [p.name for p in (self.project / ".coord" / "presence").iterdir()
                              if p.name != "antigravity.json"])


if __name__ == "__main__":
    unittest.main()
