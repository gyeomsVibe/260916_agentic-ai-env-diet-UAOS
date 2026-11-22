"""U370: the auto-attach prompt path feeds the U350 ideas intake and carries its deterministic P0/P1/P2 priority.

Receipt: U337/U368 enqueue a companion card for every live work prompt, but the card had no priority and the
prompt never reached `.coord/intake/ideas.jsonl`, so the C33 classifier and the C34 audited queue were dead code on
the live path. Each TestU370IntakeAutoAttach test maps one row of the U370 contract section 5 failure-mode table.
All fixtures live in a temporary project; no model, network or subprocess is used.
"""

from __future__ import annotations

import ast
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

from v7_harness.coord import auto_attach, intake  # noqa: E402

FAR = 100_000.0  # presence outlives every simulated clock step below


class TestU370IntakeAutoAttach(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.project = Path(self._tmp.name) / "proj"
        self.project.mkdir(parents=True)
        self.t0 = time.time()
        self._env = mock.patch.dict(os.environ, {})
        self._env.start()
        for name in ("UAOS_WORKER", "UAOS_AUTO_ATTACH"):
            os.environ.pop(name, None)

    def tearDown(self) -> None:
        self._env.stop()
        self._tmp.cleanup()

    def _presence(self, states: dict[str, str]) -> None:
        folder = self.project / ".coord" / "presence"
        folder.mkdir(parents=True, exist_ok=True)
        for tool, state in states.items():
            (folder / f"{tool}.json").write_text(
                json.dumps({"tool": tool, "state": state, "expires_at": self.t0 + FAR}), encoding="utf-8")

    def _queue_item(self, card_id: str) -> dict:
        return next(item for item in auto_attach.read_queue(self.project) if item["card_id"] == card_id)

    def test_peer_silent_zero_token_prioritization(self) -> None:
        self._presence({"codex": "LIMITED", "antigravity": "ABSENT", "claude": "ACTIVE"})
        with mock.patch("subprocess.Popen", side_effect=AssertionError("no launch")), \
                mock.patch("subprocess.run", side_effect=AssertionError("no launch")):
            res = auto_attach.hook_on_prompt(self.project, "claude", "긴급 Fix pkg/a.py", session="s1",
                                             now=self.t0)
        self.assertEqual((res["action"], res["priority"], res["intake_seq"]), ("ENQUEUED", "P0", 1))
        card = auto_attach.read_card(self.project, res["card_id"])
        self.assertEqual((card["priority"], card["intake_seq"]), ("P0", 1))
        self.assertEqual((self._queue_item(res["card_id"])["priority"], self._queue_item(res["card_id"])["intake_seq"]),
                         ("P0", 1))
        rows = intake.read_ideas(self.project)
        self.assertEqual([(r["seq"], r["source"], r["priority"], r["text"]) for r in rows],
                         [(1, "claude", "P0", "긴급 Fix pkg/a.py")])

    def test_message_flood_queue_shed_handled_safely(self) -> None:
        cap = intake.QUEUE_CAP
        folder = self.project / ".coord" / "intake"
        folder.mkdir(parents=True)
        backlog = [{"seq": i, "text": f"old idea {i}", "source": "user", "priority": "P1", "at": self.t0}
                   for i in range(1, cap - 1)]  # two free slots left before the real 500-row cap
        (folder / "ideas.jsonl").write_text("".join(json.dumps(r) + "\n" for r in backlog), encoding="utf-8")
        results = [auto_attach.enqueue_from_prompt(self.project, "codex", f"Fix pkg/m{i}.py", session=f"s{i}",
                                                   now=self.t0) for i in range(5)]
        self.assertEqual([r["action"] for r in results], ["ENQUEUED"] * 5)
        self.assertEqual([r["intake_seq"] for r in results], [cap - 1, cap, None, None, None])
        self.assertEqual({r["priority"] for r in results}, {"P1"})
        self.assertEqual(len(intake.read_ideas(self.project)), cap)
        shed = intake.read_shed(self.project)
        self.assertEqual([(s["event"], s["text"], s["cap"]) for s in shed],
                         [("QUEUE_SHED", f"Fix pkg/m{i}.py", cap) for i in (2, 3, 4)])
        self.assertEqual(len(auto_attach.read_queue(self.project)), 5)
        self.assertEqual(auto_attach.read_card(self.project, results[4]["card_id"])["priority"], "P1")

    def test_wait_cycle_lock_hierarchy_deadlock_free(self) -> None:
        tree = ast.parse((REPO_ROOT / "v7_harness" / "coord" / "intake.py").read_text(encoding="utf-8"))
        imported = {getattr(node, "module", None) or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imported |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        self.assertFalse([name for name in imported if "auto_attach" in name])
        barrier = threading.Barrier(8)
        errors: list[BaseException] = []

        def via_attach(i: int) -> None:
            barrier.wait()
            try:
                auto_attach.enqueue_from_prompt(self.project, "claude", f"Fix pkg/w{i}.py", session=f"w{i}")
            except BaseException as exc:  # noqa: BLE001 - collected and asserted below
                errors.append(exc)

        def via_intake(i: int) -> None:
            barrier.wait()
            try:
                intake.append_idea(self.project, f"direct idea {i}", source="user")
            except BaseException as exc:  # noqa: BLE001 - collected and asserted below
                errors.append(exc)

        threads = [threading.Thread(target=via_attach, args=(i,)) for i in range(4)]
        threads += [threading.Thread(target=via_intake, args=(i,)) for i in range(4)]
        started = time.monotonic()
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        self.assertFalse([t for t in threads if t.is_alive()])
        self.assertLess(time.monotonic() - started, 60.0)
        self.assertEqual(errors, [])
        rows = intake.read_ideas(self.project)
        self.assertEqual(sorted(r["seq"] for r in rows), list(range(1, 9)))
        queue = auto_attach.read_queue(self.project)
        self.assertEqual(len(queue), 4)
        self.assertEqual(len({item["intake_seq"] for item in queue}), 4)

    def test_crash_mid_write_intake_fallback_keeps_alive(self) -> None:
        with mock.patch.object(intake, "append_idea", side_effect=OSError("disk full")):
            res = auto_attach.hook_on_prompt(self.project, "codex", "urgent Fix pkg/a.py", session="s1", now=self.t0)
            out = auto_attach._intake_and_prioritize(self.project, "Fix pkg/b.py", source="codex", now=self.t0)
        self.assertEqual((res["ok"], res["action"], res["priority"], res["intake_seq"]), (True, "ENQUEUED", "P0", None))
        self.assertEqual(out, {"priority": "P1", "intake_seq": None, "intake_shed": False,
                               "intake_status": "ERROR:OSError"})
        self.assertEqual(auto_attach.read_card(self.project, res["card_id"])["priority"], "P0")
        with mock.patch.object(intake, "append_idea", side_effect=OSError("disk full")), \
                mock.patch.object(intake, "classify", side_effect=RuntimeError("classifier gone")):
            out = auto_attach._intake_and_prioritize(self.project, "urgent Fix pkg/c.py", source="codex")
        self.assertEqual((out["priority"], out["intake_status"]), ("P1", "ERROR:RuntimeError"))
        intake_dir = self.project / ".coord" / "intake"
        intake_dir.mkdir(parents=True, exist_ok=True)
        (intake_dir / "ideas.jsonl").write_bytes(b'{"seq": 1, "text": "torn')
        res = auto_attach.enqueue_from_prompt(self.project, "codex", "Fix pkg/d.py", session="s2", now=self.t0)
        self.assertEqual((res["action"], res["intake_seq"]), ("ENQUEUED", 1))
        self.assertEqual([r["text"] for r in intake.read_ideas(self.project)], ["Fix pkg/d.py"])

    def test_duplicate_delivery_skips_intake_append(self) -> None:
        first = auto_attach.enqueue_from_prompt(self.project, "antigravity", "긴급 Fix pkg/a.py", session="s1",
                                                event_id="E1", now=self.t0)
        with mock.patch.object(intake, "append_idea", wraps=intake.append_idea) as spy:
            again = auto_attach.enqueue_from_prompt(self.project, "antigravity", "긴급 Fix pkg/a.py", session="s1",
                                                    event_id="E1", now=self.t0 + 1)
        self.assertEqual(spy.call_count, 0)
        self.assertEqual(first["action"], "ENQUEUED")
        self.assertEqual((again["action"], again["card_id"], again["priority"], again["intake_seq"]),
                         ("DUPLICATE", first["card_id"], "P0", 1))
        self.assertEqual(len(intake.read_ideas(self.project)), 1)
        self.assertEqual(len(auto_attach.read_queue(self.project)), 1)

    def test_stale_state_monotonic_priority_escalation(self) -> None:
        first = auto_attach.enqueue_from_prompt(self.project, "claude", "긴급 Fix pkg/a.py", session="s1", now=self.t0)
        second = auto_attach.enqueue_from_prompt(self.project, "claude", "나중에 Fix pkg/b.py", session="s1",
                                                 now=self.t0 + 1)
        self.assertEqual((second["action"], second["card_id"]), ("REUSED", first["card_id"]))
        self.assertEqual((second["priority"], second["intake_seq"]), ("P0", 2))
        card = auto_attach.read_card(self.project, first["card_id"])
        self.assertEqual((card["priority"], card["intake_seq"]), ("P0", 2))
        self.assertEqual(self._queue_item(first["card_id"])["priority"], "P0")
        low = auto_attach.enqueue_from_prompt(self.project, "codex", "someday Fix pkg/c.py", session="s2", now=self.t0)
        up = auto_attach.enqueue_from_prompt(self.project, "codex", "P0 Fix pkg/d.py", session="s2", now=self.t0 + 1)
        self.assertEqual((low["priority"], up["action"], up["priority"]), ("P2", "REUSED", "P0"))
        self.assertEqual(self._queue_item(low["card_id"])["priority"], "P0")
        self.assertEqual(auto_attach._higher_priority("P1", "bogus"), "P1")  # an unknown value ranks as P1

    def test_conductor_down_deterministic_priority(self) -> None:
        self._presence({"codex": "ABSENT", "claude": "LIMITED", "antigravity": "ACTIVE"})
        for prompt in ("ack_only relay", "hello there", ""):
            skipped = auto_attach.hook_on_prompt(self.project, "antigravity", prompt, session="s0", now=self.t0)
            self.assertEqual(skipped["action"], "SKIPPED")
        self.assertFalse((self.project / ".coord" / "intake").exists())  # skipped prompts touch no intake state
        self.assertEqual(auto_attach.read_queue(self.project), [])
        res = auto_attach.hook_on_prompt(self.project, "antigravity", "someday Fix pkg/a.py", session="s1",
                                         now=self.t0)
        self.assertEqual((res["action"], res["priority"], res["intake_seq"]), ("ENQUEUED", "P2", 1))
        self.assertEqual(intake.read_ideas(self.project)[0]["priority"], "P2")
        self.assertEqual(auto_attach._intake_and_prioritize(self.project, "   ", source="antigravity"),
                         {"priority": "P1", "intake_seq": None, "intake_shed": False,
                          "intake_status": "EMPTY_SKIPPED"})
        self.assertEqual(len(intake.read_ideas(self.project)), 1)

    def test_user_absent_model_hint_cannot_promote(self) -> None:
        self.assertEqual(intake.classify("Fix pkg/a.py", model_hint="P0"), "P1")
        res = auto_attach.enqueue_from_prompt(self.project, "codex", "Fix pkg/a.py", session="s1", now=self.t0)
        self.assertEqual(res["priority"], "P1")
        promoted = intake.append_idea(self.project, "Fix pkg/b.py", source="model", model_hint="P0", now=self.t0)
        self.assertEqual((promoted["priority"], promoted["model_hint"], promoted["user_p0"]), ("P1", "P0", False))
        again = auto_attach.enqueue_from_prompt(self.project, "codex", "Fix pkg/c.py as the model suggested", session="s1",
                                                now=self.t0 + 1)
        self.assertEqual((again["action"], again["priority"]), ("REUSED", "P1"))
        self.assertEqual(auto_attach.read_card(self.project, res["card_id"])["priority"], "P1")


if __name__ == "__main__":
    unittest.main()
