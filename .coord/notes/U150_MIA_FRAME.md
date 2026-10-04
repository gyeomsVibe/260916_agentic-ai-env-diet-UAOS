# U150 — MIA frame: no repeated user corrections, shared user window, 티키타카 rule

Author: Claude Code (user window `[사용자 대화창구-261004-2]`), 2026-10-04. Conductor: Codex (ACTIVE) approves; Antigravity reviews.
Trigger (receipts): relay_0fc40d5a collision (same text, codex then antigravity → MailboxRejected); 윤겸스's report that
Antigravity's PC app shows no change after "shared" work (U148 visible-desk gap); 윤겸스 had to repeat one error to each tool.

## 1. Frame

| Decision | Success signal (machine-checkable) | Non-goal |
|---|---|---|
| A. Letter ids can never collide again | Property test: changing ANY payload field changes the id, or the payload is identical (idempotent). Runs in `tests/`. | Rewriting mailbox storage |
| B. One user error report reaches all 3 tools once | Hook test: one prompt classified as an error report writes one receipt and one broadcast letter per tool; the 2nd report of the same signature is P1 with "root-cause card + reproducing test" | NLP beyond deterministic keywords |
| C. A user window is renamed `[사용자 대화창구-YYMMDD-N]` in every tool | `coord user-window claim` allocates N atomically (parallel test); Claude/Codex/Antigravity adapters each show the title in their own UI (receiver check: screenshot or the tool's own store) | Renaming non-user windows |
| D. 티키타카 is a fixed global rule | Rule line in canonical `core.md` + `uaos_global_rule_block.md`; install check shows no drift in all 3 tools | Loosening any Safety human boundary |

Evidence map. Fact: only `v7_harness/coord/deliver.py` mints `relay_` ids (grep, 2026-10-04); all 3 tools send via
`uaos coord deliver`, so one fix covers all three. Fact: root cause = id hashed a subset (actor, message, card, window)
while the stored payload also holds `requested_target`; any field outside the hash makes "same id, different bytes".
Fact: Codex owns the fix (bundle 8c1c8c61, versioned compact JSON identity). Fact: Codex titles live in
`~/.codex/state_5.sqlite threads.title/name` (`codex_session_bridge.py`); Claude desktop renames via
`set_session_title`. Unknown: Antigravity PC app's conversation-title store → Antigravity researches (card C-agy).

## 2. Review (decision memo)

A — alternatives: (1) add target to the key (Claude patch; fixed one field, the next new field collides again);
(2) hash the canonical identity JSON of all routing fields (Codex 8c1c8c61); (3) (2) + an invariant test that walks
every payload field. **Go (3)**: the test makes the class of bug impossible to reintroduce. Rollback: revert one commit.

B — alternatives: (1) a rule line only (already failed: users still repeat); (2) per-tool hooks with own logic
(violates shared core); (3) one shared module `uaos_everywhere/hooks/repeat_error.py` called by each tool's prompt
hook. **Go (3)**. Signature = sorted normalized key terms; receipts `.coord/usage/user_error_reports.jsonl`
(atomic append with lock, parallel test). Report 1 → letter to the other two tools; report 2 of the same signature →
P1 root-cause card. This is the "3번 지시" prevention: the 2nd and 3rd instruction never have to be typed.

C — **Go**: core `coord user-window claim --tool <t> [--session <id>]` (counter file `.coord/user_window.json`,
per-date N, lock). Adapters: Claude → hook tells the session to call `set_session_title`; Codex → sqlite title
update via existing bridge pattern; Antigravity → research card, then its store. Receiver check is mandatory.

D — definition (proposed rule text):
> 티키타카(tiki-taka): the default no-approval, nonstop relay between the three tools. Each pass is one dependency-
> ready card step handed over by `uaos coord deliver` with its evidence (diff, test exit code, verdict); the receiver
> acts within its own turn and passes on, never waiting for or relaying through 윤겸스. A pass without new evidence is
> ACK_ONLY; five passes on one item without new evidence re-plan it. Tiki-taka stops only at a Safety human boundary,
> a cap, or three same-cause failures; it never loosens a Safety boundary.

## 3. Execute (cards, single owner each)

| Card | Owner | Files | Pass command |
|---|---|---|---|
| U150-A | Codex (in flight) + Claude adds invariant test | `v7_harness/coord/deliver.py`, `tests/test_deliver_target_id.py` | `python -m pytest -q tests/test_deliver_target_id.py tests/test_u48_deliver.py` |
| U150-B | Claude | `uaos_everywhere/hooks/repeat_error.py`, `tests/test_u150_repeat_error.py`, adapters | `python -m pytest -q tests/test_u150_repeat_error.py` |
| U150-C | Claude core + Codex adapter + Antigravity adapter | `v7_harness/coord/user_window.py`, `tests/test_u150_user_window.py` | `python -m pytest -q tests/test_u150_user_window.py` |
| U150-D | Claude drafts, Codex applies canonical (rules edit guard) | `core.md`, `uaos_global_rule_block.md` | install check no drift |

## 4. Verify

Each card: fixed acceptance above + full suite log in `.work/`, independent verdict by Codex, then merge (human),
reinstall, and receiver check in all 3 UIs. After all: read `.coord/master_schedule.json`, agree the next phase by
tiki-taka letters, continue.
