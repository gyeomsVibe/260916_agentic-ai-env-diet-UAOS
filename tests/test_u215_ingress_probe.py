"""U215: a letter with no ingress 10 s after dispatch probes the receiver's usage and replans when it is limited.

Receipt (2026-10-18): Codex stopped on its usage limit while relay_293188f2 (U214-W verdict) waited; nothing replanned
until the user noticed. User order: "메시지를 보냈을 때 10초 이상 회신이 안 온다면, 상대 도구의 사용량을 조사하고 그에
대비해 계획을 수정하는 로직". A paid reply takes 22-24 s (E5), so the 10 s deadline is on ingress (the receiver's turn
started: presence observed_at after dispatch), not on the reply. The probe is the presence record, which already turns
Codex's rollout usage_limit_exceeded into LIMITED (presence.codex_quota_block); UNKNOWN never reroutes.
"""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from v7_harness.coord import ingress, stall

T0 = 1_792_300_000.0


def _iso(epoch):
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _wait(since=T0):
    return {"item": "letter:codex:relay_a", "kind": "verdict", "waiting_on": "codex", "author": "claude",
            "since": since, "pr": ""}


class Decide(unittest.TestCase):
    def test_before_the_deadline_nothing_happens(self):
        self.assertEqual("WAIT", ingress.decide(_wait(), {"state": "LIMITED", "observed_at": _iso(T0 - 60)}, T0 + 9))

    def test_a_limited_receiver_without_ingress_is_rerouted(self):
        self.assertEqual("REROUTE",
                         ingress.decide(_wait(), {"state": "LIMITED", "observed_at": _iso(T0 - 60)}, T0 + 10))

    def test_ingress_after_dispatch_means_no_probe(self):
        self.assertEqual("WAIT", ingress.decide(_wait(), {"state": "LIMITED", "observed_at": _iso(T0 + 3)}, T0 + 30))

    def test_an_active_receiver_without_ingress_is_only_lag(self):
        self.assertEqual("LAG", ingress.decide(_wait(), {"state": "ACTIVE", "observed_at": _iso(T0 - 60)}, T0 + 30))

    def test_unknown_presence_never_reroutes(self):
        self.assertEqual("LAG", ingress.decide(_wait(), {"state": "UNKNOWN"}, T0 + 30))

    def test_a_phase_wait_is_not_an_ingress_wait(self):
        wait = {**_wait(), "item": "phase:P1"}
        self.assertEqual("WAIT", ingress.decide(wait, {"state": "LIMITED"}, T0 + 30))

    def test_limit_shrinks_only_on_reroute(self):
        limited = {"state": "LIMITED", "observed_at": _iso(T0 - 60)}
        self.assertEqual(ingress.INGRESS_DEADLINE_S, ingress.limit(_wait(), limited, T0 + 10, 1800))
        self.assertEqual(1800, ingress.limit(_wait(), {"state": "ACTIVE"}, T0 + 10, 1800))


class ScanReplans(unittest.TestCase):
    """End to end: a verdict request to a limited Codex is adopted by the next capable tool after 10 s, not 30 min."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        box = self.root / ".coord" / "mailbox"
        for sub in ("inbox", "ack", "delivery/accepted"):
            (box / sub).mkdir(parents=True)
        (self.root / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        (self.root / ".coord" / "stall").mkdir()
        (self.root / ".coord" / "stall" / "watermark.json").write_text(json.dumps({"since": T0 - 100}),
                                                                         encoding="utf-8")
        body = {"actor": "claude", "requested_target": "codex", "wake_class": "ACTIONABLE",
                "verdict_requested": True, "message": "verdict please"}
        (box / "inbox" / "relay_a.json").write_text(json.dumps({"payload": body}), encoding="utf-8")
        (box / "delivery" / "accepted" / "relay_a.json").write_text(
            json.dumps({"timestamp_ns": int(T0 * 1e9)}), encoding="utf-8")

    def _desk(self, codex_state):
        return {"codex": {"state": codex_state, "observed_at": _iso(T0 - 60)},
                "claude": {"state": "ACTIVE", "observed_at": _iso(T0)},
                "antigravity": {"state": "ACTIVE", "observed_at": _iso(T0)}}

    def test_limited_codex_is_replanned_after_ten_seconds(self):
        result = stall.scan(self.root, "claude", now=T0 + 11, desk=self._desk("LIMITED"))
        self.assertEqual(["letter:codex:relay_a"], [e["item"] for e in result["stalled"]])
        self.assertIn({"item": "letter:codex:relay_a", "decision": "REROUTE"}, result["ingress"])

    def test_active_codex_keeps_the_long_wait(self):
        result = stall.scan(self.root, "claude", now=T0 + 11, desk=self._desk("ACTIVE"))
        self.assertEqual([], result["stalled"])
        self.assertIn({"item": "letter:codex:relay_a", "decision": "LAG"}, result["ingress"])


if __name__ == "__main__":
    unittest.main()
