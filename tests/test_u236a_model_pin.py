"""U236a: an opt-in exact-model guard for the Claude worker (judge-owned fixed acceptance).

A contract that says `model_pin: exact` and names a full model id must run on exactly that model or fail closed: the
worker compares the CLI result's `modelUsage` keys with `--require-model`. Without the opt-in nothing changes.
Written by Claude acting for the absent judge (codex) before any worker ran; marked for Codex re-review. No paid call:
the claude CLI is a fake (CLAUDE_WORKER_CMD).
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

from v7_harness.adapters import claude_worker
from v7_harness.cli import main
from v7_harness.manual import lint, new_manual

# Edits calc.py like a real worker would, then reports modelUsage from FAKE_MODEL_USAGE ("absent" leaves it out).
FAKE_CLAUDE = textwrap.dedent("""
    import json, os, pathlib
    pathlib.Path("calc.py").write_text("def add(a, b):\\n    return a + b\\n", encoding="utf-8")
    out = {"type": "result", "subtype": "success", "is_error": False, "result": "fixed add", "num_turns": 2,
           "total_cost_usd": 0.01, "usage": {"input_tokens": 10, "output_tokens": 5}}
    raw = os.environ["FAKE_MODEL_USAGE"]
    if raw != "absent":
        out["modelUsage"] = json.loads(raw)
    print(json.dumps(out))
""")

PINNED = "claude-haiku-5-5"
ONE = {"inputTokens": 10, "outputTokens": 5}


class WorkerGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        fake = self.root / "fake_claude.py"
        fake.write_text(FAKE_CLAUDE, encoding="utf-8")
        self.workspace = self.root / "ws"
        self.workspace.mkdir()
        self.env = {"CLAUDE_WORKER_CMD": json.dumps([sys.executable, str(fake)])}

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _run(self, model_usage, model: str, require: str | None) -> tuple[int, dict]:
        argv = ["-p", "fix add", "--add-dir", str(self.workspace), "--model", model, "--max-budget-usd", "0.10"]
        if require is not None:
            argv += ["--require-model", require]
        raw = "absent" if model_usage is None else json.dumps(model_usage)
        out = io.StringIO()
        with mock.patch.dict(os.environ, {**self.env, "FAKE_MODEL_USAGE": raw}), redirect_stdout(out):
            code = claude_worker.main(argv)
        return code, json.loads(out.getvalue().strip().splitlines()[-1])

    def _assert_mismatch(self, code: int, env: dict) -> None:
        self.assertEqual(1, code)
        self.assertNotEqual("SUCCESS", env["status"])
        self.assertTrue(env["error"].startswith(f"MODEL_MISMATCH: expected {PINNED}"), env["error"])

    def test_1_pinned_model_matches(self) -> None:
        code, env = self._run({PINNED: ONE}, PINNED, PINNED)
        self.assertEqual((0, "SUCCESS"), (code, env["status"]))
        self.assertEqual([PINNED], env["resolved_models"])
        self.assertNotIn("resolved_models", env["usage"])
        self.assertTrue(all(isinstance(v, int) and not isinstance(v, bool) for v in env["usage"].values()))

    def test_2_other_model_fails_closed(self) -> None:
        self._assert_mismatch(*self._run({"claude-sonnet-5-5": ONE}, PINNED, PINNED))

    def test_3_missing_model_usage_fails_closed(self) -> None:
        self._assert_mismatch(*self._run(None, PINNED, PINNED))
        self._assert_mismatch(*self._run({}, PINNED, PINNED))

    def test_4_extra_model_fails_closed(self) -> None:
        self._assert_mismatch(*self._run({PINNED: ONE, "claude-sonnet-5-5": ONE}, PINNED, PINNED))

    def test_5_no_opt_in_keeps_legacy_behavior(self) -> None:
        code, env = self._run(None, "sonnet", None)
        self.assertEqual((0, "SUCCESS", ""), (code, env["status"], env["error"]))
        self.assertNotIn("resolved_models", env)
        code, env = self._run({"claude-sonnet-5-5": ONE}, "sonnet", None)
        self.assertEqual((0, "SUCCESS"), (code, env["status"]))
        self.assertNotIn("resolved_models", env)


def _manual(root: Path, extra: str = "", usd: str | None = "0.20") -> str:
    (root / "pkg").mkdir(exist_ok=True)
    (root / "pkg" / "config.py").write_text("TIMEOUT = 30\n", encoding="utf-8")
    values = dict(work_id="U236A_T", worker="claude", goal="Replace TIMEOUT = 30 with TIMEOUT = 60 in `pkg/config.py`.",
                  inputs=["pkg/config.py"], allow=["pkg/config.py"], acceptance="python -c \"import pkg.config\"",
                  judge="codex", remote_budget_tokens=60000,
                  paid_reason="fixture exercises the exact-model guard contract")
    text = new_manual(root, **values)
    if usd is not None:
        extra = f"remote_budget_usd: {usd}\n" + extra
    return text.replace("judge: codex", "judge: codex\n" + extra.rstrip("\n")) if extra else text


class LintTests(unittest.TestCase):
    def _errors(self, extra: str, usd: str | None = "0.20") -> list[str]:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            return lint(_manual(root, extra, usd), root).errors

    def test_6_alias_needs_full_id_only_with_opt_in(self) -> None:
        alias = [e for e in self._errors("model_pin: exact\nmodel: haiku\n") if e.startswith("MODEL_ALIAS")]
        self.assertEqual(["MODEL_ALIAS: model_pin exact needs a full model id"], alias)
        self.assertTrue(any(e.startswith("MODEL_ALIAS") for e in self._errors("model_pin: exact\n")))
        self.assertFalse(any(e.startswith("MODEL_ALIAS") for e in self._errors("model: haiku\n")))
        self.assertFalse(any(e.startswith("MODEL_ALIAS") for e in self._errors(f"model_pin: exact\nmodel: {PINNED}\n")))
        self.assertIn("REMOTE_WITHOUT_USD_CAP: worker claude needs remote_budget_usd > 0",
                      self._errors(f"model_pin: exact\nmodel: {PINNED}\n", usd=None))


class CliWiringTests(unittest.TestCase):
    def _command(self, extra: str, worker: str = "claude") -> list[str]:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            text = _manual(root, extra)
            if worker != "claude":
                text = text.replace("worker: claude", f"worker: {worker}")
            (root / "m.md").write_text(text, encoding="utf-8")
            with mock.patch("v7_harness.pilot.run_pilot", return_value={"state": "SUCCEEDED", "verdict_hint": "PASS"}) as run, \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                main(["pilot", "run", "--task", "U236A_T", "--source", d, "--manual", str(root / "m.md")])
            run.assert_called_once()
            return list(run.call_args.args[0].agy_command)

    def test_7_cli_passes_require_model_only_with_opt_in(self) -> None:
        argv = self._command(f"model_pin: exact\nmodel: {PINNED}\n")
        self.assertEqual(PINNED, argv[argv.index("--require-model") + 1])
        self.assertNotIn("--require-model", self._command(f"model: {PINNED}\n"))


if __name__ == "__main__":
    unittest.main()
