# HUD-AUDIT-261031 — HUD widget full audit (truth of signals, ledger freshness)

Authority: user order 2026-10-31 (MIA strategic, consult Codex, parallel orchestration). Author: claude. Judge: codex (author != judge).

## Findings (verified by reproduction unless marked)
| ID | Sev | Finding | Evidence | Owner |
|---|---|---|---|---|
| F1 | P1 | Claude/Haiku shown LIMITED while Claude runs live turns | `.coord/availability/operator.json` USER_REPORT LIMITED (2026-10-29) overrode live presence ACTIVE (2026-10-31T02:23Z) in flagman copy `capacity_truth.py:79`; Haiku inherits it (`:132-138`) | data: claude (done) / rule: codex |
| F2 | P1 | Two writers race on `.work/hud_live/hud.html` | flagman service (`flagman_service.py:175-188`, claude LIMITED, conductor UNKNOWN) vs worktree 9616aa `scripts/uaos_hud_live.pyw` every 30 s (claude ACTIVE, conductor CODEX); page flips | codex (single-writer decision) |
| F3 | P1 | `capacity_truth.py` lives only in the flagman service copy, not in git, unreviewed | file absent from repo tree; DESK31 runtime-hold territory | codex |
| F4 | P2 | Master schedule stale | U283/U286 READY though merged in PR #253 (2026-10-29); U267 READY though PR #229 merged (title says U265: linkage mismatch); U277 (PR #250) and U279 (PR #252) lack `pr` | claude (sync) / codex (U267 ruling) |
| F5 | P2 | Ollama+Haiku offload 1.0% (2/192 calls, 24 h) | HUD `offload_efficiency_24h` | claude |
| F6 | P2 | Flagman "가동" is liveness only (PULSE_FRESH_PID_RUNNING), not content truth | `flagman_liveness` | codex |
| F7 | P2 | Quality-gate tile differs per writer (UNKNOWN vs PASS) | consequence of F2 | codex |
| F8 | P3 | Haiku card rows rendered twice | HUD screenshot | claude |

Unknown: who wrote the 10-29 operator.json entry (likely Codex DESK31); PR #229 real scope.

## Actions done
- F1 data: operator.json `claude` -> AVAILABLE / USER_REPORT, reason cites the user's 2026-10-31 statement; backup `.work/backup_20261031/operator.json`. Re-run of flagman snapshot: claude `presence_state` ACTIVE, `sched_conductor` claude (codex absent from that pulse).

## Proposed rule fix (codex, F1/F3)
A negative USER_REPORT expires: newer live presence ACTIVE (heartbeat newer than `observed_at`) or an operator TTL beats it. Add a reproducing test, commit `capacity_truth.py` to git, then one HUD writer (F2).

## Gate
`python v7_harness/...` snapshot from the single writer shows claude == live presence, conductor == `coord route` output, and only one process writes hud.html (`hud.html` writer tag constant over 3 pulses).
