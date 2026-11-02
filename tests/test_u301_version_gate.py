"""U301: version-up gate — the bump each change class requires, refusals, and the LIVE status check."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from v7_harness import version_gate as vg

REPO = Path(__file__).resolve().parents[1]


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


class ClassifyTests(unittest.TestCase):
    def test_classes(self):
        self.assertEqual(vg.classify(["docs/x.md", "tests/test_a.py", ".coord/PLAN.md"]), "none")
        self.assertEqual(vg.classify(["v7_harness/cli.py"]), "patch")
        self.assertEqual(vg.classify(["v7_harness/cli.py", "CLAUDE.md"]), "minor")
        self.assertEqual(vg.classify([vg.RULE_BLOCK]), "minor")
        self.assertEqual(vg.classify(["docs/x.md"], ["feat: x\n\nBREAKING: removes coord stall"]), "major")
        self.assertEqual(vg.classify(["docs/x.md"], ["feat: y\n\nBREAKING CHANGE: drops --target"]), "major")
        self.assertEqual(vg.classify(["docs/x.md"], ["docs: mention BREAKING: in prose"]), "none")
        # The VERSION file itself never raises the class it gates.
        self.assertEqual(vg.classify([vg.VERSION_FILE]), "none")

    def test_bump(self):
        self.assertEqual(vg.bump("0.3.0", "patch"), "0.3.1")
        self.assertEqual(vg.bump("0.3.4", "minor"), "0.4.0")
        self.assertEqual(vg.bump("0.3.4", "major"), "1.0.0")
        self.assertEqual(vg.bump("0.3.4", "none"), "0.3.4")
        with self.assertRaises(ValueError):
            vg.bump("7.6", "patch")


class EvaluateTests(unittest.TestCase):
    def test_exact_bump_passes(self):
        r = vg.evaluate("0.3.0", "0.4.0", "minor", "0.4.0")
        self.assertTrue(r["ok"], r)

    def test_missing_skipped_and_mismatch(self):
        self.assertEqual(vg.evaluate("0.3.0", "0.3.0", "patch", "0.3.0")["codes"], ["VERSION_BUMP_MISSING"])
        # U300 counterexample: jumping the runtime VERSION 0.3.0 -> 7.6.3 for a minor change.
        self.assertEqual(vg.evaluate("0.3.0", "7.6.3", "minor", "7.6.3")["codes"], ["VERSION_SKIPPED"])
        self.assertEqual(vg.evaluate("0.3.0", "0.3.1", "patch", None)["codes"], ["RULE_BLOCK_VERSION_MISMATCH"])
        # Docs-only change must not bump.
        self.assertEqual(vg.evaluate("0.3.0", "0.3.1", "none", "0.3.1")["codes"], ["VERSION_SKIPPED"])


class CheckOnGitTests(unittest.TestCase):
    def _repo(self, tmp):
        repo = Path(tmp)
        git(repo, "init", "-q", "-b", "main")
        git(repo, "config", "user.email", "t@t")
        git(repo, "config", "user.name", "t")
        (repo / "uaos_everywhere").mkdir()
        (repo / "v7_harness").mkdir()
        (repo / vg.VERSION_FILE).write_text("0.3.0\n", encoding="utf-8")
        (repo / vg.RULE_BLOCK).write_text("## rules\n<!-- uaos-version: 0.3.0 -->\n- a\n", encoding="utf-8")
        (repo / "v7_harness" / "m.py").write_text("x = 1\n", encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "commit", "-q", "-m", "base")
        git(repo, "checkout", "-q", "-b", "card")
        return repo

    def test_code_change_needs_patch_bump(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            (repo / "v7_harness" / "m.py").write_text("x = 2\n", encoding="utf-8")
            git(repo, "commit", "-qam", "fix")
            r = vg.check(repo, base="main", head="HEAD")
            self.assertEqual(r["codes"], ["VERSION_BUMP_MISSING"])
            # Working-tree mode (card audit runs before the commit): an uncommitted bump already counts.
            (repo / vg.VERSION_FILE).write_text("0.3.1\n", encoding="utf-8")
            (repo / vg.RULE_BLOCK).write_text("## rules\n<!-- uaos-version: 0.3.1 -->\n- a\n", encoding="utf-8")
            self.assertTrue(vg.check(repo, base="main")["ok"])
            self.assertEqual(vg.check(repo, base="main", head="HEAD")["codes"], ["VERSION_BUMP_MISSING"])
            self.assertEqual(r["required_version"], "0.3.1")
            (repo / vg.VERSION_FILE).write_text("0.3.1\n", encoding="utf-8")
            (repo / vg.RULE_BLOCK).write_text("## rules\n<!-- uaos-version: 0.3.1 -->\n- a\n", encoding="utf-8")
            git(repo, "commit", "-qam", "bump")
            self.assertTrue(vg.check(repo, base="main")["ok"])
            self.assertEqual(vg.main(["check", "--repo", str(repo), "--base", "main"]), 0)

    def test_status_live_only_when_installed_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            home = Path(tmp) / "home"
            (home / ".uaos" / "runtime").mkdir(parents=True)
            cur = home / ".uaos" / "runtime" / "current.json"
            cur.write_text(json.dumps({"version": "0.2.9-abcdef123456"}), encoding="utf-8")
            self.assertEqual(vg.status(repo, home)["codes"], ["RUNTIME_VERSION_DRIFT"])
            cur.write_text(json.dumps({"version": "0.3.0-abcdef123456"}), encoding="utf-8")
            r = vg.status(repo, home)
            self.assertEqual((r["state"], r["codes"]), ("LIVE", []))


class RepoInvariantTests(unittest.TestCase):
    def test_repo_rule_block_declares_repo_version(self):
        version = (REPO / vg.VERSION_FILE).read_text(encoding="utf-8").strip()
        header = vg.rule_block_version((REPO / vg.RULE_BLOCK).read_text(encoding="utf-8"))
        self.assertEqual(header, version)


if __name__ == "__main__":
    unittest.main()
