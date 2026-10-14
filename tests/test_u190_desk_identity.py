"""U190-A: one read-only desk identity for all three tools, built only from the existing validators.

Receipt (Codex PIVOT relay_82dae048, PASS relay_6699e249; inventory .work/u189/prereq_inventory.md): U189 needed a
validated user desk per tool, but only codex had one (deliver._verify_thread). desk_sync.desk_identity(project, tool)
returns (status, identity):
- PROJECT_BOUND: the record names a thread the tool's own native metadata proves belongs to this project
  (codex: _verify_thread; claude: windows.claude_session exact id, one transcript, absolute cwd in the project's
  registered roots). Only this status may ever count as delivered.
- UNBOUND_EXISTS: antigravity, whose conversation exists but records no project anywhere UAOS reads. Typed
  unsupported scope, never delivered.
- anything else fails closed: ABSENT, CORRUPT, LEGACY (no generation), BAD_GENERATION (not an int >= 1, bool
  excluded), UNVERIFIED, PROJECT_MISMATCH, UNKNOWN_TOOL. Reading never writes a file.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import desk_sync

THREAD = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


class DeskIdentity(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.project = base / "project"
        self.foreign = base / "foreign"
        self.project.mkdir()
        self.foreign.mkdir()
        self.codex_home = base / "codex_sessions"
        self.claude_home = base / "claude_home"
        self.agy_home = base / "agy_home"
        env = {"UAOS_CODEX_SESSIONS": str(self.codex_home), "CLAUDE_CONFIG_DIR": str(self.claude_home),
               "UAOS_AGY_APP_HOME": str(self.agy_home)}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    # fixtures ---------------------------------------------------------------------------------------------------
    def record(self, tool: str, thread: str = THREAD, generation: object = 1, *, raw: str | None = None) -> None:
        path = self.project / ".coord" / "presence" / f"user_desk_{tool}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"thread": thread, "source": "test"}
        if generation is not None:
            data["generation"] = generation
        path.write_text(raw if raw is not None else json.dumps(data), encoding="utf-8")

    def codex_rollout(self, thread: str = THREAD, cwd: Path | None = None) -> None:
        day = self.codex_home / "2026" / "10" / "14"
        day.mkdir(parents=True, exist_ok=True)
        meta = {"type": "session_meta", "payload": {"id": thread, "session_id": thread,
                                                     "cwd": str(cwd or self.project)}}
        (day / f"rollout-2026-10-14T06-00-00-{thread}.jsonl").write_text(json.dumps(meta) + "\n", encoding="utf-8")

    def claude_transcript(self, name: str = THREAD, cwd: object = "project", session: object = "name") -> None:
        folder = self.claude_home / "projects" / "D--project"
        folder.mkdir(parents=True, exist_ok=True)
        value = str(self.project) if cwd == "project" else cwd
        rows = [{"type": "user", "sessionId": name if session == "name" else session}]
        if value is not None:
            rows.append({"type": "user", "cwd": value})
        (folder / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    def agy_conversation(self, thread: str = THREAD) -> None:
        (self.agy_home / "brain" / thread).mkdir(parents=True, exist_ok=True)

    def snapshot(self) -> dict[str, str]:
        base = Path(self._tmp.name)
        return {str(p.relative_to(base)): hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "dir"
                for p in sorted(base.rglob("*"))}

    def identity(self, tool: str) -> tuple[str, dict]:
        before = self.snapshot()
        result = desk_sync.desk_identity(self.project, tool)
        self.assertEqual(before, self.snapshot(), "desk_identity must not write anything")
        return result

    # the three-tool status matrix -------------------------------------------------------------------------------
    def test_codex_bound_by_its_rollout(self) -> None:
        self.record("codex")
        self.codex_rollout()
        self.assertEqual(self.identity("codex"), ("PROJECT_BOUND", {"thread": THREAD, "generation": 1}))

    def test_claude_bound_by_its_transcript(self) -> None:
        self.record("claude")
        self.claude_transcript()
        self.assertEqual(self.identity("claude"), ("PROJECT_BOUND", {"thread": THREAD, "generation": 1}))

    def test_antigravity_exists_but_is_never_bound(self) -> None:
        self.record("antigravity")
        self.agy_conversation()
        self.assertEqual(self.identity("antigravity"), ("UNBOUND_EXISTS", {"thread": THREAD, "generation": 1}))

    def test_missing_native_session_is_unverified_for_every_tool(self) -> None:
        for tool in ("codex", "claude", "antigravity"):
            with self.subTest(tool=tool):
                self.record(tool)
                self.assertEqual(self.identity(tool), ("UNVERIFIED", {}))

    def test_absent_record(self) -> None:
        for tool in ("codex", "claude", "antigravity"):
            with self.subTest(tool=tool):
                self.assertEqual(self.identity(tool), ("ABSENT", {}))

    def test_unknown_tool(self) -> None:
        self.assertEqual(self.identity("gemini"), ("UNKNOWN_TOOL", {}))

    # record defects ---------------------------------------------------------------------------------------------
    def test_corrupt_records_fail_closed(self) -> None:
        for raw in ("", "{not json", "[]", json.dumps({"thread": "not-a-uuid", "generation": 1}),
                    json.dumps({"generation": 1})):
            with self.subTest(raw=raw):
                self.record("claude", raw=raw)
                self.claude_transcript()
                self.assertEqual(self.identity("claude"), ("CORRUPT", {}))

    def test_legacy_record_without_generation(self) -> None:
        self.record("codex", generation=None)
        self.codex_rollout()
        self.assertEqual(self.identity("codex"), ("LEGACY", {}))

    def test_generation_must_be_an_int_of_at_least_one(self) -> None:
        for generation in (0, -1, 1.0, "1", True, False, [1]):
            with self.subTest(generation=generation):
                self.record("claude", generation=generation)
                self.claude_transcript()
                self.assertEqual(self.identity("claude"), ("BAD_GENERATION", {}))

    def test_same_thread_new_generation_is_a_new_identity(self) -> None:
        self.claude_transcript()
        self.record("claude", generation=1)
        first = self.identity("claude")
        self.record("claude", generation=2)
        second = self.identity("claude")
        self.assertEqual(first[1]["thread"], second[1]["thread"])
        self.assertNotEqual(first, second)
        self.assertEqual(second, ("PROJECT_BOUND", {"thread": THREAD, "generation": 2}))

    # project binding --------------------------------------------------------------------------------------------
    def test_wrong_project_fails_closed(self) -> None:
        self.record("codex")
        self.codex_rollout(cwd=self.foreign)
        self.assertEqual(self.identity("codex"), ("PROJECT_MISMATCH", {}))
        self.record("claude")
        self.claude_transcript(cwd=str(self.foreign))
        self.assertEqual(self.identity("claude"), ("PROJECT_MISMATCH", {}))

    def test_claude_missing_empty_or_relative_cwd_is_unverified(self) -> None:
        for cwd in (None, "", "relative/path"):
            with self.subTest(cwd=cwd):
                for old in (self.claude_home / "projects").rglob("*.jsonl"):
                    old.unlink()
                self.record("claude")
                self.claude_transcript(cwd=cwd)
                self.assertEqual(self.identity("claude"), ("UNVERIFIED", {}))

    def test_claude_prefix_collision_is_unverified(self) -> None:
        self.record("claude")
        self.claude_transcript()
        self.claude_transcript(name=f"{THREAD}-copy")  # two transcripts match the id prefix: ambiguous
        self.assertEqual(self.identity("claude"), ("UNVERIFIED", {}))

    def test_claude_transcript_of_another_thread_does_not_bind(self) -> None:
        self.record("claude")
        self.claude_transcript(name=OTHER)
        self.assertEqual(self.identity("claude"), ("UNVERIFIED", {}))

    # native metadata, not the file name (Codex REVISE relay_b1204616) ----------------------------------------------
    def test_claude_filename_with_another_native_session_does_not_bind(self) -> None:
        self.record("claude")
        self.claude_transcript(session=OTHER)  # named THREAD, rows say OTHER, cwd is this project
        self.assertEqual(self.identity("claude"), ("UNVERIFIED", {}))

    def test_claude_transcript_mixing_sessions_does_not_bind(self) -> None:
        self.record("claude")
        self.claude_transcript()
        path = next((self.claude_home / "projects").rglob(f"{THREAD}.jsonl"))
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "user", "sessionId": OTHER}) + "\n")
        self.assertEqual(self.identity("claude"), ("UNVERIFIED", {}))

    def test_claude_transcript_without_native_session_does_not_bind(self) -> None:
        for session in (None, ""):
            with self.subTest(session=session):
                for old in (self.claude_home / "projects").rglob("*.jsonl"):
                    old.unlink()
                self.record("claude")
                self.claude_transcript(session=session)
                self.assertEqual(self.identity("claude"), ("UNVERIFIED", {}))

    def test_claude_corrupt_transcript_does_not_bind(self) -> None:
        self.record("claude")
        folder = self.claude_home / "projects" / "D--project"
        folder.mkdir(parents=True)
        (folder / f"{THREAD}.jsonl").write_bytes(b"\xff\xfe{not json\n\x00\x01\n")
        self.assertEqual(self.identity("claude"), ("UNVERIFIED", {}))

    def test_an_unavailable_native_reader_fails_closed_without_writes(self) -> None:
        cases = (("claude", "v7_harness.coord.windows.claude_session_identity", self.claude_transcript),
                 ("codex", "v7_harness.coord.deliver._verify_thread", self.codex_rollout),
                 ("antigravity", "v7_harness.coord.deliver.agy_desktop_conversation", self.agy_conversation))
        for tool, target, native in cases:
            for error in (PermissionError("denied"), OSError("busy"), UnicodeDecodeError("utf-8", b"", 0, 1, "x")):
                with self.subTest(tool=tool, error=type(error).__name__):
                    self.record(tool)
                    native()
                    with mock.patch(target, side_effect=error):
                        self.assertEqual(self.identity(tool), ("UNREADABLE", {}))

    def test_an_unavailable_project_root_check_fails_closed(self) -> None:
        self.record("claude")
        self.claude_transcript()
        with mock.patch("v7_harness.coord.deliver._registered_roots", side_effect=PermissionError("denied")):
            self.assertEqual(self.identity("claude"), ("UNREADABLE", {}))


if __name__ == "__main__":
    unittest.main()
