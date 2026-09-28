"""U70: a local model gets a typed task only when that exact model artifact is QUALIFIED for the type.

U67-O1b sent a JSON symbol extraction to qwen2.5-coder:7b; the answer repeated items and missed the format, and each
repeated true item used to count as another pass. The gate now refuses before any Ollama call, the scorer counts a
repeat as a failure, and the parser lists a Python file's symbols without a model.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from v7_harness.cli import main
from v7_harness.manual import lint, new_manual
from v7_harness.model_qualification import EVIDENCE, QUALIFICATION_STORE, _key, local_admission, score_extraction
from v7_harness.symbols import symbols

MODEL = "qwen2.5-coder:7b"
DIGEST = "d" * 64


class Provider:
    name = "ollama"

    def __init__(self, digest: str | None = DIGEST, error: Exception | None = None) -> None:
        self._digest, self._error = digest, error

    def digest(self, model: str) -> str | None:
        if self._error is not None:
            raise self._error
        return self._digest


def _record(root: Path, task_type: str, verdict: str, digest: str = DIGEST) -> None:
    store = root / QUALIFICATION_STORE
    store.mkdir(parents=True, exist_ok=True)
    receipt = {"provider": "ollama", "model": MODEL, "digest": digest}
    entry = {"evidence": EVIDENCE, "provider": "ollama", "model": MODEL, "digest": digest, "task_type": task_type,
             "verdict": verdict, "receipts": [receipt]}
    (store / f"{_key('ollama', MODEL, task_type)}.json").write_text(json.dumps(entry), encoding="utf-8")


class ScoringTests(unittest.TestCase):
    def test_a_repeated_true_item_is_a_failed_item(self) -> None:
        source = "alpha beta"
        once = score_extraction([{"name": "alpha", "quote": "alpha"}, {"name": "beta", "quote": "beta"}], source)
        self.assertEqual({"list_extract": (2, 2), "verbatim_quote": (2, 2)}, once)
        # Before U70 the four copies of "alpha" scored 4/4 and qualified a model that knew one item.
        repeated = score_extraction([{"name": "alpha", "quote": "alpha"}] * 4, source)
        self.assertEqual({"list_extract": (1, 4), "verbatim_quote": (1, 4)}, repeated)


class AdmissionTests(unittest.TestCase):
    def test_only_the_same_qualified_artifact_is_admitted(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            ask = lambda provider, task="list_extract": local_admission(root, model=MODEL, task_type=task,  # noqa: E731
                                                                         provider=provider)
            self.assertEqual("UNQUALIFIED", ask(Provider()))
            _record(root, "list_extract", "QUALIFIED")
            _record(root, "verbatim_quote", "REJECTED")
            self.assertEqual("QUALIFIED", ask(Provider()))
            self.assertEqual("REJECTED", ask(Provider(), "verbatim_quote"))
            self.assertEqual("UNQUALIFIED_DIGEST_CHANGED", ask(Provider("e" * 64)))
            self.assertEqual("UNKNOWN_TASK_TYPE", ask(Provider(), "summarise"))
            # Ollama down or the model not pulled: fail closed, never admit on a guess.
            self.assertEqual("MODEL_NOT_INSTALLED", ask(Provider(None)))
            self.assertEqual("MODEL_NOT_INSTALLED", ask(Provider(error=urllib.error.URLError("refused"))))


class PilotRunGateTests(unittest.TestCase):
    def _manual(self, root: Path, task_type: str) -> Path:
        (root / "notes.md").write_text("alpha beta\n", encoding="utf-8")
        text = new_manual(root, work_id="U70_T", worker="local", goal="List the items in `notes.md`.",
                          inputs=["notes.md"], allow=["notes.md"], acceptance="python -c 1", judge="codex")
        path = root / "m.md"
        path.write_text(text.replace("worker: local\n", f"worker: local\ntask_type: {task_type}\n"), encoding="utf-8")
        return path

    def _run(self, root: Path, task_type: str, provider: Provider, *extra: str) -> tuple[int, str, mock.MagicMock]:
        out = io.StringIO()
        with mock.patch("v7_harness.pilot.run_pilot", return_value={"state": "SUCCEEDED", "verdict_hint": "PASS"}) as run, \
                mock.patch("v7_harness.model_qualification.OllamaProvider", return_value=provider), \
                mock.patch("v7_harness.cli.detect_actor", return_value="codex"), \
                redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = main(["pilot", "run", "--task", "U70_T", "--source", str(root),
                         "--manual", str(self._manual(root, task_type)), *extra])
        return code, out.getvalue(), run

    def test_an_unqualified_model_never_starts(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _record(root, "list_extract", "REJECTED")
            code, out, run = self._run(root, "list_extract", Provider())
            self.assertEqual(2, code)
            run.assert_not_called()
            report = json.loads(out)
            self.assertEqual(("LOCAL_NOT_QUALIFIED", "REJECTED", MODEL),
                             (report["error_class"], report["qualification"], report["model"]))
            code, out, run = self._run(root, "list_extract", Provider(error=urllib.error.URLError("refused")))
            self.assertEqual((2, "MODEL_NOT_INSTALLED"), (code, json.loads(out)["qualification"]))
            run.assert_not_called()

    def test_a_qualified_model_and_an_approval_replay_run(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _record(root, "list_extract", "QUALIFIED")
            code, _, run = self._run(root, "list_extract", Provider())
            run.assert_called_once()
            # --approve replays a saved bundle; no model is called, so no qualification is asked.
            code, _, run = self._run(root, "verbatim_quote", Provider(None), "--approve", "b" * 64)
            run.assert_called_once()

    def test_a_manual_without_a_task_type_is_not_gated(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            out = io.StringIO()
            (root / "notes.md").write_text("alpha\n", encoding="utf-8")
            path = root / "m.md"
            path.write_text(new_manual(root, work_id="U70_N", worker="local", goal="g", inputs=["notes.md"],
                                       allow=["notes.md"], acceptance="python -c 1", judge="codex"), encoding="utf-8")
            with mock.patch("v7_harness.pilot.run_pilot", return_value={"state": "SUCCEEDED"}) as run, \
                    mock.patch("v7_harness.model_qualification.OllamaProvider",
                               side_effect=AssertionError("no task type, no qualification lookup")), \
                    mock.patch("v7_harness.cli.detect_actor", return_value="codex"), \
                    redirect_stdout(out), redirect_stderr(io.StringIO()):
                main(["pilot", "run", "--task", "U70_N", "--source", str(root), "--manual", str(path)])
            run.assert_called_once()

    def test_lint_rejects_an_unknown_task_type(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            report = lint(self._manual(root, "summarise").read_text(encoding="utf-8"), root)
            self.assertTrue(any(e.startswith("UNKNOWN_TASK_TYPE:summarise") for e in report.errors), report.errors)
            report = lint(self._manual(root, "list_extract").read_text(encoding="utf-8"), root)
            self.assertFalse(any("TASK_TYPE" in e for e in report.errors), report.errors)


class SymbolsTests(unittest.TestCase):
    def test_the_parser_lists_symbols_with_lines(self) -> None:
        text = ("LIMIT = 3\nname = 'x'\nclass Box:\n    def open(self):\n        pass\n\n"
                "async def fetch():\n    pass\nTIMEOUT: int = 5\n")
        self.assertEqual([{"kind": "constant", "name": "LIMIT", "line": 1},
                          {"kind": "class", "name": "Box", "line": 3},
                          {"kind": "method", "name": "Box.open", "line": 4},
                          {"kind": "function", "name": "fetch", "line": 7},
                          {"kind": "constant", "name": "TIMEOUT", "line": 9}], symbols(text))

    def test_the_parser_covers_a_real_module_without_duplicates(self) -> None:
        path = Path(__file__).resolve().parents[1] / "v7_harness" / "model_qualification.py"
        names = [row["name"] for row in symbols(path.read_text(encoding="utf-8"))]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue({"score_extraction", "local_admission", "TASK_TYPES", "OllamaProvider.digest"} <= set(names))


if __name__ == "__main__":
    unittest.main()
