"""U148: Antigravity gets a user desk, and the user sees Antigravity's and Ollama's share of the work.

Receipt (윤겸스, 2026-10-04): "the user-window registration does not cover Antigravity; why do only Codex and Claude
pass work back and forth; Ollama token-thrift use is not visible". Rules under test:
1. Antigravity's PreInvocation hook (first model call of a turn, invocationNum 0) claims an ABSENT or INVALID user
   desk for the desktop conversation it fired in; it never moves an OK desk, because nothing in the payload proves a
   human turn (Codex review). Only `coord presence --desk-thread` moves it. A conversation found only in the headless
   CLI store, a later call of the turn, a non-UUID id or a pilot worker (UAOS_WORKER) registers nothing.
2. The desk record follows the U147-D rules: ABSENT, OK or INVALID; one project's desk never leaks into another;
   registrations racing in real parallel processes leave one valid record.
3. Antigravity's own hook output in its desk conversation names its headless answers of today, so the desktop
   conversation learns what its headless twin said; another conversation does not get that part. The hook text
   reaches the Antigravity model only, so delivery stays pending until that model's reply shows it.
4. The in-app line in Claude and Codex shows today's Ollama calls and Antigravity's headless answers, counted on the
   Asia/Seoul day; a letter answered twice counts once and a preflight refusal is not an Ollama call.
"""

import contextlib
import io
import json
import multiprocessing
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import agy_dispatch, board, deliver, hook_context

DESK = "2c573cc3-3c50-40a7-a060-738cadce9bc5"
CLI_ONLY = "ae1af179-2b66-4d63-a286-3dc22c4ddecd"
OTHER = "0199cccc-0000-4000-8000-000000000003"


def _register(args):
    project, thread = args
    return deliver.register_user_desk(Path(project), "antigravity", thread, source="race")


class AgyDeskTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.project = base / "proj"
        (self.project / ".coord").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        self.app = base / "agy-app"
        (self.app / "conversations").mkdir(parents=True)
        (self.app / "conversations" / f"{DESK}.db").write_bytes(b"")
        (self.app / "brain" / OTHER).mkdir(parents=True)
        cli = base / "agy-cli" / "conversations"
        cli.mkdir(parents=True)
        (cli / f"{CLI_ONLY}.db").write_bytes(b"")
        self.usage = base / "olla-usage.jsonl"
        env = {deliver.AGY_APP_HOME_ENV: str(self.app), board.OLLA_USAGE_ENV: str(self.usage),
               board.AGY_BRAIN_ENV: str(base / "no-brain"), board.CLAUDE_PROJECTS_ENV: str(base / "no-claude")}
        self._env = mock.patch.dict(os.environ, env)
        self._env.start()
        os.environ.pop("UAOS_WORKER", None)

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def _hook(self, conversation, invocation=0, **extra):
        from v7_harness.cli import main as cli_main

        event = json.dumps({"conversationId": conversation, "invocationNum": invocation,
                            "workspacePaths": [str(self.project)], **extra})
        argv = ["coord", "presence", "--tool", "antigravity", "--state", "ACTIVE", "--ttl", "3600", "--from-hook",
                "--say", "agy", "--delta", "--project", str(self.project)]
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(event)), contextlib.redirect_stdout(out):
            cli_main(argv)
        return out.getvalue().strip()

    def test_desktop_conversation_check_reads_only_the_app_store(self):
        self.assertTrue(deliver.agy_desktop_conversation(DESK))  # conversations/<id>.db
        self.assertTrue(deliver.agy_desktop_conversation(OTHER))  # brain/<id>/
        self.assertFalse(deliver.agy_desktop_conversation(CLI_ONLY))  # headless CLI store only
        for bad in ("", "abc", "../" + DESK, DESK + "/x", None, 7):
            self.assertFalse(deliver.agy_desktop_conversation(bad), bad)

    def test_first_call_registers_nothing_and_keeps_the_key_names(self):
        # REPLAN (Codex codex_u148_c1_human_origin_gate_unmet): was test_first_call_of_a_desktop_turn_registers_the_desk
        # and test_a_prompt_field_when_present_must_be_human (frozen sha a1712a8b). No payload proves a human turn, so
        # the hook registers nothing, whatever prompt it carries; it keeps only the key names as evidence.
        self._hook(DESK)
        self._hook(DESK, prompt="")
        self._hook(DESK, userPrompt="[agy-auto] re relay_x: PASS")
        self._hook(DESK, userPrompt="윤겸스가 직접 쓴 지시")
        self.assertEqual(deliver.user_desk_state(self.project, "antigravity"), ("ABSENT", ""))
        keys = json.loads((self.project / ".coord" / "presence" / "agy_hook_keys.json").read_text(encoding="utf-8"))
        self.assertEqual(keys, ["conversationId", "invocationNum", "userPrompt", "workspacePaths"])

    def test_cli_later_call_bad_id_and_worker_register_nothing(self):
        self._hook(CLI_ONLY)
        self._hook(OTHER, invocation=1)
        self._hook("not-a-uuid")
        with mock.patch.dict(os.environ, {"UAOS_WORKER": "1"}):
            self._hook(DESK)
        self.assertEqual(deliver.user_desk_state(self.project, "antigravity"), ("ABSENT", ""))

    def _explicit(self, thread, tool="antigravity"):
        from v7_harness.cli import main as cli_main

        with contextlib.redirect_stdout(io.StringIO()):
            return cli_main(["coord", "presence", "--tool", tool, "--desk-thread", thread,
                             "--project", str(self.project)])

    def test_a_hook_never_moves_a_desk_and_explicit_registration_does(self):
        # Codex review (U148 design CHANGES): nothing in the payload proves a human turn, so a worker, subagent,
        # restart or continuation must never move a designated desk; the explicit registration is the fallback.
        # REPLAN (codex_u148_c1_human_origin_gate_unmet): the desk is set explicitly, and INVALID stays INVALID.
        self.assertEqual(self._explicit(DESK), 0)
        self._hook(OTHER)
        self.assertEqual(deliver.read_user_desk(self.project, "antigravity"), DESK)
        self.assertEqual(self._explicit(CLI_ONLY), 2)  # not a desktop-app conversation
        self.assertEqual(self._explicit("not-a-uuid"), 2)
        self.assertEqual(self._explicit(OTHER, tool="codex"), 2)  # only Antigravity's desk is set this way
        self.assertEqual(deliver.read_user_desk(self.project, "antigravity"), DESK)
        self.assertEqual(self._explicit(OTHER), 0)
        record = json.loads(deliver.user_desk_path(self.project, "antigravity").read_text(encoding="utf-8"))
        self.assertEqual((record["thread"], record["source"]), (OTHER, "explicit"))
        elsewhere = Path(self._tmp.name) / "other-proj"
        (elsewhere / ".coord").mkdir(parents=True)
        self.assertEqual(deliver.user_desk_state(elsewhere, "antigravity"), ("ABSENT", ""))
        deliver.user_desk_path(self.project, "antigravity").write_text("{", encoding="utf-8")
        self.assertEqual(deliver.user_desk_state(self.project, "antigravity"), ("INVALID", ""))
        self._hook(DESK)  # the hook never repairs a broken record; only an explicit registration does
        self.assertEqual(deliver.user_desk_state(self.project, "antigravity"), ("INVALID", ""))

    def test_parallel_registrations_leave_one_valid_record(self):
        ids = [f"0199dddd-0000-4000-8000-{n:012d}" for n in range(8)]
        with multiprocessing.get_context("spawn").Pool(8) as pool:
            results = pool.map(_register, [(str(self.project), thread) for thread in ids * 3])
        self.assertTrue(all(results), results)
        state, thread = deliver.user_desk_state(self.project, "antigravity")
        self.assertEqual(state, "OK")
        self.assertIn(thread, ids)
        leftovers = list(deliver.user_desk_path(self.project, "antigravity").parent.glob("*.tmp"))
        self.assertEqual(leftovers, [])

    def _answers(self, *states):
        ledger = self.project / ".coord" / "mailbox" / "delivery" / "agy_auto.jsonl"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        rows = [{"ts": now, "message_id": f"relay_{n:04d}", "state": state} for n, state in enumerate(states)]
        rows.append({"ts": now - 3 * 86400, "message_id": "relay_old", "state": "ANSWERED"})
        ledger.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def test_desk_conversation_hears_its_headless_answers(self):
        self._answers("ANSWERED", "FAILED", "ANSWERED")
        seen = self.project / hook_context.AGY_SEEN  # the U95-A once-per-change marker; cleared so each call speaks
        self.assertEqual(self._explicit(DESK), 0)  # REPLAN: the desk is registered explicitly, not by the hook
        shown = json.loads(self._hook(DESK))
        text = shown["injectSteps"][0]["ephemeralMessage"]
        self.assertIn("2 headless answer(s) today", text)
        self.assertIn("relay_0002", text)  # the newest answered letter
        seen.unlink(missing_ok=True)
        self.assertNotIn("headless answer", self._hook(OTHER))  # another desktop conversation is not the desk
        seen.unlink(missing_ok=True)
        not_desk = self._hook(CLI_ONLY)  # an interactive CLI conversation is not the desk
        self.assertNotIn("headless answer", not_desk)
        seen.unlink(missing_ok=True)
        self.assertNotIn("headless answer", self._hook(DESK, invocation=1))  # later calls of a turn read nothing

    def test_in_app_line_shows_ollama_calls_and_antigravity_answers(self):
        today = agy_dispatch.seoul_day(time.time()) + "T12:00:00"
        rows = [{"ts": today, "event": event} for event in ("ask", "digest", "pilot_local", "hint_plan", "turn_shape")]
        rows.append({"ts": today, "event": "pilot_local", "status": "PROMPT_TOO_LARGE"})  # preflight: no model call
        rows.append({"ts": "2026-01-01T00:00:00", "event": "ask"})
        self.usage.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        self._answers("ANSWERED", "FAILED", "ANSWERED")
        line = board.status_line(self.project, "claude", [])
        self.assertIn("올라마 오늘 3회", line)
        self.assertIn("Antigravity 답장 2통", line)
        many = [{"ts": today, "event": "ask"}] * 14
        self.usage.write_text("".join(json.dumps(row) + "\n" for row in many), encoding="utf-8")
        self.assertIn("올라마 오늘 10회 이상", board.status_line(self.project, "codex", []))

    def test_daily_answers_use_the_seoul_day_and_count_a_letter_once(self):
        # Codex review: a daily count names its timezone and its dedup rule. 1791126000 is 2026-10-05 00:00 in Seoul.
        midnight = 1791126000.0
        self.assertEqual(agy_dispatch.seoul_day(midnight), "2026-10-05")
        self.assertEqual(agy_dispatch.seoul_day(midnight - 1), "2026-10-04")
        ledger = self.project / ".coord" / "mailbox" / "delivery" / "agy_auto.jsonl"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        rows = [(midnight - 5, "relay_eve", "ANSWERED"), (midnight + 10, "relay_a", "ANSWERED"),
                (midnight + 20, "relay_a", "ANSWERED"), (midnight + 30, "relay_b", "FAILED")]
        ledger.write_text("".join(json.dumps({"ts": ts, "message_id": m, "state": s}) + "\n" for ts, m, s in rows),
                          encoding="utf-8")
        self.assertEqual(agy_dispatch.answered_today(self.project, midnight + 60), ["relay_a"])

    def test_missing_or_broken_ledgers_show_zero(self):
        self.usage.write_text("not json\n{\"ts\": 5, \"event\": \"ask\"}\n", encoding="utf-8")
        line = board.status_line(self.project, "claude", [])
        self.assertIn("올라마 오늘 0회", line)
        self.assertIn("Antigravity 답장 0통", line)


if __name__ == "__main__":
    unittest.main()
