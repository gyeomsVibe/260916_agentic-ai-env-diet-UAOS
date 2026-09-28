```contract
work_id: U80-R1
worker: apply
goal: Pin the card-cost baseline in a committed file; caller overrides are exploratory and never pass the gate.
inputs:
- .coord/PLAN.md sha256=679f2c5bbb743d836e97d1fe4b7fedd3c3011a9ea6a9f32cc5ac3fc1e99e12a9
- v7_harness/coord/card_cost.py sha256=01e54c7fbf01ca295635e056569acbd122d8a90f9983aefa5cc2b92963e584d5
- tests/test_u76c_card_cost.py sha256=88caf1b7f218081d6537216b745342d4fbda55423b64e82c64a16c41e9eaf498
allow:
- v7_harness/coord/card_cost.py
- tests/test_u76c_card_cost.py
- .coord/card_baseline.json
- .coord/PLAN.md
acceptance: python -m unittest tests.test_u76c_card_cost tests.test_u79_session_dedup
forbidden: design changes; edits outside allow; weakening or deleting existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Write the files exactly as given and apply the PLAN EDIT. The one changed existing test is made stricter (override no longer passes), not weaker.

===EDIT: .coord/PLAN.md===
<<<<<<< SEARCH
| U79 | DONE-DELEGATED (Codex LIMITED 중 Claude 권한대행 2026-09-28 — Codex 복귀 시 재검토) | claude(대행 설계·판정) · apply(0토큰) | 세션 장부 중복 제거: 압축 뒤 이어진 세션 기록(transcript)은 앞 세션 호출을 복사한다(실측 f117861e가 c2275161의 호출 7건, 사용량 있는 5건 약 44만 토큰 반복). 세션 행에 호출 id의 16자리 해시(`call_digests`)를 남기고, 모든 세션 행에 이미 있는 호출은 건너뛰어 `duplicate_calls_skipped`로 보고한다. 원래 id는 저장하지 않는다. — `tests/test_u79_session_dedup.py` |
=======
| U79 | DONE-DELEGATED (Codex LIMITED 중 Claude 권한대행 2026-09-28 — Codex 복귀 시 재검토) | claude(대행 설계·판정) · apply(0토큰) | 세션 장부 중복 제거: 압축 뒤 이어진 세션 기록(transcript)은 앞 세션 호출을 복사한다(실측 f117861e가 c2275161의 호출 7건, 사용량 있는 5건 약 44만 토큰 반복). 세션 행에 호출 id의 16자리 해시(`call_digests`)를 남기고, 모든 세션 행에 이미 있는 호출은 건너뛰어 `duplicate_calls_skipped`로 보고한다. 원래 id는 저장하지 않는다. — `tests/test_u79_session_dedup.py` |
| U80 | DONE-DELEGATED (Codex LIMITED 중 Claude 권한대행 2026-09-28 — Codex 복귀 시 재검토) | claude(대행 설계·판정) · apply(0토큰) | U76-C 반례 수정: 기준 카드 수를 호출자가 고르면 `--baseline-cards 1`로 U74(3.14배)도 통과한다. 기준을 커밋된 `.coord/card_baseline.json`(U67-U73-ACTING, 9카드)에 고정하고, 고정값과 다른 기준은 탐색용(`exploratory`)으로만 보여 주며 종료 코드 1로 다음 카드를 열지 않는다. — `tests/test_u76c_card_cost.py` |
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
# U80: the baseline is pinned in a reviewed, committed file. A caller-chosen card count could make any card pass
# (--baseline-cards 1 raises the average nine-fold), so a baseline that differs from the pin is only exploratory.
BASELINE_FILE = Path(".coord") / "card_baseline.json"


def pinned_baseline(project: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((Path(project) / BASELINE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("baseline"), str) or not data["baseline"]:
        return None
    cards = data.get("baseline_cards")
    if not isinstance(cards, int) or isinstance(cards, bool) or cards < 1:
        return None
    return {"baseline": data["baseline"], "baseline_cards": cards}
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
    parser.add_argument("--baseline", help="Exploratory: exact work_id of the baseline row(s); default is the pin")
    parser.add_argument("--baseline-cards", type=int, help="Exploratory: cards the baseline covered; default is the pin")
    args = parser.parse_args(argv)
    project = Path(args.project)
    pin = pinned_baseline(project)
    baseline = args.baseline if args.baseline is not None else (pin or {}).get("baseline")
    cards = args.baseline_cards if args.baseline_cards is not None else (pin or {}).get("baseline_cards")
    if not baseline or cards is None:
        result: dict[str, Any] = {"card": args.card, "status": "UNKNOWN", "pinned": pin,
                                  "reason": f"no valid pinned baseline in {BASELINE_FILE.as_posix()}"}
    else:
        result = report(project, card=args.card, baseline=baseline, baseline_cards=cards)
        result["pinned"] = pin
        result["exploratory"] = pin is None or pin != {"baseline": baseline, "baseline_cards": cards}
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    # Exit 0 only on PASS against the pinned baseline: FAIL, UNKNOWN and exploratory runs keep the next card closed.
    return 0 if result["status"] == "PASS" and not result.get("exploratory", True) else 1


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

    def _pin(self, text: str) -> None:
        (self.root / ".coord" / "card_baseline.json").write_text(text, encoding="utf-8")

    def test_exit_code_is_zero_only_on_pass(self) -> None:
        with patch("sys.stdout", new_callable=io.StringIO) as out:
            self._write(U74_ROWS + [_row("U80", inp=1_000_000, out=10_000)])
            project = ["--project", str(self.root)]
            self.assertEqual(1, main(project + ["--card", "U80"]))  # no pin: UNKNOWN
            self._pin(json.dumps({"baseline": "U67-U73-ACTING", "baseline_cards": 9}))
            self.assertEqual(0, main(project + ["--card", "U80"]))
            self.assertEqual(1, main(project + ["--card", "U74"]))  # 3.14x FAIL
            self.assertEqual(1, main(project + ["--card", "NONE"]))
            # U80 red team: choosing a smaller card count would make U74 pass; an override is exploratory only.
            out.seek(0)
            out.truncate()
            self.assertEqual(1, main(project + ["--card", "U74", "--baseline-cards", "1"]))
            shown = json.loads(out.getvalue())
            self.assertEqual("PASS", shown["status"])
            self.assertTrue(shown["exploratory"])

    def test_a_malformed_pin_is_unknown(self) -> None:
        with patch("sys.stdout", new_callable=io.StringIO):
            self._write(U74_ROWS)
            for text in ("{bad", json.dumps({"baseline": "U67-U73-ACTING", "baseline_cards": 0}),
                         json.dumps({"baseline": "", "baseline_cards": 9}), json.dumps([1])):
                self._pin(text)
                self.assertEqual(1, main(["--project", str(self.root), "--card", "U74"]), text)

    def test_the_committed_pin_is_the_u72_baseline(self) -> None:
        pin = json.loads((Path(__file__).resolve().parents[1] / ".coord" / "card_baseline.json").read_text("utf-8"))
        self.assertEqual(("U67-U73-ACTING", 9), (pin["baseline"], pin["baseline_cards"]))


if __name__ == "__main__":
    unittest.main()
===FILE: .coord/card_baseline.json===
{
  "baseline": "U67-U73-ACTING",
  "baseline_cards": 9,
  "why": "U72/U74 (docs/62): the acting session row that covered 9 cards U67-U73; the average per card is the 3x yardstick. Change only by a reviewed commit."
}
===END===

## Output

- Reply with ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.
