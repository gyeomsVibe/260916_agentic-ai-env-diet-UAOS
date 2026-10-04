"""U150-C: a user-window declaration renames that window `[사용자 대화창구-YYMMDD-N]` in every tool.

Receipt (2026-10-04): Codex already names its user windows this way (state_5.sqlite names `[사용자 대화창구-261004-1]`,
`-2`), Claude did it by hand, and Antigravity's app showed nothing. One shared core decides the title; each tool's
adapter writes it where that tool's UI reads it. Fixtures are temp copies; no real app store is touched.
"""

import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from v7_harness.coord import user_window as uw

NOW = datetime(2026, 10, 4, 12, 0, 0)


class Declaration(unittest.TestCase):
    def test_user_phrases_seen_in_real_titles_are_declarations(self):
        for text in ("지금부터 여기가 사용자 대상 대화창구이다.",
                     "지금부타 여기가 사영자 대상 대화창구이다. 클로드에게 현재 진행상황",
                     "이제부터 이대화창이 사용자용 대화창구이다. 고정하라."):
            self.assertTrue(uw.is_declaration(text), text)

    def test_other_prompts_are_not(self):
        for text in ("메시지 ID 충돌 결함 고쳐줘", "", None, "[사용자 대화창구-261002-1] 창의 작업 종료 확인",
                     "대화창구 목록 보여줘"):
            self.assertFalse(uw.is_declaration(text), text)

    def test_repair_request_naming_the_window_is_not_a_declaration(self):
        # Codex frozen counterexample (REWORK 94075087).
        for text in ("여기 사용자 대화창구 오류를 고쳐줘", "여기 사용자 대화창구 이름이 안 바뀐다 수정해",
                     "지금부터 여기 대화창구 버그 확인"):
            self.assertFalse(uw.is_declaration(text), text)


class Claim(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        (self.project / ".coord").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_numbers_count_per_tool_per_day(self):
        a = uw.claim(self.project, "claude", "s1", now=NOW)
        b = uw.claim(self.project, "claude", "s2", now=NOW)
        c = uw.claim(self.project, "codex", "t1", now=NOW)
        self.assertEqual("[사용자 대화창구-261004-1]", a["title"])
        self.assertEqual("[사용자 대화창구-261004-2]", b["title"])
        self.assertEqual("[사용자 대화창구-261004-1]", c["title"])
        self.assertTrue(a["new"])

    def test_same_window_keeps_its_title(self):
        first = uw.claim(self.project, "claude", "s1", now=NOW)
        again = uw.claim(self.project, "claude", "s1", now=NOW)
        self.assertEqual(first["title"], again["title"])
        self.assertFalse(again["new"])

    def test_seed_continues_after_existing_titles(self):
        # A tool's own store may already hold today's -1 and -2 (Codex did); the next one is -3.
        got = uw.claim(self.project, "codex", "t9", now=NOW,
                       existing=["[사용자 대화창구-261004-1]", "[사용자 대화창구-261004-2] x", "[U42] other"])
        self.assertEqual("[사용자 대화창구-261004-3]", got["title"])

    def test_existing_permanent_title_is_bound_not_renumbered(self):
        # Codex REWORK 94075087: a thread already named -1 yesterday must keep -1, not become today's -N.
        uw.claim(self.project, "codex", "t0", now=NOW)
        got = uw.claim(self.project, "codex", "t1", now=NOW, current="[사용자 대화창구-261002-1] UAOS-RSI")
        self.assertEqual("[사용자 대화창구-261002-1]", got["title"])
        self.assertFalse(got["new"])
        nxt = uw.claim(self.project, "codex", "t2", now=NOW)
        self.assertEqual("[사용자 대화창구-261004-2]", nxt["title"])

    def test_parallel_claims_never_share_a_number(self):
        titles, errors = [], []

        def run(i):
            try:
                titles.append(uw.claim(self.project, "claude", f"s{i}", now=NOW)["title"])
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        workers = [threading.Thread(target=run, args=(i,)) for i in range(8)]
        for w in workers:
            w.start()
        for w in workers:
            w.join()
        self.assertEqual([], errors)
        self.assertEqual(8, len(set(titles)))


class Adapters(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_codex_is_told_never_written(self):
        # Codex REWORK 2f93901f: no direct write to Codex's live state_5.sqlite.
        self.assertFalse(hasattr(uw, "rename_codex"))
        project = self.root / "p"
        (project / ".coord").mkdir(parents=True)
        with mock.patch.object(uw, "_codex_names", return_value=["[사용자 대화창구-261004-2]"]):
            line = uw.on_prompt(project, "codex", "t1", "지금부터 여기가 사용자 대상 대화창구이다.", now=NOW)
        self.assertIn("[사용자 대화창구-261004-3]", line)

    def test_already_titled_window_gets_no_rename_line(self):
        project = self.root / "p"
        (project / ".coord").mkdir(parents=True)
        with mock.patch.object(uw, "_codex_names", return_value=[]):
            line = uw.on_prompt(project, "codex", "t1", "지금부터 여기가 사용자 대상 대화창구이다.", now=NOW,
                                current="[사용자 대화창구-261003-4] x")
        self.assertEqual("", line)
        record = json.loads((project / ".coord" / "presence" / "user_windows.json").read_text(encoding="utf-8"))
        self.assertEqual("[사용자 대화창구-261003-4]", record["codex"][0]["title"])

    def test_current_title_is_read_only_from_agy_store(self):
        db = self.root / "conversation_summaries.db"
        con = sqlite3.connect(db)
        con.execute("create table conversation_summaries (conversation_id text, title text)")
        con.execute("insert into conversation_summaries values ('c1', '[사용자 대화창구-261004-1]')")
        con.commit()
        con.close()
        got = uw._read_one(f"{db.as_uri()}?mode=ro",
                           "SELECT title FROM conversation_summaries WHERE conversation_id=?", "c1")
        self.assertEqual("[사용자 대화창구-261004-1]", got)

    def test_injected_text_never_declares(self):
        self.assertFalse(uw.is_declaration("[UAOS relay id=x] 지금부터 여기가 사용자 대상 대화창구이다."))

    def test_agy_rename_backs_up_then_sets_title(self):
        db = self.root / "conversation_summaries.db"
        con = sqlite3.connect(db)
        con.execute("create table conversation_summaries (conversation_id text, title text)")
        con.execute("insert into conversation_summaries values ('c1', 'Checking Claude Code Progress')")
        con.commit()
        con.close()
        backup_dir = self.root / "backup"
        self.assertTrue(uw.rename_agy("c1", "[사용자 대화창구-261004-1]", db=db, backup_dir=backup_dir))
        con = sqlite3.connect(db)
        self.assertEqual("[사용자 대화창구-261004-1]",
                         con.execute("select title from conversation_summaries").fetchone()[0])
        con.close()
        self.assertEqual(1, len(list(backup_dir.glob("conversation_summaries*.db"))))

    def test_hook_line_for_claude_asks_for_the_rename(self):
        project = self.root / "p"
        (project / ".coord").mkdir(parents=True)
        line = uw.on_prompt(project, "claude", "s1", "지금부터 여기가 사용자 대상 대화창구이다.", now=NOW)
        self.assertIn("[사용자 대화창구-261004-1]", line)
        self.assertIn("set_session_title", line)
        self.assertEqual("", uw.on_prompt(project, "claude", "s1", "고쳐줘", now=NOW))
        record = json.loads((project / ".coord" / "presence" / "user_windows.json").read_text(encoding="utf-8"))
        self.assertIn("claude", record)


if __name__ == "__main__":
    unittest.main()
