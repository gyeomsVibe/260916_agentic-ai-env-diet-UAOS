"""U390 [긴급] Fixed Acceptance, Vaccine Counterexamples & Parallel Concurrency Suite.

Covers:
1. Raw abstract idea -> repo-grounded spec -> disjoint cycle-free 3-tool gear DAG
2. 50/30/20 Ollama + 3-tool helper optimization plan (6GB VRAM + paused-pool failover)
3. Disjoint Ollama VRAM & PROVIDER_ERROR guard (PROMPT_TOO_LARGE 0-call rejection,
   dynamic 4096/8192/16384 ctx, Go keep_alive normalization, bounded retry, GPU lease)
4. Presence split-brain cure (unified_desks pause lease -> LIMITED, fail-closed UNKNOWN,
   audit_desk_split_brain)
5. Sentinel wake storm deduplication & deletion-free archiving + mailbox compact_inbox
6. Desk router schema-grounded concretization & fallback safety
7. Urgent card non-hijack handshake & live full-stack health auditor
8. Parallel ThreadPoolExecutor atomicity & all 8 U330 worst-case failure-mode proofs
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import datetime
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest import mock

from v7_harness.adapters import ollama_vram_guard
from v7_harness.coord import desk_router, idea_fullstack, mailbox, presence, sentinel, uaos_fullstack_os

REPO_ROOT = Path(__file__).resolve().parents[1]


class U390RawIdeaToGearsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        for rel in (
            "v7_harness/coord/idea_fullstack.py",
            "v7_harness/coord/desk_router.py",
            "v7_harness/coord/presence.py",
            "v7_harness/coord/mailbox.py",
            "v7_harness/coord/sentinel.py",
            "v7_harness/adapters/ollama_vram_guard.py",
            "v7_harness/coord/usage_budget.py",
            "v7_harness/coord/auto_attach.py",
            "v7_harness/coord/windows.py",
        ):
            p = self.project / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("# stub\n", encoding="utf-8")

    def test_vague_korean_idea_grounds_and_builds_disjoint_gears(self) -> None:
        raw = "사용자의 날것 아이디어를 3대 도구가 어긋남 없이 자동으로 구체화해서 현실로 만드는 풀스택 시스템을 완성해줘"
        spec = idea_fullstack.concretize_raw_idea(self.project, raw)
        self.assertGreaterEqual(len(spec["grounded_files"]), 3)
        self.assertIn("v7_harness/coord/idea_fullstack.py", spec["grounded_files"])
        self.assertTrue(spec["measurable_success_signals"])
        self.assertIn(spec["mia_tier"]["tier"], ("MIA-Standard", "MIA-Full"))

        full_spec = idea_fullstack.concretize_raw_idea(
            self.project,
            "권한 사서함 올라마 아이디어 구체화 풀스택 톱니바퀴 자동화 시스템을 완성해줘",
        )
        self.assertEqual(full_spec["mia_tier"]["tier"], "MIA-Full")

        dag = idea_fullstack.build_gear_dag(
            full_spec,
            tool_states={"codex": "ACTIVE", "antigravity": "ACTIVE", "claude": "LIMITED"},
            quota_snapshot={"claude": {"7d_remaining_pct": 1.0, "paused": True}},
            existing_locked_files=[
                "v7_harness/coord/sentinel.py",
                "v7_harness/coord/auto_attach.py",
                "v7_harness/coord/windows.py",
            ],
            max_slice_files=2,
        )
        self.assertTrue(dag["cycle_free"])
        self.assertNotIn("claude", dag["active_tools"])
        self.assertIn("v7_harness/coord/sentinel.py", dag["excluded_locked_files"])

        seen_files: set[str] = set()
        for unit in dag["units"]:
            self.assertNotEqual(unit["owner"], unit["judge"])
            self.assertNotEqual(unit["owner"], "claude")
            overlap = seen_files & set(unit["allow_files"])
            self.assertEqual(set(), overlap)
            seen_files.update(unit["allow_files"])
        self.assertNotIn("v7_harness/coord/auto_attach.py", seen_files)
        self.assertNotIn("v7_harness/coord/windows.py", seen_files)

    def test_keypoint_pins_codex_judge_and_helper_plan_honors_vram_and_unmeasured(self) -> None:
        spec = idea_fullstack.concretize_raw_idea(
            self.project,
            "전역규칙 보안 권한 아키텍처 개선 및 올라마 예산 최적화",
        )
        dag = idea_fullstack.build_gear_dag(
            spec,
            tool_states={"codex": "ACTIVE", "antigravity": "ACTIVE", "claude": "UNKNOWN"},
            quota_snapshot={"claude": {"7d_remaining_pct": 1.0}},
        )
        self.assertTrue(dag["is_keypoint"])
        for unit in dag["units"]:
            if unit["owner"] != "codex":
                self.assertEqual("codex", unit["judge"])

        alloc = idea_fullstack.plan_ollama_helper_allocation(
            dag,
            vram_gb=6.0,
            installed_models=("qwen3-embedding:0.6b", "qwen2.5-coder:3b", "qwen2.5-coder:7b"),
            tool_states={"codex": "ACTIVE", "antigravity": "ACTIVE", "claude": "LIMITED"},
            quota_snapshot={"claude": {"7d_remaining_pct": 1.0, "paused": True}},
        )
        self.assertEqual({"ollama_pct": 50.0, "helper_pct": 30.0, "paid_core_pct": 20.0}, alloc["target_parallel_ratio"])
        self.assertEqual("UNMEASURED", alloc["paid_savings_status"])
        self.assertFalse(alloc["helper_pool"]["claude"]["available"])
        self.assertTrue(alloc["helper_pool"]["antigravity"]["available"])
        self.assertTrue(alloc["helper_pool"]["codex"]["available"])
        impl_rows = [a for a in alloc["assignments"] if a["unit_id"].startswith("STAGE_IMPL_")]
        self.assertTrue(impl_rows)
        self.assertTrue(all(r["serial_gpu_lock"] and r["max_prompt_tokens"] <= 10000 for r in impl_rows))


class U390OllamaVramGuardVaccineTest(unittest.TestCase):
    def test_preflight_blocks_18750_token_prompt_with_zero_calls(self) -> None:
        oversized_prompt = "x" * (18750 * 3)
        calls = 0

        def fake_call(**_kwargs):
            nonlocal calls
            calls += 1
            return "ok"

        with self.assertRaises(ollama_vram_guard.PromptBudgetExceeded) as ctx:
            ollama_vram_guard.call_with_vram_guard(fake_call, prompt=oversized_prompt, use_gpu_lease=False)
        self.assertIn("PROMPT_TOO_LARGE", str(ctx.exception))
        self.assertEqual(0, calls)

    def test_vram_ctx_buckets_and_iso_keep_alive_normalization(self) -> None:
        self.assertEqual(8192, ollama_vram_guard.choose_vram_safe_ctx(1500))
        self.assertEqual(16384, ollama_vram_guard.choose_vram_safe_ctx(9000))
        self.assertEqual("10m", ollama_vram_guard.normalize_keep_alive("PT10M"))
        self.assertEqual("2h", ollama_vram_guard.normalize_keep_alive("pt2h"))
        self.assertEqual("-1", ollama_vram_guard.normalize_keep_alive("-1"))
        self.assertEqual("5m", ollama_vram_guard.normalize_keep_alive("garbage"))

    def test_bounded_retry_succeeds_once_and_releases_gpu_lease(self) -> None:
        attempts = 0
        seen: list[dict] = []

        def flaky(**kwargs):
            nonlocal attempts
            attempts += 1
            seen.append(kwargs)
            if attempts == 1:
                raise TimeoutError("transient cold start")
            return {"status": "ok"}

        with tempfile.TemporaryDirectory() as d, mock.patch("v7_harness.adapters.gpu_priority.GPU_DIR", Path(d)):
            res = ollama_vram_guard.call_with_vram_guard(
                flaky,
                prompt="short prompt",
                keep_alive="PT10M",
                timeout_s=90,
                retries=1,
                backoff_s=0.0,
                use_gpu_lease=True,
            )
            self.assertEqual({"status": "ok"}, res)
            self.assertEqual(2, attempts)
            self.assertEqual("10m", seen[0]["keep_alive"])
            self.assertEqual(8192, seen[0]["num_ctx"])
            self.assertEqual([], list(Path(d).glob("pilot-*.json")))


class U390PresenceAndDeskSplitBrainTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.project / ".coord" / "presence").mkdir(parents=True)

    def test_paused_unified_desk_turns_expired_claude_into_limited_while_missing_codex_stays_unknown(self) -> None:
        now = 1_800_000_000.0
        future_iso = datetime.datetime.fromtimestamp(now + 36000, tz=datetime.timezone.utc).isoformat()
        (self.project / ".coord" / "presence" / "unified_desks.json").write_text(
            json.dumps(
                {
                    "desks": {
                        "claude": {"session_id": "s-claude", "desk_gen": 1, "execution_paused_until": future_iso},
                        "codex": {"session_id": "s-codex-old", "desk_gen": 22},
                    }
                }
            ),
            encoding="utf-8",
        )
        # Expired claude heartbeat must become LIMITED (via pause lease), never ACTIVE or UNKNOWN.
        presence.mark(self.project, "claude", "ACTIVE", ttl_s=10, now=now - 100)
        cl = presence.read(self.project, "claude", now=now)
        self.assertEqual("LIMITED", cl["state"])
        self.assertEqual("unified_desks_pause", cl["evidence"]["source"])

        # Expired codex heartbeat WITHOUT a pause lease MUST stay fail-closed UNKNOWN!
        presence.mark(self.project, "codex", "ACTIVE", ttl_s=10, now=now - 100)
        cx = presence.read(self.project, "codex", now=now)
        self.assertEqual("UNKNOWN", cx["state"])

        # Once codex and antigravity are ACTIVE, conductor is codex (not UNKNOWN because of claude!).
        presence.mark(self.project, "codex", "ACTIVE", ttl_s=600, now=now)
        presence.mark(self.project, "antigravity", "ACTIVE", ttl_s=600, now=now)
        cond = presence.conductor(presence.read_all(self.project, now=now))
        self.assertEqual("codex", cond["conductor"])

    def test_audit_desk_split_brain_detects_codex_drift(self) -> None:
        pres = self.project / ".coord" / "presence"
        (pres / "unified_desks.json").write_text(
            json.dumps({"desks": {"codex": {"session_id": "01a20bd1", "desk_gen": 22}}}),
            encoding="utf-8",
        )
        (pres / "user_desk_codex.json").write_text(
            json.dumps({"thread": "01a20c43", "generation": 23}),
            encoding="utf-8",
        )
        mismatches = presence.audit_desk_split_brain(self.project)
        self.assertEqual(1, len(mismatches))
        self.assertEqual("CODEX_DESK_DRIFT", mismatches[0]["code"])


class U390MailboxAndSentinelStormTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.project / ".coord" / "mailbox").mkdir(parents=True)
        self.box = mailbox.Mailbox(self.project / ".coord" / "mailbox")

    def test_sentinel_dedupes_reordered_reasons_and_archives_superseded_wakes(self) -> None:
        self.box.publish("b1", {"kind": "BLOCKED", "step": "U320", "ts": "2026-11-24T10:00:00+09:00"})
        self.box.publish("b2", {"kind": "BLOCKED", "step": "U321", "ts": "2026-11-24T10:00:00+09:00"})
        r1 = sentinel.run_sentinel_cycle(self.project, self.box, recipient="antigravity")
        self.assertTrue(r1["p1_wake_emitted"])

        # Add a duplicate b2_dup for the same step U321 -> canonical fingerprint matches! No second wake!
        self.box.publish("b2_dup", {"kind": "BLOCKED", "step": "U321", "ts": "2026-11-24T10:01:00+09:00"})
        r2 = sentinel.run_sentinel_cycle(self.project, self.box, recipient="antigravity")
        self.assertFalse(r2["p1_wake_emitted"])

        # Add a genuinely new P1 step U322 -> emits new wake and archives the superseded wake deletion-free.
        self.box.publish("b3", {"kind": "BLOCKED", "step": "U322", "ts": "2026-11-24T10:02:00+09:00"})
        r3 = sentinel.run_sentinel_cycle(self.project, self.box, recipient="antigravity")
        self.assertTrue(r3["p1_wake_emitted"])
        self.assertEqual(1, len(r3["superseded_wakes_archived"]))
        active_wakes = list(self.box.inbox_dir.glob("wake_*.json"))
        archived_wakes = list((self.box.root / "archive" / "superseded_wakes").glob("wake_*.json"))
        self.assertEqual(1, len(active_wakes))
        self.assertEqual(1, len(archived_wakes))

    def test_compact_inbox_dry_run_and_zero_deletion_apply(self) -> None:
        for i in range(45):
            self.box.publish(f"evt_20261124T10{i:02d}_a", {"kind": "RUN", "step": f"S{i}"})
        self.box.publish("relay_important_1", {"kind": "HANDOFF", "message": "keep"})
        self.box.publish("rsi_review_1", {"kind": "RSI_REVIEW", "message": "keep"})
        for w in ("wake_aaa1", "wake_aaa2"):
            self.box.publish(
                w,
                {"recipient": "antigravity", "wake_reason": "BLOCKED_TASK: U320", "canonical_fingerprint": "samefp"},
            )

        before_total = len(list(self.box.inbox_dir.glob("*.json")))
        dry = mailbox.compact_inbox(self.project, keep_recent_events=10, dry_run=True)
        self.assertEqual(0, dry["moved_count"])
        self.assertEqual(36, dry["candidate_count"])  # 35 old events + 1 duplicate wake
        self.assertEqual(before_total, len(list(self.box.inbox_dir.glob("*.json"))))

        applied = mailbox.compact_inbox(self.project, keep_recent_events=10, dry_run=False)
        self.assertTrue(applied["ok"])
        self.assertEqual(36, applied["moved_count"])
        self.assertTrue((self.box.inbox_dir / "relay_important_1.json").is_file())
        self.assertTrue((self.box.inbox_dir / "rsi_review_1.json").is_file())
        after_inbox = list(self.box.inbox_dir.glob("*.json"))
        archived = [p for p in Path(applied["archive_target"]).glob("*.json") if not p.name.startswith("compaction_receipt_")]
        self.assertEqual(before_total, len(after_inbox) + len(archived))


class U390DeskRouterHandshakeAndLiveAuditTest(unittest.TestCase):
    def test_desk_router_concretize_grounds_project_and_survives_bad_ollama_json(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            (proj / "v7_harness" / "coord").mkdir(parents=True)
            (proj / "v7_harness" / "coord" / "mailbox.py").write_text("# m\n", encoding="utf-8")
            out = desk_router.concretize("사서함 병목 정리해줘", lambda *_a: "{not-json", project=proj)
            self.assertEqual("deterministic_fallback", out["source"])
            self.assertIn("v7_harness/coord/mailbox.py", out["grounded_files"])
            self.assertIn("mia_tier", out)

    def test_urgent_card_handshake_forbids_director_hijack(self) -> None:
        with self.assertRaises(ValueError):
            idea_fullstack.build_urgent_card_handshake(
                card_id="U390",
                session_id="c0845068",
                director_session="c0845068",
                codex_session="01a20c43",
                disjoint_files=["v7_harness/coord/idea_fullstack.py"],
                user_approved=True,
            )
        pkt = idea_fullstack.build_urgent_card_handshake(
            card_id="U390",
            session_id="830f7648",
            director_session="c0845068",
            codex_session="01a20c43",
            disjoint_files=["v7_harness/coord/idea_fullstack.py"],
            user_approved=True,
        )
        self.assertEqual("c0845068", pkt["preserved_director_session"])

    def test_diagnose_fullstack_health_read_only_live_repo(self) -> None:
        report = idea_fullstack.diagnose_fullstack_health(REPO_ROOT)
        self.assertIn("blockers", report)
        self.assertIn("summary", report)


class U390ParallelAndFailureModeProofs(unittest.TestCase):
    """Parallel ThreadPoolExecutor atomicity + 1:1 named U330 failure-mode tests."""

    def test_parallel_compact_and_sentinel_atomicity(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            (proj / ".coord" / "mailbox").mkdir(parents=True)
            box = mailbox.Mailbox(proj / ".coord" / "mailbox")
            for i in range(40):
                box.publish(f"evt_par_{i:03d}", {"kind": "RUN", "step": f"P{i}"})
            before = len(list(box.inbox_dir.glob("*.json")))

            with ThreadPoolExecutor(max_workers=4) as pool:
                futs = [pool.submit(mailbox.compact_inbox, proj, keep_recent_events=10, dry_run=False) for _ in range(4)]
                results = [f.result() for f in futs]

            self.assertTrue(all(r["ok"] for r in results))
            total_moved = sum(r["moved_count"] for r in results)
            self.assertEqual(30, total_moved)
            self.assertEqual(10, len(list(box.inbox_dir.glob("*.json"))))
            self.assertEqual(before, 10 + total_moved)

    def test_failure_peer_silent_or_limit_exhausted(self) -> None:
        now = 1_800_000_000.0
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            (proj / ".coord" / "presence").mkdir(parents=True)
            iso = datetime.datetime.fromtimestamp(now + 7200, tz=datetime.timezone.utc).isoformat()
            (proj / ".coord" / "presence" / "unified_desks.json").write_text(
                json.dumps({"desks": {"claude": {"execution_paused_until": iso}}}),
                encoding="utf-8",
            )
            self.assertEqual("LIMITED", presence.read(proj, "claude", now=now)["state"])

    def test_failure_message_flood(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            (proj / ".coord" / "mailbox").mkdir(parents=True)
            box = mailbox.Mailbox(proj / ".coord" / "mailbox")
            for i in range(25):
                box.publish(f"evt_flood_{i:02d}", {"kind": "RUN", "step": "S"})
            res = mailbox.compact_inbox(proj, keep_recent_events=5, dry_run=False)
            self.assertEqual(20, res["moved_count"])

    def test_failure_wait_cycle_or_deadlock(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            (proj / "v7_harness" / "coord").mkdir(parents=True)
            (proj / "v7_harness" / "coord" / "presence.py").write_text("# p\n", encoding="utf-8")
            spec = idea_fullstack.concretize_raw_idea(proj, "권한 출석 복구")
            dag = idea_fullstack.build_gear_dag(spec, tool_states={"codex": "ACTIVE", "antigravity": "ACTIVE"})
            self.assertTrue(dag["cycle_free"])

    def test_failure_crash_mid_write(self) -> None:
        with self.assertRaises(ollama_vram_guard.PromptBudgetExceeded):
            ollama_vram_guard.call_with_vram_guard(lambda **_kw: None, prompt="z" * 60000, use_gpu_lease=False)

    def test_failure_duplicate_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            (proj / ".coord" / "mailbox").mkdir(parents=True)
            box = mailbox.Mailbox(proj / ".coord" / "mailbox")
            box.publish("b1", {"kind": "BLOCKED", "step": "U999", "ts": "2026-11-24T10:00:00+09:00"})
            self.assertTrue(sentinel.run_sentinel_cycle(proj, box, recipient="antigravity")["p1_wake_emitted"])
            box.publish("b2", {"kind": "BLOCKED", "step": "U999", "ts": "2026-11-24T10:01:00+09:00"})
            self.assertFalse(sentinel.run_sentinel_cycle(proj, box, recipient="antigravity")["p1_wake_emitted"])

    def test_failure_stale_state(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            (proj / ".coord" / "presence").mkdir(parents=True)
            presence.mark(proj, "codex", "ACTIVE", ttl_s=10, now=1000.0)
            self.assertEqual("UNKNOWN", presence.read(proj, "codex", now=1020.0)["state"])

    def test_failure_conductor_down(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            (proj / ".coord" / "presence").mkdir(parents=True)
            presence.mark(proj, "codex", "LIMITED", ttl_s=600, now=1000.0)
            presence.mark(proj, "claude", "LIMITED", ttl_s=600, now=1000.0)
            presence.mark(proj, "antigravity", "ACTIVE", ttl_s=600, now=1000.0)
            cond = presence.conductor(presence.read_all(proj, now=1010.0))
            self.assertEqual("antigravity", cond["conductor"])
            self.assertTrue(cond["acting"])

    def test_failure_user_absent(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            (proj / "v7_harness" / "coord").mkdir(parents=True)
            (proj / "v7_harness" / "coord" / "desk_router.py").write_text("# r\n", encoding="utf-8")
            spec = idea_fullstack.concretize_raw_idea(proj, "원격 푸시 및 배포 승인 요청 테스트")
            self.assertTrue(spec["clarification_questions"])


class U390FullStackOsRedesignTest(unittest.TestCase):
    """Step 2 proofs for the 6-pillar unattended, zero-approval, nonstop, parallel, RSI OS."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        for rel in (
            "v7_harness/coord/idea_fullstack.py",
            "v7_harness/coord/uaos_fullstack_os.py",
            "v7_harness/coord/desk_router.py",
            "v7_harness/coord/presence.py",
            "v7_harness/coord/mailbox.py",
            "v7_harness/coord/sentinel.py",
            "v7_harness/adapters/ollama_vram_guard.py",
        ):
            p = self.project / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("# stub\n", encoding="utf-8")
        (self.project / ".coord" / "presence").mkdir(parents=True, exist_ok=True)
        (self.project / ".coord" / "mailbox" / "inbox").mkdir(parents=True, exist_ok=True)
        (self.project / ".coord" / "usage").mkdir(parents=True, exist_ok=True)

    def test_unattended_tick_concretizes_dispatches_and_enforces_safety7_boundary(self) -> None:
        now = 1_800_000_000.0
        presence.mark(self.project, "codex", "ACTIVE", ttl_s=600, now=now)
        presence.mark(self.project, "antigravity", "ACTIVE", ttl_s=600, now=now)
        presence.mark(self.project, "claude", "LIMITED", ttl_s=600, now=now)

        # Negation-aware boundary check: forbidding push stays AUTONOMOUS_GO; explicit prod deploy parks.
        neg = uaos_fullstack_os.classify_autonomy_boundary("원격 푸시 금지하고 로컬 테스트만 수행해줘")
        self.assertEqual("AUTONOMOUS_GO", neg["mode"])

        res = uaos_fullstack_os.tick_fullstack_os(
            self.project,
            raw_ideas=[
                "원격 푸시 금지하고 올라마 사서함 풀스택 톱니바퀴 자동화해줘",
                "프로덕션 배포 및 원격 푸시 실행해줘",
            ],
            existing_locked_files=["v7_harness/coord/windows.py"],
            installed_models=("qwen3-embedding:0.6b", "qwen2.5-coder:3b", "qwen2.5-coder:7b"),
            admitted={"codex": True, "antigravity": True, "claude": False},
            launcher=lambda card: {"opened": True, "window_id": f"win-{card['card_id']}"},
            now=now,
        )
        self.assertTrue(res["ok"])
        self.assertEqual(2, len(res["ingested"]))
        self.assertEqual("SCHEDULED", res["ingested"][0]["status"])
        self.assertEqual("AWAITING_HUMAN_SAFETY", res["ingested"][1]["status"])
        self.assertNotEqual(res["ingested"][0]["owner"], res["ingested"][0]["judge"])
        self.assertEqual(1, len(res["dispatched"]))
        state = uaos_fullstack_os.load_os_state(self.project)
        c0 = state["cards"][res["ingested"][0]["card_id"]]
        self.assertEqual("DISPATCHED", c0["status"])
        self.assertIs(c0["admitted"], True)
        self.assertIs((c0.get("launch_receipt") or {}).get("opened"), True)
        self.assertIn(c0["lane"], uaos_fullstack_os.FIVE_LANES)
        self.assertEqual({"ollama_pct": 50.0, "helper_pct": 30.0, "paid_core_pct": 20.0}, c0["resource_plan"]["target_parallel_ratio"])

    def test_crash_recovery_and_quota_auto_thaw(self) -> None:
        now = 1_800_000_000.0
        presence.mark(self.project, "codex", "ACTIVE", ttl_s=600, now=now)
        presence.mark(self.project, "antigravity", "ACTIVE", ttl_s=600, now=now)
        presence.mark(self.project, "claude", "ACTIVE", ttl_s=600, now=now)
        uaos_fullstack_os.save_os_state(
            self.project,
            {
                "schema": "uaos-fullstack-os-v2",
                "seq": 2,
                "updated_at": now - 2000,
                "cards": {
                    "OS-0001-crashed": {
                        "card_id": "OS-0001-crashed",
                        "status": "EXECUTING",
                        "owner": "antigravity",
                        "judge": "codex",
                        "allow_files": ["v7_harness/coord/idea_fullstack.py"],
                        "completed_stages": ["STAGE_SPEC"],
                        "step_lease_expires_at": now - 10.0,
                    },
                    "OS-0002-paused": {
                        "card_id": "OS-0002-paused",
                        "status": "PAUSED_QUOTA",
                        "owner": "claude",
                        "judge": "codex",
                        "allow_files": ["v7_harness/coord/mailbox.py"],
                        "pause_until": now - 5.0,
                    },
                },
            },
        )
        res1 = uaos_fullstack_os.tick_fullstack_os(self.project, now=now)
        self.assertIn("OS-0001-crashed", res1["recovered_cards"])
        self.assertIn("OS-0002-paused", res1["thawed_cards"])
        self.assertEqual([], res1["dispatched"])
        state1 = uaos_fullstack_os.load_os_state(self.project)
        self.assertEqual(["STAGE_SPEC"], state1["cards"]["OS-0001-crashed"]["completed_stages"])
        for cid in ("OS-0001-crashed", "OS-0002-paused"):
            self.assertEqual("SCHEDULED", state1["cards"][cid]["status"])
            self.assertIs(state1["cards"][cid]["admitted"], False)
            self.assertIsNone(state1["cards"][cid].get("launch_receipt"))
            self.assertIsNone(state1["cards"][cid].get("step_lease_expires_at"))

        res2 = uaos_fullstack_os.tick_fullstack_os(
            self.project,
            admitted={"antigravity": True, "claude": True, "codex": True},
            launcher=lambda c: {"opened": True, "window_id": f"w-{c['card_id']}"},
            now=now + 1.0,
        )
        self.assertEqual({"OS-0001-crashed", "OS-0002-paused"}, set(res2["dispatched"]))
        state2 = uaos_fullstack_os.load_os_state(self.project)
        for cid in ("OS-0001-crashed", "OS-0002-paused"):
            self.assertEqual("DISPATCHED", state2["cards"][cid]["status"])
            self.assertIs(state2["cards"][cid]["admitted"], True)
            self.assertIs((state2["cards"][cid].get("launch_receipt") or {}).get("opened"), True)

    def test_two_strike_reroute_quarantine_tikitaka_tiebreaker_and_merge_priority(self) -> None:
        card = {"card_id": "OS-0009", "owner": "antigravity", "judge": "codex", "status": "EXECUTING"}
        s1 = uaos_fullstack_os.record_step_failure(card, cause="PROVIDER_ERROR", active_tools=("antigravity", "codex"))
        self.assertEqual("RETRY_WITH_FEEDBACK", s1["action"])
        s2 = uaos_fullstack_os.record_step_failure(card, cause="PROVIDER_ERROR", active_tools=("antigravity", "codex"))
        self.assertEqual("TWO_STRIKE_REROUTED", s2["action"])
        self.assertEqual("codex", card["owner"])
        self.assertNotEqual(card["owner"], card["judge"])
        s3 = uaos_fullstack_os.record_step_failure(card, cause="PROVIDER_ERROR", active_tools=("antigravity", "codex"))
        self.assertEqual("THREE_STRIKE_QUARANTINED", s3["action"])
        self.assertEqual("QUARANTINED_FAILURE", card["status"])

        tcard = {"card_id": "OS-0010", "owner": "antigravity", "judge": "claude", "status": "JUDGING"}
        with self.assertRaises(ValueError):
            uaos_fullstack_os.record_tikitaka_turn(tcard, actor="antigravity", evidence_ref="r1", verdict="PASS")
        for i in range(4):
            r = uaos_fullstack_os.record_tikitaka_turn(tcard, actor="claude", evidence_ref=f"e{i}", verdict="REVISE")
            self.assertFalse(r["escalated_to_tiebreaker"])
        r5 = uaos_fullstack_os.record_tikitaka_turn(tcard, actor="claude", evidence_ref="e5", verdict="REVISE")
        self.assertTrue(r5["escalated_to_tiebreaker"])
        self.assertEqual("codex", r5["tiebreaker"])

        self.assertEqual(
            "antigravity",
            uaos_fullstack_os.select_autonomous_merger(author="codex", judge="antigravity", active_tools=("codex", "antigravity")),
        )
        self.assertEqual(
            "codex",
            uaos_fullstack_os.select_autonomous_merger(author="claude", judge="codex", active_tools=("codex", "claude")),
        )

    def test_rsi_safety_guards_and_closed_loop_synthesis(self) -> None:
        bad_eval = uaos_fullstack_os.validate_rsi_candidate_safety(["v7_harness/calculator_gate.py"])
        self.assertFalse(bad_eval["ok"])
        self.assertTrue(any("EVALUATOR_MUTATION_FORBIDDEN" in e for e in bad_eval["errors"]))

        bad_cost = uaos_fullstack_os.validate_rsi_candidate_safety(
            ["v7_harness/coord/idea_fullstack.py"], baseline_tokens=1000, candidate_tokens=3100, paired_samples=12
        )
        self.assertFalse(bad_cost["ok"])
        self.assertIn("COST_REGRESSION_3X", bad_cost["errors"])

        unmeasured = uaos_fullstack_os.validate_rsi_candidate_safety(
            ["v7_harness/coord/idea_fullstack.py"], baseline_tokens=1000, candidate_tokens=600, paired_samples=4
        )
        self.assertTrue(unmeasured["ok"])
        self.assertEqual("UNMEASURED", unmeasured["savings_claim"])
        self.assertFalse(unmeasured["auto_adopt"])

        rows = [
            {"work_id": f"W{i}", "worker": "ollama", "outcome": "BLOCKED", "error_class": "PROVIDER_ERROR", "ts": 1000 + i}
            for i in range(6)
        ]
        (self.project / ".coord" / "usage" / "runs.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
        )
        (self.project / ".coord" / "mailbox" / "inbox" / "rsi_review_ollama_10x99.json").write_text(
            json.dumps({"payload": {"worker": "ollama", "recurring": ["PROVIDER_ERROR"], "window": 10}}),
            encoding="utf-8",
        )
        pkt = uaos_fullstack_os.synthesize_rsi_loop(self.project, now=2000.0, dry_run=False)
        self.assertFalse(pkt["auto_adopt"])
        self.assertGreaterEqual(pkt["candidate_count"], 1)
        self.assertTrue((self.project / ".coord" / "fullstack_os" / "rsi_candidates.json").is_file())

    def test_parallel_tick_fullstack_os_atomicity(self) -> None:
        now = 1_800_000_000.0
        presence.mark(self.project, "codex", "ACTIVE", ttl_s=600, now=now)
        presence.mark(self.project, "antigravity", "ACTIVE", ttl_s=600, now=now)
        ideas = [
            "올라마 VRAM 방어 구현",
            "사서함 아카이브 자동 압축",
            "권한 출석 복구 모듈",
            "스케줄 동기화 점검",
        ]
        with ThreadPoolExecutor(max_workers=4) as pool:
            futs = [
                pool.submit(uaos_fullstack_os.tick_fullstack_os, self.project, raw_ideas=[idea], now=now + idx)
                for idx, idea in enumerate(ideas)
            ]
            results = [f.result() for f in futs]

        self.assertTrue(all(r["ok"] for r in results))
        state = uaos_fullstack_os.load_os_state(self.project)
        self.assertEqual(4, len(state["cards"]))
        journal_lines = (self.project / ".coord" / "fullstack_os" / "journal.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(4, len(journal_lines))

    def test_malformed_unified_desks_list_and_corrupt_json_fail_closed_without_crash(self) -> None:
        now = 1_800_000_000.0
        (self.project / ".coord" / "presence" / "unified_desks.json").write_text(
            json.dumps({"desks": []}),
            encoding="utf-8",
        )
        states = presence.read_all(self.project, now=now)
        for tool in presence.TOOLS:
            self.assertEqual("UNKNOWN", states[tool]["state"])
        health = idea_fullstack.diagnose_fullstack_health(self.project, now=now)
        self.assertIn("blockers", health)

        # Corrupt heartbeat on disk MUST remain fail-closed UNKNOWN even with a future pause lease.
        future_iso = datetime.datetime.fromtimestamp(now + 36000, tz=datetime.timezone.utc).isoformat()
        (self.project / ".coord" / "presence" / "unified_desks.json").write_text(
            json.dumps({"desks": {"claude": {"execution_paused_until": future_iso}}}),
            encoding="utf-8",
        )
        hb = self.project / ".coord" / "presence" / "claude.json"
        for corrupt in ("{bad json", json.dumps({"state": "ACTIVE", "expires_at": True})):
            hb.write_text(corrupt, encoding="utf-8")
            self.assertEqual("UNKNOWN", presence.read(self.project, "claude", now=now)["state"])

    def test_route_directive_production_invokes_project_grounded_concretizer_and_wires_os(self) -> None:
        import contextlib
        import io
        from v7_harness import cli as v7_cli

        states = {"codex": "ACTIVE", "antigravity": "ACTIVE", "claude": "LIMITED"}
        admitted = {"codex": True, "antigravity": True, "claude": False}
        calls = 0
        orig = idea_fullstack.concretize_raw_idea

        def spy(*args, **kwargs):
            nonlocal calls
            calls += 1
            return orig(*args, **kwargs)

        with mock.patch("v7_harness.coord.idea_fullstack.concretize_raw_idea", side_effect=spy):
            plan = desk_router.route_directive(
                self.project,
                "사서함 병목 정리 기능을 구현해줘",
                tool="antigravity",
                states=states,
                admitted=admitted,
                opener=lambda *_a, **_kw: {"opened": True},
                event_id="evt-u390-prod-route",
            )
        self.assertEqual(1, calls)
        self.assertEqual("ROUTED", plan["state"])
        self.assertIn("v7_harness/coord/mailbox.py", plan["concrete"]["grounded_files"])
        self.assertIn("v7_harness/coord/mailbox.py", plan["cards"][0]["files"])
        self.assertIn("mia_tier", plan["concrete"])
        os_state = uaos_fullstack_os.load_os_state(self.project)
        self.assertIn(plan["cards"][0]["id"], os_state["cards"])

        # Native CLI `coord route-directive` pops concrete yet exposes grounded files on routed cards.
        presence.mark(self.project, "codex", "ACTIVE", ttl_s=600)
        presence.mark(self.project, "antigravity", "ACTIVE", ttl_s=600)
        presence.mark(self.project, "claude", "LIMITED", ttl_s=600)
        buf = io.StringIO()
        with mock.patch("v7_harness.coord.participation.admissions", return_value=admitted), \
                mock.patch("v7_harness.coord.quota_sources.measured_accounts", return_value={}), \
                mock.patch("v7_harness.coord.desk_router.default_opener", return_value={"opened": True}), \
                contextlib.redirect_stdout(buf):
            rc = v7_cli.main([
                "coord", "route-directive",
                "--project", str(self.project),
                "--tool", "antigravity",
                "--text", "올라마 VRAM 가드 기능을 구현해줘",
                "--event-id", "evt-u390-cli",
            ])
        self.assertEqual(0, rc)
        cli_plan = json.loads(buf.getvalue().strip())
        self.assertEqual("ROUTED", cli_plan["state"])
        self.assertIn("v7_harness/adapters/ollama_vram_guard.py", cli_plan["cards"][0]["files"])

    def test_sentinel_production_entrypoint_runs_tick_fullstack_os_and_preserves_concurrent_wakes(self) -> None:
        now = 1_800_000_000.0
        presence.mark(self.project, "codex", "ACTIVE", ttl_s=600, now=now)
        presence.mark(self.project, "antigravity", "ACTIVE", ttl_s=600, now=now)
        box = mailbox.Mailbox(self.project / ".coord" / "mailbox")
        box.publish("b_p1", {"kind": "BLOCKED", "step": "U390-CONC", "ts": "2026-11-24T10:00:00+09:00"})

        with ThreadPoolExecutor(max_workers=4) as pool:
            futs = [
                pool.submit(sentinel.run_sentinel_cycle, self.project, box, recipient=target)
                for target in ("codex", "antigravity", "codex", "antigravity")
            ]
            results = [f.result() for f in futs]

        self.assertTrue(all(r["fullstack_os"]["ok"] for r in results))
        inbox_wakes = list(box.inbox_dir.glob("wake_*.json"))
        recipients_preserved = set()
        for wf in inbox_wakes:
            payload = (json.loads(wf.read_text(encoding="utf-8")) or {}).get("payload") or {}
            recipients_preserved.add(payload.get("requested_target"))
        self.assertEqual({"codex", "antigravity"}, recipients_preserved)


class U390BrainLabor7DayPacingTest(unittest.TestCase):
    """Turn 3 proofs for AGY Pool B Labor + Codex/Claude 7-day paced Brain architecture."""

    def _make_proj(self, root: Path) -> None:
        for rel in (
            "v7_harness/coord/idea_fullstack.py",
            "v7_harness/coord/uaos_fullstack_os.py",
            "v7_harness/coord/mailbox.py",
            "v7_harness/coord/presence.py",
            "v7_harness/coord/sentinel.py",
            "v7_harness/coord/desk_router.py",
        ):
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("# stub\n", encoding="utf-8")
        (root / ".coord" / "presence").mkdir(parents=True, exist_ok=True)
        (root / ".coord" / "mailbox" / "inbox").mkdir(parents=True, exist_ok=True)
        (root / ".coord" / "usage").mkdir(parents=True, exist_ok=True)

    def test_live_nov24_asymmetry_routes_labor_to_agy_pool_b_and_conserves_codex_brain(self) -> None:
        now = 1_800_000_000.0
        codex_reset = datetime.datetime.fromtimestamp(now + 6 * 86400.0, tz=datetime.timezone.utc).isoformat()
        quota = {
            "antigravity": {
                "pool_b_gemini_5h_remaining_pct": 94.0,
                "pool_b_gemini_7d_remaining_pct": 98.0,
                "pool_a_3p_7d_remaining_pct": 0.0,
            },
            "codex": {
                "5h_remaining_pct": 39.0,
                "7d_remaining_pct": 28.0,
                "7d_resets_at": codex_reset,
            },
            "claude": {
                "5h_remaining_pct": 74.0,
                "7d_remaining_pct": 1.0,
                "paused": True,
            },
        }
        states = {"codex": "ACTIVE", "antigravity": "ACTIVE", "claude": "LIMITED"}
        sched = idea_fullstack.plan_brain_labor_7d_schedule(
            tool_states=states, quota_snapshot=quota, is_keypoint=False, now=now
        )
        self.assertEqual("uaos-brain-labor-7d-v1", idea_fullstack.BRAIN_LABOR_7D_POLICY["schema"])
        self.assertTrue(sched["pool_a_blocked"])
        self.assertEqual("antigravity", sched["labor_owner"])
        self.assertEqual("pool_b_gemini", sched["labor_pool"])
        self.assertEqual("KEYPOINT_VERDICT_ONLY", sched["pacing"]["codex"]["tier"])
        self.assertEqual(8192, sched["brain_packet_max_bytes"])
        self.assertEqual("antigravity", sched["merge_owner"])
        self.assertEqual("SINGLE_BRAIN_CONSERVATION_AGY_LABOR", sched["continuity_mode"])
        self.assertEqual("UNMEASURED", sched["paid_savings_status"])

        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            self._make_proj(proj)
            spec = idea_fullstack.concretize_raw_idea(proj, "사서함 병목 정리해줘")
            dag = idea_fullstack.build_gear_dag(spec, tool_states=states, quota_snapshot=quota, now=now)
            impl_units = [u for u in dag["units"] if u["stage"] == "IMPLEMENTATION_SLICE"]
            self.assertTrue(impl_units)
            for unit in impl_units:
                self.assertEqual("antigravity", unit["owner"])
                self.assertEqual("codex", unit["judge"])
                self.assertEqual("pool_b_gemini", unit["labor_pool"])
                self.assertEqual(8192, unit["brain_packet_max_bytes"])

    def test_post_nov28_claude_thaw_shifts_non_keypoint_judge_to_claude_while_codex_keeps_keypoints(self) -> None:
        now = 1_800_000_000.0
        claude_reset = datetime.datetime.fromtimestamp(now + 7 * 86400.0, tz=datetime.timezone.utc).isoformat()
        codex_reset = datetime.datetime.fromtimestamp(now + 3 * 86400.0, tz=datetime.timezone.utc).isoformat()
        states = {"codex": "ACTIVE", "antigravity": "ACTIVE", "claude": "ACTIVE"}
        quota = {
            "antigravity": {
                "pool_b_gemini_5h_remaining_pct": 95.0,
                "pool_b_gemini_7d_remaining_pct": 96.0,
                "pool_a_3p_7d_remaining_pct": 100.0,
            },
            "claude": {"5h_remaining_pct": 100.0, "7d_remaining_pct": 100.0, "7d_resets_at": claude_reset},
            "codex": {"5h_remaining_pct": 18.0, "7d_remaining_pct": 18.0, "7d_resets_at": codex_reset},
        }
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            self._make_proj(proj)

            non_kp_spec = idea_fullstack.concretize_raw_idea(proj, "사서함 병목 정리")
            non_kp_dag = idea_fullstack.build_gear_dag(non_kp_spec, tool_states=states, quota_snapshot=quota, now=now)
            self.assertFalse(non_kp_dag["is_keypoint"])
            self.assertEqual("DUAL_BRAIN_AGY_LABOR", non_kp_dag["brain_labor_schedule"]["continuity_mode"])
            for unit in [u for u in non_kp_dag["units"] if u["stage"] == "IMPLEMENTATION_SLICE"]:
                self.assertEqual("antigravity", unit["owner"])
                self.assertEqual("claude", unit["judge"])

            kp_spec = idea_fullstack.concretize_raw_idea(proj, "전역규칙 보안 권한 개선")
            kp_dag = idea_fullstack.build_gear_dag(kp_spec, tool_states=states, quota_snapshot=quota, now=now)
            self.assertTrue(kp_dag["is_keypoint"])
            for unit in [u for u in kp_dag["units"] if u["stage"] == "IMPLEMENTATION_SLICE"]:
                self.assertEqual("antigravity", unit["owner"])
                self.assertEqual("codex", unit["judge"])

    def test_dual_brain_paused_activates_acting_labor_with_deferred_review_and_no_self_judge(self) -> None:
        now = 1_800_000_000.0
        states = {"codex": "LIMITED", "claude": "LIMITED", "antigravity": "ACTIVE"}
        quota = {
            "codex": {"7d_remaining_pct": 1.0},
            "claude": {"7d_remaining_pct": 1.0},
            "antigravity": {"pool_b_gemini_5h_remaining_pct": 90.0, "pool_b_gemini_7d_remaining_pct": 95.0},
        }
        sched = idea_fullstack.plan_brain_labor_7d_schedule(tool_states=states, quota_snapshot=quota, now=now)
        self.assertTrue(sched["acting_brain_mode"])
        self.assertTrue(sched["deferred_until_brain_return"])
        self.assertTrue(sched["requires_brain_return_review"])
        self.assertEqual("ACTING_LABOR_DEFERRED_REVIEW", sched["continuity_mode"])

        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            self._make_proj(proj)
            spec = idea_fullstack.concretize_raw_idea(proj, "사서함 병목 정리")
            dag = idea_fullstack.build_gear_dag(spec, tool_states=states, quota_snapshot=quota, now=now)
            for unit in dag["units"]:
                self.assertNotEqual(unit["owner"], unit["judge"])
            impl_units = [u for u in dag["units"] if u["stage"] == "IMPLEMENTATION_SLICE"]
            self.assertTrue(all(u["deferred_until_brain_return"] for u in impl_units))

    def test_compact_brain_packet_enforces_author_ne_judge_pregate_and_byte_cap(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            idea_fullstack.build_compact_brain_packet(
                card_id="U390",
                author="antigravity",
                judge="ANTIGRAVITY",
                patch_sha256="abc123",
                changed_files=["v7_harness/coord/idea_fullstack.py"],
                test_command="pytest -q",
                test_exit_code=0,
                test_summary="29 passed",
            )
        self.assertIn("SELF_JUDGE_FORBIDDEN", str(ctx.exception))

        failed = idea_fullstack.build_compact_brain_packet(
            card_id="U390",
            author="antigravity",
            judge="codex",
            patch_sha256="abc123",
            changed_files=["v7_harness/coord/idea_fullstack.py"],
            test_command="pytest -q",
            test_exit_code=1,
            test_summary="1 failed",
        )
        self.assertFalse(failed["ready_for_brain_review"])
        self.assertFalse(failed["pre_gate_passed"])
        self.assertEqual("LOCAL_PREGATE_FAILED", failed["block_reason"])

        compacted = idea_fullstack.build_compact_brain_packet(
            card_id="U390",
            author="antigravity",
            judge="codex",
            patch_sha256="abc123",
            changed_files=["v7_harness/coord/idea_fullstack.py"],
            test_command="pytest -q",
            test_exit_code=0,
            test_summary="35 passed",
            diff_stat="d" * 25000,
            notes="한글메모" * 5000,
            max_bytes=8192,
        )
        self.assertTrue(compacted["ready_for_brain_review"])
        self.assertTrue(compacted["within_budget"])
        self.assertTrue(compacted["truncated"])
        self.assertLessEqual(compacted["packet_bytes"], 8192)

    def test_tick_fullstack_os_reads_unified_desks_quota_and_exposes_brain_labor_summary(self) -> None:
        now = 1_800_000_000.0
        codex_reset = datetime.datetime.fromtimestamp(now + 6 * 86400.0, tz=datetime.timezone.utc).isoformat()
        claude_pause = datetime.datetime.fromtimestamp(now + 4 * 86400.0, tz=datetime.timezone.utc).isoformat()
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            self._make_proj(proj)
            presence.mark(proj, "codex", "ACTIVE", ttl_s=600, now=now)
            presence.mark(proj, "antigravity", "ACTIVE", ttl_s=600, now=now)
            presence.mark(proj, "claude", "LIMITED", ttl_s=600, now=now)
            (proj / ".coord" / "presence" / "unified_desks.json").write_text(
                json.dumps(
                    {
                        "desks": {
                            "antigravity": {
                                "quota": {
                                    "pool_b_gemini_5h_remaining_pct": 94.0,
                                    "pool_b_gemini_7d_remaining_pct": 98.0,
                                    "pool_a_3p_7d_remaining_pct": 0.0,
                                }
                            },
                            "codex": {
                                "quota": {
                                    "5h_remaining_pct": 39.0,
                                    "7d_remaining_pct": 28.0,
                                    "7d_resets_at": codex_reset,
                                }
                            },
                            "claude": {
                                "quota": {"5h_remaining_pct": 74.0, "7d_remaining_pct": 1.0},
                                "execution_paused_until": claude_pause,
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            res = uaos_fullstack_os.tick_fullstack_os(
                proj, raw_ideas=["사서함 병목 자동 정리해줘"], now=now
            )
            self.assertEqual("antigravity", res["brain_labor_summary"]["labor_owner"])
            self.assertTrue(res["brain_labor_summary"]["pool_a_blocked"])
            self.assertEqual("antigravity", res["ingested"][0]["owner"])
            self.assertEqual("codex", res["ingested"][0]["judge"])
            cid = res["ingested"][0]["card_id"]
            state = uaos_fullstack_os.load_os_state(proj)
            self.assertEqual("pool_b_gemini", state["cards"][cid]["brain_labor_plan"]["labor_pool"])

    def test_no_pct_to_token_conversion_and_balanced_mode_backcompat(self) -> None:
        pacing = idea_fullstack.evaluate_tool_pacing(
            "codex", state="ACTIVE", quota={"5h_remaining_pct": 50.0, "7d_remaining_pct": 50.0}
        )
        self.assertFalse(any("tok" in k.lower() for k in pacing))
        self.assertEqual("UNMEASURED", idea_fullstack.BRAIN_LABOR_7D_POLICY["invariants"]["paid_savings_status"])

        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            self._make_proj(proj)
            spec = idea_fullstack.concretize_raw_idea(proj, "출석 사서함 풀스택 자동화")
            dag = idea_fullstack.build_gear_dag(
                spec,
                tool_states={"codex": "ACTIVE", "antigravity": "ACTIVE", "claude": "ACTIVE"},
                max_slice_files=1,
                routing_mode="balanced",
            )
            owners = [u["owner"] for u in dag["units"] if u["stage"] == "IMPLEMENTATION_SLICE"]
            self.assertGreaterEqual(len(set(owners)), 2)


class U390DynamicModelRecencyAndOllamaCellTest(unittest.TestCase):
    """Turn 4 proofs: Cost-of-Pass model recency, zero-paid sync, cellular Ollama, dynamic positions."""

    def _make_proj(self, root: Path) -> None:
        for rel in (
            "v7_harness/coord/idea_fullstack.py",
            "v7_harness/coord/uaos_fullstack_os.py",
            "v7_harness/adapters/ollama_vram_guard.py",
            "v7_harness/coord/mailbox.py",
            "v7_harness/coord/presence.py",
        ):
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("# stub\n", encoding="utf-8")
        (root / ".coord" / "presence").mkdir(parents=True, exist_ok=True)
        (root / ".coord" / "mailbox" / "inbox").mkdir(parents=True, exist_ok=True)
        (root / ".coord" / "usage").mkdir(parents=True, exist_ok=True)

    def test_perf_per_token_rejects_deprecated_38_flash_and_prefers_neon_orchestrator_on_complex_code(self) -> None:
        sel = idea_fullstack.select_model_by_perf_per_token(
            "antigravity", complexity="complex_multi_file", reference_date="2026-11-24"
        )
        self.assertEqual("gemini-4-orchestrator-neon", sel["model_id"])
        self.assertNotIn("gemini-3.8-flash", str(sel["model_id"]))
        self.assertFalse(sel["live_paid_benchmarking_used"])

        csel = idea_fullstack.select_model_by_perf_per_token(
            "claude", complexity="complex_multi_file", reference_date="2026-11-24"
        )
        self.assertEqual("claude-opus-5-5", csel["model_id"])

        cat_nov = idea_fullstack.load_synced_benchmark_catalog(reference_date="2026-11-24")
        cat_dec = idea_fullstack.load_synced_benchmark_catalog(reference_date="2026-12-01")
        carbon_nov = next(m for m in cat_nov["models"] if m["model_id"] == "gemini-4-carbon")
        carbon_dec = next(m for m in cat_dec["models"] if m["model_id"] == "gemini-4-carbon")
        self.assertTrue(carbon_nov["promo_active"])
        self.assertEqual((2.0, 10.0), (carbon_nov["input_usd_per_1m"], carbon_nov["output_usd_per_1m"]))
        self.assertFalse(carbon_dec["promo_active"])
        self.assertEqual((4.0, 20.0), (carbon_dec["input_usd_per_1m"], carbon_dec["output_usd_per_1m"]))

    def test_codex_62_lineup_selected_and_ultra_effort_forbidden(self) -> None:
        std = idea_fullstack.select_model_by_perf_per_token("codex", complexity="standard_code")
        self.assertEqual("gpt-6.2-sol", std["model_id"])
        kp = idea_fullstack.select_model_by_perf_per_token(
            "codex", complexity="ultra_architecture", is_keypoint=True, high_quota_pressure=False
        )
        self.assertEqual("gpt-6.2-astra", kp["model_id"])
        self.assertIn("ultra", kp["forbidden_efforts"])
        self.assertNotEqual("ultra", kp["effort"])

        legacy_cat = idea_fullstack.load_synced_benchmark_catalog(
            codex_cache_models=["gpt-6.1-sol", "gpt-6-luna"]
        )
        fb = idea_fullstack.select_model_by_perf_per_token(
            "codex", complexity="standard_code", catalog=legacy_cat
        )
        self.assertEqual("gpt-6.1-sol", fb["model_id"])

    def test_zero_paid_benchmark_sync_merges_external_json_without_paid_calls(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            (proj / ".coord").mkdir(parents=True)
            (proj / ".coord" / "model_benchmarks_latest.json").write_text(
                json.dumps(
                    {
                        "as_of": "2026-12-10",
                        "models": [
                            {
                                "tool": "antigravity",
                                "model_id": "gemini-4.5-krypton",
                                "display": "Gemini 4.5 Krypton",
                                "tier": "one_shot_core",
                                "aa_index": 68.0,
                                "input_usd_per_1m": 1.8,
                                "output_usd_per_1m": 9.0,
                                "thinking_levels": ["Medium", "High", "XHigh"],
                                "est_pass_prob_by_complexity": {"complex_multi_file": 0.95},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            cat = idea_fullstack.load_synced_benchmark_catalog(proj, reference_date="2026-12-10")
            self.assertFalse(cat["live_paid_benchmarking_allowed"])
            sel = idea_fullstack.select_model_by_perf_per_token(
                "antigravity", complexity="complex_multi_file", catalog=cat
            )
            self.assertEqual("gemini-4.5-krypton", sel["model_id"])

    def test_ollama_cellular_options_cure_qwen35_thinking_trap_and_7b_cpu_spill(self) -> None:
        q35 = ollama_vram_guard.build_cellular_ollama_options("qwen3.5:4b", prompt_tokens=1500, vram_gb=6.0)
        self.assertIs(q35["think"], False)
        self.assertEqual(0.0, q35["options"]["temperature"])
        self.assertEqual(0.0, q35["options"]["presence_penalty"])
        self.assertEqual(8192, q35["options"]["num_ctx"])
        self.assertTrue(q35["estimated_100pct_gpu"])

        q35_32k = ollama_vram_guard.build_cellular_ollama_options("qwen3.5-32k:latest", prompt_tokens=1500, vram_gb=6.0)
        self.assertEqual(8192, q35_32k["options"]["num_ctx"])

        q7b = ollama_vram_guard.build_cellular_ollama_options("qwen2.5-coder:7b", prompt_tokens=1500, vram_gb=6.0)
        self.assertEqual(4096, q7b["options"]["num_ctx"])
        self.assertTrue(q7b["estimated_100pct_gpu"])

    def test_foreign_ip_ollama_tag_quarantined_in_guard_audit_and_allocation(self) -> None:
        bad = "161.97.181.198:9882/trigger/cfg:p"
        self.assertFalse(ollama_vram_guard.is_safe_ollama_model_tag(bad))
        self.assertTrue(ollama_vram_guard.is_safe_ollama_model_tag("qwen2.5-coder:7b"))
        with self.assertRaises(ValueError):
            ollama_vram_guard.build_cellular_ollama_options(bad)

        audit = ollama_vram_guard.audit_ollama_cellular_harness(
            (bad, "qwen2.5-coder:3b", "qwen2.5-coder:7b"), env={}, vram_gb=6.0
        )
        self.assertEqual([bad], audit["quarantined_foreign_tags"])
        self.assertIn("OLLAMA_KV_CACHE_TYPE", audit["missing_or_suboptimal_env"])

        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            self._make_proj(proj)
            spec = idea_fullstack.concretize_raw_idea(proj, "사서함 정리")
            dag = idea_fullstack.build_gear_dag(spec, tool_states={"codex": "ACTIVE", "antigravity": "ACTIVE"})
            alloc = idea_fullstack.plan_ollama_helper_allocation(
                dag,
                installed_models=(bad, "qwen2.5-coder:3b", "qwen2.5-coder:7b"),
                tool_states={"codex": "ACTIVE", "antigravity": "ACTIVE"},
            )
            self.assertEqual([bad], alloc["quarantined_ollama_tags"])
            self.assertNotIn(bad, alloc["ollama_tiers"].values())

    def test_dynamic_position_inverts_when_agy_quota_drops_and_claude_codex_are_fresh(self) -> None:
        now = 1_800_000_000.0
        reset_iso = datetime.datetime.fromtimestamp(now + 6 * 86400.0, tz=datetime.timezone.utc).isoformat()
        states = {"antigravity": "ACTIVE", "codex": "ACTIVE", "claude": "ACTIVE"}
        quota = {
            "antigravity": {
                "pool_b_gemini_5h_remaining_pct": 15.0,
                "pool_b_gemini_7d_remaining_pct": 10.0,
                "pool_a_3p_7d_remaining_pct": 0.0,
            },
            "claude": {"5h_remaining_pct": 95.0, "7d_remaining_pct": 96.0, "7d_resets_at": reset_iso},
            "codex": {"5h_remaining_pct": 92.0, "7d_remaining_pct": 90.0, "7d_resets_at": reset_iso},
        }
        sched = idea_fullstack.plan_dynamic_3tool_positions(
            tool_states=states, quota_snapshot=quota, is_keypoint=False, now=now
        )
        self.assertTrue(sched["position_shifted"])
        self.assertEqual("DYNAMIC_POSITION_INVERTED", sched["continuity_mode"])
        self.assertEqual("claude", sched["labor_owner"])
        self.assertEqual("codex", sched["judge_brain"])
        self.assertNotEqual(sched["labor_owner"], sched["judge_brain"])

    def test_tick_fullstack_os_includes_cellular_audit_and_selected_models(self) -> None:
        now = 1_800_000_000.0
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            self._make_proj(proj)
            presence.mark(proj, "codex", "ACTIVE", ttl_s=600, now=now)
            presence.mark(proj, "antigravity", "ACTIVE", ttl_s=600, now=now)
            presence.mark(proj, "claude", "LIMITED", ttl_s=600, now=now)
            res = uaos_fullstack_os.tick_fullstack_os(
                proj,
                raw_ideas=["사서함 병목 정리해줘"],
                installed_models=("161.97.181.198:9882/trigger/cfg:p", "qwen3.5:4b", "qwen2.5-coder:7b"),
                now=now,
            )
            self.assertEqual(
                ["161.97.181.198:9882/trigger/cfg:p"],
                res["ollama_cellular_audit"]["quarantined_foreign_tags"],
            )
            self.assertEqual(
                "gemini-4-orchestrator-neon",
                res["brain_labor_summary"]["selected_models"]["labor_owner"]["model_id"],
            )

    def test_revise_r2_blocked_pool_unbound_plan_not_thawed_or_dispatched_on_codex_heartbeat(self) -> None:
        now = 1_800_000_000.0
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            self._make_proj(proj)
            # Codex has an ACTIVE heartbeat only (no quota admission, no worker launch).
            presence.mark(proj, "codex", "ACTIVE", ttl_s=600, now=now)

            # Existing route plan blocked with POOL_UNBOUND both in directives/ and synced OS state.
            directives = proj / ".coord" / "directives"
            directives.mkdir(parents=True, exist_ok=True)
            blocked_plan = {
                "d_id": "D-u390-pool-unbound",
                "state": "ROUTED",
                "lane": "IMPL_CODE",
                "cards": [
                    {
                        "id": "Du390pool-C1",
                        "title": "Pool unbound directive",
                        "status": "BLOCKED",
                        "tool": None,
                        "files": ["v7_harness/coord/mailbox.py"],
                        "lane": "IMPL_CODE",
                        "d_id": "D-u390-pool-unbound",
                        "assignment": {"tool": None, "paid": False, "blocked": "POOL_UNBOUND"},
                        "window": {"opened": False, "reason": "POOL_UNBOUND"},
                    }
                ],
            }
            (directives / "D-u390-pool-unbound.json").write_text(
                json.dumps({"d_id": "D-u390-pool-unbound", "state": "ROUTED", "plan": blocked_plan}),
                encoding="utf-8",
            )
            (directives / "cards.json").write_text(
                json.dumps({"cards": {"Du390pool-C1": {"id": "Du390pool-C1", "status": "BLOCKED", "tool": None}}}),
                encoding="utf-8",
            )
            uaos_fullstack_os.sync_routed_plan(proj, blocked_plan, now=now)

            # Even an explicit READY directive card without measured admission + launcher stays un-dispatched.
            res = uaos_fullstack_os.tick_fullstack_os(proj, now=now)
            self.assertEqual([], res["thawed_cards"])
            self.assertEqual([], res["dispatched"])
            state = uaos_fullstack_os.load_os_state(proj)
            card = state["cards"]["Du390pool-C1"]
            self.assertEqual("BLOCKED", card["status"])
            self.assertEqual("POOL_UNBOUND", card["blocked_reason"])
            self.assertIs(card["admitted"], False)
            self.assertIsNone(card.get("launch_receipt"))

            # Production sentinel observer tick also never thaws or dispatches blocked plan.
            box = mailbox.Mailbox(proj / ".coord" / "mailbox")
            sres = sentinel.run_sentinel_cycle(proj, box, recipient="codex")
            self.assertEqual([], sres["fullstack_os"]["dispatched"])
            self.assertEqual([], sres["fullstack_os"]["thawed_cards"])

    def test_revise_r2_aged_wake_and_os_locks_never_stolen_from_live_parent_process(self) -> None:
        import os
        import subprocess
        import sys
        import time as time_mod

        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            (proj / ".coord" / "mailbox").mkdir(parents=True, exist_ok=True)
            (proj / ".coord" / "fullstack_os").mkdir(parents=True, exist_ok=True)
            wake_lock = proj / ".coord" / "mailbox" / ".sentinel_wake.lock"
            os_lock = proj / ".coord" / "fullstack_os" / ".fullstack_os.lock"

            child_code = (
                "import pathlib, sys; "
                "sys.path.insert(0, sys.argv[1]); "
                "from v7_harness.coord import sentinel, uaos_fullstack_os; "
                "mode = sys.argv[2]; target = pathlib.Path(sys.argv[3]); "
                "ctx = sentinel._sentinel_wake_lock(target, timeout_s=0.25) if mode == 'wake' "
                "else uaos_fullstack_os._os_lock(target, timeout_s=0.25); "
                "\nwith ctx:\n pass\n"
            )

            with sentinel._sentinel_wake_lock(wake_lock, timeout_s=2.0):
                old = time_mod.time() - 35.0
                os.utime(wake_lock, (old, old))
                with open(os.devnull, "rb") as dn:
                    c1 = subprocess.run(
                        [sys.executable, "-c", child_code, str(REPO_ROOT), "wake", str(wake_lock)],
                        cwd=str(REPO_ROOT), stdin=dn, capture_output=True, text=True, timeout=15,
                    )
                self.assertNotEqual(0, c1.returncode)
                self.assertIn("TimeoutError", c1.stderr)

            with open(os.devnull, "rb") as dn:
                c2 = subprocess.run(
                    [sys.executable, "-c", child_code, str(REPO_ROOT), "wake", str(wake_lock)],
                    cwd=str(REPO_ROOT), stdin=dn, capture_output=True, text=True, timeout=15,
                )
            self.assertEqual(0, c2.returncode, c2.stderr)

            with uaos_fullstack_os._os_lock(proj, timeout_s=2.0):
                old = time_mod.time() - 35.0
                os.utime(os_lock, (old, old))
                with open(os.devnull, "rb") as dn:
                    c3 = subprocess.run(
                        [sys.executable, "-c", child_code, str(REPO_ROOT), "os", str(proj)],
                        cwd=str(REPO_ROOT), stdin=dn, capture_output=True, text=True, timeout=15,
                    )
                self.assertNotEqual(0, c3.returncode)
                self.assertIn("TimeoutError", c3.stderr)

    def test_revise_r4_malformed_directive_assignment_fails_closed_and_observer_continues_valid_records(self) -> None:
        now = 1_800_000_000.0
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            self._make_proj(proj)
            presence.mark(proj, "codex", "ACTIVE", ttl_s=600, now=now)
            presence.mark(proj, "antigravity", "ACTIVE", ttl_s=600, now=now)
            directives = proj / ".coord" / "directives"
            directives.mkdir(parents=True, exist_ok=True)
            (directives / "D-probe.json").write_text(
                json.dumps(
                    {
                        "plan": {
                            "cards": [
                                {"id": "U1", "assignment": ["codex"]},
                                "bad-item",
                                {"id": "U1b", "tool": "codex", "window": ["bad"]},
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            (directives / "D-valid.json").write_text(
                json.dumps(
                    {
                        "plan": {
                            "cards": [
                                {
                                    "id": "U2",
                                    "status": "READY",
                                    "tool": "antigravity",
                                    "assignment": {"tool": "antigravity", "paid": True},
                                    "files": ["v7_harness/coord/mailbox.py"],
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            obs = uaos_fullstack_os.tick_fullstack_os(proj, observer_only=True, dry_run=True, now=now)
            self.assertTrue(obs["ok"])
            self.assertEqual([], obs["dispatched"])
            self.assertFalse((proj / ".coord" / "fullstack_os" / "state.json").exists())

            box = mailbox.Mailbox(proj / ".coord" / "mailbox")
            sres = sentinel.run_sentinel_cycle(proj, box, recipient="codex")
            self.assertTrue(sres["fullstack_os"]["ok"])
            self.assertEqual([], sres["fullstack_os"]["dispatched"])

            state = uaos_fullstack_os.load_os_state(proj)
            u1 = state["cards"]["U1"]
            self.assertEqual("BLOCKED", u1["status"])
            self.assertEqual("MALFORMED_ASSIGNMENT", u1["blocked_reason"])
            self.assertIs(u1["admitted"], False)
            self.assertIsNone(u1.get("launch_receipt"))
            self.assertEqual("BLOCKED", state["cards"]["D-probe-MALFORMED-1"]["status"])
            self.assertEqual("MALFORMED_WINDOW", state["cards"]["U1b"]["blocked_reason"])

            u2 = state["cards"]["U2"]
            self.assertEqual("SCHEDULED", u2["status"])
            self.assertIs(u2["admitted"], False)
            self.assertIsNone(u2.get("launch_receipt"))

            live = uaos_fullstack_os.tick_fullstack_os(
                proj,
                admitted={"antigravity": True},
                launcher=lambda c: {"opened": True, "window_id": f"w-{c['card_id']}"},
                now=now + 1.0,
            )
            self.assertEqual(["U2"], live["dispatched"])
            reloaded = uaos_fullstack_os.load_os_state(proj)
            self.assertEqual("BLOCKED", reloaded["cards"]["U1"]["status"])
            self.assertEqual("DISPATCHED", reloaded["cards"]["U2"]["status"])
            self.assertIs(reloaded["cards"]["U2"]["admitted"], True)
            self.assertIs((reloaded["cards"]["U2"].get("launch_receipt") or {}).get("opened"), True)

    def test_revise_r4_raw_idea_and_routed_cards_require_positive_admission_and_launcher_receipt(self) -> None:
        now = 1_800_000_000.0
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            self._make_proj(proj)
            presence.mark(proj, "codex", "ACTIVE", ttl_s=600, now=now)
            presence.mark(proj, "antigravity", "ACTIVE", ttl_s=600, now=now)

            # Exact Codex repro: raw_ideas without admitted or launcher must NEVER dispatch or allocate lease.
            r0 = uaos_fullstack_os.tick_fullstack_os(
                proj, raw_ideas=["Improve user chat title metadata display"], now=now
            )
            self.assertEqual([], r0["dispatched"])
            cid = r0["ingested"][0]["card_id"]
            owner = r0["ingested"][0]["owner"]

            def _assert_not_dispatched() -> None:
                st = uaos_fullstack_os.load_os_state(proj)
                c = st["cards"][cid]
                self.assertEqual("SCHEDULED", c["status"])
                self.assertIs(c["admitted"], False)
                self.assertIsNone(c.get("launch_receipt"))
                self.assertIsNone(c.get("step_lease_expires_at"))

            _assert_not_dispatched()

            # Admitted without launcher -> stays SCHEDULED.
            r1 = uaos_fullstack_os.tick_fullstack_os(proj, admitted={owner: True}, now=now + 1.0)
            self.assertEqual([], r1["dispatched"])
            _assert_not_dispatched()

            # Launcher without admitted -> stays SCHEDULED.
            r2 = uaos_fullstack_os.tick_fullstack_os(
                proj, launcher=lambda c: {"opened": True, "window_id": "w-none"}, now=now + 2.0
            )
            self.assertEqual([], r2["dispatched"])
            _assert_not_dispatched()

            # Admitted[owner] is False -> stays SCHEDULED.
            r3 = uaos_fullstack_os.tick_fullstack_os(
                proj,
                admitted={owner: False},
                launcher=lambda c: {"opened": True, "window_id": "w-false"},
                now=now + 3.0,
            )
            self.assertEqual([], r3["dispatched"])
            _assert_not_dispatched()

            # Launcher opened=False -> stays SCHEDULED.
            r4 = uaos_fullstack_os.tick_fullstack_os(
                proj,
                admitted={owner: True},
                launcher=lambda c: {"opened": False, "reason": "WINDOW_BUSY"},
                now=now + 4.0,
            )
            self.assertEqual([], r4["dispatched"])
            _assert_not_dispatched()

            # Observer cycle with admitted+launcher never invokes launcher and never dispatches.
            launch_calls = 0

            def _spy_launcher(c: dict) -> dict:
                nonlocal launch_calls
                launch_calls += 1
                return {"opened": True, "window_id": f"w-{c['card_id']}"}

            r5 = uaos_fullstack_os.tick_fullstack_os(
                proj, observer_only=True, admitted={owner: True}, launcher=_spy_launcher, now=now + 5.0
            )
            self.assertEqual([], r5["dispatched"])
            self.assertEqual(0, launch_calls)
            _assert_not_dispatched()

            # Positive admission + successful launch receipt -> DISPATCHED with lease and receipt.
            r6 = uaos_fullstack_os.tick_fullstack_os(
                proj, admitted={owner: True}, launcher=_spy_launcher, now=now + 6.0
            )
            self.assertEqual([cid], r6["dispatched"])
            self.assertEqual(1, launch_calls)
            final_card = uaos_fullstack_os.load_os_state(proj)["cards"][cid]
            self.assertEqual("DISPATCHED", final_card["status"])
            self.assertIs(final_card["admitted"], True)
            self.assertIs((final_card.get("launch_receipt") or {}).get("opened"), True)
            self.assertIsInstance(final_card.get("step_lease_expires_at"), float)

    def test_revise_r5_dry_run_zero_launch_and_single_following_live_dispatch(self) -> None:
        now = 1_800_000_000.0
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            self._make_proj(proj)
            presence.mark(proj, "codex", "ACTIVE", ttl_s=600, now=now)
            presence.mark(proj, "antigravity", "ACTIVE", ttl_s=600, now=now)

            raw_res = uaos_fullstack_os.tick_fullstack_os(
                proj, raw_ideas=["Improve user chat title metadata display"], now=now
            )
            raw_cid = raw_res["ingested"][0]["card_id"]
            raw_owner = raw_res["ingested"][0]["owner"]

            directives = proj / ".coord" / "directives"
            directives.mkdir(parents=True, exist_ok=True)
            (directives / "D-r5-valid.json").write_text(
                json.dumps(
                    {
                        "plan": {
                            "cards": [
                                {
                                    "id": "U-r5-routed",
                                    "status": "READY",
                                    "tool": "codex",
                                    "assignment": {"tool": "codex", "paid": True},
                                    "files": ["v7_harness/coord/r5_routed_disjoint.py"],
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            uaos_fullstack_os.tick_fullstack_os(proj, observer_only=True, now=now + 1.0)

            state_path = proj / ".coord" / "fullstack_os" / "state.json"
            journal_path = proj / ".coord" / "fullstack_os" / "journal.jsonl"
            pre_state = uaos_fullstack_os.load_os_state(proj)
            self.assertFalse(set(pre_state["cards"][raw_cid]["allow_files"]) & {"v7_harness/coord/r5_routed_disjoint.py"})
            for cid in (raw_cid, "U-r5-routed"):
                c = pre_state["cards"][cid]
                self.assertEqual("SCHEDULED", c["status"])
                self.assertIs(c["admitted"], False)
                self.assertIsNone(c.get("launch_receipt"))
                self.assertIsNone(c.get("step_lease_expires_at"))

            before_state_bytes = state_path.read_bytes()
            before_journal_bytes = journal_path.read_bytes()

            launch_calls: list[str] = []

            def _instrumented_launcher(card: dict) -> dict:
                cid = str(card["card_id"])
                launch_calls.append(cid)
                return {"opened": True, "window_id": f"w-{cid}"}

            dry = uaos_fullstack_os.tick_fullstack_os(
                proj,
                dry_run=True,
                admitted={raw_owner: True, "codex": True},
                launcher=_instrumented_launcher,
                now=now + 2.0,
            )
            self.assertTrue(dry["ok"])
            self.assertTrue(dry["dry_run"])
            self.assertEqual([], dry["dispatched"])
            self.assertEqual([], launch_calls)
            self.assertEqual(before_state_bytes, state_path.read_bytes())
            self.assertEqual(before_journal_bytes, journal_path.read_bytes())
            dry_state = uaos_fullstack_os.load_os_state(proj)
            for cid in (raw_cid, "U-r5-routed"):
                self.assertEqual("SCHEDULED", dry_state["cards"][cid]["status"])
                self.assertIs(dry_state["cards"][cid]["admitted"], False)
                self.assertIsNone(dry_state["cards"][cid].get("launch_receipt"))
                self.assertIsNone(dry_state["cards"][cid].get("step_lease_expires_at"))

            live1 = uaos_fullstack_os.tick_fullstack_os(
                proj,
                dry_run=False,
                admitted={raw_owner: True, "codex": True},
                launcher=_instrumented_launcher,
                now=now + 3.0,
            )
            self.assertEqual(2, len(launch_calls))
            self.assertEqual({raw_cid, "U-r5-routed"}, set(launch_calls))
            self.assertEqual({raw_cid, "U-r5-routed"}, set(live1["dispatched"]))
            live_state = uaos_fullstack_os.load_os_state(proj)
            for cid in (raw_cid, "U-r5-routed"):
                c = live_state["cards"][cid]
                self.assertEqual("DISPATCHED", c["status"])
                self.assertIs(c["admitted"], True)
                self.assertEqual({"opened": True, "window_id": f"w-{cid}"}, c.get("launch_receipt"))
                self.assertIsInstance(c.get("step_lease_expires_at"), float)

            live2 = uaos_fullstack_os.tick_fullstack_os(
                proj,
                dry_run=False,
                admitted={raw_owner: True, "codex": True},
                launcher=_instrumented_launcher,
                now=now + 4.0,
            )
            self.assertEqual([], live2["dispatched"])
            self.assertEqual(2, len(launch_calls))


if __name__ == "__main__":
    unittest.main()
