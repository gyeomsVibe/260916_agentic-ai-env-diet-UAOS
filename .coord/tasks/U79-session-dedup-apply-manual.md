```contract
work_id: U79
worker: apply
goal: Session usage rows count a call copied into a continued session transcript only once.
inputs:
- .coord/PLAN.md sha256=25a30615b20ae4508e2ee9396a6ab672af925a6c74c16141af01fbe1ab84d333
- v7_harness/coord/session_usage.py sha256=1d3fc5fb344e1c5d7dcc2115df0cd8a453b4fc7451ddd0735716c1b1d905570a
allow:
- v7_harness/coord/session_usage.py
- tests/test_u79_session_dedup.py
- .coord/PLAN.md
acceptance: python -m unittest tests.test_u79_session_dedup tests.test_u73_session_usage tests.test_u76c_card_cost
forbidden: design changes; edits outside allow; weakening or deleting existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the EDIT blocks exactly and write the new test file as given.

===EDIT: v7_harness/coord/session_usage.py===
<<<<<<< SEARCH
import json
import os

=======
import hashlib
import json
import os

>>>>>>> REPLACE
===EDIT: v7_harness/coord/session_usage.py===
<<<<<<< SEARCH
def _seconds(start: str, end: str) -> float:
=======
def _digest(call_id: str) -> str:
    # A short hash, not the raw id: rows stay free of provider ids; 64 bits make a collision across one ledger negligible.
    return hashlib.sha256(call_id.encode("utf-8")).hexdigest()[:16]


def _recorded_digests(ledger: Path) -> set[str]:
    """Call digests of every session row (U79): a continued session's transcript repeats calls of its parent."""
    seen: set[str] = set()
    for line in _rows(ledger):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("kind") == "session" and isinstance(row.get("call_digests"), list):
            seen.update(str(item) for item in row["call_digests"])
    return seen


def _seconds(start: str, end: str) -> float:
>>>>>>> REPLACE
===EDIT: v7_harness/coord/session_usage.py===
<<<<<<< SEARCH
        window = sorted((call for call in calls.values() if call["ts"] > since), key=lambda call: call["ts"])
        if not window:
            return {"ledger": str(ledger), "session_id": session_id, "since": since or None, "api_calls": 0,
                    "mode": "NOTHING_NEW", "appended": 0}
=======
        seen = _recorded_digests(ledger)
        fresh = {_digest(key): call for key, call in calls.items() if call["ts"] > since}
        skipped = sum(1 for digest in fresh if digest in seen)
        fresh = {digest: call for digest, call in fresh.items() if digest not in seen}
        window = sorted(fresh.values(), key=lambda call: call["ts"])
        if not window:
            return {"ledger": str(ledger), "session_id": session_id, "since": since or None, "api_calls": 0,
                    "mode": "NOTHING_NEW", "appended": 0, "duplicate_calls_skipped": skipped}
>>>>>>> REPLACE
===EDIT: v7_harness/coord/session_usage.py===
<<<<<<< SEARCH
            "api_calls": len(window),

=======
            "api_calls": len(window), "call_digests": sorted(fresh),

>>>>>>> REPLACE
===EDIT: v7_harness/coord/session_usage.py===
<<<<<<< SEARCH
            "appended": 1 if apply else 0, **{key: row[key] for key in (
=======
            "appended": 1 if apply else 0, "duplicate_calls_skipped": skipped, **{key: row[key] for key in (
>>>>>>> REPLACE
===EDIT: .coord/PLAN.md===
<<<<<<< SEARCH
| U76-C | DONE-DELEGATED (Codex LIMITED 중 Claude 권한대행 2026-09-28 — 설계·판정 동일 계보, Codex 복귀 시 재검토) | claude(대행 설계·판정) · apply(0토큰) | 카드별 3배 비용 관문을 결정적으로 계산: 카드 행(`<card>`, `<card>-*`) 합 ÷ (기준 work_id 합 ÷ 기준 카드 수). 총 토큰·출력 중 하나라도 3배 초과면 FAIL, 자료 없음은 UNKNOWN, 둘 다 종료 코드 1로 다음 카드를 열지 않는다. U74 실측 3.14배 FAIL 재현. `python -m v7_harness.coord.card_cost --card <id> --baseline <id> --baseline-cards <n>` — `tests/test_u76c_card_cost.py` |
=======
| U76-C | DONE-DELEGATED (Codex LIMITED 중 Claude 권한대행 2026-09-28 — 설계·판정 동일 계보, Codex 복귀 시 재검토) | claude(대행 설계·판정) · apply(0토큰) | 카드별 3배 비용 관문을 결정적으로 계산: 카드 행(`<card>`, `<card>-*`) 합 ÷ (기준 work_id 합 ÷ 기준 카드 수). 총 토큰·출력 중 하나라도 3배 초과면 FAIL, 자료 없음은 UNKNOWN, 둘 다 종료 코드 1로 다음 카드를 열지 않는다. U74 실측 3.14배 FAIL 재현. `python -m v7_harness.coord.card_cost --card <id> --baseline <id> --baseline-cards <n>` — `tests/test_u76c_card_cost.py` |
| U79 | DONE-DELEGATED (Codex LIMITED 중 Claude 권한대행 2026-09-28 — Codex 복귀 시 재검토) | claude(대행 설계·판정) · apply(0토큰) | 세션 장부 중복 제거: 압축 뒤 이어진 세션 기록(transcript)은 앞 세션 호출을 복사한다(실측 f117861e가 c2275161의 호출 7건, 사용량 있는 5건 약 44만 토큰 반복). 세션 행에 호출 id의 16자리 해시(`call_digests`)를 남기고, 모든 세션 행에 이미 있는 호출은 건너뛰어 `duplicate_calls_skipped`로 보고한다. 원래 id는 저장하지 않는다. — `tests/test_u79_session_dedup.py` |
>>>>>>> REPLACE
===FILE: tests/test_u79_session_dedup.py===
"""U79: a call copied into a continued session's transcript is counted once across sessions.

Seen 2026-09-28: session f117861e (continued after compaction) repeated 7 message ids of session c2275161, 5 of them
with usage (about 442k tokens). U73 deduplicated only within one session, so recording both double-counted them.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord.session_usage import record_session


def _call(message_id: str, stamp: str, out: int) -> str:
    usage = {"input_tokens": 2, "output_tokens": out, "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 10}
    return json.dumps({"type": "assistant", "timestamp": stamp,
                       "message": {"id": message_id, "model": "claude-opus-5-5", "usage": usage}})


class SessionDedupTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / ".coord").mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _transcript(self, name: str, calls: list[str]) -> Path:
        path = self.root / f"{name}.jsonl"
        path.write_text("".join(line + "\n" for line in calls), encoding="utf-8")
        return path

    def _rows(self) -> list[dict]:
        path = self.root / ".coord" / "usage" / "runs.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

    def test_calls_copied_into_a_continued_session_are_not_counted_twice(self) -> None:
        first = self._transcript("sess-a", [_call("m1", "2026-09-28T00:00:01.000Z", 100),
                                            _call("m2", "2026-09-28T00:00:02.000Z", 50)])
        second = self._transcript("sess-b", [_call("m2", "2026-09-28T00:00:02.000Z", 50),  # copied from sess-a
                                             _call("m3", "2026-09-28T00:00:03.000Z", 7)])
        record_session(self.root, first, work_id="W", apply=True)
        result = record_session(self.root, second, work_id="W", apply=True)
        self.assertEqual(1, result["api_calls"])
        self.assertEqual(7, result["output_tokens"])
        self.assertEqual(1, result["duplicate_calls_skipped"])
        self.assertEqual(157, sum(row["output_tokens"] for row in self._rows()))

    def test_a_continued_session_of_only_copied_calls_records_nothing(self) -> None:
        first = self._transcript("sess-a", [_call("m1", "2026-09-28T00:00:01.000Z", 100)])
        second = self._transcript("sess-b", [_call("m1", "2026-09-28T00:00:01.000Z", 100)])
        record_session(self.root, first, work_id="W", apply=True)
        result = record_session(self.root, second, work_id="W", apply=True)
        self.assertEqual("NOTHING_NEW", result["mode"])
        self.assertEqual(1, len(self._rows()))

    def test_rows_keep_call_digests_not_raw_message_ids(self) -> None:
        first = self._transcript("sess-a", [_call("msg_secretlooking123", "2026-09-28T00:00:01.000Z", 1)])
        record_session(self.root, first, work_id="W", apply=True)
        row = self._rows()[0]
        self.assertEqual(1, len(row["call_digests"]))
        self.assertEqual(16, len(row["call_digests"][0]))
        self.assertNotIn("msg_secretlooking123", json.dumps(row))

    def test_dry_run_reports_the_skip_and_writes_nothing(self) -> None:
        first = self._transcript("sess-a", [_call("m1", "2026-09-28T00:00:01.000Z", 100)])
        second = self._transcript("sess-b", [_call("m1", "2026-09-28T00:00:01.000Z", 100),
                                             _call("m9", "2026-09-28T00:00:09.000Z", 3)])
        record_session(self.root, first, work_id="W", apply=True)
        result = record_session(self.root, second, work_id="W")
        self.assertEqual("DRY_RUN", result["mode"])
        self.assertEqual(1, result["duplicate_calls_skipped"])
        self.assertEqual(1, len(self._rows()))


if __name__ == "__main__":
    unittest.main()
===END===

## Output

- Reply with ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.
