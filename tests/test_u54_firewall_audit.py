"""U54: the firewall gap audit classifies sites by its fixed rule, misses nothing grep sees, and is deterministic."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from v7_harness.firewall_audit import DOC_PATH, audit, audit_file, main, render

ROOT = Path(__file__).resolve().parents[1]
# Second signal: a call spelled out in the source. Type hints (`subprocess.Popen[str]`) and defaults
# (`runner=subprocess.run`) have no "(" after the name, so they are not execution sites.
GREP = re.compile(r"(subprocess\.(run|Popen|call|check_call|check_output)|os\.system|os\.(exec|spawn)\w*)\(")


class TestFixture(unittest.TestCase):
    def test_three_sites_are_guarded_gap_fixed(self):
        fixture = ROOT / "tests" / "fixtures" / "u54_sample.py"
        sites = [s for s in audit_file(fixture, ROOT) if s.kind != "READ"]
        by_line = {s.line: s for s in sites}
        text = fixture.read_text(encoding="utf-8").splitlines()
        line_of = {name: next(i for i, t in enumerate(text, 1) if f"def {name}(" in t) for name in
                   ("guarded", "unguarded", "constant")}
        status = {name: [s.status for ln, s in by_line.items() if ln > line_of[name] and
                         ln < min([v for v in line_of.values() if v > line_of[name]] or [10 ** 6])]
                  for name in line_of}
        self.assertEqual({"guarded": ["GUARDED"], "unguarded": ["GAP"], "constant": ["FIXED"]}, status)
        gap = next(s for s in sites if s.status == "GAP")
        self.assertTrue(gap.shell)
        self.assertEqual("MODEL", gap.source)

    def test_indirect_runner_and_alias_are_sites(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pkg = root / "v7_harness"
            pkg.mkdir()
            (pkg / "m.py").write_text(
                "import subprocess as sp\nfrom os import system\n\n"
                "def a(cmd, runner=sp.run):\n    return runner(cmd)\n\n"
                "def b(proposal, runner=None):\n    execute = runner or sp.run\n    return execute(proposal)\n\n"
                "def c():\n    system('echo hi')\n", encoding="utf-8")
            sites = {s.line: s for s in audit(root)}
        self.assertEqual(("INDIRECT", "CALLER_INPUT"), (sites[5].kind, sites[5].status))
        self.assertEqual(("INDIRECT", "GAP"), (sites[9].kind, sites[9].status))
        self.assertEqual(("DIRECT", "FIXED", True), (sites[12].kind, sites[12].status, sites[12].shell))


class TestReads(unittest.TestCase):
    def test_reads_without_a_site_pass_through_and_writes_are_not_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "v7_harness").mkdir()
            (root / "v7_harness" / "m.py").write_text(
                "import subprocess\n\n"
                "def translate(msg, calls):\n    a = msg.get('tool_calls')\n    b = msg['tool_calls']\n"
                "    msg['tool_calls'] = calls\n    return a, b\n\n"
                "def run_it(resp):\n    call = resp['tool_calls'][0]\n    return subprocess.run(call)\n",
                encoding="utf-8")
            sites = {(s.line, s.kind): s.status for s in audit(root)}
        self.assertEqual({(4, "READ"): "PASS_THROUGH", (5, "READ"): "PASS_THROUGH",
                          (10, "READ"): "GAP", (11, "DIRECT"): "GAP"}, sites)


class TestRealTree(unittest.TestCase):
    def test_every_grep_hit_is_in_the_audit(self):
        found = {(s.path, s.line) for s in audit(ROOT)}
        missing = []
        for path in sorted((ROOT / "v7_harness").rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("#", 1)[0]
                if GREP.search(code) and (rel, number) not in found:
                    missing.append(f"{rel}:{number}")
        self.assertEqual([], missing)

    def test_output_is_deterministic_and_matches_the_committed_doc(self):
        first = render(audit(ROOT))
        second = render(audit(ROOT))
        self.assertEqual(first, second)
        # Compare the summary counts, not the whole doc: an edit above a call site shifts line numbers without
        # changing what can run, and a full-text check would fail every unrelated change. A new or reclassified
        # site changes a count and fails here until the doc is regenerated.
        committed = (ROOT / DOC_PATH).read_text(encoding="utf-8").replace("\r\n", "\n")

        def summary(text: str) -> list[str]:
            return [ln for ln in text.split("## 전체 목록")[0].splitlines() if ln.startswith("- ") and ":" in ln
                    and ln.split(":")[0][2:].strip() in ("전체 지점", "GAP", "CALLER_INPUT", "GUARDED", "FIXED",
                                                        "PASS_THROUGH")]

        self.assertEqual(summary(first), summary(committed),
                         "docs/50 is stale: run python -m v7_harness.firewall_audit --write")

    def test_write_flag_writes_the_doc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "v7_harness").mkdir()
            (root / "v7_harness" / "x.py").write_text("import os\nos.system('ls')\n", encoding="utf-8")
            import io
            from contextlib import redirect_stdout
            with redirect_stdout(io.StringIO()):
                self.assertEqual(0, main(["--root", str(root), "--write"]))
            text = (root / DOC_PATH).read_text(encoding="utf-8")
        self.assertIn("`v7_harness/x.py:2`", text)
        self.assertIn("- FIXED: 1", text)


if __name__ == "__main__":
    unittest.main()
