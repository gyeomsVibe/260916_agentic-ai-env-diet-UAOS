# U307 — Fix Claude Stop hook duplicate `Stop says:` (`project_owns_gate`) and all-DONE `WAIT_STATUS` false wait

- Owner (author): antigravity · judge: claude
- Origin receipt: User mobile screenshot (`media_1793773249475_f299877a.jpg`, 2026-11-04 15:20 KST) showing `Stop says: ⏸ 대기·멈춤 이유: codex 사용량 한도로 멈춤 → 19:05 복귀 예정` printed twice at the end of Claude's turn in `[261104-1]`, plus `.coord/WAIT_STATUS.md` reporting `state=WAITING, all_done=False (완료: 148건, 잔여: 0건)` and `evt_20261104T1444-claude-0001` (`STOP_UNGUARDED` after 1 block in a single Stop event).

## Stage 0 — Official Docs & Root Cause Evidence
- Claude Code Hooks Reference (`https://docs.anthropic.com/en/docs/claude-code/hooks`): Both user (`~/.claude/settings.json`) and project (`.claude/settings.json`) `Stop` hooks run when present, and each hook's JSON `systemMessage` is rendered as `Stop says: <message>`.
- Root Cause 1 (`v7_harness/coord/stop_gate.py:project_owns_gate`): Checked `"coord stop-gate" in text and "--from-hook" not in text` across the entire `.claude/settings.json` file. Because `.claude/settings.json` has `--from-hook` in `SessionStart`, `UserPromptSubmit`, and `SessionEnd`, `"--from-hook" not in text` evaluated to `False`, so the global Stop hook (`--from-hook`) never stepped aside for the project Stop hook (`--project .`), running `coord stop-gate` twice per turn stop.
- Root Cause 2 (`v7_harness/coord/wait_reason.py:reasons`): Emitted `<other> 사용량 한도로 멈춤 → <time> 복귀 예정` even when `.coord/master_schedule.json` was valid and 100% of phases were in `DONE_STATES` (`완료: 148건, 잔여: 0건`), causing `Stop says:` to claim work stopped for Codex quota when all scheduled cards were already finished.

## Acceptance Criteria
1. `project_owns_gate(REPO, "claude")` returns `True` when `.claude/settings.json` has `--from-hook` in `SessionStart`/`UserPromptSubmit`/`SessionEnd` and a non-`--from-hook` `coord stop-gate` command under `hooks.Stop`.
2. `wait_reason.reasons(project, tool)` omits peer `LIMITED` wait lines when `.coord/master_schedule.json` is valid, non-empty, and all phases are in `DONE_STATES` (while still reporting `LIMITED` peers when no schedule exists or when any phase is non-DONE).
3. `python -m unittest tests.test_u307_stop_gate_dedupe tests.test_u146b_auto_gates tests.test_u201_wait_reason` exits 0.
