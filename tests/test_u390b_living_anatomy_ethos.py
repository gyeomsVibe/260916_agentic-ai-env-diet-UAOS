"""Acceptance & Vaccine Test Suite for U390-B Living Organism Anatomy & Ethos (R1).

Verifies:
1. Full 12-organ neuro-ergonomic registry, 5 capability slots, 5 virtues,
   7 eradicated pathogens, and verified existing target documents in Charter packet.
2. Strict Model-Agnostic Negative-Selection Gate (`assert_model_agnostic`):
   - Source module `uaos_living_organism.py`, canonical doc `docs/142_*.md`,
     and exported Charter packet contain ZERO specific model identifiers.
   - Injecting model names across all 3 cloud providers and local weight tags
     triggers `MODEL_SPECIFICITY_VIOLATION` 100% of the time.
3. Fail-Closed Availability & Unknown Quota Invariants (Codex R0 Counterexamples):
   - `remaining_7d_pct=None` never raises `TypeError` and fails closed (`BLOCKED_UNKNOWN_QUOTA`).
   - Explicit `available=False` or missing entries across all tools never select
     `antigravity` on `FORMAL_INVARIANT` or `ollama` on `REFLEX_TRIAGE` (`routable=False`).
4. Evidence-Gated Virtue & Pathogen Diagnosis (Codex R0 Counterexamples):
   - Empty `{}` or partial telemetry yields `organism_vital_state="UNKNOWN"` and
     `healthy=None` (never `THRIVING` or unverified virtues).
   - Full positive evidence yields `THRIVING` with all 5 virtues.
   - Each of the 7 pathogens triggers `IMMUNE_DEFENSE_ACTIVE` and its antibody.
5. Proposal-Only Boundary & Thread-Safe Determinism.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import unittest

from v7_harness.coord.uaos_living_organism import (
    CAPABILITY_SLOT_TAXONOMY,
    CHARTER_CONCEPTUAL_CLAUSES,
    DEPLOYMENT_STATUS,
    FIVE_CORE_VIRTUES,
    ORGAN_SYSTEM_REGISTRY,
    SEVEN_ERADICATED_PATHOGENS,
    assert_model_agnostic,
    diagnose_organism_ethos_and_toxins,
    export_charter_insertion_packet,
    resolve_anatomical_organ_routing,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "v7_harness" / "coord" / "uaos_living_organism.py"
DOC_142_PATH = (
    REPO_ROOT
    / "docs"
    / "142_UAOS-RSI_유기체인체해부학_무모델슬롯_헌장정신력_정본_20261124.md"
)


class TestU390BLivingAnatomyAndEthos(unittest.TestCase):
    def test_twelve_organs_five_slots_and_existing_charter_targets(self) -> None:
        self.assertEqual(len(ORGAN_SYSTEM_REGISTRY), 12)
        self.assertEqual(len(CAPABILITY_SLOT_TAXONOMY), 5)
        self.assertEqual(DEPLOYMENT_STATUS, "PROPOSAL_ONLY_UNINSTALLED")

        organ_ids = {row["organ_id"] for row in ORGAN_SYSTEM_REGISTRY}
        expected_organs = {
            "CONSCIENCE_IDENTITY_APEX",
            "LEFT_PREFRONTAL_CORTEX",
            "RIGHT_PREFRONTAL_INTEGRATIVE_CORTEX",
            "CORPUS_CALLOSUM_COMMISSURE",
            "SENSORIMOTOR_MUSCULOSKELETAL_SYSTEM",
            "PERIPHERAL_GANGLIA_SPINAL_INTERNEURONS",
            "CEREBELLUM_BRAINSTEM_MITOCHONDRIA",
            "AUTONOMIC_HOMEOSTASIS_NERVOUS_SYSTEM",
            "HIPPOCAMPUS_NEOCORTICAL_MEMORY",
            "CIRCULATORY_ENDOCRINE_METABOLIC_SYSTEM",
            "INNATE_ADAPTIVE_IMMUNE_SYSTEM",
            "AUTOPOIETIC_STEM_CELL_RSI_SYSTEM",
        }
        self.assertEqual(organ_ids, expected_organs)

        for slot in CAPABILITY_SLOT_TAXONOMY.values():
            self.assertFalse(slot["hardcoded_model_allowed"])

        total_pct = sum(s["metabolic_budget_share_pct"] for s in CAPABILITY_SLOT_TAXONOMY.values())
        self.assertEqual(total_pct, 100)

        # Every Charter target document must exist in the repository at base HEAD.
        targets = CHARTER_CONCEPTUAL_CLAUSES["target_documents"]
        self.assertIn("docs/01_unified-agent-orchestration-design.md", targets)
        self.assertNotIn("docs/019_unified-agent-orchestration-design.md", targets)
        for rel_target in targets:
            with self.subTest(target=rel_target):
                self.assertTrue(
                    (REPO_ROOT / rel_target).is_file(),
                    f"Charter target document missing at base: {rel_target}",
                )

    def test_zero_specific_model_names_in_source_doc_and_charter(self) -> None:
        self.assertTrue(MODULE_PATH.is_file(), f"Missing {MODULE_PATH}")
        self.assertTrue(DOC_142_PATH.is_file(), f"Missing {DOC_142_PATH}")

        src_audit = assert_model_agnostic(
            MODULE_PATH.read_text(encoding="utf-8"),
            context="uaos_living_organism.py",
        )
        self.assertTrue(src_audit["ok"], f"Source leaked model names: {src_audit['violations']}")

        doc_audit = assert_model_agnostic(
            DOC_142_PATH.read_text(encoding="utf-8"),
            context="docs/142",
        )
        self.assertTrue(doc_audit["ok"], f"Doc 142 leaked model names: {doc_audit['violations']}")

        packet = export_charter_insertion_packet()
        self.assertTrue(packet["model_agnostic_verified"])
        self.assertEqual(packet["deployment_status"], "PROPOSAL_ONLY_UNINSTALLED")
        self.assertFalse(packet["installed_in_production"])
        self.assertFalse(packet["production_caller_wired"])
        self.assertEqual(len(packet["charter"]["korean_articles"]), 3)
        self.assertEqual(len(packet["charter"]["english_global_rule_bullets"]), 2)

    def test_vaccine_model_specificity_detector_catches_all_families(self) -> None:
        samples = [
            "Use " + "g" + "pt-6.2 a" + "stra for formal checks",
            "Fallback to " + "g" + "pt-6-lu" + "na helper",
            "Bind " + "clau" + "de-op" + "us-5-5 as main brain",
            "Helper uses " + "hai" + "ku 5.5 under cap",
            "Avoid " + "son" + "net 5.5 retry tax",
            "Select " + "gem" + "ini 3.8 fl" + "ash or ne" + "on",
            "Hybrid orchestrator ar" + "gon and car" + "bon",
            "Run local qw" + "en2.5-coder:7b slice",
            "Try lla" + "ma3:8b or deep" + "seek-r1",
            "Model reasoning o" + "3-mini",
        ]
        for sample in samples:
            with self.subTest(sample=sample):
                res = assert_model_agnostic(sample, context="vaccine_probe")
                self.assertFalse(res["ok"], f"Failed to reject model-specific string: {sample}")
                self.assertGreaterEqual(res["violation_count"], 1)

    def test_hemispheric_sensorimotor_ganglia_and_cerebellar_routing(self) -> None:
        healthy_vitality = {
            "codex": {"remaining_7d_pct": 45.0, "available": True},
            "claude": {"remaining_7d_pct": 52.0, "available": True},
            "antigravity": {"remaining_7d_pct": 94.0, "available": True},
            "ollama": {"available": True},
        }

        left = resolve_anatomical_organ_routing(
            {"domain": "FORMAL_INVARIANT", "is_keypoint": True},
            healthy_vitality,
        )
        self.assertTrue(left["routable"])
        self.assertTrue(left["proposal_only"])
        self.assertEqual(left["organ_id"], "LEFT_PREFRONTAL_CORTEX")
        self.assertEqual(left["worker_tool"], "codex")
        self.assertNotEqual(left["judge_tool"], "codex")
        self.assertFalse(left["self_judge_permitted"])

        right = resolve_anatomical_organ_routing(
            {"domain": "HOLISTIC_CONTEXT", "is_keypoint": False},
            healthy_vitality,
        )
        self.assertTrue(right["routable"])
        self.assertEqual(right["organ_id"], "RIGHT_PREFRONTAL_INTEGRATIVE_CORTEX")
        self.assertEqual(right["worker_tool"], "claude")
        self.assertNotEqual(right["judge_tool"], "claude")

        motor = resolve_anatomical_organ_routing(
            {"domain": "SENSORIMOTOR_LABOR", "line_budget": 120},
            healthy_vitality,
        )
        self.assertTrue(motor["routable"])
        self.assertEqual(motor["organ_id"], "SENSORIMOTOR_MUSCULOSKELETAL_SYSTEM")
        self.assertEqual(motor["worker_tool"], "antigravity")
        self.assertEqual(motor["judge_tool"], "claude")

        reflex = resolve_anatomical_organ_routing(
            {"domain": "REFLEX_TRIAGE"},
            healthy_vitality,
        )
        self.assertTrue(reflex["routable"])
        self.assertEqual(reflex["organ_id"], "PERIPHERAL_GANGLIA_SPINAL_INTERNEURONS")
        self.assertEqual(reflex["capability_slot"], "PERIPHERAL_HELPER_RELAY_SLOT")

        cereb = resolve_anatomical_organ_routing(
            {"domain": "CEREBELLAR_SLICE", "line_budget": 15, "requires_judgment": False},
            healthy_vitality,
        )
        self.assertTrue(cereb["routable"])
        self.assertEqual(cereb["organ_id"], "CEREBELLUM_BRAINSTEM_MITOCHONDRIA")
        self.assertEqual(cereb["worker_tool"], "ollama")
        self.assertNotEqual(cereb["judge_tool"], "ollama")

        escalated = resolve_anatomical_organ_routing(
            {"domain": "CEREBELLAR_SLICE", "line_budget": 10, "requires_judgment": True, "is_keypoint": True},
            healthy_vitality,
        )
        self.assertTrue(escalated["routable"])
        self.assertEqual(escalated["organ_id"], "LEFT_PREFRONTAL_CORTEX")
        self.assertEqual(escalated["worker_tool"], "codex")

    def test_codex_revise_r0_none_quota_and_unavailable_fail_closed(self) -> None:
        # 1. remaining_7d_pct=None must NOT raise TypeError; when all cloud quotas are None and ollama down -> fail closed
        none_quotas = {
            "codex": {"remaining_7d_pct": None, "available": True},
            "claude": {"remaining_7d_pct": None, "available": True},
            "antigravity": {"remaining_7d_pct": None, "available": True},
            "ollama": {"available": False},
        }
        for domain in ("FORMAL_INVARIANT", "HOLISTIC_CONTEXT", "SENSORIMOTOR_LABOR", "REFLEX_TRIAGE", "CEREBELLAR_SLICE"):
            with self.subTest(case="none_quotas", domain=domain):
                res = resolve_anatomical_organ_routing({"domain": domain, "line_budget": 10}, none_quotas)
                self.assertFalse(res["routable"])
                self.assertEqual(res["status"], "BLOCKED_NO_VERIFIED_ORGAN")
                self.assertEqual(res["neuroplastic_mode"], "BLOCKED_UNKNOWN_QUOTA")
                self.assertIsNone(res["worker_tool"])
                self.assertIsNone(res["judge_tool"])
                self.assertFalse(res["self_judge_permitted"])

        # 2. All tools explicitly unavailable: neither antigravity nor ollama may ever be selected
        all_unavailable = {
            "codex": {"remaining_7d_pct": 80.0, "available": False},
            "claude": {"remaining_7d_pct": 80.0, "available": False},
            "antigravity": {"remaining_7d_pct": 95.0, "available": False},
            "ollama": {"available": False},
        }
        for domain in ("FORMAL_INVARIANT", "HOLISTIC_CONTEXT", "SENSORIMOTOR_LABOR", "REFLEX_TRIAGE", "CEREBELLAR_SLICE"):
            with self.subTest(case="all_unavailable", domain=domain):
                res = resolve_anatomical_organ_routing({"domain": domain, "line_budget": 10}, all_unavailable)
                self.assertFalse(res["routable"])
                self.assertEqual(res["neuroplastic_mode"], "BLOCKED_ALL_ORGANS_UNAVAILABLE")
                self.assertIsNone(res["worker_tool"])

        # 3. Empty vitality dict `{}` (unproven availability) must also fail closed across all domains
        for domain in ("FORMAL_INVARIANT", "HOLISTIC_CONTEXT", "SENSORIMOTOR_LABOR", "REFLEX_TRIAGE", "CEREBELLAR_SLICE"):
            with self.subTest(case="empty_vitality", domain=domain):
                res = resolve_anatomical_organ_routing({"domain": domain, "line_budget": 10}, {})
                self.assertFalse(res["routable"])
                self.assertIsNone(res["worker_tool"])

        # 4. Partial None quota: codex=None, claude=55.0 verified -> skips codex safely, routes to verified claude
        partial_none = {
            "codex": {"remaining_7d_pct": None, "available": True},
            "claude": {"remaining_7d_pct": 55.0, "available": True},
            "antigravity": {"remaining_7d_pct": 90.0, "available": True},
            "ollama": {"available": False},
        }
        routed = resolve_anatomical_organ_routing({"domain": "FORMAL_INVARIANT", "is_keypoint": True}, partial_none)
        self.assertTrue(routed["routable"])
        self.assertEqual(routed["worker_tool"], "claude")
        self.assertEqual(routed["judge_tool"], "antigravity")

    def test_neuroplastic_compensation_and_dynamic_inversion_never_self_judge(self) -> None:
        right_resting = {
            "codex": {"remaining_7d_pct": 28.0, "available": True},
            "claude": {"remaining_7d_pct": 1.0, "available": True},
            "antigravity": {"remaining_7d_pct": 95.0, "available": True},
            "ollama": {"available": True},
        }
        comp = resolve_anatomical_organ_routing({"domain": "HOLISTIC_CONTEXT"}, right_resting)
        self.assertTrue(comp["routable"])
        self.assertEqual(comp["worker_tool"], "codex")
        self.assertEqual(comp["neuroplastic_mode"], "CONTRALATERAL_LEFT_COMPENSATION")
        self.assertNotEqual(comp["judge_tool"], "codex")

        both_resting = {
            "codex": {"remaining_7d_pct": 2.0, "available": True},
            "claude": {"remaining_7d_pct": 0.0, "available": True},
            "antigravity": {"remaining_7d_pct": 88.0, "available": True},
            "ollama": {"available": True},
        }
        acting = resolve_anatomical_organ_routing({"domain": "FORMAL_INVARIANT"}, both_resting)
        self.assertTrue(acting["routable"])
        self.assertEqual(acting["worker_tool"], "antigravity")
        self.assertEqual(acting["judge_tool"], "DEFERRED_CORTICAL_JUDGE")
        self.assertEqual(acting["judge_mode"], "ACTING_SENSORIMOTOR_DEFERRED_CORTICAL_AUDIT")
        self.assertFalse(acting["self_judge_permitted"])

        motor_fatigued = {
            "codex": {"remaining_7d_pct": 65.0, "available": True},
            "claude": {"remaining_7d_pct": 78.0, "available": True},
            "antigravity": {"remaining_7d_pct": 12.0, "available": True},
            "ollama": {"available": True},
        }
        inverted = resolve_anatomical_organ_routing({"domain": "SENSORIMOTOR_LABOR"}, motor_fatigued)
        self.assertTrue(inverted["routable"])
        self.assertEqual(inverted["worker_tool"], "claude")
        self.assertEqual(inverted["neuroplastic_mode"], "DYNAMIC_NEUROPLASTIC_INVERTED")
        self.assertEqual(inverted["judge_tool"], "antigravity")
        self.assertFalse(inverted["self_judge_permitted"])

    def test_routing_rejects_hardcoded_model_in_task_profile(self) -> None:
        bad_desc = "Please run with " + "gem" + "ini-4-ne" + "on directly"
        with self.assertRaises(ValueError) as ctx:
            resolve_anatomical_organ_routing(
                {"domain": "SENSORIMOTOR_LABOR", "description": bad_desc},
                {"antigravity": {"remaining_7d_pct": 90.0, "available": True}},
            )
        self.assertIn("MODEL_SPECIFICITY_VIOLATION", str(ctx.exception))

    def test_codex_revise_r0_empty_or_partial_telemetry_is_unknown_not_thriving(self) -> None:
        # Empty telemetry must return UNKNOWN, healthy=None, and zero verified virtues.
        empty_diag = diagnose_organism_ethos_and_toxins({})
        self.assertIsNone(empty_diag["healthy"])
        self.assertEqual(empty_diag["organism_vital_state"], "UNKNOWN")
        self.assertEqual(empty_diag["detected_pathogens"], [])
        self.assertEqual(empty_diag["verified_virtues"], [])
        self.assertGreaterEqual(len(empty_diag["missing_evidence"]), 5)

        # Partial telemetry (only warmth proven; other fields None/missing) stays UNKNOWN.
        partial_diag = diagnose_organism_ethos_and_toxins(
            {
                "warm_concise_korean_user_care": True,
                "unrerouted_wait_minutes": None,
                "stage0_primary_sources": None,
            }
        )
        self.assertIsNone(partial_diag["healthy"])
        self.assertEqual(partial_diag["organism_vital_state"], "UNKNOWN")
        self.assertEqual(partial_diag["verified_virtues"], ["HUMAN_WARMTH"])

    def test_five_virtues_and_seven_pathogen_vaccine_injections(self) -> None:
        self.assertEqual(len(FIVE_CORE_VIRTUES), 5)
        self.assertEqual(len(SEVEN_ERADICATED_PATHOGENS), 7)

        # Complete positive evidence verifies all 5 virtues -> THRIVING
        clean = diagnose_organism_ethos_and_toxins(
            {
                "author_tool": "antigravity",
                "judge_tool": "codex",
                "stage0_primary_sources": 4,
                "acceptance_passed": True,
                "counterexample_verified": True,
                "ended_with_choice_prompt": False,
                "no_changes_submitted": False,
                "gate_defined_before_action": True,
                "resilient_recovery_ready": True,
                "warm_concise_korean_user_care": True,
                "rule_or_contract_text": "Bind abstract formal brain slot dynamically.",
            }
        )
        self.assertIs(clean["healthy"], True)
        self.assertEqual(clean["organism_vital_state"], "THRIVING")
        self.assertEqual(clean["missing_evidence"], [])
        self.assertEqual(
            set(clean["verified_virtues"]),
            {
                "PRIDE_IN_CRAFT",
                "SENSE_OF_MISSION",
                "CLEAR_TELOS",
                "UNSHAKEABLE_FORTITUDE",
                "HUMAN_WARMTH",
            },
        )

        injections = (
            ("WEAKNESS", {"ended_with_choice_prompt": True}, "ANTIBODY_NO_CHOICE_PROMPT"),
            ("SLOTH", {"unrerouted_wait_minutes": 45.0}, "ANTIBODY_ANTI_STALL_CALCULATOR"),
            ("DECEPTION", {"author_tool": "codex", "judge_tool": "codex"}, "ANTIBODY_CROSS_JUDGE_IMMUTABLE_GATE"),
            ("LYING", {"unmeasured_saving_reported_as_fact": True}, "ANTIBODY_EMPIRICAL_TRUTH_ONLY"),
            ("SUPERFICIALITY", {"stage0_primary_sources": 0}, "ANTIBODY_STAGE0_VACCINE_DEPTH"),
            ("MYOPIA", {"rule_or_contract_text": "Pin " + "qw" + "en:7b forever"}, "ANTIBODY_MODEL_AGNOSTIC_PACING"),
            ("DESPONDENCY", {"global_halt_despite_ready_cards": True}, "ANTIBODY_LOCAL_QUARANTINE_RESILIENCE"),
        )
        for pathogen_id, payload, antibody in injections:
            with self.subTest(pathogen=pathogen_id):
                diag = diagnose_organism_ethos_and_toxins(payload)
                self.assertIs(diag["healthy"], False)
                self.assertEqual(diag["organism_vital_state"], "IMMUNE_DEFENSE_ACTIVE")
                self.assertIn(pathogen_id, diag["detected_pathogens"])
                self.assertIn(antibody, diag["triggered_antibodies"])

    def test_parallel_thread_determinism_of_charter_and_routing(self) -> None:
        vitality = {
            "codex": {"remaining_7d_pct": 35.0, "available": True},
            "claude": {"remaining_7d_pct": 40.0, "available": True},
            "antigravity": {"remaining_7d_pct": 90.0, "available": True},
            "ollama": {"available": True},
        }

        def _worker(i: int) -> tuple[str, str]:
            pkt = export_charter_insertion_packet()
            rt = resolve_anatomical_organ_routing(
                {"domain": "CEREBELLAR_SLICE" if i % 2 == 0 else "FORMAL_INVARIANT", "line_budget": 12},
                vitality,
            )
            return pkt["sha256"], str(rt["organ_id"])

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(_worker, range(32)))

        hashes = {h for h, _ in results}
        self.assertEqual(len(hashes), 1)
        self.assertEqual(len(CHARTER_CONCEPTUAL_CLAUSES["korean_articles"]), 3)


if __name__ == "__main__":
    unittest.main()
