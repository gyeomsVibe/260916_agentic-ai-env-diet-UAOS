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
