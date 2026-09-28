```contract
work_id: U71
worker: apply
goal: Add an end-to-end test that runs the real coord CLI as parallel OS processes through ACTIVE, THRIFT, HANDOFF_READY, acting, RETURN_REVIEW and LOCAL_LOCKDOWN, counting paid Claude turns with a fake claude executable
inputs:
- v7_harness/coord/thrift.py sha256=e832fbaad81aa173cd6ded8f6ae8ab62c50af00ca64ed0688a90b2a64a3e7dba
- v7_harness/coord/watch.py sha256=7eb50c9488483ac83ad8177502b24c5f0266cd396db049c58fd03b97b71d8c6e
- v7_harness/coord/deliver.py sha256=aada355dca62ecdd5fcca0f6b07a6d3d7da953d235f517934a63e7ced2a2c82a
allow:
- tests/test_u71_three_tool_e2e.py
- docs/58_u71-three-tool-continuity-e2e.md
acceptance: python -m unittest tests.test_u71_three_tool_e2e tests.test_u63_thrift_mode tests.test_u64_nonstop_dispatch tests.test_u64f_no_double_wake
forbidden: design changes; edits outside allow; weakening or deleting existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Card U71: the U63/U64/U66 parts were tested separately, mostly in one process. The new test passes on c526903 with no production change, and three mutations (U64-F accepted skip, U64 ACK queueing, U63 fingerprint ACK) each make it fail. Judge claude (ACTING while Codex is LIMITED); Codex re-reviews. Write the two files below exactly.

===FILE: tests/test_u71_three_tool_e2e.py===
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
        proc = self._start("watch", "--target", "claude", "--timeout", str(timeout_s), "--interval", WATCH_INTERVAL_S)
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
        self.assertEqual(("THRIFT", "codex", "COMMANDER_RESERVE"), (delta["state"], delta["target"], delta["policy"]))
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
        reasons = [r["reason"] for _, r in results]
        self.assertIn("QUEUED_INTERACTIVE", reasons)
        self.assertLessEqual(set(reasons), {"QUEUED_INTERACTIVE", "IN_FLIGHT"})
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
        self.assertEqual(3, len(self._packets()))  # RETURN_REVIEW is NORMAL: a letter, no packet


if __name__ == "__main__":
    unittest.main()
===FILE: docs/58_u71-three-tool-continuity-e2e.md===
# U71 3도구 무인 연속성 E2E

## 왜 필요한가

U63(절약 모드), U64(대기 없는 전달), U64-F·U66(이중 기상 방지)은 각각 따로 시험됐다. 대부분 한 프로세스 안의 스레드나 가짜 실행기(runner)를 썼다. 그러나 실제 데스크에서는 Codex, Claude, Antigravity와 감시자(`coord watch`)가 **서로 다른 OS 프로세스**로 같은 `.coord` 폴더를 동시에 만진다. 그래서 따로 통과한 부품이 한 주기로 이어져도 규칙을 지키는지는 확인되지 않은 상태(UNKNOWN)였다.

## 무엇을 시험하나

`tests/test_u71_three_tool_e2e.py`는 임시 데스크 하나에서 실제 명령 `python -m v7_harness.cli coord ...`을 별도 프로세스로 실행한다. 경쟁 단계마다 같은 명령 6개를 먼저 모두 띄운 뒤에 기다린다. 그래서 프로세스들이 실제로 겹쳐 돈다.

유료 호출은 가짜 `claude` 실행 파일로 센다.

- PATH 맨 앞에 가짜 `claude`를 둔다. 호출 한 번마다 파일 하나를 만든다. 한 파일에 동시에 이어 쓰면 Windows에서 줄이 사라지므로 호출마다 파일을 따로 만든다.
- 파일 개수가 실제 CLI가 시작했을 유료 Claude 턴(turn) 수다.
- 시작 전에 `shutil.which("claude")`가 가짜를 가리키는지 확인한다. 진짜 Claude가 불릴 수 없게 하는 안전장치다.

한 주기의 단계와 확인 내용은 아래와 같다.

1. **ACTIVE**: 세 도구 모두 활성. `coord route`는 codex를 고른다.
2. **THRIFT**(Codex 15%): 6개 경쟁
   - 결과는 ACTIONABLE_DELTA 1개와 ACK_ONLY 5개다.
   - 인계 패킷 1개, 편지 1통이 생긴다.
   - 정책은 COMMANDER_RESERVE, 대상은 Codex 자신이다.
3. **HANDOFF_READY**(Codex LIMITED, 5%): 6개 경쟁
   - 대상이 claude인 편지 1통이 생긴다.
   - 감시자 프로세스는 그 편지 id로 한 번 깨어난다(0토큰 기상).
   - 유료 턴은 0이다.
4. **대행**: `route` 6개 경쟁 모두 claude를 답한다(권한자 1명).
5. **ACK_ONLY**(감시자 살아 있음): 전달 6개 경쟁
   - 결과는 QUEUED_INTERACTIVE, 또는 경쟁에서 진 IN_FLIGHT다. 편지 id는 1개다.
   - 감시자가 그 편지로 깨어난다.
   - 유료 턴은 0이다.
6. **ACTIONABLE_DELTA**: 같은 편지를 6개가 동시에 보낸다.
   - 유료 턴은 정확히 1이다.
   - 이미 처리된 편지에는 감시자가 깨어나지 않는다(시간 초과, 종료 코드 3).
   - 나중에 같은 편지를 다시 보내도 유료 턴은 여전히 1이다(멱등).
7. **RETURN_REVIEW**(Codex 복귀 80%): 6개 경쟁
   - 복귀 편지는 1통이다.
   - route는 다시 codex를 고른다.
8. **LOCAL_LOCKDOWN**(세 도구 모두 LIMITED)
   - route는 `BLOCKED_NO_ACTIVE_AUTHORITY`로 종료 코드 1이다.
   - 인계 대상은 LOCAL_LOCKDOWN이다.
   - 대상 없이 보낸 편지는 우편함에만 남는다(mailbox_only).
   - 유료 턴은 늘지 않는다.
   - presence 상태는 그대로다.
9. **단일 작성자**: 절약 편지는 단계당 1통씩 모두 4통이다. 인계 패킷은 3개다. RETURN_REVIEW는 NORMAL 상태라 편지만 있고 패킷은 없다.

## 시험이 진짜로 재는가(변이 시험, mutation)

main(c526903)을 복사한 뒤 규칙 하나씩을 끄고 같은 시험을 돌렸다. 세 경우 모두 실패했다.

| 끈 규칙 | 실패한 확인 |
|---|---|
| 감시자가 처리된 편지(accepted)를 건너뛰는 U64-F 규칙 | 6단계: 감시자가 시간 초과 대신 이미 처리된 편지로 깨어남 |
| 감시자가 살아 있으면 ACK_ONLY를 대기열에만 두는 U64 규칙 | 5단계: ACK_ONLY가 유료 턴으로 전달됨 |
| 같은 입력의 절약 신호를 ACK_ONLY로 줄이는 U63 규칙 | 2단계: 편지 6통이 생김 |

## 결과

- 운영 코드 변경은 0이다. 현재 main은 한 주기 전체에서 카드의 관문을 지킨다.
  - 중복 작성 0
  - 편지 1통당 유료 턴 1 이하
  - ACK_ONLY 유료 호출 0
  - LOCAL_LOCKDOWN 보존
- 시험 한 번은 약 11.7초 걸린다. 3회 연속 통과했다.

## 한계

- 실제 Codex(`codex queue`) 전달은 스레드 해석에 실제 Codex 세션이 필요하다. 그래서 이 시험은 Claude 쪽 전달과 우편함 경로만 실제로 돌린다.
- 가짜 `claude`는 응답 내용을 흉내 내지 않는다. 호출 횟수만 증거다.
- 절감량은 이 시험이 재지 않는다(`UNMEASURED`). U72가 10개 표본으로 대조한다.
===END===

## Output

- Reply with ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.
