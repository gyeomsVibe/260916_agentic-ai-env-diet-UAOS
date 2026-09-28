```contract
work_id: U81
worker: apply
goal: Keep an apply worker refusal's own cause in the ledger so rsi proposes the right remedy.
inputs:
- .coord/PLAN.md sha256=fe6ef318b41d19a39b9271a9759976d1352110e826c3ae475fb85db44c515657
- v7_harness/pilot.py sha256=be9cf5b2ef182de193a716107b77e88b3f1845522e6cd28e8ecc236907d995b7
- v7_harness/rsi.py sha256=a927d7824baf18ab95b2eb31e3e959ccd7cc97d257e48bb701cef1e6025b6d2b
allow:
- v7_harness/pilot.py
- v7_harness/rsi.py
- tests/test_u81_apply_cause.py
- .coord/PLAN.md
acceptance: python -m unittest tests.test_u81_apply_cause tests.test_u36_evidence_gated_rsi tests.test_b30_no_change_verdict tests.test_u18_accept_triage
forbidden: design changes; edits outside allow; weakening or deleting existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the EDIT blocks exactly and write the new test file as given. No existing test changes.

===EDIT: v7_harness/pilot.py===
<<<<<<< SEARCH
        if execute_error is not None and state == "FAILED":
            detail = f"{type(execute_error).__name__}: {execute_error}"
            summary["error_detail"] = detail[:300]

=======
        if execute_error is not None and state == "FAILED":
            detail = f"{type(execute_error).__name__}: {execute_error}"
            # U81: the engine reports a worker refusal as UNKNOWN_EFFECT_NEEDS_RECONCILIATION; keep the worker's own
            # reason (e.g. UNREQUESTED_DELETION) so rsi does not blame the Ollama service for a deterministic refusal.
            worker_error = _worker_error(raw_stdout)
            if worker_error and worker_error not in detail:
                detail = f"{detail}; worker: {worker_error}"
            summary["error_detail"] = detail[:300]

>>>>>>> REPLACE
===EDIT: v7_harness/pilot.py===
<<<<<<< SEARCH
def _write_summary(path: Path, summary: dict[str, Any]) -> None:
=======
def _worker_error(path: Path) -> str | None:
    """The `error` of a worker's JSON envelope (U81), or None when it is missing or unreadable."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    error = data.get("error") if isinstance(data, dict) else None
    return error if isinstance(error, str) and error else None


def _write_summary(path: Path, summary: dict[str, Any]) -> None:
>>>>>>> REPLACE
===EDIT: v7_harness/rsi.py===
<<<<<<< SEARCH
    error_class = row.get("error_class")
    if error_class and error_class != "NONE":
        return str(error_class)
    detail = str(row.get("error_detail") or "")

=======
    error_class = row.get("error_class")
    detail = str(row.get("error_detail") or "")
    if error_class and error_class != "NONE":
        # U81: a generic worker failure whose detail names a specific cause is that cause (the U80 apply refusal was
        # UNREQUESTED_DELETION, not an Ollama outage). A specific class is never overridden by its detail.
        if error_class in GENERIC_CLASSES:
            for known in REMEDIES:
                if known not in GENERIC_CLASSES and known in detail:
                    return known
        return str(error_class)

>>>>>>> REPLACE
===EDIT: v7_harness/rsi.py===
<<<<<<< SEARCH


class RsiRefused(Exception):
=======

# Classes that say only "the worker failed"; the detail may name the real cause (U81).
GENERIC_CLASSES = ("PROVIDER_ERROR", "EXECUTION_ERROR")


class RsiRefused(Exception):
>>>>>>> REPLACE
===EDIT: .coord/PLAN.md===
<<<<<<< SEARCH
| U80 | DONE-DELEGATED (Codex LIMITED 중 Claude 권한대행 2026-09-28 — Codex 복귀 시 재검토) | claude(대행 설계·판정) · apply(0토큰) | U76-C 반례 수정: 기준 카드 수를 호출자가 고르면 `--baseline-cards 1`로 U74(3.14배)도 통과한다. 기준을 커밋된 `.coord/card_baseline.json`(U67-U73-ACTING, 9카드)에 고정하고, 고정값과 다른 기준은 탐색용(`exploratory`)으로만 보여 주며 종료 코드 1로 다음 카드를 열지 않는다. — `tests/test_u76c_card_cost.py` |

=======
| U80 | DONE-DELEGATED (Codex LIMITED 중 Claude 권한대행 2026-09-28 — Codex 복귀 시 재검토) | claude(대행 설계·판정) · apply(0토큰) | U76-C 반례 수정: 기준 카드 수를 호출자가 고르면 `--baseline-cards 1`로 U74(3.14배)도 통과한다. 기준을 커밋된 `.coord/card_baseline.json`(U67-U73-ACTING, 9카드)에 고정하고, 고정값과 다른 기준은 탐색용(`exploratory`)으로만 보여 주며 종료 코드 1로 다음 카드를 열지 않는다. — `tests/test_u76c_card_cost.py` |
| U81 | DONE-DELEGATED (Codex LIMITED 중 Claude 권한대행 2026-09-28 — Codex 복귀 시 재검토) | claude(대행 설계·판정) · apply(0토큰) | U80 반례 수정: apply 작업자의 결정적 거부(UNREQUESTED_DELETION)가 엔진에서 UNKNOWN_EFFECT_NEEDS_RECONCILIATION → 장부 PROVIDER_ERROR로 바뀌어 `rsi propose`가 Ollama 점검을 권했다. pilot은 작업자 봉투의 `error`를 error_detail에 보존하고, rsi는 일반 분류(PROVIDER_ERROR·EXECUTION_ERROR)일 때만 detail의 구체 원인을 택한다. — `tests/test_u81_apply_cause.py` |

>>>>>>> REPLACE
===FILE: tests/test_u81_apply_cause.py===
"""U81: a deterministic apply refusal keeps its own cause in the ledger instead of looking like an Ollama outage.

Seen 2026-09-28 (U80): the apply worker refused with UNREQUESTED_DELETION, the engine reported
UNKNOWN_EFFECT_NEEDS_RECONCILIATION, the ledger row said PROVIDER_ERROR, and `rsi propose` advised checking the
Ollama service, which the apply worker never calls.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from v7_harness import rsi
from v7_harness.adapters import apply_worker
from v7_harness.pilot import PilotConfig, run_pilot

APPLY = [sys.executable, str(Path(apply_worker.__file__).resolve())]


class ApplyCauseTests(unittest.TestCase):
    def test_an_apply_refusal_is_recorded_as_its_own_cause(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / "proj"
            (source / ".coord").mkdir(parents=True)
            (source / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
            (source / "calc.py").write_text("def mul(a, b):\n    return a * b\n", encoding="utf-8")
            summary = run_pilot(PilotConfig(
                task_id="U81_DEL", title="rewrite", prompt="===FILE: calc.py===\nX = 1\n", source_dir=source,
                work_dir=root / "work", agy_command=APPLY, watch_roots=[], print_timeout_s=60,
                accept_cmd=f'"{sys.executable}" -c "pass"', allowed_scopes=["calc.py"],
            ))
            self.assertNotEqual("PASS", summary["verdict_hint"])
            self.assertIn("UNREQUESTED_DELETION:calc.py:mul", summary["error_detail"])
            row = json.loads((source / ".coord" / "usage" / "runs.jsonl").read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual("UNREQUESTED_DELETION", rsi._cause(row))

    def test_the_u80_ledger_row_proposes_the_manual_remedy(self) -> None:
        row = {"work_id": "U80", "worker": "apply", "outcome": "BLOCKED", "error_class": "PROVIDER_ERROR",
               "error_detail": "WorkerExecutionError: UNKNOWN_EFFECT_NEEDS_RECONCILIATION; worker: "
                               "UNREQUESTED_DELETION:tests/test_u76c_card_cost.py:test_exit_code_is_zero_only_on_pass"}
        self.assertEqual("UNREQUESTED_DELETION", rsi._cause(row))

    def test_a_plain_provider_error_stays_a_provider_error(self) -> None:
        row = {"outcome": "BLOCKED", "error_class": "PROVIDER_ERROR", "error_detail": "connection refused"}
        self.assertEqual("PROVIDER_ERROR", rsi._cause(row))

    def test_a_specific_error_class_is_not_overridden_by_its_detail(self) -> None:
        row = {"outcome": "REWORK", "error_class": "SCOPE_VIOLATION", "error_detail": "SYNTAX_ERROR:a.py:3"}
        self.assertEqual("SCOPE_VIOLATION", rsi._cause(row))


if __name__ == "__main__":
    unittest.main()
===END===

## Output

- Reply with ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.
