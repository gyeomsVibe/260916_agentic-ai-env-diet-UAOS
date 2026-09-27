"""U17: olla — 파일럿 밖에서 로컬 모델을 부려 쓰는 공용 명령.

파일럿의 게이트가 없으므로, 명령 자체가 지켜야 하는 것을 시험한다.
- 편집 전 백업, 적용 전 diff
- 모델 출력이 형식을 벗어나면 원본 무변경
- 현재 프로젝트 밖 파일은 거부
- dry-run 은 아무것도 바꾸지 않음
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from v7_harness import olla

# 사용 기록은 실제 사용자 파일(~/.cache/olla/usage.jsonl)을 오염시키면 안 된다(한 번 21줄 섞였다).
_USAGE_TMP = tempfile.TemporaryDirectory()
_USAGE_PATCH = mock.patch.object(olla, "USAGE_LOG", Path(_USAGE_TMP.name) / "usage.jsonl")


_CACHE_PATCH = mock.patch.object(olla, "DIGEST_CACHE_DIR", Path(_USAGE_TMP.name) / "digest")
# 읽기 훅은 서버가 살아 있으면 실제 요약 작업을 뒤에서 띄운다. 시험 중에는 꺼진 것으로 둔다.
_SERVER_PATCH = mock.patch.object(olla, "_server_up", return_value=False)


def setUpModule() -> None:
    _USAGE_PATCH.start()
    _CACHE_PATCH.start()
    _SERVER_PATCH.start()


def tearDownModule() -> None:
    _SERVER_PATCH.stop()
    _CACHE_PATCH.stop()
    _USAGE_PATCH.stop()
    _USAGE_TMP.cleanup()


class OllaEditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "proj"
        self.root.mkdir()
        (self.root / "config.py").write_text("TIMEOUT_S = 30\nRETRIES = 3\n", encoding="utf-8")
        self.cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self) -> None:
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def _edit(self, reply: str, *extra: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(olla.worker, "_generate", return_value=(reply, {"input_tokens": 5, "output_tokens": 5})):
            with redirect_stdout(out), redirect_stderr(err):
                code = olla.main(["edit", "set TIMEOUT_S to 90", "-f", "config.py", *extra])
        return code, out.getvalue(), err.getvalue()

    def test_edit_applies_backs_up_and_prints_a_diff(self) -> None:
        code, out, err = self._edit("===FILE: config.py===\nTIMEOUT_S = 90\nRETRIES = 3")
        self.assertEqual(0, code)
        self.assertIn("-TIMEOUT_S = 30", out)
        self.assertIn("+TIMEOUT_S = 90", out)
        self.assertEqual("TIMEOUT_S = 90\nRETRIES = 3\n", (self.root / "config.py").read_text(encoding="utf-8"))
        backups = list((self.root / ".work").glob("backup_olla_*/config.py"))
        self.assertEqual(1, len(backups))
        self.assertEqual("TIMEOUT_S = 30\nRETRIES = 3\n", backups[0].read_text(encoding="utf-8"))

    def test_dry_run_changes_nothing(self) -> None:
        code, out, _ = self._edit("===FILE: config.py===\nTIMEOUT_S = 90\nRETRIES = 3", "--dry-run")
        self.assertEqual(0, code)
        self.assertIn("+TIMEOUT_S = 90", out)
        self.assertEqual("TIMEOUT_S = 30\nRETRIES = 3\n", (self.root / "config.py").read_text(encoding="utf-8"))
        self.assertEqual([], list((self.root / ".work").glob("backup_olla_*")))

    def test_chatty_output_leaves_the_file_untouched(self) -> None:
        code, _, err = self._edit("Sure! I set it to 90.")
        self.assertEqual(3, code)
        self.assertIn("changed nothing", err)
        self.assertEqual("TIMEOUT_S = 30\nRETRIES = 3\n", (self.root / "config.py").read_text(encoding="utf-8"))

    def test_bad_search_block_leaves_the_file_untouched(self) -> None:
        code, _, err = self._edit("===EDIT: config.py===\n<<<<<<< SEARCH\nNOPE\n=======\nX\n>>>>>>> REPLACE")
        self.assertEqual(3, code)
        self.assertIn("rejected", err)
        self.assertEqual("TIMEOUT_S = 30\nRETRIES = 3\n", (self.root / "config.py").read_text(encoding="utf-8"))

    def test_files_outside_the_project_are_refused(self) -> None:
        outside = Path(self.tmp.name) / "other.py"
        outside.write_text("x = 1\n", encoding="utf-8")
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            code = olla.main(["edit", "change x", "-f", str(outside)])
        self.assertEqual(2, code)
        self.assertIn("outside", err.getvalue())
        self.assertEqual("x = 1\n", outside.read_text(encoding="utf-8"))

    def test_no_scratch_directory_is_left_behind(self) -> None:
        self._edit("===FILE: config.py===\nTIMEOUT_S = 90\nRETRIES = 3")
        self.assertEqual([], list((self.root / ".work").glob("olla_scratch_*")))


class OllaAskAndStatusTests(unittest.TestCase):
    def test_ask_prints_the_answer(self) -> None:
        out = io.StringIO()
        with mock.patch.object(olla.worker, "_generate", return_value=("요약입니다", {"input_tokens": 3, "output_tokens": 2})):
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                code = olla.main(["ask", "한 줄로 요약해"])
        self.assertEqual(0, code)
        self.assertEqual("요약입니다", out.getvalue().strip())

    def _ask_ko(self, replies: list[str]) -> tuple[int, str, str, list[str]]:
        prompts: list[str] = []

        def fake(model, prompt, timeout):
            prompts.append(prompt)
            return replies[len(prompts) - 1], {"input_tokens": 1, "output_tokens": 1}

        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(olla.worker, "_generate", side_effect=fake):
            with redirect_stdout(out), redirect_stderr(err):
                code = olla.main(["ask", "커밋 제목 한 줄", "--ko"])
        return code, out.getvalue().strip(), err.getvalue(), prompts

    def test_ko_wraps_the_request_in_korean_rules(self) -> None:
        code, out, _, prompts = self._ask_ko(["feat(olla): 캐시 추가"])
        self.assertEqual((0, "feat(olla): 캐시 추가"), (code, out))
        self.assertTrue(prompts[0].startswith(olla.KO_RULES))
        self.assertEqual(1, len(prompts))

    def test_ko_retries_once_when_the_answer_is_english(self) -> None:
        code, out, err, prompts = self._ask_ko(["feat(olla): add cache", "feat(olla): 캐시 추가"])
        self.assertEqual((0, "feat(olla): 캐시 추가"), (code, out))
        self.assertEqual(2, len(prompts))
        self.assertIn('"attempts": 2', err)

    def test_ko_gives_up_with_code_4_so_the_caller_writes_it(self) -> None:
        code, _, err, _ = self._ask_ko(["add cache", "still english"])
        self.assertEqual(4, code)
        self.assertIn("write it yourself", err)

    def test_invented_references_fail_with_code_5(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "tests" / "test_real.py").write_text("", encoding="utf-8")
            (root / "notes.md").write_text("x", encoding="utf-8")
            self.assertEqual([], olla.missing_refs("run tests.test_real and see `notes.md`", root))
            self.assertEqual(["missing.py", "tests.test_fake"],
                             olla.missing_refs("run tests.test_fake, open `missing.py`, `~/.codex/hooks.json`", root))
            cwd = os.getcwd()
            os.chdir(root)
            try:
                err = io.StringIO()
                with mock.patch.object(olla.worker, "_generate", return_value=("use tests.test_fake", {})):
                    with redirect_stdout(io.StringIO()), redirect_stderr(err):
                        code = olla.main(["ask", "x"])
            finally:
                os.chdir(cwd)
        self.assertEqual(5, code)
        self.assertIn("likely invented", err.getvalue())

    def test_ask_refuses_an_empty_input_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "input.md"
            empty.write_text("  \n", encoding="utf-8")
            err = io.StringIO()
            with mock.patch.object(olla.worker, "_generate") as generate:
                with redirect_stdout(io.StringIO()), redirect_stderr(err):
                    code = olla.main(["ask", "summarize", "-f", str(empty)])
        self.assertEqual(2, code)
        self.assertIn("empty input file", err.getvalue())
        generate.assert_not_called()

    def test_ask_reports_a_down_server(self) -> None:
        err = io.StringIO()
        with mock.patch.object(olla.worker, "_generate", side_effect=OSError("refused")):
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                code = olla.main(["ask", "x"])
        self.assertEqual(1, code)
        self.assertIn("unreachable", err.getvalue())

    def test_status_reports_a_down_server(self) -> None:
        out = io.StringIO()
        with mock.patch.object(olla, "_get", side_effect=OSError("refused")):
            with redirect_stdout(out):
                code = olla.main(["status"])
        self.assertEqual(1, code)
        self.assertIn('"ok": false', out.getvalue())


class OllaBudgetTests(unittest.TestCase):
    """토큰 0 활용: 추정, 경로 결정, 요약본."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.big = self.base / "big.py"
        self.big.write_text("x = 1\n" * 4000, encoding="utf-8")
        # Windows 는 줄바꿈을 \r\n 으로 저장한다. 기대값은 실제 파일 크기에서 계산한다.
        self.big_tokens = round(self.big.stat().st_size / olla.BYTES_PER_TOKEN)
        self.small = self.base / "small.py"
        self.small.write_text("x = 1\n", encoding="utf-8")
        # 요약본 캐시는 시험마다 비운 임시 폴더로 — 실제 사용자 캐시를 건드리지 않는다
        cache = mock.patch.object(olla, "DIGEST_CACHE_DIR", self.base / "cache")
        cache.start()
        self.addCleanup(cache.stop)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_digest_cache_skips_the_model_until_the_file_changes(self) -> None:
        calls = []

        def fake(model, prompt, timeout):
            calls.append(prompt)
            return ("- L1-300: x", {"input_tokens": 1, "output_tokens": 1})

        def run() -> str:
            err = io.StringIO()
            with mock.patch.object(olla.worker, "_generate", side_effect=fake):
                with redirect_stdout(io.StringIO()), redirect_stderr(err):
                    self.assertEqual(0, olla.main(["digest", "-f", str(self.small), "--focus", "q"]))
            return err.getvalue()

        self.assertIn('"cached": false', run())
        self.assertIn('"cached": true', run())
        self.assertEqual(1, len(calls))
        self.small.write_text("y = 2\n", encoding="utf-8")
        self.assertIn('"cached": false', run())
        self.assertEqual(2, len(calls))

    def test_estimate_counts_rereads(self) -> None:
        cost = olla.estimate_tokens([str(self.big)])
        self.assertEqual(self.big_tokens, cost["read_once"])
        self.assertEqual(self.big_tokens * (1 + olla.REREAD_TURNS), cost["with_rereads"])

    def test_large_read_goes_through_a_local_digest(self) -> None:
        decision = olla.decide_route("이 파일 구조를 설명해줘", [str(self.big)])
        self.assertEqual("local-digest-then-self", decision["route"])
        self.assertGreater(decision["tokens_saved_estimate"], 0)

    def test_specific_edit_goes_local(self) -> None:
        decision = olla.decide_route("In `config.py`, change TIMEOUT_S from 30 to 90.", [])
        self.assertEqual("local-edit", decision["route"])

    def test_small_judgement_task_stays_with_the_paid_model(self) -> None:
        decision = olla.decide_route("이 모듈 설계를 어떻게 바꿀지 판단해줘", [str(self.small)])
        self.assertEqual("self", decision["route"])
        self.assertEqual(0, decision["tokens_saved_estimate"])

    def test_draft_task_goes_local_answer(self) -> None:
        decision = olla.decide_route("write a commit message for this change", [str(self.small)])
        self.assertEqual("local-answer", decision["route"])

    def test_digest_keeps_line_anchors_per_chunk(self) -> None:
        calls = []

        def fake(model, prompt, timeout):
            calls.append(prompt)
            return ("- L1-10: assignments", {"input_tokens": 10, "output_tokens": 3})

        with mock.patch.object(olla.worker, "_generate", side_effect=fake):
            digest, usage = olla.digest_file(self.big, "x", "m", 60)
        # 4,000줄 → 300줄씩 14조각, 조각마다 줄 번호가 붙어 넘어간다
        self.assertEqual(14, len(calls))
        self.assertIn("\n1: x = 1", calls[0])
        self.assertIn("\n301: x = 1", calls[1])
        self.assertTrue(digest.startswith("# digest:"))
        self.assertEqual(140, usage["input_tokens"])

    def test_digest_cli_reports_savings(self) -> None:
        err = io.StringIO()
        with mock.patch.object(olla.worker, "_generate", return_value=("- L1-300: x", {"input_tokens": 1, "output_tokens": 1})):
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                code = olla.main(["digest", "-f", str(self.big)])
        self.assertEqual(0, code)
        report = err.getvalue()
        self.assertIn("saved_pct", report)
        self.assertIn(f'"paid_tokens_if_read": {self.big_tokens}', report)


class OllaReadHookTests(unittest.TestCase):
    """Read 직전 훅: 큰 파일만 알리고, 무슨 입력이 와도 막지 않는다."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.big = Path(self.tmp.name) / "big.py"
        self.big.write_text("x = 1\n" * 4000, encoding="utf-8")
        self.small = Path(self.tmp.name) / "small.py"
        self.small.write_text("x = 1\n", encoding="utf-8")

    def _hook(self, stdin: str) -> tuple[int, str]:
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(stdin)), redirect_stdout(out):
            code = olla.main(["hook-read"])
        return code, out.getvalue()

    def _medium(self) -> Path:
        medium = Path(self.tmp.name) / "medium.py"
        medium.write_text("x = 1\n" * 2000, encoding="utf-8")  # 약 4~5천 토큰: 알림만, 거부 안 함
        return medium

    def test_medium_whole_file_read_gets_a_hint_not_a_denial(self) -> None:
        code, out = self._hook(json.dumps({"tool_name": "Read", "tool_input": {"file_path": str(self._medium())}}))
        self.assertEqual(0, code)
        payload = json.loads(out)["hookSpecificOutput"]
        self.assertIn("offset/limit", payload["additionalContext"])
        self.assertNotIn("permissionDecision", payload)

    def test_very_large_whole_file_read_is_denied_with_a_way_out(self) -> None:
        _, out = self._hook(json.dumps({"tool_input": {"file_path": str(self.big)}}))
        payload = json.loads(out)["hookSpecificOutput"]
        self.assertEqual("deny", payload["permissionDecision"])
        self.assertIn("offset/limit", payload["permissionDecisionReason"])
        self.assertIn("select:mcp__olla__local_read_map", payload["permissionDecisionReason"])  # 지연 도구 불러오는 법
        _, ranged = self._hook(json.dumps({"tool_input": {"file_path": str(self.big), "offset": 1, "limit": 200}}))
        self.assertEqual("", ranged)  # 줄 범위 읽기는 언제나 통과

    def test_cached_digest_is_handed_over_inline(self) -> None:
        medium = self._medium()
        cache = olla._digest_cache_path(medium, "", olla.CHAT_MODEL)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"path": "x", "digest": "- L1-300: assignments"}), encoding="utf-8")
        self.addCleanup(cache.unlink)
        _, out = self._hook(json.dumps({"tool_input": {"file_path": str(medium)}}))
        context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("- L1-300: assignments", context)
        self.assertIn("cached, 0 paid tokens", context)

    def test_uncached_digest_is_prewarmed_once(self) -> None:
        with mock.patch.object(olla, "_server_up", return_value=True), \
                mock.patch("subprocess.Popen") as popen:
            _, first = self._hook(json.dumps({"tool_input": {"file_path": str(self.big)}}))
            _, second = self._hook(json.dumps({"tool_input": {"file_path": str(self.big)}}))
        self.assertEqual(1, popen.call_count)  # 두 번째는 만드는 중 표식 때문에 다시 띄우지 않음
        self.assertIn("digest", popen.call_args.args[0])
        self.assertIn("background", first)
        self.assertNotIn("background", second)
        olla._digest_cache_path(self.big, "", olla.CHAT_MODEL).with_suffix(".pending").unlink()

    def test_korean_path_through_real_stdin_bytes(self) -> None:
        # StringIO 모의로는 못 잡는다. 실제 프로세스에 UTF-8 바이트로 넣어야 cp949 오독이 드러난다.
        import subprocess
        import sys as _sys

        folder = Path(self.tmp.name) / "한글폴더"
        folder.mkdir()
        target = folder / "큰파일.py"
        target.write_text("x = 1\n" * 4000, encoding="utf-8")
        root = Path(__file__).resolve().parents[1]
        env = dict(os.environ, PYTHONPATH=str(root), OLLA_USAGE=str(Path(self.tmp.name) / "u.jsonl"),
                   OLLA_CACHE=str(Path(self.tmp.name) / "cache"), OLLAMA_HOST="http://127.0.0.1:9")
        env.pop("PYTHONIOENCODING", None)
        env.pop("PYTHONUTF8", None)
        done = subprocess.run([_sys.executable, "-m", "v7_harness.olla", "hook-read"], cwd=root, env=env,
                              input=json.dumps({"tool_input": {"file_path": str(target)}}, ensure_ascii=False).encode("utf-8"),
                              capture_output=True, timeout=60)
        self.assertEqual(0, done.returncode)
        self.assertIn("tokens", done.stdout.decode("utf-8"))

    def test_small_or_targeted_reads_stay_silent(self) -> None:
        for tool_input in ({"file_path": str(self.small)}, {"file_path": str(self.big), "offset": 100, "limit": 40}):
            code, out = self._hook(json.dumps({"tool_input": tool_input}))
            self.assertEqual((0, ""), (code, out))

    def test_garbage_input_never_blocks(self) -> None:
        for stdin in ("", "not json", "[]", json.dumps({"tool_input": {"file_path": "Z:/missing.py"}})):
            self.assertEqual((0, ""), self._hook(stdin))


class OllaShellHookTests(unittest.TestCase):
    """Codex 읽은 직후 훅: 셸로 큰 파일을 통째로 출력했을 때만 알리고, 막지 않는다."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        (self.base / "big.py").write_text("x = 1\n" * 4000, encoding="utf-8")
        (self.base / "small.py").write_text("x = 1\n", encoding="utf-8")

    def _hook(self, command, cwd=None) -> tuple[int, str]:
        event = {"hook_event_name": "PostToolUse", "tool_name": "Bash",
                 "cwd": str(cwd or self.base), "tool_input": {"command": command}}
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(json.dumps(event))), redirect_stdout(out):
            code = olla.main(["hook-shell"])
        return code, out.getvalue()

    def test_whole_file_dumps_get_a_digest_hint(self) -> None:
        for command in ("cat big.py", "Get-Content big.py", "cd x && type big.py", f'cat "{self.base / "big.py"}"'):
            code, out = self._hook(command)
            self.assertEqual(0, code, command)
            payload = json.loads(out)["hookSpecificOutput"]
            self.assertEqual("PostToolUse", payload["hookEventName"])
            self.assertIn("tokens", payload["additionalContext"], command)

    def test_ranged_piped_or_small_reads_stay_silent(self) -> None:
        for command in ("cat small.py", "sed -n '1,40p' big.py", "cat big.py | head -40",
                        "Get-Content big.py -TotalCount 40", "grep -n def big.py", "cat missing.py"):
            self.assertEqual((0, ""), self._hook(command), command)

    def test_argv_list_commands_are_read_too(self) -> None:
        for command in (["cat", "big.py"], ["powershell.exe", "-Command", "Get-Content big.py"], ["bash", "-lc", "cat big.py"],
                        ["powershell.exe", "-NoProfile", "-Command", "Get-Content big.py"],
                        'powershell -NoProfile -Command "Get-Content big.py"'):
            code, out = self._hook(command)
            self.assertEqual(0, code)
            self.assertIn("tokens", out, command)

    def test_garbage_input_never_blocks(self) -> None:
        for stdin in ("", "not json", "[]", '{"tool_input": {"command": "cat \\"unterminated"}}'):
            out = io.StringIO()
            with mock.patch("sys.stdin", io.StringIO(stdin)), redirect_stdout(out):
                self.assertEqual(0, olla.main(["hook-shell"]))
            self.assertEqual("", out.getvalue())


class OllaPlanHookTests(unittest.TestCase):
    """작업 시작 훅: 서버가 살아 있을 때만 분업 한 줄을 넣고, 막지 않는다."""

    def _hook(self, stdin: str, up: bool) -> tuple[int, str]:
        out = io.StringIO()
        with mock.patch.object(olla, "_server_up", return_value=up), \
                mock.patch("sys.stdin", io.StringIO(stdin)), redirect_stdout(out):
            code = olla.main(["hook-plan"])
        return code, out.getvalue()

    def test_task_prompt_gets_the_split_reminder(self) -> None:
        code, out = self._hook(json.dumps({"prompt": "니가 할 수 있는 일을 찾아봐"}), up=True)
        self.assertEqual(0, code)
        payload = json.loads(out)["hookSpecificOutput"]
        self.assertEqual("UserPromptSubmit", payload["hookEventName"])
        self.assertIn("local_draft", payload["additionalContext"])
        self.assertIn("local_read_map", payload["additionalContext"])

    def test_silent_when_the_server_is_down_or_input_is_garbage(self) -> None:
        self.assertEqual((0, ""), self._hook(json.dumps({"prompt": "x"}), up=False))
        for stdin in ("not json", "[]"):
            self.assertEqual((0, ""), self._hook(stdin, up=True))


class OllaUsageLogTests(unittest.TestCase):
    """실제 세션 절감을 재기 위한 기록: 병렬로 써도 줄을 잃지 않고, 집계가 맞는다."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.object(olla, "USAGE_LOG", Path(self.tmp.name) / "usage.jsonl")
        patch.start()
        self.addCleanup(patch.stop)

    def test_parallel_writers_lose_no_lines(self) -> None:
        # 스레드는 한 프로세스 안 잠금으로 직렬화되므로, 세 도구처럼 별도 프로세스 4개로 동시에 쓴다.
        import subprocess
        import sys as _sys

        root = Path(__file__).resolve().parents[1]
        code = ("import sys;from pathlib import Path;from v7_harness import olla;"
                "olla.USAGE_LOG=Path(sys.argv[1]);[olla.log_usage('ask',w=int(sys.argv[2]),n=i) for i in range(50)]")
        env = dict(os.environ, PYTHONPATH=str(root))
        procs = [subprocess.Popen([_sys.executable, "-c", code, str(olla.USAGE_LOG), str(w)], env=env, cwd=root)
                 for w in range(4)]
        self.assertEqual([0, 0, 0, 0], [p.wait(timeout=60) for p in procs])
        lines = olla.USAGE_LOG.read_text(encoding="utf-8").splitlines()
        self.assertEqual(200, len(lines))
        self.assertEqual({(w, n) for w in range(4) for n in range(50)},
                         {(json.loads(line)["w"], json.loads(line)["n"]) for line in lines})

    def test_stats_counts_savings_and_followed_hints(self) -> None:
        lines = [json.dumps(r) for r in (
            {"ts": "2026-09-22T10:00:00", "event": "hint_read", "caller": "claude", "file": "a.py"},
            {"ts": "2026-09-22T10:01:00", "event": "digest", "caller": "claude", "file": "a.py",
             "paid_tokens_if_read": 10000, "paid_tokens_digest": 800, "cached": False},
            {"ts": "2026-09-22T10:30:00", "event": "hint_read", "caller": "claude", "file": "b.py"},
            {"ts": "2026-09-22T10:31:00", "event": "digest", "caller": "codex", "file": "c.py",
             "paid_tokens_if_read": 5000, "paid_tokens_digest": 400, "cached": True},
        )] + ["not json"]
        stats = olla.usage_stats(lines)
        claude, codex = stats["by_caller"]["claude"], stats["by_caller"]["codex"]
        self.assertEqual((2, 1, 9200), (claude["hint_read"], claude["hint_read_followed"], claude["paid_tokens_saved"]))
        self.assertEqual((1, 1, 4600), (codex["digest"], codex["digest_cached"], codex["paid_tokens_saved"]))

    def test_logging_failure_never_breaks_the_command(self) -> None:
        with mock.patch.object(olla, "USAGE_LOG", Path(self.tmp.name) / "missing_dir_is_file"):
            (Path(self.tmp.name) / "missing_dir_is_file").mkdir()
            olla.log_usage("ask")  # 디렉터리에 append 실패 — 예외 없이 지나가야 한다


class OllaTurnShapeTests(unittest.TestCase):
    """Stop 훅: 진행 설명 수와 최종 보고 길이를 두 도구 기록 형식에서 모두 잰다."""

    def _write(self, rows: list[dict]) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "t.jsonl"
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
        return path

    def test_claude_transcript(self) -> None:
        path = self._write([
            {"type": "user", "message": {"content": "이전 지시"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "옛 보고"}]}},
            {"type": "user", "message": {"content": "새 지시"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "진행 설명"}, {"type": "tool_use"}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result"}]}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "결과 1\n결과 2"}]}},
        ])
        self.assertEqual({"narration_blocks": 1, "final_lines": 2, "final_chars": 9, "nested_lines": 0}, olla.turn_shape(path))

    def test_codex_rollout(self) -> None:
        msg = lambda t: {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"text": t}]}}
        path = self._write([{"type": "event_msg", "payload": {"type": "task_started"}}, msg("a"), msg("b"), msg("끝")])
        self.assertEqual(2, olla.turn_shape(path)["narration_blocks"])

    def test_stats_counts_turns_within_rule(self) -> None:
        lines = [json.dumps({"ts": "2026-09-22T10:00:00", "event": "turn_shape", "caller": "claude", **shape}) for shape in (
            {"narration_blocks": 0, "final_lines": 3}, {"narration_blocks": 2, "final_lines": 3}, {"narration_blocks": 0, "final_lines": 7})]
        row = olla.usage_stats(lines)["by_caller"]["claude"]
        self.assertEqual((3, 1), (row["turns"], row["turns_within_rule"]))

    def _stop(self, lines: int, active: bool) -> str:
        path = self._write([{"type": "user", "message": {"content": "지시"}},
                            {"type": "assistant", "message": {"content": [{"type": "text", "text": "\n".join(["줄"] * lines)}]}}])
        out = io.StringIO()
        event = {"transcript_path": str(path), "stop_hook_active": active}
        with mock.patch("sys.stdin", io.StringIO(json.dumps(event))), redirect_stdout(out):
            self.assertEqual(0, olla.main(["hook-stop"]))
        return out.getvalue()

    def test_long_report_is_recorded_not_sent_back(self) -> None:
        # 되돌리면 긴 보고와 고쳐 쓴 보고가 둘 다 화면에 남는다(Biz 캡처). 기록만 하고 다음 지시에서 되비춘다.
        self.assertEqual("", self._stop(olla.REPORT_MAX_LINES + 3, active=False))
        shape = [json.loads(l) for l in olla.USAGE_LOG.read_text(encoding="utf-8").splitlines()][-1]
        self.assertEqual(olla.REPORT_MAX_LINES + 3, shape["final_lines"])
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": ""}):
            rows = olla.USAGE_LOG.read_text(encoding="utf-8").splitlines()
            olla.USAGE_LOG.write_text("\n".join(json.dumps({**json.loads(r), "session": "sx"}) for r in rows),
                                      encoding="utf-8")
            self.assertIn("write the next one shorter", olla.session_scorecard("sx"))

    def test_hook_never_blocks(self) -> None:
        for stdin in ("", "x", json.dumps({"transcript_path": "Z:/none.jsonl"})):
            out = io.StringIO()
            with mock.patch("sys.stdin", io.StringIO(stdin)), redirect_stdout(out):
                self.assertEqual(0, olla.main(["hook-stop"]))
            self.assertEqual("", out.getvalue())


class OllaRecurringFailureGuardTests(unittest.TestCase):
    """반복 오류 차단: 세션 성적 되비춤, 260자 한도에 가까운 cd 거부."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.object(olla, "USAGE_LOG", Path(self.tmp.name) / "usage.jsonl")
        patch.start()
        self.addCleanup(patch.stop)

    def test_scorecard_reports_only_this_session(self) -> None:
        rows = [
            {"event": "hint_read", "session": "s1"}, {"event": "digest", "session": "s1"},
            {"event": "turn_shape", "session": "s1", "narration_blocks": 0, "final_lines": 9},
            {"event": "turn_shape", "session": "s1", "narration_blocks": 0, "final_lines": 3, "final_chars": 100},
            {"event": "ask", "session": "other"},
        ]
        olla.USAGE_LOG.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        card = olla.session_scorecard("s1")
        self.assertIn("olla used 1x", card)
        self.assertIn("big-read hints 1", card)
        self.assertIn("output rule 1/2", card)
        self.assertEqual("", olla.session_scorecard("nobody"))

    def test_plan_hint_carries_the_scorecard(self) -> None:
        olla.USAGE_LOG.write_text(json.dumps({"event": "hint_read", "session": "s9"}), encoding="utf-8")
        out = io.StringIO()
        with mock.patch.object(olla, "_server_up", return_value=True), \
                mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "s9"}), \
                mock.patch("sys.stdin", io.StringIO("{}")), redirect_stdout(out):
            olla.main(["hook-plan"])
        self.assertIn("This session so far", json.loads(out.getvalue())["hookSpecificOutput"]["additionalContext"])

    def _bash(self, command: str, cwd: str) -> str:
        out = io.StringIO()
        event = {"tool_input": {"command": command}, "cwd": cwd}
        with mock.patch("sys.stdin", io.StringIO(json.dumps(event))), redirect_stdout(out):
            self.assertEqual(0, olla.main(["hook-bash"]))
        return out.getvalue()

    def test_deep_cd_is_denied_shallow_is_allowed(self) -> None:
        deep = "D:/" + "a" * olla.CWD_MAX_CHARS
        payload = json.loads(self._bash(f'cd "{deep}" && ls', "D:/proj"))["hookSpecificOutput"]
        self.assertEqual("deny", payload["permissionDecision"])
        self.assertEqual("", self._bash("cd src && ls", "D:/proj"))
        self.assertEqual("", self._bash("git status", "D:/" + "a" * 250))
        self.assertEqual("", self._bash("", ""))


class OllaSqueezeTests(unittest.TestCase):
    """발상 전환: 선택을 기다리지 않고 시끄러운 명령의 출력을 훅이 줄인다. 전체는 파일, 종료 코드는 그대로."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        for name, value in (("USAGE_LOG", self.tmp / "usage.jsonl"), ("RUN_DIR", self.tmp / "run")):
            patch = mock.patch.object(olla, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def _hook(self, command: str, tool: str = "Bash") -> str:
        out = io.StringIO()
        event = {"tool_name": tool, "tool_input": {"command": command, "timeout": 5}, "cwd": "D:/proj"}
        with mock.patch("sys.stdin", io.StringIO(json.dumps(event))), redirect_stdout(out):
            self.assertEqual(0, olla.main(["hook-bash"]))
        return out.getvalue()

    def test_only_noisy_stateless_bash_commands_are_wrapped(self) -> None:
        payload = json.loads(self._hook("python -m pytest tests"))["hookSpecificOutput"]
        self.assertTrue(payload["updatedInput"]["command"].startswith("olla squeeze --script "))
        self.assertEqual(5, payload["updatedInput"]["timeout"])  # 다른 입력은 그대로
        script = Path(payload["updatedInput"]["command"].split("'")[1])
        self.assertEqual("python -m pytest tests\n", script.read_text(encoding="utf-8"))
        self.assertNotIn("permissionDecision", payload)  # 권한 판단은 바꾸지 않는다
        self.assertIn("updatedInput", self._hook('git -C "D:/a b/proj" log'))  # 실측에서 놓친 형태
        for quiet in ("git diff --stat", "git log --oneline", "git log -n 5", "cd src && pytest",
                      "pytest | tail -5", "git status", "ls"):
            self.assertEqual("", self._hook(quiet), quiet)
        self.assertEqual("", self._hook("pytest", tool="PowerShell"))

    def test_long_output_keeps_signals_and_tail_full_log_on_disk(self) -> None:
        passed = "tests/test_a.py::test_ok PASSED"
        text = "\n".join([passed] * 500 + ["FAILED test_x - AssertionError"] + [passed] * 500 + ["1 failed"]) + "\n"
        log = self.tmp / "out" / "full.log"
        out = olla.squeeze_text(text, log)
        self.assertEqual(text, log.read_text(encoding="utf-8"))
        self.assertIn("501: FAILED test_x", out)
        self.assertTrue(out.rstrip().endswith("1 failed"))
        self.assertLess(len(out), len(text) / 3)
        short = "short output\n"
        self.assertIs(short, olla.squeeze_text(short, self.tmp / "none.log"))

    def test_squeeze_keeps_the_exit_code(self) -> None:
        script = self.tmp / "s.sh"
        script.write_text("echo hi\nexit 3\n", encoding="utf-8", newline="\n")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(3, olla.main(["squeeze", "--script", str(script)]))
        self.assertEqual("hi\n", out.getvalue().replace("\r", ""))

    def test_windows_ignores_powershell_shell_and_falls_back_to_git_bash(self) -> None:
        script = self.tmp / "s.sh"
        script.write_text("echo hi\nexit 3\n", encoding="utf-8", newline="\n")
        powershell = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
        git_bash = r"C:\Program Files\Git\bin\bash.exe"

        def run(command, **_kwargs):
            return olla.subprocess.CompletedProcess(command, 3 if command[0] == git_bash else 0, b"hi\n")

        out = io.StringIO()
        with mock.patch.dict(os.environ, {"SHELL": powershell}), \
                mock.patch.object(olla.sys, "platform", "win32"), \
                mock.patch.object(olla.shutil, "which", return_value=None), \
                mock.patch.object(olla.os.path, "exists", side_effect=lambda path: path == git_bash), \
                mock.patch.object(olla.subprocess, "run", side_effect=run) as runner, \
                redirect_stdout(out):
            self.assertEqual(3, olla.main(["squeeze", "--script", str(script)]))

        self.assertEqual(git_bash, runner.call_args.args[0][0])
        self.assertEqual("hi\n", out.getvalue().replace("\r", ""))

    def test_context_size_note_reads_the_last_usage(self) -> None:
        transcript = self.tmp / "t.jsonl"
        rows = [{"message": {"usage": {"input_tokens": 1, "cache_read_input_tokens": 1000}}},
                {"message": {"usage": {"input_tokens": 5, "cache_creation_input_tokens": 1000,
                                       "cache_read_input_tokens": 170_000}}}]
        transcript.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        note = olla.context_size_note(str(transcript))
        self.assertIn("~171k tokens per call", note)
        self.assertNotIn("새 대화", note)  # 세션 번호가 없으면 한 번만 주기를 셀 수 없으니 주지 않는다
        first = olla.context_size_note(str(transcript), "", "s1")
        self.assertIn("같은 폴더에서 새 대화를 열면", first)  # 사용자가 할 행동을 그대로 준다
        self.assertNotIn("새 대화", olla.context_size_note(str(transcript), "", "s1"))  # 같은 구간에서는 한 번만
        self.assertEqual("", olla.context_size_note(""))


class OllaHandoffTests(unittest.TestCase):
    """이어 열기(호출당 약 30만 토큰) 대신 새 세션 + 인계문. 모델이 꺼져도 결정적 사실만으로 인계된다."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        for name, value in (("USAGE_LOG", self.tmp / "usage.jsonl"), ("HANDOFF_DIR", self.tmp / "handoff")):
            patch = mock.patch.object(olla, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        rows = [
            {"type": "user", "message": {"content": "Optimize the Biz coach prompts"}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "x"}]}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Edit", "input": {"file_path": "D:/biz/a.md"}},
                {"type": "tool_use", "name": "Bash", "input": {"command": 'git commit -q -m "feat: tune routing"'}},
                {"type": "text", "text": "**결과**: routing tuned"}]}},
        ]
        self.transcript = self.tmp / "s.jsonl"
        self.transcript.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")

    def _start(self, source: str, session: str = "new") -> str:
        out = io.StringIO()
        event = {"source": source, "cwd": "D:/biz", "session_id": session}
        with mock.patch("sys.stdin", io.StringIO(json.dumps(event))), redirect_stdout(out):
            self.assertEqual(0, olla.main(["hook-start"]))
        return out.getvalue()

    def test_stop_starts_the_handoff_for_a_big_context_without_a_new_prompt(self) -> None:
        # Biz 40375870: 지시 1번에 188k 까지 자랐는데 인계문 0건 — 지시 때만 재면 놓친다
        def stop(size: int) -> mock.MagicMock:
            row = {"type": "assistant", "message": {"usage": {"input_tokens": 1, "cache_read_input_tokens": size},
                                                     "content": [{"type": "text", "text": "**결과**: ok"}]}}
            self.transcript.write_text(json.dumps(row), encoding="utf-8")
            event = {"transcript_path": str(self.transcript), "cwd": "D:/biz", "session_id": "s"}
            with mock.patch.object(olla, "_start_handoff") as start, \
                    mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": ""}), \
                    mock.patch("sys.stdin", io.StringIO(json.dumps(event))), redirect_stdout(io.StringIO()):
                self.assertEqual(0, olla.main(["hook-stop"]))
            return start

        stop(188_000).assert_called_once_with(str(self.transcript), "D:/biz", "s")
        stop(90_000).assert_not_called()

    def test_facts_and_new_session_injection(self) -> None:
        facts = olla.handoff_facts(self.transcript)
        self.assertEqual(["Optimize the Biz coach prompts"], facts["prompts"])  # 도구 결과는 지시가 아니다
        self.assertEqual(["D:/biz/a.md"], facts["files"])
        self.assertEqual(["feat: tune routing"], facts["commits"])
        with mock.patch.object(olla, "_server_up", return_value=False):
            self.assertEqual(0, olla.main(["handoff", "--transcript", str(self.transcript), "--cwd", "D:/biz",
                                           "--session", "old"]))
        context = json.loads(self._start("startup"))["hookSpecificOutput"]["additionalContext"]
        self.assertIn("previous session old", context)
        self.assertIn("feat: tune routing", context)
        self.assertEqual("", self._start("resume"))  # 이어 열기에는 이미 전체 기록이 있다
        self.assertEqual("", self._start("startup", session="old"))  # 자기 인계문은 넣지 않는다

    def test_worktrees_of_one_repo_share_the_handoff(self) -> None:
        self.assertEqual(olla._handoff_path("D:/biz/.claude/worktrees/old-a1"),
                         olla._handoff_path("D:/biz/.claude/worktrees/new-b2"))
        self.assertEqual(olla._handoff_path("D:/biz"), olla._handoff_path("D:/biz/.claude/worktrees/new-b2"))
        self.assertNotEqual(olla._handoff_path("D:/biz"), olla._handoff_path("D:/other"))

    def test_stale_or_missing_handoff_is_ignored(self) -> None:
        self.assertEqual("", self._start("startup"))
        path = olla._handoff_path("D:/biz")
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"session": "old", "created": 0, "text": "x"}), encoding="utf-8")
        self.assertEqual("", self._start("startup"))

    def test_big_context_starts_a_background_handoff_once(self) -> None:
        big = self.tmp / "big.jsonl"
        big.write_text(json.dumps({"message": {"usage": {"cache_read_input_tokens": 300_000}}}), encoding="utf-8")
        with mock.patch.object(olla.subprocess, "Popen") as popen:
            note = olla.context_size_note(str(big), "D:/biz", "s1")
            olla.context_size_note(str(big), "D:/biz", "s1")
        self.assertIn("~300k", note)
        self.assertEqual(1, popen.call_count)  # 30분 안에는 다시 만들지 않는다
        self.assertIn("handoff", popen.call_args[0][0])


class OllaAntigravityHookTests(unittest.TestCase):
    """Antigravity 형식: 입력·출력 모양이 달라 어댑터로 옮긴다. 승인을 대신 내주지 않는다."""

    def test_pre_invocation_injects_once_per_turn(self) -> None:
        with mock.patch.object(olla, "_server_up", return_value=True):
            first = olla.agy_hook("PreInvocation", {"invocationNum": 0, "conversationId": "c1"})
            later = olla.agy_hook("PreInvocation", {"invocationNum": 3})
        self.assertIn("local_read_map", first["injectSteps"][0]["ephemeralMessage"])
        self.assertIsNone(later)

    def test_pre_tool_use_denies_only_deep_cd_and_never_allows(self) -> None:
        deep = "D:/" + "a" * olla.CWD_MAX_CHARS
        denied = olla.agy_hook("PreToolUse", {"toolCall": {"name": "run_command", "args": {"CommandLine": f"cd {deep}", "Cwd": "D:/p"}}})
        self.assertEqual("deny", denied["decision"])
        self.assertIsNone(olla.agy_hook("PreToolUse", {"toolCall": {"name": "run_command", "args": {"CommandLine": "git status"}}}))
        self.assertIsNone(olla.agy_hook("PreToolUse", {"toolCall": {"name": "view_file", "args": {"AbsolutePath": "x"}}}))

    def test_view_file_of_a_very_large_file_is_denied_unless_ranged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            big = Path(tmp) / "big.py"
            big.write_text("x = 1\n" * 4000, encoding="utf-8")
            whole = olla.agy_hook("PreToolUse", {"toolCall": {"name": "view_file", "args": {"AbsolutePath": str(big)}}})
            ranged = olla.agy_hook("PreToolUse", {"toolCall": {"name": "view_file",
                                                               "args": {"AbsolutePath": str(big), "StartLine": 1, "EndLine": 50}}})
        self.assertEqual("deny", whole["decision"])
        self.assertIsNone(ranged)

    def test_stop_records_a_long_report_without_sending_it_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.jsonl"
            path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in (
                {"type": "user", "message": {"content": "x"}},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "\n".join(["줄"] * 9)}]}})), encoding="utf-8")
            with mock.patch.object(olla, "USAGE_LOG", Path(tmp) / "u.jsonl"):
                self.assertIsNone(olla.agy_hook("Stop", {"transcriptPath": str(path), "executionNum": 0}))
                self.assertIn('"final_lines": 9', (Path(tmp) / "u.jsonl").read_text(encoding="utf-8"))

    def test_stop_records_antigravity_native_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "transcript.jsonl"
            path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in (
                {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "과제 해줘"},
                {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "thinking": "생각 중", "content": "중간 설명"},
                {"step_index": 2, "source": "MODEL", "type": "PLANNER_RESPONSE", "thinking": "생각 완료",
                 "content": "**결과**: 완료\n- 과정: A -> B\n- 근거: 테스트 통과"})), encoding="utf-8")
            with mock.patch.object(olla, "USAGE_LOG", Path(tmp) / "u.jsonl"):
                self.assertIsNone(olla.agy_hook("Stop", {"transcriptPath": str(path), "conversationId": "conv1", "executionNum": 0}))
                log_content = (Path(tmp) / "u.jsonl").read_text(encoding="utf-8")
                self.assertIn('"caller": "antigravity"', log_content)
                self.assertIn('"session": "conv1"', log_content)
                self.assertIn('"narration_blocks": 1', log_content)
                self.assertIn('"final_lines": 3', log_content)


class OllaFindTests(unittest.TestCase):
    def test_ranks_files_by_similarity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "cache.md").write_text("캐시 만료 정책", encoding="utf-8")
            (base / "auth.md").write_text("로그인 토큰 갱신", encoding="utf-8")
            def fake_embed(texts):
                # 파일을 읽는 순서와 무관하게 내용으로 벡터를 정한다. "캐시"가 든 글은 질문과 같은 방향.
                return [[1.0, 0.0] if "캐시" in text else [0.0, 1.0] for text in texts]

            out = io.StringIO()
            with mock.patch.object(olla, "_embed", side_effect=fake_embed):
                with redirect_stdout(out):
                    code = olla.main(["find", "캐시", "-d", str(base)])
            self.assertEqual(0, code)
            lines = out.getvalue().splitlines()
            self.assertTrue(lines[0].endswith("cache.md"))
            self.assertTrue(lines[1].endswith("auth.md"))


if __name__ == "__main__":
    unittest.main()
