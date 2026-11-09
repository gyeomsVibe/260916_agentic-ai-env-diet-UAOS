# U195 explicit automatic PENDING candidates

Maintained contract draft; DESIGN REVIEW REQUIRED. Author: Codex, original scope/spec by Claude47da92e5. Native ownership handoff: relay_5788c92316f74416d7117197bc335783, no active writer/pilot. Execution checkout `.work/u195`, branch `codex/u195-pending-opt-in`, base `f23d0c25db60ebb291d601fb339a7fc6600f9441`.

## Stage 0: evidence research

- Primary source: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idneeds — dependent jobs require successful predecessors by default; failed/skipped predecessors do not silently authorize successors.
- Primary source: https://airflow.apache.org/docs/task-sdk/stable/api.html — default trigger rule `all_success` differs from `all_done`. Inference for UAOS: newly opted automatic phases must require DONE, not REVIEW; preserve existing READY/PLANNED stacking semantics.
- Observed receipt: original Claude `.work/u194_196/SPECS.md` reports U191-U185-FREEZE stayed PENDING after its dependencies completed. Independent installed-source reproduction `.work/userdesk_261015/U195_RED_RECEIPT.json`: 12 cases, 3 failures across codex/claude/antigravity; opted PENDING returns WAIT; nine negative controls pass. Schedule bytes unchanged.
- Root cause: `next_card.CANDIDATE` excludes PENDING. Installed transition controller consumes next_step, so it cannot publish these missing candidates. The shared untracked `master_scheduler.py` is outside the installed 124-file runtime and is not an authorized replacement or edit target.

## Stages 1–4: frame, comparison and review

Success: explicitly opted automatic phases become NEXT for the matching tool/session once all dependencies are DONE, with the same locked claim. No schedule mutation on reads. Unknown/failed/human/capped/raced conditions fail closed. Non-goals: enabling existing phases by default, weakening review/evaluators, changing original READY/PLANNED behavior, starting paid calls, or claiming native app restart.

Alternatives: (A) per-phase boolean opt-in and read-only candidate selection; (B) schedule-wide whitelist; (C) promote every PENDING. A is the smallest opt-in change and preserves owner control. B adds a second authority source; C can cross human/scope gates. Proposed A, not yet independently approved.

Original spec leaves cap field names undefined. Proposed exact schema: optional `caps` maps resource names to objects with exactly `used` and `limit`; both finite JSON numbers excluding booleans, `0 <= used < limit`. Empty/absent caps has no phase cap. Other phase keys containing underscore-delimited cap/caps/budget/budgets/limit/limits/token/tokens/quota/remaining markers are unsupported and block automatic promotion rather than being guessed. No quota-percent conversion or resource spending. This schema requires independent review before implementation.

Rollback: old runtime `0.3.0-ad00e2cb5602` remains intact; feature branch/local bundle may be abandoned without rewriting history. No opt-in flags are added to real project phases as part of implementation.

## Stages 5–8: fixed acceptance and implementation plan

Allowed implementation: `v7_harness/coord/next_card.py` only. New maintained frozen acceptance module may be added as `tests/test_u195_pending_auto.py`; do not edit existing tests, fixtures, budgets, evaluator code, PLAN owners, global settings or unrelated files.

Eligibility contract: state exactly PENDING, auto_promote exactly boolean true; depends_on must be a list of unique nonempty IDs resolving to DONE; absent/empty dependencies are allowed only with explicit opt-in. Reject duplicate/malformed phase IDs. Reject any human or gate_failed field, or rerouted_from state HUMAN/PARKED/SCOPE/BLOCKED/REWORK/FAILED; malformed reroute metadata blocks. Preserve owner_tool/all and owner_session matching. Validate caps as above. Existing READY/PLANNED rules stay unchanged.

Concurrency contract: an automatic claim must compare the exact schedule bytes observed by next_step again under the existing claim lock. Checking just owner_tool/session/state is insufficient: another process can revoke opt-in, fail a dependency or exhaust a cap before claim. Add an optional digest parameter to the existing claim API for the new path only; old callers retain their behavior. Do not mutate the schedule to mark READY.

Frozen black-box acceptance: all three tools positive/negative opt-in cases; REVIEW/failed/missing/duplicate dependencies; human/gate_failed fields including false/empty values; protected/malformed reroute; absent/valid/exhausted/NaN/infinite/bool/unknown caps; owner/session isolation; byte-identical read; one successful claim; actual parallel process races revoking flag, dependency or cap under the shared lock. Existing U146 ownership/parallel-lock and U197 regressions must remain green. Add no fixture-dependent production branch.

Route: first freeze acceptance and run RED; independent Antigravity design audit with input hashes and explicit cap/time limit; local worker one function/~20 changed lines per run. Each manual pins inputs, allowed output and exact fixed gate. Exact scope/hash inspection precedes promotion. Two same-cause small-slice failures permit one documented deterministic apply route; no automatic paid escalation. QUIET_LOCK and pre-edit backups before running.

## Stages 9–10: completion gate

Independent fixed suite plus full tests; card audit; exact-head non-author verdict and CI; push/PR/merge; install from merged main; runtime integrity and controlled resident restart; installed all-three-tool fixture and actual claim proof. Until these pass, status is not DONE. Record local/paid tokens and elapsed time including failures; unknown values remain UNKNOWN.
