# AGY-PROXY-261031 — Antigravity usage limit: Claude + Codex split Antigravity's duties

Authority: user order 2026-10-31 (no-approval, non-stop; human-only Safety list still applies). Antigravity is LIMITED until it returns; this is the master record of who holds what.

## Evidence map (Stage 0/1 inventory, read-only)
- Merged by Antigravity before stop: PR #253 (U283 peer-audit gate + U286 HUD v4), #244 (U275 REA bridge), #243/#245/#246/#247 (Flagman U273-U275).
- Antigravity-authored OPEN: PR #252 U279 3-tool window pool + burst coalescing (head d2be820, CI `test` SUCCESS, mergeable UNKNOWN, no independent verdict).
- Claude-authored OPEN: PR #250 U277 verdict-request registry (MERGEABLE, no verdict); PR #224 DRAFT base snapshot (Codex re-review, do not merge).
- Blocked cards (coord brief): U278 (old L2 reverts U282 guards; Claude owns fresh-source fix), DESK31-RESET-PROVENANCE, DESK31-RUNTIME-HOLD (runtime reinstall HOLD stays).
- Inbox P1 waits: U275-VERDICT-DELIVERY, U275-R3-RUNTIME-INTEGRITY, U275-R8-L1, PR244-R8-DISPOSITION, U276-HARD-CAP-REGRESSION, U278-WIN32-NO-CONSOLE-L1.
- Antigravity presence: UNKNOWN since 2026-10-29T04:30Z (never a ground for acting alone; Claude+Codex both ACTIVE so conductor = codex).

## Duty split (author != judge)
| Antigravity duty | Holder | Judge |
|---|---|---|
| Admission / peer audit (U283 gate) of Claude work | Codex | Codex (non-author) |
| Admission / peer audit of Codex work | Claude | Claude |
| Merge priority 1 (Antigravity) | Codex | gate + match-head |
| PR #252 U279 independent verdict | Claude reviews (author was Antigravity) | Codex confirms merge |
| PR #250 U277 verdict | Codex | Codex |
| U278 fresh-source fix, U275/U276 P1 reconciliation | Claude implements | Codex |
| Runtime hold / reinstall, DESK31 | Codex | Claude cross-check |
| Heavy-token chores (multi-file patch, tests, doc sweep) | Haiku 5.5 (`uaos-haiku`) under Claude; Codex finds its own low-cost model equivalent | spec owner |
| Zero-token map/summary/search | Ollama (olla) first | deterministic gate |

## Budget rule
Paid-token order: Ollama -> Haiku 5.5 / Codex low-cost tier -> Sonnet/Opus effort medium. No paid polling. Record card_cost per card.

## Gate
A step with no machine-checkable pass command is unmeasured. Re-plan once if Antigravity returns with changed state; on return it re-reviews inbox and diffs of everything done in its name.
