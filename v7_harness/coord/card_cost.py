"""U76-C: the per-card cost gate. A card whose paid tokens exceed 3x the baseline card average does not open the next card.

Seen 2026-09-28 (U72/U74, docs/62): the 3x check was computed by hand from ledger rows, so it ran late and once. This
reads the same ledger deterministically: a card is every row whose work_id equals the card or starts with
"<card>-" (U74 + U74-TAIL), the baseline is one work_id divided by how many cards it covered. Both total tokens and
output tokens are checked; either above the limit is FAIL. A missing baseline or card is UNKNOWN, never PASS.
Read-only: the ledger is never rewritten.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# The global rule's cost gate: "a 3x cost regression is a failed gate" (Verification, v5.29).
RATIO_LIMIT = 3.0
TOKEN_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
METRICS = ("total_tokens", "output_tokens")


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _rows(path: Path) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    malformed = 0
    if not path.is_file():
        return rows, malformed
    for line in path.read_bytes().decode("utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if isinstance(row, dict):
            rows.append(row)
        else:
            malformed += 1
    return rows, malformed


def _belongs(work_id: Any, card: str) -> bool:
    return isinstance(work_id, str) and (work_id == card or work_id.startswith(card + "-"))


def _sum(rows: list[dict[str, Any]]) -> dict[str, int]:
    total = sum(_count(row.get(key)) for row in rows for key in TOKEN_KEYS)
    return {"rows": len(rows), "total_tokens": total, "output_tokens": sum(_count(r.get("output_tokens")) for r in rows)}


def report(project: Path, *, card: str, baseline: str, baseline_cards: int) -> dict[str, Any]:
    from .usage_ledger import ledger_file

    path = ledger_file(Path(project))
    rows, malformed = _rows(path)
    card_rows = [row for row in rows if _belongs(row.get("work_id"), card)]
    # The baseline is one exact work_id: a prefix could pull in later cards and hide a regression.
    base_rows = [row for row in rows if row.get("work_id") == baseline]
    spent, base = _sum(card_rows), _sum(base_rows)
    result: dict[str, Any] = {"source": str(path), "card": card, "baseline": baseline, "baseline_cards": baseline_cards,
                              "ratio_limit": RATIO_LIMIT, "card_usage": spent, "baseline_usage": base,
                              "malformed": malformed}
    if not isinstance(baseline_cards, int) or isinstance(baseline_cards, bool) or baseline_cards < 1:
        return {**result, "status": "UNKNOWN", "reason": "baseline_cards must be a positive integer"}
    if not card_rows or not base_rows or not all(base[m] for m in METRICS):
        return {**result, "status": "UNKNOWN", "reason": "card or baseline rows missing or zero"}
    ratios = {m: round(spent[m] / (base[m] / baseline_cards), 2) for m in METRICS}
    over = [m for m in METRICS if ratios[m] > RATIO_LIMIT]
    return {**result, "status": "FAIL" if over else "PASS", "ratios": ratios, "over_limit": over,
            "next_card_allowed": not over,
            "reason": "over 3x the baseline card average: " + ", ".join(over) if over else None}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Per-card 3x cost gate over the usage ledger (read only)")
    parser.add_argument("--project", default=".")
    parser.add_argument("--card", required=True)
    parser.add_argument("--baseline", required=True, help="Exact work_id of the baseline row(s)")
    parser.add_argument("--baseline-cards", type=int, required=True, help="How many cards the baseline covered")
    args = parser.parse_args(argv)
    result = report(Path(args.project), card=args.card, baseline=args.baseline, baseline_cards=args.baseline_cards)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    # Exit 0 only on PASS: FAIL and UNKNOWN both keep the next card closed.
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
