"""U52: tool-output token gate. docs/49 §5 U-TOK-1.

Tool output that reaches a paid model is cut deterministically, never summarized by a model: arXiv 2508.21433 found
plain masking as good as LLM summaries at half the cost (measured on SWE-agent trajectories), and the local model quoted
its source verbatim only 32/67 times in the docs/49 run. A cut is always announced in the text, with the original size
and hash, so a reader never takes a partial output for the whole one; the full text can be kept in a spill file.

U52-R2 (Codex verdict on U52-S1b):
- `max_chars` is a hard cap on the whole result, marker included; S1b kept max_chars and then added the marker
  (gate_output('x'*10000, 1000) returned 1096 chars).
- mask_observations() is removed: no paid-model path in the harness carries a list of earlier observations, so it had
  no production caller. It returns with the first path that does (docs/49 §5 U-TOK-1, open item).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

# Head share of the kept characters. The tail keeps the rest because test runners and tracebacks put the verdict
# and the last error at the end; the head keeps the first failure and the command context.
HEAD_SHARE = 0.4
# Hash prefix length in markers: 12 hex characters is the prefix the repo already uses for bundle ids (brief.py).
HASH_CHARS = 12


@dataclass(frozen=True)
class GateResult:
    text: str
    truncated: bool
    original_chars: int
    sha256: str
    spill_path: str | None = None


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _spill(text: str, spill_path: str | Path | None) -> str | None:
    if spill_path is None:
        return None
    path = Path(spill_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", errors="replace")
    except OSError:
        return None  # the marker still reports size and hash; a missing spill is shown as "not saved"
    return str(path)


def gate_output(text: str, max_chars: int, spill_path: str | Path | None = None) -> GateResult:
    """Return at most `max_chars` characters of `text`, marker included: head and tail around an explicit cut marker.
    When the cap is too small for even the marker, the marker itself is cut, so the cap still holds."""
    text = text or ""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    digest = _sha(text)
    if len(text) <= max_chars:
        return GateResult(text, False, len(text), digest)
    saved = _spill(text, spill_path)
    where = f"full text: {saved}" if saved else "full text not saved"

    def marker(omitted: int) -> str:
        return (f"\n[U52 OUTPUT CUT: {omitted:,} of {len(text):,} chars omitted here; "
                f"sha256 {digest[:HASH_CHARS]}; {where}]\n")

    # The omitted count is part of the marker, so size the marker for the largest count it can show (everything).
    budget = max_chars - len(marker(len(text)))
    if budget <= 0:
        return GateResult(marker(len(text))[:max_chars], True, len(text), digest, saved)
    head_n = int(budget * HEAD_SHARE)
    tail_n = budget - head_n
    body = text[:head_n] + marker(len(text) - head_n - tail_n) + (text[len(text) - tail_n:] if tail_n else "")
    return GateResult(body, True, len(text), digest, saved)
