"""U216: four defects found in real use on 2026-10-18 (U214/U215 cards), each reproduced here before its fix.

R1 (relay_df7c40c5): a card-tagged verdict letter to Antigravity was never auto-answered. First read as "no card
    window"; the receipt's 16,363-char body quotes `[agy-auto]` (U214 stall.py docstring), so it is R2's cause.
R2 (relay_6fabd2c8): a letter that quoted the loop tag `[agy-auto]` anywhere in its body (an audit diff) was dropped
    as SKIPPED_LOOP; only an auto reply itself starts with the tag, so the tag counts only at the start.
R3: `pilot run --approve` on an already applied bundle replays the saved summary and never checks that the working
    files still hold the approved bytes, so a reverted file stayed reverted while the result said APPLIED.
R4: a manual input pin taken from the git blob (LF) never matches the CRLF working file under core.autocrlf=true;
    the pin is compared on the bytes and on the LF-normalized text, so both spellings of the same text pass.
"""
import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from v7_harness import manual
from v7_harness.coord import agy_dispatch, presence
from v7_harness.coord.deliver import deliver
from v7_harness.coord.watch import watch_file
from v7_harness.pilot import PilotConfig, run_pilot


class AgyRoutes(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        sessions = Path(self._tmp.name) / "codex-sessions"
        sessions.mkdir()
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(sessions)})
        self._env.start()
        os.environ.pop("UAOS_AGY_AUTO", None)
        self._which = mock.patch("v7_harness.coord.deliver.shutil.which", side_effect=lambda name: name)
        self._which.start()
        presence.mark(self.project, "claude", "ACTIVE")
        beat = watch_file(self.project, "claude")
        beat.parent.mkdir(parents=True, exist_ok=True)
        beat.write_text(json.dumps({"tool": "claude", "token": "t", "pid": 1, "expires_at": time.time() + 300,
                                    "wakes_session": True}), encoding="utf-8")
        self.calls = []

    def tearDown(self):
        self._which.stop()
        self._env.stop()
        self._tmp.cleanup()

    def runner(self, argv, **kwargs):
        self.calls.append(list(argv))
        envelope = {"status": "SUCCESS", "conversation_id": "conv-auto",
                    "usage": {"input_tokens": 20_000, "output_tokens": 500}, "response": "PASS abc"}
        return SimpleNamespace(returncode=0, stdout=json.dumps(envelope).encode("utf-8"), stderr=b"")

    def test_r1_a_card_verdict_letter_without_a_window_is_answered(self):
        body = f"Audit U214: diff below.\n+    \"\"\"the id a reply answers: `{agy_dispatch.AUTO_TAG} re`.\"\"\""
        result = deliver(self.project, message=body, actor="claude", target="antigravity",
                         runner=self.runner, card="U214", verdict_requested=True)
        self.assertEqual(1, len(self.calls), result.output)
        self.assertTrue(result.output.startswith("AGY_ANSWERED"), result.output)

    def test_r2_a_quoted_tag_inside_the_body_still_dispatches(self):
        body = f"Audit U215: the diff quotes `{agy_dispatch.AUTO_TAG} re` from stall.py; verdict please."
        result = deliver(self.project, message=body, actor="claude", target="antigravity", runner=self.runner,
                         verdict_requested=True)
        self.assertEqual(1, len(self.calls), result.output)

    def test_r2_a_reply_that_starts_with_the_tag_never_dispatches(self):
        result = deliver(self.project, message=f"  {agy_dispatch.AUTO_TAG} re relay_x: PASS", actor="claude",
                         target="antigravity", runner=self.runner, verdict_requested=True)
        self.assertEqual([], self.calls)
        self.assertIn("SKIPPED_LOOP", result.output)


FAKE_AGY = [sys.executable, str(Path(__file__).parent / "fixtures" / "fake_agy.py")]
ORIGINAL = "def mul(a, b):\n    return a * b\n"


class ApproveReplay(unittest.TestCase):
    """R3: a re-approve of an applied bundle must leave the working files holding the approved bytes, or say not."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.source = root / "sample"
        self.source.mkdir()
        (self.source / "calc.py").write_text(ORIGINAL, encoding="utf-8")
        self.home = root / "home"
        self.home.mkdir()
        self.work = root / "work"

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, **overrides):
        config = PilotConfig(**{**dict(task_id="R3", title="add", prompt="Add add(a, b).", source_dir=self.source,
                                        work_dir=self.work, agy_command=FAKE_AGY, watch_roots=[self.home],
                                        print_timeout_s=60, approve_bundle_id=None), **overrides})
        with mock.patch.dict(os.environ, {"FAKE_AGY_MODE": "success", "FAKE_AGY_OUTSIDE_DIR": str(self.home)}):
            return run_pilot(config)

    def _applied(self):
        first = self._run()
        self.assertEqual("APPLIED", self._run(approve_bundle_id=first["bundle_id"])["promotion"])
        return first["bundle_id"]

    def test_a_reverted_file_is_written_again(self):
        bundle = self._applied()
        (self.source / "calc.py").write_text(ORIGINAL, encoding="utf-8")
        again = self._run(approve_bundle_id=bundle)
        self.assertEqual("APPLIED", again["promotion"])
        self.assertIn("def add(a, b):", (self.source / "calc.py").read_text(encoding="utf-8"))

    def test_an_applied_tree_replays_without_writing(self):
        bundle = self._applied()
        before = (self.source / "calc.py").read_bytes()
        self.assertEqual("APPLIED", self._run(approve_bundle_id=bundle)["promotion"])
        self.assertEqual(before, (self.source / "calc.py").read_bytes())

    def test_a_drifted_file_is_reported_and_kept(self):
        bundle = self._applied()
        (self.source / "calc.py").write_text("x = 1\n", encoding="utf-8")
        self.assertEqual("SOURCE_DRIFTED", self._run(approve_bundle_id=bundle)["promotion"])
        self.assertEqual("x = 1\n", (self.source / "calc.py").read_text(encoding="utf-8"))


class InputPinEol(unittest.TestCase):
    """R4: a pin from the LF git blob matches the CRLF working file of the same text, and a wrong pin still fails."""

    def _errors(self, data, pin_of):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pkg").mkdir()
            (root / "pkg" / "mod.py").write_bytes(data)
            pin = hashlib.sha256(pin_of).hexdigest()
            return [e for e in manual.lint(MANUAL.replace("<PIN>", pin), project=root).errors
                    if e.startswith("INPUT_")]

    def test_an_lf_pin_matches_a_crlf_working_file(self):
        self.assertEqual([], self._errors(b"a = 1\r\nb = 2\r\n", b"a = 1\nb = 2\n"))

    def test_a_byte_pin_still_matches(self):
        self.assertEqual([], self._errors(b"a = 1\r\n", b"a = 1\r\n"))

    def test_a_pin_of_other_text_still_fails(self):
        self.assertEqual(["INPUT_HASH_MISMATCH:pkg/mod.py"], self._errors(b"a = 1\r\n", b"a = 2\n"))


MANUAL = """```contract
work_id: R4-T
worker: local
goal: Change pkg/mod.py exactly as dictated so the pin check is exercised.
inputs:
- pkg/mod.py sha256=<PIN>
allow:
- pkg/mod.py
acceptance: python -m unittest tests.test_u216_use_receipts
forbidden: edits outside allow
stop: input hash mismatch
judge: codex
timeout_s: 60
remote_budget_tokens: 0
```
"""


if __name__ == "__main__":
    unittest.main()
