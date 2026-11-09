# U303 — HUD Cockpit Reform (measured quota · helper models · live schedule)

- Owner (author): antigravity (IMPL_CODE) · co-author: claude (Claude-side recorder) · judge: non-author peer
- Origin receipt: 윤겸스 2026-11-03 21:06 KST screenshot — HUD shows `?`, `UNKNOWN`, `미확인` for every tool; schedule panel says "no active phase" (stale `U144-MASTER`, phase U279).
- Branch: `agy/u303-hud-cockpit-reform` (worktree `.work/wt_u303`, base `origin/main` 9ed3b88)

## Stage 0 evidence map (measured on this PC, 2026-11-03 21:10 KST)

| Tool | Measured source (read-only, no secrets) | Fields | Last sample |
|---|---|---|---|
| Codex | `~/.codex/sessions/**/rollout-*.jsonl` `token_count.rate_limits` (limit_id `codex`), also `~/.uaos/usage/ledger.sqlite3` `quota_snapshots` | primary 300 min / secondary 10080 min `used_percent`, `resets_at`, `plan_type`, `total_token_usage` | 2026-11-01 13:32Z: 5h 21 %, 7d 100 % (reset 2026-11-04 13:03Z); 3,189 rows |
| Antigravity | cockpit-tools cache `~/.antigravity_cockpit/cache/quota_api_v1_plugin/authorized/*.json` (`payload.models[*].quotaInfo`) + `cache/quota_history/*.json` (time series) — logic from jlcodes99/cockpit-tools | per-model `remainingFraction`, `resetTime`, `thinkingLevel`, `displayName`; history `remainingPercentage`, `countdownSeconds` | updatedAt 1793682218001 (2026-11-03 02:03 KST): Opus/Sonnet 5.5 72.3 % left, Gemini 3.8 Flash 23.1 % left |
| Claude | Claude Code 2.1.317 statusLine stdin JSON `rate_limits.five_hour/seven_day.used_percentage, resets_at` (docs: code.claude.com statusline) — recorded by a new statusLine recorder into `~/.uaos/usage/claude_rate_limits.jsonl` | 5h/7d used %, reset epoch, `model.display_name` | first sample after recorder install |
| Haiku/Ollama | `ledger.sqlite3` contributions + `.coord/usage/runs.jsonl` | calls, tokens | live |
| Models/effort | `~/.codex/config.toml` (`model`, `model_reasoning_effort`), rollout `turn_context.effort`; `~/.claude/settings.json` (`model`, `effortLevel`) + statusLine `model`; `~/.gemini/antigravity/antigravity_state.pbtxt` `last_selected_agent_model` → cockpit model map (`thinkingLevel`) | | gpt-6.1-sol/medium; opus; M401 |

Token figures: provider % stays the authority. Tokens-per-1 % is **calibrated** from paired samples (Δ used % vs Δ ledger tokens inside one reset window, median of ≥3 pairs); the HUD shows the formula, sample count and sample age next to every derived number. A stale sample is shown with its age, never as `UNKNOWN`.

## Master schedule (U303-MASTER)

| Step | Lane | Owner | Depends | Gate (machine-checkable) |
|---|---|---|---|---|
| U303-A measured quota collectors (`v7_harness/coord/quota_sources.py`) | IMPL_CODE | antigravity | — | `python -m pytest tests/test_u303_quota_sources.py -q` exit 0 |
| U303-B Claude statusLine recorder + install (`uaos_everywhere/claude_statusline_recorder.py`) | IMPL_CODE | claude | — (parallel to A) | recorder unit test exit 0; a live Claude turn writes ≥1 row |
| U303-C HUD reform: cards (measured %, reset countdown, tokens, calibrated remaining, cards, helper model/effort), no `UNKNOWN/미확인` strings, schedule panel from PLAN.md + master | IMPL_CODE | antigravity | A | `tests/test_u303_hud_render.py` + `tests/test_u286_hud_dark_flagman.py` + `tests/test_u256_*` exit 0; rendered live HTML contains 0 × `UNKNOWN`/`미확인`/`?` gauges |
| U303-D master/sub schedule rebuild (`.coord/master_schedule.json` phase pointer, `build_sub_process_schedule` reads PLAN active cards) | ARCH_DESIGN | antigravity | A | schedule test exit 0; panel lists ≥1 active card |
| U303-E cross review (claude judges A/C/D, antigravity judges B) | VERIFY_AUDIT | non-author | A–D | `coord deliver --verdict PASS` from the non-author |
| U303-F merge (priority 1 Antigravity), `uaos` runtime reinstall `--check` no drift, HUD restart, live verification | MERGE_RELEASE | antigravity | E | PR MERGED; `install --check` exit 0; live `hud.html` regenerated < 60 s with measured values |

## Detailed schedule (U303-A/C, author antigravity)

1. A1 Codex: freshest rollout row with non-null `primary` per `limit_id=codex`; carry `plan_type`; reset-elapsed ⇒ 0 % with `reset_elapsed=true` (gate: fixture test).
2. A2 Antigravity: parse cockpit `authorized` cache → group by quota pool (identical `resetTime`+`remainingFraction`), map `last_selected_agent_model` placeholder → display name + `thinkingLevel` (gate: fixture test).
3. A3 Claude: read recorder JSONL newest row (gate: fixture test).
4. A4 Calibration: tokens per 1 % from history pairs + ledger tokens, median, n, formula (gate: fixture with known answer).
5. A5 Helper/effort: Codex config + rollout `turn_context`; Claude settings + recorder `model`; Antigravity state + model map; helper lanes from `helper_telemetry` (gate: fixture test).
6. C1 Wire A into `collect_capacity_snapshot` (`measured_quota` per engine) and replace `UNKNOWN` fallbacks with last-measured+age.
7. C2 HTML: gauge = remaining % (measured), sub-lines: reset countdown, 5h/7d tokens used (ledger), calibrated remaining tokens + n, usable cards, model · effort · helper.
8. C3 Schedule panel: PLAN.md ACTIVE/REVIEW/READY cards + master pointer.
9. Full suite `python -m pytest -q -x` (record exit code), live render, screenshot.
