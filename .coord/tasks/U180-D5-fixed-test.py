"""U180-D5 (real use, Lotto v3.0 slice S01, 2026-10-16): `pilot judge --judge codex` returned APPROVE but
approve_exit 2 and applied false, because the approval call passed the ledger label "ollama" as
`pilot run --worker`, which argparse rejects. The approval call must name the run choice "local".
"""

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness import judge
from v7_harness.cli import build_parser

MANUAL = """```contract
work_id: T1
worker: local
goal: g
allow:
- a.py
acceptance: python -c "pass"
judge: codex
remote_budget_tokens: 0
```
"""


class Done:
    def __init__(self, stdout=b"", returncode=0):
        self.stdout = stdout
        self.stderr = b""
        self.returncode = returncode


class OllamaAuthorApprovalTest(unittest.TestCase):
    def test_approval_call_uses_a_valid_worker_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work, source, stage = root / "work", root / "src", root / "stage"
            runs = work / "runs" / "T1"
            for folder in (runs, source, stage):
                folder.mkdir(parents=True)
            (source / "a.py").write_text("X = 1\n", encoding="utf-8")
            (stage / "a.py").write_text("X = 2\n", encoding="utf-8")
            (runs / "worker").write_text("ollama", encoding="utf-8")
            (runs / "summary.json").write_text(json.dumps(
                {"agy_workspace": str(stage), "changed_files": ["a.py"], "bundle_id": "b1",
                 "promotion": "DRY_RUN_PASSED", "acceptance_exit": 0}), encoding="utf-8")
            manual = root / "m.md"
            manual.write_text(MANUAL, encoding="utf-8")
            approvals = []

            def runner(argv, **kwargs):
                Path(argv[argv.index("-o") + 1]).write_text(
                    json.dumps({"verdict": "APPROVE", "bundle_id": "b1", "evidence": ["x"]}), encoding="utf-8")
                events = [{"type": "thread.started", "thread_id": "t"},
                          {"type": "turn.completed", "usage": {"input_tokens": 12_000, "output_tokens": 900}}]
                return Done("\n".join(json.dumps(e) for e in events).encode("utf-8"))

            record = judge.run_judge(task_id="T1", work_dir=work, source=source, manual_path=manual, project=root,
                                     judge="codex", budget=50_000, runner=runner,
                                     approver=lambda cmd, **k: approvals.append(cmd) or Done(b"APPLIED"),
                                     desk={"codex": {"state": "ACTIVE"}})
        self.assertEqual("APPROVE", record["verdict"])
        self.assertEqual(1, len(approvals))
        argv = approvals[0][approvals[0].index("pilot"):]
        self.assertEqual("local", argv[argv.index("--worker") + 1])
        # The real parser accepts the call (argparse exit 2 was the observed failure).
        build_parser().parse_args(argv)
        self.assertTrue(record["applied"])
