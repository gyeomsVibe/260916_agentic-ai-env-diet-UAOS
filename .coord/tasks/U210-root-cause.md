# U210: why both tools stop in the middle of a tiki-taka (2026-10-18)

Receipt: the user, 2026-10-18: "또 둘다 멈춰 있어 … 티키타카를 하라는 지시를 구현 못하는 근본원인도 못찾고".
This is the eighth stop complaint (see memory nonstop-chain-no-turn-end).

## What happened

1. Codex wrote the U209-R2C execution contract to Claude: letter relay_9f21437a, requested_target claude,
   wake_class ACTIONABLE. Then Codex ended its turn to wait for the receiver's result.
2. Claude's `coord watch` woke the Claude session with `NEW_LETTER relay_9f21437a`.
3. Claude ended the turn without opening the letter. The Stop hook (`coord stop-gate`) let the stop through.
4. Each tool now waited on the other, and no turn was running anywhere.

## Root cause (code)

`stop_gate.gate` held a turn end only for a `NEXT` card on `.coord/master_schedule.json` (U146-A). A letter
addressed to the tool did not count as owed work. A HANDOFF letter is how one tool passes work to the other, so
the one moment the tiki-taka depends on, a letter just received, was the moment the gate ignored. The same gate is
the Stop hook of Codex and Antigravity (U146-B), so a letter could also end Codex's turn unread.

Contributing defect, seen in the same session: Codex verdict relay_82f23af5 was restored "after interrupted legacy
transport" with an older mtime. `desk_delta` decides freshness by `mtime > cursor.since`, so the DESK DELTA never
showed that verdict. It kept showing the same three stale letters on every hook call. That noise trains the reader
to skip the delta.

## Fix (this card)

`stop_gate.letter_hold`: while a fresh (≤1 day) ACTIONABLE letter addressed to the tool is still in the inbox (not
moved by `coord ack`), the stop is held once per letter id. The hold reason names the ids and the steps: open the
letter, act on it, deliver the result, ack. A letter left unacked holds only once, so the gate cannot spin. Old
backlog (1885 inbox items) is outside the 1-day window.

Universal: the gate runs for claude, codex and antigravity alike. A test proves the codex hold.

## Not fixed here (follow-ups)

- The DESK DELTA mtime freshness and stale repeats (above).
- Hooks run with cwd inside a pilot stage write `.coord/presence` and `.coord/stall` files there, which breaks the
  approval replay. This is the U209-R2B APPROVAL_MISMATCH cause, and it was reproduced again in this session (run3
  stage).
