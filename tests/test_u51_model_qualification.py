"""U51: task-specific model qualification gate bound to execution provenance (docs/49 §5 U-MQ-1)."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path

from v7_harness import model_qualification as mq

# Static synthetic fixture: used only to test the scorer (Codex U51-R1b verdict). The 12 private articles behind
# docs/49's 60/67 and 32/67 stay local evidence only and are not part of this gate.
FIXTURE = Path(__file__).parent / "fixtures"
PATTERN = "u51_art*.json"
SOURCES = sorted(FIXTURE.glob("u51_synthetic_*.md"))


def _fixture_outputs() -> dict[str, str]:
    """Source file name -> the saved answer for it, replayed by the fake provider as if the model produced it."""
    outputs = {}
    for path in sorted(FIXTURE.glob(PATTERN)):
        run = json.loads(path.read_text(encoding="utf-8"))
        outputs[run["meta"]["file"]] = json.dumps(run["data"], ensure_ascii=False)
    return outputs


class FakeProvider:
    """No network. Answers each prompt with the saved output of the source it contains; digests come from a queue so a
    test can swap the model mid-run."""

    name = "ollama"

    def __init__(self, digests: list[str | None], outputs: dict[str, str] | None = None) -> None:
        self.digests = list(digests)
        self.outputs = outputs if outputs is not None else _fixture_outputs()
        self.calls = 0

    def digest(self, model: str) -> str | None:
        return self.digests.pop(0) if len(self.digests) > 1 else self.digests[0]

    def generate(self, model: str, prompt: str) -> tuple[str, dict[str, int]]:
        self.calls += 1
        for name, output in self.outputs.items():
            text = (FIXTURE / name).read_text(encoding="utf-8")
            if text in prompt:
                return output, {"input_tokens": len(prompt) // 3, "output_tokens": len(output) // 3}
        return "not json", {"input_tokens": 0, "output_tokens": 0}


def _status(store: Path, digest: str, model: str = "m") -> dict[str, str]:
    return {t: mq.lookup(store, provider="ollama", model=model, digest=digest, task_type=t) for t in mq.TASK_TYPES}


class ScoreTest(unittest.TestCase):
    def test_literal_name_and_quote_pass_paraphrase_fails(self) -> None:
        source = "Intro.\nC09 — Tool Firewall keeps   execution separate.\n"
        cands = [{"name": "C09 — Tool Firewall", "quote": "keeps execution separate"},
                 {"name": "Invented idea", "quote": "separates execution"}]
        self.assertEqual(mq.score_extraction(cands, source),
                         {"list_extract": (1, 2), "verbatim_quote": (1, 2)})

    def test_candidate_key_drops_model_explanation(self) -> None:
        self.assertEqual(mq.candidate_key("UAOS-C09 — Firewall"), "UAOS-C09")
        self.assertEqual(mq.candidate_key("Name :: detail"), "Name")

    def test_verdict_thresholds(self) -> None:
        self.assertEqual(mq.verdict(16, 20), "QUALIFIED")
        self.assertEqual(mq.verdict(15, 20), "REJECTED")
        self.assertEqual(mq.verdict(5, 5), "UNQUALIFIED")  # too few items to say anything

    def test_unparseable_answer_fails_items_instead_of_vanishing(self) -> None:
        self.assertEqual(mq.score_output("not json", "x"),
                         {t: (0, mq.MAX_CANDIDATES) for t in mq.TASK_TYPES})

    def test_changed_source_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runs, src = Path(tmp) / "runs", Path(tmp) / "src"
            runs.mkdir(), src.mkdir()
            (src / "a.md").write_text("edited", encoding="utf-8")
            (runs / "art01.json").write_text(json.dumps(
                {"meta": {"file": "a.md", "sha256": hashlib.sha256(b"original").hexdigest()}, "data": {}}),
                encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SOURCE_HASH_MISMATCH"):
                mq.score_fixture(runs, src)

    def test_scorer_splits_the_two_task_types_and_names_no_model(self) -> None:
        result = mq.score_fixture(FIXTURE, FIXTURE, PATTERN)
        self.assertEqual(result["evidence"], "SCORER_ONLY")
        self.assertEqual(result["items"], 3)
        self.assertEqual(result["tasks"]["list_extract"], {"passed": 21, "total": 24, "verdict": "QUALIFIED"})
        self.assertEqual(result["tasks"]["verbatim_quote"], {"passed": 12, "total": 24, "verdict": "REJECTED"})


class ForgedIdentityTest(unittest.TestCase):
    """Codex U51-R1b counterexample. Red on U51-R1b: this exact command exited 0 and wrote QUALIFIED."""

    def test_codex_forged_command_is_refused_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["score", "--runs", str(FIXTURE), "--sources", str(FIXTURE), "--pattern", PATTERN,
                    "--provider", "ollama", "--model", "never-ran-model", "--digest", "fabricated-digest",
                    "--record", tmp]
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                mq.main(argv)
            self.assertNotEqual(caught.exception.code, 0)
            self.assertEqual(list(Path(tmp).iterdir()), [])
            self.assertEqual(_status(Path(tmp), "fabricated-digest", "never-ran-model"),
                             {t: "UNQUALIFIED" for t in mq.TASK_TYPES})

    def test_score_without_identity_prints_and_records_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as out:
            code = mq.main(["score", "--runs", str(FIXTURE), "--sources", str(FIXTURE), "--pattern", PATTERN])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out.getvalue())["evidence"], "SCORER_ONLY")
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_hand_made_record_without_receipts_is_not_trusted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # What U51-R1b's `score --record` wrote: a verdict with a typed digest and nothing that shows a call.
            (Path(tmp) / "ollama__never-ran-model__list_extract.json").write_text(json.dumps(
                {"provider": "ollama", "model": "never-ran-model", "digest": "fabricated-digest",
                 "task_type": "list_extract", "passed": 21, "total": 24, "verdict": "QUALIFIED"}), encoding="utf-8")
            self.assertEqual(mq.lookup(Path(tmp), provider="ollama", model="never-ran-model",
                                       digest="fabricated-digest", task_type="list_extract"), "UNQUALIFIED")

    def test_typed_digest_that_the_provider_does_not_report_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provider = FakeProvider(["sha256:real"])
            with self.assertRaisesRegex(ValueError, "IDENTITY_MISMATCH"):
                mq.qualify(Path(tmp), provider, "m", SOURCES, expect_digest="fabricated-digest")
            self.assertEqual(provider.calls, 0)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_model_the_provider_does_not_have_never_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provider = FakeProvider([None])
            with self.assertRaisesRegex(ValueError, "MODEL_NOT_INSTALLED"):
                mq.qualify(Path(tmp), provider, "never-ran-model", SOURCES)
            self.assertEqual(list(Path(tmp).iterdir()), [])


class ProvenanceTest(unittest.TestCase):
    def test_qualify_records_receipts_from_its_own_calls(self) -> None:
        self.assertEqual(len(SOURCES), 3)
        with tempfile.TemporaryDirectory() as tmp:
            provider = FakeProvider(["sha256:real"])
            result = mq.qualify(Path(tmp), provider, "m", SOURCES, expect_digest="sha256:real")
            self.assertEqual(provider.calls, 3)
            self.assertEqual(result["tasks"]["list_extract"], {"passed": 21, "total": 24, "verdict": "QUALIFIED"})
            self.assertEqual(result["tasks"]["verbatim_quote"], {"passed": 12, "total": 24, "verdict": "REJECTED"})
            self.assertEqual(_status(Path(tmp), "sha256:real"),
                             {"list_extract": "QUALIFIED", "verbatim_quote": "REJECTED"})
            entry = json.loads((Path(tmp) / "ollama__m__list_extract.json").read_text(encoding="utf-8"))
            outputs = _fixture_outputs()
            for receipt in entry["receipts"]:
                text = (FIXTURE / receipt["source_file"]).read_text(encoding="utf-8")
                self.assertEqual(receipt["digest"], "sha256:real")
                self.assertEqual(receipt["source_sha256"], hashlib.sha256(text.encode("utf-8")).hexdigest())
                self.assertEqual(receipt["output_sha256"],
                                 hashlib.sha256(outputs[receipt["source_file"]].encode("utf-8")).hexdigest())

    def test_new_digest_does_not_inherit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mq.qualify(Path(tmp), FakeProvider(["sha256:a"]), "m", SOURCES)
            self.assertEqual(_status(Path(tmp), "sha256:b"),
                             {t: "UNQUALIFIED_DIGEST_CHANGED" for t in mq.TASK_TYPES})

    def test_model_swapped_during_the_run_records_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "DIGEST_CHANGED_DURING_RUN"):
                mq.qualify(Path(tmp), FakeProvider(["sha256:a", "sha256:b"]), "m", SOURCES)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_unknown_model_is_unqualified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(_status(Path(tmp), "d", "x"), {t: "UNQUALIFIED" for t in mq.TASK_TYPES})

    def test_parallel_qualify_runs_leave_whole_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            errors: list[BaseException] = []

            def run(i: int) -> None:
                try:
                    mq.qualify(store, FakeProvider([f"sha256:d{i}"]), "m", SOURCES)
                except BaseException as exc:  # PermissionError from os.replace on Windows is the failure mode
                    errors.append(exc)

            threads = [threading.Thread(target=run, args=(i,)) for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(errors, [], errors)
            files = sorted(p.name for p in store.iterdir())
            self.assertEqual(files, ["ollama__m__list_extract.json", "ollama__m__verbatim_quote.json"])
            for name in files:
                entry = json.loads((store / name).read_text(encoding="utf-8"))  # parses: never half-written
                self.assertEqual({r["digest"] for r in entry["receipts"]}, {entry["digest"]})


if __name__ == "__main__":
    unittest.main()
