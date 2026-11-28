# MODE-SDT result (Claude, 2026-11-29)

- Card: [MODE-SDT] Solo/Duo/Trio situation-manual modes + situational prompt library.
- PR: https://github.com/gyeomsVibe/260916_agentic-ai-env-diet-UAOS/pull/333 (OPEN, not merged)
- Committed: docs/140, docs/136 +1 link, this file.
- Code landed as U404 (commit af6be3b, branch claude/u404-mode-sdt-code stacked on U403-LAND PR #334) on SOLO evidence: fresh reference judge R1 REVISE -> fixed -> R2 PASS (reference_only), .coord/solo_evidence/U404.json; deferred Codex re-review relay_9edc7d49680eebc7674b6688c596e53e. Tests: 65 passed (log .work/mode_sdt/tests_r4.log).
- Written: docs/140 (modes SOLO/DUO/TRIO/HALT mapped to docs/136 regimes; 12 copy-paste prompt templates with trigger/mode/steps/[경계]); `uaos coord mode --show` (v7_harness/coord/collab_mode.py + cli.py); tests/test_mode_sdt_collab_mode.py (6 tests, UNKNOWN fails closed); docs/136 +1 link line.
- Tests: `python -m pytest tests/test_mode_sdt_collab_mode.py tests/test_s5_participation_mode.py tests/test_u355b_situational_ops.py tests/test_u365_situational_live_hook.py tests/test_*doc*.py -q` -> exit 0, 79 passed, 27 subtests (log .work/mode_sdt/tests_r2.log).
- Live: `coord mode --show` on the desk -> SOLO_CLAUDE, fail_closed true (codex/antigravity UNKNOWN), exit 1.
- Reference judge (fresh subagent, reference_only): REVISE on prompt-library completeness (missing trigger/mode lines, P12 boundary), ambiguous Safety wording, silent parser test guard. All fixed in the same commit; A1/A2/A3/A5 PASS.
- Ollama: local_draft attempted, unreachable (WinError 10061); 40-line module written directly.
- deferred_review: codex (binding verdict pending; author != judge).
- Tag: [자가구현/테스트] stays until TRIO beta.
- Gates: .work/notes/mode_sdt/GATES.md, research: .work/notes/mode_sdt/RESEARCH.md.
