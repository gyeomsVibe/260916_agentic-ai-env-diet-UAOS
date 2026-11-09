"""U276: 3-Tool Commit-Gate Independent Reviewer Routing, B85 Hard-Cap Review & Mediator Anti-Wait Tests."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from v7_harness.calculator_gate import (
    JUDGE_TOOL_NAMES,
    LOCAL_AUTHORS,
    NATIVE_JUDGES,
    REVIEWERS,
    audit_errors,
    author_tool,
    check,
)
from v7_harness.disjoint_mediator import (
    PAID_TOOLS_3,
    detect_and_break_3tool_wait_cycles,
    dispatch_nonstop_3tool_tiki_taka,
)
from v7_harness.review import REVIEWERS as PILOT_REVIEWERS, ReviewRefused, run_review

GATED_FILE = "v7_harness/sample_u276.py"
SAMPLE_CODE = b"def compute_total(x: int, y: int) -> int:\n    return x + y\n"
SAMPLE_BUNDLE = "d" * 64


class CommitGateReviewerSelectionTest(unittest.TestCase):
    def test_gate_and_review_exports_registered(self) -> None:
        self.assertEqual(("agy", "codex"), REVIEWERS)
        self.assertEqual(("claude", "agy"), PILOT_REVIEWERS)
        self.assertEqual(("codex", "claude", "antigravity"), PAID_TOOLS_3)
        self.assertIn("ollama", LOCAL_AUTHORS)
        self.assertEqual("antigravity", JUDGE_TOOL_NAMES["agy"])
        self.assertEqual("agy", NATIVE_JUDGES["antigravity"])
        self.assertEqual("codex", NATIVE_JUDGES["codex"])

    def test_author_tool_from_branch_prefix(self) -> None:
        self.assertEqual("antigravity", author_tool("agy/u311-u318-nonstop-sustain"))
        self.assertEqual("antigravity", author_tool("antigravity/u276"))
        self.assertEqual("claude", author_tool("claude/u276-review"))
        self.assertEqual("codex", author_tool("codex/u276-fix"))
        self.assertIsNone(author_tool("main"))

    def test_audit_errors_accepts_non_author_peer_and_rejects_self_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ack_dir = root / "mailbox" / "ack"
            delivery_dir = root / "mailbox" / "delivery"
            ack_dir.mkdir(parents=True, exist_ok=True)
            delivery_dir.mkdir(parents=True, exist_ok=True)
            agy_auto = delivery_dir / "agy_auto.jsonl"
            agy_auto.write_text("", encoding="utf-8")

            relay_id = "relay_11112222333344445555666677778888"
            (ack_dir / f"{relay_id}.json").write_text(
                json.dumps({"payload": {"actor": "claude", "verdict": "PASS"}}),
                encoding="utf-8",
            )

            # Non-author (codex or antigravity) audited by claude -> PASS (0 errors)
            self.assertEqual(
                [],
                audit_errors(f"fix: u276\n\nAudit: {relay_id}\n", [GATED_FILE], agy_auto, author="codex"),
            )
            self.assertEqual(
                [],
                audit_errors(f"fix: u276\n\nAudit: {relay_id}\n", [GATED_FILE], agy_auto, author="antigravity"),
            )
            # Self-audit (claude author audited by claude) -> rejected
            errs_self = audit_errors(f"fix: u276\n\nAudit: {relay_id}\n", [GATED_FILE], agy_auto, author="claude")
            self.assertEqual(1, len(errs_self))
            self.assertIn("self-audit forbidden", errs_self[0])

            # Provenance CONFLICT -> rejected
            errs_conflict = audit_errors(f"fix: u276\n\nAudit: {relay_id}\n", [GATED_FILE], agy_auto, author="CONFLICT")
            self.assertEqual(1, len(errs_conflict))
            self.assertIn("CONFLICT", errs_conflict[0])


class CommitGateReviewVerificationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.pd = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _stage_bundle(self, task: str, *, reviewer: str, review_payload: dict) -> None:
        run_dir = self.pd / "runs" / task
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "summary.json").write_text(
            json.dumps({
                "state": "SUCCEEDED",
                "verdict_hint": "PASS",
                "promotion": "APPLIED",
                "bundle_id": SAMPLE_BUNDLE,
                "changed_files": [GATED_FILE],
            }),
            encoding="utf-8",
        )
        stg = self.pd / "stage" / task / GATED_FILE
        stg.parent.mkdir(parents=True, exist_ok=True)
        stg.write_bytes(SAMPLE_CODE)
        (run_dir / f"review_{reviewer}.json").write_text(
            json.dumps(review_payload),
            encoding="utf-8",
        )

    def test_independent_review_passes_commit_gate_for_ollama_author(self) -> None:
        self._stage_bundle(
            "U276-L1",
            reviewer="agy",
            review_payload={
                "verdict": "PASS",
                "bundle_id": SAMPLE_BUNDLE,
                "author_worker": "ollama",
            },
        )
        violations = check({GATED_FILE: SAMPLE_CODE}, "fix: u276", self.pd)
        self.assertEqual([], violations)

    def test_self_review_is_rejected_by_commit_gate(self) -> None:
        self._stage_bundle(
            "U276-SELF1",
            reviewer="agy",
            review_payload={
                "verdict": "PASS",
                "bundle_id": SAMPLE_BUNDLE,
                "author_worker": "antigravity",
            },
        )
        ledger = [{"work_id": "U276-SELF1", "worker": "ollama", "outcome": "FAIL", "input_tokens": 900}]
        violations = check({GATED_FILE: SAMPLE_CODE}, "fix: self", self.pd, ledger_rows=ledger)
        self.assertEqual(1, len(violations))


class ReviewB85HardCapAndFlagmanAntiWaitTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / ".coord" / "presence").mkdir(parents=True, exist_ok=True)
        (self.root / "v7_harness").mkdir(parents=True, exist_ok=True)
        (self.root / GATED_FILE).write_bytes(b"def compute_total(x: int, y: int) -> int:\n    return x\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _prepare_pilot_bundle(self, task_id: str, author: str = "ollama") -> Path:
        work_dir = self.root / ".coord" / "pilot"
        run_dir = work_dir / "runs" / task_id
        stg_dir = work_dir / "stage" / task_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (stg_dir / "v7_harness").mkdir(parents=True, exist_ok=True)
        (stg_dir / GATED_FILE).write_bytes(SAMPLE_CODE)
        (run_dir / "worker").write_text(f"{author}\n", encoding="utf-8")
        (run_dir / "summary.json").write_text(
            json.dumps({
                "state": "SUCCEEDED",
                "verdict_hint": "PASS",
                "promotion": "APPLIED",
                "bundle_id": SAMPLE_BUNDLE,
                "changed_files": [GATED_FILE],
                "agy_workspace": str(stg_dir),
            }),
            encoding="utf-8",
        )
        return work_dir

    def test_run_review_enforces_b85_budget_usd_and_non_author_invariants(self) -> None:
        work_dir = self._prepare_pilot_bundle("U276-B85", author="ollama")

        # Missing token budget -> refused before spending
        with self.assertRaises(ReviewRefused) as ctx_budget:
            run_review(
                task_id="U276-B85",
                work_dir=work_dir,
                source=self.root,
                manual_text="contract:\n  work_id: U276-B85\n",
                reviewer="claude",
                budget=0,
                budget_usd=0.25,
            )
        self.assertIn("REVIEW_WITHOUT_BUDGET", str(ctx_budget.exception))

        # Claude review without USD cap -> refused before spending
        with self.assertRaises(ReviewRefused) as ctx_usd:
            run_review(
                task_id="U276-B85",
                work_dir=work_dir,
                source=self.root,
                manual_text="contract:\n  work_id: U276-B85\n",
                reviewer="claude",
                budget=28000,
                budget_usd=0.0,
            )
        self.assertIn("REVIEW_WITHOUT_USD_CAP", str(ctx_usd.exception))

        # Self-review -> refused before spending
        work_dir_self = self._prepare_pilot_bundle("U276-SELF-REV", author="claude")
        with self.assertRaises(ReviewRefused) as ctx_self:
            run_review(
                task_id="U276-SELF-REV",
                work_dir=work_dir_self,
                source=self.root,
                manual_text="contract:\n  work_id: U276-SELF-REV\n",
                reviewer="claude",
                budget=28000,
                budget_usd=0.25,
            )
        self.assertIn("REVIEWER_IS_AUTHOR", str(ctx_self.exception))

        # Valid independent Claude review under explicit token and USD caps -> PASS & WITHIN
        def fake_runner(argv, **kwargs):
            payload = {
                "result": json.dumps({
                    "verdict": "PASS",
                    "counterexamples": [],
                    "evidence_lines": ["v7_harness/sample_u276.py:2 return x + y"],
                }),
                "usage": {"input_tokens": 200, "output_tokens": 80, "cache_creation_input_tokens": 1200},
                "total_cost_usd": 0.012,
            }
            return subprocess.CompletedProcess(argv, 0, json.dumps(payload).encode("utf-8"), b"")

        rec = run_review(
            task_id="U276-B85",
            work_dir=work_dir,
            source=self.root,
            manual_text="contract:\n  work_id: U276-B85\n",
            reviewer="claude",
            budget=28000,
            budget_usd=0.25,
            runner=fake_runner,
        )
        self.assertEqual("PASS", rec["verdict"])
        self.assertEqual("claude", rec["reviewer"])
        self.assertEqual("WITHIN", rec["cost_gate"])
        self.assertTrue(rec["advisory"])

    def test_flagman_never_fabricates_synthetic_review_and_routes_non_author(self) -> None:
        pdir = self.root / ".coord" / "pilot"
        run_dir = pdir / "runs" / "U276-STALL"
        stg_dir = pdir / "stage" / "U276-STALL"
        run_dir.mkdir(parents=True, exist_ok=True)
        (stg_dir / "v7_harness").mkdir(parents=True, exist_ok=True)
        (stg_dir / GATED_FILE).write_bytes(SAMPLE_CODE)
        (run_dir / "worker").write_text("apply\n", encoding="utf-8")
        (run_dir / "summary.json").write_text(
            json.dumps({
                "state": "SUCCEEDED",
                "verdict_hint": "PASS",
                "promotion": "APPLIED",
                "bundle_id": SAMPLE_BUNDLE,
                "changed_files": [GATED_FILE],
            }),
            encoding="utf-8",
        )
        (run_dir / "review_agy.json").write_text(
            json.dumps({
                "task_id": "U276-STALL",
                "reviewer": "agy",
                "author_worker": "apply",
                "bundle_id": SAMPLE_BUNDLE,
                "verdict": "UNUSABLE",
                "cost_gate": "EXCEEDED:18105>12000",
            }),
            encoding="utf-8",
        )
        ledger = [{"work_id": "U276-STALL", "worker": "ollama", "outcome": "FAIL", "input_tokens": 950}]

        heal_res = detect_and_break_3tool_wait_cycles(self.root, auto_heal=True)
        self.assertIn("flagman_action", heal_res)
        # Ensure Flagman never injected a synthetic passing review file
        self.assertFalse((run_dir / "review_codex.json").exists())
        self.assertEqual(1, len(check({GATED_FILE: SAMPLE_CODE}, "fix: stall", pdir, ledger_rows=ledger)))

        dispatch = dispatch_nonstop_3tool_tiki_taka(
            presence_states={"codex": "ACTIVE", "claude": "ACTIVE", "antigravity": "ACTIVE"},
            ready_cards=[{"phase_id": "U276", "owner_tool": "antigravity", "state": "READY"}],
        )
        self.assertEqual(0, dispatch["wait_ms"])
        self.assertEqual(1, len(dispatch["card_assignments"]))
        self.assertNotEqual(
            dispatch["card_assignments"][0]["owner"],
            dispatch["card_assignments"][0]["reviewer"],
        )


if __name__ == "__main__":
    unittest.main()
