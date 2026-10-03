from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from v7_harness.isolation.manifest import DEFAULT_EXCLUDES, build_manifest


class B58RelayManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        files = {
            ".claude/codex-relay/sent.log": "before\n",
            ".claude/codex-relay/nested/run.log": "before\n",
            ".claude/codex-relay/codex_relay.sh": "echo safe\n",
            ".claude/settings.json": "{}\n",
            ".claude/skills/demo/SKILL.md": "skill\n",
            ".claude/hooks/hook.py": "hook = 1\n",
            ".claude/agents/a.md": "agent\n",
            ".claude/commands/c.md": "command\n",
            ".claude/rules/r.md": "rule\n",
            "src/app.py": "value = 1\n",
        }
        for relative, content in files.items():
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_relay_runtime_logs_are_excluded_including_nested_logs(self) -> None:
        before = build_manifest(self.root).manifest_hash
        (self.root / ".claude/codex-relay/sent.log").write_text("after\n", encoding="utf-8")
        (self.root / ".claude/codex-relay/nested/run.log").write_text("after\n", encoding="utf-8")
        self.assertEqual(before, build_manifest(self.root).manifest_hash)

    def test_relay_scripts_remain_protected(self) -> None:
        before = build_manifest(self.root).manifest_hash
        (self.root / ".claude/codex-relay/codex_relay.sh").write_text("echo changed\n", encoding="utf-8")
        self.assertNotEqual(before, build_manifest(self.root).manifest_hash)

    def test_all_protected_claude_paths_remain_detected(self) -> None:
        protected = [
            ".claude/settings.json",
            ".claude/skills/demo/SKILL.md",
            ".claude/hooks/hook.py",
            ".claude/agents/a.md",
            ".claude/commands/c.md",
            ".claude/rules/r.md",
        ]
        for relative in protected:
            with self.subTest(path=relative):
                before = build_manifest(self.root).manifest_hash
                target = self.root / relative
                original = target.read_text(encoding="utf-8")
                target.write_text(original + "changed\n", encoding="utf-8")
                self.assertNotEqual(before, build_manifest(self.root).manifest_hash)
                target.write_text(original, encoding="utf-8")

    def test_claude_tree_is_not_broadly_excluded(self) -> None:
        self.assertNotIn(".claude", DEFAULT_EXCLUDES)

    def test_claude_worktrees_are_excluded_while_other_claude_files_remain(self) -> None:
        self.assertIn(".claude/worktrees", DEFAULT_EXCLUDES)
        manifest_before = build_manifest(self.root)
        hash_before = manifest_before.manifest_hash

        wt_file = self.root / ".claude" / "worktrees" / "wt1" / "file.py"
        wt_file.parent.mkdir(parents=True, exist_ok=True)
        wt_file.write_text("print('worktree')\n", encoding="utf-8")

        manifest_after = build_manifest(self.root)
        self.assertEqual(hash_before, manifest_after.manifest_hash)
        self.assertIsNone(manifest_after.get_entry(".claude/worktrees/wt1/file.py"))

        wt_file.write_text("print('modified worktree')\n", encoding="utf-8")
        self.assertEqual(hash_before, build_manifest(self.root).manifest_hash)

        normal_claude = self.root / ".claude" / "settings.json"
        self.assertIsNotNone(manifest_after.get_entry(".claude/settings.json"))
        normal_claude.write_text("{\"updated\": true}\n", encoding="utf-8")
        self.assertNotEqual(hash_before, build_manifest(self.root).manifest_hash)


if __name__ == "__main__":
    unittest.main()
