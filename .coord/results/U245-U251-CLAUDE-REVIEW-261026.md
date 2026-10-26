# U245–U251 review by claude (acting for Codex, LIMITED) — 2026-10-26

Branch `origin/agy/u245-rea-failover-closeout` @ 05d4c32 (4 commits over origin/main, 27 files, +3030).
Author: antigravity. Reviewer: claude (non-author). Verdict: **REWORK** (not mergeable as is).

## Evidence (judge-run)

- `python -B -m unittest tests.test_u245_evidence_citation_gate tests.test_u246_analysis_view tests.test_u247_rea_static_bridge tests.test_u248_process_finalization tests.test_u249_failover_preemption_closeout tests.test_u250_reference_library_rule tests.test_u251_benchmark_logic_transplant` → 19 tests, exit 0 (letters claimed 31/31).
- Full suite log: `.work/review_u245_full.log` (main checkout).

## Findings (severity first)

1. **P1 — self-approval by the sole survivor.** `v7_harness/coord/failover_closeout.py` `replan_on_quota_limit`: when only one tool is ACTIVE, every `REVIEW` phase is set to `DONE` (`acting_sole_survivor`). The survivor is usually the author, so it approves its own work and unlocks dependants. This breaks "missing independent review is UNKNOWN; never self-approve". Fix: keep REVIEW as REVIEW with `needs_return_review`, and let only phases that do not depend on it proceed. Missing test: a sole-survivor REVIEW phase must stay non-DONE.
2. **P1 — BLOCKED and ACTIVE phases are force-reassigned.** `REASSIGNABLE_STATES` includes `BLOCKED` and `ACTIVE`, and `waiting_on` is dropped. A step blocked on a human boundary, an external reset or a dependency becomes READY for another tool, and an in-progress ACTIVE phase is taken over with no stall check. That gives two platforms on one step. Fix: reassign only READY/PLANNED; BLOCKED only when `waiting_on` names the unavailable tool; ACTIVE only after a stall timeout.
3. **P2 — unlocked read-modify-write of `master_schedule.json`.** It does an atomic replace but takes no lock, so two tools running the failover at once lose each other's updates. Fix: use the lock the other schedule writers use, plus a real two-process test.
4. **P2 — the commit claim does not match the code.** 05d4c32 says "wire failover_closeout into stop_gate", but `stop_gate.py` is unchanged on the branch, and nothing outside tests imports `replan_on_quota_limit` or `preempt_foreground_wait`. The feature is not live.
5. **P2 — fake telemetry.** `cmd_coord_transplant_status` passes a hard-coded `active_watchers=["coord watch --target antigravity"]` and `changed_files=[]`, so the 5-chip status reports a watcher that may not exist.
6. **P3 — card hygiene.** All 4 commits carry `Card: U245`, U250 and U251 included, and they share one Audit relay. The schedule expects separate cards.
7. **P3 — scope.** Three large HTML/MD reports are committed into `docs/` in the same PR as the runtime code. Split them out.

## Required for PASS

Fix findings 1–5 with tests that fail on the current code:

- Finding 1: a sole-survivor REVIEW phase stays non-DONE.
- Finding 2: a phase BLOCKED on a human stays BLOCKED.
- Finding 3: a concurrent replan from two processes keeps both updates.
- Finding 4: a stop_gate path calls the failover.

The judge then re-runs the 7 modules and the full suite.
