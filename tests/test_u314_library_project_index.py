from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from v7_harness.library_store import (
    KNOWN_LIBRARY_PROJECT_PROFILES,
    build_library_catalog_index,
    create_excluded_library_session,
    create_library_project_session,
    identify_library_project,
)


class TestU314LibraryProjectIndex(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        lib_dir = self.root / ".work" / "library"
        lib_dir.mkdir(parents=True, exist_ok=True)
        # Populate hermetic fixture tree for the 10 selected library repositories
        for slug, prof in KNOWN_LIBRARY_PROJECT_PROFILES.items():
            repo_dir = lib_dir / prof["canonical_dir"]
            git_dir = repo_dir / ".git"
            git_dir.mkdir(parents=True, exist_ok=True)
            (git_dir / "HEAD").write_text("a" * 40 + "\n", encoding="utf-8")
            (git_dir / "config").write_text(
                f'[remote "origin"]\n\turl = https://github.com/{prof["upstream_repo"]}.git\n',
                encoding="utf-8",
            )
            (repo_dir / "README.md").write_text(
                f"# {prof['canonical_dir']}\n\nHermetic test fixture for {slug}.\n",
                encoding="utf-8",
            )
            (repo_dir / "pyproject.toml").write_text("[project]\nname = 'fixture'\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_selected_vs_excluded_curated_catalog_and_freshness(self) -> None:
        catalog = build_library_catalog_index(self.root)
        self.assertEqual(catalog["schema"], "uaos.library_catalog_index.v3")
        self.assertEqual(catalog["total_selected_projects"], 10)
        self.assertEqual(catalog["total_excluded_projects"], 14)
        self.assertTrue(catalog["deduplicated"])
        self.assertTrue(catalog["catalog_freshness_digest"])
        self.assertEqual(catalog["unified_excluded_root"], ".work/library/_excluded")

        # Verify legacy duplicate folders are gone
        self.assertFalse((self.root / ".work" / "library" / "_excluded_sessions").exists())
        self.assertFalse((self.root / ".work" / "library" / "_tmp").exists())

        # Verify _analysis and _sessions contain ONLY the 10 selected projects (zero excluded duplicates)
        analysis_dirs = {p.name.lower() for p in (self.root / ".work" / "library" / "_analysis").iterdir() if p.is_dir()}
        session_dirs = {p.name.lower() for p in (self.root / ".work" / "library" / "_sessions").iterdir() if p.is_dir()}
        selected_names = {p["repo_name"].lower() for p in catalog["selected_projects"]}
        self.assertEqual(analysis_dirs, selected_names)
        self.assertEqual(session_dirs, selected_names)

        excluded_slugs = {e["repo_slug"].lower() for e in catalog["excluded_projects"]}
        for excluded in ("impeccable", "taste-skill", "agent-reach", "openrig", "voicestudio", "hyperframes", "comfyui", "ghidra", "freellmapi", "deepinfer", "ecc"):
            self.assertIn(excluded, excluded_slugs)
            self.assertNotIn(excluded, selected_names)
            self.assertNotIn(excluded, analysis_dirs)

        self.assertTrue((self.root / ".work" / "library" / "_excluded" / "session.json").exists())

    def test_identify_selected_and_excluded_projects(self) -> None:
        info = identify_library_project(self.root, "graphify")
        self.assertEqual(info["selection_status"], "SELECTED_FOR_UAOS_RSI")
        self.assertEqual(info["upstream_repo"], "Graphify-Labs/graphify")
        self.assertTrue(info["freshness_digest"])
        self.assertTrue(info["latest_mtime_utc"])
        self.assertTrue(info["read_only"])

        excl_info = identify_library_project(self.root, "impeccable")
        self.assertEqual(excl_info["selection_status"], "EXCLUDED_OUT_OF_SCOPE")
        self.assertIn("4,469", excl_info["exclusion_reason_ko"])

    def test_isolated_sessions_for_selected_and_excluded(self) -> None:
        sess = create_library_project_session(self.root, "ai-memory")
        self.assertTrue(sess["session_id"].startswith("libsess_ai-memory_"))
        self.assertEqual(sess["selection_status"], "SELECTED_FOR_UAOS_RSI")

        excl_sess = create_excluded_library_session(self.root)
        self.assertEqual(excl_sess["status"], "EXCLUDED_OUT_OF_SCOPE")
        self.assertEqual(excl_sess["unified_excluded_folder"], ".work/library/_excluded")
        self.assertEqual(excl_sess["total_excluded_projects"], 14)


if __name__ == "__main__":
    unittest.main()
