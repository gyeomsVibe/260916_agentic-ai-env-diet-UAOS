"""U108 (revised 2026-10-01): the map arrives with the read, instead of a second gate in front of it.

The first U108 design denied every read of an unmapped file over 300 lines. Rejected before shipping: each deny costs
one more paid call that re-sends the whole context (~140k tokens), ranged reads after a Grep are the cheap path, and
the local model's map of `ollama_worker.py` gave wrong line numbers (L1-40 for code at L93-339). What helps instead:
- `code_outline` gives exact line ranges from `ast` (Python) or headings (Markdown) in milliseconds, no GPU.
- `digest_file` puts that outline first, so local_read_map's line numbers are right even when the model's are not.
- The whole-read deny (>= DENY_WHOLE_READ_TOKENS, unchanged) carries the outline, so the refused tool can open the
  right lines in its very next call.
- Claude's Bash gets the same shell gate Codex has (`olla hook-shell`); before, `cat big.py` in Claude passed.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_u37_install_everywhere import _home, _run
from v7_harness import olla

BIG_PY = "".join(f"# filler {i}\n" for i in range(40)) + "".join(
    f"\n\ndef func_{n}(x):\n" + "".join(f"    x += {k}  # padding to make the file large enough\n" for k in range(60))
    + "    return x\n"
    for n in range(12)
) + "\n\nclass Holder:\n    def method_a(self):\n        return 1\n"


class OutlineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.py = self.root / "big.py"
        self.py.write_text(BIG_PY, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_python_outline_has_exact_line_ranges(self):
        outline = olla.code_outline(self.py)
        lines = BIG_PY.splitlines()
        start = lines.index("def func_3(x):") + 1
        self.assertIn(f"L{start}-{start + 61}: def func_3", outline)
        self.assertIn("class Holder", outline)
        self.assertIn("def Holder.method_a", outline)

    def test_markdown_outline_lists_headings_with_lines(self):
        md = self.root / "doc.md"
        md.write_text("# Title\n\ntext\n\n## Part two\nmore\n", encoding="utf-8")
        outline = olla.code_outline(md)
        self.assertIn("L1: # Title", outline)
        self.assertIn("L5: ## Part two", outline)

    def test_unparsable_or_other_files_give_empty_outline(self):
        bad = self.root / "bad.py"
        bad.write_text("def (:\n", encoding="utf-8")
        self.assertEqual("", olla.code_outline(bad))
        txt = self.root / "a.txt"
        txt.write_text("x\n", encoding="utf-8")
        self.assertEqual("", olla.code_outline(txt))

    def test_outline_is_capped(self):
        self.assertLessEqual(len(olla.code_outline(self.py).splitlines()), olla.OUTLINE_MAX_LINES)

    def test_digest_puts_the_exact_outline_first(self):
        with mock.patch.object(olla.worker, "_generate", return_value=("- L1-40: comments", {})):
            text, _usage = olla.digest_file(self.py, "", "m", 5)
        self.assertIn("def func_3", text)
        self.assertLess(text.index("def func_3"), text.index("- L1-40: comments"))

    def test_digest_cache_version_was_bumped(self):
        self.assertNotEqual("1", olla.DIGEST_PROMPT_VERSION)

    def test_whole_read_deny_carries_the_outline(self):
        event = {"tool_input": {"file_path": str(self.py)}}
        with mock.patch.object(olla, "read_hint", return_value="hint"), \
                mock.patch.object(olla, "DENY_WHOLE_READ_TOKENS", 10), \
                mock.patch.object(olla, "_stdin_text", return_value=json.dumps(event)), \
                mock.patch.object(olla, "log_usage"), \
                mock.patch("builtins.print") as printed:
            olla.cmd_hook_read(None)
        out = json.loads(printed.call_args[0][0])["hookSpecificOutput"]
        self.assertEqual("deny", out["permissionDecision"])
        self.assertIn("def func_3", out["permissionDecisionReason"])

    def test_shell_deny_carries_the_outline(self):
        with mock.patch.object(olla, "DENY_WHOLE_READ_TOKENS", 10), mock.patch.object(olla, "log_usage"):
            reason = json.loads(olla.shell_read_deny([self.py]))["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("def func_3", reason)

    def test_small_reads_still_pass(self):
        small = self.root / "s.py"
        small.write_text("x = 1\n", encoding="utf-8")
        self.assertIsNone(olla.shell_read_deny([small]))


class ClaudeBashGateInstallTests(unittest.TestCase):
    def _home(self, olla_path):
        with tempfile.TemporaryDirectory() as d:
            home = _home(Path(d))
            with mock.patch("v7_harness.global_install.shutil.which",
                            side_effect=lambda name, *a, **k: olla_path if name == "olla" else None):
                self.assertEqual(0, _run(home, "--apply")[0])
            return json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))

    def test_claude_bash_runs_the_shell_gate_when_olla_is_installed(self):
        groups = self._home("C:/bin/olla.exe")["hooks"]["PreToolUse"]
        bash = [g for g in groups if g.get("matcher") == "Bash"]
        commands = [h["command"] for g in bash for h in g["hooks"]]
        self.assertEqual(1, commands.count("olla hook-shell"), groups)
        self.assertTrue(any(g.get("matcher") == "Read" for g in groups))

    def test_no_olla_no_bash_gate(self):
        groups = (self._home(None).get("hooks") or {}).get("PreToolUse") or []
        self.assertFalse(any("olla hook-shell" in h.get("command", "") for g in groups for h in g.get("hooks", [])))


if __name__ == "__main__":
    unittest.main()
