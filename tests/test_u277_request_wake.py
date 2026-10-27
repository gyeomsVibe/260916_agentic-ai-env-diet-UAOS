"""U277 rev 2 (H1+H2): a verdict request is durable, an exact answer wakes its requester once, a fuzzy hint never closes
a request, the turn end is held while a request is open, and a dispatched request counts as a stall wait.

Receipt (2026-10-27, CLAUDE-WAKE-GAP-PR249): a verdict request returned DISPATCHED, the answer came back as a
`coord log --kind BLOCKED` row, and the requester never woke. These tests use real temp project folders, the real
stream writer (`stream.append_event`) and real watcher processes; only the clock is passed in where a test needs it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v7_harness.coord import stream  # noqa: E402

SHA = "09e49ee355605ddd83bc9c0aaaa9d3de77530b77"
PR = "https://github.com/o/r/pull/249"


def _project() -> tuple[tempfile.TemporaryDirectory, Path]:
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    (root / ".coord").mkdir()
    (root / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
    return tmp, root


def _register(root: Path, request_id: str, *, session: str = "sA", now: float | None = None) -> dict:
    from v7_harness.coord import requests

    row = requests.register(root, request_id=request_id, requester="claude", target="codex", card="U275",
                            subject=PR, head=SHA, requester_session=session, now=now)
    requests.mark_delivered(root, request_id, "DISPATCHED")
    return row


def _answer(root: Path, request_id: str, *, actor: str = "codex", kind: str = "BLOCKED",
            outcome: str = "BLOCKED") -> None:
    stream.append_event(root, actor=actor, kind=kind, step="U277-TEST", summary="answer",
                        refs=[f"request:{request_id}"], evidence={"outcome": outcome} if outcome else {})


def _lease(root: Path, session: str, *, expires_in: float = 60.0, pid: int | None = None) -> None:
    from v7_harness.coord import watch

    pid = os.getpid() if pid is None else pid
    target = watch.watch_file(root, "claude")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"tool": "claude", "token": "t", "pid": pid,
                                  "process_created": watch.process_identity(pid),
                                  "expires_at": time.time() + expires_in, "wakes_session": True,
                                  "session": session, "adapter": "claude-bg-task"}), encoding="utf-8")


class RegistryTests(unittest.TestCase):
    def test_register_is_idempotent_and_conflicting_binding_is_refused(self) -> None:
        from v7_harness.coord import requests

        tmp, root = _project()
        with tmp:
            now = time.time()
            first = requests.register(root, request_id="relay_r1", requester="claude", target="codex", card="U275",
                                      subject=PR, head=SHA, requester_session="sA", now=now)
            again = requests.register(root, request_id="relay_r1", requester="claude", target="codex", card="U275",
                                      subject=PR, head=SHA, requester_session="sA", now=now + 50)
            self.assertEqual(first["rev"], again["rev"])
            with self.assertRaises(requests.RequestError) as cm:
                requests.register(root, request_id="relay_r1", requester="claude", target="codex", card="U275",
                                  subject=PR, head="1" * 40, requester_session="sA", now=now)
            self.assertEqual(cm.exception.code, "REQUEST_ID_CONFLICT")

    def test_exact_answer_moves_only_its_request(self) -> None:
        from v7_harness.coord import requests

        tmp, root = _project()
        with tmp:
            _register(root, "relay_a")
            _register(root, "relay_b")
            _answer(root, "relay_a", outcome="REVISE")
            requests.scan(root)
            self.assertEqual(requests.get(root, "relay_a")["state"], "ANSWER_OBSERVED")
            self.assertEqual(requests.get(root, "relay_a")["outcome"], "REVISE")
            self.assertEqual(requests.get(root, "relay_b")["state"], "OPEN")

    def test_note_and_wrong_actor_never_answer(self) -> None:
        from v7_harness.coord import requests

        tmp, root = _project()
        with tmp:
            _register(root, "relay_n")
            _answer(root, "relay_n", actor="antigravity")
            _answer(root, "relay_n", kind="NOTE", outcome="")
            requests.scan(root)
            self.assertEqual(requests.get(root, "relay_n")["state"], "OPEN")

    def test_pending_delivery_reconciles_from_accepted_receipt(self) -> None:
        from v7_harness.coord import requests

        tmp, root = _project()
        with tmp:
            requests.register(root, request_id="relay_p", requester="claude", target="codex", card="U275",
                              subject=PR, head=SHA, requester_session="sA")
            accepted = root / ".coord" / "mailbox" / "delivery" / "accepted"
            accepted.mkdir(parents=True)
            (accepted / "relay_p.json").write_text("{}", encoding="utf-8")
            requests.reconcile(root)
            row = requests.get(root, "relay_p")
            self.assertEqual((row["state"], row["delivery"]), ("OPEN", "DISPATCHED"))

    def test_registry_failure_refuses_deliver_and_sends_nothing(self) -> None:
        from v7_harness.coord import deliver

        tmp, root = _project()
        with tmp:
            (root / ".coord" / "requests").write_text("not a directory", encoding="utf-8")
            calls: list[tuple] = []

            def runner(*args, **kwargs):
                calls.append(args)
                raise AssertionError("dispatch must not run when the request cannot be recorded")

            result = deliver.deliver(root, message="please judge U275 PR249", actor="claude", target="codex",
                                     card="U275", verdict_requested=True, runner=runner)
            self.assertFalse(result.delivered)
            self.assertEqual(result.reason, "REQUEST_TRACKING_FAILED")
            self.assertEqual(calls, [])
            inbox = root / ".coord" / "mailbox" / "inbox"
            self.assertFalse(inbox.exists() and any(inbox.glob("*.json")))


class WakeTests(unittest.TestCase):
    def test_claim_has_one_winner_across_real_processes(self) -> None:
        from v7_harness.coord import requests

        tmp, root = _project()
        with tmp:
            _register(root, "relay_mp")
            _answer(root, "relay_mp")
            requests.scan(root)
            # Each child records its start before the shared "go" file, so every claim is later than every start.
            code = ("import json,sys,time;from pathlib import Path;root=Path(sys.argv[1]);started=time.time();"
                    "(root/('ready_'+sys.argv[2])).write_text('1');"
                    "go=root/'go'\nwhile not go.exists():\n    time.sleep(0.01)\n"
                    "sys.path.insert(0,sys.argv[3]);from v7_harness.coord import requests;"
                    "print(json.dumps(requests.claim_wake(root,'relay_mp',session='sA',started_at=started)))")
            procs = [subprocess.Popen([sys.executable, "-c", code, str(root), str(i), str(ROOT)],
                                      stdout=subprocess.PIPE, text=True) for i in range(4)]
            deadline = time.time() + 60
            while time.time() < deadline and sum((root / f"ready_{i}").exists() for i in range(4)) < 4:
                time.sleep(0.02)
            (root / "go").write_text("1")
            outs = [json.loads(proc.communicate(timeout=60)[0].strip().splitlines()[-1]) for proc in procs]
            self.assertEqual(outs.count(True), 1, outs)
            self.assertEqual(requests.get(root, "relay_mp")["state"], "WAKE_PENDING")

    def test_ack_is_session_bound_and_idempotent(self) -> None:
        from v7_harness.coord import requests

        tmp, root = _project()
        with tmp:
            _register(root, "relay_k")
            _answer(root, "relay_k")
            requests.scan(root)
            self.assertTrue(requests.claim_wake(root, "relay_k", session="sA"))
            with self.assertRaises(requests.RequestError) as cm:
                requests.ack(root, "relay_k", session="sB")
            self.assertEqual(cm.exception.code, "ACK_SESSION_MISMATCH")
            self.assertEqual(requests.ack(root, "relay_k", session="sA"), "ACKED")
            self.assertEqual(requests.ack(root, "relay_k", session="sA"), "ALREADY")
            self.assertEqual(requests.open_for(root, "claude", session="sA"), [])

    def test_fuzzy_hint_wakes_once_and_keeps_request_open(self) -> None:
        from v7_harness.coord import requests, watch

        tmp, root = _project()
        with tmp:
            _register(root, "relay_h", now=time.time() - 5)
            stream.append_event(root, actor="codex", kind="BLOCKED", step="U275",
                                summary="PR249 missing check; head 09e49ee REVISE", refs=[], evidence={})
            first = watch.watch(root, ("claude",), timeout_s=3, interval_s=0.2, wakes_session=True,
                                requester_session="sA")
            self.assertEqual((first or {}).get("reason"), "REQUEST_HINT")
            self.assertEqual(requests.get(root, "relay_h")["state"], "OPEN")
            second = watch.watch(root, ("claude",), timeout_s=1.0, interval_s=0.2, wakes_session=True,
                                 requester_session="sA")
            self.assertTrue(second is None or second.get("reason") not in ("REQUEST_HINT", "REQUEST_ANSWERED"))


class StopHoldTests(unittest.TestCase):
    def test_hold_blocks_once_releases_on_live_watcher_and_logs_fallback(self) -> None:
        from v7_harness.coord import stop_gate

        tmp, root = _project()
        with tmp:
            _register(root, "relay_s")
            first = stop_gate.gate(root, "claude", session="sA")
            self.assertEqual((first or {}).get("decision"), "block")
            self.assertIn("relay_s", first.get("reason", ""))
            _lease(root, "sA")
            self.assertIsNone(stop_gate.gate(root, "claude", session="sA"))
            _lease(root, "sA", expires_in=-5)
            self.assertEqual((stop_gate.gate(root, "claude", session="sA") or {}).get("decision"), "block")
            for _ in range(5):
                if stop_gate.gate(root, "claude", session="sA") is None:
                    break
            self.assertIsNone(stop_gate.gate(root, "claude", session="sA"))
            events = stream.read_events(root)
            self.assertTrue(any("STOP_UNGUARDED" in e.get("summary", "") and "request:relay_s" in e.get("refs", [])
                                for e in events), events)

    def test_foreign_session_lease_does_not_release_the_hold(self) -> None:
        from v7_harness.coord import stop_gate

        tmp, root = _project()
        with tmp:
            _register(root, "relay_f")
            _lease(root, "sB")
            self.assertEqual((stop_gate.gate(root, "claude", session="sA") or {}).get("decision"), "block")

    def test_registry_error_never_blocks(self) -> None:
        from v7_harness.coord import stop_gate

        tmp, root = _project()
        with tmp:
            (root / ".coord" / "requests").write_text("not a directory", encoding="utf-8")
            self.assertIsNone(stop_gate._request_hold(root, "claude", "sA"))


class StallTests(unittest.TestCase):
    def test_dispatched_open_request_is_a_stall_wait(self) -> None:
        from v7_harness.coord import stall

        tmp, root = _project()
        with tmp:
            _register(root, "relay_t")
            waits = stall._letter_waits(root)
            self.assertTrue(any(w["item"] == "request:codex:relay_t" for w in waits), waits)


if __name__ == "__main__":
    unittest.main()
