"""U237 fixed acceptance: user-desk titles converge on the full title, per window, in all three tools.

Receipts (2026-10-25, 윤겸스 report): Codex thread 01a17325 was marked CONVERGED while its name was only the prefix
(U207 `_shows` compared the prefix); Claude desks 46c52914/c3a04094 went BLOCKED because the desktop-app session
store moved (readback always UNKNOWN) although the transcript recorded the renamed `custom-title`; every window got
the same project-wide topic. Fake stores only: no real Codex, Claude or Antigravity file is read or written.
"""

import hashlib
import json
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from v7_harness.coord import desk_title as dt
from v7_harness.coord import user_window as uw

NOW = datetime(2026, 10, 25, 9, 0, 0)
PREFIX = "[사용자 대화창구-261025-1]"
SHARED = "창구·호출기록 개선"
DECLARE = "이제부터 이대화창이 사용자 대상 대화창구이다."


def _registry(project):
    return json.loads((project / ".coord" / "presence" / "user_windows.json").read_text(encoding="utf-8"))


def _entry(project, tool, thread):
    return next(e for e in _registry(project)[tool] if e["thread"] == thread)


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.p = Path(self._tmp.name)
        (self.p / ".coord").mkdir()

    def agree(self, topic=SHARED):
        phases = [{"phase_id": "U237", "title": "desk titles", "state": "ACTIVE"}]
        digest = hashlib.sha256(json.dumps(phases, sort_keys=True, separators=(",", ":"),
                                           ensure_ascii=False).encode()).hexdigest()
        data = dict(phases=phases, desk_title=dict(topic=topic, agreed_by=sorted(dt.TOOLS), schedule_sha256=digest))
        (self.p / ".coord" / "master_schedule.json").write_text(json.dumps(data, ensure_ascii=False),
                                                               encoding="utf-8")

    def event(self, tool, thread, **fields):
        return dict(hook_event_name="UserPromptSubmit", session_id=thread, **fields)

    def check(self, tool, thread, **fields):
        return dt.reconcile_title(self.p, tool, thread, self.event(tool, thread, **fields))

    def declare(self, tool, thread, prompt=DECLARE, current=None):
        with mock.patch.object(uw, "_codex_names", return_value=[]), \
                mock.patch.object(uw, "rename_agy_status", return_value="RENAMED"), \
                mock.patch.object(uw, "_current_title", return_value=current):
            return uw.on_prompt(self.p, tool, thread, prompt, now=NOW)


class CodexFullTitle(Base):
    def test_prefix_only_name_is_not_converged(self):
        self.agree()
        uw.claim(self.p, "codex", "t1", current=PREFIX)
        self.assertFalse(uw._shows(PREFIX, f"{PREFIX} {SHARED}"))
        with mock.patch.object(uw, "_current_title", return_value=PREFIX):
            got = self.check("codex", "t1")
            self.assertEqual(f"{PREFIX} {SHARED}", got["title"])
            self.assertIn(f"{PREFIX} {SHARED}", got["instruction"])
            # a later non-declaration prompt (relay wake or human) never converges on the prefix
            self.assertEqual("", uw.on_prompt(self.p, "codex", "t1", "다음 진행", now=NOW))
        entry = _entry(self.p, "codex", "t1")
        self.assertFalse(entry.get("converged"))
        self.assertNotEqual("CONVERGED", entry.get("title_state"))
        with mock.patch.object(uw, "_current_title", return_value=f"{PREFIX} {SHARED}"):
            self.assertEqual("CONVERGED", self.check("codex", "t1")["state"])


class ClaudeReadback(Base):
    def transcript(self, *titles, session="s1"):
        path = self.p / "t.jsonl"
        lines = [json.dumps({"type": "user", "message": {"content": "x"}, "sessionId": session})]
        for title in titles:
            lines.append(json.dumps({"type": "custom-title", "customTitle": title, "sessionId": session},
                                    ensure_ascii=False))
        lines.append(json.dumps({"type": "custom-title", "customTitle": "남의 창", "sessionId": "other"},
                                ensure_ascii=False))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_transcript_custom_title_is_the_readback(self):
        path = self.transcript("새 대화", PREFIX)
        self.assertEqual(PREFIX, uw._claude_title("s1", transcript=path))
        self.assertIsNone(uw._claude_title("s1", transcript=self.p / "missing.jsonl"))
        self.assertIsNone(uw._claude_title("nobody", transcript=path))

    def test_hook_converges_from_transcript(self):
        uw.claim(self.p, "claude", "s1", current=PREFIX)
        path = self.transcript(PREFIX)
        self.assertEqual("CONVERGED", self.check("claude", "s1", transcript_path=str(path))["state"])

    def test_unknown_readback_never_blocks(self):
        uw.claim(self.p, "claude", "s1", current=PREFIX)
        states = [self.check("claude", "s1")["state"] for _ in range(6)]
        self.assertNotIn("BLOCKED", states)
        entry = _entry(self.p, "claude", "s1")
        self.assertLessEqual(entry["native_emits"], dt.MAX_NATIVE_EMITS)
        self.assertEqual("UNVERIFIED", entry["title_state"])
        # a known wrong title after the budget is a real block
        self.assertEqual("BLOCKED", self.check("claude", "s1", session_title="새 대화")["state"])

    def test_explicit_instruction_is_the_repair_path(self):
        uw.claim(self.p, "claude", "s1", current=PREFIX)
        first = self.check("claude", "s1", session_title="새 대화")
        self.assertEqual(PREFIX, first["title"])
        self.assertNotIn("set_session_title", first["instruction"])
        second = self.check("claude", "s1", session_title="새 대화")
        self.assertIn("set_session_title", second["instruction"])
        self.assertIn(PREFIX, second["instruction"])

    def test_old_blocked_entry_gets_a_fresh_budget(self):
        uw.claim(self.p, "claude", "s1", current=PREFIX)
        uw._entry_change(self.p, "claude", "s1", lambda e: e.update(
            adapter_version="U229_NATIVE1", desired_title=PREFIX, native_emits=3, title_state="BLOCKED"))
        self.assertEqual(PREFIX, self.check("claude", "s1", session_title="새 대화")["title"])


class PerWindowTopic(Base):
    def test_topic_from_declaration(self):
        self.assertIsNone(uw._topic_from_text(DECLARE))
        self.assertEqual("로또 분석기 검증을 진행한다", uw._topic_from_text(DECLARE + " 로또 분석기 검증을 진행한다."))
        got = uw._topic_from_text("여기 사용자 대화창구이다. 창구 호출기록 개선과 모델 고정 착지를 끝낸다")
        self.assertEqual("창구 호출기록 개선과 모델", got)
        long_word = uw._topic_from_text(DECLARE + " https://x.y/z " + "가" * 30)
        self.assertTrue(long_word and len(long_word) <= dt.MAX_TOPIC_CHARS and "http" not in long_word)

    def test_each_window_keeps_its_own_topic_over_the_shared_one(self):
        self.agree()
        self.declare("codex", "c1", DECLARE + " 로또 분석기 검증")
        self.declare("antigravity", "a1", DECLARE + " 감사 보고서 정리")
        self.declare("claude", "s1")  # no own topic: falls back to the shared one
        with mock.patch.object(uw, "_current_title", return_value="old"), \
                mock.patch.object(uw, "rename_agy_status", return_value="RENAMED") as write:
            codex = self.check("codex", "c1")["title"]
            agy = self.check("antigravity", "a1")
        self.assertTrue(codex.endswith(" 로또 분석기 검증"))
        self.assertTrue(agy["title"].endswith(" 감사 보고서 정리"))
        self.assertEqual(agy["title"], write.call_args[0][1])
        self.assertTrue(self.check("claude", "s1", session_title="old")["title"].endswith(" " + SHARED))
        # another window's declaration never changes this window's topic
        self.declare("codex", "c2", DECLARE + " 다른 작업")
        self.assertEqual("로또 분석기 검증", _entry(self.p, "codex", "c1")["topic"])

    def test_window_named_by_itself_is_adopted(self):
        self.agree()
        uw.claim(self.p, "claude", "s1", current=PREFIX)
        own = f"{PREFIX} 모델고정·호출기록 착지"
        self.assertEqual("CONVERGED", self.check("claude", "s1", session_title=own)["state"])
        self.assertEqual("모델고정·호출기록 착지", _entry(self.p, "claude", "s1")["topic"])
        self.assertEqual("CONVERGED", self.check("claude", "s1", session_title=own)["state"])

    def test_invalid_self_name_is_not_adopted(self):
        self.agree()
        uw.claim(self.p, "claude", "s1", current=PREFIX)
        bad = f"{PREFIX} " + "가" * 20
        self.assertEqual(f"{PREFIX} {SHARED}", self.check("claude", "s1", session_title=bad)["title"])
        self.assertNotIn("topic", _entry(self.p, "claude", "s1"))


class ParallelRegistry(Base):
    def test_parallel_hooks_keep_the_budget_and_a_valid_registry(self):
        uw.claim(self.p, "claude", "s1", current=PREFIX)
        start = threading.Barrier(8)

        def run():
            start.wait()
            self.check("claude", "s1", session_title="새 대화")

        workers = [threading.Thread(target=run) for _ in range(8)]
        for w in workers:
            w.start()
        for w in workers:
            w.join()
        self.assertLessEqual(_entry(self.p, "claude", "s1")["native_emits"], dt.MAX_NATIVE_EMITS)

    def test_parallel_declarations_keep_every_window_and_topic(self):
        start = threading.Barrier(6)
        jobs = [(tool, f"{tool}-{i}", f"{DECLARE} 작업{i}") for tool in sorted(dt.TOOLS) for i in (1, 2)]

        def run(job):
            start.wait()
            uw.on_prompt(self.p, job[0], job[1], job[2], now=NOW, current="old")

        with mock.patch.object(uw, "_codex_names", return_value=[]), \
                mock.patch.object(uw, "rename_agy_status", return_value="RENAMED"), \
                mock.patch.object(uw, "_current_title", return_value="old"):
            workers = [threading.Thread(target=run, args=(job,)) for job in jobs]
            for w in workers:
                w.start()
            for w in workers:
                w.join()
        for tool, thread, prompt in jobs:
            self.assertEqual(prompt.rsplit(" ", 1)[1], _entry(self.p, tool, thread)["topic"])


if __name__ == "__main__":
    unittest.main()
