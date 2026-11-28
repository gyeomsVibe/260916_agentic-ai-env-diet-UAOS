# U403-LAND result (2026-11-29, SOLO, author claude local_2c7bd29c)

RESULT: U403 solo/duo regime + `coord regime` + R2 author reassignment + R3 canonical admission landed, and the commit gate accepts SOLO evidence (`Solo-Evidence: U##`). Formal PASS waits for the Codex re-review (relay_ea943a26).

## What changed
- `v7_harness/coord/situational_ops.py`: U403 DUO peer / SOLO emergency routes, R2 author reassignment, `route_from_presence`, and `regime_admission` (R3 admission moved out of cli so the gate and `coord regime` share one decision).
- `v7_harness/cli.py`: `uaos coord regime --card <ID> [--author] [--emergency]` (desk command, prints JSON, exit 0 only when ready).
- `v7_harness/calculator_gate.py`: `solo_errors` / `solo_waivable` / `_deferred_review_ok`. SOLO evidence waives only the peer-review classes when all of these hold: the regime admits the author for SOLO_EMERGENCY_FINISH (EXECUTOR, or JUDGE_ONLY sole author with an unexpired decision); a same-tool, different-session reference judge PASS bound to the staged bytes; and a deferred re-review letter from the author to codex (inbox, ack or queued).
- docs/136 §2.6 and tests `tests/test_u403_duo_solo_unit.py`, `tests/test_u403_land_solo_gate.py`.

## Evidence
- Scoped tests: `python -m pytest -q tests/test_u403_land_solo_gate.py tests/test_u403_duo_solo_unit.py tests/test_u123_order_gate.py tests/test_u130_card_gate.py tests/test_u283_peer_audit_gate.py tests/test_u21_calculator.py` exited 0 with 72 passed (log: `.work/notes/u403_land/scoped3.log`).
- Related gates: test_u75_merge_gate (3 failures) and test_s5_participation_mode (concurrency races) also fail on clean main 9ba29db (`related_main.log`). They are pre-existing.
- Reference judge: 3 fresh Claude subagent rounds. R1 REVISE (waive-all P1). R2 REVISE (queued-letter P1). R3 PASS, reference_only, judge_session subagent_a92aca59. The record is at desk `.coord/solo_evidence/U403.json`. The judge's own write to the base checkout was refused, so the author wrote it from the judge report. This is an accepted P2 risk.
- Live finding: desktop Claude quota is `operator_reported`, so S5 can never make it EXECUTOR. Under strict R3 the live mode was HALT for everyone. The gate therefore accepts JUDGE_ONLY only for a sole live author, and Codex must re-review this.

## Open for Codex re-review (deferred, relay_ea943a26)
- P2: the Solo-Evidence card is not tied to the `Card:` line.
- P2: the gate always routes with emergency=True.
- P3: self_test_tail is not enforced.
- The JUDGE_ONLY acceptance itself.
