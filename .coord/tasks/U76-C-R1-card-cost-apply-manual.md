```contract
work_id: U76-C-R1
worker: apply
goal: Per-card 3x cost gate over the usage ledger (read only); FAIL or UNKNOWN keeps the next card closed.
inputs:
- .coord/PLAN.md sha256=215d7c33e3cdf3ab7c367eb90f7b527761b40c2c09805520bf4c3ade59c5808c
allow:
- v7_harness/coord/card_cost.py
- tests/test_u76c_card_cost.py
- .coord/PLAN.md
acceptance: python -m unittest tests.test_u76c_card_cost tests.test_u78_price_table
forbidden: design changes; edits outside allow; weakening or deleting existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Write the files exactly as given; for .coord/PLAN.md apply the one EDIT (insert the U76-C row after U78).

===EDIT: .coord/PLAN.md===
<<<<<<< SEARCH
| U78 | REVIEW (Claude 부관 구현 2026-09-28, 사용자 지시; 판정 codex) | claude · apply(0토큰) | 3대 도구 모델 가격표(Anthropic·OpenAI·Google 공식 페이지 2026-09-28), 장부 API 환산 달러(구독 청구서 아님), 모호한 모델은 추측 없이 unpriced, 30일·할인 기한 경과 시 STALE과 `--check` 종료 1 — docs/64 |
=======
| U78 | REVIEW (Claude 부관 구현 2026-09-28, 사용자 지시; 판정 codex) | claude · apply(0토큰) | 3대 도구 모델 가격표(Anthropic·OpenAI·Google 공식 페이지 2026-09-28), 장부 API 환산 달러(구독 청구서 아님), 모호한 모델은 추측 없이 unpriced, 30일·할인 기한 경과 시 STALE과 `--check` 종료 1 — docs/64 |
| U76-C | DONE-DELEGATED (Codex LIMITED 중 Claude 권한대행 2026-09-28 — 설계·판정 동일 계보, Codex 복귀 시 재검토) | claude(대행 설계·판정) · apply(0토큰) | 카드별 3배 비용 관문을 결정적으로 계산: 카드 행(`<card>`, `<card>-*`) 합 ÷ (기준 work_id 합 ÷ 기준 카드 수). 총 토큰·출력 중 하나라도 3배 초과면 FAIL, 자료 없음은 UNKNOWN, 둘 다 종료 코드 1로 다음 카드를 열지 않는다. U74 실측 3.14배 FAIL 재현. `python -m v7_harness.coord.card_cost --card <id> --baseline <id> --baseline-cards <n>` — `tests/test_u76c_card_cost.py` |
>>>>>>> REPLACE
===FILE: v7_harness/coord/card_cost.py===
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
===FILE: tests/test_u76c_card_cost.py===
"""U76-C: a card over 3x the baseline card average fails and keeps the next card closed; missing data is UNKNOWN."""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from v7_harness.coord.card_cost import RATIO_LIMIT, main, report


def _row(work_id, *, inp=0, out=0, cache_read=0, cache_write=0) -> dict:
    return {"work_id": work_id, "kind": "session", "input_tokens": inp, "output_tokens": out,
            "cache_read_input_tokens": cache_read, "cache_creation_input_tokens": cache_write}


# The real U72/U74 numbers (docs/62): baseline 46,206,721 total / 235,078 output over 9 cards;
# U74 two rows plus U74-TAIL = 16,123,467 total / 69,482 output -> 3.14x total, 2.66x output.
U74_ROWS = [_row("U67-U73-ACTING", inp=1_000_000, out=235_078, cache_read=44_971_643),
            _row("U74", inp=300_000, out=48_990, cache_read=11_165_461),
            _row("U74", inp=100_000, out=14_108, cache_read=2_664_204),
            _row("U74-TAIL", inp=50_000, out=6_384, cache_read=1_774_320),
            _row("U75", inp=999_999_999)]


class CardCostTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ledger = self.root / ".coord" / "usage" / "runs.jsonl"
        self.ledger.parent.mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, rows, extra=()) -> None:
        self.ledger.write_bytes(("\n".join([json.dumps(r) for r in rows] + list(extra)) + "\n").encode("utf-8"))

    def test_limit_is_the_global_rule_three_times(self) -> None:
        self.assertEqual(3.0, RATIO_LIMIT)

    def test_u74_reproduces_the_hand_computed_fail(self) -> None:
        self._write(U74_ROWS)
        result = report(self.root, card="U74", baseline="U67-U73-ACTING", baseline_cards=9)
        self.assertEqual(16_123_467, result["card_usage"]["total_tokens"])
        self.assertEqual(3, result["card_usage"]["rows"])  # U74 x2 + U74-TAIL; U75 is another card
        self.assertEqual({"total_tokens": 3.14, "output_tokens": 2.66}, result["ratios"])
        self.assertEqual("FAIL", result["status"])
        self.assertEqual(["total_tokens"], result["over_limit"])
        self.assertFalse(result["next_card_allowed"])

    def test_within_limit_passes(self) -> None:
        self._write([_row("B", inp=900, out=90), _row("C", inp=250, out=25)])
        result = report(self.root, card="C", baseline="B", baseline_cards=3)
        self.assertEqual("PASS", result["status"])
        self.assertEqual({"total_tokens": 0.83, "output_tokens": 0.83}, result["ratios"])
        self.assertTrue(result["next_card_allowed"])

    def test_output_alone_over_the_limit_fails(self) -> None:
        self._write([_row("B", inp=1000, out=10), _row("C", inp=100, out=40)])
        result = report(self.root, card="C", baseline="B", baseline_cards=1)
        self.assertEqual(["output_tokens"], result["over_limit"])
        self.assertEqual("FAIL", result["status"])

    def test_exactly_three_times_is_not_over(self) -> None:
        self._write([_row("B", inp=100, out=10), _row("C", inp=300, out=30)])
        self.assertEqual("PASS", report(self.root, card="C", baseline="B", baseline_cards=1)["status"])

    def test_card_prefix_does_not_capture_other_cards(self) -> None:
        self._write([_row("B", inp=100, out=10), _row("U7", inp=100, out=10), _row("U70", inp=10**9, out=10**6)])
        result = report(self.root, card="U7", baseline="B", baseline_cards=1)
        self.assertEqual(1, result["card_usage"]["rows"])
        self.assertEqual("PASS", result["status"])

    def test_missing_card_baseline_or_bad_count_is_unknown_not_pass(self) -> None:
        self._write([_row("B", inp=100, out=10)])
        self.assertEqual("UNKNOWN", report(self.root, card="C", baseline="B", baseline_cards=1)["status"])
        self._write([_row("C", inp=100, out=10)])
        self.assertEqual("UNKNOWN", report(self.root, card="C", baseline="B", baseline_cards=1)["status"])
        self._write([_row("B", inp=100, out=10), _row("C", inp=100, out=10)])
        self.assertEqual("UNKNOWN", report(self.root, card="C", baseline="B", baseline_cards=0)["status"])

    def test_read_only_and_malformed_counted(self) -> None:
        self._write(U74_ROWS, extra=("{bad",))
        before = hashlib.sha256(self.ledger.read_bytes()).hexdigest()
        result = report(self.root, card="U74", baseline="U67-U73-ACTING", baseline_cards=9)
        self.assertEqual(before, hashlib.sha256(self.ledger.read_bytes()).hexdigest())
        self.assertEqual(1, result["malformed"])

    def test_exit_code_is_zero_only_on_pass(self) -> None:
        with patch("sys.stdout", new_callable=io.StringIO):
            self._write(U74_ROWS)
            args = ["--project", str(self.root), "--card", "U74", "--baseline", "U67-U73-ACTING"]
            self.assertEqual(1, main(args + ["--baseline-cards", "9"]))
            self.assertEqual(0, main(args + ["--baseline-cards", "1"]))
            self.assertEqual(1, main(["--project", str(self.root), "--card", "NONE", "--baseline", "U67-U73-ACTING",
                                      "--baseline-cards", "9"]))


if __name__ == "__main__":
    unittest.main()
===END===

## Output

- Reply with ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.
