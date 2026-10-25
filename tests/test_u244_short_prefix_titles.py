"""U244 fixed acceptance: [YYMMDD-N] <프로세스명> short prefix automatic conversion across all 3 tools."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from v7_harness.coord import desk_title as dt
from v7_harness.coord import user_window as uw

NOW = datetime(2026, 10, 26, 4, 30, 0)
SHORT_PREFIX = "[261026-1]"
LEGACY_PREFIX = "[사용자 대화창구-261026-1]"
TOPIC = "메인컨트롤UX·3도구병렬"
DECLARE = "지금부터 여기가 사용자 대상 대화창구이다."


def _entry(project: Path, tool: str, thread: str) -> dict:
    record = json.loads((project / ".coord" / "presence" / "user_windows.json").read_text(encoding="utf-8"))
    return next(e for e in record[tool] if e["thread"] == thread)


class U244ShortPrefixTitlesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.p = Path(self._tmp.name)
        (self.p / ".coord").mkdir()

    def agree(self, topic: str = TOPIC):
        phases = [{"phase_id": "U244", "title": topic, "state": "ACTIVE"}]
        digest = hashlib.sha256(
            json.dumps(phases, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
        data = {
            "phases": phases,
            "desk_title": {"topic": topic, "agreed_by": sorted(dt.TOOLS), "schedule_sha256": digest},
        }
        (self.p / ".coord" / "master_schedule.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def event(self, tool: str, thread: str, **fields) -> dict:
        return dict(hook_event_name="UserPromptSubmit", session_id=thread, **fields)

    def check(self, tool: str, thread: str, **fields) -> dict:
        return dt.reconcile_title(self.p, tool, thread, self.event(tool, thread, **fields))

    def declare(self, tool: str, thread: str, prompt: str = DECLARE, current: str | None = None) -> str:
        with mock.patch.object(uw, "_codex_names", return_value=[]), \
                mock.patch.object(uw, "rename_agy_status", return_value="RENAMED"), \
                mock.patch.object(uw, "_current_title", return_value=current):
            return uw.on_prompt(self.p, tool, thread, prompt, now=NOW)

    def test_new_declarations_use_short_yymmdd_n_prefix_across_all_three_tools(self):
        self.agree(TOPIC)
        for tool, tid in (("codex", "c1"), ("claude", "s1"), ("antigravity", "a1")):
            line = self.declare(tool, tid, DECLARE)
            self.assertIn(f"{SHORT_PREFIX} {TOPIC}", line)
            self.assertNotIn("사용자 대화창구-", line)
            self.assertEqual(SHORT_PREFIX, _entry(self.p, tool, tid)["title"])

    def test_legacy_prefix_automatically_migrates_to_short_prefix(self):
        self.agree(TOPIC)
        uw.claim(self.p, "codex", "c1", now=NOW, current=f"{LEGACY_PREFIX} 이전 제목")
        self.assertEqual(SHORT_PREFIX, _entry(self.p, "codex", "c1")["title"])
        uw._entry_change(self.p, "codex", "c1", lambda e: e.update(title=LEGACY_PREFIX))
        with mock.patch.object(uw, "_current_title", return_value=f"{LEGACY_PREFIX} {TOPIC}"):
            res = self.check("codex", "c1")
        self.assertEqual(f"{SHORT_PREFIX} {TOPIC}", res["title"])
        self.assertEqual(SHORT_PREFIX, _entry(self.p, "codex", "c1")["title"])

    def test_short_and_legacy_title_mentions_are_not_declarations(self):
        self.assertFalse(uw.is_declaration("[261026-1] 대화창구 작업 확인"))
        self.assertFalse(uw.is_declaration("[사용자 대화창구-261026-1] 대화창구 작업 확인"))


if __name__ == "__main__":
    unittest.main()
