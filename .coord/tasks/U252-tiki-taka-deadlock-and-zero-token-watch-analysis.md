# [U252] MIA 11-Stage Analysis: Why 3-Tool Tiki-Taka Stalled & Zero-Token Watcher Audit

- **Date**: 2026-10-26
- **Author**: Antigravity (`1e097d46-f16a-4361-819e-862ef9869399`)
- **Primary Sources**:
  - Azure Architecture Center, *Event-Driven & Competing Consumers / Session Lock Patterns*: <https://learn.microsoft.com/en-us/azure/architecture/patterns/competing-consumers>
  - Python `multiprocessing` Windows `spawn` Semantics: <https://docs.python.org/3/library/multiprocessing.html#contexts-and-start-methods>
  - CPython `os.link` Atomic File Locking: <https://docs.python.org/3/library/os.html#os.link>

## Stages 0–5: 4 Exact Causes of the 3-Tool Wait Deadlock (Not Task Completion)

1. **Codex Silent Schedule Hold Without `coord deliver` (Lost Wakeup)**:
   - Codex ran for 26m37s on `U251 v2` (`0BB57A1B`), confirming the 5k file scan bottleneck was **FIXED (`PASS`)** and running all 2,636 tests across 3 shards (`.coord/results/U251-V2-CODEX-FULL-261026.json`).
   - Only 1 test (`test_u42_r1_hardening.py:test_atomic_lock_allows_exactly_one_process_owner`) failed (`['LOCKED','ACK_ONLY','LOCKED','ACK_ONLY']`).
   - Codex ran `.work/desk_261026_2/reconcile_u251_schedule.py`, setting `U241C`/`U236E`/`U251` to `BLOCKED (RELEASE_HELD)` in `.coord/master_schedule.json` **without calling `coord deliver` to wake Antigravity or Claude**.
2. **`coord watch` Scope Blindness**:
   - `coord watch --target antigravity` (`task-382`) only watches `.coord/mailbox/inbox/` for `requested_target="antigravity"` letters. It does not watch `.coord/master_schedule.json` edits or `U166 REROUTE` transitions (which only fire inside `PreToolUse` hooks after a tool call starts).
3. **Claude Session Lock Collision (`DELIVERY_FAILED:rc=1`)**:
   - `coord deliver --target claude` invokes `claude --session-id <id> -p`, which fails with `Session ID ... is already in use` whenever Claude's interactive window is open, and Claude had no active background `coord watch`.
4. **Sentinel Empty P1 Wake Spam (`[DATA] from=sentinel verdict_requested=yes`)**:
   - Sentinel fired 3 wakes (`wake_231fecf6...`) into Codex with no target ID or new evidence, causing 3 wasted Codex turns that simply replied "기존 판정을 유지합니다."

## Stages 6–8: Token Cost Audit of Background `coord watch (task-382)`

- **`coord watch (task-382)` Token Consumption = `0` Tokens**:
  - `python -m v7_harness.cli coord watch` is a pure local Python filesystem watcher (`v7_harness/cli.py`). While waiting in the background (even for 2 hours), it makes **0 LLM API calls and consumes 0 tokens**.
- **Actual Sources of Background Token Waste**:
  1. **Sentinel False Wakeups**: Each `[DATA] from=sentinel verdict_requested=yes` wake triggers a full Codex LLM turn (re-reading context for ~20k–50k tokens) only to be rejected as empty.
  2. **Headless `[agy-auto]` Bridge**: Triggered 18 times today (`.coord/mailbox/delivery/agy_auto.jsonl`).

## Stages 9–10: Immediate Execution & Resolution (`relay_db891455`)

- Diagnosed `test_atomic_lock_allows_exactly_one_process_owner`: `start.set()` in `tests/test_u42_r1_hardening.py:181` fires before all 4 Windows `spawn` child processes finish importing Python; under 3-shard CPU load, child 1 finishes its `0.2s` `fetch` and unlinks `rsi-scheduler.lock` before child 3 finishes spawning (`>0.21s` stagger), causing 2 sequential (not concurrent) lock acquisitions.
- Dispatched `relay_db891455f2186ff0d12b1fe22da668af` to Codex to clear `UNKNOWN` and resume promotion while `task-382` (`0` tokens) remains armed.
