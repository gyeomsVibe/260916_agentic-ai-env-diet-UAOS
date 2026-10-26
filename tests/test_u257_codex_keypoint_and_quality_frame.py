"""U257: Tests for UAOS-RSI Core Founding Principle (Supreme Quality Frame) & Codex $20 Plus Astra Keypoint Routing."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord.agy_moderator import (
    CODEX_EXCLUSIVE_KEYPOINTS,
    UAOS_CORE_FINANCIAL_FRAME,
    UAOS_CORE_FOUNDING_PRINCIPLE,
    AntigravityModerator,
    is_codex_exclusive_keypoint,
    verify_supreme_quality_gate,
)


class TestU257CodexKeypointAndQualityFrame(unittest.TestCase):
    def test_1_core_founding_principle_and_financial_frame_constants(self) -> None:
        self.assertIn("최대 성과를 목표로 3대 AI 도구", UAOS_CORE_FOUNDING_PRINCIPLE)
        self.assertIn("결과물의 최상의 품질기준이 근본 존재이유이다", UAOS_CORE_FOUNDING_PRINCIPLE)
        self.assertIn("사용량 제한 및 구독제 업그레이드의 재정적 부담", UAOS_CORE_FINANCIAL_FRAME)
        self.assertTrue({"architectural_core", "security_boundary", "rsi_canon"}.issubset(CODEX_EXCLUSIVE_KEYPOINTS))

    def test_2_is_codex_exclusive_keypoint_distinguishes_core_vs_routine(self) -> None:
        self.assertTrue(is_codex_exclusive_keypoint({"phase_id": "U257-ARCH", "codex_keypoint": True}))
        self.assertTrue(is_codex_exclusive_keypoint({"phase_id": "U257-SEC", "tier": "security_boundary"}))
        self.assertTrue(is_codex_exclusive_keypoint({"phase_id": "U257-TAGS", "tags": ["rsi_canon"]}))
        self.assertFalse(is_codex_exclusive_keypoint({"phase_id": "U257-ROUTINE", "state": "REVIEW"}))
        self.assertFalse(
            is_codex_exclusive_keypoint({"phase_id": "U257-OVERRIDE", "tier": "architectural_core", "routine_approval": True})
        )

    def test_3_verify_supreme_quality_gate_rejects_weak_or_self_approved_work(self) -> None:
        # 1. Self-approval forbidden
        res_self = verify_supreme_quality_gate(
            {"phase_id": "U1", "author_tool": "antigravity", "owner_tool": "antigravity"},
            judge_tool="antigravity",
        )
        self.assertFalse(res_self["ok"])
        self.assertEqual(res_self["error"], "SELF_APPROVAL_FORBIDDEN")

        # 2. Missing accept_cmd when required
        res_no_cmd = verify_supreme_quality_gate(
            {"phase_id": "U2", "author_tool": "antigravity", "require_accept_cmd": True, "accept_cmd": ""},
            judge_tool="claude",
        )
        self.assertFalse(res_no_cmd["ok"])
        self.assertEqual(res_no_cmd["error"], "MISSING_ACCEPT_CMD")

        # 3. Non-zero accept_exit_code rejected
        res_exit = verify_supreme_quality_gate(
            {"phase_id": "U3", "author_tool": "antigravity", "accept_exit_code": 1},
            judge_tool="claude",
        )
        self.assertFalse(res_exit["ok"])
        self.assertEqual(res_exit["error"], "ACCEPT_GATE_FAILED")

        # 4. Failed tests rejected
        res_tests = verify_supreme_quality_gate(
            {"phase_id": "U4", "author_tool": "antigravity", "tests_failed": 2},
            judge_tool="claude",
        )
        self.assertFalse(res_tests["ok"])
        self.assertEqual(res_tests["error"], "TESTS_FAILED")

        # 5. Valid quality evidence passes with founding principle attached
        res_ok = verify_supreme_quality_gate(
            {
                "phase_id": "U5",
                "author_tool": "antigravity",
                "require_accept_cmd": True,
                "accept_cmd": "python -m unittest",
                "accept_exit_code": 0,
                "tests_failed": 0,
                "require_primary_sources": True,
                "primary_source_urls": ["https://github.com/openai/codex"],
            },
            judge_tool="claude",
        )
        self.assertTrue(res_ok["ok"])
        self.assertEqual(res_ok["founding_principle"], UAOS_CORE_FOUNDING_PRINCIPLE)

    def test_4_route_codex_keypoint_preserves_core_and_offloads_routine_even_when_codex_idle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            coord = root / ".coord"
            coord.mkdir(parents=True)
            (coord / "master_schedule.json").write_text(
                json.dumps(
                    {
                        "schedule_id": "U257-SCHEDULE",
                        "phases": [
                            {
                                "phase_id": "U257-CORE",
                                "state": "REVIEW",
                                "owner_tool": "claude",
                                "author_tool": "claude",
                                "reviewer": "codex",
                                "waiting_on": "codex-verdict",
                                "tier": "architectural_core",
                                "depends_on": [],
                            },
                            {
                                "phase_id": "U257-ROUTINE",
                                "state": "REVIEW",
                                "owner_tool": "antigravity",
                                "author_tool": "antigravity",
                                "reviewer": "codex",
                                "waiting_on": "codex-verdict",
                                "accept_cmd": "python -m unittest",
                                "accept_exit_code": 0,
                                "depends_on": [],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            desk = {
                "codex": {"state": "ACTIVE"},
                "claude": {"state": "ACTIVE"},
                "antigravity": {"state": "ACTIVE"},
            }
            mod = AntigravityModerator(root)
            res = mod.route_codex_keypoint_and_routine_approvals(desk=desk, now=5000.0)
            self.assertTrue(res["ok"])
            self.assertEqual(res["preserved_keypoints"], ["U257-CORE"])
            self.assertEqual(len(res["offloaded_routine"]), 1)
            self.assertEqual(res["offloaded_routine"][0]["phase_id"], "U257-ROUTINE")
            self.assertEqual(res["offloaded_routine"][0]["to_tool"], "claude")

            sched = json.loads((coord / "master_schedule.json").read_text(encoding="utf-8"))
            by_id = {p["phase_id"]: p for p in sched["phases"]}
            self.assertEqual(by_id["U257-CORE"]["reviewer"], "codex")
            self.assertTrue(by_id["U257-CORE"]["codex_keypoint_preserved"])
            self.assertEqual(by_id["U257-ROUTINE"]["reviewer"], "claude")
            self.assertTrue(by_id["U257-ROUTINE"]["codex_astra_quota_saved"])
            self.assertEqual(by_id["U257-ROUTINE"]["quality_frame"], UAOS_CORE_FOUNDING_PRINCIPLE)


if __name__ == "__main__":
    unittest.main()
