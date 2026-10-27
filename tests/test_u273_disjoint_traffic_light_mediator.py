"""U273: Unit tests for Disjoint Traffic-Light Mediator (`v7_harness/disjoint_mediator.py`)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from v7_harness.disjoint_mediator import (
    acquire_lane_lease,
    evaluate_scoped_divergence,
    release_lane_lease,
)
from v7_harness.isolation.manifest import build_manifest, create_patch_bundle


class TestU273DisjointTrafficLightMediator(unittest.TestCase):
    def test_traffic_light_green_parallel_on_disjoint_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            res_olla = acquire_lane_lease(
                root,
                lane_id="U272-L1",
                worker="ollama",
                allowed_scopes=["v7_harness/rsi.py"],
                now=1000.0,
            )
            self.assertTrue(res_olla["ok"])
            self.assertEqual(res_olla["signal"], "GREEN_PARALLEL")

            res_haiku = acquire_lane_lease(
                root,
                lane_id="U272-H1",
                worker="haiku",
                allowed_scopes=["tests/test_u272.py", "docs/*"],
                now=1001.0,
            )
            self.assertTrue(res_haiku["ok"])
            self.assertEqual(res_haiku["signal"], "GREEN_PARALLEL")
            self.assertIn("U272-L1", res_haiku["active_companion_lanes"])

            rel = release_lane_lease(root, lane_id="U272-L1", now=1002.0)
            self.assertTrue(rel["released"])

    def test_traffic_light_red_on_overlapping_scopes_or_dual_ollama_gpu(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            acquire_lane_lease(
                root,
                lane_id="U272-L1",
                worker="ollama",
                allowed_scopes=["v7_harness/*.py"],
                now=1000.0,
            )
            # Second Ollama lane must be blocked by GPU serial lock
            res_olla2 = acquire_lane_lease(
                root,
                lane_id="U272-L2",
                worker="ollama",
                allowed_scopes=["tests/test_other.py"],
                now=1001.0,
            )
            self.assertFalse(res_olla2["ok"])
            self.assertEqual(res_olla2["signal"], "RED_PATH_CONFLICT")
            self.assertTrue(any("OLLAMA_GPU_SERIAL_LOCK" in c["reason"] for c in res_olla2["conflicts"]))

            # Haiku lane overlapping v7_harness/rsi.py must be blocked with RED_PATH_CONFLICT
            res_haiku_bad = acquire_lane_lease(
                root,
                lane_id="U272-H1",
                worker="haiku",
                allowed_scopes=["v7_harness/rsi.py"],
                now=1002.0,
            )
            self.assertFalse(res_haiku_bad["ok"])
            self.assertEqual(res_haiku_bad["signal"], "RED_PATH_CONFLICT")
            self.assertTrue(any("DISJOINT_SCOPE_OVERLAP" in c["reason"] for c in res_haiku_bad["conflicts"]))

    def test_yellow_scoped_rebase_resolves_source_diverged_between_ollama_and_haiku(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            stg = Path(tmp) / "stg"
            (src / "v7_harness").mkdir(parents=True)
            (src / "tests").mkdir(parents=True)
            (src / "v7_harness" / "rsi.py").write_text("x = 1\n", encoding="utf-8")
            (src / "tests" / "test_u272.py").write_text("assert True\n", encoding="utf-8")

            base_manifest = build_manifest(src)

            # Copy to staging for Ollama pilot run
            (stg / "v7_harness").mkdir(parents=True)
            (stg / "tests").mkdir(parents=True)
            (stg / "v7_harness" / "rsi.py").write_text("x = 2\n", encoding="utf-8")  # Ollama edits rsi.py
            (stg / "tests" / "test_u272.py").write_text("assert True\n", encoding="utf-8")

            target_manifest = build_manifest(stg)
            bundle = create_patch_bundle(
                base_manifest=base_manifest,
                target_manifest=target_manifest,
                base_dir=src,
                target_dir=stg,
            )

            # Meanwhile, Haiku edits tests/test_u272.py in src directly!
            (src / "tests" / "test_u272.py").write_text("assert 1 == 1\n", encoding="utf-8")

            # Evaluate scoped divergence for Ollama's allowed_scopes=["v7_harness/rsi.py"]
            med = evaluate_scoped_divergence(
                base_manifest=base_manifest,
                source_dir=src,
                excludes=[],
                pilot_allowed_scopes=["v7_harness/rsi.py"],
                bundle=bundle,
            )
            self.assertEqual(med["signal"], "YELLOW_SCOPED_REBASE")
            self.assertEqual(med["conflicting_paths"], [])
            self.assertEqual(med["disjoint_companion_paths"], ["tests/test_u272.py"])
            rebased = med["rebased_bundle"]
            self.assertIsNotNone(rebased)
            self.assertEqual(rebased.base_manifest_hash, med["current_manifest"].manifest_hash)

            # Now simulate a real conflict: someone also modified v7_harness/rsi.py in src!
            (src / "v7_harness" / "rsi.py").write_text("x = 999\n", encoding="utf-8")
            med_conflict = evaluate_scoped_divergence(
                base_manifest=base_manifest,
                source_dir=src,
                excludes=[],
                pilot_allowed_scopes=["v7_harness/rsi.py"],
                bundle=bundle,
            )
            self.assertEqual(med_conflict["signal"], "RED_CONFLICTING_DIVERGENCE")
            self.assertIn("v7_harness/rsi.py", med_conflict["conflicting_paths"])


if __name__ == "__main__":
    unittest.main()
