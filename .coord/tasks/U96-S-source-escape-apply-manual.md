```contract
work_id: U96-S
worker: apply
goal: After every Antigravity pilot run, name each source file that changed while the worker ran (its workspace is the stage), even when another error ended the run first; a change with no other error fails the run as SOURCE_DIVERGED.
inputs:
- .coord/PLAN.md sha256=2281a94cd5fd19bf9bc7ac74502195ec9bf9da898e81aa1bbc59238f53a62cf7
- v7_harness/pilot.py sha256=eb47c39c61dfb82aa9f54c679e0ccdf1ec1ca314d8218979ce81b33151b767c0
- tests/test_b41_bundle.py sha256=adede9c2eb30020daf66a3dc9bb10ec0284bcc42a24f6b84560b1524fadf3bec
allow:
- v7_harness/pilot.py
- tests/test_u96s_source_escape.py
- .coord/PLAN.md
acceptance: python -m unittest tests.test_u96s_source_escape tests.test_b41_bundle
forbidden: design changes; edits outside allow; editing or weakening existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the blocks below exactly; they are the whole change. Receipt: U95-R (2026-09-30) Antigravity wrote `.coord/notes/U95_token_thrift_research.md` into the source worktree instead of its stage `.coord/stage/U95-R`. The pilot never named it: an earlier EXTERNAL_WRITE ended the run, and the whole-manifest divergence check in the dry run names no path.

===EDIT: v7_harness/pilot.py===
<<<<<<< SEARCH
from v7_harness.isolation.manifest import PatchBundle, build_manifest
=======
from v7_harness.isolation.manifest import DeterministicManifest, PatchBundle, build_manifest
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/pilot.py===
<<<<<<< SEARCH
def reconcile_pilot(*, work_dir: Path, task_id: str) -> dict[str, Any]:
=======
# A runaway worker can touch thousands of files; the summary names the first 50 (sorted), enough to judge the escape.
SOURCE_ESCAPE_LIST_LIMIT = 50


def source_escape_paths(base: DeterministicManifest, source_dir: Path, excludes: list[str]) -> list[str]:
    """Source files changed while the worker ran, relative and sorted (U96-S).

    The worker's workspace is the stage, so a changed source file escaped containment, or a second writer ran during
    the paid run; both break the single-writer rule, which is why the class stays SOURCE_DIVERGED. An unreadable source
    returns [] here: the dry run and apply still fail closed on the manifest hash.
    """
    try:
        now = build_manifest(source_dir, excludes=excludes)
    except Exception:
        return []
    if now.manifest_hash == base.manifest_hash:
        return []
    before = {entry.path: entry.sha256 for entry in base.entries}
    after = {entry.path: entry.sha256 for entry in now.entries}
    changed = sorted(path for path in before.keys() | after.keys() if before.get(path) != after.get(path))
    return changed[:SOURCE_ESCAPE_LIST_LIMIT]


def reconcile_pilot(*, work_dir: Path, task_id: str) -> dict[str, Any]:
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/pilot.py===
<<<<<<< SEARCH
        except Exception:
            watch_error = ("EXTERNAL_WRITE", "UNKNOWN")

        # 10. Success check and bundle creation
=======
        except Exception:
            watch_error = ("EXTERNAL_WRITE", "UNKNOWN")

        # 9b. U96-S: name every source file changed during the run, even when another error ended it first.
        source_changed = source_escape_paths(workspace.base_manifest, Path(config.source_dir), source_excludes)
        if source_changed and watch_error is None:
            watch_error = ("SOURCE_DIVERGED", "UNKNOWN")
        external_paths.extend(f"source:{path}" for path in source_changed)

        # 10. Success check and bundle creation
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/pilot.py===
<<<<<<< SEARCH
        # B41: external_paths for EXTERNAL_WRITE
        if external_paths and error_class == "EXTERNAL_WRITE":
            summary["external_paths"] = external_paths
=======
        # B41: external_paths for EXTERNAL_WRITE; U96-S adds source files (prefix "source:") under either class.
        if external_paths and error_class in ("EXTERNAL_WRITE", "SOURCE_DIVERGED"):
            summary["external_paths"] = external_paths
>>>>>>> REPLACE
===END===

===EDIT: .coord/PLAN.md===
<<<<<<< SEARCH
`v7_harness/coord/mode.py`, `v7_harness/coord/card_cost.py`, `v7_harness/coord/hook_context.py`, `tests/test_u95t_thrift_mode.py` |
=======
`v7_harness/coord/mode.py`, `v7_harness/coord/card_cost.py`, `v7_harness/coord/hook_context.py`, `tests/test_u95t_thrift_mode.py` |
| U96-S | REVIEW (Claude 설계, Codex 복귀 시 재검토) | claude(설계) · apply(0토큰) | 영수증: U95-R에서 Antigravity가 작업 폴더(stage) 대신 원본 작업 트리에 노트를 썼는데 파일럿이 경로를 남기지 않았다(앞선 EXTERNAL_WRITE가 먼저 실행을 끝냈고, 드라이런의 전체 해시 비교는 경로를 말하지 않는다). 조치: 실행 직후 원본 매니페스트를 다시 재어 바뀐 파일을 `external_paths`에 `source:` 접두어로 남기고, 다른 오류가 없으면 SOURCE_DIVERGED로 실패시킨다. — `v7_harness/pilot.py`, `tests/test_u96s_source_escape.py` |
>>>>>>> REPLACE
===END===

===FILE: tests/test_u96s_source_escape.py===
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


if __name__ == "__main__":
    unittest.main()
===END===
