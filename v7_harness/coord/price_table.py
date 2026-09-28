"""U78: list prices per model, so token-thrift decisions weigh tokens by what they cost (docs/64).

Prices are USD per 1M tokens at each vendor's standard, short-context API rate, read from the vendor's own pricing
page on RETRIEVED. They are an API-equivalent yardstick, NOT the user's bill: all three tools run on subscriptions
whose quotas are not dollars, and a quota percentage is never converted into tokens or dollars (docs/27, U56).

Rows are priced only when the ledger names an exact model in the table. A missing, ambiguous ("sonnet"), mixed
("gpt-5.6-sol,gpt-6-sol"), or default ("agy-default") model is reported as unpriced tokens, never guessed.
Read-only: the ledger is never rewritten.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

RETRIEVED = "2026-09-28"
# Prices move: Sonnet 5's scheduled rise was cancelled on 2026-09-01 and Gemini 3.8 Flash's promo ends 2026-12-31.
# 30 days keeps the table within one vendor announcement cycle; after that the report says STALE and `--check`
# exits 1, so the refresh is an ACTIONABLE_DELTA for the conductor instead of a silent wrong number.
MAX_AGE_DAYS = 30
SOURCES = {
    "anthropic": "https://platform.claude.com/docs/en/about-claude/pricing",
    "openai": "https://developers.openai.com/api/docs/pricing",
    "google": "https://ai.google.dev/gemini-api/docs/pricing",
}

# (input, cache_write, cache_read, output) USD per 1M tokens, standard tier, short context.
# cache_write: Anthropic 5-minute write (1.25x input); OpenAI and Google bill no separate write, so it equals input.
PRICES: dict[str, dict[str, Any]] = {
    "claude-opus-5-5": {"vendor": "anthropic", "input": 4.00, "cache_write": 5.00, "cache_read": 0.20, "output": 20.00},
    "claude-sonnet-5": {"vendor": "anthropic", "input": 2.00, "cache_write": 2.50, "cache_read": 0.20, "output": 10.00},
    "claude-sonnet-4-6": {"vendor": "anthropic", "input": 3.00, "cache_write": 3.75, "cache_read": 0.30,
                          "output": 15.00},
    "claude-haiku-4-5": {"vendor": "anthropic", "input": 1.00, "cache_write": 1.25, "cache_read": 0.10, "output": 5.00},
    "gpt-5.6-sol": {"vendor": "openai", "input": 4.00, "cache_write": 4.00, "cache_read": 0.40, "output": 20.00},
    "gpt-6-sol": {"vendor": "openai", "input": 2.00, "cache_write": 2.00, "cache_read": 0.20, "output": 10.00},
    "gemini-3.1-pro": {"vendor": "google", "input": 2.00, "cache_write": 2.00, "cache_read": 0.20, "output": 12.00},
    # Gemini 3.8 Flash: promotional rate through 2026-12-31, then 1.50 / 0.15 / 7.50 (vendor page).
    "gemini-3.8-flash": {"vendor": "google", "input": 0.75, "cache_write": 0.75, "cache_read": 0.075,
                         "output": 3.75, "valid_until": "2026-12-31"},
}
# Local and deterministic workers spend no paid tokens; their cost (inference, wall time, power) stays UNMEASURED.
ZERO_PAID = {"deterministic"}
ZERO_PAID_PREFIXES = ("qwen", "llama", "gemma", "mistral", "phi", "deepseek")  # Ollama tags run on this PC
TOKEN_FIELDS = (("input_tokens", "input"), ("cache_creation_input_tokens", "cache_write"),
                ("cache_read_input_tokens", "cache_read"), ("output_tokens", "output"))


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def price_of(model: Any) -> dict[str, Any] | None:
    return PRICES.get(model) if isinstance(model, str) else None


def is_zero_paid(model: Any) -> bool:
    return isinstance(model, str) and (model in ZERO_PAID or model.lower().startswith(ZERO_PAID_PREFIXES))


def usd_equivalent(row: dict[str, Any]) -> dict[str, Any] | None:
    """API-equivalent USD of one ledger row by component, or None when its model is not an exact table entry."""
    price = price_of(row.get("model"))
    if price is None:
        return None
    parts = {rate: round(_count(row.get(field)) * price[rate] / 1_000_000, 6) for field, rate in TOKEN_FIELDS}
    return {**parts, "total": round(sum(parts.values()), 6)}


def freshness(today: date | None = None) -> dict[str, Any]:
    """FRESH within MAX_AGE_DAYS of RETRIEVED; STALE after, or once any entry passes its valid_until date."""
    today = today or date.today()
    age = (today - date.fromisoformat(RETRIEVED)).days
    expired = sorted(model for model, price in PRICES.items()
                     if price.get("valid_until") and today > date.fromisoformat(price["valid_until"]))
    stale = age > MAX_AGE_DAYS or bool(expired)
    return {"status": "STALE" if stale else "FRESH", "retrieved": RETRIEVED, "age_days": age,
            "max_age_days": MAX_AGE_DAYS, "expired_entries": expired,
            "refresh": ("re-read the three vendor pages in `sources`, update PRICES and RETRIEVED, rerun "
                        "tests/test_u78_price_table.py") if stale else None}


def report(project: Path, today: date | None = None) -> dict[str, Any]:
    from .usage_ledger import ledger_file

    path = ledger_file(Path(project))
    priced: dict[str, dict[str, Any]] = {}
    unpriced: dict[str, dict[str, int]] = {}
    zero_paid_rows = malformed = 0
    lines = path.read_bytes().decode("utf-8", errors="replace").splitlines() if path.is_file() else []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if not isinstance(row, dict):
            malformed += 1
            continue
        model = row.get("model")
        if is_zero_paid(model):
            zero_paid_rows += 1
            continue
        usd = usd_equivalent(row)
        tokens = {field: _count(row.get(field)) for field, _ in TOKEN_FIELDS}
        if usd is None:
            if not any(tokens.values()):
                continue  # a row with no tokens costs nothing whatever its model
            slot = unpriced.setdefault(str(model), {"rows": 0, **dict.fromkeys(tokens, 0)})
            slot["rows"] += 1
            for field, count in tokens.items():
                slot[field] += count
            continue
        slot = priced.setdefault(model, {"rows": 0, **dict.fromkeys(tokens, 0),
                                         **{rate: 0.0 for _, rate in TOKEN_FIELDS}, "total": 0.0})
        slot["rows"] += 1
        for field, count in tokens.items():
            slot[field] += count
        for key in (*(rate for _, rate in TOKEN_FIELDS), "total"):
            slot[key] = round(slot[key] + usd[key], 6)
    for slot in priced.values():
        # Which component drives cost tells the thrift rule what to cut first (long sessions: cache reads).
        slot["largest_component"] = max((rate for _, rate in TOKEN_FIELDS), key=lambda rate: slot[rate])
    return {
        "source": str(path),
        "freshness": freshness(today),
        "sources": SOURCES,
        "priced_usd_equivalent": priced,
        "priced_total_usd_equivalent": round(sum(slot["total"] for slot in priced.values()), 2),
        "unpriced_tokens": unpriced,
        "zero_paid_rows": zero_paid_rows,
        "malformed": malformed,
        "note": ("API list-price equivalent at standard short-context rates, not the subscription bill. Requests "
                 "above 200k-272k context cost up to 2x, so totals are a lower bound. Unpriced models are not "
                 "guessed. Local rows spend no paid tokens but are not zero cost."),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="API-equivalent cost of the usage ledger by model (read only)")
    parser.add_argument("--project", default=".")
    parser.add_argument("--check", action="store_true", help="Only check freshness; exit 1 when STALE")
    args = parser.parse_args(argv)
    result = freshness() if args.check else report(Path(args.project))
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 1 if args.check and result["status"] == "STALE" else 0


if __name__ == "__main__":
    sys.exit(main())
