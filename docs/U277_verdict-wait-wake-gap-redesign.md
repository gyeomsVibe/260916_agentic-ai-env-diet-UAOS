# U277 — Fix the gap where a requester never wakes after a verdict (MIA design, rev 2)

Status: maintained (it records intent and has tests). Author: Claude. Judges: Codex (design + final), Antigravity (audit).
Rev 2 answers Codex Stage 2/4 REVISE (`relay_26fd16e5…`, `.work/desk_261027_2/u277_design/DESIGN_VERDICT.md`),
which reviewed rev 1 at sha256 `45df000f…`. Each Codex correction maps to a section and test ID below (§9).

## 0. Evidence (Stage 0)
- Failure receipt `20261027T2228-claude-0001`. Claude asked for a PR #249 verdict with `deliver --verdict-requested`.
  The letter was DISPATCHED, and Claude ended its turn.
  - Codex answered at 21:06 with `coord log --kind BLOCKED` (`20261027T2106-codex-0001`).
  - The root desk also queued the passive NOTICE `relay_d6c9cbf6345e8ec2d583a0bcedb00c68`.
  - That notice was classified non-actionable, so no watcher woke Claude. Claude sat idle for 1 h 20 m.
  - Correction to rev 1: a letter did exist. It was passive, and the gap is that nothing actionable reached the requester.
- Same class as U208 (10-17) and the 10-26 three-hour idle. This is the second time, so the cause must be fixed.
- Official sources:
  - https://code.claude.com/docs/en/hooks : `asyncRewake: true` wakes Claude only on exit code 2. Ordinary async output may wait for the next interaction. A Stop hook with `decision:"block"` continues the turn.
  - Claude Code background Bash tasks notify the session when they exit. That is the route `coord watch --wakes-session` uses today (U117).
  - https://docs.python.org/3/library/threading.html#condition-objects : after a wake, recheck the real condition. A wake is a hint, never the answer.
  - https://www.sqlite.org/atomiccommit.html : state transitions must be all-or-none and survive a crash. We adopt the criterion, not SQLite.
- Code facts (main @6cc36b9):
  - `watch.watch` never reads `.coord/stream`.
  - `stall._letter_waits` scans only `delivery/queued/` and only the text token `VERDICT_REQUESTED=YES`.
  - `stop_gate.gate` ignores an open request.
  - `deliver` computes `message_id = relay_<sha256[:32]>` before dispatch (`deliver.py:1171,1325,1367`), so a request can be registered before the letter leaves.
  - `stream.archive_settled` moves settled events to `stream/archive/*.jsonl` and never deletes them.
  - `hook_context.shared_desk` maps a linked worktree to the main checkout's desk.

## 1. Frame (Stage 1)
The problem: an answer can arrive as a letter, a stream event or a passive notice. The requester listens to one channel, nothing ties an answer to its request, and nothing stops the requester from ending a turn with no wake route.

Success signals (all deterministic; test IDs are in §8):
- S1: an answer event or letter that names `request:<id>` moves that request to ANSWER_OBSERVED. A watcher bound to the requester session then returns `REQUEST_ANSWERED`. Fuzzy matches (same card, PR or sha) only produce `REQUEST_HINT` and the request stays OPEN.
- S2: `stall` counts a verdict request in `queued/` **and** in `accepted/` (DISPATCHED), whether it is marked by the structured flag or by the legacy token. This comes from the registry, not just a text predicate.
- S3: the stop gate blocks while an open request has no live wake lease bound to that session. It blocks again after the watcher dies. At MAX_BLOCKS it writes a durable `STOP_UNGUARDED` fallback event instead of silently allowing the stop.
- S4: the frozen rev-1 smoke tests (S2, S3) and all existing coord tests stay green. The full suite shows no new failure versus base.
- S5 (live, final admission): a native drill. A real Claude session registers a request, Codex appends an answer that names the request, the background watcher exits, and the same session runs `requests ack` with its own session id. A route that is unavailable stays UNKNOWN, never PASS.

Non-goals:
- No exactly-once promise. Wakes are at-least-once, and the acknowledgment is idempotent.
- No paid polling or paid retry loop, and no new daemon.
- No change to the Codex or Antigravity wake adapters. Each tool keeps its own semantics, and we claim no three-tool guarantee.
- No `cli.py` edits while U276 owns it (§6). No runtime hold, release or synthetic evidence changes.

## 3. Alternatives (Stage 3)
| Option | Value | Feasibility | Viability | Risk/Rollback |
|---|---|---|---|---|
| A. Convention only (always answer with an ACTIONABLE letter) | Medium. Codex now does this, but discipline has failed twice | High | Low | Low |
| B. Durable request registry + exact-reference answers + at-least-once wake/ACK state machine | High | High (atomic replace + O_EXCL lock already in tree) | High | Low: new module, wiring reverts alone |
| C. B + session-bound stop hold with a durable fallback + registry-backed stall | Highest | High | High | Low |

Decision: **C**. A stays in force as convention (Codex committed to it) and as defense in depth.

## 5. Detailed design (Stage 5)

### 5.1 Request identity and binding (Codex §1)
- `request_id` = the deliver `message_id`. It is stable and computed before dispatch.
- The record binds:
  - `project_root`: `shared_desk` resolved and absolute.
  - `repo`: normalized `origin` URL, or `""`.
  - `requester`: the tool. `requester_session`: the hook/session id, or `""` if unknown.
  - `target`, `card` and `subject`: a PR URL, or a free label when there is none.
  - `head`: a 40-hex sha, or `""`.
  - `created_at` and `binding_hash` = sha256 over the canonical JSON of those fields.
- **Answer intent is explicit.** An event answers a request only if `"request:<request_id>"` is in its `refs`, its actor is `target` and it carries an outcome:
  - VERDICT `evidence.outcome` in {PASS, REVISE, FAIL}.
  - BLOCKED (outcome BLOCKED).
  - HANDOFF with `evidence.outcome`.
  - A letter whose payload has `in_reply_to: <request_id>` also answers (outcome from `payload.outcome`, else `REPLIED`).
  - The target owns what its outcome means. The registry only records it.
- Anything else from the target that shares card, PR number or sha (≥7 hex) creates a `REQUEST_HINT`. The hint wakes at most once per (request, event). It never closes the request, and it never fabricates an outcome.
- Concurrent requests with the same card but a different head or subject are distinct ids. An answer naming one never touches the other.

### 5.2 Durable registration (Codex §2)
`deliver --verdict-requested` runs these steps in order:
1. Write `requests/<id>.json` with `state=PENDING_DELIVERY` (atomic replace under the per-request lock).
   - If that write fails, deliver **does not send**. It exits 1 with `REQUEST_TRACKING_FAILED`.
2. Dispatch or queue the letter as today.
3. Move the request to `OPEN` and record `delivery` = DISPATCHED | QUEUED.
   - DISPATCHED stays a delivery fact. It is not read, not ACK and not answered.

Idempotency and recovery:
- The same id with the same `binding_hash` is a no-op that returns the existing record.
- The same id with a different hash is refused with `REQUEST_ID_CONFLICT`. It never overwrites.
- `requests reconcile` finds `PENDING_DELIVERY` records and checks the delivery dirs for the message id. The record becomes `OPEN` if the letter is found, or `DELIVERY_FAILED` if the letter is absent after 10 minutes. 10 minutes is two dispatch timeouts, `DISPATCH_TIMEOUT_S`.

### 5.3 State machine and at-least-once wake (Codex §3)
States:
`PENDING_DELIVERY → OPEN → ANSWER_OBSERVED → WAKE_PENDING → ACKED → CLOSED`, plus terminal `EXPIRED`, `CANCELLED`, `DELIVERY_FAILED`.

- Every transition is a compare-and-set on `rev` under `requests/<id>.lock`. The lock uses O_EXCL with stale-owner recovery, the same pattern as `stream._exclusive`. The write is a whole-file atomic replace.
- **ANSWER_OBSERVED** stores the answer (`answer_ref` event id or letter id, `outcome`, `observed_at`). Answer data is never dropped before ACKED.
- **WAKE_PENDING** stores `waker` = {pid, process_created, session, lease_until}. The watcher writes it, then exits. The exit is the native wake.
  - If the waker process is dead or the lease has expired (`WAKE_LEASE_S = 1800`, one cache lifetime), any watcher may move the request back to ANSWER_OBSERVED and wake again. That is at-least-once.
- **ACKED** comes only from `requests ack --id <id> --session <s>`, where `<s>` must equal `requester_session`, or the request has no session.
  - A duplicate ACK is a no-op. A foreign session's ACK is refused with `ACK_SESSION_MISMATCH`.
- CLOSED is ACKED plus archival into `requests/closed/`. Nothing is deleted.
- Two watchers: only the CAS winner returns `REQUEST_ANSWERED`. The loser keeps watching.
- Crash at every boundary:
  - After ANSWER_OBSERVED: the next scan wakes.
  - After WAKE_PENDING with a dead waker: re-wake.
  - After the process exits before the session reads it: still WAKE_PENDING until the lease ends, then re-wake.

### 5.4 History, replay and lifetime (Codex §4)
- Exact answers are matched by `request:<id>` in **all** stream files: the live `*.jsonl` and `archive/*.jsonl`.
  - Ordering uses (file name, line index), never `ts`. Clock skew and equal timestamps therefore cannot drop or reorder an exact answer.
  - Archive files are immutable, so each watcher process scans each one once and caches it by (name, size, mtime).
- Hints consider only events whose `ts ≥ created_at − 300 s` (300 s is the skew tolerance). Hints are advisory, so skew only affects hints.
- `EXPIRED` comes after `REQUEST_TTL_S = 7 days` (the weekly limit window). Expiry is not an answer and not completed work. The stop gate reports an EXPIRED-but-unacked request once as a BLOCKED stream event. Records are retained, and retention never deletes them.
- `CANCELLED` comes only from `requests cancel --id --session` by the requester.

### 5.5 Native wake and bounded stop behavior (Codex §5)
- The watcher lease (`watch_file`) gains `session`, `adapter` and `process_created`.
- `watcher_wakes_for(project, tool, session)` is true only when all of these hold:
  - the lease has not expired;
  - `wakes_session` is true;
  - `adapter` is a supported native adapter;
  - `process_identity(pid) == process_created`;
  - the lease session equals `session`, or one side is empty and the tool has exactly one desk session.
- Claude adapters:
  - `claude-bg-task`, in use today: `coord watch --wakes-session` runs as a Claude Code background Bash task. Process exit means a task notification, which starts a new turn.
  - `claude-async-rewake`: the same command with `--wake-exit-code 2` under a hook with `asyncRewake: true`. Exit 2 means a rewake.
  - Both map the watch result to the process exit: a wake gives `wake_exit_code`, a timeout gives 0, so a timeout never wakes.
  - Lifecycle: start at SessionStart and re-arm after every wake.
  - Installing the asyncRewake hook is a settings change, so it ships through the reviewed runtime installer, not this card's source.
- Codex and Antigravity keep their current wake routes. This card claims nothing for them.
- Stop gate:
  - While the session has a request in OPEN, ANSWER_OBSERVED or WAKE_PENDING, and `watcher_wakes_for` is false, it blocks. The reason names the id and the arm command.
  - Blocks are counted per (session, request) up to `MAX_BLOCKS` (the existing guard). When the watcher dies the count resets once, so a fresh death blocks again.
  - At MAX_BLOCKS it appends one stream BLOCKED event `STOP_UNGUARDED request:<id>`, which is durable and seen by the conductor's briefing, then allows the stop. There is no retry loop.
  - If the native adapter fails (the watcher exits non-zero), the lease is cleared, so the next stop blocks.

### 5.6 Canonical desk and concurrency (Codex §6)
- The registry lives at `shared_desk(project)/.coord/requests/`, so linked worktrees share one desk. Records carry `project_root` and `repo`, and a lookup from a different repo ignores them.
- Concurrency is proven with real parallel processes (`multiprocessing`), not threads: two writers per id, and two watcher processes.
- U276 currently owns `cli.py` and pilot/coord CLI work. This card exposes `python -m v7_harness.coord.requests {ack,cancel,reconcile,list}`. CLI registration (`uaos coord requests …`) is a separate slice H3, serialized after U276 merges.
- The source worktree is isolated (`claude/u277-wake-on-stream`). Canonical installation happens once, after merge, through the runtime reinstall.

### 5.7 Stall (Codex §7–8)
- `_letter_waits` keeps its queued scan and adds the structured flag, which is slice L1.
- It also adds registry-backed waits for requests in OPEN with `delivery=DISPATCHED`. This is slice H2. The 3-line text patch alone does not cover DISPATCHED, and the design does not claim it does.

## 7. Route (Stage 7)
| Slice | Worker | Files | Gate |
|---|---|---|---|
| L1 stall text predicate (3 lines) | `worker: apply`, `apply_after: U277-L1` (Ollama failed SPLICE twice today; failed run preserved: 12961 in / 135 out, effect UNKNOWN, claim ABANDONED) | `stall.py` | frozen smoke S2 + `test_u179_wait_watchdog`, `test_u203_stall_quorum_timeout`, `test_u205_owner_wake` |
| H1 registry and state machine | Haiku 5.5 | `requests.py`, `tests/test_u277_request_wake.py` | §8 R-tests |
| H2 wiring | Haiku 5.5 | `deliver.py`, `watch.py`, `stop_gate.py`, `stall.py` (registry waits) | §8 W-tests + frozen smoke |
| H3 CLI | after U276 merges | `cli.py` | separate card |

Prototype v0 (Haiku, rev-1 contract) is kept at `.work/u277/proto_v0/` as non-approved input. H1 and H2 rewrite against rev 2.
- Antigravity runs a headless `pilot review` audit on each bundle.
- Codex judges the design rev 2, the expanded frozen tests and the final PR.
- Merge goes through the tool merge route.

## 8. Expanded frozen acceptance (judge-owned: `.work/u277/judge_v2_test.py`)
The rev-1 smoke file `judge_test.py` (sha `1a84debc…`) stays frozen.
- Its S1 asserted that a fuzzy match closes the request. Rev 2 forbids that, so S1 is **superseded** by J-E1/J-F1 and recorded as expected-fail under rev 2.
- S2 and S3 must still pass.

New cases:
- J-E1: an exact `request:<id>` BLOCKED event from the target gives ANSWER_OBSERVED, then WAKE_PENDING, and `watch` returns REQUEST_ANSWERED with that id.
- J-E2: an exact answer that sits only in `archive/*.jsonl` with an older ts (long-idle replay) is still found.
- J-F1: same target, same card, PR number in the summary, no request ref gives REQUEST_HINT. The request stays OPEN, and a second scan gives no second hint.
- J-F2: two requests with the same card and different heads. An answer naming request A leaves B OPEN.
- J-F3: the wrong actor, or the right actor with no outcome, causes no transition.
- J-D1: a registry write failure (the requests dir is a file) makes deliver send nothing and return `REQUEST_TRACKING_FAILED`.
- J-D2: re-registering the same id and binding is a no-op. A different binding gives REQUEST_ID_CONFLICT.
- J-D3: PENDING_DELIVERY plus a letter in `accepted/` reconciles to OPEN with delivery DISPATCHED.
- J-W1: WAKE_PENDING with a dead waker pid re-wakes. A duplicate ACK is a no-op, and a foreign-session ACK is refused.
- J-W2: two real watcher processes race and exactly one returns REQUEST_ANSWERED for the request.
- J-S1: the stop gate blocks with no lease, passes with a live lease bound to the session, blocks again after the lease expires, and at MAX_BLOCKS appends STOP_UNGUARDED and returns None.
- J-S2: a lease bound to another session does not satisfy the gate.
- J-T1: an accepted/DISPATCHED registry request appears in `stall._letter_waits`, and so does a queued letter with the structured flag.
- J-C1: a request registered from a linked worktree path is visible from the main checkout path.

## 9. Codex correction map
- §1 correlation → 5.1, tests J-F1, J-F2, J-F3.
- §2 durability → 5.2, tests J-D1, J-D2, J-D3.
- §3 wake/ACK → 5.3, tests J-W1, J-W2.
- §4 history → 5.4, test J-E2.
- §5 native/stop → 5.5, tests J-S1, J-S2 and live S5.
- §6 ownership → 5.6, tests J-C1 and J-W2.
- §7 coverage → §8.
- §8 contracts → §7. L1, H1 and H2 manuals are linted before dispatch.

## 10. Verify (Stage 10)
- `judge_v2_test.py` must fail on base 6cc36b9 for behavioral reasons, not only on a missing module. Each case is checked first against prototype v0, which lacks request refs.
- It must pass on the candidate.
- The full suite must show no new failures versus base.
- After merge: reinstall the runtime, then run the live native drill S5 with the exact receiver's own ACK.
