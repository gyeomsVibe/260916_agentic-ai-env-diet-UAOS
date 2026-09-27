# U48-D0 — Claude re-review of the guarded deliver (2026-09-27 ~16:00)

Target: main checkout `v7_harness/coord/deliver.py` (mtime 15:38; adds a guard file created with `O_EXCL` around
publish → dispatch → restore) and `tests/test_u48_deliver.py` (mtime 15:30).
Reference evidence only; binding approval stays with Codex or the user.

## Verdict: REJECT, one new defect. The earlier race is largely fixed.

- **Race, measured.**
  - Command: `python -m unittest tests.test_u48_deliver` in a loop.
  - First loop: 18 of 20 OK.
  - Second loop: 30 of 30 OK.
  - Total: 48 of 50 OK. The 2 failures did not reproduce and their cause is UNKNOWN; they may have been caused by load.
  - Before the guard it was 1 of 4 OK.
- **Defect: a stale guard blocks publishing forever.**
  - Condition: a dispatcher crashes, is killed, or times out while it holds `delivery/guards/<id>.lock`.
  - Consequence 1: every later `deliver()` of that message returns `IN_FLIGHT` before publishing.
  - Consequence 2: the inbox never gets the message, which breaks D0's "publish first, return PUBLISHED even if no recipient".
  - Consequence 3: nothing recovers the guard.
  - Reproduction: create the guard file, then call `deliver(..., target="claude")` twice. Output: `IN_FLIGHT inbox msgs: 0`, and on retry `IN_FLIGHT`.
- **Fix, within D0 scope:**
  1. Call `box.publish()` before taking the guard. It is idempotent by id and digest, so the fact is durable even while a guard is held.
  2. Treat a guard older than the dispatch timeout plus a margin as stale: the Claude CLI timeout is 120 s, so use for example 300 s. Record the recovery in an attempt receipt, then take the guard over, just as `recover_stale_claims` does for claims.
  3. Add a test that pre-creates the guard: the message must be in the inbox at once. Add a second test that ages the guard: dispatch must proceed.
- **Unchanged open gates:**
  - No real recipient ACK exists.
  - The ACK path through `coord ack` still needs a fresh session.

## M1 Claude live call (16:02)

- This Claude Code session called `mcp__olla__local_draft` once. Instruction: reply exactly `M1-CLAUDE-CANARY OK`. Output: `[올라마] M1-CLAUDE-CANARY OK`, with no error.
- Caveat: this session started before Codex re-registered `olla`, so the call proves that the Claude→olla path works, not that the new registration (PYTHONPATH runtime/0.3.1) was loaded. A newly opened session is still needed for that. Codex: UNKNOWN. Antigravity: UNKNOWN (LIMITED).
