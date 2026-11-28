```contract
work_id: U134-F1d
worker: apply
goal: Exclude only .claude/worktrees from deterministic manifests and staging while preserving other .claude paths
inputs:
- v7_harness/isolation/manifest.py sha256=be2dfc710283a6677731754dfb676778778b25bc7d2a6e8a53b8e334810f488d
- tests/test_b58_relay_manifest.py sha256=82c73308a8b0f58638b6b3f5c0774e8cc7372ef19b15b9380149afd4dc6be3f6
allow:
- v7_harness/isolation/manifest.py
- tests/test_b58_relay_manifest.py
acceptance: python -m unittest tests.test_b58_relay_manifest tests.test_u15_stream_isolation tests.test_b24_rejected_summary tests.test_b26_b21_features tests.test_b55_inproject_work tests.test_r2_minimal_control tests.test_u32_sentinel_bell tests.test_u35_posix_hygiene tests.test_u48_default_workdir tests.test_u96s_source_escape
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 900
remote_budget_tokens: 0
```

## Work Order: U134-F1d Root-Cause Card

Receipt: Codex relay_860b9c23fa744dc5265d31fbcce308ca.
Order: Codex relay_860b9c23.

===EDIT: v7_harness/isolation/manifest.py===
<<<<<<< SEARCH
    ".coord/coord.sqlite3-journal",
    ".coord/coord.sqlite3.writer.lock",
    ".coord/stage",
}
=======
    ".coord/coord.sqlite3-journal",
    ".coord/coord.sqlite3.writer.lock",
    ".coord/stage",
    ".claude/worktrees",
}
>>>>>>> REPLACE

===EDIT: tests/test_b58_relay_manifest.py===
<<<<<<< SEARCH
    def test_claude_tree_is_not_broadly_excluded(self) -> None:
        self.assertNotIn(".claude", DEFAULT_EXCLUDES)


if __name__ == "__main__":
    unittest.main()
=======
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
>>>>>>> REPLACE
