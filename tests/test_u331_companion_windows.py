"""U331-A/B/C/D gates: companion conversation windows, auto manual, Codex naming race, release on DONE.

No network or paid calls: fake runners / fake Codex RPC, a temp project, isolated Codex session logs.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from v7_harness.card_pipeline import missing_slots
from v7_harness.coord import card_nav, presence, windows
from v7_harness.coord.deliver import deliver


class _AgyRunner:
    """Answers `agy -p <manual> --output-format json` with a conversation id, like the real CLI."""

    def __init__(self) -> None:
        self.opens: list[str] = []

    def __call__(self, command, **_kw):
        self.opens.append(command[command.index("-p") + 1] if "-p" in command else "")
        envelope = {"conversation_id": f"agy-conv-{len(self.opens)}", "usage": {"input_tokens": 10}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(envelope), stderr="")


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.p = Path(self._tmp.name) / "proj"
        (self.p / ".coord").mkdir(parents=True)
        (self.p / ".coord" / "PLAN.md").write_text("# plan\n| U329 | council | READY |\n", encoding="utf-8")
        sessions = Path(self._tmp.name) / "codex-sessions"
        sessions.mkdir()
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(sessions), "UAOS_AGY_AUTO": "0"})
        self._env.start()
        self._which = mock.patch("v7_harness.coord.deliver.shutil.which", side_effect=lambda name: name)
        self._which.start()
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(self._env.stop)
        self.addCleanup(self._which.stop)

    def _primary(self, cid: str = "U329") -> None:
        card_nav.write_card(self.p, cid, "claude", title="Council", nature="implementation", lane="IMPL_CODE",
                            state="RUNNING", owned_files=["x.py"], acceptance="python -m pytest -q tests/x.py")

    def _payload(self, result) -> dict:
        letter = self.p / ".coord" / "mailbox" / "inbox" / f"{result.message_id}.json"
        return json.loads(letter.read_text(encoding="utf-8"))["payload"]


class CollaborationLetterOpensCompanion(_Base):
    def test_explicit_notice_and_invalid_intent_launch_nothing(self) -> None:
        """Codex audit: a refused or manual (NOTICE/ACK_ONLY) letter must not open a companion window first."""
        presence.mark(self.p, "antigravity", "ACTIVE")
        self._primary()
        runner = _AgyRunner()
        notice = deliver(self.p, message="fyi only", actor="claude", target="antigravity", runner=runner,
                         card="U329", wake_class="NOTICE")
        ack = deliver(self.p, message="seen", actor="claude", target="antigravity", runner=runner, card="U329",
                      wake_class="ACK_ONLY")
        invalid = deliver(self.p, message="needs a turn", actor="claude", target="antigravity", runner=runner,
                          card="U329", wake_class="ACTIONABLE")  # ACTIONABLE without --delta is refused
        self.assertEqual("INVALID_INTENT", invalid.reason)
        self.assertEqual(0, len(runner.opens))
        self.assertEqual({}, windows.window_entry(self.p, "U329.agy", "antigravity"))
        self.assertEqual(2, sum(1 for r in (notice, ack) if r.message_id))

    def test_body_only_ack_marker_launches_nothing(self) -> None:
        self._primary()
        runner = _AgyRunner()
        deliver(self.p, message="ACK_ONLY: status echo, nothing new", actor="claude", target="antigravity",
                runner=runner, card="U329")
        self.assertEqual([], runner.opens)

    def test_done_primary_gets_no_new_companion(self) -> None:
        presence.mark(self.p, "antigravity", "ACTIVE")
        self._primary()
        card_nav.write_card(self.p, "U329", "claude", state="DONE")
        self.assertEqual([], card_nav.open_companions(self.p, "U329"))

    def test_letter_creates_then_reuses_companion_window_and_routes_there(self) -> None:
        presence.mark(self.p, "antigravity", "ACTIVE")
        self._primary()
        runner = _AgyRunner()
        first = deliver(self.p, message="counterexample please", actor="claude", target="antigravity",
                        runner=runner, card="U329")
        self.assertEqual(1, len(runner.opens))
        payload = self._payload(first)
        self.assertEqual(("U329", "agy-conv-1"), (payload["card"], payload["window"]))
        entry = windows.window_entry(self.p, "U329.agy", "antigravity")
        self.assertEqual("agy-conv-1", entry["id"])
        self.assertEqual("agy-conv-1", card_nav.read_card(self.p, "U329.agy")["owner"]["session"])
        # the letter went to the companion window, not into a window of the primary card
        self.assertEqual({}, windows.window_entry(self.p, "U329", "antigravity"))
        second = deliver(self.p, message="and a second point", actor="claude", target="antigravity",
                         runner=runner, card="U329")
        self.assertEqual(1, len(runner.opens))  # reused: no second launch
        self.assertEqual("agy-conv-1", self._payload(second)["window"])

    def test_cap_three_keeps_the_fourth_card_on_the_desk_route(self) -> None:
        presence.mark(self.p, "antigravity", "ACTIVE")
        runner = _AgyRunner()
        for n in range(4):
            self._primary(f"U{500 + n}")
            result = deliver(self.p, message=f"collab {n}", actor="claude", target="antigravity",
                             runner=runner, card=f"U{500 + n}")
            window = self._payload(result)["window"]
            if n < 3:
                self.assertTrue(window, n)
            else:
                self.assertFalse(window)  # QUEUED at the 3-cap: no fourth window
        self.assertEqual(3, len(runner.opens))
        self.assertEqual("QUEUED", card_nav.read_card(self.p, "U503.agy")["state"])

    def test_card_without_nav_record_keeps_todays_route(self) -> None:
        presence.mark(self.p, "antigravity", "ACTIVE")
        runner = _AgyRunner()
        result = deliver(self.p, message="plain", actor="claude", target="antigravity", runner=runner, card="U777")
        self.assertEqual([], runner.opens)
        self.assertFalse(self._payload(result)["window"])

    def test_opt_out_env_keeps_todays_route(self) -> None:
        presence.mark(self.p, "antigravity", "ACTIVE")
        self._primary()
        runner = _AgyRunner()
        with mock.patch.dict(os.environ, {"UAOS_COMPANION_WINDOWS": "0"}):
            deliver(self.p, message="x", actor="claude", target="antigravity", runner=runner, card="U329")
        self.assertEqual([], runner.opens)

    def test_same_tool_gets_no_companion(self) -> None:
        self._primary()
        self.assertEqual({"skipped": "SAME_TOOL"}, card_nav.ensure_companion_window(self.p, "U329", "claude", "claude"))


class AutoManualAndRelease(_Base):
    def test_companion_manual_fills_every_stage_slot(self) -> None:
        self._primary()
        companion = card_nav.open_companion_for(self.p, "U329", "antigravity")
        manual = card_nav.companion_manual(self.p, companion)
        self.assertEqual([], missing_slots(manual))  # no MANUAL_MISSING_SLOTS
        self.assertIn("| U329 | council | READY |", manual)  # PLAN row carried
        self.assertIn("python -m pytest -q tests/x.py", manual)  # acceptance carried

    def test_window_released_when_primary_finishes(self) -> None:
        presence.mark(self.p, "antigravity", "ACTIVE")
        self._primary()
        runner = _AgyRunner()
        result = card_nav.ensure_companion_window(self.p, "U329", "antigravity", "claude", runner=runner)
        self.assertEqual("agy-conv-1", result["window"])
        card_nav.finish_primary(self.p, "U329", "claude", "merged")
        entry = windows.window_entry(self.p, "U329.agy", "antigravity")
        self.assertEqual("RELEASED", entry["state"])
        # a late letter for the finished primary neither resurrects the released window nor opens another
        again = card_nav.ensure_companion_window(self.p, "U329", "antigravity", "claude", runner=runner)
        self.assertEqual({"skipped": "NO_NAV_PRIMARY"}, again)
        self.assertEqual(1, len(runner.opens))


class _FakeCodex:
    """Fake `codex app-server` RPC: thread/name/set fails with the empty-rollout error `empty_for` times."""

    def __init__(self, empty_for: int, other_error: str = "") -> None:
        self.empty_for, self.other_error, self.calls = empty_for, other_error, []

    def __call__(self, method: str, params: dict) -> dict:
        self.calls.append(method)
        if method == "thread/start":
            return {"thread": {"id": f"thread-{self.calls.count('thread/start')}"}}
        if method == "thread/name/set":
            if self.other_error:
                raise RuntimeError(self.other_error)
            if self.calls.count("thread/name/set") <= self.empty_for:
                raise RuntimeError("{'message': 'rollout /x/rollout-t.jsonl is empty'}")
        return {}


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class CodexNamingRace(unittest.TestCase):
    def test_name_succeeds_after_the_rollout_fills(self) -> None:
        rpc, clock = _FakeCodex(empty_for=3), _Clock()
        self.assertTrue(windows.name_codex_thread(rpc, "t1", "[U1] x", sleep=clock.sleep, clock=clock))
        self.assertEqual(4, rpc.calls.count("thread/name/set"))
        self.assertEqual([0.25, 0.5, 1.0], clock.sleeps)  # bounded exponential backoff

    def test_deadline_returns_false_within_ten_seconds_and_never_raises(self) -> None:
        rpc, clock = _FakeCodex(empty_for=10**6), _Clock()
        self.assertFalse(windows.name_codex_thread(rpc, "t1", "[U1] x", sleep=clock.sleep, clock=clock))
        self.assertLessEqual(clock.now, windows.NAME_DEADLINE_S)
        self.assertGreaterEqual(clock.now, windows.NAME_DEADLINE_S - 1e-9)

    def test_other_errors_are_not_retried(self) -> None:
        rpc, clock = _FakeCodex(empty_for=0, other_error="permission denied"), _Clock()
        self.assertFalse(windows.name_codex_thread(rpc, "t1", "x", sleep=clock.sleep, clock=clock))
        self.assertEqual(1, rpc.calls.count("thread/name/set"))

    def test_open_codex_reuses_the_created_thread_when_naming_never_succeeds(self) -> None:
        """Receipt 2026-11-20: 4/7 opens failed 'rollout ... jsonl is empty' and left orphan unnamed threads."""
        rpc = _FakeCodex(empty_for=10**6)
        clock = _Clock()
        with mock.patch.object(windows, "NAME_DEADLINE_S", 0.6), \
                mock.patch.object(windows.time, "sleep", clock.sleep), \
                mock.patch.object(windows.time, "monotonic", clock):
            thread_id = windows._open_codex(Path("."), "[U332] t", "prompt", rpc)
        self.assertEqual("thread-1", thread_id)  # returned, not raised
        self.assertEqual(1, rpc.calls.count("thread/start"))  # exactly one thread: no orphan from a retry

    def test_open_codex_names_once_the_rollout_is_ready(self) -> None:
        rpc, clock = _FakeCodex(empty_for=2), _Clock()
        with mock.patch.object(windows.time, "sleep", clock.sleep), mock.patch.object(windows.time, "monotonic", clock):
            self.assertEqual("thread-1", windows._open_codex(Path("."), "[U332] t", "p", rpc))
        self.assertEqual(3, rpc.calls.count("thread/name/set"))


class AgyOpenWithoutConversationId(_Base):
    def test_envelope_without_conversation_id_is_a_refusal_not_a_keyerror(self) -> None:
        """Receipt 2026-11-20: `coord window --tool antigravity` crashed with KeyError 'conversation_id'."""
        presence.mark(self.p, "antigravity", "ACTIVE")

        def runner(_command, **_kw):
            return SimpleNamespace(returncode=1, stderr="",
                                   stdout=json.dumps({"status": "ERROR", "error": "429 quota exhausted"}))

        result = windows.open_window(self.p, "U331", "antigravity", "t", "prompt", runner=runner)
        self.assertEqual("AGY_OPEN_FAILED", result["refused"])
        self.assertIn("429 quota exhausted", result["detail"])
        self.assertNotIn("id", result)
        self.assertEqual({}, windows.window_entry(self.p, "U331", "antigravity"))  # nothing recorded as open

    def test_non_json_output_is_also_a_refusal(self) -> None:
        presence.mark(self.p, "antigravity", "ACTIVE")
        runner = lambda _c, **_k: SimpleNamespace(returncode=0, stdout="plain text, no json", stderr="")  # noqa: E731
        self.assertEqual("AGY_OPEN_FAILED",
                         windows.open_window(self.p, "U331", "antigravity", "t", "p", runner=runner)["refused"])

    def test_companion_falls_back_to_the_desk_route_on_that_refusal(self) -> None:
        presence.mark(self.p, "antigravity", "ACTIVE")
        self._primary()
        runner = lambda _c, **_k: SimpleNamespace(returncode=1, stdout=json.dumps({"status": "ERROR"}), stderr="")  # noqa: E731
        result = card_nav.ensure_companion_window(self.p, "U329", "antigravity", "claude", runner=runner)
        self.assertEqual("AGY_OPEN_FAILED", result["skipped"])


class CodexAppServerStaysUntilTurnEnds(unittest.TestCase):
    def test_open_codex_waits_for_the_first_turn_when_it_owns_the_server(self) -> None:
        """Receipt: our app-server was killed right after turn/start, so rollouts ended `turn_aborted`."""
        rpc = _FakeCodex(empty_for=0)
        waited: list[float] = []
        rpc.wait_turn = lambda timeout: (waited.append(timeout) or "COMPLETED")  # type: ignore[attr-defined]
        rpc.proc = SimpleNamespace(kill=lambda: None)  # type: ignore[attr-defined]
        with mock.patch.object(windows, "_codex_rpc_session", return_value=rpc):
            info: dict = {}
            windows._open_codex(Path("."), "[U331] t", "prompt", None, info)
        self.assertEqual([windows.TURN_WAIT_S], waited)
        self.assertEqual("COMPLETED", info["first_turn"])
        self.assertTrue(info["named"])

    def test_unnamed_thread_is_reported_not_hidden(self) -> None:
        """AGY review: a failed name must surface as named=False, never silently pass as a named window."""
        rpc, clock = _FakeCodex(empty_for=10**6), _Clock()
        info: dict = {}
        with mock.patch.object(windows, "NAME_DEADLINE_S", 0.6), \
                mock.patch.object(windows.time, "sleep", clock.sleep), mock.patch.object(windows.time, "monotonic", clock):
            windows._open_codex(Path("."), "[U331] t", "p", rpc, info)
        self.assertIs(False, info["named"])

    def test_wait_turn_survives_non_dict_json_and_reports_eof(self) -> None:
        lines = iter(['[1, 2]\n', '"x"\n', 'not json\n'])
        fake = SimpleNamespace(stdout=lines, stdin=SimpleNamespace(write=lambda s: None, flush=lambda: None),
                               kill=lambda: None)
        answers = iter(['{"jsonrpc":"2.0","id":0,"result":{}}\n'])
        fake.stdout = iter(['{"jsonrpc":"2.0","id":0,"result":{}}\n', '[1, 2]\n', '"x"\n', 'garbage\n'])
        with mock.patch.object(windows.subprocess, "Popen", return_value=fake):
            call = windows._codex_rpc_session()
        self.assertEqual("EOF", call.wait_turn(5.0))

    def test_agy_non_json_braces_become_open_failed(self) -> None:
        runner = lambda *a, **k: SimpleNamespace(stdout="noise {not json} tail", stderr="", returncode=0)  # noqa: E731
        with self.assertRaises(windows.AgyOpenFailed):
            windows._open_antigravity(Path("."), "p", runner)

    def test_agy_non_dict_json_and_non_dict_usage_never_crash(self) -> None:
        for out in ("null", "[]", '"error"', "123"):
            runner = lambda *a, _o=out, **k: SimpleNamespace(stdout=_o, stderr="", returncode=0)  # noqa: E731
            with self.assertRaises(windows.AgyOpenFailed):
                windows._open_antigravity(Path("."), "p", runner)
        runner = lambda *a, **k: SimpleNamespace(stdout='{"conversation_id": "c-2", "usage": 5}', stderr="", returncode=0)  # noqa: E731
        self.assertEqual(("c-2", None), windows._open_antigravity(Path("."), "p", runner))

    def test_agy_conversation_id_is_stripped(self) -> None:
        runner = lambda *a, **k: SimpleNamespace(stdout='{"conversation_id": " c-1 "}', stderr="", returncode=0)  # noqa: E731
        self.assertEqual(("c-1", None), windows._open_antigravity(Path("."), "p", runner))

    def test_injected_rpc_is_not_waited_on(self) -> None:
        rpc = _FakeCodex(empty_for=0)
        rpc.wait_turn = lambda timeout: self.fail("must not wait on a caller-owned rpc")  # type: ignore[attr-defined]
        windows._open_codex(Path("."), "[U331] t", "prompt", rpc)


class CodexCompanionWindow(_Base):
    def test_codex_companion_window_opens_with_manual_and_is_reused(self) -> None:
        self._primary()
        presence.mark(self.p, "codex", "ACTIVE")
        rpc = _FakeCodex(empty_for=1)
        with mock.patch.object(windows.time, "sleep", lambda _s: None), \
                mock.patch("v7_harness.coord.deliver._verify_thread", return_value="DISPATCH"):
            first = card_nav.ensure_companion_window(self.p, "U329", "codex", "claude", rpc=rpc)
            second = card_nav.ensure_companion_window(self.p, "U329", "codex", "claude", rpc=rpc)
        self.assertEqual(("thread-1", False), (first["window"], first["reused"]))
        self.assertEqual(("thread-1", True), (second["window"], second["reused"]))
        self.assertEqual(1, rpc.calls.count("thread/start"))

    def test_reused_codex_companion_with_a_foreign_thread_is_released_not_used(self) -> None:
        self._primary()
        presence.mark(self.p, "codex", "ACTIVE")
        rpc = _FakeCodex(empty_for=1)
        with mock.patch.object(windows.time, "sleep", lambda _s: None):
            card_nav.ensure_companion_window(self.p, "U329", "codex", "claude", rpc=rpc)
        with mock.patch("v7_harness.coord.deliver._verify_thread", return_value="THREAD_PROJECT_MISMATCH"):
            again = card_nav.ensure_companion_window(self.p, "U329", "codex", "claude", rpc=rpc)
        self.assertEqual("COMPANION_THREAD_PROJECT_MISMATCH", again["skipped"])
        self.assertNotIn("window", again)
        entry = windows.window_entry(self.p, "U329.codex", "codex")
        self.assertEqual("RELEASED", entry.get("state"))


class AgyCompanionDispatch(_Base):
    def test_headless_antigravity_turn_resumes_the_companion_card_window(self) -> None:
        presence.mark(self.p, "antigravity", "ACTIVE")
        self._primary()
        runner = _AgyRunner()
        seen: list[str] = []

        def _fake(_desk, **kw):
            seen.append(kw.get("card"))
            return {"state": "ANSWERED"}

        with mock.patch.dict(os.environ, {"UAOS_AGY_AUTO": "1"}), \
                mock.patch("v7_harness.coord.agy_dispatch.dispatch", side_effect=_fake):
            deliver(self.p, message="ACTIONABLE_DELTA counterexample please", actor="claude", target="antigravity",
                    runner=runner, card="U329")
        self.assertEqual(["U329.agy"], seen)


if __name__ == "__main__":
    unittest.main()
