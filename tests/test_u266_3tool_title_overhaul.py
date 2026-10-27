"""U266 fixed acceptance: 3-tool window title generation & auto-conversion overhaul (4 reproducing tests)."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from v7_harness.coord import desk_title as dt
from v7_harness.coord import user_window as uw

NOW = datetime(2026, 10, 27, 8, 20, 0)
PREFIX = "[261027-1]"
LEGACY_PREFIX = "[사용자 대화창구-261027-1]"
SHARED = "메인컨트롤UX·3도구병렬"
REAL_OPENING_PROMPT = (
    "## 이제부터 이대화창이 사용자 대상 대화창구이다. 대화창 제목을 이제부터 진행해야 하는 프로세스가 정해지면 자동변환하라.\n"
    "- 출석체크하고, 이전에 구현했던 프로세스와 이제부터 진행해야하는 마스터 계획 스케줄을 살펴보고, 내게 업무진행 계획을 보고 후, 무승인 논스톱 절차를 진행하라. 사용자의 모든 승인은 구하지 않음을 승인한다.\n"
    "- 올라마 CLI와 Haiku 5.5의 높은 사용빈도로 3대 도구의 티키타카 무승인 논스톱-**병렬**-협업 오케스트레이션을 진행하라."
)


def _entry(project: Path, tool: str, thread: str) -> dict:
    record = json.loads((project / ".coord" / "presence" / "user_windows.json").read_text(encoding="utf-8"))
    return next(e for e in record[tool] if e["thread"] == thread)


class U266ThreeToolTitleOverhaulTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.p = Path(self._tmp.name)
        (self.p / ".coord").mkdir()

    def agree(self, topic: str = SHARED):
        phases = [{"phase_id": "U266", "title": topic, "state": "ACTIVE"}]
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

    def declare(self, tool: str, thread: str, prompt: str = REAL_OPENING_PROMPT, current: str | None = None) -> str:
        with mock.patch.object(uw, "_codex_names", return_value=[]), \
                mock.patch.object(uw, "rename_agy_status", return_value="RENAMED"), \
                mock.patch.object(uw, "_current_title", return_value=current):
            return uw.on_prompt(self.p, tool, thread, prompt, now=NOW)

    def test_1_meta_boilerplate_prompt_never_pollutes_entry_topic(self):
        """Reproduces Bug 1 (user_window.py:493): standard opening prompt must not set topic='대화창 제목을 이제부터' or '출석체크하고'."""
        self.assertIsNone(uw._topic_from_text(REAL_OPENING_PROMPT))
        self.agree(SHARED)
        for tool, tid in (("claude", "s1"), ("codex", "c1"), ("antigravity", "a1")):
            line = self.declare(tool, tid, REAL_OPENING_PROMPT)
            entry = _entry(self.p, tool, tid)
            self.assertNotIn("topic", entry)
            self.assertIn(f"{PREFIX} {SHARED}", line)
            self.assertNotIn("대화창 제목을 이제부터", line)
            self.assertNotIn("출석체크하고", line)

    def test_2_legacy_prefix_self_named_window_preserves_topic_and_normalizes_to_short_prefix(self):
        """Reproduces Bug 2 (desk_title.py:153, Claude 7c54950f): '[사용자 대화창구-261027-1] P1경보정리·병렬협업' -> '[261027-1] P1경보정리·병렬협업'."""
        self.agree(SHARED)
        self.declare("claude", "s1", REAL_OPENING_PROMPT)
        # Simulate polluted legacy state where topic was '대화창 제목을 이제부터' and Claude set '[사용자 대화창구-261027-1] P1경보정리·병렬협업'
        uw._entry_change(self.p, "claude", "s1", lambda e: e.update(
            topic="대화창 제목을 이제부터", desired_title=f"{PREFIX} 대화창 제목을 이제부터"))
        res = self.check("claude", "s1", session_title=f"{LEGACY_PREFIX} P1경보정리·병렬협업")
        self.assertEqual("PENDING", res["state"])
        self.assertEqual(f"{PREFIX} P1경보정리·병렬협업", res["title"])
        self.assertEqual("P1경보정리·병렬협업", _entry(self.p, "claude", "s1")["topic"])

    def test_3_tool_updating_process_topic_mid_session_is_adopted_across_3_tools(self):
        """Reproduces Bug 3 (Codex 01a17a55 & Claude 4116399c): when a tool updates its own '[YYMMDD-N] <new_process>', adopt it."""
        self.agree(SHARED)
        self.declare("codex", "c1", REAL_OPENING_PROMPT)
        uw._entry_change(self.p, "codex", "c1", lambda e: e.update(
            topic="출석체크하고", desired_title=f"{PREFIX} 출석체크하고"))
        with mock.patch.object(uw, "_current_title", return_value=f"{PREFIX} 병렬협업·독립검증"):
            res = self.check("codex", "c1")
        self.assertEqual("CONVERGED", res["state"])
        self.assertEqual("병렬협업·독립검증", _entry(self.p, "codex", "c1")["topic"])
        self.assertEqual(f"{PREFIX} 병렬협업·독립검증", _entry(self.p, "codex", "c1")["desired_title"])

    def test_4_claude_sessions_root_discovers_windows_msix_claude_data_store(self):
        """Reproduces Bug 4 (user_window.py:200): Windows MSIX %LOCALAPPDATA%/Claude-Data/claude_*/claude-code-sessions lookup."""
        fake_roaming = self.p / "Roaming"
        fake_local = self.p / "Local"
        msix_sessions = fake_local / "Claude-Data" / "claude_pzs8sxrjxfjjc" / "claude-code-sessions" / "u1" / "o1"
        msix_sessions.mkdir(parents=True)
        (msix_sessions / "local_abc.json").write_text(
            json.dumps({"cliSessionId": "s-msix", "title": f"{PREFIX} P1경보정리·병렬협업"}, ensure_ascii=False),
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, {"APPDATA": str(fake_roaming), "LOCALAPPDATA": str(fake_local)}):
            self.assertEqual(f"{PREFIX} P1경보정리·병렬협업", uw._claude_title("s-msix"))


if __name__ == "__main__":
    unittest.main()
