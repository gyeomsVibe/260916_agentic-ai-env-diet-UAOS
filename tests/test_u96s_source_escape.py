"""U96-S: an Antigravity run that writes into the source, not its stage, is named and fails.

Receipt: U95-R (2026-09-30) wrote its note into the source worktree; the pilot summary named only `_b` in temp.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.adapters.agy import AgyOutcome
from v7_harness.isolation.errors import ExternalWriteDetectedError
from v7_harness.isolation.manifest import build_manifest
from v7_harness.pilot import PilotConfig, run_pilot, source_escape_paths


class SourceEscapeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.source = root / "source"
        self.work = root / "work"
        self.home = root / "home"
        for folder in (self.source, self.work, self.home):
            folder.mkdir()
        (self.source / "calc.py").write_text("def mul(a, b): return a * b\n", encoding="utf-8")
        (self.source / "old.txt").write_text("old\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _config(self, task_id: str) -> PilotConfig:
        return PilotConfig(
            task_id=task_id,
            title=task_id,
            prompt="write the note",
            source_dir=self.source,
            work_dir=self.work,
            agy_command=["python", "-c", "import sys; sys.exit(0)"],
            watch_roots=[self.home],
            print_timeout_s=10,
        )

    def _run(self, task_id: str, write_source: bool, watch: object | None = None) -> dict:
        def fake_execute(*args: object, **kwargs: object) -> None:
            if write_source:
                (self.source / "notes").mkdir(exist_ok=True)
                (self.source / "notes" / "escaped.md").write_text("note\n", encoding="utf-8")

        launcher = mock.MagicMock()
        launcher.last_outcome = AgyOutcome(
            successful=True, status="SUCCESS", error_class="NONE", effect_state="CONFIRMED", retryable=False,
            conversation_id="conv", usage={"input_tokens": 1},
        )
        launcher.raw_paths = (self.work / "stdout.json", self.work / "stderr.err")
        patches = [
            mock.patch("v7_harness.pilot.DurableExecutionEngine.execute", side_effect=fake_execute),
            mock.patch("v7_harness.pilot.AgyProcessLauncher", return_value=launcher),
        ]
        if watch is not None:
            patches.append(mock.patch("v7_harness.pilot.snapshot_watch_roots", return_value=watch))
        for patch in patches:
            patch.start()
        try:
            return run_pilot(self._config(task_id))
        finally:
            for patch in reversed(patches):
                patch.stop()

    def test_source_write_fails_and_is_named(self) -> None:
        summary = self._run("U96S_ESCAPE", write_source=True)
        self.assertEqual(summary["state"], "FAILED")
        self.assertEqual(summary["error_class"], "SOURCE_DIVERGED")
        self.assertEqual(summary["external_paths"], ["source:notes/escaped.md"])

    def test_source_write_is_named_even_after_an_external_write(self) -> None:
        class MutatingWatch:
            def assert_unchanged(self) -> None:
                raise ExternalWriteDetectedError("External write", effect_state="UNKNOWN", changed_paths=["_b"])

        summary = self._run("U96S_BOTH", write_source=True, watch=MutatingWatch())
        self.assertEqual(summary["error_class"], "EXTERNAL_WRITE")
        self.assertEqual(summary["external_paths"], ["_b", "source:notes/escaped.md"])

    def test_clean_run_names_nothing(self) -> None:
        summary = self._run("U96S_CLEAN", write_source=False)
        self.assertNotEqual(summary["error_class"], "SOURCE_DIVERGED")
        self.assertNotIn("external_paths", summary)

    def test_paths_cover_added_modified_and_deleted(self) -> None:
        base = build_manifest(self.source)
        (self.source / "calc.py").write_text("def mul(a, b): return b * a\n", encoding="utf-8")
        (self.source / "old.txt").unlink()
        (self.source / "new.txt").write_text("new\n", encoding="utf-8")
        self.assertEqual(source_escape_paths(base, self.source, []), ["calc.py", "new.txt", "old.txt"])
        self.assertEqual(source_escape_paths(build_manifest(self.source), self.source, []), [])

    def test_no_base_manifest_names_nothing(self) -> None:
        self.assertEqual(source_escape_paths(None, self.source, []), [])


if __name__ == "__main__":
    unittest.main()
