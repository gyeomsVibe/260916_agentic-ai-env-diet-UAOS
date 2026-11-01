# U290D gate disposition (Claude author; judge Antigravity, Codex LIMITED)

Intentional default change: `agy_dispatch.DAILY_CAP` 20 -> None and `notify.DAILY_LIMIT` 24 -> None (윤겸스 2026-11-01).
An int still re-enables the cap; the existing cap tests patch 20/24 and are unchanged.
Kept (NOT removed): pilot per-call budgets, `notify.MIN_INTERVAL` 1 min, `NO_CHANGE` digest, secret/size refusals,
`BACKLOG_TRIES`=3, budget lock, `MAX_REPLY_CHARS`, `MAX_CONCURRENT_OLLA`=1. Only the two per-day count quotas go.

Evidence (Codex REVISE relay_b5d48223):
- (a) 10-module acceptance in stage: Codex ran 93 tests exit 0; U290D acceptance (11 modules) exit 0, bundle bd5484d5.
- (b) full suite on 463ddb5 + staged bytes: Ran 2817, OK (skipped=7), exit 0 (.work/u290d_full.log);
  sha256 manifest of 528 source+test files identical before and after the run (.work/u290d_manifest_{before,after}.txt).
- (c) this document.
- (d) tests/test_u290d_backlog_drain.py: 25 letters parked by the old cap drain the same day under the default; second drain answers nothing twice. Red before change (failures=2, errors=1).
- (e) KeptSafetyLimits tests pin the kept limits.
