# U295 — Claude <-> Antigravity coordination bottlenecks (B1 B2 B3 B4 B8; B7 B9 B10 analysed)

MIA strategic 11-stage record. Author: Claude (card session, acting for Codex while LIMITED; marked CODEX_REREVIEW).
Receipts: `.coord/notes/BOTTLENECK_RECEIPTS_261102.md` (2026-11-02, Claude main desk [261102-1]).

## Stage 0 — research (official sources)

| Source | What it settles |
|---|---|
| https://kubernetes.io/docs/concepts/architecture/leases/ | A lease names one holder (`holderIdentity`) with a duration; others take it only after it expires; the holder renews. Model for B2. |
| https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches | "Dismiss stale pull request approvals when new commits are pushed": an approval belongs to a diff; a new push voids it. Model for B4 (we refuse the push instead, or mark STALE and say so). |
| https://cli.github.com/manual/gh_pr_merge | `--match-head-commit` makes GitHub refuse a moved head (already used by `merge_route`); the verdict must therefore name the full head. B3. |
| https://git-scm.com/docs/git-rev-parse | `rev-parse --verify <rev>^{commit}` resolves an abbreviated sha only when unambiguous, else fails. B3 short-sha resolution. |
| https://docs.python.org/3/library/os.html#os.replace | `os.replace` is an atomic rename on the same filesystem. B8 schedule write (tmp + replace, as `benchmark_logic_transplant.py:953`). |
| https://kubernetes.io/docs/concepts/architecture/controller/ | Level-triggered reconcile (already cited by `owner_wake.py`); wake routing reads current desk state each loop. B8 reroute. |

## Stage 1 — frame

- Decision: make the coordination state (who writes a branch, which head a verdict pins, which card is done) a durable
  record checked by the deterministic commands, instead of letters and model replies.
- Success signal (machine-checkable): `python -m unittest tests.test_u295_branch_guard` (17 tests) passes; full suite has
  no new failures; on the receipts' scenarios: a second writer gets `LEASE_HELD`, a push over an open request gets
  `VERDICT_FREEZE`, a short-sha verdict reaches the gate with the full head, a merged `[U###]` PR closes its phase, and
  a LIMITED owner gets no OWNER WAKE.
- Non-goals: mailbox watch addressing / singleton watcher (B6) and STOP_UNGUARDED flood (B5) — card U296; stop-gate
  no-ask (U294); agy auto-responder internals (B1 beyond the lease record), deliver blocking (B11).

## Stage 2 — verification of the frame

Each fix maps to one receipt: B2 (#259/#252 double writer), B4 (10b1949 -> 2923c21 -> c5cfe70), B3 (`MERGE-GATE-SHORTSHA`
x2, #256/#258), B8 (9 phases READY after merge, OWNER WAKE to LIMITED Codex). Allowed files cover all four. Go.

## Stage 3 — macro plan, alternatives

| Option | Value | Feasibility | Viability | Risk |
|---|---|---|---|---|
| A. Lease + freeze files on the shared desk, checked by `push-check` / `coord lease`; full head embedded at `deliver`; schedule closed in `merge` (chosen) | Closes B2 B3 B4 B8 at the commands every tool already runs | High: stdlib, the existing `requests` registry already stores `head` per verdict request | One new module + small hooks; no new daemon | A tool that pushes without `push-check` bypasses it (same as today's grant check) |
| B. Lease rows inside `coord.sqlite3` (DB) | Same value; queryable | Medium: WAL DB is shared by many writers; a new table needs migration | Couples to DB schema owned elsewhere | Lock contention with the sentinel; migration risk |
| C. GitHub-side: branch protection "dismiss stale approvals" + required reviewers | Strong for B4 | Low: all tools share one GitHub account, so reviews are not independent identities; needs repo settings change (human-only boundary) | Cannot express "which tool holds the branch" | Settings change is a 윤겸스-only action |

Decision: A (Go). B rejected for coupling/migration risk, C for the shared-account identity gap and human-only settings.

## Stage 4 — verification of macro plan

The verdict registry (`v7_harness/coord/requests.py`, U277) already records `head` and `WAITING_STATES`, so the
freeze needs no new state. `push_check` in `stop_gate.py` is owned by in-flight U294, so the freeze/lease checks live in
a new module and are chained in `cli.cmd_coord_push_check` after the grant check (stop_gate.py untouched).

## Stage 5 — detailed plan

New `v7_harness/coord/branch_guard.py`:
- Lease: `<shared desk>/.coord/leases/<branch>.json` {branch, tool, session, head, acquired_at, renewed_at, expires_at};
  `acquire` under `stream._exclusive` lock, refuses another live holder (`LeaseHeld`); same holder renews; `release`
  only by holder, record kept (nothing deleted); `leases()` = briefing source (B1). TTL 4 h (longer than one card's
  run, shorter than a 5 h usage window, so a holder that hit its limit frees the branch before reset).
- `lease_check`: another tool, or an unnamed pusher while a lease exists -> DENY `LEASE_HELD`.
- Freeze: open (`PENDING_DELIVERY`/`OPEN`) requests whose `head == origin/<branch>`; a push of a different local head ->
  DENY `VERDICT_FREEZE`; `--supersede` -> ALLOW, `STALE` rows appended to `.coord/verdict_freeze.jsonl`, one ACTIONABLE
  `VERDICT STALE` letter per (request, new head) to the requester.
- `embed_full_head`: a verdict/verdict-request message without a 40-hex head but with exactly one 7-39 hex token that
  `git rev-parse --verify` resolves gets ` head=<40 hex>` appended.
- `close_merged_phases`: `U\d+` ids in the PR title -> phases with that `phase_id` not DONE* become DONE with note
  `merged PR #N at <head12>`; tmp + `os.replace` under lock.
- `wake_recipient`: owner LIMITED/ABSENT -> `route_authority` conductor (if a tool and not the owner), else no wake.
Hooks: `merge_route.gate` reads the head from `message` or `delta`; `merge` calls `after_merge` (close phases, release
lease) on MERGED; `PR_FIELDS += title`; `deliver.deliver` embeds the full head for verdict letters; `owner_wake.wake_owners`
reroutes; `cli`: `coord lease --action acquire|release|show|list`, `push-check --tool --session --supersede`.

## Stage 6 — verification of detailed plan

Failure modes checked: parallel acquire (8 threads -> exactly one holder, test), path injection in branch (`..`
refused), ambiguous short sha (two tokens -> unchanged), all-digit tokens ignored, answered request no longer freezes,
lease/phase-close failure never undoes a merge (`after_merge` catches), UNKNOWN conductor -> no wake (fail closed).

## Stage 7 — implementation plan

Calculator gate route (U198/U98-D): Ollama local runs first, `worker: apply` with `apply_after` only after two
same-cause local failures; Antigravity `pilot judge`; commit with `Card: U295` + `Audit: relay_<agy PASS>`.

## Stage 8 — verification of implementation plan

Acceptance command fixed before the runs: `python -m unittest tests.test_u295_branch_guard` plus the existing tests of
every touched module (merge_route, deliver, owner_wake, cli push-check). Fixed tests are not edited.

## Stage 9-10 — implementation, debugging and gate receipts

See the "Gate receipts" section below (filled from the real runs).

## B7, B9, B10 — analysis (not implemented here)

- B7 commit gate gives no route: the refusal text names the slots but not the route. Fix belongs in
  `calculator_gate.main` (not an allowed file): print the exact `pilot manual new` -> local -> `apply_after` chain and
  the card's existing failed run ids. Proposed as a follow-up card.
- B9 every reviewer reruns the full suite: `merge_route.ci_attested` already verifies a signed CI receipt for the same
  head; reviewers could accept that receipt instead of rerunning. Needs a reviewer-manual rule plus a `pilot review
  --ci-receipt` flag; outside allowed files. Follow-up.
- B10 child session hit the subscription limit silently: the verdict request stays OPEN in the registry, so the stall
  scan already sees it; what is missing is reroute of an open request whose *reviewer* session died. With leases, a
  review lease that expires (TTL) is the signal. Follow-up: give review sessions a lease on `review/<pr>` and let the
  stall scan reroute on expiry.

## Gate receipts

- `U295-BG-LOCAL1` (worker local, Ollama, whole-module spec): FAILED `PROVIDER_ERROR`; the model answered a new file
  with `===EDIT` blocks.
- `U295-BG-LOCAL2` (worker local, ~20-line slice, U198): FAILED `EDIT_FENCED_NEEDS_EXISTING_PY`, the same cause.
  Two same-cause local failures -> `worker: apply` with `apply_after: U295-BG-LOCAL2` (U98-D).
- `U295-BG-APPLY` (bundle `d6176b54...`): DRY_RUN_PASSED, 160 tests OK; superseded before judging because the full
  suite found 4 regressions (adapter bullet count >6 in test_u219/test_u45; a new CALLER_INPUT subprocess site for
  test_u54_s2; docs/50 site count). Fixed by folding the adapter rule into the last bullet, adding the
  `_check_git_args` guard before `_git` (site now GUARDED), and regenerating docs/50 (`firewall_audit --write`).
- `U295-BG-APPLY2` (bundle `90ab91b9d676f39ed27c3e97af18766796df18452f84eba6adf40dc60018f1e7`): DRY_RUN_PASSED,
  acceptance 163 tests OK; `pilot review --reviewer agy` PASS (advisory); `pilot judge --judge agy` APPROVE ->
  APPLIED. Codex was marked LIMITED (lease until 2026-11-04 22:03) on its own rollout receipt: `task_complete`
  `usage_limit_exceeded` at 2026-11-02 14:51 local, "try again at Nov 4th, 2026 10:03 PM".
- Audit: request `relay_0a804dae9019e1cbf8f2072194baacf2` -> Antigravity reply `relay_ab5589d39a200ed025fb5f4b3e784b30`
  verdict PASS.
- `U295-BG-APPLY3` (same dictation on origin/main 91b53eb, bundle `af0eab04934bdacb...`): acceptance 163 OK, agy
  judge APPROVE -> APPLIED; the merge commit's cli.py/deliver.py equal this stage (normalised digest).
- Full suite: r2 (pre-merge) 2948 tests, 1 failure (own test flake: an all-digit 8-char sha prefix, fixed in
  67b61b7) + 1 u229 subprocess timeout under load (passes alone); r3 (merged tree) 2992 tests OK, skipped 7.
