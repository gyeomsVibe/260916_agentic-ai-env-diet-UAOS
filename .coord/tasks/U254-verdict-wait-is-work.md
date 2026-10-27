# U254 — an owed verdict is the reviewer's next step

- Receipt (2026-10-26, P1, user): all three tools idled. `coord next --tool claude` said WAIT over 11 "open" cards. Ten
  were DONE_SCOPED/DONE_ELSEWHERE/RETIRED/SUPERSEDED. The eleventh, U253 in REVIEW with `waiting_on: claude-verdict`,
  was nobody's NEXT. So `stop_gate.gate` let every turn end.
- Fix: `v7_harness/coord/next_card.py`.
  - `TERMINAL` states are not open work.
  - A REVIEW phase whose `reviewer` is the tool, or whose `waiting_on` is `<tool>-verdict`, becomes that tool's
    `NEXT` with `kind: VERDICT`. This step comes after the tool's own READY/PLANNED cards. The author never gets its
    own verdict.
- Acceptance: `tests/test_u254_verdict_wait_is_work.py` (5 tests; 3 fail on main 2a32317), plus the next_card
  neighbours.
- Agreement: antigravity AGREE relay_de047426; codex re-review requested in relay_22d6b38c.
- Route:
  - Ollama U254-L1 failed with SPLICE_UNSUPPORTED (17460 input tokens).
  - `apply` U254-APPLY2 (apply_after U254-L1), then review by agy, the non-author.
