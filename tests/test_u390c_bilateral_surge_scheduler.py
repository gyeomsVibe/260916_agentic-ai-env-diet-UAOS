"""Acceptance & Vaccine Test Suite for U390-C Bilateral Parallel Surge Scheduler.

Verifies:
1. All 8 (2^3) tool-availability scenarios (S1..S8), including 3-way cyclic
   cross-verify (S1), 2-way mirror cross-verify (S2..S4), solo deferred peer
   verdict without self-judgment (S5..S7), and fail-closed zero-cloud (S8).
2. Banich-Belger load crossover: NORMAL runs serial (1 card); ELEVATED/SURGE
   expands to disjoint parallel work-stealing; empty telemetry returns UNKNOWN.
3. Kleppmann fencing & anti-tangle invariants: stale fencing epochs rejected,
   unscoped mutating tasks rejected, overlapping Windows/POSIX allow_files
   deferred into conflict queue with zero overlapping locks.
4. None/invalid/<=5% quotas and unproven availability fail closed without
   TypeError.
5. Zero hardcoded model identifiers across module, docs/143, and Charter
   proposal + verified on-disk existence of all Charter target documents.
6. Multi-thread deterministic stability under concurrent planning calls.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import unittest

from v7_harness.coord.bilateral_surge_scheduler import (
    AVAILABILITY_SCENARIO_MATRIX,
    CHARTER_SURGE_PROPOSAL,
    DEPLOYMENT_STATUS,
    assert_surge_model_agnostic,
    classify_availability_scenario,
    evaluate_congestion_state,
    export_surge_charter_proposal,
    plan_bilateral_surge_wave,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "v7_harness" / "coord" / "bilateral_surge_scheduler.py"
DOC_143_PATH = (
    REPO_ROOT
    / "docs"
    / "143_UAOS-RSI_총괄병목해소_좌우뇌분산병렬급행_말단고속교차검증_전시나리오_정본_20261125.md"
)


def _sample_disjoint_tasks(epoch: int = 5) -> list[dict]:
    return [
        {
            "task_id": "T-URGENT",
            "priority": "URGENT",
            "domain": "SENSORIMOTOR_LABOR",
            "allow_files": ["v7_harness/coord/lane_a.py"],
            "is_keypoint": False,
            "fencing_epoch": epoch,
        },
        {
            "task_id": "T-FORMAL",
            "priority": "HIGH",
            "domain": "FORMAL_INVARIANT",
            "allow_files": ["v7_harness/coord/lane_b.py"],
            "is_keypoint": True,
            "fencing_epoch": epoch,
        },
        {
            "task_id": "T-HOLISTIC",
            "priority": "NORMAL",
            "domain": "HOLISTIC_CONTEXT",
            "allow_files": ["v7_harness/coord/lane_c.py"],
            "is_keypoint": False,
            "fencing_epoch": epoch,
        },
        {
            "task_id": "T-LOCAL-SLICE",
            "priority": "NORMAL",
            "domain": "CEREBELLAR_SLICE",
            "allow_files": ["v7_harness/coord/lane_d.py"],
            "line_budget": 14,
            "requires_judgment": False,
            "fencing_epoch": epoch,
        },
    ]


SURGE_TELEMETRY = {
    "pending_tasks": 4,
    "urgent_tasks": 1,
    "oldest_wait_minutes": 22.0,
    "active_director_load": 0.90,
    "stale_pointer_conflicts": 1,
}


class TestU390CBilateralSurgeScheduler(unittest.TestCase):
    def test_zero_hardcoded_models_and_existing_charter_targets(self) -> None:
        self.assertEqual(DEPLOYMENT_STATUS, "PROPOSAL_ONLY_UNINSTALLED")
        self.assertTrue(MODULE_PATH.is_file())
        self.assertTrue(DOC_143_PATH.is_file())

        for label, path in (("module", MODULE_PATH), ("doc143", DOC_143_PATH)):
            audit = assert_surge_model_agnostic(path.read_text(encoding="utf-8"), context=label)
            self.assertTrue(audit["ok"], f"{label} leaked model names: {audit['violations']}")

        proposal = export_surge_charter_proposal()
        self.assertTrue(proposal["model_agnostic_verified"])
        self.assertEqual(proposal["proposal"]["deployment_status"], "PROPOSAL_ONLY_UNINSTALLED")
        self.assertFalse(proposal["proposal"]["installed_in_production"])
        self.assertFalse(proposal["proposal"]["production_caller_wired"])

        for rel in CHARTER_SURGE_PROPOSAL["target_documents"]:
            with self.subTest(target=rel):
                self.assertTrue((REPO_ROOT / rel).is_file(), f"Missing target doc: {rel}")

        bad_task = _sample_disjoint_tasks()[0]
        bad_task["description"] = "Force " + "g" + "pt-6.2 a" + "stra on this shard"
        with self.assertRaises(ValueError) as ctx:
            plan_bilateral_surge_wave(
                [bad_task],
                {"codex": {"available": True, "remaining_7d_pct": 50.0}},
                active_fencing_epoch=5,
                congestion_telemetry=SURGE_TELEMETRY,
            )
        self.assertIn("MODEL_SPECIFICITY_VIOLATION", str(ctx.exception))

    def test_all_eight_availability_scenarios_and_zero_self_judge(self) -> None:
        self.assertEqual(len(AVAILABILITY_SCENARIO_MATRIX), 8)
        combos = (
            ("S1", True, True, True, 3),
            ("S2", True, True, False, 2),
            ("S3", True, False, True, 2),
            ("S4", False, True, True, 2),
            ("S5", True, False, False, 1),
            ("S6", False, True, False, 1),
            ("S7", False, False, True, 1),
            ("S8", False, False, False, 0),
        )
        for sid, cx_on, cl_on, ag_on, expected_p in combos:
            with self.subTest(scenario=sid):
                vitality = {
                    "codex": {"available": cx_on, "remaining_7d_pct": 45.0 if cx_on else 0.0},
                    "claude": {"available": cl_on, "remaining_7d_pct": 70.0 if cl_on else 0.0},
                    "antigravity": {"available": ag_on, "remaining_7d_pct": 92.0 if ag_on else 0.0},
                    "ollama": {"available": False},
                }
                sc = classify_availability_scenario(vitality)
                self.assertEqual(sc["scenario_id"], sid)
                self.assertEqual(sc["parallelism"], expected_p)

                wave = plan_bilateral_surge_wave(
                    _sample_disjoint_tasks(epoch=5),
                    vitality,
                    active_fencing_epoch=5,
                    congestion_telemetry=SURGE_TELEMETRY,
                )
                self.assertFalse(wave["self_judge_permitted"])
                self.assertEqual(wave["measured_wallclock_gain"], "UNMEASURED")
                self.assertEqual(wave["paid_token_savings"], "UNMEASURED")
                self.assertEqual(wave["theoretical_parallelism_factor"], expected_p)

                if expected_p == 0:
                    self.assertFalse(wave["routable"])
                    self.assertEqual(wave["status"], "BLOCKED_NO_VERIFIED_ORGAN")
                    self.assertEqual(wave["dispatches"], [])
                else:
                    self.assertTrue(wave["routable"])
                    self.assertEqual(len(wave["dispatches"]), expected_p)
                    for item in wave["terminal_cross_verify_plan"]:
                        self.assertFalse(item["self_judge_permitted"])
                        self.assertNotEqual(item["author_tool"], item["judge_tool"])
                        if expected_p == 1:
                            self.assertEqual(item["judge_tool"], "DEFERRED_PEER_JUDGE")
                        else:
                            self.assertIn(item["judge_tool"], sc["active_cloud_organs"])

                    if sid == "S4":
                        kp = [d for d in wave["dispatches"] if d["task_id"] == "T-FORMAL"]
                        if kp:
                            self.assertTrue(kp[0]["requires_codex_keypoint_signoff"])

    def test_s1_full_surge_with_ollama_cerebellum_and_cilk_work_stealing(self) -> None:
        vitality = {
            "codex": {"available": True, "remaining_7d_pct": 40.0},
            "claude": {"available": True, "remaining_7d_pct": 85.0},
            "antigravity": {"available": True, "remaining_7d_pct": 95.0},
            "ollama": {"available": True},
        }
        tasks = [
            {
                "task_id": "M1",
                "priority": "URGENT",
                "domain": "SENSORIMOTOR_LABOR",
                "allow_files": ["v7_harness/a.py"],
                "fencing_epoch": 5,
            },
            {
                "task_id": "M2",
                "priority": "HIGH",
                "domain": "SENSORIMOTOR_LABOR",
                "allow_files": ["v7_harness/b.py"],
                "fencing_epoch": 5,
            },
            {
                "task_id": "F1",
                "priority": "HIGH",
                "domain": "FORMAL_INVARIANT",
                "allow_files": ["v7_harness/c.py"],
                "is_keypoint": True,
                "fencing_epoch": 5,
            },
            {
                "task_id": "C1",
                "priority": "NORMAL",
                "domain": "CEREBELLAR_SLICE",
                "allow_files": ["v7_harness/d.py"],
                "line_budget": 12,
                "requires_judgment": False,
                "fencing_epoch": 5,
            },
        ]
        wave = plan_bilateral_surge_wave(
            tasks,
            vitality,
            active_fencing_epoch=5,
            congestion_telemetry=SURGE_TELEMETRY,
        )
        self.assertEqual(wave["status"], "BILATERAL_SURGE_DISPATCHED")
        by_id = {d["task_id"]: d for d in wave["dispatches"]}
        self.assertEqual(by_id["M1"]["worker_tool"], "antigravity")
        self.assertFalse(by_id["M1"]["work_stolen"])
        self.assertEqual(by_id["M2"]["worker_tool"], "claude")
        self.assertTrue(by_id["M2"]["work_stolen"])
        self.assertEqual(by_id["M2"]["dispatch_route"], "CILK_WORK_STEAL_SURGE")
        self.assertEqual(by_id["F1"]["worker_tool"], "codex")
        self.assertEqual(by_id["C1"]["worker_tool"], "ollama")

        for j in wave["terminal_cross_verify_plan"]:
            self.assertNotEqual(j["author_tool"], j["judge_tool"])

    def test_banich_belger_normal_load_runs_serial_and_missing_telemetry_is_unknown(self) -> None:
        empty_c = evaluate_congestion_state({})
        self.assertEqual(empty_c["congestion_level"], "UNKNOWN")
        self.assertFalse(empty_c["surge_recommended"])
        self.assertGreaterEqual(len(empty_c["missing_evidence"]), 4)

        vitality = {
            "codex": {"available": True, "remaining_7d_pct": 50.0},
            "claude": {"available": True, "remaining_7d_pct": 80.0},
            "antigravity": {"available": True, "remaining_7d_pct": 95.0},
            "ollama": {"available": False},
        }
        blocked = plan_bilateral_surge_wave(
            _sample_disjoint_tasks(epoch=5),
            vitality,
            active_fencing_epoch=5,
            congestion_telemetry={},
        )
        self.assertFalse(blocked["routable"])
        self.assertEqual(blocked["status"], "BLOCKED_UNKNOWN_CONGESTION")
        self.assertEqual(blocked["dispatches"], [])

        normal_telemetry = {
            "pending_tasks": 1,
            "urgent_tasks": 0,
            "oldest_wait_minutes": 2.0,
            "active_director_load": 0.25,
            "stale_pointer_conflicts": 0,
        }
        normal_wave = plan_bilateral_surge_wave(
            _sample_disjoint_tasks(epoch=5),
            vitality,
            active_fencing_epoch=5,
            congestion_telemetry=normal_telemetry,
        )
        self.assertEqual(normal_wave["congestion"]["congestion_level"], "NORMAL")
        self.assertEqual(len(normal_wave["dispatches"]), 1)
        self.assertEqual(normal_wave["dispatches"][0]["task_id"], "T-URGENT")

    def test_kleppmann_fencing_unscoped_and_disjoint_file_anti_tangle_locks(self) -> None:
        vitality = {
            "codex": {"available": True, "remaining_7d_pct": 50.0},
            "claude": {"available": True, "remaining_7d_pct": 80.0},
            "antigravity": {"available": True, "remaining_7d_pct": 95.0},
            "ollama": {"available": False},
        }
        tasks = [
            {
                "task_id": "STALE-OLD-DESK",
                "priority": "URGENT",
                "domain": "FORMAL_INVARIANT",
                "allow_files": ["v7_harness/coord/a.py"],
                "fencing_epoch": 4,
            },
            {
                "task_id": "UNSCOPED-MUTATION",
                "priority": "URGENT",
                "domain": "SENSORIMOTOR_LABOR",
                "allow_files": [],
                "fencing_epoch": 5,
            },
            {
                "task_id": "WIN-OWNER",
                "priority": "URGENT",
                "domain": "SENSORIMOTOR_LABOR",
                "allow_files": [r".\v7_harness\coord\Shared.py"],
                "fencing_epoch": 5,
            },
            {
                "task_id": "POSIX-CONFLICT",
                "priority": "HIGH",
                "domain": "FORMAL_INVARIANT",
                "allow_files": ["v7_harness/coord/shared.py"],
                "fencing_epoch": 5,
            },
            {
                "task_id": "DISJOINT-OK",
                "priority": "NORMAL",
                "domain": "HOLISTIC_CONTEXT",
                "allow_files": ["v7_harness/coord/other.py"],
                "fencing_epoch": 5,
            },
        ]
        wave = plan_bilateral_surge_wave(
            tasks,
            vitality,
            active_fencing_epoch=5,
            congestion_telemetry=SURGE_TELEMETRY,
        )
        self.assertEqual([r["task_id"] for r in wave["rejected_stale_epoch_tasks"]], ["STALE-OLD-DESK"])
        self.assertEqual([r["task_id"] for r in wave["rejected_unscoped_tasks"]], ["UNSCOPED-MUTATION"])
        self.assertEqual([c["task_id"] for c in wave["deferred_file_conflict_queue"]], ["POSIX-CONFLICT"])
        self.assertEqual(wave["deferred_file_conflict_queue"][0]["blocked_by_tasks"], ["WIN-OWNER"])
        self.assertEqual([d["task_id"] for d in wave["dispatches"]], ["WIN-OWNER", "DISJOINT-OK"])

    def test_none_quota_protective_rest_and_s8_offline_local_staging_only(self) -> None:
        vitality = {
            "codex": {"available": True, "remaining_7d_pct": None},
            "claude": {"available": True, "remaining_7d_pct": 4.5},
            "antigravity": {"available": False, "remaining_7d_pct": 99.0},
            "ollama": {"available": True},
        }
        wave = plan_bilateral_surge_wave(
            _sample_disjoint_tasks(epoch=5),
            vitality,
            active_fencing_epoch=5,
            congestion_telemetry=SURGE_TELEMETRY,
        )
        self.assertEqual(wave["scenario"]["scenario_id"], "S8")
        self.assertEqual(wave["theoretical_parallelism_factor"], 0)
        self.assertEqual(len(wave["dispatches"]), 1)
        self.assertEqual(wave["dispatches"][0]["worker_tool"], "ollama")
        self.assertEqual(wave["terminal_cross_verify_plan"][0]["judge_tool"], "DEFERRED_PEER_JUDGE")
        self.assertEqual(len(wave["deferred_capacity_queue"]), 3)

    def test_parallel_thread_safety_and_determinism(self) -> None:
        vitality = {
            "codex": {"available": True, "remaining_7d_pct": 42.0},
            "claude": {"available": True, "remaining_7d_pct": 78.0},
            "antigravity": {"available": True, "remaining_7d_pct": 93.0},
            "ollama": {"available": True},
        }

        def _run(_: int) -> tuple[str, tuple[tuple[str, str], ...]]:
            w = plan_bilateral_surge_wave(
                _sample_disjoint_tasks(epoch=5),
                vitality,
                active_fencing_epoch=5,
                congestion_telemetry=SURGE_TELEMETRY,
            )
            p = export_surge_charter_proposal()
            return p["sha256"], tuple((d["task_id"], d["worker_tool"]) for d in w["dispatches"])

        with ThreadPoolExecutor(max_workers=8) as pool:
            outputs = list(pool.map(_run, range(24)))

        self.assertEqual(len(set(outputs)), 1)


if __name__ == "__main__":
    unittest.main()
