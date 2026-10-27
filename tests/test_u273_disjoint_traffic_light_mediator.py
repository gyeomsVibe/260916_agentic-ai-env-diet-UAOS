"""U273: Unit tests for Competent Zero-Wait Flagman (`v7_harness/disjoint_mediator.py`)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from v7_harness.disjoint_mediator import (
    acquire_lane_lease,
    evaluate_scoped_divergence,
    flagman_route_lanes,
    flagman_sync_companion_tests_into_staging,
    release_lane_lease,
)
from v7_harness.isolation.manifest import build_manifest, create_patch_bundle


class TestU273ZeroWaitFlagman(unittest.TestCase):
    def test_flagman_dynamic_lane_carve_out_zero_wait(self) -> None:
        # Even if Ollama was carelessly given wildcard '*' or overlapping 'tests/test_u272.py',
        # the Flagman carves out tests/docs to Haiku and code to Ollama with 0ms wait!
        routed = flagman_route_lanes(
            ollama_scopes=["v7_harness/rsi.py", "tests/test_u272.py"],
            haiku_scopes=["tests/test_u272.py", "docs/100_design.html"],
        )
        self.assertEqual(routed["flagman_action"], "ZERO_WAIT_DYNAMIC_BYPASS")
        self.assertEqual(routed["wait_ms"], 0)
        self.assertFalse(routed["ollama_Blocked"])
        self.assertFalse(routed["haiku_Blocked"])
        self.assertTrue(routed["disjoint_guaranteed"])
        self.assertEqual(routed["ollama_assigned_scopes"], ["v7_harness/rsi.py"])
        self.assertEqual(routed["haiku_assigned_scopes"], ["tests/test_u272.py", "docs/100_design.html"])

    def test_auto_carve_on_lease_acquisition_never_stops_ollama(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            res_haiku = acquire_lane_lease(
                root,
                lane_id="U272-H1",
                worker="haiku",
                allowed_scopes=["tests/test_u272.py"],
                now=1000.0,
            )
            self.assertTrue(res_haiku["ok"])

            # Ollama arrives with overlapping scope but auto_carve_on_overlap=True -> 0ms wait, immediate pass!
            res_olla = acquire_lane_lease(
                root,
                lane_id="U272-L1",
                worker="ollama",
                allowed_scopes=["v7_harness/rsi.py", "tests/test_u272.py"],
                auto_carve_on_overlap=True,
                now=1001.0,
            )
            self.assertTrue(res_olla["ok"])
            self.assertEqual(res_olla["wait_ms"], 0)
            self.assertEqual(res_olla["flagman_action"], "ZERO_WAIT_DYNAMIC_BYPASS")
            self.assertEqual(res_olla["allowed_scopes"], ["v7_harness/rsi.py"])
            release_lane_lease(root, lane_id="U272-L1", now=1002.0)

    def test_zero_wait_scoped_bypass_and_live_test_hot_sync(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            stg = Path(tmp) / "stg"
            (src / "v7_harness").mkdir(parents=True)
            (src / "tests").mkdir(parents=True)
            (src / "v7_harness" / "rsi.py").write_text("x = 1\n", encoding="utf-8")
            (src / "tests" / "test_u272.py").write_text("assert False\n", encoding="utf-8")

            base_manifest = build_manifest(src)

            (stg / "v7_harness").mkdir(parents=True)
            (stg / "tests").mkdir(parents=True)
            (stg / "v7_harness" / "rsi.py").write_text("x = 2\n", encoding="utf-8")
            (stg / "tests" / "test_u272.py").write_text("assert False\n", encoding="utf-8")

            target_manifest = build_manifest(stg)
            bundle = create_patch_bundle(
                base_manifest=base_manifest,
                target_manifest=target_manifest,
                base_dir=src,
                target_dir=stg,
            )

            # Haiku edits tests/test_u272.py in src while Ollama runs in stg (without any manual lease registration)
            (src / "tests" / "test_u272.py").write_text("assert x == 2\n", encoding="utf-8")

            med = evaluate_scoped_divergence(
                base_manifest=base_manifest,
                source_dir=src,
                excludes=[],
                pilot_allowed_scopes=["v7_harness/rsi.py"],
                bundle=bundle,
            )
            self.assertEqual(med["signal"], "YELLOW_SCOPED_REBASE")
            self.assertEqual(med["flagman_action"], "ZERO_WAIT_SCOPED_BYPASS")
            self.assertEqual(med["wait_ms"], 0)
            self.assertEqual(med["disjoint_companion_paths"], ["tests/test_u272.py"])

            # Hot-sync Haiku's updated test into Ollama's staging dir before accept_cmd
            synced = flagman_sync_companion_tests_into_staging(
                source_dir=src,
                staging_dir=stg,
                disjoint_companion_paths=med["disjoint_companion_paths"],
                pilot_allowed_scopes=["v7_harness/rsi.py"],
            )
            self.assertEqual(synced, ["tests/test_u272.py"])
            self.assertEqual((stg / "tests" / "test_u272.py").read_text(encoding="utf-8"), "assert x == 2\n")


if __name__ == "__main__":
    unittest.main()
