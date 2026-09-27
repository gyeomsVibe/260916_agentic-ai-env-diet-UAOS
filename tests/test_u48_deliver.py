"""coord deliver 단위 테스트 — 사용자 수동 릴레이 영구 제거 검증.

불변식:
  1. 사용자에게 "전달해달라"는 요청이 발생하지 않는다.
  2. Codex ACTIVE → codex queue, Claude ACTIVE → claude -p 직접 호출.
  3. 둘 다 부재 → 사서함에만 보존, 사용자 릴레이 요청 금지.
  4. 비밀 포함 메시지는 전달 거부.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from v7_harness.coord.deliver import (
    GUARD_STALE_S,
    DeliverResult,
    _check_secrets,
    _deliver_to_claude,
    _deliver_to_codex,
    deliver,
)
from v7_harness.coord.mailbox import Mailbox


def _delivery_process(project_text: str, results) -> None:
    runner = FakeRunner(returncode=0, stdout=json.dumps({"result": "accepted", "type": "result"}))
    with patch("v7_harness.coord.deliver.shutil.which", return_value="claude"):
        outcome = deliver(Path(project_text), message="U48-D0 parallel contract", actor="codex",
                          target="claude", runner=runner)
    results.put({"reason": outcome.reason, "calls": len(runner.calls), "id": outcome.message_id})


class FakeRunner:
    """CLI 호출을 가로채는 테스트용 러너."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.calls: list[list[str]] = []
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        return SimpleNamespace(
            returncode=self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
        )


class TestSecretCheck(unittest.TestCase):
    def test_clean_message_passes(self):
        _check_secrets("U47-R1e 857 테스트 통과, 매뉴얼 요청")

    def test_api_key_rejected(self):
        with self.assertRaises(ValueError):
            _check_secrets("api_key=sk-abc1234567890abcdefghij")


class TestDeliverToCodex(unittest.TestCase):
    def test_sends_via_codex_queue(self):
        runner = FakeRunner(returncode=0)
        result = _deliver_to_codex("test message", "thread-123", runner=runner)
        self.assertTrue(result.delivered)
        self.assertEqual(result.target, "codex")
        self.assertEqual(result.reason, "SENT")
        self.assertEqual(len(runner.calls), 1)
        self.assertIn("queue", runner.calls[0])
        self.assertIn("test message", runner.calls[0])

    def test_failure_does_not_ask_user(self):
        runner = FakeRunner(returncode=1, stderr="connection refused")
        result = _deliver_to_codex("test", "thread-1", runner=runner)
        self.assertFalse(result.delivered)
        self.assertEqual(result.target, "codex")
        self.assertIn("DELIVERY_FAILED", result.reason)
        # 핵심: 사용자에게 릴레이를 요청하는 텍스트가 없어야 한다
        self.assertNotIn("전달해 주세요", result.output)
        self.assertNotIn("붙여넣기", result.output)


class TestDeliverToClaude(unittest.TestCase):
    def test_sends_via_claude_cli(self):
        runner = FakeRunner(
            returncode=0,
            stdout=json.dumps({"result": "매뉴얼 수신 완료", "type": "result"}),
        )
        result = _deliver_to_claude("test message", runner=runner)
        self.assertTrue(result.delivered)
        self.assertEqual(result.target, "claude")
        self.assertEqual(result.reason, "SENT")
        self.assertEqual(len(runner.calls), 1)
        self.assertIn("-p", runner.calls[0])

    def test_failure_does_not_ask_user(self):
        runner = FakeRunner(returncode=1, stderr="timeout")
        result = _deliver_to_claude("test", runner=runner)
        self.assertFalse(result.delivered)
        self.assertIn("DELIVERY_FAILED", result.reason)
        self.assertNotIn("전달해 주세요", result.output)
        self.assertNotIn("붙여넣기", result.output)


class TestDeliverAutoRoute(unittest.TestCase):
    """자동 판별: presence에 따라 대상을 고른다."""

    def _mock_presence(self, codex_state: str, claude_state: str):
        def fake_read(project, tool):
            states = {"codex": codex_state, "claude": claude_state}
            return {"state": states.get(tool, "UNKNOWN")}
        return fake_read

    @patch("v7_harness.coord.deliver.shutil.which", return_value="/usr/bin/claude")
    def test_codex_absent_routes_to_claude(self, _mock_which):
        runner = FakeRunner(
            returncode=0,
            stdout=json.dumps({"result": "ok", "type": "result"}),
        )
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / ".coord" / "mailbox").mkdir(parents=True)
            with patch("v7_harness.coord.presence.read", self._mock_presence("LIMITED", "ACTIVE")):
                result = deliver(project, message="테스트", actor="antigravity", runner=runner)
        self.assertFalse(result.delivered)
        self.assertEqual("DISPATCHED", result.reason)
        self.assertEqual(result.target, "claude")
        # Claude CLI가 직접 호출되었는지 확인
        self.assertEqual(len(runner.calls), 1)
        self.assertIn("-p", runner.calls[0])
        sent = runner.calls[0][runner.calls[0].index("-p") + 1]
        self.assertIn(result.message_id, sent)
        self.assertIn(result.digest, sent)

    def test_both_absent_saves_to_mailbox_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / ".coord" / "mailbox").mkdir(parents=True)
            with patch("v7_harness.coord.presence.read", self._mock_presence("ABSENT", "ABSENT")):
                result = deliver(project, message="테스트", actor="antigravity")
        self.assertFalse(result.delivered)
        self.assertEqual(result.target, "mailbox_only")
        self.assertEqual(result.reason, "PUBLISHED")
        # 핵심 불변식: 사용자 릴레이 요청 금지
        self.assertEqual("", result.output)


class TestAntiRelay(unittest.TestCase):
    """사용자에게 수동 릴레이를 부탁하는 문구가 코드에 존재하지 않음을 검증."""

    def test_deliver_module_has_no_user_relay_request(self):
        import v7_harness.coord.deliver as mod
        source = Path(mod.__file__).read_text(encoding="utf-8")
        banned_phrases = [
            "전달해 주세요",
            "붙여넣기해 주세요",
            "전달해주세요",
            "복사해서 전달",
            "대화창에 아래",
            "아래 1줄을 전달",
        ]
        for phrase in banned_phrases:
            self.assertNotIn(
                phrase, source,
                f"deliver.py에 사용자 릴레이 요청 문구 '{phrase}'가 포함되어 있다 — 설계 결함",
            )


class TestDurableDelivery(unittest.TestCase):
    def test_absent_recipient_still_publishes_original_message(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / ".coord" / "mailbox").mkdir(parents=True)
            with patch("v7_harness.coord.presence.read", return_value={"state": "ABSENT"}):
                result = deliver(project, message="U48-D0 fixed contract", actor="codex", target=None)
            self.assertFalse(result.delivered)
            inbox = list((project / ".coord" / "mailbox" / "inbox").glob("*.json"))
            self.assertEqual(1, len(inbox))
            self.assertIn("U48-D0 fixed contract", inbox[0].read_text(encoding="utf-8"))

    def test_cli_exit_zero_is_dispatch_not_receiver_ack(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / ".coord" / "mailbox").mkdir(parents=True)
            runner = FakeRunner(returncode=0, stdout=json.dumps({"result": "ok", "type": "result"}))
            with patch("v7_harness.coord.deliver.shutil.which", return_value="claude"):
                result = deliver(project, message="U48-D0 fixed contract", actor="codex", target="claude", runner=runner)
            self.assertFalse(result.delivered)
            self.assertEqual("DISPATCHED", result.reason)
            self.assertEqual(1, len(list((project / ".coord" / "mailbox" / "inbox").glob("*.json"))))
            self.assertEqual(0, len(list((project / ".coord" / "mailbox" / "ack").glob("*.json"))))

    def test_eight_processes_one_dispatch_and_explicit_ack(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / ".coord" / "mailbox").mkdir(parents=True)
            ctx = multiprocessing.get_context("spawn")
            results = ctx.Queue()
            workers = [ctx.Process(target=_delivery_process, args=(str(project), results)) for _ in range(8)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(15)
                self.assertEqual(0, worker.exitcode)
            outcomes = [results.get(timeout=2) for _ in workers]
            ids = {outcome["id"] for outcome in outcomes}
            self.assertEqual(1, len(ids))
            self.assertEqual(1, sum(outcome["calls"] for outcome in outcomes), outcomes)
            box = Mailbox(project / ".coord" / "mailbox")
            message_id = ids.pop()
            inbox = box.inbox_dir / f"{message_id}.json"
            self.assertTrue(inbox.is_file())
            original = inbox.read_bytes()
            self.assertEqual(1, len(list((box.root / "delivery" / "attempts").glob("*.json"))))
            self.assertFalse((box.ack_dir / f"{message_id}.json").exists())
            claim = box.claim(message_id, "receiver")
            self.assertIsNotNone(claim)
            ack = box.ack(claim)
            self.assertEqual(original, ack.read_bytes())
            result = deliver(project, message="U48-D0 parallel contract", actor="codex", target="claude")
            self.assertTrue(result.delivered)
            self.assertEqual("ACKED", result.reason)

    def test_failed_attempt_is_retained_and_retryable(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / ".coord" / "mailbox").mkdir(parents=True)
            with patch("v7_harness.coord.deliver.shutil.which", return_value="claude"):
                first = deliver(project, message="retry contract", actor="codex", target="claude",
                                runner=FakeRunner(returncode=1, stderr="connection refused"))
                second = deliver(project, message="retry contract", actor="codex", target="claude",
                                 runner=FakeRunner(returncode=0, stdout=json.dumps({"result": "ok"})))
            self.assertIn("DELIVERY_FAILED", first.reason)
            self.assertEqual("DISPATCHED", second.reason)
            self.assertEqual(first.message_id, second.message_id)
            attempts = list((project / ".coord" / "mailbox" / "delivery" / "attempts").glob("*.json"))
            self.assertEqual(2, len(attempts))
            self.assertTrue((project / ".coord" / "mailbox" / "inbox" /
                             f"{first.message_id}.json").is_file())


def _guard_for(project: Path, message: str, actor: str = "codex") -> Path:
    digest = hashlib.sha256((actor + "\0" + message).encode("utf-8")).hexdigest()
    guard = project / ".coord" / "mailbox" / "delivery" / "guards" / f"relay_{digest[:32]}.lock"
    guard.parent.mkdir(parents=True, exist_ok=True)
    guard.write_text("{}", encoding="utf-8")
    return guard


def _age(path: Path, seconds: float) -> None:
    old = time.time() - seconds
    os.utime(path, (old, old))


class TestGuardRecovery(unittest.TestCase):
    """U48-D0 re-review (Claude, 2026-09-27): a guard left by a crashed dispatcher must not block the message."""

    def test_fresh_guard_is_in_flight_but_message_is_published(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / ".coord" / "mailbox").mkdir(parents=True)
            guard = _guard_for(project, "held contract")
            runner = FakeRunner(returncode=0, stdout=json.dumps({"result": "ok"}))
            with patch("v7_harness.coord.deliver.shutil.which", return_value="claude"):
                result = deliver(project, message="held contract", actor="codex", target="claude", runner=runner)
            self.assertEqual("IN_FLIGHT", result.reason)
            self.assertEqual([], runner.calls)
            self.assertTrue(guard.is_file())  # a live holder's guard is never touched
            inbox = project / ".coord" / "mailbox" / "inbox" / f"{result.message_id}.json"
            self.assertIn("held contract", inbox.read_text(encoding="utf-8"))

    def test_aged_guard_is_recovered_once_with_a_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / ".coord" / "mailbox").mkdir(parents=True)
            guard = _guard_for(project, "crashed contract")
            _age(guard, GUARD_STALE_S + 100)
            runner = FakeRunner(returncode=0, stdout=json.dumps({"result": "ok"}))
            with patch("v7_harness.coord.deliver.shutil.which", return_value="claude"):
                result = deliver(project, message="crashed contract", actor="codex", target="claude", runner=runner)
            self.assertEqual("DISPATCHED", result.reason)
            self.assertEqual(1, len(runner.calls))
            guards = guard.parent
            self.assertFalse(guard.exists())
            self.assertEqual(1, len(list(guards.glob(f"{guard.name}.stale-*"))))  # preserved, not deleted
            self.assertEqual([], list(guards.glob("*.recover")))
            attempts = project / ".coord" / "mailbox" / "delivery" / "attempts"
            states = [json.loads(p.read_text(encoding="utf-8")).get("state") for p in attempts.glob("*.json")]
            self.assertEqual(1, states.count("GUARD_RECOVERED"))

    def test_eight_processes_recover_an_aged_guard_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / ".coord" / "mailbox").mkdir(parents=True)
            guard = _guard_for(project, "U48-D0 parallel contract")
            _age(guard, GUARD_STALE_S + 100)
            ctx = multiprocessing.get_context("spawn")
            results = ctx.Queue()
            workers = [ctx.Process(target=_delivery_process, args=(str(project), results)) for _ in range(8)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(15)
                self.assertEqual(0, worker.exitcode)
            outcomes = [results.get(timeout=2) for _ in workers]
            self.assertEqual(1, sum(outcome["calls"] for outcome in outcomes), outcomes)
            self.assertEqual(1, len(list(guard.parent.glob(f"{guard.name}.stale-*"))))


if __name__ == "__main__":
    unittest.main()
