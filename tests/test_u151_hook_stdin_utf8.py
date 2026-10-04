"""U151: the hook reads its payload as UTF-8, so a Korean prompt reaches U150 intact.

Receipt (2026-10-04, after installing runtime 0.3.0-389e0dd26486): a raw UTF-8 hook payload with the prompt
"메시지 ID 충돌 결함 고쳐줘" produced no U150 line, while the same payload with \\u-escaped JSON did. Windows Python
decodes stdin with the ANSI code page (cp949 here), so every Korean prompt the hook runners send became mojibake
and the U150 declaration/error matching never saw a real prompt. Claude Code and Antigravity set no
PYTHONIOENCODING for their hooks.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import hook_context

ROOT = Path(__file__).resolve().parent.parent
PROMPT = "메시지 ID 충돌 결함 고쳐줘"


class ReadStdin(unittest.TestCase):
    def test_utf8_bytes_under_a_cp949_text_layer_decode_intact(self):
        raw = json.dumps({"prompt": PROMPT}, ensure_ascii=False).encode("utf-8")
        stream = io.TextIOWrapper(io.BytesIO(raw), encoding="cp949", errors="strict")
        with mock.patch.object(sys, "stdin", stream):
            self.assertEqual(PROMPT, json.loads(hook_context.read_stdin())["prompt"])

    def test_text_only_stream_still_works(self):
        with mock.patch.object(sys, "stdin", io.StringIO('{"prompt": "x"}')):
            self.assertEqual('{"prompt": "x"}', hook_context.read_stdin())

    def test_non_utf8_bytes_fall_back_without_raising(self):
        raw = "결함".encode("cp949")
        stream = io.TextIOWrapper(io.BytesIO(raw), encoding="cp949")
        with mock.patch.object(sys, "stdin", stream):
            self.assertIsInstance(hook_context.read_stdin(), str)


class HookEndToEnd(unittest.TestCase):
    def test_raw_utf8_payload_reaches_u150(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".coord").mkdir()
            (project / ".coord" / "PLAN.md").write_text("", encoding="utf-8")
            env = {k: v for k, v in os.environ.items()
                   if k not in ("PYTHONIOENCODING", "PYTHONUTF8", "UAOS_WORKER")}
            env["PYTHONPATH"] = str(ROOT)
            payload = json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "u151-s1",
                                  "prompt": PROMPT}, ensure_ascii=False).encode("utf-8")
            done = subprocess.run(
                [sys.executable, "-m", "v7_harness.cli", "coord", "presence", "--project", str(project),
                 "--from-hook", "--tool", "claude", "--state", "ACTIVE", "--say", "p1", "--delta"],
                input=payload, capture_output=True, env=env, cwd=str(ROOT), timeout=120)
            self.assertEqual(0, done.returncode, done.stderr[-400:])
            rows = (project / ".coord" / "usage" / "user_error_reports.jsonl").read_text(encoding="utf-8")
            self.assertIn("충돌", rows)
            self.assertIn("USER ERROR REPORT", done.stdout.decode("utf-8", errors="replace"))


if __name__ == "__main__":
    unittest.main()
