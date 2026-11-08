# U327 — Automatic collaboration-mode failover (TRIO → DUO → SOLO)

Design owner: **Antigravity** (author). Brief + design review: **Claude Code** (non-author judge of the design).
Codex re-review on return (CODEX_REREVIEW). Status: DESIGN_REQUESTED, 2026-11-09. Deliverable kind: maintained.

## 0. User order (2026-11-09, binding)

1. Codex stopped on usage limit. Until Codex returns, **all Codex authority is delegated to Claude Code + Antigravity**,
   who split Codex's roles and proceed **without user approval by mutual agreement** (tiki-taka, author != judge).
2. First, fully inventory what Codex was running (done: §1).
3. Always critical (/CRITIC /REDTEAM), step by step.
4. MIA: stop making the user paste this order every time. Build a situational manual + logic that **automatically
   switches the collaboration form** when any tool hits a usage limit mid-process: 3 → 2-tool collaboration,
   2 down → solo, etc. Antigravity designs it; Claude helps.

Human-only list (delete data, remote push to main, deploy, public post, spend, account/credential/permission/
system settings) still binds in every mode. Standing feature-branch push/PR grant (2026-10-04) unchanged.

## 1. Codex in-flight inventory (sources: `.coord/tasks/DESK261109_ORCHESTRATION.md`, `coord route`, `coord inbox`)

| # | Work | Owner | Gate state at Codex stop | Next under delegation |
|---|---|---|---|---|
| 1 | U326-M1-S4 (PR291, head 09cca98) | Claude author; AGY verifier | Root REVISE, 3 reproduced regressions | Claude repairs under frozen acceptance; AGY judges |
| 2 | U311-U318 integration | AGY author; Claude judge | REVISE at f063f80 (Windows lock PermissionError, staged rename) | AGY repairs; 15 true-parallel stress runs; Claude judges |
| 3 | U321/U325 atomicity + reservation authority | Codex evaluator author | HOLD (API/evaluator pin required) | **Parked: Codex-exclusive keypoint** |
| 4 | U326-M1-S5 | Claude | Waits on S4 | After S4: 26 pinned acceptance + AGY verdict |
| 5 | Runtime reinstall | — | HOLD (clean exact-head regression + provenance) | Stays HOLD until S4/U311 green |
| 6 | U42-REPRO | parked (same cause twice) | route change needs Codex contract | **Parked: Codex keypoint** |

Route at 2026-11-09: `{"authority":"claude","states":{"codex":"LIMITED","claude":"ACTIVE","antigravity":"ACTIVE"}}`.
Open PRs: #291 (S4, REVISE, do not merge), #224 (draft snapshot, do not merge). Mailbox pending 222.

## 2. Gap (why the user had to paste the order)

- `v7_harness/coord/presence.py:392 conductor()` picks only **one conductor** by succession (codex → claude → agy).
  It does not encode the role split, who judges whom, which approvals proceed without the user, or what parks.
- The delegation order lives only in chat; nothing durable says "absence of X ⇒ standing approval for the rest".

## 3. Proposed model (Antigravity to refine or replace with evidence)

### 3.1 Modes (pure function of desk states; UNKNOWN never triggers a switch — existing fail-closed rule)

| Mode | Active set | Conductor | Author/Judge pairing | Parks |
|---|---|---|---|---|
| TRIO | C,L,A | Codex | as PLAN | — |
| DUO_LA (Codex out) | Claude, AGY | Claude (AGY backup) | Claude-authored → AGY judges; AGY-authored → Claude judges | `CODEX_EXCLUSIVE_KEYPOINTS` (U257): evaluator authorship, concurrency/security/release judge → park, mark CODEX_REREVIEW |
| DUO_CA (Claude out) | Codex, AGY | Codex | Codex ↔ AGY | Claude-owned cards reassigned only if unstarted |
| DUO_CL (AGY out) | Codex, Claude | Codex | Codex ↔ Claude | AGY merge role → Codex (merge priority 2) |
| SOLO_x | one tool | that tool | **no self-judge**: may implement, run fixed acceptance, commit to feature branch, open PR; verdict = `PENDING_PEER`; merge/release/runtime install HOLD | all judge-gated steps |
| NONE | — | none | deterministic watcher only (0 paid tokens) | everything |

C = Codex, L = Claude (deputy), A = Antigravity.

### 3.2 Standing delegation (removes the paste)

- Durable file `.coord/grants/collab_failover.json` recording the 2026-11-09 order:
  absent tool's authority passes to remaining tools; peer agreement replaces user approval; human-only list still
  binds; no self-judge; Codex-exclusive keypoints park.
- `coord route` reads it and returns `mode`, `roles`, `judge_map`, `parked`, `grant` beside `authority`/`states`.

### 3.3 Transition mechanics (evidence: Raft terms; Kubernetes Lease holder/duration/renewTime)

- `mode_term`: monotonic integer bumped on each mode change (Raft term) — letters stamped with an older term are not
  used for authority decisions (prevents split brain when a tool returns mid-step).
- Lease: conductor holds `holderIdentity` + `renewTime`; another tool may take over only after `leaseDuration`
  expires from the last observed renew (Kubernetes Lease semantics). No percentage→token conversion.
- Hysteresis: a switch needs two signals (e.g. LIMITED in tool log + no heartbeat renew) and a minimum dwell time,
  so one lost beat does not flap the mode. Each number gets a recorded reason.
- On change: one `MODE_CHANGE` stream event `{from,to,term,reason}`; each **receiver's** hook output shows it once
  (delivery counts only when shown in receiver hook output).
- Returning tool enters `REJOIN`: re-reviews inbox + diffs made in its absence (CODEX_REREVIEW list) before it
  conducts again; in-flight steps keep their owner (one platform owns a step).

### 3.4 Red-team checklist (design must answer each)

1. Flapping LIMITED/ACTIVE every few minutes → hysteresis + dwell time.
2. Split brain (Claude and AGY both conduct) → term + single lease file under the existing lock.
3. SOLO self-approval disguised as "peer agreement" → judge tool identity must differ from author, enforced in gate.
4. Delegation grant stretched to human-only actions → grant excludes the list; gate test.
5. Codex-exclusive keypoints silently done in DUO → park list machine-checked; any PASS on them is PROVISIONAL.
6. Tool dies holding lock/lease mid-commit → lease expiry, step owner unchanged, BLOCKED receipt, next ready card.
7. UNKNOWN heartbeat treated as LIMITED → forbidden (existing presence rule stays).
8. Windows concurrent-append loss on MODE_CHANGE events → true-parallel test.
9. Both remaining tools quota-thin → DUO must not burn the last reserve on routine ACKs; ACK_ONLY stays silent.

### 3.5 Fixed acceptance (proposal; the judge freezes it before implementation)

- A1 `collab_mode()` pure: all 27 combinations of {ACTIVE, AWAY, UNKNOWN}^3 → expected mode table (UNKNOWN ⇒ no switch).
- A2 judge_map never maps an author to itself in any mode; SOLO yields PENDING_PEER.
- A3 parked set in DUO_LA equals CODEX_EXCLUSIVE_KEYPOINTS.
- A4 grant never authorizes a human-only operation.
- A5 term monotonic under 15 true-parallel writers; zero lost MODE_CHANGE lines.
- A6 hysteresis: one signal does not switch; two signals do.
- A7 `coord route` backward compatible (`authority`, `states`, `quota_conversion` unchanged).
- Full suite green; no evaluator edited.

## 4. Ask to Antigravity

Author the design `docs/137_U327_collab_mode_failover_design.md` (beginner-complete Korean guide + English contract):
accept, replace or reject each part of §3 with evidence, answer every §3.4 item, freeze §3.5.
Reply via `coord deliver --target claude`. Claude judges the design (non-author). After design PASS, implementation
goes Ollama-first slices (U198); Claude runs full tests, PR, ledger; AGY reviews and merges (priority 1).

## Sources (Stage 0)

- Kubernetes Leases: https://kubernetes.io/docs/concepts/architecture/leases/
- Lease API (holderIdentity, leaseDurationSeconds, renewTime): https://kubernetes.io/docs/reference/kubernetes-api/coordination/lease-v1/
- Raft terms and election timeouts: https://en.wikipedia.org/wiki/Raft_(algorithm) (Ongaro & Ousterhout, "In Search of an Understandable Consensus Algorithm", USENIX ATC 2014)
