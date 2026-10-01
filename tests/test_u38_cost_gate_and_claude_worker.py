"""U38: the remote budget gate for every paid worker (B85) and Claude Code as a formal UAOS worker.

B85 (Codex, 2026-09-25): a direct `worker: agy` run spent 655,207 tokens against a 120,000 budget and still ended
PASS and approvable, because the cost gate lived only in the cascade branch and counted input tokens only.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from v7_harness.cli import main
from v7_harness.manual import lint, new_manual
from v7_harness.pilot import PilotConfig, evaluate_cost_gate, run_pilot

FAKE_WORKER = textwrap.dedent('''
    import argparse, json, os, pathlib, sys
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--prompt", required=True)
    parser.add_argument("--add-dir", dest="workspace", required=True)
    args, _ = parser.parse_known_args()
    (pathlib.Path(args.workspace) / "calc.py").write_text("def add(a, b):\\n    return a + b\\n", encoding="utf-8")
    print(json.dumps({"status": "SUCCESS", "response": "wrote calc.py", "conversation_id": "fake",
                      "usage": json.loads(os.environ["FAKE_USAGE"])}))
''')


def _project(root: Path) -> tuple[Path, list[str]]:
    source = root / "proj"
    (source / ".coord").mkdir(parents=True)
    (source / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
    (source / "calc.py").write_text("def add(a, b):\n    return 0\n", encoding="utf-8")
    worker = root / "fake_worker.py"
    worker.write_text(FAKE_WORKER, encoding="utf-8")
    return source, [sys.executable, str(worker)]


def _run(root: Path, usage: dict, budget: int | None, approve: str | None = None, task: str = "B85_T") -> dict:
    source, command = _project(root) if not (root / "proj").exists() else (root / "proj", [sys.executable, str(root / "fake_worker.py")])
    with mock.patch.dict(os.environ, {"FAKE_USAGE": json.dumps(usage)}):
        return run_pilot(PilotConfig(
            task_id=task, title="cost", prompt="Make add return a + b in calc.py", source_dir=source,
            work_dir=root / "work", agy_command=command, watch_roots=[], print_timeout_s=60,
            accept_cmd=f'"{sys.executable}" -c "import calc; assert calc.add(1, 2) == 3"', allowed_scopes=["calc.py"],
            approve_bundle_id=approve, remote_budget_tokens=budget,
        ))


class CostGateUnitTests(unittest.TestCase):
    def test_every_token_kind_counts(self) -> None:
        usage = {"input_tokens": 602482, "output_tokens": 52725}
        self.assertEqual("EXCEEDED:655207>120000", evaluate_cost_gate(usage, 120000))
        cached = {"input_tokens": 10, "output_tokens": 10, "cache_creation_input_tokens": 50, "cache_read_input_tokens": 40}
        self.assertEqual("EXCEEDED:110>100", evaluate_cost_gate(cached, 100))
        self.assertEqual("WITHIN", evaluate_cost_gate({"input_tokens": 50, "output_tokens": 50}, 100))

    def test_missing_counts_are_unknown_not_zero(self) -> None:
        self.assertEqual("UNKNOWN", evaluate_cost_gate({"input_tokens": 500}, 1000))
        self.assertEqual("UNKNOWN", evaluate_cost_gate({}, 1000))
        self.assertEqual("UNKNOWN", evaluate_cost_gate(None, 1000))
        self.assertEqual("UNKNOWN", evaluate_cost_gate({"input_tokens": True, "output_tokens": 1}, 1000))


class CostGateInThePilotTests(unittest.TestCase):
    """The gate runs inside the pilot, before summary.json and the ledger row are written."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _ledger_row(self) -> dict:
        lines = (self.root / "proj" / ".coord" / "usage" / "runs.jsonl").read_text(encoding="utf-8").splitlines()
        return json.loads(lines[-1])

    def test_a_direct_remote_run_over_budget_is_blocked_and_cannot_be_approved(self) -> None:
        summary = _run(self.root, {"input_tokens": 602482, "output_tokens": 52725}, 120000)
        self.assertEqual(("BLOCKED", "COST_EXCEEDED"), (summary["verdict_hint"], summary["error_class"]))
        self.assertEqual("EXCEEDED:655207>120000", summary["cost_gate"])
        row = self._ledger_row()
        self.assertEqual(("BLOCKED", "COST_EXCEEDED"), (row["outcome"], row["error_class"]))
        approved = _run(self.root, {"input_tokens": 602482, "output_tokens": 52725}, 120000, approve=summary["bundle_id"])
        self.assertEqual("BLOCKED", approved["promotion"])
        self.assertEqual("def add(a, b):\n    return 0\n", (self.root / "proj" / "calc.py").read_text(encoding="utf-8"))

    def test_within_budget_passes_and_records_the_gate(self) -> None:
        summary = _run(self.root, {"input_tokens": 500, "output_tokens": 100}, 120000)
        self.assertEqual(("PASS", "WITHIN"), (summary["verdict_hint"], summary["cost_gate"]))

    def test_unreported_usage_with_a_budget_is_blocked(self) -> None:
        summary = _run(self.root, {"input_tokens": 500}, 120000)
        self.assertEqual(("BLOCKED", "COST_UNKNOWN", "UNKNOWN"),
                         (summary["verdict_hint"], summary["error_class"], summary["cost_gate"]))

    def test_no_budget_keeps_the_old_behavior(self) -> None:
        summary = _run(self.root, {"input_tokens": 0, "output_tokens": 0}, None)
        self.assertEqual("PASS", summary["verdict_hint"])
        self.assertNotIn("cost_gate", summary)


class RemoteBudgetContractTests(unittest.TestCase):
    def _manual(self, root: Path, **overrides) -> str:
        (root / "pkg").mkdir(exist_ok=True)
        (root / "pkg" / "config.py").write_text("TIMEOUT = 30\n", encoding="utf-8")
        values = dict(work_id="U38_T", worker="agy", goal="Replace TIMEOUT = 30 with TIMEOUT = 60 in `pkg/config.py`.",
                      inputs=["pkg/config.py"], allow=["pkg/config.py"], acceptance="python -c \"import pkg.config\"",
                      judge="codex",
                      # U106: a paid worker on code needs a recorded reason; this fixture tests budgets, not routing.
                      paid_reason="fixture exercises the paid worker budget contract")
        values.update(overrides)
        return new_manual(root, **values)

    def test_a_paid_worker_needs_a_budget(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertIn("REMOTE_WITHOUT_BUDGET: worker agy needs remote_budget_tokens > 0",
                          lint(self._manual(root), root).errors)
            self.assertTrue(lint(self._manual(root, remote_budget_tokens=120000), root).ok)
            self.assertFalse(any(e.startswith("REMOTE_WITHOUT_BUDGET")
                                 for e in lint(self._manual(root, worker="local"), root).errors))

    def test_the_cli_hands_the_budget_to_the_pilot(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "m.md").write_text(self._manual(root, remote_budget_tokens=120000), encoding="utf-8")
            with mock.patch("v7_harness.pilot.run_pilot", return_value={"state": "SUCCEEDED", "verdict_hint": "PASS"}) as run, \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                main(["pilot", "run", "--task", "U38_T", "--source", d, "--manual", str(root / "m.md")])
            self.assertEqual(120000, run.call_args.args[0].remote_budget_tokens)
            (root / "m2.md").write_text(self._manual(root, remote_budget_tokens=120000).replace(
                "judge: codex", "judge: codex\nmodel: claude-haiku-4-5-20251001"), encoding="utf-8")
            with mock.patch("v7_harness.pilot.run_pilot", return_value={"state": "SUCCEEDED", "verdict_hint": "PASS"}) as run, \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                main(["pilot", "run", "--task", "U38_T", "--source", d, "--manual", str(root / "m2.md")])
            self.assertEqual("claude-haiku-4-5-20251001", run.call_args.args[0].model)

    def test_an_unidentified_approver_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "m.md").write_text(self._manual(root, remote_budget_tokens=120000), encoding="utf-8")
            out = io.StringIO()
            with mock.patch("v7_harness.pilot.run_pilot") as run, mock.patch("v7_harness.cli.detect_actor", return_value=None), \
                    redirect_stdout(out), redirect_stderr(io.StringIO()):
                code = main(["pilot", "run", "--task", "U38_T", "--source", d, "--manual", str(root / "m.md"),
                             "--approve", "b" * 64])
            self.assertEqual(2, code)
            run.assert_not_called()
            self.assertEqual("APPROVER_UNKNOWN", json.loads(out.getvalue())["error_class"])



# A stand-in for the claude CLI: records its argv, cwd and environment, edits calc.py in worker mode, answers a
# JSON verdict in review mode, and reports usage the way `claude -p --output-format json` does.
FAKE_CLAUDE = textwrap.dedent("""
    import json, os, pathlib, sys
    argv = sys.argv[1:]
    log = pathlib.Path(os.environ["FAKE_CLAUDE_LOG"])
    log.write_text(json.dumps({"argv": argv, "cwd": os.getcwd(),
                               "env": {k: os.environ.get(k) for k in ("CLAUDECODE", "UAOS_WORKER", "ANTHROPIC_BASE_URL")}}))
    tools = argv[argv.index("--tools") + 1]
    if "Edit" in tools:
        pathlib.Path("calc.py").write_text("def add(a, b):\\n    return a + b\\n", encoding="utf-8")
        result = "fixed add"
    else:
        result = json.dumps({"verdict": "REWORK", "counterexamples": ["add(0, 0) path untested"],
                             "evidence_lines": ["calc.py:2 return a + b"]})
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": result, "num_turns": 3,
                      "total_cost_usd": 0.0123, "usage": json.loads(os.environ["FAKE_CLAUDE_USAGE"])}))
""")


class ClaudeWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source, _ = _project(self.root)
        fake = self.root / "fake_claude.py"
        fake.write_text(FAKE_CLAUDE, encoding="utf-8")
        self.log = self.root / "claude_call.json"
        self.env = {"CLAUDE_WORKER_CMD": json.dumps([sys.executable, str(fake)]), "FAKE_CLAUDE_LOG": str(self.log),
                    "CLAUDECODE": "1", "ANTHROPIC_BASE_URL": "http://127.0.0.1:11434"}

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _pilot(self, usage: dict, budget: int, task: str = "U38_W") -> dict:
        from v7_harness.cli import resolve_worker_command

        with mock.patch.dict(os.environ, {**self.env, "FAKE_CLAUDE_USAGE": json.dumps(usage)}):
            return run_pilot(PilotConfig(
                task_id=task, title="claude", prompt="Make add return a + b in calc.py", source_dir=self.source,
                work_dir=self.root / "work", agy_command=[*resolve_worker_command("claude", None), "--max-budget-usd", "0.50"],
                watch_roots=[],
                print_timeout_s=60, accept_cmd=f'"{sys.executable}" -c "import calc; assert calc.add(1, 2) == 3"',
                allowed_scopes=["calc.py"], remote_budget_tokens=budget, model="claude-haiku-4-5-20251001",
            ))

    def test_a_budgeted_claude_run_passes_and_is_recorded_as_claude(self) -> None:
        usage = {"input_tokens": 1200, "output_tokens": 300, "cache_creation_input_tokens": 500, "cache_read_input_tokens": 2000}
        summary = self._pilot(usage, 60000)
        worker = (self.root / "work" / "runs" / "U38_W" / "worker").read_text(encoding="utf-8")
        self.assertEqual(("PASS", "WITHIN", "claude"), (summary["verdict_hint"], summary["cost_gate"], worker))
        row = json.loads((self.source / ".coord" / "usage" / "runs.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(("claude", "claude-haiku-4-5-20251001", 12300, 2000),
                         (row["worker"], row["model"], row["cost_microusd"], row["cache_read_input_tokens"]))

    def test_the_worker_is_fenced(self) -> None:
        self._pilot({"input_tokens": 1, "output_tokens": 1}, 60000)
        call = json.loads(self.log.read_text(encoding="utf-8"))
        argv = call["argv"]
        self.assertNotIn("--bare", argv)  # Codex: --bare cannot use the OAuth (Pro) login on the user's PC
        self.assertEqual(["--safe-mode", "--restricted", "--permission-prompts", "none"],
                         argv[argv.index("--safe-mode"):argv.index("--safe-mode") + 4])
        self.assertEqual("0.50", argv[argv.index("--max-budget-usd") + 1])
        self.assertEqual("Read,Edit,Write,Glob,Grep", argv[argv.index("--tools") + 1])
        for fence in ("Write(tests/**)", "Edit(.coord/**)", "Write(.claude/**)"):
            self.assertIn(fence, argv)
        self.assertEqual("claude-haiku-4-5-20251001", argv[argv.index("--model") + 1])
        # The parent session's marker and lane's local-model redirect do not reach the paid worker.
        self.assertEqual({"CLAUDECODE": None, "UAOS_WORKER": "claude", "ANTHROPIC_BASE_URL": None}, call["env"])
        self.assertNotEqual(Path(call["cwd"]).resolve(), self.source.resolve())

    def test_cache_tokens_count_against_the_budget(self) -> None:
        usage = {"input_tokens": 100, "output_tokens": 100, "cache_read_input_tokens": 900}
        summary = self._pilot(usage, 1000)
        self.assertEqual(("BLOCKED", "COST_EXCEEDED", "EXCEEDED:1100>1000"),
                         (summary["verdict_hint"], summary["error_class"], summary["cost_gate"]))

    def test_a_non_ollama_base_url_is_kept(self) -> None:
        from v7_harness.adapters.claude_worker import worker_env

        env = worker_env({"ANTHROPIC_BASE_URL": "https://proxy.example/v1", "CLAUDE_PROJECT_DIR": "/x"})
        self.assertEqual("https://proxy.example/v1", env["ANTHROPIC_BASE_URL"])
        self.assertNotIn("CLAUDE_PROJECT_DIR", env)

    def test_review_is_read_only_advisory_and_never_by_the_author(self) -> None:
        from v7_harness.review import ReviewRefused, run_review

        manual = "```contract\nwork_id: U38_R\n```\n"
        with mock.patch.dict(os.environ, {"FAKE_USAGE": json.dumps({"input_tokens": 10, "output_tokens": 5})}):
            _run(self.root, {"input_tokens": 10, "output_tokens": 5}, None, task="U38_R")  # an agy-labelled bundle
        with mock.patch.dict(os.environ, {**self.env, "FAKE_CLAUDE_USAGE": json.dumps({"input_tokens": 800, "output_tokens": 90})}):
            with self.assertRaises(ReviewRefused):
                run_review(task_id="U38_R", work_dir=self.root / "work", source=self.source, manual_text=manual,
                           reviewer="claude", budget=0, budget_usd=0.25)
            record = run_review(task_id="U38_R", work_dir=self.root / "work", source=self.source, manual_text=manual,
                                reviewer="claude", budget=5000, budget_usd=0.25)
        self.assertEqual((True, "REWORK", "custom", "WITHIN"),
                         (record["advisory"], record["verdict"], record["author_worker"], record["cost_gate"]))
        argv = json.loads(self.log.read_text(encoding="utf-8"))["argv"]
        self.assertEqual("Read,Glob,Grep", argv[argv.index("--tools") + 1])
        for denied in ("Edit", "Write", "Bash"):
            self.assertIn(denied, argv[argv.index("--disallowedTools") + 1:])
        self.assertIn("```diff", argv[argv.index("-p") + 1])
        self.assertEqual("0.25", argv[argv.index("--max-budget-usd") + 1])
        rows = [json.loads(line) for line in (self.source / ".coord" / "usage" / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(("review", "U38_R-review-claude"), (rows[-1]["kind"], rows[-1]["work_id"]))
        # A claude-built bundle is not reviewed by claude.
        self._pilot({"input_tokens": 1, "output_tokens": 1}, 60000, task="U38_SELF")
        with mock.patch.dict(os.environ, self.env), self.assertRaises(ReviewRefused) as caught:
            run_review(task_id="U38_SELF", work_dir=self.root / "work", source=self.source, manual_text=manual,
                       reviewer="claude", budget=5000, budget_usd=0.25)
        self.assertIn("REVIEWER_IS_AUTHOR", str(caught.exception))
        (self.root / "work" / "runs" / "U38_R" / "worker").unlink()
        with mock.patch.dict(os.environ, self.env), self.assertRaises(ReviewRefused) as caught:
            run_review(task_id="U38_R", work_dir=self.root / "work", source=self.source, manual_text=manual,
                       reviewer="claude", budget=5000, budget_usd=0.25)
        self.assertIn("AUTHOR_UNKNOWN", str(caught.exception))


class ClaudeMembershipTests(unittest.TestCase):
    def test_contract_rules_for_a_claude_worker(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            helper = RemoteBudgetContractTests()
            capped = lambda text: text.replace("judge: ", "remote_budget_usd: 0.50\njudge: ", 1)  # noqa: E731
            self.assertIn("SELF_JUDGE:claude cannot accept work done by --worker claude",
                          lint(capped(helper._manual(root, worker="claude", judge="claude", remote_budget_tokens=60000)), root).errors)
            self.assertIn("REMOTE_WITHOUT_BUDGET: worker claude needs remote_budget_tokens > 0",
                          lint(capped(helper._manual(root, worker="claude")), root).errors)
            self.assertTrue(lint(capped(helper._manual(root, worker="claude", remote_budget_tokens=60000)), root).ok)

    def test_a_limited_claude_is_not_sent_to_work(self) -> None:
        from v7_harness.coord.presence import mark

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "m.md").write_text(RemoteBudgetContractTests()._manual(root, worker="claude", remote_budget_tokens=60000)
                                       .replace("judge: ", "remote_budget_usd: 0.50\njudge: ", 1), encoding="utf-8")
            mark(root, "claude", "LIMITED")
            out = io.StringIO()
            with mock.patch("v7_harness.pilot.run_pilot") as run, redirect_stdout(out), redirect_stderr(io.StringIO()):
                code = main(["pilot", "run", "--task", "U38_T", "--source", d, "--manual", str(root / "m.md")])
            self.assertEqual((2, "CLAUDE_LIMITED"), (code, json.loads(out.getvalue())["error_class"]))
            run.assert_not_called()

    def test_worker_labels(self) -> None:
        from v7_harness.pilot import worker_label

        self.assertEqual(["claude", "lane", "apply", "ollama", "custom"],
                         [worker_label(["py", f"x/{name}"]) for name in
                          ("claude_worker.py", "lane_worker.py", "apply_worker.py", "ollama_worker.py", "fake_worker.py")])
        # Only the real agy binary counts as the paid Antigravity worker (a stand-in is "custom").
        self.assertEqual(["agy", "agy", "custom"], [worker_label([c]) for c in ("agy", "C:/bin/agy.cmd", "x/py")])

    def test_p1_reaches_claude_only_while_codex_is_away(self) -> None:
        from v7_harness.coord.hook_context import p1_line
        from v7_harness.coord.mailbox import Mailbox
        from v7_harness.coord.presence import mark

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".coord" / "mailbox").mkdir(parents=True)
            (root / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
            self.assertEqual("", p1_line(root, {"codex": {"state": "UNKNOWN"}}))
            Mailbox(root / ".coord" / "mailbox").publish("wake_abc", {"wake_reason": "STALE_LOCK: PID_DEAD"})
            self.assertIn("STALE_LOCK: PID_DEAD", p1_line(root, {"codex": {"state": "UNKNOWN"}}))
            self.assertEqual("", p1_line(root, {"codex": {"state": "ACTIVE"}}))
            mark(root, "codex", "ACTIVE")
            out = io.StringIO()
            with redirect_stdout(out), mock.patch("v7_harness.coord.hook_context.read_stdin", return_value="{}"), \
                    mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": ""}):
                main(["coord", "presence", "--tool", "claude", "--state", "ACTIVE", "--from-hook", "--project", d, "--say", "p1"])
            self.assertEqual("", out.getvalue())

    def test_hooks_inside_a_worker_write_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".coord").mkdir()
            (Path(d) / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
            with redirect_stdout(io.StringIO()), mock.patch.dict(os.environ, {"UAOS_WORKER": "claude"}), \
                    mock.patch("v7_harness.coord.hook_context.read_stdin", return_value="{}"):
                self.assertEqual(0, main(["coord", "presence", "--tool", "claude", "--state", "ACTIVE", "--from-hook",
                                          "--project", d]))
            self.assertFalse((Path(d) / ".coord" / "presence").exists())


class CodexReworkTests(unittest.TestCase):
    """Codex audit of 1d9bcc0/dc474aa (2026-09-25): the no-manual bypass, --bare on a subscription host, no dollar
    cap, and the U39 route. Each test here failed before the rework."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _cli(self, argv: list[str]) -> tuple[int, dict, mock.MagicMock]:
        out = io.StringIO()
        with mock.patch("v7_harness.pilot.run_pilot", return_value={"state": "SUCCEEDED", "verdict_hint": "PASS"}) as run, \
                redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = main(argv)
        text = out.getvalue().strip()
        return code, (json.loads(text) if text.startswith("{") else {}), run

    def test_a_paid_worker_without_a_manual_is_refused(self) -> None:
        prompt = self.root / "p.txt"
        prompt.write_text("fix x", encoding="utf-8")
        for worker in ("agy", "claude"):
            for source in (["--prompt", "fix x"], ["--prompt-file", str(prompt)]):
                for extra in ([], ["--approve", "b" * 64]):
                    code, out, run = self._cli(["pilot", "run", "--task", "T", "--source", str(self.root), "--worker", worker,
                                                *source, *extra])
                    self.assertEqual((2, "REMOTE_WITHOUT_MANUAL"), (code, out.get("error_class")), (worker, source, extra))
                    run.assert_not_called()

    def test_cascade_without_a_manual_does_not_escalate_to_a_paid_worker(self) -> None:
        calls = []

        def fake_run(config):
            calls.append(config.task_id)
            return {"task_id": config.task_id, "state": "SUCCEEDED", "verdict_hint": "REWORK"}

        out = io.StringIO()
        with mock.patch("v7_harness.pilot.run_pilot", fake_run), redirect_stdout(out), redirect_stderr(io.StringIO()):
            main(["pilot", "run", "--task", "C1", "--source", str(self.root), "--prompt", "fix x", "--worker", "cascade"])
        self.assertEqual(["C1"], calls)
        self.assertEqual("REFUSED:REMOTE_WITHOUT_MANUAL", json.loads(out.getvalue())["escalation"])

    def test_approval_needs_a_persisted_within_gate_whatever_the_flags(self) -> None:
        # A paid run recorded without a budget, then approved while claiming another worker, must not promote.
        source, command = _project(self.root)
        agy = self.root / "agy"
        agy.write_text("", encoding="utf-8")
        with mock.patch.dict(os.environ, {"FAKE_USAGE": json.dumps({"input_tokens": 10, "output_tokens": 5})}):
            first = run_pilot(PilotConfig(task_id="AP", title="t", prompt="Make add return a + b in calc.py",
                                          source_dir=source, work_dir=self.root / "work", agy_command=command,
                                          watch_roots=[], print_timeout_s=60, allowed_scopes=["calc.py"],
                                          accept_cmd=f'"{sys.executable}" -c "import calc; assert calc.add(1, 2) == 3"'))
        (self.root / "work" / "runs" / "AP" / "worker").write_text("agy", encoding="utf-8")
        with mock.patch.dict(os.environ, {"FAKE_USAGE": json.dumps({"input_tokens": 10, "output_tokens": 5})}):
            second = run_pilot(PilotConfig(task_id="AP", title="t", prompt="Make add return a + b in calc.py",
                                           source_dir=source, work_dir=self.root / "work", agy_command=command,
                                           watch_roots=[], print_timeout_s=60, allowed_scopes=["calc.py"],
                                           approve_bundle_id=first["bundle_id"],
                                           accept_cmd=f'"{sys.executable}" -c "import calc; assert calc.add(1, 2) == 3"'))
        self.assertEqual("BLOCKED", second["promotion"])
        self.assertEqual("def add(a, b):\n    return 0\n", (source / "calc.py").read_text(encoding="utf-8"))

    def test_the_claude_worker_runs_in_safe_restricted_mode_with_a_dollar_cap(self) -> None:
        from v7_harness.adapters.claude_worker import review_command, worker_command

        for argv in (worker_command("p", "haiku", 0.5), review_command("p", "haiku", 0.25)):
            self.assertNotIn("--bare", argv)  # --bare never reads OAuth; a Pro/claude.ai login cannot authenticate
            for flag in ("--safe-mode", "--restricted"):
                self.assertIn(flag, argv)
            self.assertEqual("none", argv[argv.index("--permission-prompts") + 1])
            self.assertGreater(float(argv[argv.index("--max-budget-usd") + 1]), 0)

    def test_the_claude_worker_refuses_to_start_without_a_dollar_cap(self) -> None:
        from v7_harness.adapters import claude_worker

        out = io.StringIO()
        with mock.patch("subprocess.run") as run, redirect_stdout(out):
            code = claude_worker.main(["-p", "x", "--add-dir", str(self.root)])
        self.assertEqual(1, code)
        run.assert_not_called()
        self.assertIn("NO_USD_CAP", json.loads(out.getvalue())["error"])

    def test_a_claude_contract_needs_a_dollar_cap_and_passes_it_to_the_worker(self) -> None:
        helper = RemoteBudgetContractTests()
        text = helper._manual(self.root, worker="claude", remote_budget_tokens=60000)
        self.assertIn("REMOTE_WITHOUT_USD_CAP: worker claude needs remote_budget_usd > 0", lint(text, self.root).errors)
        capped = text.replace("judge: codex", "judge: codex\nremote_budget_usd: 0.50")
        self.assertTrue(lint(capped, self.root).ok, lint(capped, self.root).errors)
        (self.root / "m.md").write_text(capped, encoding="utf-8")
        _code, _out, run = self._cli(["pilot", "run", "--task", "U38_T", "--source", str(self.root),
                                      "--manual", str(self.root / "m.md")])
        command = run.call_args.args[0].agy_command
        self.assertEqual("0.50", command[command.index("--max-budget-usd") + 1])

    def test_a_paid_review_needs_a_dollar_cap(self) -> None:
        from v7_harness.review import ReviewRefused, run_review

        with self.assertRaises(ReviewRefused) as caught:
            run_review(task_id="X", work_dir=self.root, source=self.root, manual_text="", reviewer="claude",
                       budget=5000, budget_usd=0)
        self.assertIn("REVIEW_WITHOUT_USD_CAP", str(caught.exception))


class U39RouteTests(unittest.TestCase):
    """docs/41 §5: deterministic → Ollama once → Antigravity once → verdict; an Ollama semantic failure never loops."""

    def test_state_machine(self) -> None:
        from v7_harness.routing import next_route

        self.assertEqual("done", next_route("local", None, local_attempts=1, local_tokens=3000))
        self.assertEqual("local_retry", next_route("local", "FORMAT_ONLY", local_attempts=1, local_tokens=3000))
        self.assertEqual("remote", next_route("local", "FORMAT_ONLY", local_attempts=1, local_tokens=12000))
        for failure in ("SEMANTIC", "UNSUPPORTED", "SCOPE", "TOOL_LIMIT", "JUDGMENT_REQUIRED"):
            self.assertEqual("remote", next_route("local", failure, local_attempts=1, local_tokens=100), failure)
        self.assertEqual("remote", next_route("local_retry", "FORMAT_ONLY", local_attempts=2, local_tokens=5000))
        self.assertEqual("split", next_route("remote", "SEMANTIC", local_attempts=2, local_tokens=5000))
        self.assertEqual("stop", next_route("local", "ENVIRONMENT", local_attempts=1, local_tokens=0))

    def test_failure_classes(self) -> None:
        from v7_harness.routing import classify_failure

        self.assertIsNone(classify_failure({"verdict_hint": "PASS"}))
        self.assertEqual("SEMANTIC", classify_failure({"verdict_hint": "REWORK"}))
        self.assertEqual("SCOPE", classify_failure({"verdict_hint": "REWORK", "error_class": "SCOPE_VIOLATION"}))
        self.assertEqual("FORMAT_ONLY", classify_failure({"verdict_hint": "BLOCKED", "error_class": "PROVIDER_ERROR",
                                                         "error_detail": "model returned no file block"}))
        self.assertEqual("TOOL_LIMIT", classify_failure({"verdict_hint": "BLOCKED", "error_class": "PROVIDER_ERROR",
                                                        "error_detail": "PROMPT_TOO_LARGE: ~9000 tokens > 8000"}))
        self.assertEqual("ENVIRONMENT", classify_failure({"verdict_hint": "BLOCKED", "error_class": "ACCEPT_INFRA"}))

    def test_a_semantic_local_failure_never_gets_a_second_local_attempt(self) -> None:
        calls = []

        def fake_run(config):
            calls.append(config.agy_command[-1])
            return {"task_id": config.task_id, "state": "SUCCEEDED", "verdict_hint": "REWORK",
                    "agy_usage": {"input_tokens": 100, "output_tokens": 50}}

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            helper = RemoteBudgetContractTests()
            (root / "m.md").write_text(helper._manual(root, work_id="R1", worker="cascade", remote_budget_tokens=120000), encoding="utf-8")
            out = io.StringIO()
            with mock.patch("v7_harness.pilot.run_pilot", fake_run), redirect_stdout(out), redirect_stderr(io.StringIO()):
                # U110: the paid stage is named on the run; without it the failed local result is held for the judge.
                main(["pilot", "run", "--task", "R1", "--source", d, "--manual", str(root / "m.md"), "--escalate-to", "agy"])
        self.assertEqual(2, len(calls))
        self.assertTrue(calls[0].endswith("ollama_worker.py"))
        self.assertEqual("agy", calls[1])
        self.assertEqual(["local:SEMANTIC", "remote:SEMANTIC", "split"], json.loads(out.getvalue())["route"])

    def test_a_format_failure_gets_exactly_one_local_retry(self) -> None:
        calls = []
        results = iter([
            {"state": "FAILED", "verdict_hint": "BLOCKED", "error_class": "PROVIDER_ERROR",
             "error_detail": "model returned no file block", "agy_usage": {"input_tokens": 3000, "output_tokens": 200}},
            {"state": "SUCCEEDED", "verdict_hint": "PASS", "agy_usage": {"input_tokens": 3000, "output_tokens": 300}},
        ])

        def fake_run(config):
            calls.append(config.task_id)
            return {"task_id": config.task_id, **next(results)}

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "m.md").write_text(RemoteBudgetContractTests()._manual(root, work_id="R2", worker="cascade", remote_budget_tokens=120000),
                                       encoding="utf-8")
            out = io.StringIO()
            with mock.patch("v7_harness.pilot.run_pilot", fake_run), redirect_stdout(out), redirect_stderr(io.StringIO()):
                main(["pilot", "run", "--task", "R2", "--source", d, "--manual", str(root / "m.md")])
        self.assertEqual(["R2", "R2-retry"], calls)
        self.assertEqual(["local:FORMAT_ONLY", "local_retry:PASS"], json.loads(out.getvalue())["route"])

if __name__ == "__main__":
    unittest.main()
