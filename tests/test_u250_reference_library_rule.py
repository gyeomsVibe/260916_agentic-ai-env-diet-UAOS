"""U250: Unit & Contract Tests for the Canonical Reference & Benchmark Library Global Rule."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from v7_harness.library_store import (
    CANONICAL_LIBRARY_PATH_STR,
    CANONICAL_LIBRARY_ROOT,
    extract_repo_name,
    inspect_library_repo,
    register_library_entry,
    resolve_library_repo_path,
)


class TestU250ReferenceLibraryRule(unittest.TestCase):
    def test_canonical_library_root_constant(self) -> None:
        self.assertEqual(
            CANONICAL_LIBRARY_PATH_STR,
            r"D:\D_Workspace_NB\-agentic-ai-workspace\260916_agentic-ai-env-diet\.work\library",
        )
        self.assertEqual(CANONICAL_LIBRARY_ROOT.name, "library")
        self.assertEqual(CANONICAL_LIBRARY_ROOT.parent.name, ".work")

    def test_extract_and_resolve_library_repo_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".work" / "library"
            root.mkdir(parents=True, exist_ok=True)

            self.assertEqual(extract_repo_name("https://github.com/morluto/rea.git"), "rea")
            self.assertEqual(extract_repo_name("https://github.com/mvschwarz/openrig"), "openrig")
            self.assertEqual(
                extract_repo_name("UnrealFactory/AgentCodeGUI"),
                "AgentCodeGUI",
            )
            resolved = resolve_library_repo_path("https://github.com/morluto/rea", root)
            self.assertEqual(resolved, (root / "rea").resolve())

            with self.assertRaises(ValueError):
                resolve_library_repo_path("../escape", root)
            with self.assertRaises(ValueError):
                extract_repo_name("_analysis")

    def test_register_library_entry_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".work" / "library"
            readme = register_library_entry(
                library_root=root,
                folder_name="rea",
                source_url="https://github.com/morluto/rea",
                license_id="MIT",
                commit_sha="1173c0a9d",
                file_count=6324,
                description="TypeScript/MCP/Polyglot",
            )
            self.assertTrue(readme.is_file())
            text1 = readme.read_text(encoding="utf-8")
            self.assertIn("| `rea/` | https://github.com/morluto/rea (TypeScript/MCP/Polyglot) | MIT | 1173c0a9d | 6324 |", text1)

            # Update existing entry without duplicating rows
            register_library_entry(
                library_root=root,
                folder_name="rea",
                source_url="https://github.com/morluto/rea",
                license_id="MIT",
                commit_sha="1173c0a9d",
                file_count=6324,
                description="Updated description",
            )
            text2 = readme.read_text(encoding="utf-8")
            self.assertEqual(text2.count("| `rea/` |"), 1)
            self.assertIn("Updated description", text2)

    def test_live_library_repositories_and_rule_files(self) -> None:
        if CANONICAL_LIBRARY_ROOT.is_dir():
            for expected in ("openrig", "AgentCodeGUI", "rea"):
                repo_dir = CANONICAL_LIBRARY_ROOT / expected
                if repo_dir.is_dir():
                    info = inspect_library_repo(repo_dir)
                    self.assertTrue(info["ok"], msg=f"{expected} failed inspection: {info}")
                    self.assertGreater(info["file_count"], 100)
                    self.assertTrue(info["read_only_isolated"])

        repo_root = Path(__file__).resolve().parent.parent
        for rel in (
            "uaos_everywhere/uaos_global_rule_block.md",
            "uaos_everywhere/skills/mia-strategic/SKILL.md",
            "AGENTS.md",
            "CLAUDE.md",
            "GEMINI.md",
            ".coord/PROJECT_MANUAL.md",
        ):
            target = repo_root / rel
            self.assertTrue(target.is_file(), msg=f"Missing rule file: {rel}")
            content = target.read_text(encoding="utf-8")
            self.assertIn(".work", content, msg=f"Missing .work reference in {rel}")
            self.assertIn("library", content, msg=f"Missing library reference in {rel}")


if __name__ == "__main__":
    unittest.main()
