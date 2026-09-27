U51-R2: rework of the rejected U51-R1b per Codex verdict relay_d8ff049c (execution provenance; score is SCORER_ONLY). Apply the blocks exactly. No other change.

Pinned sha256 of every block body:
- v7_harness/model_qualification.py: df7178eb130d693e22164c6150b05ea42b08218c84b10d83850440b06fb920d7
- tests/test_u51_model_qualification.py: 8927d81f860d970d966cce03199d9d3ae632615c7ab0ae77c46d55053b282848
- docs/49_article12-ollama-extraction-and-uaos-update-report_2026-09-27.md: 3dc5e0eea312fabf30e897fa5883aa184abec53e866d2661752d95072c934682
- tests/fixtures/u51_art01.json: 8720a051560b12de743f46183d32b1f93feac5036deda45a1e96fe9a4c7cdc47
- tests/fixtures/u51_art02.json: 4d5f066d6a2084d9ee858c7028ece831de6cbe39085939fbb97165968f34b6d0
- tests/fixtures/u51_art03.json: 66a96cddf4237ef67f49f95d6f693aab95b77bac46a9706a227cc93b714f6072
- tests/fixtures/u51_synthetic_ledger.md: 3b1500f42aa61351c35174b7763196d53e4a1b3acb6eb2edf6afd652b46bad2a
- tests/fixtures/u51_synthetic_mailbox.md: 78b3f1160a24de71abbd4da148598f22b69a7613fc3fcc994fb5a35ce39492bf
- tests/fixtures/u51_synthetic_sentinel.md: 8b8a7cfeb211c1e528199f46fa2db908643175cf8628b945e8a2575f99ed3359

===FILE: v7_harness/model_qualification.py===
"""U51: task-specific model qualification gate bound to execution provenance. docs/49 §2·§5 U-MQ-1.

"The model runs in Ollama" is not "the model may do this task". A model is QUALIFIED per task type only when a
deterministic source check passes on outputs that this module itself obtained from the provider, and the verdict is
tied to the digest the provider reports, not to a name somebody typed.

Two commands, two kinds of evidence (Codex U51-R1b verdict: a hand-made output file scored under any typed identity
forged a QUALIFIED record):
- `score`   scores existing output files. Evidence kind SCORER_ONLY: it prints, it never records, and it takes no
            provider, model or digest, so no identity can be attached to outputs it did not see produced.
- `qualify` calls the provider itself for every source, reads the model digest from the provider before and after the
            run, hashes source, prompt and output into one receipt per call, scores those outputs and only then
            records. A typed --expect-digest that differs from the provider's digest is refused (IDENTITY_MISMATCH).
`lookup` accepts only records that carry receipts for the asked digest.

Limit, stated: a record file is still plain JSON in the user's own account; someone who edits it by hand can forge
it (B83: a label in the same account is not authentication). The gate stops the tool path from minting a verdict for
a model that never ran; it does not defend against the account owner.

Usage: python -m v7_harness.model_qualification qualify --model qwen3.5-32k --sources <dir> --record <dir>
       python -m v7_harness.model_qualification score --runs <dir> --sources <dir> [--pattern art*.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

# A task type is QUALIFIED when at least this share of items passes the source check. 0.8 = at most one item in five
# is thrown away by the independent gate; below that the checking and rework cost more than the local call saves.
# Initial value, to be re-tuned after three fixture runs (docs/49 §5 U-MQ-1).
QUALIFY_MIN = 0.8
# Fewer checked items than this cannot qualify: one lucky pass out of two says nothing about the model.
MIN_ITEMS = 20
TASK_TYPES = ("list_extract", "verbatim_quote")
# Another writer holds the target only for the length of its own replace (milliseconds), so 50 tries x 10 ms
# bounds the wait at 0.5 s before the error surfaces.
REPLACE_TRIES = 50
REPLACE_WAIT_S = 0.01
STATUSES = ("QUALIFIED", "REJECTED", "UNQUALIFIED", "UNQUALIFIED_DIGEST_CHANGED")
EVIDENCE = "PROVENANCE_BOUND"
# Each source asks for at most this many items; an output that does not parse counts as this many failed items, so a
# broken answer lowers the share instead of shrinking the denominator.
MAX_CANDIDATES = 6
# The docs/49 extraction contract (.work/article_ollama_20260927/extract.py), reduced to the two scored fields.
EXTRACT_PROMPT = """TASK: extract, do not judge. Output one JSON object only:
{{"candidates": [{{"name": str (the item's name as written in the document), "quote": str (EXACT substring copied from
the document, 10-80 chars)}}] (max {m})}}
Forbidden: inventing text not in the document; paraphrasing inside "quote".
Every name and quote is checked as a literal substring of the document by an independent script.

DOCUMENT (sha256={h}):
{text}"""
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
# One article of ~20 KB Korean took up to 72 s in docs/49; 900 s leaves room for a cold model load.
CALL_TIMEOUT_S = 900


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def candidate_key(name: str) -> str:
    """The item name without the model's appended explanation ("C09 — Firewall" -> "C09", "X :: y" -> "X")."""
    return re.split(r" — | ::", name or "")[0].strip()


def score_extraction(candidates: list[dict[str, Any]], source_text: str) -> dict[str, tuple[int, int]]:
    """Per task type: (items passing the literal source check, items checked)."""
    flat = _norm(source_text)
    names = [candidate_key(str(c.get("name") or "")) for c in candidates]
    quotes = [_norm(str(c.get("quote") or "")) for c in candidates]
    return {
        "list_extract": (sum(bool(n) and n in source_text for n in names), len(names)),
        "verbatim_quote": (sum(bool(q) and q in flat for q in quotes), len(quotes)),
    }


def score_output(output: str, source_text: str) -> dict[str, tuple[int, int]]:
    """Score one raw model answer; an answer without a candidates list fails MAX_CANDIDATES items per task."""
    try:
        data = json.loads(output)
        candidates = data.get("candidates") if isinstance(data, dict) else None
    except json.JSONDecodeError:
        candidates = None
    if not isinstance(candidates, list):
        return {t: (0, MAX_CANDIDATES) for t in TASK_TYPES}
    return score_extraction([c for c in candidates if isinstance(c, dict)], source_text)


def verdict(passed: int, total: int) -> str:
    if total < MIN_ITEMS:
        return "UNQUALIFIED"
    return "QUALIFIED" if passed / total >= QUALIFY_MIN else "REJECTED"


def score_fixture(runs_dir: Path, sources_dir: Path, pattern: str = "art*.json") -> dict[str, Any]:
    """SCORER_ONLY: score saved outputs against their sources. The result names no model and is never recorded."""
    totals = {t: [0, 0] for t in TASK_TYPES}
    files = sorted(Path(runs_dir).glob(pattern))
    if not files:
        raise ValueError(f"NO_FIXTURE: no {pattern} in {runs_dir}")
    for path in files:
        run = json.loads(path.read_text(encoding="utf-8"))
        meta, data = run["meta"], run.get("data") or {}
        # The pin is the sha256 of the text as Python reads it (newlines normalised to \n), the same text the model
        # was given, so a CRLF checkout of an unchanged document still matches.
        text = (Path(sources_dir) / meta["file"]).read_text(encoding="utf-8")
        if _sha(text) != meta["sha256"]:
            raise ValueError(f"SOURCE_HASH_MISMATCH:{meta['file']}")
        candidates = data.get("candidates") if isinstance(data, dict) else None
        for task, (ok, n) in score_extraction(candidates or [], text).items():
            totals[task][0] += ok
            totals[task][1] += n
    return {"evidence": "SCORER_ONLY", "items": len(files),
            "tasks": {t: {"passed": p, "total": n, "verdict": verdict(p, n)} for t, (p, n) in totals.items()}}


class Provider(Protocol):
    name: str

    def digest(self, model: str) -> str | None: ...

    def generate(self, model: str, prompt: str) -> tuple[str, dict[str, int]]: ...


class OllamaProvider:
    """The local Ollama API: the digest comes from /api/tags, the answer from /api/chat (temperature 0, JSON)."""

    name = "ollama"

    def __init__(self, host: str = OLLAMA_HOST) -> None:
        self.host = host

    def digest(self, model: str) -> str | None:
        with urllib.request.urlopen(f"{self.host}/api/tags", timeout=10) as response:
            tags = json.loads(response.read().decode("utf-8"))
        wanted = {model, f"{model}:latest"}
        for row in tags.get("models", []):
            if row.get("name") in wanted or row.get("model") in wanted:
                return str(row.get("digest") or "") or None
        return None

    def generate(self, model: str, prompt: str) -> tuple[str, dict[str, int]]:
        body = json.dumps({"model": model, "stream": False, "format": "json", "think": False,
                           "options": {"temperature": 0, "num_ctx": 32768},
                           "messages": [{"role": "user", "content": prompt}]}).encode("utf-8")
        request = urllib.request.Request(f"{self.host}/api/chat", body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=CALL_TIMEOUT_S) as response:
            raw = json.loads(response.read().decode("utf-8"))
        usage = {"input_tokens": int(raw.get("prompt_eval_count") or 0), "output_tokens": int(raw.get("eval_count") or 0)}
        return str((raw.get("message") or {}).get("content") or ""), usage


@dataclass(frozen=True)
class Receipt:
    """One provider call: who answered (digest read from the provider), on what (source, prompt), with what (output)."""
    provider: str
    model: str
    digest: str
    source_file: str
    source_sha256: str
    prompt_sha256: str
    output_sha256: str
    started_at: float
    elapsed_s: float
    input_tokens: int
    output_tokens: int


def measure(provider: Provider, model: str, sources: list[Path]) -> tuple[list[Receipt], list[str], list[str]]:
    """Run the extraction on every source through the provider. The digest is read before and after; a model that is
    missing or was replaced during the run yields no receipts."""
    before = provider.digest(model)
    if not before:
        raise ValueError(f"MODEL_NOT_INSTALLED:{provider.name}/{model}")
    receipts, outputs, texts = [], [], []
    for path in sources:
        text = Path(path).read_text(encoding="utf-8")
        prompt = EXTRACT_PROMPT.format(m=MAX_CANDIDATES, h=_sha(text), text=text)
        started = time.time()
        output, usage = provider.generate(model, prompt)
        receipts.append(Receipt(provider.name, model, before, Path(path).name, _sha(text), _sha(prompt), _sha(output),
                                round(started, 3), round(time.time() - started, 3),
                                usage.get("input_tokens", 0), usage.get("output_tokens", 0)))
        outputs.append(output)
        texts.append(text)
    after = provider.digest(model)
    if after != before:
        raise ValueError(f"DIGEST_CHANGED_DURING_RUN:{before}->{after}")
    return receipts, outputs, texts


def _key(provider: str, model: str, task_type: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", f"{provider}__{model}__{task_type}")


def _write(store: Path, name: str, entry: dict[str, Any]) -> None:
    """Atomic write (temp file + os.replace): parallel writers never leave a half-written record."""
    store = Path(store)
    store.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=store, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(entry, handle, ensure_ascii=False, indent=1)
    for attempt in range(REPLACE_TRIES):
        try:
            os.replace(tmp, store / f"{name}.json")
            return
        except PermissionError:
            # Windows refuses a replace while another writer's replace holds the target (U51 8-thread test).
            if attempt == REPLACE_TRIES - 1:
                Path(tmp).unlink(missing_ok=True)
                raise
            time.sleep(REPLACE_WAIT_S)


def qualify(store: Path, provider: Provider, model: str, sources: list[Path],
            expect_digest: str | None = None) -> dict[str, Any]:
    """Measure, verify the provenance, score and record one verdict per task type."""
    if not sources:
        raise ValueError("NO_SOURCES")
    if expect_digest:
        actual = provider.digest(model)
        if actual != expect_digest:
            raise ValueError(f"IDENTITY_MISMATCH: expected digest {expect_digest}, provider reports {actual}")
    receipts, outputs, texts = measure(provider, model, sources)
    totals = {t: [0, 0] for t in TASK_TYPES}
    for receipt, output, text in zip(receipts, outputs, texts):
        # Re-check each receipt against the bytes it describes before any of them may count.
        if receipt.output_sha256 != _sha(output) or receipt.source_sha256 != _sha(text):
            raise ValueError(f"RECEIPT_MISMATCH:{receipt.source_file}")
        for task, (ok, n) in score_output(output, text).items():
            totals[task][0] += ok
            totals[task][1] += n
    digest = receipts[0].digest
    result = {"provider": provider.name, "model": model, "digest": digest, "tasks": {}}
    for task, (passed, total) in totals.items():
        entry = {"evidence": EVIDENCE, "provider": provider.name, "model": model, "digest": digest,
                 "task_type": task, "passed": passed, "total": total, "verdict": verdict(passed, total),
                 "qualify_min": QUALIFY_MIN, "receipts": [asdict(r) for r in receipts]}
        _write(store, _key(provider.name, model, task), entry)
        result["tasks"][task] = {"passed": passed, "total": total, "verdict": entry["verdict"]}
    return result


def lookup(store: Path, *, provider: str, model: str, digest: str, task_type: str) -> str:
    """Status of this exact model artifact for this task. A different digest never inherits a verdict, and a record
    without receipts for that digest (hand-made or from the old `score --record`) counts as no record."""
    path = Path(store) / f"{_key(provider, model, task_type)}.json"
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "UNQUALIFIED"
    if entry.get("digest") != digest:
        return "UNQUALIFIED_DIGEST_CHANGED"
    receipts = entry.get("receipts") or []
    if entry.get("evidence") != EVIDENCE or not receipts or any(
            r.get("digest") != digest or r.get("model") != model or r.get("provider") != provider for r in receipts):
        return "UNQUALIFIED"
    return entry.get("verdict") if entry.get("verdict") in ("QUALIFIED", "REJECTED") else "UNQUALIFIED"


PROVIDERS = {"ollama": OllamaProvider}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="model_qualification")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("score", help="SCORER_ONLY: score saved outputs; never records, takes no identity")
    sc.add_argument("--runs", type=Path, required=True)
    sc.add_argument("--sources", type=Path, required=True)
    sc.add_argument("--pattern", default="art*.json", help="Run file glob inside --runs")
    qu = sub.add_parser("qualify", help="Call the provider on every source, then score and record with receipts")
    qu.add_argument("--provider", default="ollama", choices=sorted(PROVIDERS))
    qu.add_argument("--model", required=True)
    qu.add_argument("--sources", type=Path, required=True)
    qu.add_argument("--pattern", default="*.md", help="Source file glob inside --sources")
    qu.add_argument("--record", type=Path, required=True, help="Store dir for the verdict records")
    qu.add_argument("--expect-digest", default=None, help="Refuse to run unless the provider reports this digest")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "score":
            result = score_fixture(args.runs, args.sources, args.pattern)
        else:
            sources = sorted(args.sources.glob(args.pattern))
            result = qualify(args.record, PROVIDERS[args.provider](), args.model, sources, args.expect_digest)
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
===END===

===FILE: tests/test_u51_model_qualification.py===
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
===END===

===FILE: docs/49_article12-ollama-extraction-and-uaos-update-report_2026-09-27.md===
# 49. 기사 12건 올라마 재분석 + 외부 자료 비교 → UAOS 개선·업데이트 보고서

- 작성: Claude Code (Codex 대행 아님, Codex 복귀 시 재검토 대상), 2026-09-27
- 입력: `docs/user-docs/# UAOS 기사 분석 보고서 01~12.md` (13~15번 종합본은 비교 기준으로만 사용)
- 산출물 등급: 유지(maintained) 문서. 추출 원본은 `.work/article_ollama_20260927/`(일회성, 커밋 제외)

---

## 1. 결론 먼저

**UAOS에 새 에이전트나 새 프로바이더 계층을 더하지 말고, "문맥에 무엇이 들어가도 되는가"를 재는 관문 3개를 먼저 넣는다.**

| 순위 | 도입 로직 | 출처 기사 | 현재 코드 상태 | 외부 근거 |
|---|---|---|---|---|
| P1 | 도구 출력 토큰 관문(Tool Output Token Gate) + 오래된 관찰 가리기(observation masking) | 08, 15번 종합 | 없음(`grep tool_output\|masking` 0건) | 관찰 토큰이 턴의 약 84%, 단순 가리기로 비용 절반·성능 동등(arXiv 2508.21433) |
| P1 | 문맥 입장 관문(Context Admission Gate) = 지연 능력 로딩(Lazy Capability Loading) | 08, 04(C10) | 없음(`admission` 0건) | MCP 도구 정의 선로딩 1회 약 7k~50k 토큰, 도구 검색 지연 로딩으로 85% 감소 보고 |
| P1 | 작업별 모델 자격 관문(Model Qualification Gate) + 모델 산출물 고정(pinning) | 06, 11 | 부분(`olla.py` 읽기 비용 추정만 있음) | **이번 실행 자체가 증거**: 4B 로컬 모델의 원문 인용 정확도 32/67=48% |
| P2 | 토큰 톱니(Token Ratchet): 검증된 최저 토큰량을 회귀 상한으로 고정 | 01 | 부분(`rsi.py`에 회귀 관문 있음, 토큰 축은 없음) | claude.ai 3배 개선: 여정 4개(사용량 95%)·지표 13개로 측정 후 고정 |
| P2 | 도구 실행 방화벽(Tool Proposal/Execution Firewall)·작업별 허용목록 | 04, 08 | 부분(`adapters/guard.py`, 전역 규칙) | Ollama·OpenAI 도구 호출은 "요청"일 뿐 실행 권한이 아님 |
| P3 | 능력 증거 등록부(Capability Evidence Registry)·프로브 | 02, 03, 07, 10 | 없음 | OpenAI 호환 선언 ≠ 기능 보장(Ollama 문서도 부분 호환 명시) |
| 보류 | 빠른 판단 평면(Fast Decision Plane), 다중 프로바이더 라이브러리 흡수, OpenClaude 코드 도입 | 12, 07, 10 | — | 12번 추출 6건 모두 인용 불일치, 07번은 유출 코드 라이선스 위험 |

---

## 2. 이번 분석을 어떻게 했나 (재현 가능한 절차)

토큰 예산이 사용 한도에 가깝다는 조건 때문에 **읽기·추출은 올라마, 판단·비교는 Claude**로 나눴다.

1. **기사 1건 = 올라마 새 대화 1회.** 대화 기록을 공유하지 않고 12번 따로 호출했다(`extract.py`, 모델 `qwen3.5-32k`, temperature 0, JSON 형식 강제).
2. **호출마다 작업 매뉴얼 전달.** 작업 ID `U-ART12-EXTRACT-nn`, 입력 SHA-256, 출력 스키마, 금지 행동(원문에 없는 문장 생성), 인수 관문을 프롬프트 머리에 넣었다.
3. **독립 관문 2개로 검증.** (a) `quote`가 원문에 글자 그대로 있는지, (b) 후보 이름이 원문에 있는지 — 둘 다 결정적(deterministic) 파이썬 검사. 올라마의 "성공" 응답은 증거로 치지 않았다.
4. **Claude는 원문 전체를 읽지 않았다.** 제목·판정 줄과 올라마 추출 결과, 코드 `grep` 결과, 웹 검색 8회만 사용했다.

### 측정값

| 항목 | 값 |
|---|---|
| 호출 수 | 12회(실패 0, JSON 파싱 오류 0) |
| 로컬 벽시계 시간 | 합계 360초(1번 72초는 모델 적재 포함, 나머지 21~33초) |
| 로컬 토큰 | 입력 45,037 / 출력 7,053 |
| 후보 추출 | 67건 |
| 인용 원문 일치 | 32건(48%) — 35건은 의역이라 관문에서 탈락 |
| 이름 원문 일치 | 60건(90%) — 탈락 7건은 이름 앞 번호 형식 변형 |
| 기사별 최악 | 12번: 인용 0/6 (긴 원문 20KB, 추상 개념 위주) |

**해석:** 4B급 로컬 모델은 "무엇이 있는지 찾기(이름·목록)"는 90% 신뢰, "그대로 베끼기(인용)"는 48%다. 그래서 UAOS에서 올라마 출력은 **반드시 원문 대조 관문 뒤에서만** 쓰여야 하며, 이것이 P1 "모델 자격 관문"의 직접 근거다.

**Claude 토큰 절감은 측정하지 않았다(UNMEASURED).** 원문 12건(약 187KB)을 Claude가 직접 읽었을 경우와의 대조 실험은 하지 않았다.

---

## 3. 12개 기사별 핵심 (올라마 추출 → 원문 대조 통과분 중심)

| # | 기사 | 문서 자체 판정 | 대조 통과한 핵심 로직 |
|---|---|---|---|
| 01 | Claude.ai 2주 만에 3배 빠르게 | 보강 도입 | 사용자 여정 성능 장부, 대리지표 검증 관문, 성능 톱니 |
| 02 | Ollama OpenAI 호환성 | 도입 | OpenAI 호환 전송 어댑터, 능력 명세(SUPPORTED/UNSUPPORTED/UNVERIFIED), 네이티브 탈출구 |
| 03 | Ollama OpenAI 형식 호출 | 신규 로직 없음 | 프로바이더 교체 불변식(판단 체계는 바뀌면 안 됨) |
| 04 | Ollama 도구 호출 | 강력 도입 | 도구 제안/실행 방화벽, 작업별 도구 허용목록 |
| 05 | Ollama 웹 검색 API | 강력 도입 | 검색 증거 사다리, 검색 권한 방화벽, 외부 전송 최소화, 검색 예산 관문 |
| 06 | Ollama v0.1.33 신모델 | 강력 도입 | 모델 자격 관문(실행 가능 ≠ 작업자 승인) |
| 07 | OpenClaude(유출 코드 파생) | 코드 보류 / 구조만 추출 | 런타임·프로바이더 분리, 도구 호출 정규화 |
| 08 | Function Calling vs MCP | 신규 도입 | MCP 경계 어댑터, 발견/인가 분리, 서버 신뢰 등록부, 지연 능력 로딩, 버전 고정 |
| 09 | MCP로 IntelliJ 연동 | 강력 도입 | 작업공간 범위 고정 |
| 10 | OpenLM 다중 LLM 클라이언트 | 부분 중복 + 보강 | 결과 봉투 정규화, 실패 분류 정규화, 실패 인식 대체 경로, 어댑터 의존성 방화벽 |
| 11 | Ollama Python/JS 라이브러리 | 도입 | 클라이언트 SDK 동작 고정 |
| 12 | Laya(Jev 대안) | "생각할 필요 없는 판단을 LLM에 시키지 않는다" | 인용 통과 0건 → 이름만 확인(C45~C50), 판단 근거로 쓰지 않음 |

---

## 4. 외부 자료와의 비교

### 4.1 기사 내용이 외부 자료로 확인된 것 (사실)

- **01번 수치**: Anthropic은 사용량 95%를 차지하는 여정 4개를 측정해 3,000건 이상 변경을 2주에 배포했고 롤백이 없었다. 예: 새 페이지 입력 가능 시점 p75 3.1초→0.55초. → "측정 먼저, 개선은 작게, 개선치는 고정"이라는 01번 해석과 일치.
- **05·02·04번**: Ollama는 웹 검색 API, OpenAI 호환 엔드포인트의 도구 지원, Anthropic Messages API 호환(2026-01)까지 제공한다. → 로컬 모델에 도구·검색 권한이 "기술적으로" 열렸다는 뜻이며, 그래서 **실행 권한 분리(04번 C09)**가 필수가 된다.
- **07번**: OpenClaude는 2026-03-31 npm 소스맵 유출본의 파생이다. → 코드 직접 도입 보류 판정이 맞다.
- **08번**: MCP 도구 정의를 매 턴 선로딩하면 서버 4개 기준 메시지당 약 7,000토큰, 무거운 구성은 50,000토큰 이상. 지연 로딩(도구 검색)으로 85% 감소, 코드 실행 방식으로 150k→2k(98.7%) 사례.

### 4.2 논문이 더해 준 것 (기사에 없던 근거)

- **The Complexity Trap (arXiv 2508.21433, NeurIPS DL4Code 2025)**: 오래된 도구 관찰을 그냥 가리는 방식이 LLM 요약과 해결률이 같거나 약간 높고 비용은 절반. → UAOS는 **요약 에이전트를 추가하지 말고, 결정적 가리기부터** 해야 한다. 이는 전역 규칙 "결정적 추출 먼저"와 같은 방향.
- **ACON(arXiv 2510.00615)**, **SWE-Pruner(2601.16746)**, **Squeez(2604.04979)**: 압축 지침을 실패 분석으로 개선, 작업 조건부로 도구 출력을 잘라냄. → P2 이후 후보. 모델 학습이 필요 없는 ACON 방식만 UAOS RSI(증거 제안→관문)와 궁합이 맞다.
- **Execution Instability 연구(arXiv 2608.06503)**: 압축이 장기 작업을 불안정하게 만들 수 있다. → 압축 도입 시 반드시 회귀 관문(인수 테스트 동일 통과)을 둔다.

### 4.3 커뮤니티(일화, 증거 아님)

- CLAUDE.md는 매 질의마다 다시 전송되므로 가장 비싼 상시 문맥이라는 경험담이 반복된다. 설정 도중 변경은 프롬프트 캐시를 깨뜨린다. → "상시 적재 문맥 예산"을 따로 재야 한다(15번 종합본 14절과 일치).
- Claude Code를 Ollama로 돌리는 "월 0원" 사례가 많지만 64K 이상 문맥·도구 호출 품질이 전제다. → UAOS의 "올라마 = 계산기" 원칙을 바꿀 근거는 되지 않는다. 이번 실측 인용 정확도 48%가 반례다.

### 4.4 기존 종합본(13~15번)과의 차이

- 15번이 제안한 5개(문맥 입장 관문, 한 번 읽기 공유 증거 캐시, 도구 출력 관문, 공급자별 예산 중개, 토큰 회귀 관문)는 **방향 동의**.
- 차이 1: "한 번 읽기 공유 증거 캐시"는 이미 `olla.py`의 읽기 비용 추정·요약본 우선 규칙(`read_once`, `DIGEST_MIN_TOKENS`)으로 일부 존재 → 신규가 아니라 **확장**이다.
- 차이 2: `broker/core.py`는 프로세스 잠금 중개기이지 예산 중개기가 아니다. 이름이 같아 혼동 위험 → 새 기능은 `budget_broker`가 아닌 다른 이름을 권장.
- 차이 3: 15번은 모델 품질 문제를 다루지 않았다. 이번 실측(인용 48%)으로 **모델 자격 관문을 P1로 올린다.**

---

## 5. 도입 계획 (작은 계약 단위)

각 항목은 "관문(gate)을 먼저 정하고, 통과하면 끝"이다. 코드는 아직 바꾸지 않았다.

### U-TOK-1 도구 출력 토큰 관문 + 관찰 가리기 (P1)
- 무엇: 작업자에게 되돌리는 도구 출력에 상한(예: 결과당 N토큰)을 두고, 넘으면 머리/꼬리+파일 포인터로 대체. 최근 k턴보다 오래된 관찰은 "[생략: 파일경로#해시]"로 가린다.
- 왜 이 방식: 논문상 결정적 가리기가 LLM 요약과 성능 동등·비용 절반. 로컬 모델 요약은 이번 실측처럼 원문 충실도가 낮다.
- 관문: 기존 `pilot` 인수 테스트 통과율 동일 + 같은 작업 3회 평균 입력 토큰 감소를 `usage_ledger` 수치로 비교. 감소 없으면 폐기.

### U-TOK-2 문맥 입장 관문 (P1)
- 무엇: 작업 계약(PLAN 카드)에 `context_allow: [파일, 도구, MCP 서버]`를 두고, 목록 밖 항목은 작업자 호출에 싣지 않는다.
- 관문: 입장 거부된 항목 때문에 인수 실패가 생기면 목록 누락으로 기록(자동 확장 금지). 호출당 입력 토큰을 전후 비교.

### U-MQ-1 작업별 모델 자격 관문 + 고정 (P1)
- 무엇: `(provider, model tag, digest, 작업 유형)`별로 자격 기록. 작업 유형 예: `list_extract`, `verbatim_quote`, `summarize`, `code_edit`.
- 초기값(이번 실측): `qwen3.5-32k` → `list_extract` 90% QUALIFIED, `verbatim_quote` 48% REJECTED.
- 관문: 고정 fixture 12건(이번 기사 12건과 해시)으로 재측정. 모델 digest가 바뀌면 자격 자동 승계 금지.

### U-TOK-3 토큰 톱니 (P2)
- 무엇: `rsi gate`에 토큰 축 추가. 검증된 최저 토큰량을 기준선으로 저장, 품질이 같아도 토큰이 기준선의 1.2배를 넘으면 실패. (1.2 = 실행 간 변동 흡수용 초기값, 3회 측정 후 재조정)
- 전역 규칙의 "3배 회귀 = 실패"보다 촘촘한 조기 경보 역할.

### U-SEC-1 도구 실행 방화벽 명문화 (P2)
- 무엇: 올라마·외부 모델의 tool call은 `PROPOSED` 상태로만 기록하고, 실행은 UAOS 정책 판정 후에만. `POLICY_DENIED`는 대체 경로 없이 종료(10번 C41).

### 도입하지 않을 것
- 빠른 판단 평면(12번): 원문 대조 0/6, 자체 데이터 보정 근거 없음.
- 다중 프로바이더 라이브러리 흡수(07·10번): 어댑터 1개 뒤로 격리하는 원칙만 채택.
- 요약 전용 에이전트 추가: 논문상 가리기 대비 이득 없음.

---

## 6. 확인된 사실 / 가정 / 모름

- **사실**: 올라마 12회 호출 결과·토큰·시간(위 표), 코드 검색 결과(`admission`·`tool_output`·`masking`·`ratchet`·`journey` 0건), 외부 수치(출처 아래).
- **가정**: U-TOK-1/2가 UAOS 작업에서도 논문 수준(비용 약 50%)의 절감을 낸다는 것. 측정 전까지 UNMEASURED.
- **모름**: Claude 쪽 토큰이 실제로 얼마나 절감됐는지(대조 실험 없음), 더 큰 로컬 모델(예: `qwen2.5-coder:7b`)의 인용 정확도.

## 7. 출처

- [How we made claude.ai 3x faster in two weeks](https://claude.dev/blog/how-we-made-claude-ai-faster/) · [Help Net Security 요약](https://www.helpnetsecurity.com/2026/09/24/anthropic-claude-ai-faster/)
- [Ollama Web search 문서](https://docs.ollama.com/capabilities/web-search) · [Ollama Tool support](https://ollama.com/blog/tool-support) · [Ollama OpenAI Compatibility](https://ollama.readthedocs.io/en/openai/)
- [OpenClaude (Gitlawb)](https://github.com/Gitlawb/openclaude) · [Claude Code 유출 요약](https://actionablenotes.substack.com/p/the-claude-code-leak-a-mini-brief)
- [MCP Tool Search 가이드](https://www.atcyrus.com/stories/mcp-tool-search-claude-code-context-pollution-guide) · [MCP 토큰 오버헤드 분석](https://docs.bswen.com/blog/2026-04-24-mcp-token-overhead/) · [Code execution with MCP 98.7%](https://brightbean.xyz/blog/code-execution-mcp-efficient-ai-agents/) · [MCP 토론 #629](https://github.com/orgs/modelcontextprotocol/discussions/629)
- 논문: [The Complexity Trap 2508.21433](https://arxiv.org/abs/2508.21433) · [저장소](https://github.com/JetBrains-Research/the-complexity-trap) · [ACON 2510.00615](https://arxiv.org/abs/2510.00615) · [SWE-Pruner 2601.16746](https://arxiv.org/pdf/2601.16746) · [Squeez 2604.04979](https://arxiv.org/pdf/2604.04979) · [압축 실행 불안정성 2608.06503](https://arxiv.org/html/2608.06503v1) · [Awesome-Agent-Context-Compression](https://github.com/YerbaPage/Awesome-Agent-Context-Compression)
- 커뮤니티(일화): [Claude Code 프롬프트 캐싱 문서](https://code.claude.com/docs/en/prompt-caching) · [Ollama + Claude Code 설정기](https://www.morphllm.com/ollama-claude-code)
===END===

===FILE: tests/fixtures/u51_art01.json===
{
 "meta": {
  "n": 1,
  "file": "u51_synthetic_mailbox.md",
  "sha256": "78b3f1160a24de71abbd4da148598f22b69a7613fc3fcc994fb5a35ce39492bf"
 },
 "data": {
  "candidates": [
   {
    "name": "MAILBOX-R1 — model note",
    "quote": "Rule 1 of the mailbox keeps step 1 idempotent and records its receipt."
   },
   {
    "name": "MAILBOX-R2",
    "quote": "Rule 2 of the mailbox keeps step 2 idempotent and records its receipt."
   },
   {
    "name": "MAILBOX-R3 — model note",
    "quote": "Rule 3 of the mailbox keeps step 3 idempotent and records its receipt."
   },
   {
    "name": "MAILBOX-R4",
    "quote": "Rule 4 of the mailbox keeps step 4 idempotent and records its receipt."
   },
   {
    "name": "MAILBOX-R5 — model note",
    "quote": "The mailbox makes step 5 safe to repeat."
   },
   {
    "name": "MAILBOX-R6",
    "quote": "The mailbox makes step 6 safe to repeat."
   },
   {
    "name": "MAILBOX-R7 — model note",
    "quote": "The mailbox makes step 7 safe to repeat."
   },
   {
    "name": "MAILBOX-R8",
    "quote": "The mailbox makes step 8 safe to repeat."
   }
  ]
 }
}
===END===

===FILE: tests/fixtures/u51_art02.json===
{
 "meta": {
  "n": 2,
  "file": "u51_synthetic_ledger.md",
  "sha256": "3b1500f42aa61351c35174b7763196d53e4a1b3acb6eb2edf6afd652b46bad2a"
 },
 "data": {
  "candidates": [
   {
    "name": "LEDGER-R1 — model note",
    "quote": "Rule 1 of the ledger keeps step 1 idempotent and records its receipt."
   },
   {
    "name": "LEDGER-R2",
    "quote": "Rule 2 of the ledger keeps step 2 idempotent and records its receipt."
   },
   {
    "name": "LEDGER-R3 — model note",
    "quote": "Rule 3 of the ledger keeps step 3 idempotent and records its receipt."
   },
   {
    "name": "LEDGER-R4",
    "quote": "Rule 4 of the ledger keeps step 4 idempotent and records its receipt."
   },
   {
    "name": "LEDGER-R5 — model note",
    "quote": "The ledger makes step 5 safe to repeat."
   },
   {
    "name": "LEDGER-R6",
    "quote": "The ledger makes step 6 safe to repeat."
   },
   {
    "name": "LEDGER-R7 — model note",
    "quote": "The ledger makes step 7 safe to repeat."
   },
   {
    "name": "LEDGER-R8",
    "quote": "The ledger makes step 8 safe to repeat."
   }
  ]
 }
}
===END===

===FILE: tests/fixtures/u51_art03.json===
{
 "meta": {
  "n": 3,
  "file": "u51_synthetic_sentinel.md",
  "sha256": "8b8a7cfeb211c1e528199f46fa2db908643175cf8628b945e8a2575f99ed3359"
 },
 "data": {
  "candidates": [
   {
    "name": "SENTINEL-R1 — model note",
    "quote": "Rule 1 of the sentinel keeps step 1 idempotent and records its receipt."
   },
   {
    "name": "SENTINEL-R2",
    "quote": "Rule 2 of the sentinel keeps step 2 idempotent and records its receipt."
   },
   {
    "name": "SENTINEL-R3 — model note",
    "quote": "Rule 3 of the sentinel keeps step 3 idempotent and records its receipt."
   },
   {
    "name": "SENTINEL-R4",
    "quote": "Rule 4 of the sentinel keeps step 4 idempotent and records its receipt."
   },
   {
    "name": "SENTINEL-R5 — model note",
    "quote": "The sentinel makes step 5 safe to repeat."
   },
   {
    "name": "SENTINEL-R6",
    "quote": "The sentinel makes step 6 safe to repeat."
   },
   {
    "name": "SENTINEL-R7 — model note",
    "quote": "The sentinel makes step 7 safe to repeat."
   },
   {
    "name": "SENTINEL-R8",
    "quote": "The sentinel makes step 8 safe to repeat."
   }
  ]
 }
}
===END===

===FILE: tests/fixtures/u51_synthetic_ledger.md===
# Synthetic note on the ledger

- LEDGER-R1: Rule 1 of the ledger keeps step 1 idempotent and records its receipt.
- LEDGER-R2: Rule 2 of the ledger keeps step 2 idempotent and records its receipt.
- LEDGER-R3: Rule 3 of the ledger keeps step 3 idempotent and records its receipt.
- LEDGER-R4: Rule 4 of the ledger keeps step 4 idempotent and records its receipt.
- LEDGER-R5: Rule 5 of the ledger keeps step 5 idempotent and records its receipt.
- LEDGER-R6: Rule 6 of the ledger keeps step 6 idempotent and records its receipt.
- LEDGER-R7: Rule 7 of the ledger keeps step 7 idempotent and records its receipt.

Invented items are not in this note (ledger).
===END===

===FILE: tests/fixtures/u51_synthetic_mailbox.md===
# Synthetic note on the mailbox

- MAILBOX-R1: Rule 1 of the mailbox keeps step 1 idempotent and records its receipt.
- MAILBOX-R2: Rule 2 of the mailbox keeps step 2 idempotent and records its receipt.
- MAILBOX-R3: Rule 3 of the mailbox keeps step 3 idempotent and records its receipt.
- MAILBOX-R4: Rule 4 of the mailbox keeps step 4 idempotent and records its receipt.
- MAILBOX-R5: Rule 5 of the mailbox keeps step 5 idempotent and records its receipt.
- MAILBOX-R6: Rule 6 of the mailbox keeps step 6 idempotent and records its receipt.
- MAILBOX-R7: Rule 7 of the mailbox keeps step 7 idempotent and records its receipt.

Invented items are not in this note (mailbox).
===END===

===FILE: tests/fixtures/u51_synthetic_sentinel.md===
# Synthetic note on the sentinel

- SENTINEL-R1: Rule 1 of the sentinel keeps step 1 idempotent and records its receipt.
- SENTINEL-R2: Rule 2 of the sentinel keeps step 2 idempotent and records its receipt.
- SENTINEL-R3: Rule 3 of the sentinel keeps step 3 idempotent and records its receipt.
- SENTINEL-R4: Rule 4 of the sentinel keeps step 4 idempotent and records its receipt.
- SENTINEL-R5: Rule 5 of the sentinel keeps step 5 idempotent and records its receipt.
- SENTINEL-R6: Rule 6 of the sentinel keeps step 6 idempotent and records its receipt.
- SENTINEL-R7: Rule 7 of the sentinel keeps step 7 idempotent and records its receipt.

Invented items are not in this note (sentinel).
===END===
