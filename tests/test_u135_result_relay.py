"""U135: every card ends by writing its result in its own checkout and sending one RESULT line to the user window.

Receipt (2026-10-03, 윤겸스): hopping between card windows to merge was hard, so the user window collects the cards'
RESULT lines and reports the merges together (interim rule RESULT_RELAY.md). U132 could not write
.coord/results/U132.md into the base checkout from its card worktree (the desktop app's worktree hook blocks writes
outside the worktree, a platform permission this card does not weaken), so a card writes `.coord/results/<card>.md`
in its own checkout and `uaos card results` collects every checkout's file.
Fixed acceptance written by the judge (claude) before the implementation.
"""

import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from v7_harness import card_pipeline
from v7_harness.card_pipeline import TEMPLATE, collect_results, result_line, write_result

PR = "https://github.com/o/r/pull/7"


def _worktree(main: Path, name: str, root: Path) -> Path:
    """Lay out what `git worktree add` leaves on disk: <main>/.git/worktrees/<name>/gitdir -> <wt>/.git, and a
    `.git` file in the worktree pointing back."""
    wt = root / name
    wt.mkdir(parents=True)
    meta = main / ".git" / "worktrees" / name
    meta.mkdir(parents=True)
    (meta / "gitdir").write_text(str(wt / ".git") + "\n", encoding="utf-8")
    (wt / ".git").write_text(f"gitdir: {meta}\n", encoding="utf-8")
    return wt


class TemplateTest(unittest.TestCase):
    def test_a_generated_manual_ends_with_the_result_relay_step(self):
        body = TEMPLATE.format(card="U135", title="t")
        last = body[body.rindex("\n## "):]
        self.assertIn("Result relay", last)
        self.assertIn("uaos card result --card U135", last)
        self.assertIn("RESULT", last)
        self.assertIn("user window", last)
        self.assertIn("uaos card results", last)

    def test_the_relay_step_keeps_the_four_stage_slots_valid(self):
        self.assertEqual([], card_pipeline.missing_slots(TEMPLATE.format(card="U135", title="t")))

    def test_card_new_writes_the_relay_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            made = card_pipeline.new_manual(Path(tmp), "U135", "t", now=1.0)
            self.assertIn("uaos card result --card U135", Path(made["manual"]).read_text(encoding="utf-8"))


class ResultLineTest(unittest.TestCase):
    def test_the_line_has_the_relay_shape(self):
        self.assertEqual(f"RESULT U135 | PR {PR} | MERGEABLE yes | tests 1590/0 | blocker none",
                         result_line("U135", PR, "yes", "1590/0", "none"))

    def test_bad_fields_are_refused(self):
        bad = [("../x", PR, "yes", "1/0", "none"), ("U135", PR, "maybe", "1/0", "none"),
               ("U135", PR, "yes", "many", "none"), ("U135", "", "yes", "1/0", "none"),
               ("U135", PR, "yes", "1/0", ""), ("U135", PR, "yes", "1/0", "a\nb"),
               ("U135", PR + " | MERGEABLE yes", "no", "1/0", "none")]
        for args in bad:
            with self.assertRaises(ValueError, msg=repr(args)):
                result_line(*args)


class WriteAndCollectTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.main = self.root / "main"
        (self.main / ".git").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_card_writes_its_result_in_its_own_checkout(self):
        wt = _worktree(self.main, "u135", self.root / "wts")
        made = write_result(wt, "U135", PR, "yes", "10/0", "none")
        path = wt / ".coord" / "results" / "U135.md"
        self.assertEqual(str(path), made["path"])
        self.assertIn(made["line"], path.read_text(encoding="utf-8"))
        self.assertFalse((self.main / ".coord" / "results").exists())  # the base checkout is never written

    def test_the_user_window_collects_every_checkout(self):
        a = _worktree(self.main, "u135", self.root / "wts")
        b = _worktree(self.main, "u136", self.root / "wts")
        write_result(a, "U135", PR, "yes", "10/0", "none")
        write_result(b, "U136", PR, "no", "10/1", "conflict in PLAN.md")
        write_result(self.main, "U130", PR, "yes", "5/0", "none")
        found = {row["card"]: row["line"] for row in collect_results(self.main)}
        self.assertEqual({"U130", "U135", "U136"}, set(found))
        self.assertTrue(found["U136"].endswith("blocker conflict in PLAN.md"))

    def test_collecting_from_inside_a_worktree_finds_the_others(self):
        a = _worktree(self.main, "u135", self.root / "wts")
        b = _worktree(self.main, "u136", self.root / "wts")
        write_result(b, "U136", PR, "yes", "1/0", "none")
        self.assertEqual(["U136"], [row["card"] for row in collect_results(a)])

    def test_the_newest_file_wins_when_a_card_wrote_twice(self):
        a = _worktree(self.main, "u135", self.root / "wts")
        write_result(self.main, "U135", PR, "no", "1/1", "tests")
        old = time.time() - 60
        os.utime(self.main / ".coord" / "results" / "U135.md", (old, old))
        write_result(a, "U135", PR, "yes", "1/0", "none")
        rows = collect_results(self.main)
        self.assertEqual(1, len(rows))
        self.assertIn("MERGEABLE yes", rows[0]["line"])

    def test_only_card_named_files_are_collected(self):
        # agy audit relay_6a94044c point 1: a file name that is not a card id is never reported as a card.
        write_result(self.main, "U135", PR, "yes", "1/0", "none")
        results = self.main / ".coord" / "results"
        (results / "Unotes.md").write_text(f"RESULT U9 | PR {PR} | MERGEABLE yes | tests 1/0 | blocker none\n",
                                           encoding="utf-8")
        self.assertEqual(["U135"], [row["card"] for row in collect_results(self.main)])

    def test_a_removed_worktree_is_skipped(self):
        gone = _worktree(self.main, "u140", self.root / "wts")
        (gone / ".git").unlink()
        gone.rmdir()
        self.assertEqual([], collect_results(self.main))


class CliTest(unittest.TestCase):
    def _run(self, argv):
        from v7_harness import cli
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            args = cli.build_parser().parse_args(argv)
            code = args.func(args)
        return code, json.loads(out.getvalue())

    def test_result_and_results_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            main = Path(tmp) / "main"
            (main / ".git").mkdir(parents=True)
            (main / ".coord").mkdir()
            (main / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
            wt = _worktree(main, "u135", Path(tmp) / "wts")
            code, made = self._run(["card", "result", "--project", str(wt), "--card", "U135", "--pr", PR,
                                    "--mergeable", "yes", "--tests", "3/0"])
            self.assertEqual(0, code)
            self.assertEqual(f"RESULT U135 | PR {PR} | MERGEABLE yes | tests 3/0 | blocker none", made["line"])
            self.assertTrue((wt / ".coord" / "results" / "U135.md").is_file())
            code, listed = self._run(["card", "results", "--project", str(main)])
            self.assertEqual(0, code)
            self.assertEqual([made["line"]], [row["line"] for row in listed["results"]])

    def test_a_bad_result_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, made = self._run(["card", "result", "--project", tmp, "--card", "U135", "--pr", PR,
                                    "--mergeable", "yes", "--tests", "lots"])
            self.assertEqual(2, code)
            self.assertFalse(made["ok"])


if __name__ == "__main__":
    unittest.main()
