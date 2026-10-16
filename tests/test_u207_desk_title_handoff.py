"""U207-A: a declared user desk keeps getting its rename instruction until the tool's own store shows the title.

Receipt (2026-10-16, 윤겸스 report with screenshots): the new desk [사용자 대화창구-261016-1] kept its old title in Claude and
Antigravity. The claim registry was right; the rename was a one-shot hook line (lost once = lost for good) and the
Antigravity write was opt-in and off. Codex verdict relay_b12ae490 / Antigravity audit relay_4791eecf gates:
readback per exact session, UNKNOWN is never a match, bounded re-issue, AGY backup of DB and annotation, atomic
annotation replace, explicit partial-failure status, concurrent-writer test. Fixtures are temp copies only.
"""

import json
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest import mock

from v7_harness.coord import user_window as uw

NOW = datetime(2026, 10, 16, 10, 0, 0)
DECLARE = "이제부터 이대화창이 사용자 대상 대화창구이다."
TITLE = "[사용자 대화창구-261016-1]"


def _registry(project):
    return json.loads((project / ".coord" / "presence" / "user_windows.json").read_text(encoding="utf-8"))


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.project = self.root / "p"
        (self.project / ".coord").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()


class Reconcile(Base):
    def test_lost_instruction_is_reissued_until_readback_matches(self):
        with mock.patch.object(uw, "_current_title", return_value="새 대화"):
            first = uw.on_prompt(self.project, "claude", "s1", DECLARE, now=NOW)
            self.assertIn(TITLE, first)  # the hook runner may discard this output (timeout): nothing else depends on it
            again = uw.on_prompt(self.project, "claude", "s1", "진행상황 알려줘", now=NOW)
        self.assertIn(TITLE, again)
        self.assertIn("set_session_title", again)
        with mock.patch.object(uw, "_current_title", return_value=TITLE):
            self.assertEqual("", uw.on_prompt(self.project, "claude", "s1", "다음", now=NOW))
        self.assertTrue(_registry(self.project)["claude"][0]["converged"])
        with mock.patch.object(uw, "_current_title", side_effect=AssertionError("converged desk must not read")):
            self.assertEqual("", uw.on_prompt(self.project, "claude", "s1", "다음", now=NOW))

    def test_unknown_readback_is_never_a_match_and_is_capped(self):
        with mock.patch.object(uw, "_current_title", return_value=None):
            lines = [uw.on_prompt(self.project, "claude", "s1", DECLARE if i == 0 else "x", now=NOW) for i in range(6)]
        self.assertEqual(uw.MAX_EMITS, sum(1 for line in lines if TITLE in line))
        entry = _registry(self.project)["claude"][0]
        self.assertFalse(entry.get("converged"))
        self.assertEqual("BLOCKED", entry.get("title_state"))

    def test_session_that_is_not_a_desk_gets_nothing_and_writes_nothing(self):
        with mock.patch.object(uw, "_current_title", side_effect=AssertionError("no readback for a non-desk")):
            self.assertEqual("", uw.on_prompt(self.project, "claude", "worker-1", "작업 진행", now=NOW))
        self.assertFalse((self.project / ".coord" / "presence" / "user_windows.json").exists())

    def test_codex_mismatch_reissues_and_match_converges(self):
        with mock.patch.object(uw, "_codex_names", return_value=[]), \
                mock.patch.object(uw, "_current_title", return_value="old name"):
            uw.on_prompt(self.project, "codex", "t1", DECLARE, now=NOW)
            self.assertIn("thread rename", uw.on_prompt(self.project, "codex", "t1", "x", now=NOW))
        with mock.patch.object(uw, "_current_title", return_value=TITLE):
            self.assertEqual("", uw.on_prompt(self.project, "codex", "t1", "x", now=NOW))

    def test_agy_mismatch_rewrites_its_store_without_an_env_flag(self):
        with mock.patch.object(uw, "_current_title", return_value="자동 프로세스 마스터 계획 스케줄 수립"), \
                mock.patch.object(uw, "rename_agy_status", return_value="RENAMED") as write, \
                mock.patch.dict("os.environ", {}, clear=False):
            uw.os.environ.pop(uw.AGY_WRITE_ENV, None)
            uw.on_prompt(self.project, "antigravity", "c0", DECLARE, now=NOW)
            uw.on_prompt(self.project, "antigravity", "c0", "x", now=NOW)
        self.assertEqual(2, write.call_count)
        self.assertEqual(TITLE, write.call_args[0][1])

    def test_parallel_prompts_never_exceed_the_cap(self):
        with mock.patch.object(uw, "_current_title", return_value=None):
            uw.on_prompt(self.project, "claude", "s1", DECLARE, now=NOW)
            out, start = [], threading.Barrier(8)

            def run():
                start.wait()
                out.append(uw.on_prompt(self.project, "claude", "s1", "x", now=NOW))

            workers = [threading.Thread(target=run) for _ in range(8)]
            for w in workers:
                w.start()
            for w in workers:
                w.join()
        self.assertEqual(uw.MAX_EMITS - 1, sum(1 for line in out if TITLE in line))


class ClaudeReadback(Base):
    def _session_file(self, cli_id, title, name="local_a.json"):
        folder = self.root / "sessions" / "acct" / "org"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(json.dumps({"cliSessionId": cli_id, "title": title}), encoding="utf-8")

    def test_reads_title_of_exact_cli_session_only(self):
        self._session_file("8d25ac09", TITLE)
        self._session_file("other", "다른 창", name="local_b.json")
        self.assertEqual(TITLE, uw._claude_title("8d25ac09", root=self.root / "sessions"))
        self.assertIsNone(uw._claude_title("missing", root=self.root / "sessions"))

    def test_malformed_or_absent_store_is_unknown(self):
        folder = self.root / "sessions" / "acct" / "org"
        folder.mkdir(parents=True)
        (folder / "local_bad.json").write_text("{not json", encoding="utf-8")
        self.assertIsNone(uw._claude_title("8d25ac09", root=self.root / "sessions"))
        self.assertIsNone(uw._claude_title("8d25ac09", root=self.root / "nowhere"))


class AgyRename(Base):
    def _store(self, cid="c0c36b04-681e-4025-98a7-df44b8eda13b", title="자동 프로세스 마스터 계획 스케줄 수립"):
        base = self.root / "agy"
        (base / "annotations").mkdir(parents=True)
        db = base / "conversation_summaries.db"
        con = sqlite3.connect(db)
        con.execute("create table conversation_summaries (conversation_id text, title text, preview text)")
        con.execute("insert into conversation_summaries values (?, ?, ?)", (cid, title, title))
        con.commit()
        con.close()
        ann = base / "annotations" / f"{cid}.pbtxt"
        ann.write_text(f'title:"{title}"  last_user_view_time:{{seconds:1792117829  nanos:286000000}}\n',
                       encoding="utf-8")
        return cid, db, ann

    def _row(self, db, cid):
        con = sqlite3.connect(db)
        try:
            return con.execute("select title, preview from conversation_summaries where conversation_id=?",
                               (cid,)).fetchone()
        finally:
            con.close()

    def test_backs_up_both_then_title_preview_annotation_agree(self):
        cid, db, ann = self._store()
        backup = self.root / "backup"
        status = uw.rename_agy_status(cid, TITLE, db=db, annotations_dir=ann.parent, backup_dir=backup)
        self.assertEqual("RENAMED", status)
        self.assertEqual((TITLE, TITLE), self._row(db, cid))
        text = ann.read_text(encoding="utf-8")
        self.assertIn(f'title:"{TITLE}"', text)
        self.assertIn("last_user_view_time", text)  # the rest of the annotation is kept
        self.assertEqual(1, len(list(backup.glob("conversation_summaries_*.db"))))
        saved = list(backup.glob(f"{cid}_*.pbtxt"))
        self.assertEqual(1, len(saved))
        self.assertIn("자동 프로세스", saved[0].read_text(encoding="utf-8"))
        old = sqlite3.connect(next(backup.glob("conversation_summaries_*.db")))
        self.assertEqual("자동 프로세스 마스터 계획 스케줄 수립", old.execute("select title from conversation_summaries").fetchone()[0])
        old.close()

    def test_quotes_and_backslashes_are_escaped_and_read_back_equal(self):
        cid, db, ann = self._store()
        odd = 'a "b" \\c'
        self.assertEqual("RENAMED", uw.rename_agy_status(cid, odd, db=db, annotations_dir=ann.parent,
                                                         backup_dir=self.root / "b"))
        self.assertEqual(odd, uw._agy_annotation_title(ann))
        self.assertEqual("RENAMED", uw.rename_agy_status(cid, TITLE, db=db, annotations_dir=ann.parent,
                                                         backup_dir=self.root / "b"))
        self.assertEqual(TITLE, uw._agy_annotation_title(ann))

    def test_invalid_conversation_id_writes_nothing(self):
        cid, db, ann = self._store()
        for bad in ("../x", "c0; drop table", "", "a" * 200):
            self.assertEqual("INVALID_ID", uw.rename_agy_status(bad, TITLE, db=db, annotations_dir=ann.parent,
                                                                backup_dir=self.root / "b"))
        self.assertNotEqual(TITLE, self._row(db, cid)[0])
        self.assertFalse((self.root / "b").exists())

    def test_failed_annotation_replace_is_partial_not_success(self):
        cid, db, ann = self._store()
        with mock.patch.object(uw.os, "replace", side_effect=OSError("locked")):
            status = uw.rename_agy_status(cid, TITLE, db=db, annotations_dir=ann.parent, backup_dir=self.root / "b")
        self.assertEqual("PARTIAL", status)
        self.assertFalse(uw.rename_agy(cid, TITLE, db=self.root / "missing.db", annotations_dir=ann.parent))

    def test_writer_holding_the_db_past_the_timeout_leaves_annotation_untouched(self):
        cid, db, ann = self._store()
        before = ann.read_text(encoding="utf-8")
        holder = sqlite3.connect(db, timeout=0, check_same_thread=False)
        holder.execute("BEGIN IMMEDIATE")
        try:
            status = uw.rename_agy_status(cid, TITLE, db=db, annotations_dir=ann.parent,
                                          backup_dir=self.root / "b", timeout=0.2)
        finally:
            holder.rollback()
            holder.close()
        self.assertEqual("DB_LOCKED", status)
        self.assertEqual(before, ann.read_text(encoding="utf-8"))

    def test_concurrent_writer_released_in_time_still_renames(self):
        cid, db, ann = self._store()
        holder = sqlite3.connect(db, timeout=0, check_same_thread=False)
        holder.execute("BEGIN IMMEDIATE")
        holder.execute("update conversation_summaries set preview='app write' where conversation_id=?", (cid,))

        def release():
            time.sleep(0.3)
            holder.commit()
            holder.close()

        t = threading.Thread(target=release)
        t.start()
        status = uw.rename_agy_status(cid, TITLE, db=db, annotations_dir=ann.parent, backup_dir=self.root / "b",
                                      timeout=5)
        t.join()
        self.assertEqual("RENAMED", status)
        self.assertEqual((TITLE, TITLE), self._row(db, cid))

    def test_missing_row_is_not_found(self):
        _cid, db, ann = self._store()
        self.assertEqual("NOT_FOUND", uw.rename_agy_status("unknown-id", TITLE, db=db, annotations_dir=ann.parent,
                                                           backup_dir=self.root / "b"))


class PartialConvergence(unittest.TestCase):
    """Codex REVISE relay_f3895ddb frozen invariants (test SHA 46d04bcd), bodies unchanged; module import adapted."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / '.gemini/antigravity/conversation_summaries.db'
        self.db.parent.mkdir(parents=True)
        self.ann = self.db.parent / 'annotations'
        self.thread = '11111111-1111-4111-8111-111111111111'
        with closing(sqlite3.connect(self.db)) as con:
            con.execute('CREATE TABLE conversation_summaries (conversation_id TEXT, title TEXT, preview TEXT)')
            con.execute('INSERT INTO conversation_summaries VALUES (?, ?, ?)', (self.thread, 'Old', 'Old'))
            con.commit()
        self.claimed = uw.claim(self.root, 'antigravity', self.thread, now=datetime(2026, 10, 16), current='Old')['title']

    def test_missing_annotation_store_never_reports_renamed(self):
        status = uw.rename_agy_status(self.thread, self.claimed, db=self.db,
                                      annotations_dir=self.ann, backup_dir=self.root / 'backup')
        if status == 'RENAMED':
            annotation = self.ann / f'{self.thread}.pbtxt'
            self.assertTrue(annotation.is_file(), 'RENAMED needs an actual annotation readback')
            self.assertEqual(self.claimed, uw._agy_annotation_title(annotation))

    def test_failed_annotation_replace_does_not_become_permanently_converged(self):
        self.ann.mkdir()
        annotation = self.ann / f'{self.thread}.pbtxt'
        annotation.write_text('title:"Old"\n', encoding='utf-8')
        original_replace = uw.os.replace

        def denied_annotation(source, dest):
            if Path(dest) == annotation:
                raise PermissionError('disposable annotation failure')
            return original_replace(source, dest)

        with mock.patch.object(uw.os, 'replace', side_effect=denied_annotation):
            status = uw.rename_agy_status(self.thread, self.claimed, db=self.db,
                                          annotations_dir=self.ann, backup_dir=self.root / 'backup')
        self.assertEqual('PARTIAL', status)
        self.assertEqual('title:"Old"\n', annotation.read_text(encoding='utf-8'))

        with mock.patch.object(uw.Path, 'home', return_value=self.root):
            uw.reconcile(self.root, 'antigravity', self.thread)
        record = json.loads((self.root / '.coord/presence/user_windows.json').read_text(encoding='utf-8'))
        entry = next(e for e in record['antigravity'] if e['thread'] == self.thread)
        if entry.get('converged', False):
            self.assertEqual(self.claimed, uw._agy_annotation_title(annotation),
                             'DB title alone must not suppress repair while annotation still differs')

    def test_disagreeing_stores_read_as_unknown(self):
        self.ann.mkdir()
        (self.ann / f'{self.thread}.pbtxt').write_text('title:"Other"\n', encoding='utf-8')
        self.assertIsNone(uw._agy_title(self.thread, base=self.db.parent))
        (self.ann / f'{self.thread}.pbtxt').write_text('title:"Old"\n', encoding='utf-8')
        self.assertEqual('Old', uw._agy_title(self.thread, base=self.db.parent))


if __name__ == "__main__":
    unittest.main()
