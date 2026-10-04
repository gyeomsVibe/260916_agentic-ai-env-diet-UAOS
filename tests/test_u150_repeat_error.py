"""U150-B: one user error report reaches all three tools; a repeat becomes P1 instead of a third instruction.

Receipt (2026-10-04): 윤겸스 had to tell each tool about the same failure (message-id collision, invisible Antigravity
changes). The shared prompt hook now records every error report, shows it to the other two tools on their next
turn, and marks a repeat of the same report P1 with a mandatory root-cause card.
"""

import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import repeat_error as re_

T0 = 1_790_000_000.0


class Classify(unittest.TestCase):
    def test_error_reports(self):
        for text in ("메시지 ID 충돌 결함 고쳐줘", "안티그래비티 앱에서 아무 변화가 없다. 프로젝트 실패이다.",
                     "the relay is broken again"):
            self.assertTrue(re_.is_error_report(text), text)

    def test_not_error_reports(self):
        # Codex counterexample 1 (REWORK 2f93901f): an injected relay was classified as a human report.
        for text in ("지금부터 여기가 사용자 대상 대화창구이다.", "다음 카드 진행", "", None,
                     "<task-notification> failed", "[agy-auto] error",
                     "[UAOS relay id=fixture digest=fixture] error report", "[DATA] from=codex failed"):
            self.assertFalse(re_.is_error_report(text), text)


class Record(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        (self.project / ".coord").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_first_report_is_count_one(self):
        got = re_.record(self.project, "claude", "메시지 ID 충돌 결함 고쳐줘", now=T0)
        self.assertEqual(1, got["count"])

    def test_same_error_again_in_another_tool_counts_two(self):
        re_.record(self.project, "claude", "메시지 ID 충돌 결함 고쳐줘", now=T0)
        got = re_.record(self.project, "codex", "메시지 ID 충돌 결함 아직도 있다, 고쳐라", now=T0 + 60)
        self.assertEqual(2, got["count"])
        self.assertEqual({"claude", "codex"}, set(got["tools"]))

    def test_unrelated_error_is_separate(self):
        re_.record(self.project, "claude", "메시지 ID 충돌 결함 고쳐줘", now=T0)
        got = re_.record(self.project, "claude", "안티그래비티 화면 제목 변화 없음 실패", now=T0 + 60)
        self.assertEqual(1, got["count"])

    def test_reports_older_than_the_window_do_not_count(self):
        re_.record(self.project, "claude", "메시지 ID 충돌 결함 고쳐줘", now=T0)
        got = re_.record(self.project, "claude", "메시지 ID 충돌 결함 고쳐줘", now=T0 + re_.WINDOW_S + 1)
        self.assertEqual(1, got["count"])

    def test_parallel_records_lose_no_line(self):
        def run(i):
            re_.record(self.project, f"tool{i % 3}", f"결함 {i} 고쳐줘 case{i}", now=T0 + i)

        workers = [threading.Thread(target=run, args=(i,)) for i in range(12)]
        for w in workers:
            w.start()
        for w in workers:
            w.join()
        self.assertEqual(12, len(re_.load(self.project)))


class HookLines(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        (self.project / ".coord").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_first_report_tells_the_tool_to_fix_for_all_three(self):
        line = re_.on_prompt(self.project, "claude", "메시지 ID 충돌 결함 고쳐줘", now=T0)
        self.assertIn("USER ERROR REPORT", line)
        self.assertIn("all 3 tools", line)

    def test_repeat_is_p1(self):
        re_.on_prompt(self.project, "claude", "메시지 ID 충돌 결함 고쳐줘", now=T0)
        line = re_.on_prompt(self.project, "codex", "메시지 ID 충돌 결함 또 났다 고쳐", now=T0 + 5)
        self.assertIn("P1", line)
        self.assertIn("root-cause card", line)

    def test_other_tools_see_the_report_once(self):
        re_.on_prompt(self.project, "claude", "메시지 ID 충돌 결함 고쳐줘", now=T0)
        seen = re_.on_prompt(self.project, "antigravity", "다음 카드 진행", now=T0 + 5)
        self.assertIn("claude", seen)
        self.assertIn("메시지 ID 충돌", seen)
        self.assertEqual("", re_.on_prompt(self.project, "antigravity", "다음 카드 진행", now=T0 + 6))
        self.assertEqual("", re_.on_prompt(self.project, "claude", "다음 카드 진행", now=T0 + 7))

    def test_each_receiver_has_one_receipt(self):
        got = re_.record(self.project, "claude", "메시지 ID 충돌 결함 고쳐줘", now=T0)
        re_.deliver_unseen(self.project, "codex", now=T0 + 1)
        re_.deliver_unseen(self.project, "antigravity", now=T0 + 2)
        re_.deliver_unseen(self.project, "codex", now=T0 + 3)
        rows = re_._read_jsonl(re_._receipts(self.project))
        self.assertEqual([("codex", got["id"]), ("antigravity", got["id"])], [(r["tool"], r["report"]) for r in rows])


class Durability(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        (self.project / ".coord").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_failed_read_loses_nothing(self):
        # Codex counterexample 2: a read OSError after the cursor advanced made the report invisible on retry.
        re_.record(self.project, "claude", "메시지 ID 충돌 결함 고쳐줘", now=T0)
        real = Path.read_text

        def broken(path, *a, **k):
            if path.name == "user_error_reports.jsonl":
                raise PermissionError("locked")
            return real(path, *a, **k)

        with mock.patch.object(Path, "read_text", broken):
            self.assertEqual([], re_.deliver_unseen(self.project, "codex", now=T0 + 2))
        self.assertEqual(1, len(re_.deliver_unseen(self.project, "codex", now=T0 + 3)))

    def test_parallel_receivers_of_one_tool_get_it_once(self):
        re_.record(self.project, "claude", "메시지 ID 충돌 결함 고쳐줘", now=T0)
        counts = []

        def run(i):
            counts.append(len(re_.deliver_unseen(self.project, "codex", now=T0 + 1 + i)))

        workers = [threading.Thread(target=run, args=(i,)) for i in range(8)]
        for w in workers:
            w.start()
        for w in workers:
            w.join()
        self.assertEqual(1, sum(counts))

    def test_mixed_tool_parallel_receivers_each_get_it_once(self):
        # Codex REWORK 94075087: different tools appending to the shared receipt file at the same time.
        got = re_.record(self.project, "claude", "메시지 ID 충돌 결함 고쳐줘", now=T0)
        counts = {"codex": [], "antigravity": []}

        def run(tool, i):
            counts[tool].append(len(re_.deliver_unseen(self.project, tool, now=T0 + 1 + i)))

        workers = [threading.Thread(target=run, args=(tool, i)) for i in range(6) for tool in counts]
        for w in workers:
            w.start()
        for w in workers:
            w.join()
        self.assertEqual({"codex": 1, "antigravity": 1}, {tool: sum(c) for tool, c in counts.items()})
        rows = re_._read_jsonl(re_._receipts(self.project))
        self.assertEqual(sorted([("antigravity", got["id"]), ("codex", got["id"])]),
                         sorted((r["tool"], r["report"]) for r in rows))

    def test_secret_like_prompt_is_stored_redacted_but_still_matches(self):
        secret = "sk-ant-api03-" + "A" * 40
        first = re_.record(self.project, "claude", f"키 {secret} 넣으니 결함 고쳐줘", now=T0)
        again = re_.record(self.project, "codex", f"키 {secret} 넣으니 결함 고쳐줘", now=T0 + 1)
        stored = re_._reports(self.project).read_text(encoding="utf-8")
        self.assertNotIn(secret, stored)
        self.assertNotIn("sk-ant", stored)
        self.assertEqual(re_.REDACTED, first["text"])
        self.assertEqual(2, again["count"])


if __name__ == "__main__":
    unittest.main()
