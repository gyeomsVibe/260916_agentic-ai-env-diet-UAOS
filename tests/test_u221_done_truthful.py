"""U221: a finished card ends with a 3-line Korean completion report that is earned from remote and runtime evidence.

Receipt (2026-10-19, user): U220 closed with an evidence report a user could not read as "finished". The user ordered
one common 3-line closing. Codex counterexamples (REVISE, .coord/results/U221-U222-integration-desk4-261022.md): local
ancestry of a sha is not a merge, and a hand-written runtime label is not an install. Contract v2 (Antigravity PASS,
relay_f15037a8 and relay_6fa2e094): DONE needs the PR to be MERGED on the remote (state, url, head) and, when named,
a runtime that `runtime_install.verify` re-hashes. Antigravity condition: the head guard compares headRefOid and falls
back to mergeCommit.oid so squash and rebase merges do not false-fail. Fixed acceptance written by the author
(claude) before the implementation; readers are injected so no test needs the network.
"""

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from v7_harness import card_pipeline, cli, firewall_audit, runtime_install
from v7_harness.card_pipeline import check_done, done_report
from v7_harness.coord import merge_route

ROOT = Path(__file__).resolve().parents[1]
SHA = "97d3af83a0b7615aaa95ccb879a9a5c088f1a1c7"
MERGE_SHA = "1" * 40
URL = "https://github.com/gyeomsVibe/260916_agentic-ai-env-diet-UAOS/pull/187"
SEPARATORS = ("\n", "\r", "\v", "\f", "\x85", " ", " ")


def _view(**over):
    return {"state": "MERGED", "url": URL, "headRefOid": SHA, **over}


def _reader(view):
    return lambda pr, project: view


def _copy_repo(dst: Path) -> Path:
    from tests.test_u48_r1_runtime_install import _copy_repo as copy

    return copy(dst)


class Report(unittest.TestCase):
    def test_three_lines_in_the_report_shape(self):
        lines = done_report("UAOS", "U220", "Codex가 막히면 쉬는 도구가 대신 일을 맡습니다", URL, SHA,
                            "0.3.0-eb7141da0e28").splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("**결과**: "))
        for needle in ("UAOS", "U220", "완료", "Codex가 막히면 쉬는 도구가 대신 일을 맡습니다"):
            self.assertIn(needle, lines[0])
        self.assertTrue(lines[1].startswith("- 근거: "))
        self.assertIn(URL, lines[1])
        self.assertIn(SHA[:7], lines[1])
        self.assertNotIn(SHA, lines[1])
        self.assertIn("0.3.0-eb7141da0e28", lines[1])
        self.assertTrue(lines[2].startswith("- 다음: "))

    def test_no_runtime_says_none_was_needed(self):
        second = done_report("UAOS", "U220", "정책 문서가 갱신됐습니다", URL, SHA).splitlines()[1]
        self.assertIn("런타임 설치가 필요 없는", second)

    def test_a_human_action_becomes_the_remaining_work_line(self):
        last = done_report("UAOS", "U220", "기능이 켜졌습니다", URL, SHA, user_action="새 세션을 여세요").splitlines()[2]
        self.assertEqual(last, "- **남은 일**: 새 세션을 여세요")

    def test_bad_fields_refuse(self):
        too_long = "가" * (card_pipeline.DONE_FIELD_MAX + 1)
        for kwargs in ({"project": ""}, {"what": " "}, {"card": "x"}, {"head": "zz"}, {"head": SHA.upper()},
                       {"head": SHA[:39]}, {"pr_url": "https://example.com/x/pull/1"}, {"what": too_long},
                       {"runtime": ""}):
            args = {"project": "UAOS", "card": "U220", "what": "끝", "pr_url": URL, "head": SHA, **kwargs}
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                done_report(**args)

    def test_single_line_enforced_for_every_separator(self):
        for sep in SEPARATORS:
            for field in ("project", "what", "runtime", "user_action"):
                args = {"project": "UAOS", "card": "U220", "what": "끝", "pr_url": URL, "head": SHA,
                        "runtime": "0.3.0-abc", "user_action": "새 세션", field: f"a{sep}b"}
                with self.subTest(sep=repr(sep), field=field), self.assertRaises(ValueError):
                    done_report(**args)


class Remote(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _check(self, reader, pr_url=URL, head=SHA):
        return check_done(self.repo, pr_url, head, pr_reader=reader)

    def test_no_remote_is_not_done(self):
        subprocess.run(["git", "-C", str(self.repo), "init", "-q"], check=True, capture_output=True)
        problems = check_done(self.repo, URL, SHA)
        self.assertTrue(problems and problems[0].startswith("REMOTE"), problems)
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.main(["card", "done", "--project", str(self.repo), "--name", "UAOS", "--card", "U221",
                             "--what", "끝", "--pr-url", URL, "--head", SHA])
        self.assertEqual(code, 1)
        self.assertNotIn("DONE", out.getvalue().replace("NOT_DONE", ""))

    def test_gh_failure_timeout_missing_gh_all_fail_closed(self):
        def run_with(runner):
            return check_done(self.repo, URL, SHA, pr_reader=lambda pr, project: merge_route.pr_view(pr, project, runner))

        def fail(argv, **kw):
            return subprocess.CompletedProcess(argv, 1, b"", b"boom")

        def timeout(argv, **kw):
            raise subprocess.TimeoutExpired(argv, 60)

        def missing(argv, **kw):
            raise FileNotFoundError("gh")

        def text(argv, **kw):
            return subprocess.CompletedProcess(argv, 0, b"not json", b"")

        def listing(argv, **kw):
            return subprocess.CompletedProcess(argv, 0, b"[]", b"")

        for runner in (fail, timeout, missing, text, listing):
            problems = run_with(runner)
            with self.subTest(runner=runner.__name__):
                self.assertTrue(problems and problems[0].startswith("REMOTE"), problems)

    def test_pr_open_or_closed_is_not_done(self):
        for state in ("OPEN", "CLOSED", ""):
            self.assertTrue(self._check(_reader(_view(state=state))), state)
        missing = _view()
        del missing["state"]
        self.assertTrue(self._check(_reader(missing)))

    def test_head_sha_mismatch_is_not_done(self):
        self.assertTrue(self._check(_reader(_view(headRefOid="2" * 40))))
        for bad in (SHA.upper(), SHA[:39]):
            problems = self._check(_reader(_view()), head=bad)
            self.assertTrue(problems and "head" in problems[0].lower(), problems)

    def test_squash_merge_accepts_the_merge_commit_as_head(self):
        view = _view(headRefOid=SHA, mergeCommit={"oid": MERGE_SHA})
        self.assertEqual(self._check(_reader(view), head=MERGE_SHA), [])
        self.assertEqual(self._check(_reader(view), head=SHA), [])
        self.assertTrue(self._check(_reader(view), head="3" * 40))

    def test_rebase_merge_accepts_the_merge_commit_as_head(self):
        view = _view(headRefOid="a" * 40, mergeCommit={"oid": "b" * 40})
        self.assertEqual(self._check(_reader(view), head="b" * 40), [])
        self.assertEqual(self._check(_reader(view), head="a" * 40), [])
        self.assertTrue(self._check(_reader(_view(headRefOid="a" * 40, mergeCommit=None)), head="b" * 40))

    def test_url_mismatch_or_not_github_pr_is_not_done(self):
        other = URL.replace("187", "188")
        self.assertTrue(self._check(_reader(_view(url=other))))
        for bad in ("https://example.com/x/pull/1", "file:///x/pull/1", URL + "?x=1", URL + " extra", URL + "\n"):
            with self.subTest(url=bad):
                self.assertTrue(self._check(_reader(_view(url=bad)), pr_url=bad))

    def test_check_done_validates_its_own_inputs(self):
        problems = check_done(self.repo, None, "zz", runtime="a\nb", pr_reader=_reader(_view()))
        self.assertGreaterEqual(len(problems), 3, problems)

    def test_local_ancestry_alone_is_not_done(self):
        repo = self.repo
        git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
        git("init", "-q")
        git("config", "user.email", "t@example.invalid")
        git("config", "user.name", "t")
        (repo / "a.txt").write_text("a", encoding="utf-8")
        git("add", "a.txt")
        git("commit", "-q", "-m", "a")
        sha = git("rev-parse", "HEAD").stdout.strip()
        git("update-ref", "refs/remotes/origin/main", sha)
        self.assertTrue(self._check(_reader(_view(state="OPEN", headRefOid=sha)), head=sha))


class Runtime(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _check(self, version):
        return check_done(self.root, URL, SHA, runtime=version, uaos_home=self.home, pr_reader=_reader(_view()))

    def test_fabricated_runtime_label_is_not_done(self):
        base = runtime_install.runtime_dir(self.home)
        base.mkdir(parents=True)
        (base / "current.json").write_text(json.dumps({"version": "0.3.0-abc"}), encoding="utf-8")
        problems = self._check("0.3.0-abc")
        self.assertTrue(problems and problems[0].startswith("RUNTIME"), problems)

    def test_tampered_installed_runtime_is_not_done(self):
        repo = _copy_repo(self.root / "repo")
        version = runtime_install.install(self.home, repo)["version"]
        self.assertEqual(self._check(version), [])
        target = runtime_install.runtime_dir(self.home) / version / "v7_harness" / "cli.py"
        target.write_bytes(target.read_bytes() + b"\n# tampered\n")
        self.assertTrue(self._check(version)[0].startswith("RUNTIME"))

    def test_other_current_version_is_not_done(self):
        repo = _copy_repo(self.root / "repo")
        version = runtime_install.install(self.home, repo)["version"]
        current = runtime_install.runtime_dir(self.home) / "current.json"
        current.write_text(json.dumps({"version": "9.9.9-other"}), encoding="utf-8")
        with mock.patch.object(runtime_install, "verify", return_value={}):
            self.assertTrue(self._check(version)[0].startswith("RUNTIME"))

    def test_remote_ok_and_runtime_ok_is_done(self):
        repo = _copy_repo(self.root / "repo")
        version = runtime_install.install(self.home, repo)["version"]
        self.assertEqual(self._check(version), [])
        report = done_report("UAOS", "U221", "끝난 이유를 3줄로 알려 줍니다", URL, SHA, version).splitlines()
        self.assertEqual(len(report), 3)
        self.assertIn(URL, report[1])
        self.assertIn(SHA[:7], report[1])


class Audit(unittest.TestCase):
    def test_check_done_adds_no_exec_site(self):
        sites = firewall_audit.audit(ROOT)
        self.assertEqual([s for s in sites if s.path == "v7_harness/card_pipeline.py"], [])


class Command(unittest.TestCase):
    def _run(self, *extra, view=None):
        out = io.StringIO()
        argv = ["card", "done", "--project", self.tmp.name, "--name", "UAOS", "--card", "U221",
                "--what", "끝난 이유를 3줄로 알려 줍니다", *extra]
        with mock.patch.object(merge_route, "pr_view", return_value=view or _view()), redirect_stdout(out):
            code = cli.main(argv)
        return code, json.loads(out.getvalue())

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_done_prints_the_report(self):
        code, body = self._run("--pr-url", URL, "--head", SHA)
        self.assertEqual((code, body["state"]), (0, "DONE"))
        self.assertEqual(len(body["lines"]), 3)
        self.assertEqual(body["report"], "\n".join(body["lines"]))

    def test_not_done_prints_no_report(self):
        code, body = self._run("--pr-url", URL, "--head", SHA, view=_view(state="OPEN"))
        self.assertEqual((code, body["state"]), (1, "NOT_DONE"))
        self.assertNotIn("report", body)

    def test_bad_input_exits_2(self):
        for extra in (("--pr-url", URL, "--head", "nothex"), ("--pr-url", "https://x.test/pull/1", "--head", SHA)):
            code, body = self._run(*extra)
            self.assertEqual(code, 2)
            self.assertFalse(body["ok"])

    def test_merged_flag_is_gone(self):
        with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()), mock.patch.object(sys, "stderr", io.StringIO()):
            cli.main(["card", "done", "--name", "UAOS", "--card", "U221", "--what", "끝", "--merged", SHA])


class Rule(unittest.TestCase):
    def test_global_rule_block_names_the_closing(self):
        text = (ROOT / "uaos_everywhere" / "uaos_global_rule_block.md").read_text(encoding="utf-8")
        line = next(item for item in text.splitlines() if "U221" in item)
        for needle in ("uaos card done", "3줄", "완료", "PR url + head"):
            self.assertIn(needle, line)


if __name__ == "__main__":
    unittest.main()
