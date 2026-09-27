# U49 — Claude acting as Codex: critical review and applied verdicts (2026-09-27)

Order: the user said on 2026-09-27: "codex를 기다리지말고 ... 지금까지 구현한 것을 codex의 입장에서 codex대신 수행하라".
- That order overrides the default "no self-judging" rule. The global CLAUDE.md lets explicit user instructions take
  precedence.
- It does not override code guards. Claude never passed `--coord-actor codex`, so no Codex identity was forged.
- Each codex-judged manual got a byte-exact copy that differs only in `judge: claude`
  (`.work/mkjudge.py` asserts exactly one judge line).
- Approval ran through the unchanged `pilot run --approve` gate as `--coord-actor claude`.
- Every verdict below is **ACTING** and binding until Codex re-reviews on return. Codex may revert any of them.

Usage at review start: 5-hour window 11% used (resets 23:59 KST), weekly 41% used (resets 10-03 04:59 KST).
Context was 186k/1M.

## Part 1 — critique of U49 so far (/CRITIC /REDTEAM /SELFREFINE)

| # | Severity | Finding | Evidence | Fix / status |
|---|---|---|---|---|
| C1 | P1 | **Runtime provenance gap.** All 3 tools run global runtime `0.3.2-ad721a2fc713`, but it matches no commit. | `mailbox.py`/`deliver.py` = Codex's uncommitted files in `.work/u45_claude` (d8865ad3, 308dd373). `olla_mcp.py` = a third, uncommitted version (7e969624). `current.json` set 15:40:52; main `uaos_everywhere/VERSION` = 0.3.0. | This review lands those layers on a branch (Part 2). A runtime reinstall from the merged commit needs user approval (global install). |
| C2 | P1 | **Open bundles pinned an uncommitted base.** D0 and OLLA-SCOPE-F1 input hashes matched only `.work/u45_claude` (branch `claude/u48-next`, 2 commits ahead of main, uncommitted Codex work). They could never apply to main. | D0 pins mailbox d8865ad3; main working copy has 3e677ca0. F1 pins olla_mcp 319e7b1d; main has b6bf9f1f. | Codex's base (Layer A) was imported verbatim. The source tree was read-only and not modified. |
| C3 | P2 | The U49 plan said "no independent judge → everything waits". That was not wrong under the default rules, but it left a known P1 (C1) unaddressed. | §6 of the U49 plan | Superseded by the user's order. |
| C4 | P2 | Claude wrote Codex's presence (ABSENT) itself. The presence desk has no "declared by" field, so a tool can promote itself to authority. | `coord presence --tool codex --state ABSENT` from a Claude session | Source recorded in the U49 plan §1. A `declared_by` field is a follow-up for Codex. |
| C5 | P2 | `JUDGE_IS_AUTHOR` compares the judge with the **worker** (`apply`), not with the content author. A Codex-written apply bundle passes the check for `--judge codex`. | `judge.py:191` | Follow-up for Codex. Not changed here, because it is a design change to the evaluator. |
| C6 | P3 | Rows appended by the usage ledger are LF in a CRLF working copy (57 CRLF, 3 LF). Git normalizes on commit, so the repository is unaffected. | byte count of `runs.jsonl` | Record only. |
| C7 | P3 | The number "≤150k session tokens" in the U49 plan had no stated basis. | U49 plan §4 | Replaced by the measured usage above. |
| C8 | P3 | Project rule: record `/usage` at start and end. The start value was taken only from the user's screenshot. | this file | Recorded here and at the end. |

## Part 2 — Codex's role (/CRITIC /STEPBYSTEP /OPTIMIZE)

- Objective: make main == reviewed code, with the fewest steps and 0 remote tokens.
- Constraints: fixed acceptance gates unchanged, input hashes pinned, the calculator gate honoured with no
  `Calculator-Exempt`, other trees untouched.

| Step | Card | Author → acting judge | Gate before | Result |
|---|---|---|---|---|
| 1 | Layer A import (mailbox publish race, `deliver.py`, `test_u48_deliver.py`, OLLA-SCOPE `olla_mcp.py` + test) | Codex → Claude (independent) | `test_u48_deliver`, `test_u17_olla_mcp`, `test_u23_mailbox` | 44 OK |
| 2 | U48-D0 `f7c13556` | Codex + Claude rework → Claude | fixed gate `U48-D0-fixed-gate.py` | APPLIED |
| 3 | U48-D1 `914f76c9` | Claude → Claude (self-lineage) | new test red on D0 (3 errors) → green; 5 suites | APPLIED |
| 4 | U47-OLLA-SCOPE-F1 `83cd8555` | Claude on Codex base → Claude | `test_u17_olla_mcp` | APPLIED |
| 5 | U48-W2 `d96778fa` | Claude → Claude (self-lineage) | 4 judge suites | APPLIED |
| 6 | U49-R1 `b740e15b` | Claude → Claude (self-lineage) | new test red on HEAD (11 failures) → green; U45 route test unchanged | APPLIED |
| 7 | U49-A0 `9144e709` (Codex's `coord deliver` CLI, 20 lines) | Codex → Claude | `test_u15_coord_cli` + deliver suites | APPLIED |

Left out on purpose:
- `.work/u45_claude` staged `uaos_everywhere/install_runtime.py`, `tests/test_u48_runtime_install.py`, VERSION
  0.3.1/0.3.2, and the `test_u45` VERSION relaxation. That is a parallel runtime installer beside the committed
  `v7_harness/runtime_install.py` (U48-R1, fa2c4ab), so ownership and intent are unclear. Codex decides.

### REDTEAM notes on the applied code (none blocks; all go to Codex)

- D0 `mailbox._read_settled`: 50 consecutive PermissionErrors on an **ack** file read as "absent". A permanently
  locked ack could then be re-published. At-least-once semantics already dedupe by id. P2.
- D0 guard recovery: a dispatcher alive past `GUARD_STALE_S`=300 s (the stated bound is the 120 s CLI timeout) loses
  its guard, and its final `unlink` removes the new holder's guard. P3.
- D1 `_dispatch_count`: a receipt that is valid JSON but not an object raises AttributeError, which is not caught.
  Receipts come only from `_write_receipt`. P3.
- W2 `run_resolved`: a `.cmd` shim runs through cmd.exe, so metacharacters in a path argument (`-C <runs dir>`)
  could be interpreted (BatBadBut class). Prompts go by stdin. Current paths contain no metacharacters. P3.
- F1: the `(parent, child)` pair pruning is intentional. An ordinary `pilot/` folder outside `.coord` is still
  searched.

### Codex-owned decisions (recommendations only, not decided here)

- U47-X1 (keep or re-commit b4c0fba's `Calculator-Exempt`): **keep**. It is history; rewriting it violates the
  no-history-rewrite rule, and this review shows the gate can be met by apply bundles.
- U47-C2 (Claude review cost 95k > 80k): count cache reads separately and set the budget from 2 measured runs.
  User and Codex decide.
- U46-G1 (merge-commit route in the calculator gate): still needed. Merges of already-APPLIED content should not need
  an exemption. User and Codex decide.

## Evidence

- Full regression after all steps: `python -m unittest discover -s tests -t . -p "test_*.py"`, Ran 992, OK (skipped=6),
  exit 0, 148.4 s. The baseline was 958 tests in 128.6 s: +34 tests, +15% wall time, below the 3x alarm.
  `python -m compileall -q v7_harness` exit 0.
- Receipts: `.work/u49_{d0,d1,f1,w2d,r1run,a0run}/runs/*/summary.json` (promotion APPLIED). The apply manuals and
  acting copies are in `.coord/tasks/`.
