"""M2 acceptance tests (failing first): real-process agy launcher, pilot pipeline, approved promotion.

Uses tests/fixtures/fake_agy.py instead of the real CLI so the contract is deterministic.
The real agy run is a separate live pilot (P01), not part of this suite.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.isolation import NonGitStagingAdapter
from v7_harness.isolation.errors import IsolationError
from v7_harness.isolation.promotion import apply_promotion
from v7_harness.pilot import PilotConfig, run_pilot

FAKE_AGY = [sys.executable, str(Path(__file__).parent / "fixtures" / "fake_agy.py")]
ORIGINAL = "def mul(a, b):\n    return a * b\n"


class M2PilotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "sample"
        self.source.mkdir()
        (self.source / "calc.py").write_text(ORIGINAL, encoding="utf-8")
        self.home = self.root / "home"
        self.home.mkdir()
        self.work = self.root / "work"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _config(self, **overrides) -> PilotConfig:
        values = dict(
            task_id="P01",
            title="add function",
            prompt="Add add(a, b) to calc.py.",
            source_dir=self.source,
            work_dir=self.work,
            agy_command=FAKE_AGY,
            watch_roots=[self.home],
            print_timeout_s=60,
            approve_bundle_id=None,
        )
        values.update(overrides)
        return PilotConfig(**values)

    def _run(self, mode: str, **overrides) -> dict:
        env = {"FAKE_AGY_MODE": mode, "FAKE_AGY_OUTSIDE_DIR": str(self.home)}
        with mock.patch.dict(os.environ, env):
            return run_pilot(self._config(**overrides))

    # 1. success path, no approval → dry-run only
    def test_success_produces_bundle_and_leaves_source_untouched(self) -> None:
        summary = self._run("success")
        self.assertEqual("SUCCEEDED", summary["state"])
        self.assertEqual("DRY_RUN_PASSED", summary["promotion"])
        self.assertEqual(["calc.py"], summary["changed_files"])
        self.assertEqual(ORIGINAL, (self.source / "calc.py").read_text(encoding="utf-8"))
        self.assertTrue(summary["bundle_id"])

    # 2. summary is compact and persisted with raw evidence
    def test_summary_and_raw_evidence_are_persisted(self) -> None:
        summary = self._run("success")
        summary_path = Path(summary["summary_path"])
        self.assertTrue(summary_path.is_file())
        self.assertEqual(summary, json.loads(summary_path.read_text(encoding="utf-8")))
        self.assertLessEqual(len(summary), 14)
        self.assertTrue(Path(summary["raw_stdout_path"]).is_file())
        self.assertTrue(Path(summary["raw_stderr_path"]).is_file())
        self.assertEqual("fake-conv-0001", summary["conversation_id"])
        self.assertEqual(1000, summary["agy_usage"]["input_tokens"])

    # 3. approval with matching bundle id applies to source
    def test_matching_approval_applies_patch(self) -> None:
        first = self._run("success")
        second = self._run("success", approve_bundle_id=first["bundle_id"], task_id="P01B")
        self.assertEqual("APPLIED", second["promotion"])
        self.assertIn("def add(a, b):", (self.source / "calc.py").read_text(encoding="utf-8"))

    # 4. wrong approval id never writes
    def test_wrong_approval_id_does_not_write(self) -> None:
        summary = self._run("success", approve_bundle_id="not-the-bundle")
        self.assertEqual("APPROVAL_MISMATCH", summary["promotion"])
        self.assertEqual(ORIGINAL, (self.source / "calc.py").read_text(encoding="utf-8"))

    # 5. envelope ERROR with a real write is not success and is never promoted
    def test_error_status_with_write_is_unknown_and_blocked(self) -> None:
        summary = self._run("error503_write", approve_bundle_id="anything")
        self.assertNotEqual("SUCCEEDED", summary["state"])
        self.assertEqual("UNKNOWN", summary["effect_state"])
        self.assertEqual("TRANSIENT_CAPACITY", summary["error_class"])
        self.assertEqual("BLOCKED", summary["promotion"])
        self.assertEqual(ORIGINAL, (self.source / "calc.py").read_text(encoding="utf-8"))

    # 6. partial timeout wording is not success
    def test_partial_timeout_is_blocked(self) -> None:
        summary = self._run("partial_timeout")
        self.assertEqual("TIMEOUT_PARTIAL", summary["error_class"])
        self.assertEqual("BLOCKED", summary["promotion"])

    # 7. write outside staging into a watched root blocks promotion
    def test_outside_write_detected_and_blocked(self) -> None:
        summary = self._run("outside_write", approve_bundle_id="anything")
        self.assertEqual("EXTERNAL_WRITE", summary["error_class"])
        self.assertEqual("UNKNOWN", summary["effect_state"])
        self.assertEqual("BLOCKED", summary["promotion"])
        self.assertEqual(ORIGINAL, (self.source / "calc.py").read_text(encoding="utf-8"))

    # 8. agy only ever sees the staging copy (A1: isolation derived from StagingWorkspace)
    def test_agy_workspace_is_staging_not_source(self) -> None:
        summary = self._run("success")
        workspace = Path(summary["agy_workspace"]).resolve()
        self.assertNotEqual(self.source.resolve(), workspace)
        self.assertTrue(str(workspace).startswith(str(self.work.resolve())))

    # 9. same task replay does not run agy twice (idempotent enqueue)
    def test_replay_same_task_is_idempotent(self) -> None:
        first = self._run("success")
        second = self._run("success")
        self.assertTrue(second["replayed"])
        self.assertEqual(first["bundle_id"], second["bundle_id"])

    # 11. real approval flow: review first run, then approve the SAME task without re-running agy
    def test_approve_same_task_on_replay_applies_saved_bundle(self) -> None:
        first = self._run("success")
        self.assertEqual("DRY_RUN_PASSED", first["promotion"])
        with mock.patch("v7_harness.pilot.AgyProcessLauncher.launch", side_effect=AssertionError("agy must not re-run")):
            second = self._run("success", approve_bundle_id=first["bundle_id"])
        self.assertTrue(second["replayed"])
        self.assertEqual("APPLIED", second["promotion"])
        self.assertIn("def add(a, b):", (self.source / "calc.py").read_text(encoding="utf-8"))
        saved = json.loads(Path(first["summary_path"]).read_text(encoding="utf-8"))
        self.assertEqual("APPLIED", saved["promotion"])

    # 12. replay approval of a failed run never applies
    def test_approve_replay_of_failed_run_is_blocked(self) -> None:
        first = self._run("error503_write")
        second = self._run("error503_write", approve_bundle_id="anything")
        self.assertEqual("BLOCKED", second["promotion"])
        self.assertEqual(ORIGINAL, (self.source / "calc.py").read_text(encoding="utf-8"))
        self.assertEqual(first["state"], second["state"])

    # 10. no-change run is success with empty bundle and nothing to apply
    def test_no_change_is_empty_bundle(self) -> None:
        summary = self._run("no_change")
        self.assertEqual("SUCCEEDED", summary["state"])
        self.assertEqual([], summary["changed_files"])

    # 13. direct sibling file in staging root is detected as external write and blocked
    def test_direct_sibling_file_in_staging_is_detected_and_blocked(self) -> None:
        def fake_launch(*args, **kwargs):
            (self.work / "stage" / "ESCAPED_FROM_STAGING.txt").write_text("escaped sibling\n", encoding="utf-8")
            (self.work / "stage" / "P01" / "calc.py").write_text("\n\ndef add(a, b):\n    return a + b\n", encoding="utf-8")
            from v7_harness.adapters.agy import AgyOutcome
            return AgyOutcome(
                successful=True,
                response_text="DONE",
                conversation_id="fake-conv-rogue",
                usage={"input_tokens": 100},
                duration_seconds=0.1,
                num_turns=1,
            )

        with mock.patch("v7_harness.pilot.AgyProcessLauncher.launch", side_effect=fake_launch):
            summary = run_pilot(self._config(approve_bundle_id="anything"))

        self.assertEqual("FAILED", summary["state"])
        self.assertEqual("EXTERNAL_WRITE", summary["error_class"])
        self.assertEqual("UNKNOWN", summary["effect_state"])
        self.assertEqual("BLOCKED", summary["promotion"])
        self.assertEqual("BLOCKED", summary["verdict_hint"])
        self.assertEqual(ORIGINAL, (self.source / "calc.py").read_text(encoding="utf-8"))


class PilotCliTests(unittest.TestCase):
    def test_cli_defaults_watch_roots_include_home_temp_and_parents(self) -> None:
        from v7_harness import cli

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "project" / "src"
            source.mkdir(parents=True)
            work = root / "workspace" / "coord"
            work.mkdir(parents=True)
            captured = {}

            def fake_run(config):
                captured["watch_roots"] = list(config.watch_roots)
                return {"state": "SUCCEEDED"}

            # U113: local now watches only its stage; these tests keep checking the strict roots of a worker with tools.
            with mock.patch("v7_harness.pilot.run_pilot", side_effect=fake_run), \
                    mock.patch("v7_harness.cli.HARNESS_ONLY_WORKERS", ()):
                args = cli.build_parser().parse_args([
                    "pilot", "run",
                    "--task", "P09",
                    "--source", str(source),
                    "--prompt", "x",
                    "--worker", "local",  # a paid worker needs a manual since B85; this test checks CLI plumbing only
                    "--work-dir", str(work),
                ])
                self.assertEqual(0, args.func(args))

            expected = [
                Path.home().resolve(),
                Path(tempfile.gettempdir()).resolve(),
                work.resolve().parent,
                source.resolve().parent,
                (work / "stage").resolve(),
            ]
            self.assertEqual(expected, captured["watch_roots"])

    def test_cli_defaults_watch_roots_deduplicate_overlapping_parents(self) -> None:
        from v7_harness import cli

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src"
            source.mkdir()
            work = root / "work"
            work.mkdir()
            captured = {}

            def fake_run(config):
                captured["watch_roots"] = list(config.watch_roots)
                return {"state": "SUCCEEDED"}

            # U113: local now watches only its stage; these tests keep checking the strict roots of a worker with tools.
            with mock.patch("v7_harness.pilot.run_pilot", side_effect=fake_run), \
                    mock.patch("v7_harness.cli.HARNESS_ONLY_WORKERS", ()):
                args = cli.build_parser().parse_args([
                    "pilot", "run",
                    "--task", "P09",
                    "--source", str(source),
                    "--prompt", "x",
                    "--worker", "local",  # a paid worker needs a manual since B85; this test checks CLI plumbing only
                    "--work-dir", str(work),
                ])
                self.assertEqual(0, args.func(args))

            expected = list(dict.fromkeys([
                Path.home().resolve(),
                Path(tempfile.gettempdir()).resolve(),
                work.resolve().parent,
                source.resolve().parent,
                (work / "stage").resolve(),
            ]))
            self.assertEqual(expected, captured["watch_roots"])

    def test_cli_explicit_watch_root_augments_mandatory_safety_roots(self) -> None:
        from v7_harness import cli

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "src"
            source.mkdir()
            custom_watch = Path(tmp) / "custom"
            custom_watch.mkdir()
            captured = {}

            def fake_run(config):
                captured["watch_roots"] = list(config.watch_roots)
                return {"state": "SUCCEEDED"}

            # U113: local now watches only its stage; these tests keep checking the strict roots of a worker with tools.
            with mock.patch("v7_harness.pilot.run_pilot", side_effect=fake_run), \
                    mock.patch("v7_harness.cli.HARNESS_ONLY_WORKERS", ()):
                args = cli.build_parser().parse_args([
                    "pilot", "run",
                    "--task", "P09",
                    "--source", str(source),
                    "--prompt", "x",
                    "--worker", "local",  # a paid worker needs a manual since B85; this test checks CLI plumbing only
                    "--work-dir", tmp,
                    "--watch-root", str(custom_watch),
                ])
                self.assertEqual(0, args.func(args))

            expected = list(dict.fromkeys([
                Path.home().resolve(),
                Path(tempfile.gettempdir()).resolve(),
                Path(tmp).resolve().parent,
                source.resolve().parent,
                (Path(tmp) / "stage").resolve(),
                custom_watch.resolve(),
            ]))
            self.assertEqual(expected, captured["watch_roots"])

    def test_cli_explicit_watch_roots_deduplicate_deterministically(self) -> None:
        from v7_harness import cli

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "src"
            source.mkdir()
            custom_watch = Path(tmp) / "custom"
            custom_watch.mkdir()
            captured = {}

            def fake_run(config):
                captured["watch_roots"] = list(config.watch_roots)
                return {"state": "SUCCEEDED"}

            # U113: local now watches only its stage; these tests keep checking the strict roots of a worker with tools.
            with mock.patch("v7_harness.pilot.run_pilot", side_effect=fake_run), \
                    mock.patch("v7_harness.cli.HARNESS_ONLY_WORKERS", ()):
                args = cli.build_parser().parse_args([
                    "pilot", "run",
                    "--task", "P09",
                    "--source", str(source),
                    "--prompt", "x",
                    "--worker", "local",  # a paid worker needs a manual since B85; this test checks CLI plumbing only
                    "--work-dir", tmp,
                    "--watch-root", str(custom_watch),
                    "--watch-root", str(Path.home()),
                    "--watch-root", str(custom_watch),
                ])
                self.assertEqual(0, args.func(args))

            expected = list(dict.fromkeys([
                Path.home().resolve(),
                Path(tempfile.gettempdir()).resolve(),
                Path(tmp).resolve().parent,
                source.resolve().parent,
                (Path(tmp) / "stage").resolve(),
                custom_watch.resolve(),
            ]))
            self.assertEqual(expected, captured["watch_roots"])


class ApplyPromotionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "src"
        self.source.mkdir()
        (self.source / "a.py").write_text("x = 1\n", encoding="utf-8")
        (self.source / "b.py").write_text("y = 1\n", encoding="utf-8")
        self.workspace = NonGitStagingAdapter().create_staging(self.source, self.root / "stage")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_rejects_when_source_diverged_after_bundle(self) -> None:
        (self.workspace.staging_dir / "a.py").write_text("x = 2\n", encoding="utf-8")
        bundle = self.workspace.create_patch_bundle()
        (self.source / "b.py").write_text("y = 99\n", encoding="utf-8")
        with self.assertRaises(IsolationError):
            apply_promotion(source_dir=self.source, staging_dir=self.workspace.staging_dir, patch_bundle=bundle, approve_bundle_id=bundle.bundle_id)
        self.assertEqual("x = 1\n", (self.source / "a.py").read_text(encoding="utf-8"))

    def test_rejects_delete_items(self) -> None:
        (self.workspace.staging_dir / "b.py").unlink()
        bundle = self.workspace.create_patch_bundle()
        with self.assertRaises(IsolationError):
            apply_promotion(source_dir=self.source, staging_dir=self.workspace.staging_dir, patch_bundle=bundle, approve_bundle_id=bundle.bundle_id)
        self.assertTrue((self.source / "b.py").exists())

    def test_rejects_staging_content_changed_after_bundle(self) -> None:
        (self.workspace.staging_dir / "a.py").write_text("x = 2\n", encoding="utf-8")
        bundle = self.workspace.create_patch_bundle()
        (self.workspace.staging_dir / "a.py").write_text("x = 3  # tampered\n", encoding="utf-8")
        with self.assertRaises(IsolationError):
            apply_promotion(source_dir=self.source, staging_dir=self.workspace.staging_dir, patch_bundle=bundle, approve_bundle_id=bundle.bundle_id)
        self.assertEqual("x = 1\n", (self.source / "a.py").read_text(encoding="utf-8"))

    def test_applies_modify_and_add_with_matching_approval(self) -> None:
        (self.workspace.staging_dir / "a.py").write_text("x = 2\n", encoding="utf-8")
        (self.workspace.staging_dir / "c.py").write_text("z = 3\n", encoding="utf-8")
        bundle = self.workspace.create_patch_bundle()
        result = apply_promotion(source_dir=self.source, staging_dir=self.workspace.staging_dir, patch_bundle=bundle, approve_bundle_id=bundle.bundle_id)
        self.assertEqual(sorted(["a.py", "c.py"]), sorted(result["applied"]))
        self.assertEqual("x = 2\n", (self.source / "a.py").read_text(encoding="utf-8"))
        self.assertEqual("z = 3\n", (self.source / "c.py").read_text(encoding="utf-8"))

    def test_apply_rolls_back_all_files_when_later_replace_fails(self) -> None:
        (self.workspace.staging_dir / "a.py").write_text("x = 2\n", encoding="utf-8")
        (self.workspace.staging_dir / "b.py").write_text("y = 2\n", encoding="utf-8")
        bundle = self.workspace.create_patch_bundle()
        real_replace = os.replace
        forward_replacements = 0

        def fail_second_forward(source, target):
            nonlocal forward_replacements
            source_path = Path(source)
            if "payload" in source_path.parts:
                forward_replacements += 1
                if forward_replacements == 2:
                    raise OSError("simulated second replace failure")
            return real_replace(source, target)

        with mock.patch("v7_harness.isolation.promotion.os.replace", side_effect=fail_second_forward):
            with self.assertRaises(OSError):
                apply_promotion(
                    source_dir=self.source,
                    staging_dir=self.workspace.staging_dir,
                    patch_bundle=bundle,
                    approve_bundle_id=bundle.bundle_id,
                )
        self.assertEqual("x = 1\n", (self.source / "a.py").read_text(encoding="utf-8"))
        self.assertEqual("y = 1\n", (self.source / "b.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
