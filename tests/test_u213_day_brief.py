"""U213: the day briefing 윤겸스 sees when a tool opens on a UAOS project (version, progress, desk, next step).

Receipt 2026-10-18: opening the three tools told 윤겸스 nothing about where the work stood, so each day began with a
typed "진행상황을 브리핑해라 / 현재 UAOS-RSI 버전은? / 다음 수행계획은?".
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from v7_harness.coord import day_brief as db  # noqa: E402


def _phase(pid: str, state: str, owner: str = "codex") -> dict:
    return {"phase_id": pid, "state": state, "owner_tool": owner}


def _project(tmp: Path, phases: list[dict] | None = None) -> Path:
    (tmp / ".coord").mkdir(parents=True, exist_ok=True)
    (tmp / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
    if phases is not None:
        (tmp / ".coord" / "master_schedule.json").write_text(json.dumps({"phases": phases}), encoding="utf-8")
    return tmp


def _brief_once_worker(args: tuple[str, str]) -> bool:
    return db.brief_once(Path(args[0]), "claude", args[1])


def _hook(project: Path, payload: dict, say: str = "brief", tool: str = "claude") -> dict:
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    done = subprocess.run([sys.executable, "-m", "v7_harness.cli", "coord", "presence", "--project", str(project),
                           "--tool", tool, "--state", "ACTIVE", "--ttl", "60", "--from-hook", "--say", say],
                          input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8",
                          cwd=str(ROOT), env=env, timeout=60)
    assert done.returncode == 0, done.stderr
    out = done.stdout.strip()
    try:
        return json.loads(out) if out.startswith("{") else {"plain": out}
    except json.JSONDecodeError:
        return {"plain": out}


class VersionAndMerge(unittest.TestCase):
    def test_runtime_version_short_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / ".uaos" / "runtime"
            runtime.mkdir(parents=True)
            (runtime / "current.json").write_text(json.dumps({"version": "0.3.0-3354d2136a7b"}), encoding="utf-8")
            self.assertEqual(db.runtime_version(Path(tmp)), "0.3.0-3354d21")

    def test_runtime_version_missing_is_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(db.runtime_version(Path(tmp)), "미확인")

    def test_last_merge_names_pr_branch_and_day(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            git = ["git", "-C", tmp, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
            subprocess.run(["git", "init", "-q", "-b", "main", tmp], check=True)
            subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "base"], check=True)
            subprocess.run(git + ["checkout", "-q", "-b", "feature"], check=True)
            subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "work"], check=True)
            subprocess.run(git + ["checkout", "-q", "main"], check=True)
            subprocess.run(git + ["merge", "-q", "--no-ff", "feature", "-m",
                                  "Merge pull request #173 from gyeomsVibe/claude/u212-native-verdict-gate"], check=True)
            line = db.last_merge(Path(tmp))
            self.assertTrue(line.startswith("#173 u212-native-verdict-gate ("), line)

    def test_last_merge_outside_git_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(db.last_merge(Path(tmp)), "")


class ProgressAndNext(unittest.TestCase):
    PHASES = [_phase("A", "DONE"), _phase("B", "DONE_SCOPED"), _phase("C", "BLOCKED"), _phase("D", "BLOCKED", "claude"),
              _phase("E", "PARKED"), _phase("F", "READY", "claude")]

    def test_progress_counts_every_state_once(self) -> None:
        self.assertEqual(db.schedule_progress(self.PHASES), "일정 2/6 완료 · 진행 1 · 막힘 2 · 보류 1")
        self.assertEqual(db.schedule_progress(None), "일정 미확인")

    def test_next_words_per_state(self) -> None:
        blocked = db.blocked_cards(self.PHASES)
        self.assertEqual(blocked, ["C(codex)", "D(claude)"])
        self.assertEqual(db.next_words({"state": "NEXT", "card": "F"}, blocked), "F 착수 (이 도구 차례)")
        self.assertEqual(db.next_words({"state": "HANDOFF", "card": "F", "owner": "codex"}, blocked), "F — Codex 차례")
        self.assertEqual(db.next_words({"state": "DONE"}, []), "일정 완료 — 새 카드 없음")
        self.assertEqual(db.next_words({"state": "HUMAN", "items": ["merge #9"]}, []), "사람 확인 필요: merge #9")
        self.assertEqual(db.next_words({"state": "WAIT", "cards": ["C", "D"]}, blocked),
                         "바로 착수할 카드 없음 — 막힘 해소가 먼저: C(codex), D(claude)")
        self.assertIn("일정 파일 없음", db.next_words({"state": "WAIT", "code": "SCHEDULE_MISSING"}, []))

    def test_day_brief_is_four_short_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), self.PHASES)
            text = db.day_brief(project, "claude", {"codex": {"state": "LIMITED"}, "claude": {"state": "ACTIVE"}},
                                home=Path(tmp))
            lines = text.splitlines()
            self.assertEqual(len(lines), 4, text)
            self.assertTrue(lines[0].startswith("[UAOS-RSI 브리핑] 버전 미확인"), text)
            self.assertTrue(lines[1].startswith("진행: 일정 2/6 완료"), text)
            self.assertEqual(lines[2], "도구: Codex 한도 · Claude 활동")
            self.assertEqual(lines[3], "다음: F 착수 (이 도구 차례)")
            self.assertTrue(all(len(line) <= db.LINE_CHARS for line in lines))


class OncePerSession(unittest.TestCase):
    def test_same_session_once_other_session_again(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(db.brief_once(Path(tmp), "claude", "s1"))
            self.assertFalse(db.brief_once(Path(tmp), "claude", "s1"))
            self.assertTrue(db.brief_once(Path(tmp), "codex", "s1"))
            self.assertTrue(db.brief_once(Path(tmp), "claude", "s2"))
            self.assertTrue(db.brief_once(Path(tmp), "claude", None))
            self.assertTrue(db.brief_once(Path(tmp), "claude", None))

    def test_parallel_hooks_show_exactly_once(self) -> None:
        # Claude runs the project and the global SessionStart hook at the same time (two briefings seen 2026-10-18).
        with tempfile.TemporaryDirectory() as tmp:
            with ProcessPoolExecutor(max_workers=8) as pool:
                shown = list(pool.map(_brief_once_worker, [(tmp, "same")] * 16))
            self.assertEqual(shown.count(True), 1, shown)


class HookShowsUser(unittest.TestCase):
    def test_session_start_shows_brief_to_user_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [_phase("A", "READY", "claude")])
            payload = {"session_id": "sess-u213", "source": "startup", "cwd": str(project),
                       "hook_event_name": "SessionStart"}
            first = _hook(project, payload)
            self.assertTrue(first.get("systemMessage", "").startswith("[UAOS-RSI 브리핑]"), first)
            self.assertIn("다음: A 착수", first["systemMessage"])
            self.assertEqual(first["hookSpecificOutput"]["hookEventName"], "SessionStart")
            self.assertIn("UAOS project", first["hookSpecificOutput"]["additionalContext"])
            again = _hook(project, payload)
            self.assertNotIn("systemMessage", again)

    def test_compaction_shows_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [])
            out = _hook(project, {"session_id": "sess-c", "source": "compact", "cwd": str(project)})
            self.assertNotIn("systemMessage", out)

    def test_today_command_prints_the_brief(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [_phase("A", "DONE")])
            (project / "sub").mkdir()
            done = subprocess.run([sys.executable, "-m", "v7_harness.cli", "coord", "today", "--project",
                                   str(project / "sub")], capture_output=True, text=True, encoding="utf-8",
                                  cwd=str(ROOT), env=dict(os.environ, PYTHONPATH=str(ROOT)), timeout=60)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("다음: 일정 완료 — 새 카드 없음", done.stdout)


class AntigravityUserDeskOnly(unittest.TestCase):
    def test_only_registered_desk_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [])
            with mock.patch("v7_harness.coord.deliver.read_user_desk", return_value="conv-desk"):
                self.assertEqual(db.agy_brief(project, "conv-headless", {}), "")
                first = db.agy_brief(project, "conv-desk", {})
                self.assertIn("[UAOS-RSI 브리핑]", first)
                self.assertTrue(first.startswith("Begin your next visible reply"))
                self.assertEqual(db.agy_brief(project, "conv-desk", {}), "")
            with mock.patch("v7_harness.coord.deliver.read_user_desk", return_value=""):
                self.assertEqual(db.agy_brief(project, "", {}), "")


if __name__ == "__main__":
    unittest.main()
