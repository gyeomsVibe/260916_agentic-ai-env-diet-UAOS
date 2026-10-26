# U253: Zero-Deadlock 3-Tool Tiki-Taka Orchestration Overhaul (maintained)

## 0. Stage 0 Pre-Research (Primary Sources)
- **Kubernetes Controller / Informer Level-Triggered vs Edge-Triggered Reconciliation**:
  - https://kubernetes.io/docs/concepts/architecture/controller/
  - https://github.com/kubernetes/sample-controller/blob/master/docs/controller-client-go.md
  - Edge-triggered notifications alone suffer from **lost wakeups** whenever state is mutated directly or a notification arrives between watch transitions. Level-triggered reconciliation (comparing desired state in `.coord/master_schedule.json` against claimed receipts on every watch cycle) guarantees eventual wakeup.
- **Claude Code CLI Session Locking & Hook Wake Semantics**:
  - https://code.claude.com/docs/en/cli-reference
  - https://code.claude.com/docs/en/hooks
  - `claude -p --resume <session_id>` fails with `rc=1` (`Error: Session ID <uuid> is already in use.`) when an interactive Claude Desktop/CLI session holds `<uuid>` open without a live watcher.
- **OpenAI Codex CLI & Antigravity Hooks**:
  - https://developers.openai.com/codex/hooks
  - https://antigravity.google/docs/hooks

## 1–6. Frame, Root-Cause Diagnosis (4 Deadlock Vectors), and Contract
### Why All 3 Tools Fell Into Infinite Wait (Verified Root Causes)
1. **RC-1 (`v7_harness/coord/deliver.py` `_WAKE_RES` Silent `LEGACY` Drop on `VERDICT_REQUESTED`)**:
   - `_WAKE_RES` matched `"VERDICT_REQUESTED=YES"` but NOT `"VERDICT_REQUESTED U225 ..."` (space-separated, as sent in `relay_c099939c9f382fc690607a8790c30272`).
   - `_requires_wake()` returned `False`, publishing an untagged `LEGACY` envelope (`wake_class=None`).
   - `coord watch --policy structured` (`watch.py:401`) permanently skips `cls != "ACTIONABLE"`, and `_deliver_unlocked` (`deliver.py:1115`) returns `QUEUED_INTERACTIVE` when `watcher_live` is True and `not _requires_wake(message)`, creating a 100% deterministic black hole where neither the watcher nor headless CLI ever wakes.
2. **RC-2 (`v7_harness/coord/deliver.py` `_deliver_to_claude_locked` Session-In-Use Collision)**:
   - When `.coord/mailbox/delivery/claude-session.json` holds an open interactive Claude session ID (`8d94eeeb-a66e-404e-947d-ee69c4756dfb`) and Claude's watcher expires, `claude -p ... --resume <id>` fails with `DELIVERY_FAILED:rc=1 ("Error: Session ID ... is already in use.")` without falling back to an ephemeral `--session-id <new_uuid>`, leaving Claude unreachable for 3+ hours.
3. **RC-3 (`v7_harness/coord/watch.py` Pure Edge-Triggered Inbox-Only Watch Loop)**:
   - `watch()` only scanned `.coord/mailbox/inbox/` and never checked level-triggered `READY`/`ACTIVE` phases in `.coord/master_schedule.json`. Direct schedule mutations or `U166` reroutes left watchers sleeping for up to `14,400s` (4 hours).
4. **RC-4 (`v7_harness/coord/master_scheduler.py` Silent Phase Transitions)**:
   - `MasterTaskScheduler.advance_phase()` and `mark_blocked()` mutated `.coord/master_schedule.json` without publishing a structured `ACTIONABLE` handoff to `.coord/mailbox/inbox/`.

## 7–10. Implementation & Independent RED -> GREEN Verification
- **Staged Candidate Overlay** (`.work/desk_261026_2/u253_zero_deadlock_stage/`, preserving live `deliver.py` hash `7DD331BA...` while `U251-TIMING` is being judged by Codex):
  - `v7_harness/coord/deliver.py` (`SHA256: 10E7339685F1480FED32D57AD0B5FBA0D38A4393C6AD1BA99375F842BD75E14D`)
  - `v7_harness/coord/watch.py` (`SHA256: 77C9F445843BA8935234E21CD4BD61C2E8AA899B49D0B834F5018E5C68E026BA`)
  - `v7_harness/coord/master_scheduler.py` (`SHA256: 133A26476B21CE55063F063AEC687B81CA3E276A2576A6F10CB3F86787703DCF`)
  - `tests/test_u253_zero_deadlock_watch_and_deliver.py` (`SHA256: 2989CE9B1DA901BE33CEBD6520B03C2A699B1BC781BD5321C092DE454E0130B7`)
- **Verification Gate Results**:
  - **RED (unpatched `v7_harness`)**: `Ran 4 tests in 0.277s — FAILED (failures=3, errors=1)` (all 4 root causes reproduced).
  - **GREEN (patched `U253` stage)**: `Ran 4 tests in 0.222s — OK` (`exit 0`).
  - **Regression Suite**: `tests.test_u141a_wake_policy`, `tests.test_u134_thread_fallback`, `tests.test_u144_master_scheduler` (`41 tests in 18.072s — OK`, `exit 0`).
