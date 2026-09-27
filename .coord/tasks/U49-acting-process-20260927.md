# U49 — Claude acting-conductor process while Codex is absent (2026-09-27)

Author: Claude Code (acting conductor, user-declared Codex absence 2026-09-27 ~19:04 KST).
Status: PLAN (Claude-authored; Codex re-reviews on return — Claude never judges its own bundles).
User chat window: this session is pinned as the single user-facing chat (user-20260927).

## 1. Snapshot (verified 2026-09-27 19:04 KST)

- `origin/main` = `b3c1ca6` (PR #16), worktree clean, inbox 0, P1 0.
- Presence: codex ABSENT (user-declared, recorded ttl 14,400 s), claude ACTIVE, antigravity UNKNOWN.
- `coord route` = `BLOCKED_UNKNOWN`: `budget_route.route_authority` fails closed when **any** tool is UNKNOWN,
  even though Antigravity's state cannot change the answer when Codex is ABSENT and Claude is ACTIVE (see U49-R1).
- Full regression: see §5 (recorded after the run).

## 2. Open cards and what blocks each

| Card | State | Blocker | Who can move it |
|---|---|---|---|
| U48-W2 | REVIEW, bundle `139b9d2d` DRY_RUN passed | independent judge | codex (or agy if ACTIVE) |
| U48-D0 | REVIEW, bundle `020acb1c` DRY_RUN 50/50 | independent judge; real receive ACK missing | codex / agy |
| U48-D1 | PREPARED, 20/20 on scratch stage | D0 must be APPLIED first (hash pins D0 `deliver.py`) | claude after D0 |
| U48-M1 | REVIEW | new-session `olla` call per tool unverified | claude (evidence) + judge |
| U47-OLLA-SCOPE | REVIEW | binding verdict is Codex's | codex |
| U47-D1 | BLOCKED | causes fixed (N1/N2/D1a, PROBE3 exact-byte PASS) — can be retried | claude (manual + local run) |
| U47-X1 | READY | Codex decision on `Calculator-Exempt` commit | codex |
| U47-C2 | READY | review budget policy decision | codex · user |
| U46-G1 | READY | merge-commit calculator-gate route design | codex · user |

## 3. Process (ordered; each step has its gate before it)

- **S0 — seat** (done): pin chat, presence, route, inbox, full regression. Gate: regression OK, inbox 0.
- **S1 — judge probe, once**: `pilot judge --judge agy` on the smallest ready bundle, `U48-W2 139b9d2d`.
  Gate: APPROVE within budget → apply; QUOTA → A1 path records LIMITED, stop; no retry loop, no paid polling.
  Why W2 first: it makes `codex` resolvable on Windows, which later Codex judgments depend on.
- **S2 — judge-free work Claude may do now** (author-only, every output stays REVIEW):
  - U49-R1: route fix candidate — treat UNKNOWN as blocking only for tools whose state can change the result
    (Codex ABSENT/LIMITED + Claude ACTIVE → `claude` regardless of Antigravity). Red test first, apply bundle,
    DRY_RUN only. Gate: new tests red on HEAD, green on stage, `test_u45_general_uaos` unchanged and OK.
  - U47-D1 retry: publish + lint a manual, one bounded Ollama mechanical op via `pilot run --manual`.
    Gate: exact-byte acceptance; 2 same-cause failures → stop route (global rule).
  - U48-M1 evidence: one `local_read_map` call from this new session is observed (done in S0: `[올라마]` digest
    returned) → record as Claude-side evidence; Codex/Agy sides stay UNKNOWN.
- **S3 — on judge availability**, apply in dependency order: W2 → D0 → build D1 manual on D0 → D1 → U49-R1.
  Gate per bundle: independent APPROVE receipt + full regression OK + HEAD == origin after push (push needs user OK).
- **S4 — Codex return package**: append §2 table and every receipt path to `.coord/codex_return_checklist.md`;
  decisions X1/C2/G1 stay with Codex · user.

## 4. Limits

- No self-judging, no paid polling, no push/merge without user approval, no deletion.
- Budget per step: S1 ≤ one `pilot judge` default clamp; S2 Claude work ≤ 150k session tokens total; Ollama calls
  recorded in `.coord/usage/`.
- Stop and report on: 3 failures with one cause, any P1, route still blocked after R1 is judged REJECT.

## 5. Evidence log

- S0 (19:04–19:15): `python -m unittest discover -s tests -t . -p "test_*.py"` → Ran 958, OK (skipped=6), exit 0,
  128.6 s. `local_read_map` from this new session returned an `[올라마]` digest (Claude-side U48-M1 evidence only).
- S0 note: the main checkout sits at `768a1e9`, an ancestor of `origin/main b3c1ca6` (behind, not diverged). Left as is;
  no auto-pull (global rule).
- S1: the W2 bundle's original work dir was not in this worktree, so the bundle was rebuilt with the 0-token apply worker.
  Input hash `d3e7613e…` matched HEAD. `.work/u49_w2` → bundle `851948c0…`, acceptance exit 0, PASS.
  - `pilot judge --judge agy` on the original manual → `NOT_THE_NAMED_JUDGE` (the contract names `codex`).
  - A byte-exact copy `.coord/tasks/U48-W2-agy-judge-manual.md` differs only in `judge: antigravity`.
    Rebuild `.work/u49_w2c` → bundle `b5728f35…`, PASS.
  - Judge → `UNUSABLE`, `JUDGE_FAILED:agy QUOTA`, "Resets in 97h59m" (about 2026-10-01 21:15 KST).
    157 s, 0 tokens, `presence_marked=LIMITED`, receipt `.work/u49_w2c/runs/U48-W2/judge_agy.json`. Not applied.
  - A first copy made with `sed` altered line endings (BLOCKED) and was removed before use.
- Route after S1: `coord route` → `authority: claude` (codex ABSENT, antigravity LIMITED).

## 6. Consequence and revised plan

- No independent judge exists until Codex returns or agy resets (about 10-01 21:15 KST). Every bundle stays REVIEW.
  No self-approval.
- Judge-free Claude work continues in S2 order: U49-R1 red test + bundle (DRY_RUN) → U47-D1 retry. Each result
  stays REVIEW, is listed in the Codex return checklist, and is judged in S3 order when a judge returns.
- The only faster judge route is a headless `codex exec` call. The user declared Codex absent, so Claude does not
  spend Codex quota without the user's word.
