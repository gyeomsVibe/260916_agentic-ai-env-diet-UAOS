"""U243 fixed acceptance: dynamic process topic transition and stale desired_title guard across all 3 tools."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from v7_harness.coord import desk_title as dt
from v7_harness.coord import user_window as uw

NOW = datetime(2026, 10, 26, 3, 50, 0)
PREFIX = "[사용자 대화창구-261026-1]"
OLD_TOPIC = "창구·호출기록 개선"
NEW_TOPIC = "메인컨트롤UX·3도구병렬"
DECLARE = "지금부터 여기가 사용자 대상 대화창구이다."


def _entry(project: Path, tool: str, thread: str) -> dict:
    record = json.loads((project / ".coord" / "presence" / "user_windows.json").read_text(encoding="utf-8"))
    return next(e for e in record[tool] if e["thread"] == thread)


class U243DynamicProcessTitlesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.p = Path(self._tmp.name)
        (self.p / ".coord").mkdir()

    def agree(self, topic: str):
        phases = [{"phase_id": "U243", "title": topic, "state": "ACTIVE"}]
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

    def test_stale_desired_title_is_not_falsely_adopted_as_own_topic(self):
        self.agree(OLD_TOPIC)
        self.declare("antigravity", "a1", DECLARE)
        with mock.patch.object(uw, "_current_title", return_value=f"{PREFIX} {OLD_TOPIC}"), \
                mock.patch.object(uw, "rename_agy_status", return_value="RENAMED"):
            self.check("antigravity", "a1")
        (self.p / ".coord" / "master_schedule.json").write_text("{}", encoding="utf-8")
        with mock.patch.object(uw, "_current_title", return_value=f"{PREFIX} {OLD_TOPIC}"):
            self.check("antigravity", "a1")
        self.assertNotIn("topic", _entry(self.p, "antigravity", "a1"))

    def test_process_change_dynamically_updates_all_three_tools(self):
        self.agree(OLD_TOPIC)
        self.declare("codex", "c1", DECLARE + " 초기 선언 작업")
        self.declare("antigravity", "a1", DECLARE + " 이전 프로세스")
        self.declare("claude", "s1", DECLARE)
        self.agree(NEW_TOPIC)
        with mock.patch.object(uw, "_current_title", return_value="old"), \
                mock.patch.object(uw, "rename_agy_status", return_value="RENAMED"):
            c_res = self.check("codex", "c1")
            a_res = self.check("antigravity", "a1")
            s_res = self.check("claude", "s1", session_title="old")
        self.assertEqual(f"{PREFIX} {NEW_TOPIC}", c_res["title"])
        self.assertEqual(f"{PREFIX} {NEW_TOPIC}", a_res["title"])
        self.assertEqual(f"{PREFIX} {NEW_TOPIC}", s_res["title"])
        self.assertEqual(NEW_TOPIC, _entry(self.p, "codex", "c1")["topic"])
        self.assertEqual(NEW_TOPIC, _entry(self.p, "antigravity", "a1")["topic"])
        self.assertEqual(NEW_TOPIC, _entry(self.p, "claude", "s1")["topic"])


if __name__ == "__main__":
    unittest.main()
