"""U65: the three-tool rollout on 2026-09-28 stopped twice on stale assumptions.

1. `install_uaos_everywhere --check` reported "codex hooks feature" drift on a config that already had
   `[features] hooks = true`: Codex 0.157.1 lists the feature as `hooks` and no longer lists `codex_hooks`.
2. `deploy_to_this_pc` stopped with CANON_SOURCES_AMBIGUOUS:claude because canon v5.26.0 added
   `adapters/claude.md` next to the standalone `claude.md`.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from v7_harness import deploy_pc as dp
from v7_harness import global_install as gi


def _home(root: Path, toml: str) -> Path:
    home = root / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".codex").mkdir()
    (home / ".gemini" / "config").mkdir(parents=True)
    (home / ".codex" / "config.toml").write_text(toml, encoding="utf-8")
    return home


def _run(home: Path, *args: str) -> tuple[int, dict]:
    out = io.StringIO()
    with redirect_stdout(out):
        code = gi.main(["--home", str(home), "--python", sys.executable, "--no-rules", *args])
    return code, json.loads(out.getvalue())


def _feature(report: dict) -> str:
    return next(c["action"] for c in report["changes"] if c["target"] == "codex hooks feature")


class CodexHooksKeyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_current_and_legacy_names_both_count_as_enabled(self) -> None:
        for toml in ("[features]\nhooks = true\n", "[features]\ncodex_hooks = true\n"):
            with self.subTest(toml=toml):
                home = _home(self.root / str(abs(hash(toml))), toml)
                self.assertEqual("UNCHANGED", _feature(_run(home, "--check")[1]))
                self.assertEqual(toml, (home / ".codex" / "config.toml").read_text(encoding="utf-8"))

    def test_hand_disabled_current_name_is_left_alone(self) -> None:
        home = _home(self.root, "[features]\nhooks = false\n")
        self.assertEqual("SKIP", _feature(_run(home, "--apply")[1]))
        self.assertEqual("[features]\nhooks = false\n", (home / ".codex" / "config.toml").read_text(encoding="utf-8"))

    def test_new_install_writes_current_name_and_uninstall_removes_only_it(self) -> None:
        home = _home(self.root, 'model = "gpt"\n[features]\nweb = true\n')
        _run(home, "--apply")
        self.assertIn("[features]\nhooks = true\nweb = true", (home / ".codex" / "config.toml").read_text(encoding="utf-8"))
        self.assertEqual("UNCHANGED", _feature(_run(home, "--check")[1]))
        _run(home, "--apply", "--uninstall")
        self.assertEqual('model = "gpt"\n[features]\nweb = true\n',
                         (home / ".codex" / "config.toml").read_text(encoding="utf-8"))

    def test_uninstall_after_a_pre_rename_install_removes_codex_hooks(self) -> None:
        home = _home(self.root, "[features]\ncodex_hooks = true\nweb = true\n")
        (home / ".uaos").mkdir()
        (home / ".uaos" / gi.STATE_FILE).write_text(json.dumps({"codex_hooks_added": True}), encoding="utf-8")
        _run(home, "--apply", "--uninstall")
        self.assertEqual("[features]\nweb = true\n", (home / ".codex" / "config.toml").read_text(encoding="utf-8"))


class CanonAdapterTests(unittest.TestCase):
    def test_adapters_claude_md_does_not_make_the_claude_source_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "shared" / "global-rules"
            (src / "adapters").mkdir(parents=True)
            for rel in ("claude.md", "core.md", "adapters/claude.md", "adapters/codex.md", "adapters/antigravity.md"):
                (src / rel).write_text("# rules\n", encoding="utf-8")
            found, problems = dp.find_canon_sources(Path(d))
        self.assertEqual([], problems)
        self.assertEqual({"claude": Path("claude.md"), "codex": Path("core.md"), "antigravity": Path("core.md")},
                         {k: v.relative_to(src) for k, v in found.items()})


if __name__ == "__main__":
    unittest.main()
