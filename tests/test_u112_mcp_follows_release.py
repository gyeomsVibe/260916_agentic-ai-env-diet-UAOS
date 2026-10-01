"""U112: the olla MCP server of all three tools loads the release the installer keeps current, not a pinned runtime.

Receipt (2026-10-01, after PR #82 merged): Claude's `~/.claude.json`, Codex's `~/.codex/config.toml` and Antigravity's
`~/.gemini/antigravity/mcp_config.json` all ran `olla_mcp` from `runtime/0.3.2-ad721a2fc713`, pinned by hand on 09-27
(U48-M1). Since then the runtime moved ~38 times; the MCP tools (local_read_map, ...) served code without U108's
outline while the hooks had it. The installer now points each existing olla MCP entry at the olla release (U111),
so one copy serves hooks and MCP for all three tools. It never creates an entry, and a test --home is never touched.
Fixed acceptance written by the judge (claude) first.
"""

import json
import tempfile
import unittest
from pathlib import Path

from tests.test_u37_install_everywhere import PYTHON, _home
from tests.test_u111_olla_release_sync import _release, _repo
from v7_harness import global_install as gi

OLD = "C:\\Users\\me\\.uaos\\runtime\\0.3.2-ad721a2fc713"


def _mcp(home: Path) -> None:
    olla = {"type": "stdio", "command": "C:\\Python314\\python.exe", "args": ["-m", "v7_harness.olla_mcp"],
            "env": {"PYTHONIOENCODING": "utf-8", "PYTHONPATH": OLD}}
    other = {"command": "other-mcp", "args": [], "env": {"PYTHONPATH": "C:\\keep\\me"}}
    (home / ".claude.json").write_text(json.dumps({"numStartups": 9, "mcpServers": {"other": other, "olla": olla}},
                                                  indent=2), encoding="utf-8")
    (home / ".gemini" / "antigravity").mkdir(parents=True)
    (home / ".gemini" / "antigravity" / "mcp_config.json").write_text(json.dumps({"mcpServers": {"olla": olla}}),
                                                                       encoding="utf-8")
    toml = (home / ".codex" / "config.toml").read_text(encoding="utf-8")
    (home / ".codex" / "config.toml").write_text(
        toml + "\n[mcp_servers.other.env]\nPYTHONPATH = 'C:\\keep\\me'\n\n[mcp_servers.olla]\n"
        "command = 'C:\\Python314\\python.exe'\nargs = [\"-m\", \"v7_harness.olla_mcp\"]\n\n"
        f"[mcp_servers.olla.env]\nPYTHONIOENCODING = \"utf-8\"\nPYTHONPATH = '{OLD}'\n", encoding="utf-8")


def _files(home: Path) -> dict[str, Path]:
    return {"claude mcp": home / ".claude.json", "codex": home / ".codex" / "config.toml",
            "antigravity mcp": home / ".gemini" / "antigravity" / "mcp_config.json"}


class McpFollowsReleaseTests(unittest.TestCase):
    def test_all_three_entries_point_at_the_release_and_nothing_else_moves(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            home, repo, release = _home(root), _repo(root), _release(root)
            _mcp(home)
            changes = gi.plan(home, PYTHON, repo=repo, olla_release=release)
            gi.apply(changes, home, backup_root=root / "backups")
            want = release.as_posix()
            claude = json.loads(_files(home)["claude mcp"].read_text(encoding="utf-8"))
            self.assertEqual(want, claude["mcpServers"]["olla"]["env"]["PYTHONPATH"])
            self.assertEqual("C:\\keep\\me", claude["mcpServers"]["other"]["env"]["PYTHONPATH"])
            self.assertEqual(9, claude["numStartups"])
            agy = json.loads(_files(home)["antigravity mcp"].read_text(encoding="utf-8"))
            self.assertEqual(want, agy["mcpServers"]["olla"]["env"]["PYTHONPATH"])
            toml = _files(home)["codex"].read_text(encoding="utf-8")
            self.assertIn(f"PYTHONPATH = '{want}'", toml)
            self.assertIn("PYTHONPATH = 'C:\\keep\\me'", toml)
            self.assertNotIn(OLD, toml)
            # The same config.toml also got the hooks feature line: both edits survive in one file.
            self.assertRegex(toml, r"(?m)^hooks = true$")
            again = [c for c in gi.plan(home, PYTHON, repo=repo, olla_release=release)
                     if c.action not in ("UNCHANGED", "SKIP")]
            self.assertEqual([], again)

    def test_a_tool_without_an_olla_mcp_entry_is_left_alone(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            home, repo, release = _home(root), _repo(root), _release(root)
            (home / ".claude.json").write_text('{"mcpServers": {}}', encoding="utf-8")
            changes = gi.plan(home, PYTHON, repo=repo, olla_release=release)
            self.assertFalse([c for c in changes if "mcp" in c.target])
            self.assertFalse((home / ".gemini" / "antigravity" / "mcp_config.json").exists())

    def test_uninstall_and_no_release_leave_mcp_alone(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            home, repo, release = _home(root), _repo(root), _release(root)
            _mcp(home)
            for kwargs in ({"olla_release": release, "uninstall": True}, {"olla_release": None}):
                changes = gi.plan(home, PYTHON, repo=repo, **kwargs)
                self.assertFalse([c for c in changes if "mcp" in c.target], kwargs)
                self.assertFalse([c for c in changes if c.new_text and "olla-release" in c.new_text], kwargs)


if __name__ == "__main__":
    unittest.main()
