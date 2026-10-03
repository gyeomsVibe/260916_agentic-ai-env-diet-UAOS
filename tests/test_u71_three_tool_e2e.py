"""U71: three-tool unattended continuity, end to end, with real parallel OS processes.

Every step runs the real `python -m v7_harness.cli coord ...` command in its own process, several at once, against one
throwaway desk. A fake `claude` executable first on PATH writes one file per invocation, so the count of files is the
count of paid Claude turns that the real CLI would have started. The run walks the whole cycle:

    ACTIVE -> THRIFT -> HANDOFF_READY -> acting (Claude) -> RETURN_REVIEW -> LOCAL_LOCKDOWN

and checks the gates of card U71: one writer per step (one packet and one letter per episode, however many callers
race), at most one paid turn per letter, zero paid turns for ACK_ONLY, the zero-token watcher as the wake path, and a
lockdown that routes nothing and wakes nobody.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from v7_harness.coord.watch import watcher_live

REPO = Path(__file__).resolve().parents[1]
# Six callers per racing step: U63's in-process race used eight threads; six processes keep the run near 20 s on
# this host (each process pays a ~0.3 s interpreter start) while still overlapping every critical section.
RACERS = 6
# The watcher scans every 0.2 s here instead of 30 s so the test waits seconds, not minutes; the scan logic is the same.
WATCH_INTERVAL_S = "0.2"
FIELDS = ["--current-card", "U71", "--next-action", "run the fixed acceptance",
          "--acceptance", "python -m unittest tests.test_u71_three_tool_e2e", "--stop-condition", "fixed test changed"]

FAKE_CLAUDE = """import json, os, sys, time, uuid
log = os.environ["U71_CLAUDE_LOG"]
name = f"{time.time_ns()}_{os.getpid()}_{uuid.uuid4().hex}.json"
# One file per call: concurrent appends to one file lose lines on Windows.
with open(os.path.join(log, name), "w", encoding="utf-8") as handle:
    json.dump({"argv": sys.argv[1:]}, handle)
print(json.dumps({"result": "processed", "is_error": False}))
"""


class ThreeToolContinuityE2E(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.desk = root / "desk"
        (self.desk / ".coord" / "mailbox").mkdir(parents=True)
        (self.desk / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        self.calls = root / "claude_calls"
        self.calls.mkdir()
        fake_bin = root / "bin"
        fake_bin.mkdir()
        (fake_bin / "fake_claude.py").write_text(FAKE_CLAUDE, encoding="utf-8")
        if os.name == "nt":
            (fake_bin / "claude.cmd").write_text(f'@"{sys.executable}" "%~dp0fake_claude.py" %*\r\n', encoding="utf-8")
        else:
            script = fake_bin / "claude"
            script.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$(dirname "$0")/fake_claude.py" "$@"\n',
                              encoding="utf-8")
            script.chmod(0o755)
        self.env = {**os.environ, "PATH": str(fake_bin) + os.pathsep + os.environ.get("PATH", ""),
                    "PYTHONPATH": str(REPO), "U71_CLAUDE_LOG": str(self.calls), "PYTHONIOENCODING": "utf-8"}
        self.env.pop("CLAUDE_WORKER_CMD", None)
        # Safety before anything runs: the only `claude` these processes can find is the fake one.
        found = shutil.which("claude", path=self.env["PATH"])
        self.assertIsNotNone(found)
        self.assertEqual(fake_bin.resolve(), Path(found).resolve().parent)
        self._watchers: list[subprocess.Popen] = []

    def tearDown(self) -> None:
        for proc in self._watchers:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
        self._tmp.cleanup()

    # --- process helpers -----------------------------------------------------------------------------------------
    def _argv(self, *args: str) -> list[str]:
        return [sys.executable, "-m", "v7_harness.cli", "coord", args[0], "--project", str(self.desk), *args[1:]]

    def _start(self, *args: str) -> subprocess.Popen:
        return subprocess.Popen(self._argv(*args), cwd=REPO, env=self.env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")

    def _race(self, *args: str, n: int = RACERS) -> list[tuple[int, dict]]:
        """Start n identical processes before waiting on any, so they overlap for real."""
        procs = [self._start(*args) for _ in range(n)]
        results = []
        for proc in procs:
            out, err = proc.communicate(timeout=120)
            self.assertTrue(out.strip(), f"no output (rc={proc.returncode}): {err[-800:]}")
            results.append((proc.returncode, json.loads(out)))
        return results

    def _one(self, *args: str) -> tuple[int, dict]:
        return self._race(*args, n=1)[0]

    def _presence(self, **states: str) -> None:
        for tool, state in states.items():
            code, _ = self._one("presence", "--tool", tool, "--state", state)
            self.assertEqual(0, code)

    def _watch(self, timeout_s: int) -> subprocess.Popen:
        # U141-A rev 6: this cycle pins the U57-U74 delivery races, which wake on untagged letters; the structured CLI
        # default is proven in tests/test_u141a_wake_policy.py.
        proc = self._start("watch", "--target", "claude", "--timeout", str(timeout_s), "--interval", WATCH_INTERVAL_S,
                           "--policy", "legacy")
        self._watchers.append(proc)
        deadline = time.monotonic() + 30
        while not watcher_live(self.desk, "claude"):
            self.assertIsNone(proc.poll(), "watcher exited before it was live")
            self.assertLess(time.monotonic(), deadline, "watcher never became live")
            time.sleep(0.05)
        return proc

    def _paid_turns(self) -> int:
        return len(list(self.calls.glob("*.json")))

    def _letters(self, prefix: str) -> list[str]:
        return sorted(p.stem for p in (self.desk / ".coord" / "mailbox" / "inbox").glob(f"{prefix}*.json"))

    def _packets(self) -> list[Path]:
        return sorted((self.desk / ".coord" / "handoff").glob("*.md"))

    # --- the cycle ---------------------------------------------------------------------------------------------
    def test_full_cycle_one_writer_one_paid_turn_per_letter(self) -> None:
        # ACTIVE: all three tools present, Codex conducts.
        self._presence(codex="ACTIVE", claude="ACTIVE", antigravity="ACTIVE")
        self.assertEqual("codex", self._one("route")[1]["authority"])

        # THRIFT: Codex at 15 % keeps working under its own reserve policy; the racers write one packet, one letter.
        results = self._race("thrift", "--tool", "codex", "--remaining-percent", "15", *FIELDS)
        self.assertEqual([0] * RACERS, [code for code, _ in results])
        statuses = sorted(r["status"] for _, r in results)
        self.assertEqual(["ACK_ONLY"] * (RACERS - 1) + ["ACTIONABLE_DELTA"], statuses)
        delta = next(r for _, r in results if r["status"] == "ACTIONABLE_DELTA")
        self.assertEqual(("LOW", "codex", "COMMANDER_RESERVE"), (delta["state"], delta["target"], delta["policy"]))
        self.assertEqual(1, len(self._packets()))

        # HANDOFF_READY: Claude's watcher is the only wake path; thrift itself starts no model.
        self._presence(codex="LIMITED")
        watcher = self._watch(timeout_s=60)
        results = self._race("thrift", "--tool", "codex", "--remaining-percent", "5", *FIELDS)
        deltas = [r for _, r in results if r["status"] == "ACTIONABLE_DELTA"]
        self.assertEqual(1, len(deltas), results)
        self.assertEqual(("HANDOFF_READY", "claude"), (deltas[0]["state"], deltas[0]["target"]))
        out, _ = watcher.communicate(timeout=60)
        woke = json.loads(out)
        self.assertEqual((0, "NEW_LETTER", deltas[0]["message_id"], "HANDOFF"),
                         (watcher.returncode, woke["reason"], woke["id"], woke["kind"]))
        self.assertEqual(2, len(self._packets()))
        self.assertEqual(0, self._paid_turns())

        # Acting: every racer sees the same single authority.
        routes = self._race("route")
        self.assertEqual({"claude"}, {r["authority"] for _, r in routes})

        # ACK_ONLY while the interactive session listens: queued for it, no paid turn.
        watcher = self._watch(timeout_s=60)
        results = self._race("deliver", "--actor", "codex", "--target", "claude",
                             "--message", "ACK_ONLY liveness: U71 unchanged")
        # A racer that loses the per-letter guard answers IN_FLIGHT; the letter is already published either way.
        # U74-D: the watcher returns on the published letter and clears its file, so a racer that checks after that
        # sees no watcher; it answers QUEUED_ACK_ONLY (it used to answer DISPATCHED and buy a paid turn).
        reasons = [r["reason"] for _, r in results]
        self.assertTrue({"QUEUED_INTERACTIVE", "QUEUED_ACK_ONLY"} & set(reasons), reasons)
        self.assertLessEqual(set(reasons), {"QUEUED_INTERACTIVE", "QUEUED_ACK_ONLY", "IN_FLIGHT"})
        self.assertEqual(1, len({r["message_id"] for _, r in results}))
        out, _ = watcher.communicate(timeout=60)
        self.assertEqual((0, results[0][1]["message_id"]), (watcher.returncode, json.loads(out)["id"]))
        self.assertEqual(0, self._paid_turns())

        # ACTIONABLE_DELTA: racing senders of one letter buy exactly one paid turn, and a live watcher that has
        # seen everything else does not wake on that already-dispatched letter: it times out (exit 3).
        watcher = self._watch(timeout_s=6)
        results = self._race("deliver", "--actor", "antigravity", "--target", "claude",
                             "--message", "ACTIONABLE_DELTA verdict_requested=yes: U71 evidence changed")
        self.assertEqual(1, self._paid_turns(), results)
        self.assertEqual({"DISPATCHED"}, {r["reason"] for _, r in results} - {"IN_FLIGHT"})
        out, _ = watcher.communicate(timeout=60)
        self.assertEqual((3, "TIMEOUT"), (watcher.returncode, json.loads(out)["reason"]),
                         "the watcher woke on a letter a paid turn already answered")
        # Re-sending the same letter later is idempotent: still one paid turn.
        self._one("deliver", "--actor", "antigravity", "--target", "claude",
                  "--message", "ACTIONABLE_DELTA verdict_requested=yes: U71 evidence changed")
        self.assertEqual(1, self._paid_turns())

        # RETURN_REVIEW: Codex comes back; one return letter, and it leads again.
        self._presence(codex="ACTIVE")
        results = self._race("thrift", "--tool", "codex", "--remaining-percent", "80")
        returns = [r for _, r in results if r.get("event") == "RETURN_REVIEW" and r["status"] == "ACTIONABLE_DELTA"]
        self.assertEqual(1, len(returns), results)
        self.assertEqual("codex", self._one("route")[1]["authority"])

        # LOCAL_LOCKDOWN: nobody may act. Routing fails closed, the hand-off names no tool, a letter stays in the
        # mailbox, and no paid turn starts.
        self._presence(codex="LIMITED", claude="LIMITED", antigravity="LIMITED")
        code, route = self._one("route")
        self.assertEqual((1, "BLOCKED_NO_ACTIVE_AUTHORITY"), (code, route["authority"]))
        results = self._race("thrift", "--tool", "claude", "--remaining-percent", "5", *FIELDS)
        lockdown = [r for _, r in results if r["status"] == "ACTIONABLE_DELTA"]
        self.assertEqual(["LOCAL_LOCKDOWN"], [r["target"] for r in lockdown])
        code, sent = self._one("deliver", "--actor", "codex", "--message", "ACTIONABLE_DELTA verdict_requested=yes: lockdown")
        self.assertEqual(("mailbox_only", "PUBLISHED"), (sent["target"], sent["reason"]))
        self.assertEqual(1, self._paid_turns())
        self.assertEqual({"codex": "LIMITED", "claude": "LIMITED", "antigravity": "LIMITED"}, route["states"])

        # One writer per step: THRIFT, HANDOFF, RETURN_REVIEW and LOCKDOWN each left exactly one thrift letter.
        self.assertEqual(4, len(self._letters("thrift_")))
        self.assertEqual(3, len(self._packets()))  # RETURN_REVIEW is AMPLE: a letter, no packet


if __name__ == "__main__":
    unittest.main()
