"""U337: Option C zero-LLM autonomous companion auto-attach control-plane tests.

Covers all Codex U337_OPTION_C_DECISION invariants with offline mocks and real
Windows cross-process races (zero live/paid model or native session execution):
1. Prompt hook reads & enqueues only, idempotently, zero adapter launches.
2. Separate admission (HALT/JUDGE_ONLY/UNKNOWN/read-only fail-closed) and pool freshness + FIFO capacity.
3. Real cross-process duplicate generation claim -> atomic O_EXCL single winner.
4. Real cross-process crash before vs after ADAPTER_STARTED -> safe g+1 vs UNKNOWN_EFFECT barrier.
5. Real cross-process slow owner & +24h TTL advance -> HELD_BY_SLOW_OWNER, no TTL takeover or close.
6. Retry with UNKNOWN_EFFECT -> blocked until record_trusted_receipt (converges or unlocks g+1).
7. Real cross-process pause/stop before launch -> ABORTED_BEFORE_LAUNCH, 0 adapter calls, preserves owner.
8. Real cross-process multi-project isolation -> distinct project_id, zero collision.
9. Adapter without verified session -> NO_VERIFIED_SESSION, queue & owner preserved, no guessed session.
10. Optional hook failure -> caller stays alive, auditable BLOCKED_HOOK_ERROR receipt, no paid fallthrough.
11. Claude exact watcher route only -> exact desk watcher vs durable non-waking notice.
12. Overlap guard + finish_card -> closes companions cleanly, unblocks WAITING card, promotes FIFO.
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
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v7_harness.coord import auto_attach  # noqa: E402


def _child_env(sessions_dir: Path | None = None) -> dict[str, str]:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{REPO_ROOT}{os.pathsep}{existing}" if existing else str(REPO_ROOT)
    env.pop("UAOS_WORKER", None)
    if sessions_dir is not None:
        env["UAOS_CODEX_SESSIONS"] = str(sessions_dir)
    return env


def _spawn_helper(code: str, *args: str, sessions_dir: Path | None = None) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-c", code, *args],
        cwd=str(REPO_ROOT),
        env=_child_env(sessions_dir),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )


def _iso_utc(ts: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def _seed_admitted_env(
    project: Path,
    *,
    now: float = 1_700_000_000.0,
    mode: str = "TRIO",
    roles: dict[str, str] | None = None,
    presence_states: dict[str, str] | None = None,
    pools: dict[str, dict] | None = None,
) -> None:
    coord = project / ".coord"
    (coord / "presence").mkdir(parents=True, exist_ok=True)
    (coord / "auto_attach" / "pools").mkdir(parents=True, exist_ok=True)
    (coord / "PLAN.md").write_text("# U337 test plan\n", encoding="utf-8")

    default_roles = {t: "EXECUTOR" for t in auto_attach.TOOLS}
    if roles:
        default_roles.update(roles)
    snap = {
        "mode": mode,
        "roles": default_roles,
        "decided_at": now,
        "expires_at": now + 900.0,
    }
    (coord / "participation.json").write_text(json.dumps(snap), encoding="utf-8")

    pstates = {t: "ACTIVE" for t in auto_attach.TOOLS}
    if presence_states:
        pstates.update(presence_states)
    for tool, st in pstates.items():
        (coord / "presence" / f"{tool}.json").write_text(
            json.dumps(
                {
                    "tool": tool,
                    "state": st,
                    "observed_at": _iso_utc(now),
                    "expires_at": now + 3600.0,
                }
            ),
            encoding="utf-8",
        )

    for tool in auto_attach.TOOLS:
        pool = (pools or {}).get(
            tool,
            {
                "tool": tool,
                "pool_id": f"{tool}-default-pool",
                "state": "FRESH",
                "observed_at": now - 5.0,
                "expires_at": now + 300.0,
            },
        )
        if pool is not None:
            (coord / "auto_attach" / "pools" / f"{tool}.json").write_text(
                json.dumps(pool), encoding="utf-8"
            )


class TestU337AutoAttachOptionC(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.project = Path(self._tmp.name) / "proj"
        self.project.mkdir(parents=True, exist_ok=True)
        self.empty_sessions = Path(self._tmp.name) / "empty_codex_sessions"
        self.empty_sessions.mkdir(parents=True, exist_ok=True)
        sess_patch = mock.patch.dict(os.environ, {"UAOS_CODEX_SESSIONS": str(self.empty_sessions)})
        sess_patch.start()
        self.addCleanup(sess_patch.stop)
        self.now = 1_700_000_000.0

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_1_prompt_hook_reads_and_enqueues_only_idempotent_zero_launch(self) -> None:
        with mock.patch("subprocess.Popen") as popen_mock:
            # Non-work prompts & injected relay text do not enqueue
            for noise in ("", "   ", "안녕", "지금 상태 어때?", "ACK_ONLY: noted"):
                res = auto_attach.hook_on_prompt(
                    self.project, "antigravity", noise, session="sess-agy-1", now=self.now
                )
                self.assertTrue(res["ok"])
                self.assertIn("skipped", res)

            # Real work prompt enqueues cleanly & idempotently with zero launches
            prompt = "Implement v7_harness/coord/auto_attach.py companion routing"
            t0 = time.perf_counter()
            r1 = auto_attach.hook_on_prompt(
                self.project,
                "antigravity",
                prompt,
                session="sess-agy-1",
                event_id="evt-101",
                now=self.now,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            self.assertTrue(r1["ok"])
            self.assertFalse(r1.get("duplicate", False))
            self.assertEqual(r1["action"], "ENQUEUED")
            self.assertLess(elapsed_ms, 500.0)

            # Replaying same event_id OR second prompt in same session reuses same primary & never duplicates queue
            r2 = auto_attach.hook_on_prompt(
                self.project,
                "antigravity",
                prompt,
                session="sess-agy-1",
                event_id="evt-101",
                now=self.now + 1,
            )
            self.assertTrue(r2["duplicate"])
            self.assertEqual(r1["card_id"], r2["card_id"])

            r3 = auto_attach.hook_on_prompt(
                self.project,
                "antigravity",
                "Also add unit tests in tests/test_u337_auto_attach.py",
                session="sess-agy-1",
                event_id="evt-102",
                now=self.now + 2,
            )
            self.assertEqual(r1["card_id"], r3["card_id"])
            self.assertTrue(r3["reused"])

            # Companion window sessions never recurse into new primaries
            comp_card = f"{r1['card_id']}.codex"
            auto_attach._write_verified_session_for_test(
                self.project, comp_card, "codex", "comp-codex-sess"
            )
            r_rec = auto_attach.hook_on_prompt(
                self.project,
                "codex",
                "Fix tests/test_u337_auto_attach.py inside companion",
                session="comp-codex-sess",
                event_id="evt-rec",
                now=self.now + 3,
            )
            self.assertEqual(r_rec.get("skipped"), "COMPANION_WINDOW_NO_RECURSION")

            # UAOS_WORKER and UAOS_AUTO_ATTACH=0 both no-op cleanly
            with mock.patch.dict(os.environ, {"UAOS_WORKER": "local"}):
                rw = auto_attach.hook_on_prompt(self.project, "codex", prompt, session="s2", now=self.now)
                self.assertEqual(rw.get("skipped"), "UAOS_WORKER")
            with mock.patch.dict(os.environ, {"UAOS_AUTO_ATTACH": "0"}):
                rd = auto_attach.hook_on_prompt(self.project, "codex", prompt, session="s2", now=self.now)
                self.assertEqual(rd.get("skipped"), "AUTO_ATTACH_DISABLED")

            popen_mock.assert_not_called()

        queue = auto_attach.read_queue(self.project)
        primaries = [q for q in queue if q["card_id"] == r1["card_id"]]
        self.assertEqual(len(primaries), 1)
        self.assertEqual(set(primaries[0]["peers"]), {"codex", "claude"})

    def test_2_separate_admission_and_pool_freshness_blocks_halt_judge_only_unknown_and_readonly(self) -> None:
        calls: list[str] = []

        def fake_adapter(**kwargs):
            calls.append(kwargs["peer"])
            return {"verified": True, "session_id": f"sess-{kwargs['peer']}"}

        enq = auto_attach.enqueue_from_prompt(
            self.project,
            "antigravity",
            "Implement v7_harness/feature_a.py",
            session="agy-desk-1",
            now=self.now,
        )
        card_id = enq["card_id"]

        # 2a. Missing snapshot defaults fail-closed to HALT; read-only sandbox confers zero launch authority
        res_missing = auto_attach.reconcile_once(
            self.project,
            adapters={"codex": fake_adapter, "claude": fake_adapter},
            sandbox="read-only",
            now=self.now,
        )
        self.assertEqual(calls, [])
        self.assertEqual(res_missing["peers"][f"{card_id}.codex"]["reason"], "ADMISSION_HALT")

        # 2b. Explicit HALT, JUDGE_ONLY, UNKNOWN, expired snapshot, and non-ACTIVE presence all fail closed
        for label, mode, role, state, exp_delta in [
            ("ADMISSION_HALT", "HALT", "EXECUTOR", "ACTIVE", 900.0),
            ("ADMISSION_JUDGE_ONLY", "TRIO", "JUDGE_ONLY", "ACTIVE", 900.0),
            ("ADMISSION_UNKNOWN", "TRIO", "UNKNOWN", "ACTIVE", 900.0),
            ("ADMISSION_EXPIRED", "TRIO", "EXECUTOR", "ACTIVE", -5.0),
            ("PRESENCE_NOT_ACTIVE", "TRIO", "EXECUTOR", "LIMITED", 900.0),
        ]:
            _seed_admitted_env(
                self.project,
                now=self.now,
                mode=mode,
                roles={"codex": role, "claude": "JUDGE_ONLY"},
                presence_states={"codex": state, "claude": "ABSENT"},
            )
            snap_path = self.project / ".coord" / "participation.json"
            snap = json.loads(snap_path.read_text(encoding="utf-8"))
            snap["expires_at"] = self.now + exp_delta
            snap_path.write_text(json.dumps(snap), encoding="utf-8")

            adm = auto_attach.evaluate_admission(self.project, "codex", now=self.now, sandbox="read-only")
            self.assertFalse(adm["admitted"], label)
            self.assertEqual(adm["reason"], label)
            auto_attach.reconcile_once(
                self.project,
                adapters={"codex": fake_adapter},
                sandbox="read-only",
                now=self.now,
            )
            self.assertEqual(calls, [])

        # 2c. Valid admission EXECUTOR, but stale/missing pool freshness fails closed & preserves queue/owner
        _seed_admitted_env(
            self.project,
            now=self.now,
            roles={"codex": "EXECUTOR", "claude": "OFFLINE"},
            pools={
                "codex": {
                    "tool": "codex",
                    "pool_id": "codex-main",
                    "state": "FRESH",
                    "observed_at": self.now - (auto_attach.POOL_MAX_AGE_S + 10.0),
                },
                "claude": None,
            },
        )
        res_stale = auto_attach.reconcile_once(
            self.project,
            adapters={"codex": fake_adapter},
            now=self.now,
        )
        self.assertEqual(calls, [])
        self.assertEqual(res_stale["peers"][f"{card_id}.codex"]["reason"], "POOL_STALE_OR_UNKNOWN")
        self.assertEqual(auto_attach.read_card(self.project, card_id)["owner"], "antigravity")

        # 2d. Capacity cap holds extra work in controlled FIFO queue without invoking adapter
        _seed_admitted_env(self.project, now=self.now, roles={"codex": "EXECUTOR", "claude": "OFFLINE"})
        for idx in range(auto_attach.MAX_OPEN_COMPANIONS):
            c_extra = auto_attach.enqueue_from_prompt(
                self.project,
                "antigravity",
                f"Implement v7_harness/cap_{idx}.py",
                session=f"agy-cap-{idx}",
                now=self.now + idx + 1,
            )["card_id"]
            auto_attach._write_verified_session_for_test(
                self.project, f"{c_extra}.codex", "codex", f"live-codex-{idx}"
            )
        res_cap = auto_attach.reconcile_once(
            self.project,
            adapters={"codex": fake_adapter},
            now=self.now + 10,
        )
        self.assertEqual(calls, [])
        self.assertEqual(res_cap["peers"][f"{card_id}.codex"]["reason"], "POOL_AT_CAPACITY")

    def test_3_windows_cross_process_duplicate_claim_atomic_one_winner(self) -> None:
        _seed_admitted_env(self.project, now=self.now, roles={"codex": "EXECUTOR", "claude": "OFFLINE"})
        enq = auto_attach.enqueue_from_prompt(
            self.project,
            "antigravity",
            "Implement v7_harness/race_target.py",
            session="agy-race",
            now=self.now,
        )
        card_id = enq["card_id"]

        worker_code = (
            "import json, sys; from pathlib import Path\n"
            "from v7_harness.coord import auto_attach\n"
            "proj = Path(sys.argv[1])\n"
            "now = float(sys.argv[2])\n"
            "calls = 0\n"
            "def adapter(**kw):\n"
            "    global calls; calls += 1\n"
            "    import time; time.sleep(0.15)\n"
            "    return {'verified': True, 'session_id': f'codex-win-{calls}'}\n"
            "res = auto_attach.reconcile_once(proj, adapters={'codex': adapter}, now=now)\n"
            "print(json.dumps({'calls': calls, 'res': res}))\n"
        )
        procs = [_spawn_helper(worker_code, str(self.project), str(self.now)) for _ in range(6)]
        outs = []
        for p in procs:
            stdout, stderr = p.communicate(timeout=30)
            self.assertEqual(p.returncode, 0, stderr)
            outs.append(json.loads(stdout.strip().splitlines()[-1]))

        total_adapter_calls = sum(o["calls"] for o in outs)
        self.assertEqual(total_adapter_calls, 1)
        claim = auto_attach.read_claim(self.project, card_id, "codex", 1)
        self.assertIsNotNone(claim)
        self.assertEqual(claim["state"], "VERIFIED_OPEN")
        self.assertEqual(claim["verified_session_id"], "codex-win-1")

    def test_4_windows_cross_process_crash_before_and_after_adapter_effect(self) -> None:
        _seed_admitted_env(self.project, now=self.now, roles={"codex": "EXECUTOR", "claude": "OFFLINE"})

        # Case A: crash BEFORE ADAPTER_STARTED -> proven dead PID -> CRASHED_BEFORE_EFFECT -> g2 succeeds
        c_before = auto_attach.enqueue_from_prompt(
            self.project, "antigravity", "Implement v7_harness/crash_a.py", session="s-a", now=self.now
        )["card_id"]
        crash_before_code = (
            "import os, sys; from pathlib import Path\n"
            "from v7_harness.coord import auto_attach\n"
            "proj, card, now = Path(sys.argv[1]), sys.argv[2], float(sys.argv[3])\n"
            "r = auto_attach.claim_generation(proj, card, 'codex', 1, now=now)\n"
            "assert r['claimed'] is True\n"
            "os._exit(99)\n"
        )
        p_a = _spawn_helper(crash_before_code, str(self.project), c_before, str(self.now))
        self.assertEqual(p_a.wait(timeout=20), 99)
        if p_a.stdout:
            p_a.stdout.close()
        if p_a.stderr:
            p_a.stderr.close()

        calls_a: list[int] = []

        def adapter_a(**kw):
            calls_a.append(kw["generation"])
            return {"verified": True, "session_id": f"recovered-g{kw['generation']}"}

        res_a = auto_attach.reconcile_once(self.project, adapters={"codex": adapter_a}, now=self.now + 5)
        self.assertEqual(calls_a, [2])
        self.assertEqual(auto_attach.read_claim(self.project, c_before, "codex", 1)["state"], "CRASHED_BEFORE_EFFECT")
        self.assertEqual(auto_attach.read_claim(self.project, c_before, "codex", 2)["state"], "VERIFIED_OPEN")
        self.assertEqual(res_a["peers"][f"{c_before}.codex"]["status"], "VERIFIED_OPEN")

        # Case B: crash AFTER ADAPTER_STARTED -> UNKNOWN_EFFECT -> REFUSE retry until trusted receipt
        c_after = auto_attach.enqueue_from_prompt(
            self.project, "antigravity", "Implement v7_harness/crash_b.py", session="s-b", now=self.now + 10
        )["card_id"]
        crash_after_code = (
            "import os, sys; from pathlib import Path\n"
            "from v7_harness.coord import auto_attach\n"
            "proj, card, now = Path(sys.argv[1]), sys.argv[2], float(sys.argv[3])\n"
            "def die_inside(**kw): os._exit(88)\n"
            "auto_attach.reconcile_once(proj, adapters={'codex': die_inside}, now=now)\n"
        )
        p_b = _spawn_helper(crash_after_code, str(self.project), c_after, str(self.now + 10))
        self.assertEqual(p_b.wait(timeout=20), 88)
        if p_b.stdout:
            p_b.stdout.close()
        if p_b.stderr:
            p_b.stderr.close()

        calls_b: list[int] = []

        def adapter_b(**kw):
            calls_b.append(kw["generation"])
            return {"verified": True, "session_id": "must-not-run"}

        for offset in (15, 200, 5000):
            r_b = auto_attach.reconcile_once(self.project, adapters={"codex": adapter_b}, now=self.now + offset)
            self.assertEqual(calls_b, [])
            self.assertEqual(r_b["peers"][f"{c_after}.codex"]["reason"], "RETRY_BLOCKED_UNKNOWN_EFFECT")
            self.assertEqual(auto_attach.read_claim(self.project, c_after, "codex", 1)["state"], "UNKNOWN_EFFECT")

    def test_5_windows_cross_process_slow_owner_and_stale_ttl_never_taken_over_or_closed(self) -> None:
        _seed_admitted_env(self.project, now=self.now, roles={"codex": "EXECUTOR", "claude": "OFFLINE"})
        card_id = auto_attach.enqueue_from_prompt(
            self.project, "antigravity", "Implement v7_harness/slow_owner.py", session="s-slow", now=self.now
        )["card_id"]

        ready_flag = self.project / "slow_ready.flag"
        slow_code = (
            "import sys, time; from pathlib import Path\n"
            "from v7_harness.coord import auto_attach\n"
            "proj, card, flag, now = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), float(sys.argv[4])\n"
            "res = auto_attach.claim_generation(proj, card, 'codex', 1, now=now)\n"
            "assert res['claimed'] is True\n"
            "flag.write_text('claimed', encoding='utf-8')\n"
            "time.sleep(30)\n"
        )
        proc = _spawn_helper(slow_code, str(self.project), card_id, str(ready_flag), str(self.now))
        try:
            deadline = time.monotonic() + 15.0
            while not ready_flag.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(ready_flag.exists())

            # Advance clock by +24 hours and refresh snapshot/pool freshness so only TTL-elapsed on claim differs
            future = self.now + 86400.0
            _seed_admitted_env(self.project, now=future, roles={"codex": "EXECUTOR", "claude": "OFFLINE"})
            calls = []
            res = auto_attach.reconcile_once(
                self.project,
                adapters={"codex": lambda **kw: calls.append(1) or {"verified": True, "session_id": "x"}},
                now=future,
            )
            self.assertEqual(calls, [])
            self.assertEqual(res["peers"][f"{card_id}.codex"]["reason"], "HELD_BY_SLOW_OWNER")
            self.assertIsNone(auto_attach.read_claim(self.project, card_id, "codex", 2))

            # Verify VERIFIED_OPEN is also NEVER closed by TTL alone after +24h
            c_open = auto_attach.enqueue_from_prompt(
                self.project, "antigravity", "Implement v7_harness/open_no_ttl_close.py", session="s-open", now=self.now
            )["card_id"]
            auto_attach._write_verified_session_for_test(self.project, f"{c_open}.codex", "codex", "open-live-1")
            res2 = auto_attach.reconcile_once(self.project, adapters={}, now=future + 86400.0)
            self.assertEqual(auto_attach.read_claim(self.project, c_open, "codex", 1)["state"], "VERIFIED_OPEN")
            self.assertEqual(res2["orphans_closed"], [])
        finally:
            proc.terminate()
            proc.wait(timeout=10)
            if proc.stdout:
                proc.stdout.close()
            if proc.stderr:
                proc.stderr.close()

    def test_6_retry_with_unknown_external_effect_requires_trusted_receipt(self) -> None:
        _seed_admitted_env(self.project, now=self.now, roles={"codex": "EXECUTOR", "claude": "OFFLINE"})

        # Subcase 1: trusted receipt confirms session already exists -> converges to VERIFIED_OPEN with zero relaunch
        c1 = auto_attach.enqueue_from_prompt(
            self.project, "antigravity", "Implement v7_harness/unknown_1.py", session="u1", now=self.now
        )["card_id"]
        relaunch_calls: list[int] = []

        def flaky_adapter(**kw):
            relaunch_calls.append(kw["generation"])
            if kw["generation"] == 1:
                raise TimeoutError("ambiguous RPC timeout")
            return {"verified": True, "session_id": "should-not-run-for-c1"}

        auto_attach.reconcile_once(self.project, adapters={"codex": flaky_adapter}, now=self.now)
        self.assertEqual(auto_attach.read_claim(self.project, c1, "codex", 1)["state"], "UNKNOWN_EFFECT")

        blocked = auto_attach.reconcile_once(self.project, adapters={"codex": flaky_adapter}, now=self.now + 10)
        self.assertEqual(blocked["peers"][f"{c1}.codex"]["reason"], "RETRY_BLOCKED_UNKNOWN_EFFECT")
        self.assertEqual(relaunch_calls, [1])

        tr1 = auto_attach.record_trusted_receipt(
            self.project,
            c1,
            "codex",
            1,
            source="codex_thread_list",
            verified_session_id="native-thread-999",
            now=self.now + 15,
        )
        self.assertEqual(tr1["state"], "VERIFIED_OPEN")
        r_after1 = auto_attach.reconcile_once(self.project, adapters={"codex": flaky_adapter}, now=self.now + 20)
        self.assertEqual(r_after1["peers"][f"{c1}.codex"]["reason"], "ALREADY_VERIFIED_OPEN")
        self.assertEqual(relaunch_calls, [1])

        # Subcase 2: trusted receipt confirms no external session -> unlocks g2 cleanly
        c2 = auto_attach.enqueue_from_prompt(
            self.project, "antigravity", "Implement v7_harness/unknown_2.py", session="u2", now=self.now + 30
        )["card_id"]
        auto_attach.reconcile_once(
            self.project,
            adapters={"codex": lambda **kw: {"outcome": "UNKNOWN"}},
            now=self.now + 30,
        )
        self.assertEqual(auto_attach.read_claim(self.project, c2, "codex", 1)["state"], "UNKNOWN_EFFECT")
        tr2 = auto_attach.record_trusted_receipt(
            self.project,
            c2,
            "codex",
            1,
            source="codex_thread_list",
            verified_absent=True,
            now=self.now + 35,
        )
        self.assertEqual(tr2["state"], "CONFIRMED_ABSENT")
        r_after2 = auto_attach.reconcile_once(
            self.project,
            adapters={"codex": lambda **kw: {"verified": True, "session_id": f"fresh-g{kw['generation']}"}},
            now=self.now + 40,
        )
        self.assertEqual(r_after2["peers"][f"{c2}.codex"]["status"], "VERIFIED_OPEN")
        self.assertEqual(auto_attach.read_claim(self.project, c2, "codex", 2)["verified_session_id"], "fresh-g2")

    def test_7_windows_cross_process_paused_or_stopped_card_before_launch_aborts(self) -> None:
        _seed_admitted_env(self.project, now=self.now, roles={"codex": "EXECUTOR", "claude": "OFFLINE"})

        # Case A: paused card never claims or calls adapter
        c_paused = auto_attach.enqueue_from_prompt(
            self.project, "antigravity", "Implement v7_harness/paused.py", session="p1", now=self.now
        )["card_id"]
        auto_attach.pause_card(self.project, c_paused, reason="user_paused", now=self.now + 1)
        calls: list[int] = []
        res_p = auto_attach.reconcile_once(
            self.project, adapters={"codex": lambda **kw: calls.append(1)}, now=self.now + 2
        )
        self.assertEqual(calls, [])
        self.assertEqual(res_p["skipped_cards"][c_paused], "CARD_PAUSED")
        self.assertEqual(auto_attach.read_card(self.project, c_paused)["owner"], "antigravity")

        # Case B: cross-process pre-launch stop race (stopped AFTER claim_generation, BEFORE ADAPTER_STARTED)
        c_stop = auto_attach.enqueue_from_prompt(
            self.project, "antigravity", "Implement v7_harness/stop_race.py", session="s1", now=self.now + 5
        )["card_id"]
        claimed_flag = self.project / "claimed.flag"
        go_flag = self.project / "go.flag"
        race_code = (
            "import json, sys, time; from pathlib import Path\n"
            "from v7_harness.coord import auto_attach\n"
            "proj, card, cflag, gflag, now = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4]), float(sys.argv[5])\n"
            "called = []\n"
            "def hook(p, cid, peer, gen):\n"
            "    if cid == card:\n"
            "        cflag.write_text('yes', encoding='utf-8')\n"
            "        deadline = time.monotonic() + 15.0\n"
            "        while not gflag.exists() and time.monotonic() < deadline:\n"
            "            time.sleep(0.02)\n"
            "def adapter(**kw): called.append(1); return {'verified': True, 'session_id': 'bad'}\n"
            "res = auto_attach.reconcile_once(proj, adapters={'codex': adapter}, pre_launch_hook=hook, now=now)\n"
            "print(json.dumps({'called': len(called), 'res': res}))\n"
        )
        proc = _spawn_helper(race_code, str(self.project), c_stop, str(claimed_flag), str(go_flag), str(self.now + 6))
        deadline = time.monotonic() + 15.0
        while not claimed_flag.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(claimed_flag.exists())
        auto_attach.stop_card(self.project, c_stop, reason="user_stop", now=self.now + 7)
        go_flag.write_text("go", encoding="utf-8")

        out, err = proc.communicate(timeout=20)
        self.assertEqual(proc.returncode, 0, err)
        parsed = json.loads(out.strip().splitlines()[-1])
        self.assertEqual(parsed["called"], 0)
        self.assertEqual(auto_attach.read_claim(self.project, c_stop, "codex", 1)["state"], "ABORTED_BEFORE_LAUNCH")
        self.assertEqual(auto_attach.read_card(self.project, c_stop)["owner"], "antigravity")

    def test_8_windows_cross_process_different_projects_isolated(self) -> None:
        proj_a = Path(self._tmp.name) / "proj_a"
        proj_b = Path(self._tmp.name) / "proj_b"
        proj_a.mkdir()
        proj_b.mkdir()
        _seed_admitted_env(proj_a, now=self.now, roles={"codex": "EXECUTOR", "claude": "OFFLINE"})
        _seed_admitted_env(proj_b, now=self.now, roles={"codex": "EXECUTOR", "claude": "OFFLINE"})

        ca = auto_attach.enqueue_from_prompt(
            proj_a, "antigravity", "Implement v7_harness/shared_name.py", explicit_card="T-SHARED", session="sa", now=self.now
        )["card_id"]
        cb = auto_attach.enqueue_from_prompt(
            proj_b, "antigravity", "Implement v7_harness/shared_name.py", explicit_card="T-SHARED", session="sb", now=self.now
        )["card_id"]
        self.assertEqual(ca, "T-SHARED")
        self.assertEqual(cb, "T-SHARED")
        self.assertNotEqual(auto_attach.project_id(proj_a), auto_attach.project_id(proj_b))

        run_code = (
            "import json, sys; from pathlib import Path\n"
            "from v7_harness.coord import auto_attach\n"
            "proj, label, now = Path(sys.argv[1]), sys.argv[2], float(sys.argv[3])\n"
            "res = auto_attach.reconcile_once(proj, adapters={'codex': lambda **kw: {'verified': True, 'session_id': f'sess-{label}'}}, now=now)\n"
            "print(json.dumps(res))\n"
        )
        pa = _spawn_helper(run_code, str(proj_a), "A", str(self.now))
        pb = _spawn_helper(run_code, str(proj_b), "B", str(self.now))
        oa, ea = pa.communicate(timeout=20)
        ob, eb = pb.communicate(timeout=20)
        self.assertEqual(pa.returncode, 0, ea)
        self.assertEqual(pb.returncode, 0, eb)
        self.assertEqual(json.loads(oa)["peers"]["T-SHARED.codex"]["session_id"], "sess-A")
        self.assertEqual(json.loads(ob)["peers"]["T-SHARED.codex"]["session_id"], "sess-B")

    def test_9_adapter_without_verified_session_preserves_queue_and_owner(self) -> None:
        _seed_admitted_env(self.project, now=self.now, roles={"codex": "EXECUTOR", "claude": "OFFLINE"})
        c1 = auto_attach.enqueue_from_prompt(
            self.project, "antigravity", "Implement v7_harness/unverified.py", session="s-unv", now=self.now
        )["card_id"]

        res = auto_attach.reconcile_once(
            self.project,
            adapters={"codex": lambda **kw: {"verified": False, "session_id": ""}},
            now=self.now,
        )
        self.assertEqual(res["peers"][f"{c1}.codex"]["reason"], "NO_VERIFIED_SESSION")
        claim = auto_attach.read_claim(self.project, c1, "codex", 1)
        self.assertEqual(claim["state"], "NO_VERIFIED_SESSION")
        self.assertEqual(claim.get("verified_session_id", ""), "")
        self.assertEqual(auto_attach.read_card(self.project, c1)["owner"], "antigravity")
        q_item = next(q for q in auto_attach.read_queue(self.project) if q["card_id"] == c1)
        self.assertEqual(q_item["state"], "PENDING")

    def test_10_optional_hook_failure_leaves_auditable_pending_block_no_paid_fallthrough(self) -> None:
        calls = []

        def boom(*args, **kwargs):
            raise OSError("simulated lock I/O error")

        with mock.patch("subprocess.Popen") as popen_mock:
            res = auto_attach.hook_on_prompt(
                self.project,
                "codex",
                "Implement v7_harness/hook_fail.py",
                session="codex-desk",
                now=self.now,
                _enqueue_fn=boom,
            )
            popen_mock.assert_not_called()

        self.assertFalse(res["ok"])
        self.assertEqual(res["state"], "BLOCKED_HOOK_ERROR")
        audit_path = Path(res["audit_file"])
        self.assertTrue(audit_path.is_file())
        audit_doc = json.loads(audit_path.read_text(encoding="utf-8"))
        self.assertEqual(audit_doc["state"], "BLOCKED_HOOK_ERROR")
        self.assertIn("simulated lock I/O error", audit_doc["error"])
        self.assertEqual(calls, [])

    def test_11_claude_exact_watcher_route_only_else_durable_non_waking_notice(self) -> None:
        _seed_admitted_env(self.project, now=self.now, roles={"codex": "OFFLINE", "claude": "EXECUTOR"})
        card_id = auto_attach.enqueue_from_prompt(
            self.project, "antigravity", "Implement v7_harness/claude_route.py", session="s-cl", now=self.now
        )["card_id"]

        claude_calls: list[str] = []

        def claude_adapter(**kw):
            claude_calls.append(kw["exact_session"])
            return {"verified": True, "session_id": f"tab-{kw['companion_id']}"}

        # 11a. Without exact waking watcher -> durable non-waking notice only, zero adapter/subprocess calls
        with mock.patch("subprocess.Popen") as popen_mock:
            res_no_watcher = auto_attach.reconcile_once(
                self.project,
                adapters={"claude": claude_adapter},
                claude_watcher_check=lambda _p, _s: False,
                now=self.now,
            )
            popen_mock.assert_not_called()

        self.assertEqual(claude_calls, [])
        peer_res = res_no_watcher["peers"][f"{card_id}.claude"]
        self.assertEqual(peer_res["status"], "DURABLE_NON_WAKING_NOTICE")
        notice_path = self.project / ".coord" / "auto_attach" / "claude_notices" / f"{card_id}.claude.json"
        self.assertTrue(notice_path.is_file())
        notice = json.loads(notice_path.read_text(encoding="utf-8"))
        self.assertEqual(notice["status"], "DURABLE_NON_WAKING_NOTICE")
        self.assertEqual(notice["launch_spec"]["method"], "mcp__ccd_session__start_session")
        self.assertEqual(auto_attach.read_card(self.project, card_id)["owner"], "antigravity")

        # 11b. Once user_desk_claude.json binds exact live waking session -> routes exclusively to it
        (self.project / ".coord" / "presence" / "user_desk_claude.json").write_text(
            json.dumps({"thread": "claude-desk-live-777", "at": self.now}), encoding="utf-8"
        )
        res_ok = auto_attach.reconcile_once(
            self.project,
            adapters={"claude": claude_adapter},
            claude_watcher_check=lambda _p, s: s == "claude-desk-live-777",
            now=self.now + 5,
        )
        self.assertEqual(claude_calls, ["claude-desk-live-777"])
        self.assertEqual(res_ok["peers"][f"{card_id}.claude"]["status"], "VERIFIED_OPEN")

    def test_12_overlap_guard_and_finish_card_reconcile_promotes_fifo(self) -> None:
        _seed_admitted_env(self.project, now=self.now, roles={"codex": "EXECUTOR", "claude": "OFFLINE"})

        # Primary A owns v7_harness/shared_mod.py
        a = auto_attach.enqueue_from_prompt(
            self.project, "antigravity", "Implement v7_harness/shared_mod.py", session="s-a", now=self.now
        )
        # Primary B from different tool touches same file -> held WAITING with blocked_by=A
        b = auto_attach.enqueue_from_prompt(
            self.project, "codex", "Modify v7_harness/shared_mod.py", session="s-b", now=self.now + 1
        )
        self.assertEqual(b["state"], "WAITING")
        self.assertEqual(b["blocked_by"], a["card_id"])

        opened: list[str] = []

        def adapter(**kw):
            opened.append(f"{kw['card_id']}:{kw['peer']}")
            return {"verified": True, "session_id": f"win-{kw['card_id']}-{kw['peer']}"}

        # Reconcile attaches A only; B stays WAITING (0 competing peer launches for B)
        auto_attach.reconcile_once(self.project, adapters={"codex": adapter}, now=self.now + 2)
        self.assertEqual(opened, [f"{a['card_id']}:codex"])

        # Finish A cleanly via trusted close callback -> closes A's companion, unblocks B to RUNNING
        closed: list[str] = []
        fin = auto_attach.finish_card(
            self.project,
            a["card_id"],
            "antigravity",
            "completed cleanly",
            close_adapter=lambda **kw: closed.append(kw["companion_id"]) or {"closed": True},
            now=self.now + 5,
        )
        self.assertEqual(closed, [f"{a['card_id']}.codex"])
        self.assertEqual(fin["status"], "DONE")
        self.assertIn(b["card_id"], fin["unblocked"])

        # Next reconcile_once promotes B's peer ("antigravity") automatically
        auto_attach.reconcile_once(self.project, adapters={"antigravity": adapter}, now=self.now + 6)
        self.assertIn(f"{b['card_id']}:antigravity", opened)

    def test_13_circuit_breaker_trips_on_provider_errors_and_fast_fails_zero_wait(self) -> None:
        _seed_admitted_env(self.project, now=self.now)
        c1 = auto_attach.record_peer_failure(
            self.project, "antigravity", error="PROVIDER_ERROR", now=self.now
        )
        self.assertEqual(c1["state"], "CLOSED")
        self.assertEqual(c1["consecutive_failures"], 1)

        c2 = auto_attach.record_peer_failure(
            self.project, "antigravity", error="PROVIDER_ERROR", now=self.now + 1
        )
        self.assertEqual(c2["state"], "OPEN")
        self.assertEqual(c2["open_until"], self.now + 1 + auto_attach.CB_COOLDOWN_S)

        t0 = time.perf_counter()
        pick = auto_attach.select_verdict_judge(self.project, author="claude", now=self.now + 2)
        self.assertLess((time.perf_counter() - t0) * 1000.0, 200.0)
        self.assertEqual(pick["judge"], "codex")
        self.assertEqual(pick["skipped"]["antigravity"], "CIRCUIT_OPEN")

        half = auto_attach.get_circuit_state(
            self.project, "antigravity", now=self.now + 2 + auto_attach.CB_COOLDOWN_S
        )
        self.assertEqual(half["state"], "HALF_OPEN")
        closed = auto_attach.record_peer_success(self.project, "antigravity", now=self.now + 400)
        self.assertEqual(closed["state"], "CLOSED")
        self.assertEqual(closed["consecutive_failures"], 0)

    def test_14_ack_sla_fast_failover_replaces_30min_stall_with_zero_pingpong(self) -> None:
        _seed_admitted_env(self.project, now=self.now)
        req = auto_attach.create_verdict_request(
            self.project,
            card_id="U330",
            author="claude",
            preferred_judge="antigravity",
            req_id="req_u330",
            now=self.now,
        )
        self.assertEqual(req["current_judge"], "antigravity")
        self.assertEqual(req["state"], "AWAITING_ACK")

        # Before ACK_SLA_S -> remains with antigravity
        r_early = auto_attach.reconcile_verdict_requests(self.project, now=self.now + 5)
        self.assertEqual(r_early["rerouted"], [])

        # Just past ACK_SLA_S (31s, NOT 1800s!) -> fast failover to codex without ping-pong
        r_failover = auto_attach.reconcile_verdict_requests(
            self.project, now=self.now + auto_attach.ACK_SLA_S + 1.0
        )
        self.assertEqual(len(r_failover["rerouted"]), 1)
        self.assertEqual(r_failover["rerouted"][0]["to"], "codex")
        after1 = auto_attach.read_verdict_request(self.project, "req_u330")
        self.assertEqual(after1["tried_tools"], ["antigravity", "codex"])
        self.assertEqual(after1["hops"], 1)

        # Even if codex then limits/expires, NEVER bounce back to already-tried antigravity -> EXHAUSTED_WAIT_RESET
        _seed_admitted_env(
            self.project,
            now=self.now + 100.0,
            roles={"codex": "OFFLINE", "claude": "EXECUTOR", "antigravity": "EXECUTOR"},
            presence_states={"codex": "LIMITED", "claude": "ACTIVE", "antigravity": "ACTIVE"},
        )
        r_exh = auto_attach.reconcile_verdict_requests(self.project, now=self.now + 100.0)
        self.assertIn("req_u330", r_exh["exhausted"])
        after2 = auto_attach.read_verdict_request(self.project, "req_u330")
        self.assertEqual(after2["state"], "EXHAUSTED_WAIT_RESET")
        self.assertEqual(after2["tried_tools"], ["antigravity", "codex"])
        self.assertGreater(after2["next_wake_at"], self.now + 100.0)

    def test_15_symmetric_non_author_judge_pool_includes_claude_when_codex_limited(self) -> None:
        _seed_admitted_env(
            self.project,
            now=self.now,
            mode="DUO",
            roles={"codex": "OFFLINE", "claude": "EXECUTOR", "antigravity": "EXECUTOR"},
            presence_states={"codex": "LIMITED", "claude": "ACTIVE", "antigravity": "ACTIVE"},
        )
        # Non-keypoint AGY-authored card routes cleanly to Claude (never self-judge AGY)
        pick_normal = auto_attach.select_verdict_judge(
            self.project, author="antigravity", keypoint_codex_only=False, now=self.now
        )
        self.assertEqual(pick_normal["judge"], "claude")
        self.assertNotEqual(pick_normal["judge"], "antigravity")

        # Codex-exclusive keypoint ALWAYS fails closed when Codex is LIMITED, reporting reset timestamp
        pick_kp = auto_attach.select_verdict_judge(
            self.project, author="antigravity", keypoint_codex_only=True, now=self.now
        )
        self.assertIsNone(pick_kp["judge"])
        self.assertEqual(pick_kp["reason"], "KEYPOINT_NEEDS_CODEX")
        self.assertEqual(pick_kp["next_wake_at"], self.now + 3600.0)

    def test_16_windows_cross_process_tied_judge_single_winner_cancels_loser(self) -> None:
        _seed_admitted_env(self.project, now=self.now)
        auto_attach.create_verdict_request(
            self.project,
            card_id="U330",
            author="claude",
            preferred_judge="antigravity",
            req_id="req_tied",
            now=self.now,
        )
        auto_attach.ack_verdict_request(self.project, "req_tied", "antigravity", now=self.now + 5)
        rec_h = auto_attach.reconcile_verdict_requests(
            self.project, now=self.now + auto_attach.VERDICT_SLA_S + 2.0
        )
        self.assertEqual(len(rec_h["hedged"]), 1)
        req = auto_attach.read_verdict_request(self.project, "req_tied")
        self.assertEqual(req["state"], "TIED_HEDGED")
        self.assertEqual(set(req["hedged_judges"]), {"antigravity", "codex"})

        # Prevent self-approval inside submit_verdict too
        with self.assertRaises(PermissionError):
            auto_attach.submit_verdict(
                self.project, "req_tied", judge="claude", verdict="PASS", now=self.now + 200
            )

        sub_code = (
            "import json, sys; from pathlib import Path\n"
            "from v7_harness.coord import auto_attach\n"
            "proj, req_id, judge_name, now = Path(sys.argv[1]), sys.argv[2], sys.argv[3], float(sys.argv[4])\n"
            "res = auto_attach.submit_verdict(proj, req_id, judge=judge_name, verdict='PASS', evidence=f'ev-{judge_name}', now=now)\n"
            "print(json.dumps(res))\n"
        )
        p1 = _spawn_helper(sub_code, str(self.project), "req_tied", "antigravity", str(self.now + 200))
        p2 = _spawn_helper(sub_code, str(self.project), "req_tied", "codex", str(self.now + 200))
        o1, e1 = p1.communicate(timeout=20)
        o2, e2 = p2.communicate(timeout=20)
        self.assertEqual(p1.returncode, 0, e1)
        self.assertEqual(p2.returncode, 0, e2)
        r1 = json.loads(o1.strip().splitlines()[-1])
        r2 = json.loads(o2.strip().splitlines()[-1])

        self.assertEqual([r["won"] for r in (r1, r2)].count(True), 1)
        self.assertEqual([r["status"] for r in (r1, r2)].count("VERDICT_COMMITTED"), 1)
        self.assertEqual([r["status"] for r in (r1, r2)].count("CANCELLED_SUPERSEDED"), 1)

    def test_17_anti_bottleneck_sla_never_violates_no_ttl_reclaim_of_inflight_claims(self) -> None:
        _seed_admitted_env(self.project, now=self.now, roles={"codex": "EXECUTOR", "claude": "OFFLINE"})
        card_id = auto_attach.enqueue_from_prompt(
            self.project, "antigravity", "Implement v7_harness/sla_no_ttl.py", session="s-nttl", now=self.now
        )["card_id"]
        flag = self.project / "nttl_ready.flag"
        hold_code = (
            "import sys, time; from pathlib import Path\n"
            "from v7_harness.coord import auto_attach\n"
            "proj, cid, flag, now = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), float(sys.argv[4])\n"
            "assert auto_attach.claim_generation(proj, cid, 'codex', 1, now=now)['claimed'] is True\n"
            "flag.write_text('held', encoding='utf-8')\n"
            "time.sleep(30)\n"
        )
        proc = _spawn_helper(hold_code, str(self.project), card_id, str(flag), str(self.now))
        try:
            deadline = time.monotonic() + 15.0
            while not flag.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(flag.exists())

            future = self.now + 86400.0
            _seed_admitted_env(self.project, now=future, roles={"codex": "EXECUTOR", "claude": "OFFLINE"})
            res_claim = auto_attach.reconcile_once(self.project, adapters={}, now=future)
            res_vrd = auto_attach.reconcile_verdict_requests(self.project, now=future)
            self.assertEqual(res_claim["peers"][f"{card_id}.codex"]["reason"], "HELD_BY_SLOW_OWNER")
            self.assertEqual(auto_attach.read_claim(self.project, card_id, "codex", 1)["state"], "CLAIMED")
            self.assertEqual(res_vrd["open_waits"], [])
        finally:
            proc.terminate()
            proc.wait(timeout=10)
            if proc.stdout:
                proc.stdout.close()
            if proc.stderr:
                proc.stderr.close()

    def test_18_zombie_request_closure_clears_answered_and_done_card_waits(self) -> None:
        _seed_admitted_env(self.project, now=self.now)
        c_done = auto_attach.enqueue_from_prompt(
            self.project, "claude", "Implement v7_harness/zombie_done.py", session="zd", now=self.now
        )["card_id"]
        auto_attach.create_verdict_request(
            self.project, card_id=c_done, author="claude", req_id="req_z_done", now=self.now
        )
        auto_attach.finish_card(self.project, c_done, "claude", "merged", now=self.now + 5)

        auto_attach.create_verdict_request(
            self.project, card_id="U331", author="antigravity", req_id="req_z_answered", now=self.now + 10
        )
        rec = auto_attach.reconcile_verdict_requests(
            self.project, answered_ids={"req_z_answered"}, now=self.now + 15
        )
        self.assertEqual(set(rec["converged"]), {"req_z_done", "req_z_answered"})
        self.assertEqual(rec["open_waits"], [])
        self.assertEqual(auto_attach.read_verdict_request(self.project, "req_z_done")["state"], "CLOSED_CONVERGED")
        self.assertEqual(auto_attach.read_verdict_request(self.project, "req_z_answered")["state"], "CLOSED_CONVERGED")


if __name__ == "__main__":
    unittest.main()
