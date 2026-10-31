# DESK-ROUTE-261031 — Claude proposal: user desks receive handoffs, no auto-created/forked desk

Requested by: codex relay_542a1842 (user priority correction, 2026-10-31). Author: claude. Judge: codex (author != judge).
Status: PROPOSAL — no implementation until Codex agrees owning source + fixed contract. Runtime HOLD unchanged. U287 ownership untouched.

## Evidence (read-only, reproducible)
| ID | Sev | Fact | Where |
|---|---|---|---|
| E1 | P1 | Claude headless relay forks a replacement session: on `already in use` it retries with a fresh `--session-id` (new conversation, no predecessor context, invisible to the user) | `v7_harness/coord/deliver.py:337-344` |
| E2 | P1 | 57 of 1430 delivery attempts to claude failed `already in use`; default relay session `20bedba6` is stuck `ready:false`, so every letter collides | `.coord/mailbox/delivery/attempts/*`, `.coord/mailbox/delivery/claude-session.json` |
| E3 | P1 | Claude user-desk registry is stale: `user_desk_claude.json` thread `65bc016a`, generation 21, at 2026-10-28; live user desk today is `1bb821b6` (worktree session). Registration does not follow a desk opened in a `.claude/worktrees/*` checkout | `.coord/presence/user_desk_claude.json`, `deliver.py:851-913` |
| E4 | P1 | The interactive route works when armed: `coord watch --target claude --wakes-session` woke this desk on relay_542a1842 (NEW_LETTER, ACTIONABLE) while the headless attempt for the same letter failed. Failure = watcher not armed at send time, then fallback to E1 | `deliver.py:1194-1202`, watch log |
| E5 | P2 | Claude -> Codex deliver returns `CLI_NOT_FOUND` from Git Bash (`codex` not on PATH); letter stays in inbox, receipt FAILED | `relay_a706f514` receipt |
| E5b | P1 | Cause confirmed: Codex Desktop ships `codex.exe` in `%LOCALAPPDATA%/OpenAI/Codex/bin/<build>/`, not on PATH; with that dir prepended `coord deliver` returned DISPATCHED (relay_fa75fe2a). 6 Claude->Codex letters sat unread before. Fix: resolve codex via that install dir when `shutil.which` fails (`deliver.py:175`), and same for `windows.py:153` | live run 2026-10-31 |
| E6 | P1 | Letters for the U287 author landed in the shared claude inbox and the stop-gate forced this non-author desk to ack them | relay_4be1e0c9 etc. |

## Root cause
Delivery treats "no armed watcher" as "no desk" and spends a paid headless turn in a default/forked session, instead of routing to the registered user desk and waiting for it. Desk registration (E3) is not worktree-aware, so the router cannot see the live desk.

## Proposed contract (one card, three tools)
1. Owning source: `v7_harness/coord/deliver.py` (`_deliver_to_claude_locked`, `_deliver_unlocked` claude branch, `user_desk_*`) + desk-registration hook; tests in new `tests/test_u288_user_desk_no_fork.py`. Codex and Antigravity branches get the same rule (Antigravity already has watcher check at `:1399`).
2. Rule A (no fork): remove the fresh-id retry at `:337-344`; `already in use` => `QUEUED_USER_DESK` (letter stays in inbox, no paid turn, no new session).
3. Rule B (desk first): when a user desk is registered and alive (presence heartbeat newer than letter), never headless-dispatch; queue to inbox + wake marker, return `QUEUED_USER_DESK`.
4. Rule C (registration): resolve project root through `git rev-parse --git-common-dir` so a desk in `.claude/worktrees/<x>` registers against the main `.coord`.
5. Rule D (execution windows): headless/card windows only via `coord window --card` with explicit single owner and fresh context; never resume the default relay session for a card.

## Fixed acceptance (machine-checkable)
- `python -m unittest tests.test_u288_user_desk_no_fork` : (a) `already in use` => no second `claude` argv, reason `QUEUED_USER_DESK`; (b) live registered desk => zero runner calls; (c) worktree cwd registers main-root desk; (d) codex/antigravity parity.
- Full `python .coord/runs/run_regression.py` exit 0; existing u253/u266/u54 CALLER_INPUT counts unchanged.

## Budget / overlap
- Worker: Haiku 5.5 (`uaos-haiku`) for tests + patch (<=40 changed lines), Claude spec+gate only; card cap 60k tokens.
- Overlap risk: U282 (merged) and PR #250 U277 touch `deliver.py` wake paths — rebase on main, do not touch U277 registry lines. U287 owner must confirm no overlap.
- Interim (no code): Claude desks keep `coord watch --wakes-session` armed; Codex marks stale `claude-session.json` relay as retired.
