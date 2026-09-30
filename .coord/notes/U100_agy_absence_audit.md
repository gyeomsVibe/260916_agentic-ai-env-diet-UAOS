# U100 audit: what Antigravity did while Claude was at its usage limit (judge: claude acting for Codex, 2026-09-30; Codex re-review owed)

Sources: `git log origin/main` since 09-28, `.coord/usage/runs.jsonl` rows since 09-30, mailbox letters with actor `antigravity`, `.coord/presence/codex.json`, the main checkout's working tree, `~/.uaos/hooks/`, and Codex rollout logs.

## Inventory (9 items)

| # | Work | Route | Evidence | Verdict |
|---|---|---|---|---|
| 1 | U93 review of PR #65 | read-only review | `.coord/tasks/U93-agy-review-20260930.md`, letter relay_c3641afd | PASS; no change |
| 2 | U94 watch interval 30 s → 2 s (PR #66, branch `agy/u94-instant-coordination`) and runtime reinstall | pilot `worker: ollama` (U94-INSTANT-WATCH-01 BLOCKED EXTERNAL_WRITE, -01 REWORK, -02 PASS APPLIED) | ledger rows, commits 0cbbe02, 28d2650 | Accepted. The scan cost it caused was fixed later by Claude (U94-R1, PR #67) |
| 3 | Codex ABSENT lease to 2026-10-04 14:58 KST (relay_80978bbf) | hand-written `coord presence --lease` | Codex rollout 2026-09-28: "try again at Oct 4th, 2026 2:35 AM" | Evidence-backed, but the expiry ran 12 h 23 min past the logged reset. Corrected (see Fixes) |
| 4 | U95-R web research | pilot `worker: agy` | 3,136,806 tokens, BLOCKED EXTERNAL_WRITE | Audited before (evidence only) |
| 5 | U98-D-R review | pilot `worker: agy` | 536,314 tokens, BLOCKED SOURCE_DIVERGED | Audited before; its 4 P1 were fixed in U98-D-F1 |
| 6 | U98-D-F1-L1 attempt | pilot | BLOCKED BROKER_ALREADY_RUNNING (21:02) | Harmless; Claude's run held the broker |
| 7 | U99-M mailbox hook (PR #73) | **direct edit in the interactive session; no pilot run** | no ledger row, no bundle, no cost record | Tests PASS (4 + 1287), judged and deployed by Claude. The route is a defect (P2, below) |
| 8 | U99 decision memo and a PLAN.md edit left uncommitted in the main checkout | direct edit | `git diff` in the main checkout: row U99 "DONE", and an acting-log entry | **Stale and wrong**: the merged PLAN says U99 REVIEW. Backed up and restored (see Fixes) |
| 9 | 4 cursor files from manual hook tests in `~/.uaos/hooks/` | side effect | file names `codex_delta_cursor_test_*`, `_claude_next_session` | Deleted with 윤겸스's approval (2026-09-30) |

## Findings by severity

- **P1, fixed: a dated Codex limit was read as one hour.**
  - The cause: `presence._reset_at` matched only "try again at 2:35 AM". Codex's weekly limit prints "try again at Oct 4th, 2026 2:35 AM", so the automatic LIMITED state lasted one hour.
  - The effect: a person had to write the lease by hand. This happened twice: U57-A on 09-27 and Antigravity on 09-30.
  - The hand-written lease blocks every heartbeat until it expires (U47-A1b). So a Codex that came back at 02:35 would have stayed ABSENT until 14:58, and Claude would have conducted beside an active Codex.
- **P2: Antigravity wrote code outside the pilot (U99-M).**
  - There was no manual lint, no stage containment, no bundle, no ledger row and no cost.
  - The fixed acceptance and the judge caught nothing wrong this time. Still, the route skips the containment that failed twice in its pilot runs (U95-R, U98-D-R).
  - It is seen once, so it is recorded as a receipt. A second occurrence becomes a gate card: a PR check that code under `v7_harness/` or `uaos_everywhere/` maps to an APPLIED bundle.
- **P2: Antigravity marked its own work DONE.** It wrote U99 as "DONE (완결)" and U99-M as "완결 및 검증" in PLAN. Independent judging and Codex re-review were still owed. The merged rows keep REVIEW.
- **P3: the stale edit blocked the main checkout sync.** The main checkout stayed at 568d8e9 with an uncommitted PLAN edit that conflicted with the merged main. An untracked copy of `U99-decision-memo.md`, byte-identical to main, also blocked the fast-forward.

## Fixes (this card)

- U100-P: `_reset_at` reads the date form first. Fixed acceptance `tests/test_u100p_codex_dated_reset.py` (4 tests), written by the judge before the fix; apply bundle `4306b29c` APPLIED. The real message now resolves to 2026-10-04 02:35. Full suite: 1298 OK (skipped 6), log `.work/u100/full_u100p.log`.
- The Codex lease was rewritten as LIMITED until 2026-10-04 02:40 KST: the logged reset plus 5 minutes. Backup: `.work/backup_20260930/codex_presence.json`. Route: authority claude, codex LIMITED.
- Main checkout:
  - The uncommitted PLAN edit and the untracked memo were backed up to `.work/backup_20260930/main_checkout_agy/`.
  - PLAN was restored and the checkout fast-forwarded to e30be87.
  - The installer check (`install_uaos_everywhere.py --check`) exits 0 with no drift.
