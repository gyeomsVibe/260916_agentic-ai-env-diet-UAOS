"""U34: the worker harness — contract manuals, enforced scope, output guards, dictation without a model."""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from v7_harness.adapters import apply_worker
from v7_harness.adapters import ollama_worker as w
from v7_harness.calculator_gate import check
from v7_harness.cli import main
from v7_harness.manual import lint, new_manual, parse_contract
from v7_harness.pilot import PilotConfig, run_pilot
from v7_harness.pilot_dirs import discover

FAKE_AGY = [sys.executable, str(Path(__file__).parent / "fixtures" / "fake_agy.py")]
APPLY = [sys.executable, str(Path(apply_worker.__file__).resolve())]
TWO_FUNCS = "def keep():\n    return 1\n\n\ndef cmd_coord_log():\n    return 2\n"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class WorkerGuardTests(unittest.TestCase):
    def test_whole_file_rewrite_that_drops_a_function_is_rejected(self) -> None:
        # P08: the local model rewrote cli.py without cmd_coord_log; nobody asked for that.
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "cli.py").write_text(TWO_FUNCS, encoding="utf-8")
            text = "===FILE: cli.py===\ndef keep():\n    return 1\n\n\ndef cmd_coord_status():\n    return 3\n"
            with self.assertRaisesRegex(ValueError, "UNREQUESTED_DELETION:cli.py:cmd_coord_log"):
                w._apply(text, Path(d), task="Add cmd_coord_status to cli.py")
            self.assertEqual(TWO_FUNCS, (Path(d) / "cli.py").read_text(encoding="utf-8"))

    def test_deletion_named_by_the_task_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "cli.py").write_text(TWO_FUNCS, encoding="utf-8")
            text = "===FILE: cli.py===\ndef keep():\n    return 1\n"
            self.assertEqual(["cli.py"], w._apply(text, Path(d), task="Remove cmd_coord_log from cli.py"))

    def test_a_name_in_a_prohibition_is_not_a_deletion_request(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "cli.py").write_text(TWO_FUNCS, encoding="utf-8")
            text = "===FILE: cli.py===\ndef keep():\n    return 1\n"
            for task in ("forbidden: do not delete cmd_coord_log", "cmd_coord_log 삭제 금지", "keep cmd_coord_log as is"):
                with self.subTest(task=task), self.assertRaisesRegex(ValueError, "UNREQUESTED_DELETION"):
                    w._apply(text, Path(d), task=task)

    def test_edit_that_drops_a_function_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "cli.py").write_text(TWO_FUNCS, encoding="utf-8")
            text = "===EDIT: cli.py===\n<<<<<<< SEARCH\ndef cmd_coord_log():\n    return 2\n=======\n\n>>>>>>> REPLACE\n"
            with self.assertRaisesRegex(ValueError, "UNREQUESTED_DELETION"):
                w._apply(text, Path(d), task="tidy cli.py")

    def test_syntax_error_writes_nothing_even_with_a_valid_block(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a.py").write_text("x = 1\n", encoding="utf-8")
            text = "===FILE: b.py===\ny = 2\n===FILE: a.py===\nHere is the fixed file:\nx = = 1\n"
            with self.assertRaisesRegex(ValueError, "SYNTAX_ERROR:a.py"):
                w._apply(text, Path(d))
            self.assertFalse((Path(d) / "b.py").exists())
            self.assertEqual("x = 1\n", (Path(d) / "a.py").read_text(encoding="utf-8"))

    def test_dictated_paths_skip_the_template_placeholder(self) -> None:
        text = "===FILE: <relative/path>===\nx\n===EDIT: a.py===\n<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE\n"
        self.assertEqual(["a.py"], w.dictated_paths(text))


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def read(self):
        return json.dumps({"response": "{}", "prompt_eval_count": 1, "eval_count": 1}).encode()


class GenerationTests(unittest.TestCase):
    def _payload(self, **kwargs) -> dict:
        stored: dict = {}

        def fake_urlopen(request, timeout=None):
            stored.update(json.loads(request.data.decode()))
            return _Response()

        with mock.patch.object(w.urllib.request, "urlopen", side_effect=fake_urlopen):
            w._generate("m", "p", 5, **kwargs)
        return stored

    def test_seed_is_fixed_so_a_failure_can_be_reproduced(self) -> None:
        payload = self._payload()
        self.assertEqual(w.SEED, payload["options"]["seed"])
        self.assertNotIn("format", payload)

    def test_schema_is_sent_as_the_structured_output_format(self) -> None:
        schema = {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}
        self.assertEqual(schema, self._payload(fmt=schema)["format"])

    def test_evidence_extraction_constrains_the_output_shape(self) -> None:
        from v7_harness import olla_evidence

        with tempfile.TemporaryDirectory() as d:
            manual, evidence = Path(d) / "m.md", Path(d) / "e.txt"
            manual.write_text("Copy only.\n", encoding="utf-8")
            evidence.write_text("SOURCE: alpha\n", encoding="utf-8")
            argv = ["--manual", str(manual), "--evidence", str(evidence), "--sha256", _sha(evidence),
                    "--keys", "quote,line", "--prompt", "copy"]
            with mock.patch.object(olla_evidence.worker, "_generate", return_value=('{"quote":"SOURCE","line":"alpha"}', {})) as gen, \
                    redirect_stdout(io.StringIO()), mock.patch("sys.stderr", io.StringIO()):
                olla_evidence.main(argv)
            schema = gen.call_args.kwargs["fmt"]
            self.assertEqual(["quote", "line"], schema["required"])
            self.assertFalse(schema["additionalProperties"])


class ApplyWorkerTests(unittest.TestCase):
    def _run(self, prompt: str, workspace: str) -> dict:
        out = io.StringIO()
        with redirect_stdout(out):
            apply_worker.main(["-p", prompt, "--add-dir", workspace, "--output-format", "json"])
        return json.loads(out.getvalue())

    def test_dictated_edit_is_applied_without_a_model(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a.py").write_text("x = 1\n", encoding="utf-8")
            prompt = "Set x.\n===EDIT: a.py===\n<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE\n"
            envelope = self._run(prompt, d)
            self.assertEqual("SUCCESS", envelope["status"])
            self.assertEqual({"input_tokens": 0, "output_tokens": 0}, envelope["usage"])
            self.assertEqual("x = 2\n", (Path(d) / "a.py").read_text(encoding="utf-8"))

    def test_prompt_without_blocks_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            envelope = self._run("Please improve a.py", d)
            self.assertEqual("ERROR", envelope["status"])
            self.assertIn("NO_BLOCKS_IN_PROMPT", envelope["error"])

    def test_pilot_end_to_end_records_the_apply_worker_in_the_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / "proj"
            (source / ".coord").mkdir(parents=True)
            (source / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
            (source / "calc.py").write_text("def mul(a, b):\n    return a * b\n", encoding="utf-8")
            prompt = "===FILE: calc.py===\ndef mul(a, b):\n    return a * b\n\n\ndef add(a, b):\n    return a + b\n"
            summary = run_pilot(PilotConfig(
                task_id="AP1", title="apply", prompt=prompt, source_dir=source, work_dir=root / "work",
                agy_command=APPLY, watch_roots=[], print_timeout_s=60,
                accept_cmd=f'"{sys.executable}" -c "import calc; assert calc.add(1, 2) == 3"',
                allowed_scopes=["calc.py"],
            ))
            self.assertEqual(("SUCCEEDED", "PASS"), (summary["state"], summary["verdict_hint"]))
            row = json.loads((source / ".coord" / "usage" / "runs.jsonl").read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(("apply", "deterministic", 0), (row["worker"], row["model"], row["input_tokens"]))


class ScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.source = root / "sample"
        self.source.mkdir()
        (self.source / "calc.py").write_text("def mul(a, b):\n    return a * b\n", encoding="utf-8")
        self.home = root / "home"
        self.home.mkdir()
        self.work = root / "work"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _run(self, allowed: list[str]) -> dict:
        config = PilotConfig(task_id="S1", title="scope", prompt="Add add(a, b) to calc.py.", source_dir=self.source,
                             work_dir=self.work, agy_command=FAKE_AGY, watch_roots=[self.home], print_timeout_s=60,
                             allowed_scopes=allowed)
        with mock.patch.dict(os.environ, {"FAKE_AGY_MODE": "success"}):
            return run_pilot(config)

    def test_change_outside_allow_is_rework_not_promoted(self) -> None:
        summary = self._run(["other.py"])
        self.assertEqual(("REWORK", "SCOPE_VIOLATION", "REJECTED"),
                         (summary["verdict_hint"], summary["error_class"], summary["promotion"]))
        self.assertIn("calc.py", summary["error_detail"])
        self.assertNotIn("def add", (self.source / "calc.py").read_text(encoding="utf-8"))

    def test_change_inside_allow_passes_the_dry_run(self) -> None:
        self.assertEqual("DRY_RUN_PASSED", self._run(["calc.py"])["promotion"])


def _project(d: str) -> Path:
    root = Path(d)
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "config.py").write_text("TIMEOUT = 30\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_config.py").write_text("import pkg.config\n", encoding="utf-8")
    return root


def _manual(root: Path, **overrides) -> str:
    values = dict(work_id="U35_T", worker="local", goal="Replace TIMEOUT = 30 with TIMEOUT = 60 in `pkg/config.py`.",
                  inputs=["pkg/config.py"], allow=["pkg/config.py"], acceptance="python -m unittest tests.test_config",
                  judge="codex")
    values.update(overrides)
    return new_manual(root, **values)


class ManualLintTests(unittest.TestCase):
    def test_generated_manual_passes(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = _project(d)
            report = lint(_manual(root), root)
            self.assertTrue(report.ok, report.errors)
            self.assertEqual(["pkg/config.py"], report.contract["allow"])

    def test_missing_contract_and_fields(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertIn("NO_CONTRACT", lint("just prose", Path(d)).errors[0])
            report = lint("```contract\nwork_id: X\n```\n", Path(d))
            for key in ("worker", "goal", "inputs", "allow", "acceptance", "judge"):
                self.assertIn(f"MISSING:{key}", report.errors)

    def test_inputs_must_be_pinned_to_their_current_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = _project(d)
            text = _manual(root)
            source_sha = _sha(root / "pkg" / "config.py")
            (root / "pkg" / "config.py").write_text("TIMEOUT = 31\n", encoding="utf-8")
            self.assertIn("INPUT_HASH_MISMATCH:pkg/config.py", lint(text, root).errors)
            unpinned = text.replace(f" sha256={source_sha}", "")
            self.assertNotEqual(text, unpinned)
            self.assertIn("INPUT_UNPINNED:pkg/config.py (add sha256=<hex>)", lint(unpinned, root).errors)
            self.assertIn("INPUT_MISSING:pkg/nope.py", lint(text.replace("- pkg/config.py sha", "- pkg/nope.py sha"), root).errors)

    def test_judge_rules(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = _project(d)
            self.assertIn("JUDGE_NOT_ALLOWED:ollama (Ollama and the worker never judge)",
                          lint(_manual(root).replace("judge: codex", "judge: ollama"), root).errors)
            report = lint(_manual(root, worker="agy", judge="antigravity"), root)
            self.assertIn("SELF_JUDGE:antigravity cannot accept work done by --worker agy", report.errors)

    def test_goal_and_scope_rules(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = _project(d)
            self.assertTrue(any(e.startswith("VAGUE_GOAL") for e in lint(_manual(root, goal="improve pkg/config.py"), root).errors))
            self.assertIn("ALLOW_TOO_WIDE:*", lint(_manual(root, allow=["*"]), root).errors)
            self.assertIn("ALLOW_TOO_WIDE:../x.py", lint(_manual(root, allow=["../x.py"]), root).errors)

    def test_worker_rules(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = _project(d)
            self.assertIn("CASCADE_WITHOUT_BUDGET: set remote_budget_tokens or use worker: local",
                          lint(_manual(root, worker="cascade"), root).errors)
            self.assertTrue(lint(_manual(root, worker="cascade", remote_budget_tokens=50000), root).ok)
            self.assertIn("NO_BLOCKS_FOR_APPLY: worker apply needs ===FILE/===EDIT blocks in the manual",
                          lint(_manual(root, worker="apply"), root).errors)
            block = "===EDIT: pkg/other.py===\n<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE\n"
            self.assertIn("BLOCK_OUTSIDE_ALLOW:pkg/other.py", lint(_manual(root, worker="apply") + block, root).errors)
            dictated = _manual(root) + block.replace("other", "config")
            self.assertTrue(any(w.startswith("DICTATION") for w in lint(dictated, root).warnings))

    def test_low_specificity_blocks_a_local_worker(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "notes").write_text("n\n", encoding="utf-8")
            text = (
                "```contract\nwork_id: X\nworker: local\ngoal: handle the notes\n"
                f"inputs:\n- notes sha256={_sha(root / 'notes')}\nallow:\n- notes\n"
                "acceptance: python -m unittest\nforbidden: none\nstop: first failure\njudge: codex\ntimeout_s: 60\n```\n"
            )
            self.assertTrue(any(e.startswith("LOW_SPECIFICITY") for e in lint(text, root).errors))

    def test_related_tests_missing_from_acceptance_is_a_warning(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = _project(d)
            report = lint(_manual(root, acceptance="python -m unittest tests.test_other"), root)
            self.assertTrue(report.ok)
            self.assertIn("RELATED_TESTS_NOT_IN_ACCEPTANCE:tests.test_config", report.warnings)

    def test_comment_needs_two_spaces_so_issue_numbers_survive(self) -> None:
        contract = parse_contract("```contract\ngoal: fix issue #12 in a.py   # note\n```\n")
        self.assertEqual("fix issue #12 in a.py", contract["goal"])


class ManualCliTests(unittest.TestCase):
    def _main(self, argv: list[str]) -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(argv)
        return code, out.getvalue()

    def test_invalid_manual_refuses_before_running(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "m.md").write_text("no contract here", encoding="utf-8")
            with mock.patch("v7_harness.pilot.run_pilot") as run:
                code, out = self._main(["pilot", "run", "--task", "X", "--source", d, "--manual", str(Path(d) / "m.md")])
            self.assertEqual(2, code)
            run.assert_not_called()
            self.assertEqual("MANUAL_INVALID", json.loads(out)["error_class"])

    def test_valid_manual_drives_prompt_acceptance_scope_worker_and_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = _project(d)
            text = _manual(root, worker="apply", timeout_s=90) + "===EDIT: pkg/config.py===\n<<<<<<< SEARCH\nTIMEOUT = 30\n=======\nTIMEOUT = 60\n>>>>>>> REPLACE\n"
            (root / "m.md").write_text(text, encoding="utf-8")
            summary = {"state": "SUCCEEDED", "verdict_hint": "PASS"}
            with mock.patch("v7_harness.pilot.run_pilot", return_value=summary) as run:
                self._main(["pilot", "run", "--task", "U35_T", "--source", d, "--manual", str(root / "m.md")])
            config = run.call_args.args[0]
            self.assertEqual(text, config.prompt)
            self.assertEqual("python -m unittest tests.test_config", config.accept_cmd)
            self.assertEqual(["pkg/config.py"], config.allowed_scopes)
            self.assertEqual(90, config.print_timeout_s)
            self.assertTrue(config.agy_command[-1].endswith("apply_worker.py"))

    def test_only_the_judge_may_approve(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = _project(d)
            (root / "m.md").write_text(_manual(root), encoding="utf-8")
            with mock.patch("v7_harness.pilot.run_pilot") as run:
                code, out = self._main(["pilot", "run", "--task", "U35_T", "--source", d, "--manual", str(root / "m.md"),
                                        "--approve", "b" * 64, "--coord-actor", "antigravity"])
            self.assertEqual(2, code)
            run.assert_not_called()
            self.assertEqual("APPROVER_NOT_JUDGE", json.loads(out)["error_class"])

    def test_cascade_escalation_is_checked_against_the_remote_budget(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = _project(d)
            # B85 (2026-09-25): input + output are counted (input alone undercounted a 655,207-token run), an
            # unreported count is UNKNOWN, and anything but WITHIN blocks the escalated run.
            cases = (({"input_tokens": 500, "output_tokens": 100}, 1000, "WITHIN", "PASS"),
                     ({"input_tokens": 500, "output_tokens": 100}, 100, "EXCEEDED:600>100", "BLOCKED"),
                     ({"input_tokens": 500}, 1000, "UNKNOWN", "BLOCKED"))
            for usage, budget, expected, verdict in cases:
                (root / "m.md").write_text(_manual(root, worker="cascade", remote_budget_tokens=budget), encoding="utf-8")
                first = {"state": "SUCCEEDED", "verdict_hint": "REWORK"}
                second = {"state": "SUCCEEDED", "verdict_hint": "PASS", "agy_usage": usage}
                seen = []  # the CLI reuses one config object, so record the budget at each call

                def fake_run(config, _results=iter([first, second])):
                    seen.append(config.remote_budget_tokens)
                    return next(_results)

                # U110: the paid stage is named on the run; without --escalate-to a failed local result goes to the judge.
                with mock.patch("v7_harness.pilot.run_pilot", side_effect=fake_run):
                    _code, out = self._main(["pilot", "run", "--task", "U35_T", "--source", d, "--manual", str(root / "m.md"),
                                             "--escalate-to", "agy"])
                result = json.loads(out)
                self.assertEqual((expected, verdict), (result["cost_gate"], result["verdict_hint"]))
                self.assertEqual([None, budget], seen)  # the local first stage is free; the paid escalation is gated

    def test_auto_routes_a_dictated_prompt_to_the_apply_worker(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            prompt = "===EDIT: a.py===\n<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE\n"
            with mock.patch("v7_harness.pilot.run_pilot", return_value={"state": "SUCCEEDED", "verdict_hint": "PASS"}) as run:
                _code, out = self._main(["pilot", "run", "--task", "A", "--source", d, "--prompt", prompt, "--worker", "auto"])
            self.assertTrue(run.call_args.args[0].agy_command[-1].endswith("apply_worker.py"))
            self.assertEqual("apply", json.loads(out)["routed_by"]["worker"])

    def test_manual_new_writes_a_manual_that_lints(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = _project(d)
            code, out = self._main(["pilot", "manual", "new", "--out", str(root / "m.md"), "--source", d,
                                    "--work-id", "U35_T", "--worker", "local",
                                    "--goal", "Replace TIMEOUT = 30 with TIMEOUT = 60 in `pkg/config.py`.",
                                    "--input", "pkg/config.py", "--allow", "pkg/config.py",
                                    "--accept", "python -m unittest tests.test_config", "--judge", "codex"])
            self.assertEqual(0, code, out)
            code, _ = self._main(["pilot", "manual", "lint", "--manual", str(root / "m.md"), "--source", d])
            self.assertEqual(0, code)


class GateTests(unittest.TestCase):
    def test_gate_accepts_applied_output_from_a_work_dir_pilot(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            pilot = root / ".work" / "pilot_P08"
            (pilot / "runs" / "P08").mkdir(parents=True)
            (pilot / "stage" / "P08" / "v7_harness").mkdir(parents=True)
            (pilot / "stage" / "P08" / "v7_harness" / "x.py").write_text("A = 1\n", encoding="utf-8")
            (pilot / "runs" / "P08" / "summary.json").write_text(
                json.dumps({"promotion": "APPLIED", "changed_files": ["v7_harness/x.py"]}), encoding="utf-8")
            self.assertEqual([], check({"v7_harness/x.py": b"A = 1\n"}, "feat", discover(root)))
            self.assertEqual(1, len(check({"v7_harness/x.py": b"A = 2\n"}, "feat", discover(root))))


if __name__ == "__main__":
    unittest.main()
