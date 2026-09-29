```contract
work_id: U88
worker: apply
goal: Drop a BLOCKED message from the P1 wake once the ledger shows its step (or its -R<n> retry) passed later.
inputs:
- .coord/PLAN.md sha256=b82edd7425e50186d2040d2cac666801f045efd8a54021c47b0f133c6b268ce4
- v7_harness/coord/sentinel.py sha256=b4cf508dd455b6cd6ade2f7d9d9c17811cae705c8a8fc552a64032673066e25b
allow:
- v7_harness/coord/sentinel.py
- tests/test_u88_p1_superseded.py
- .coord/PLAN.md
acceptance: python -m unittest tests.test_u88_p1_superseded tests.test_u32_sentinel_bell tests.test_u23_mailbox tests.test_u36_evidence_gated_rsi
forbidden: design changes; edits outside allow; weakening or deleting existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the EDIT blocks exactly. The new test pins which BLOCKED messages leave the P1 wake and which stay.

===EDIT: v7_harness/coord/sentinel.py===
<<<<<<< SEARCH


def run_sentinel_cycle(

=======


def _last_pass_by_step(project_root: Path) -> dict[str, float]:
    """U88: latest ledger PASS time per step; a `-R<n>` retry also counts for the step it retries.

    Seen 2026-09-29: the P1 wake still listed U80 and U86 after U80-R1 and U86-R1 passed, and it grew with every BLOCKED
    message ever sent, so the one P1 at each session start carried no signal. An unreadable ledger proves nothing.
    """
    import re

    try:
        from ..rsi import load_rows

        rows = load_rows(project_root)
    except Exception:  # noqa: BLE001 - no evidence means every alert stays
        return {}
    passed: dict[str, float] = {}
    for row in rows:
        work_id, ts = row.get("work_id"), row.get("ts")
        if row.get("outcome") != "PASS" or not isinstance(work_id, str):
            continue
        if not isinstance(ts, (int, float)) or isinstance(ts, bool):
            continue
        for step in {work_id, re.sub(r"-R\d+$", "", work_id)}:
            passed[step] = max(passed.get(step, 0.0), float(ts))
    return passed


def _passed_since(passed: dict[str, float], payload: dict[str, Any]) -> bool:
    """U88: the message's own step passed after the message was written. A missing or unreadable time keeps the alert."""
    from datetime import datetime

    step, stamp = payload.get("step"), payload.get("ts")
    if not isinstance(step, str) or step not in passed or not isinstance(stamp, str):
        return False
    try:
        blocked_at = datetime.fromisoformat(stamp).timestamp()
    except ValueError:
        return False
    return passed[step] > blocked_at


def run_sentinel_cycle(

>>>>>>> REPLACE
===EDIT: v7_harness/coord/sentinel.py===
<<<<<<< SEARCH
    # Read only. Claiming to look hid each message from real consumers for the length of the check.
    for msg_id, payload in box.peek():

=======
    passed = _last_pass_by_step(project_root)
    p1_superseded: list[str] = []
    # Read only. Claiming to look hid each message from real consumers for the length of the check.
    for msg_id, payload in box.peek():

>>>>>>> REPLACE
===EDIT: v7_harness/coord/sentinel.py===
<<<<<<< SEARCH
        if payload.get("kind") == "BLOCKED" or payload.get("is_p1"):
            p1_reasons.append(f"BLOCKED_TASK: {payload.get('step')}")

=======
        if payload.get("kind") == "BLOCKED" and not payload.get("is_p1") and _passed_since(passed, payload):
            p1_superseded.append(str(payload.get("step")))
            continue
        if payload.get("kind") == "BLOCKED" or payload.get("is_p1"):
            p1_reasons.append(f"BLOCKED_TASK: {payload.get('step')}")

>>>>>>> REPLACE
===EDIT: v7_harness/coord/sentinel.py===
<<<<<<< SEARCH
        "p1_wake_emitted": p1_wake_emitted,

=======
        "p1_wake_emitted": p1_wake_emitted,
        "p1_superseded": sorted(set(p1_superseded)),

>>>>>>> REPLACE
===EDIT: .coord/PLAN.md===
<<<<<<< SEARCH
| U87 | DONE-DELEGATED (Codex LIMITED 중 Claude 권한대행 2026-09-29 — Codex 복귀 시 재검토) | claude(대행 설계) · apply(0토큰) | 윤겸스 지시(2026-09-29): 정식 명칭 UAOS-RSI, 모든 agentic AI 환경의 기본 운영체제, 도구별 역할·토큰 예산. 전역 규칙 정본 v6.0.0(platform PR #5)과 같은 내용을 정본이 없는 PC에 설치되는 이식용 규칙 블록·도구 어댑터에도 반영. — `uaos_everywhere/uaos_global_rule_block.md`, `uaos_everywhere/adapters/*.md`, `tests/test_u87_uaos_rsi_name.py` |

=======
| U87 | DONE-DELEGATED (Codex LIMITED 중 Claude 권한대행 2026-09-29 — Codex 복귀 시 재검토) | claude(대행 설계) · apply(0토큰) | 윤겸스 지시(2026-09-29): 정식 명칭 UAOS-RSI, 모든 agentic AI 환경의 기본 운영체제, 도구별 역할·토큰 예산. 전역 규칙 정본 v6.0.0(platform PR #5)과 같은 내용을 정본이 없는 PC에 설치되는 이식용 규칙 블록·도구 어댑터에도 반영. — `uaos_everywhere/uaos_global_rule_block.md`, `uaos_everywhere/adapters/*.md`, `tests/test_u87_uaos_rsi_name.py` |
| U88 | DONE-DELEGATED (Codex LIMITED 중 Claude 권한대행 2026-09-29 — Codex 복귀 시 재검토) | claude(대행 설계) · apply(0토큰) | 실사용 영수증(2026-09-29): 세션 시작마다 뜨는 P1 경보가 U80-R1·U86-R1 통과 뒤에도 U80·U86을 BLOCKED로 나열하고 모든 과거 BLOCKED를 누적해 신호가 없었다. 장부의 PASS(같은 단계 또는 -R<n> 재시도)가 메시지 시각보다 늦으면 그 BLOCKED는 P1에서 빼고 `p1_superseded`로 공개한다. 명시적 is_p1·시각 불명·다른 단계는 유지. — `v7_harness/coord/sentinel.py`, `tests/test_u88_p1_superseded.py` |

>>>>>>> REPLACE
===FILE: tests/test_u88_p1_superseded.py===
"""U88: a BLOCKED message whose step later passed (itself or its -R<n> retry) no longer raises the P1 wake.

Seen 2026-09-29: the sentinel's P1 wake listed U80 and U86 after U80-R1 and U86-R1 had passed, and it grew with every
BLOCKED message ever sent, so the single P1 shown at every session start carried no signal. The ledger PASS row, later
than the message, is the evidence; anything unproven keeps its alert.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from v7_harness.coord.mailbox import Mailbox
from v7_harness.coord.sentinel import run_sentinel_cycle

BLOCKED_AT = "2026-09-29T11:44:32+09:00"
BEFORE = datetime.fromisoformat(BLOCKED_AT).timestamp() - 60
AFTER = datetime.fromisoformat(BLOCKED_AT).timestamp() + 60


def _project(directory: str, rows: list[dict]) -> tuple[Path, Mailbox]:
    root = Path(directory)
    (root / ".coord" / "mailbox").mkdir(parents=True)
    ledger = root / ".coord" / "usage" / "runs.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return root, Mailbox(root / ".coord" / "mailbox")


def _pass(work_id: str, ts: float) -> dict:
    return {"kind": "pilot", "work_id": work_id, "outcome": "PASS", "worker": "apply", "ts": ts}


def _blocked(step: str) -> dict:
    return {"kind": "BLOCKED", "step": step, "ts": BLOCKED_AT, "actor": "claude"}


class SupersededBlockTests(unittest.TestCase):
    def test_a_passed_retry_clears_the_block(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root, box = _project(d, [_pass("U86-R1", AFTER), _pass("U80", AFTER)])
            box.publish("b86", _blocked("U86"))
            box.publish("b80", _blocked("U80"))
            result = run_sentinel_cycle(root, box)
            self.assertFalse(result["p1_wake_emitted"])
            self.assertEqual(["U80", "U86"], result["p1_superseded"])

    def test_a_pass_before_the_block_or_of_another_step_keeps_the_alert(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root, box = _project(d, [_pass("U86", BEFORE), _pass("U860-R1", AFTER), _pass("U86-F1", AFTER)])
            box.publish("b86", _blocked("U86"))
            result = run_sentinel_cycle(root, box)
            self.assertTrue(result["p1_wake_emitted"])
            self.assertEqual([], result["p1_superseded"])

    def test_a_block_without_a_readable_time_keeps_the_alert(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root, box = _project(d, [_pass("U86", AFTER)])
            box.publish("b86", {"kind": "BLOCKED", "step": "U86", "ts": "yesterday"})
            self.assertTrue(run_sentinel_cycle(root, box)["p1_wake_emitted"])

    def test_an_explicit_p1_is_never_cleared_by_the_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root, box = _project(d, [_pass("U86", AFTER)])
            box.publish("p86", {"kind": "NOTE", "is_p1": True, "step": "U86", "ts": BLOCKED_AT})
            self.assertTrue(run_sentinel_cycle(root, box)["p1_wake_emitted"])


if __name__ == "__main__":
    unittest.main()
===END===

## Output

- Reply with ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.
