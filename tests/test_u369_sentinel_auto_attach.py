"""U369: the resident sentinel cycle reconciles the auto-attach queue and the verdict-request SLAs.

Receipt: U337 shipped auto_attach.reconcile_once and reconcile_verdict_requests and U368 made the live prompt hook
enqueue cards, but no resident loop called either reconcile, so a WAITING card stayed blocked and an un-ACKed verdict
request never failed over until some tool ran a manual pass. Each TestU369SentinelAutoAttach test maps one row of the
U369 contract section 5 failure-mode table. All fixtures live in a temporary project; no model, network or subprocess
is used, and a root with no auto-attach state must stay untouched.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v7_harness.coord import auto_attach, sentinel  # noqa: E402
from v7_harness.coord.mailbox import Mailbox  # noqa: E402

FAR = 100_000.0  # participation and presence outlive every simulated clock step below


def _tree(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*")}


class TestU369SentinelAutoAttach(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord" / "mailbox").mkdir(parents=True, exist_ok=True)
        self.t0 = time.time()
        self._env = mock.patch.dict(os.environ, {})
        self._env.start()
        for name in ("UAOS_WORKER", "UAOS_AUTO_ATTACH"):
            os.environ.pop(name, None)

    def tearDown(self) -> None:
        self._env.stop()
        self._tmp.cleanup()

    def _admission(self, presence: dict[str, str] | None = None, pools: bool = False) -> None:
        coord = self.project / ".coord"
        (coord / "presence").mkdir(parents=True, exist_ok=True)
        snap = {"mode": "TRIO", "roles": {t: "EXECUTOR" for t in auto_attach.TOOLS},
                "decided_at": self.t0, "expires_at": self.t0 + FAR}
        (coord / "participation.json").write_text(json.dumps(snap), encoding="utf-8")
        states = {t: "ACTIVE" for t in auto_attach.TOOLS}
        states.update(presence or {})
        for tool, state in states.items():
            (coord / "presence" / f"{tool}.json").write_text(
                json.dumps({"tool": tool, "state": state, "expires_at": self.t0 + FAR}), encoding="utf-8")
        if pools:
            folder = coord / "auto_attach" / "pools"
            folder.mkdir(parents=True, exist_ok=True)
            for tool in auto_attach.TOOLS:
                (folder / f"{tool}.json").write_text(json.dumps(
                    {"tool": tool, "state": "FRESH", "observed_at": self.t0 - 5.0,
                     "expires_at": self.t0 + 300.0}), encoding="utf-8")

    def _reconcile(self, now: float) -> object:
        return sentinel.reconcile_sentinel_auto_attach(self.project, now=now)

    def _cycle(self) -> dict:
        return sentinel.run_sentinel_cycle(self.project, Mailbox(self.project / ".coord" / "mailbox"))

    def test_peer_silent_limit_exhausted_regime(self) -> None:
        self._admission(pools=True)
        card = auto_attach.enqueue_from_prompt(self.project, "claude", "Fix pkg/a.py", session="s1", now=self.t0)
        req = auto_attach.create_verdict_request(self.project, card_id=card["card_id"], author="claude",
                                                 req_id="R1", preferred_judge="antigravity", now=self.t0)
        self.assertEqual(req["current_judge"], "antigravity")
        self._admission({"antigravity": "LIMITED"}, pools=True)
        with mock.patch("subprocess.Popen", side_effect=AssertionError("no launch")), \
                mock.patch("subprocess.run", side_effect=AssertionError("no launch")):
            first = self._reconcile(self.t0 + auto_attach.ACK_SLA_S + 1)
            self._admission({"antigravity": "LIMITED", "codex": "LIMITED"}, pools=True)
            second = self._reconcile(self.t0 + 2 * auto_attach.ACK_SLA_S + 3)
        self.assertEqual(first["verdicts"]["rerouted"], [{"req_id": "R1", "from": "antigravity", "to": "codex"}])
        self.assertEqual(first["cards"]["peers"][f"{card['card_id']}.codex"],
                         {"status": "NOT_ADMITTED", "reason": "NO_ADAPTER"})
        self.assertEqual(second["verdicts"]["exhausted"], ["R1"])
        doc = auto_attach.read_verdict_request(self.project, "R1")
        self.assertEqual(doc["state"], "EXHAUSTED_WAIT_RESET")
        self.assertEqual(doc["tried_tools"], ["antigravity", "codex"])
        self.assertGreater(doc["next_wake_at"], self.t0 + 2 * auto_attach.ACK_SLA_S + 3)

    def test_message_flood_bounded_processing(self) -> None:
        self._admission()
        ids = [auto_attach.enqueue_from_prompt(self.project, "codex", f"Fix pkg/m{i}.py", session=f"s{i}",
                                               now=self.t0)["card_id"] for i in range(101)]
        for i in range(101):
            auto_attach.create_verdict_request(self.project, card_id=ids[i], author="codex", req_id=f"R{i:03d}",
                                               preferred_judge="claude", now=self.t0)
        started = time.monotonic()
        result = self._reconcile(self.t0 + auto_attach.ACK_SLA_S + 1)
        self.assertLess(time.monotonic() - started, 60.0)
        peers = result["cards"]["peers"]
        self.assertEqual(len(peers), 202)
        self.assertEqual(list(peers)[::2], [f"{cid}.claude" for cid in ids])
        self.assertTrue(all(v["status"] == "NOT_ADMITTED" for v in peers.values()))
        self.assertEqual(len(result["verdicts"]["rerouted"]), 101)
        self.assertEqual({r["to"] for r in result["verdicts"]["rerouted"]}, {"antigravity"})
        self.assertEqual([item["card_id"] for item in auto_attach.read_queue(self.project)], ids)

    def test_wait_cycle_deadlock_unblock_safety(self) -> None:
        first = auto_attach.enqueue_from_prompt(self.project, "codex", "Fix pkg/a.py", session="s1")
        second = auto_attach.enqueue_from_prompt(self.project, "claude", "Fix pkg/a.py", session="s2")
        self.assertEqual(second["state"], "WAITING")
        for _ in range(3):
            result = self._cycle()
            self.assertEqual(result["paid_api_calls"], 0)
            self.assertEqual(result["auto_attach"]["cards"]["unblocked"], [])
            self.assertEqual(result["auto_attach"]["cards"]["skipped_cards"][second["card_id"]],
                             "WAITING_FILE_OVERLAP")
        card = auto_attach.read_card(self.project, second["card_id"])
        self.assertEqual((card["state"], card["blocked_by"]), ("WAITING", first["card_id"]))
        auto_attach.stop_card(self.project, first["card_id"])
        result = self._cycle()
        self.assertEqual(result["auto_attach"]["cards"]["unblocked"], [second["card_id"]])
        self.assertEqual(auto_attach.read_card(self.project, second["card_id"])["state"], "PENDING")

    def test_crash_mid_write_exception_captured(self) -> None:
        folder = self.project / ".coord" / "auto_attach"
        (folder / "verdicts").mkdir(parents=True)
        (folder / "queue.json").write_text('[{"card_id": "AA-1', encoding="utf-8")
        (folder / "verdicts" / "broken.json").write_text('{"req_id": "R', encoding="utf-8")
        result = self._reconcile(self.t0)
        self.assertEqual(result["cards"]["peers"], {})
        self.assertEqual(result["verdicts"]["open_waits"], [])
        (folder / "verdicts" / "torn.json").write_text(json.dumps({"state": "AWAITING_ACK"}), encoding="utf-8")
        self.assertEqual(self._reconcile(self.t0), {"error": "KeyError: 'req_id'"})
        with mock.patch.object(auto_attach, "reconcile_once", side_effect=RuntimeError("torn queue")):
            result = self._cycle()
        self.assertEqual(result["auto_attach"], {"error": "RuntimeError: torn queue"})
        self.assertEqual(result["paid_api_calls"], 0)

    def test_duplicate_delivery_idempotent_reconcile(self) -> None:
        self._admission()
        first = auto_attach.enqueue_from_prompt(self.project, "codex", "Fix pkg/a.py", session="s1", now=self.t0)
        second = auto_attach.enqueue_from_prompt(self.project, "claude", "Fix pkg/a.py", session="s2", now=self.t0)
        auto_attach.create_verdict_request(self.project, card_id=second["card_id"], author="claude", req_id="R1",
                                           preferred_judge="antigravity", now=self.t0)
        auto_attach.stop_card(self.project, first["card_id"], now=self.t0)
        now = self.t0 + auto_attach.ACK_SLA_S + 1
        barrier = threading.Barrier(4)
        results: list[object] = []

        def run() -> None:
            barrier.wait()
            results.append(self._reconcile(now))

        threads = [threading.Thread(target=run) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        self.assertEqual(len(results), 4)
        self.assertFalse([r for r in results if "error" in r])
        unblocked = [cid for r in results for cid in r["cards"]["unblocked"]]
        rerouted = [x for r in results for x in r["verdicts"]["rerouted"]]
        self.assertEqual(unblocked, [second["card_id"]])
        self.assertEqual(rerouted, [{"req_id": "R1", "from": "antigravity", "to": "codex"}])
        self.assertEqual(auto_attach.read_verdict_request(self.project, "R1")["hops"], 1)

    def test_stale_state_verdict_sla_hedge(self) -> None:
        self._admission()
        auto_attach.create_verdict_request(self.project, card_id="C1", author="claude", req_id="R1",
                                           preferred_judge="antigravity", now=self.t0)
        self.assertTrue(auto_attach.ack_verdict_request(self.project, "R1", "antigravity", now=self.t0 + 1)["ok"])
        self.assertEqual(self._reconcile(self.t0 + 30)["verdicts"]["hedged"], [])
        result = self._reconcile(self.t0 + auto_attach.VERDICT_SLA_S + 2)
        self.assertEqual(result["verdicts"]["hedged"], [{"req_id": "R1", "judges": ["antigravity", "codex"]}])
        self.assertEqual(auto_attach.read_verdict_request(self.project, "R1")["state"], "TIED_HEDGED")
        won = auto_attach.submit_verdict(self.project, "R1", judge="codex", verdict="PASS",
                                         now=self.t0 + auto_attach.VERDICT_SLA_S + 3)
        self.assertTrue(won["won"])
        self.assertEqual(self._reconcile(self.t0 + auto_attach.VERDICT_SLA_S + 4)["verdicts"]["open_waits"], [])

    def test_conductor_down_non_author_judge_routing(self) -> None:
        self._admission({"codex": "ABSENT"})
        req = auto_attach.create_verdict_request(self.project, card_id="C1", author="claude", req_id="R1",
                                                 preferred_judge="codex", now=self.t0)
        self.assertEqual(req["current_judge"], "antigravity")
        result = self._reconcile(self.t0 + auto_attach.ACK_SLA_S + 1)
        self.assertEqual(result["verdicts"]["exhausted"], ["R1"])
        doc = auto_attach.read_verdict_request(self.project, "R1")
        self.assertEqual(doc["state"], "EXHAUSTED_WAIT_RESET")
        self.t0 = float(doc["next_wake_at"])  # the conductor returns at its reset; snapshots are fresh from then
        self._admission()
        result = self._reconcile(self.t0 + 1)
        self.assertEqual(result["verdicts"]["rerouted"], [{"req_id": "R1", "from": None, "to": "antigravity"}])
        doc = auto_attach.read_verdict_request(self.project, "R1")
        self.assertEqual(doc["state"], "AWAITING_ACK")
        self.assertNotIn("claude", doc["tried_tools"] + [doc["current_judge"]])

    def test_user_absent_idle_no_queue_zero_pollution(self) -> None:
        before = _tree(self.project)
        with mock.patch.object(auto_attach, "reconcile_once", side_effect=AssertionError("must not run")), \
                mock.patch.object(auto_attach, "reconcile_verdict_requests",
                                  side_effect=AssertionError("must not run")):
            self.assertEqual(self._reconcile(self.t0), "IDLE_NO_QUEUE")
            self.assertEqual(_tree(self.project), before)
            result = self._cycle()
        self.assertEqual(result["auto_attach"], "IDLE_NO_QUEUE")
        self.assertEqual(result["paid_api_calls"], 0)
        self.assertFalse((self.project / ".coord" / "auto_attach").exists())

    def test_disabled_env_records_disabled_without_files(self) -> None:
        folder = self.project / ".coord" / "auto_attach"
        (folder / "verdicts").mkdir(parents=True)
        (folder / "queue.json").write_text("[]", encoding="utf-8")
        before = _tree(self.project)
        os.environ["UAOS_AUTO_ATTACH"] = " 0 "
        with mock.patch.object(auto_attach, "reconcile_once", side_effect=AssertionError("must not run")):
            self.assertEqual(self._reconcile(self.t0), "DISABLED")
            self.assertEqual(self._cycle()["auto_attach"], "DISABLED")
        self.assertEqual(_tree(folder), {"verdicts", "queue.json"})
        self.assertTrue(before <= _tree(self.project))


if __name__ == "__main__":
    unittest.main()
