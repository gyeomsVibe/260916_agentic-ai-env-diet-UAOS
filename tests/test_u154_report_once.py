"""U154: one user prompt is one error report, and a broadcast report is data, never an order to the receiver.

Receipt (2026-10-04, .work/u154/receipt_tikitaka_break_20261004.md):
- C3: Claude runs `coord presence --from-hook` from both the global hook (installed by global_install, `--delta`) and
  the project hook (.claude/settings.json, no `--delta`). Each prompt was recorded twice, 35 ms apart
  (user_error_reports.jsonl 1791099455.79/.81), so the user's first report already printed "P1 REPEATED #2".
  Both hooks get byte-identical stdin, so no time window can tell them from two real submissions (Codex REWORK
  261aa180: two real submissions 5 s apart must stay two). Only the one installed per-prompt hook (`--delta`, present
  for all 3 tools) runs U150.
- C2: the user's "작업 후 잠깐 대기 컴퓨터 재시작" to one Claude window reached Codex through the broadcast. Codex took
  it as its own pause and held a requested verdict, which stopped the 3-tool chain.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord import repeat_error as re_

ROOT = Path(__file__).resolve().parent.parent
T0 = 1_790_000_000.0
PROMPT = "또 티키타카가 안되네. 지금 너희들 따로 놀고 있잖아. 프로젝트 실패이다."


def _hook(project: Path, *extra: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8", "UAOS_WORKER")}
    env["PYTHONPATH"] = str(ROOT)
    payload = json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "u154-s1", "prompt": PROMPT},
                         ensure_ascii=False).encode("utf-8")
    return subprocess.run(
        [sys.executable, "-m", "v7_harness.cli", "coord", "presence", "--project", str(project), "--from-hook",
         "--tool", "claude", "--state", "ACTIVE", "--say", "p1", *extra],
        input=payload, capture_output=True, env=env, cwd=str(ROOT), timeout=120)


class OnePromptOneReport(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        (self.project / ".coord").mkdir()
        (self.project / ".coord" / "PLAN.md").write_text("", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_global_and_project_hooks_for_one_prompt_record_one_row(self):
        project_hook = _hook(self.project)  # .claude/settings.json: no --delta
        global_hook = _hook(self.project, "--delta")  # global_install: --delta
        self.assertEqual(0, project_hook.returncode, project_hook.stderr[-400:])
        self.assertEqual(0, global_hook.returncode, global_hook.stderr[-400:])
        out = (project_hook.stdout + global_hook.stdout).decode("utf-8", errors="replace")
        self.assertIn("USER ERROR REPORT", out)
        self.assertNotIn("P1 REPEATED", out)
        self.assertEqual(1, len(re_.load(self.project)))

    def test_two_real_submissions_seconds_apart_stay_two(self):
        # Codex frozen counterexample (REWORK 261aa180).
        re_.on_prompt(self.project, "claude", PROMPT, now=T0)
        line = re_.on_prompt(self.project, "claude", PROMPT, now=T0 + 5)
        self.assertEqual(2, len(re_.load(self.project)))
        self.assertIn("P1 REPEATED USER ERROR (U150-B, report #2", line)


class BroadcastIsDataNotOrders(unittest.TestCase):
    def test_receiver_line_says_wait_or_restart_words_are_not_for_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".coord").mkdir()
            re_.on_prompt(project, "claude", "지금 진행하는 작업 후 잠깐 대기 컴퓨터 재시작. 이것도 실패이다.", now=T0)
            line = re_.on_prompt(project, "codex", "다음 카드 진행", now=T0 + 60)
        self.assertIn("USER ERROR REPORTED TO claude", line)
        self.assertIn("not an instruction to you", line)
        self.assertIn("do not pause", line)


if __name__ == "__main__":
    unittest.main()
