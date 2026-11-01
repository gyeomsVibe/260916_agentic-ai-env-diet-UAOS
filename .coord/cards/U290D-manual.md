```contract
work_id: U290D
worker: local
goal: Remove the default daily count caps on Antigravity auto-replies and Codex notices per the dictated edits
inputs:
- v7_harness/coord/agy_dispatch.py sha256=6a6adaf7d965174f0b152df9eb419e5dcdde11acdbd1bd51c8b1ff9ae3773940
- v7_harness/coord/notify.py sha256=d6a8ab5ad7f2527e63a44d9972e5fd3aba68f738999b874cbdaf1c574a8a37d5
- v7_harness/coord/wait_reason.py sha256=58e7c22cd8007555d16ca3d2410ed1904ad4dc2a4ea7e4dd7cbba6fcbe0da87a
- tests/test_u290_no_daily_caps.py sha256=806b84770df9bccebd45a7a1e6f250da0d4b36001d34f06c86a8b1696b0abe1d
- tests/test_u290d_backlog_drain.py sha256=b04a6fce8a2668d8634fb62ccb7a15187ad7107bef0b722a4c1c176c42af49a9
- tests/test_u164_agy_backlog.py sha256=992d20bd0fd4c493a1c5141ffdab6775e588409691d9083746739d6af4685010
- tests/test_u15_notify_codex.py sha256=d21cb2fb8f2c1664b294a64577dd98526f16a1b71be14034b50d16279ec80986
- tests/test_u120_agy_auto_reply.py sha256=b6d538a19311b018c249021e7e42270224c3704b8c17482cb461e33292a803e6
- tests/test_u194_verdict_wakes_agy.py sha256=24214829c7fe94f510fa410ccb4c4f8da5cb12ab821d4d48bab484c86d8bc0ac
allow:
- v7_harness/coord/agy_dispatch.py
- v7_harness/coord/notify.py
- v7_harness/coord/wait_reason.py
context_allow:
- v7_harness/coord/agy_dispatch.py
- v7_harness/coord/notify.py
- v7_harness/coord/wait_reason.py
acceptance: python -m unittest tests.test_u290_no_daily_caps tests.test_u290d_backlog_drain tests.test_u15_notify_codex tests.test_u164_agy_backlog tests.test_u120_agy_auto_reply tests.test_u194_verdict_wakes_agy tests.test_u199_audit_uncapped tests.test_u200_sentinel_backlog_and_judge_review tests.test_u141a_rev6_thrift_wake tests.test_u253_zero_deadlock_watch_and_deliver tests.test_u32_sentinel_bell
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

# U290 dictation contract: no default daily count caps

Why: 윤겸스 2026-11-01 "Antigravity가 하루 자동 응답 한도를 누가 설정했나? 모든 한도를 없애라". Receipt the same day: the
U277-A11 approval request to Antigravity parked as AGY_CAP_REACHED_BACKLOG after 20 answers, and the card had to be
re-cut for another judge. The cap came from U120 (commit 6605c1f, 2026-10-01), set by Claude as a token guard.

Design (Claude): the two collaboration count caps, `agy_dispatch.DAILY_CAP` (20 answers a day) and `notify.DAILY_LIMIT`
(24 Codex notices a day), default to None, which means no cap. An int still re-enables the old path, so the cap tests
keep it working by patching 20/24. Technical and safety limits stay: reply length, rate interval, backlog tries,
budget lock, single Ollama slot on 8 GB VRAM, and the user-mandated report size. Those limits are not count quotas.

Frozen gate identity (Codex REVISE relay_7de73555): the test changes are the author's acceptance, committed before this
run in 413922b and pinned above by hash; the worker may not edit them. Kept protections, by kind: per-call token
budgets (pilot `--budget`, `remote_budget_tokens`, worker USD/time caps), rate (`notify.MIN_INTERVAL` 1 min,
`NO_CHANGE` digest), safety (secret refusal, message size, `BACKLOG_TRIES`, budget lock, `MAX_REPLY_CHARS`), hardware
(`MAX_CONCURRENT_OLLA=1`). Removed: only the two per-day count quotas, which waited a whole day regardless of spend.

## Allowed change

Only the three files below, only these six blocks.

## Output

Reply with exactly these ===EDIT blocks, unchanged.

===EDIT: v7_harness/coord/agy_dispatch.py===
<<<<<<< SEARCH
# 20 answers x ~28k tokens (U119 live) = at most ~560k Antigravity tokens a day; past it letters wait (U118 route).
DAILY_CAP = 20
=======
# U290 (윤겸스 2026-11-01 "모든 한도를 없애라"): no daily answer cap by default. The U120 cap (20 answers x ~28k tokens)
# parked approval requests until the next Seoul day. An int re-enables that path (the cap tests use 20).
DAILY_CAP: int | None = None
>>>>>>> REPLACE

===EDIT: v7_harness/coord/agy_dispatch.py===
<<<<<<< SEARCH
def _reserve(project: Path, message_id: str, now: float, audit: bool = False) -> str | None:
=======
def _cap_spent(project: Path, now: float) -> bool:
    """U290: True only when a daily cap is set and today's answers reached it."""
    return DAILY_CAP is not None and _today_count(project, now) >= DAILY_CAP


def _reserve(project: Path, message_id: str, now: float, audit: bool = False) -> str | None:
>>>>>>> REPLACE

===EDIT: v7_harness/coord/agy_dispatch.py===
<<<<<<< SEARCH
        if not audit and _today_count(project, now) >= DAILY_CAP:  # U199: 윤겸스 2026-10-15, audits are uncapped
=======
        if not audit and _cap_spent(project, now):  # U199: 윤겸스 2026-10-15, audits are uncapped
>>>>>>> REPLACE

===EDIT: v7_harness/coord/agy_dispatch.py===
<<<<<<< SEARCH
    return _today_count(project, time.time() if now is None else now) < DAILY_CAP
=======
    return not _cap_spent(project, time.time() if now is None else now)
>>>>>>> REPLACE

===EDIT: v7_harness/coord/agy_dispatch.py===
<<<<<<< SEARCH
    for path in sorted(folder.glob("*.json"), key=_parked_order):
        if _today_count(project, now) >= DAILY_CAP:
            break
=======
    for path in sorted(folder.glob("*.json"), key=_parked_order):
        if _cap_spent(project, now):
            break
>>>>>>> REPLACE

===EDIT: v7_harness/coord/notify.py===
<<<<<<< SEARCH
DAILY_LIMIT = 24
=======
# U290 (윤겸스 2026-11-01): no daily notice cap by default; an int re-enables it. NO_CHANGE and MIN_INTERVAL still stop floods.
DAILY_LIMIT: int | None = None
>>>>>>> REPLACE

===EDIT: v7_harness/coord/notify.py===
<<<<<<< SEARCH
    if sent_today >= DAILY_LIMIT:
=======
    if DAILY_LIMIT is not None and sent_today >= DAILY_LIMIT:
>>>>>>> REPLACE

===EDIT: v7_harness/coord/wait_reason.py===
<<<<<<< SEARCH
        lines.append(f"Antigravity 답장 {parked}건 대기: 오늘 자동 답장 한도({DAILY_CAP}건) 소진 → 다음 날 첫 도구 턴에 자동 처리")
=======
        if DAILY_CAP is not None:
            lines.append(f"Antigravity 답장 {parked}건 대기: 오늘 자동 답장 한도({DAILY_CAP}건) 소진 → 다음 날 첫 도구 턴에 자동 처리")
        else:  # U290: no cap; letters parked before it are answered by the next drain
            lines.append(f"Antigravity 답장 {parked}건 대기: 이전 한도로 보류된 편지 → 다음 도구 턴에 자동 처리")
>>>>>>> REPLACE

## Acceptance (judge runs; author must not edit)

- The acceptance command above exits 0. Before this change, 5 tests fail: the 4 in `tests/test_u290_no_daily_caps.py`
  and `test_no_daily_limit_by_default` (log `.work/u290_red.log`, Ran 70, failures=5).
- Full suite exit 0.

## Stop

Two failures with the same cause; input hash mismatch; any SEARCH block not found exactly once.
