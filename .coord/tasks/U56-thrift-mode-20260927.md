# U56 — Codex thrift mode: hand over before the quota runs out (2026-09-27)

Status: DESIGN (maintained). Author: Claude acting as Codex (user order 2026-09-27: "모든권한을 codex가 돌아올때까지
승인한다"). Codex started this card at 21:29 KST and stopped at 5% remaining of its 5-hour window before writing
anything. This file carries out Codex's stated plan, "절약모드 → 사전 인계 패킷 → Claude 권한대행 → Codex 복귀
재검토". Codex re-reviews it on return.

User's request (to Codex, 2026-09-27 21:28): "이제 너의 사용량이 7%미만이다. 이럴경우를 대비해 '절약모드'를
설계하라. 너 없이도 니가 있는 것처럼 미리 설계계획과 메뉴얼을 배포하여 권한 대행이 이를 따르게 하는 것도
좋은예이다."

## 1. Why this exists (what went wrong today)

- 21:29: Codex measured 95% used (5% left) in its 5-hour window, announced U56, and was cut off after context
  compaction. It left no files: the U53 worktree was clean, and no handoff packet existed.
- The deputy (Claude) had to rebuild Codex's intent from Codex's session log
  (`~/.codex/sessions/2026/09/27/rollout-…01a0e2a7….jsonl`) and from mailbox verdicts.
- Earlier the same day, Codex-to-Claude relays failed or lost replies (relay_d2eb17 timed out, relay_c98cfe's reply
  was not stored). U53 fixes storage, but the rule stands: **a handoff that is not written to a file before the
  stop does not exist.**

## 2. Rules that do not change

- Never convert a quota percentage into tokens. Limits bind on several axes (requests, tokens, windows).
  `coord route` already returns `quota_conversion: FORBIDDEN`. Thrift mode is triggered by the **displayed state**,
  not by an estimated token balance.
- Succession stays: Codex ACTIVE → Codex; otherwise Claude ACTIVE → Claude; only when both are away → Antigravity.
  UNKNOWN fails closed only when it decides the answer (U49-R1).
- The acting authority never uses `--coord-actor codex`. Acting verdicts are marked ACTING and Codex re-reviews them.

## 3. State machine

| State | Enter when | What the conductor does | Leaves to |
|---|---|---|---|
| NORMAL | quota display ≥ 20% left | plans, judges, implements as usual | THRIFT |
| THRIFT | display < 20% left (or the user says so) | no new implementation or broad scans; only finishes the current step; writes the handoff packet **first** | PACKET_READY |
| PACKET_READY | packet file committed or published and the mailbox notice sent | one short ACK-only reply per incoming relay; no paid polling | ACTING (on stop) or NORMAL (window reset) |
| ACTING | presence codex LIMITED/ABSENT and `coord route` = claude | deputy follows the packet in order; every verdict is ACTING | RETURN_REVIEW |
| RETURN_REVIEW | Codex ACTIVE again | Codex reads the return checklist, re-judges ACTING items, self-lineage first | NORMAL |

Why 20%: today Codex needed about two turns (~1 minute of work) between noticing "<7%" and being cut off at 5%.
Writing a packet costs one short turn. 20% leaves room for the packet plus finishing the current step, even when a
single verdict (for example U52-S1b: a 246-test rerun plus two counterexamples) takes a noticeable share. Tune it
from measured samples; do not treat it as a token budget.

## 4. The handoff packet (Codex writes it in THRIFT, before anything else)

Path: `.coord/handoff/codex-<YYYYMMDD-HHMM>.md` on a clean feature branch. The mailbox notice `kind: HANDOFF`
carries the path and the sha256. Contents, in this order:

1. **Snapshot**: origin/main SHA, open PRs, every worktree with branch + HEAD + dirty paths (`git worktree list`,
   `git status --short`).
2. **In-flight card**: work id, what is done, the exact next command, the acceptance gate, the stop condition.
3. **Queue**: ordered READY cards with owner and dependencies. Example from today: U51-R1 → U50-R1 → U52 rebuild,
   then U54/U55 contracts.
4. **Pending verdicts**: bundle id, work dir, which counterexample to re-run first.
5. **Decisions already made**: approvals with scope. Example: U50/U52 paid S2 approved by the user at 20:56, not
   transferable to U55.
6. **Do-not-touch list**: dirty main checkout, other sessions' worktrees, human gates that stay human
   (see §6).
7. **Return checklist pointer**: what Codex must re-review first.

A packet older than the last commit on any listed branch is stale. The deputy then rebuilds the snapshot itself
and records the difference.

## 5. Deputy manual (ACTING)

1. Seat: `coord presence --tool claude --state ACTIVE`; set codex LIMITED; check that `coord route` = claude.
2. Read the newest packet. If there is none, rebuild the intent from the Codex session log (read-only) and the
   mailbox, and write what was found into `.coord/handoff/rebuilt-<time>.md` before acting.
3. Run the queue in order, one source writer at a time. For each card: pin the input hashes, test red first, run a
   `pilot run --worker apply` bundle, `--approve` with `--coord-actor claude`, run the full suite, commit with the
   bundle digest (no `Calculator-Exempt` for deputy work).
4. Judge other authors' bundles independently: re-run the acceptance, repeat the Windows parallel gates (≥ 20 runs;
   today they caught U53's 1/30 defect), and try one counterexample per boundary.
5. Watch the mailbox with `coord watch --target claude` in the background (U57: zero tokens, exits 0 on a new letter,
   3 on timeout; re-arm after each wake). Never poll with a paid model. Codex's own quota refusal now turns its
   desk LIMITED by itself (U57-A); `coord presence --tool codex --state LIMITED --ttl <s> --lease` is the manual
   fallback.
6. Push feature branches and open PRs under the user's standing grant. When a merge is blocked by platform
   permission, report it; never work around it.
7. Record every ACTING verdict in the PLAN and in `.coord/codex_return_checklist.md`.

## 6. What stays human even in ACTING

- Anything the platform's permission settings deny (today: `gh pr merge`). The deputy reports it and does not try
  another route.
- Deleting data, changes to credentials or system settings, and spending beyond an approved scope.

## 7. Codex return checklist (RETURN_REVIEW)

1. `coord inbox`, then the newest handoff and the rebuilt packets.
2. Re-judge ACTING items, self-lineage first. From today: U49-G1R `5d3badd`, U53-F1 `e608caa`, and the ACTING
   APPROVE of your own U53 `0633dd1` (PR #19).
3. Check that the acceptance tests are unchanged and really measure the requirement.
4. Take back the queue and the conductor seat: presence codex ACTIVE.

## 8. Acceptance for this design (how we know it works)

- G1: the next time Codex drops below 20%, a packet file exists **before** the stop (a file check; pass/fail).
- G2: the deputy starts from the packet without reading the Codex session log (the log read is recorded as a
  fallback use).
- G3: every ACTING verdict appears in the return checklist, and Codex re-judges it within its first active window.
- The 20% threshold is UNMEASURED until 10 THRIFT episodes record the display value at entry and at stop
  (same rule as U55's 10 valid samples).
