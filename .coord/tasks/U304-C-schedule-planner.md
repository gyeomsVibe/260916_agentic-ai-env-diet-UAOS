# U304-C — 스케줄 기반 모델·추론강도·도우미 자동지정 + 세부 스케줄 실 세션

- Parent card: `.coord/tasks/U304-hud-uaos-os-revision.md` (items 3, 5). Lane ARCH_DESIGN→IMPL_CODE. Author claude, judge antigravity.
- Conductor note: written while Codex is LIMITED (until 2026-11-04 22:03 KST); marked `CODEX_REREV`.
- Deliverable class: maintained (recorded intent below + `tests/test_u304c_*.py`).

## Stage 0 — research (cited)

| Source | What it fixes in this design |
|---|---|
| OpenAI Codex config reference, `model_reasoning_effort` (https://developers.openai.com/codex/config-reference ; template default `medium`: https://github.com/openai/codex/pull/7449/files) | Codex effort values are `low/medium/high` (+ model-dependent `minimal/xhigh`); default `medium`. The planner emits only `low/medium/high`, so every value is valid on every Codex model. |
| Anthropic effort parameter (https://platform.claude.com/docs/en/build-with-claude/effort) | `output_config.effort` trades thoroughness for tokens; `high` = complex reasoning / hard coding, `medium` = balanced, `low` = classification/lookups/high volume. This is the semantic used for the three effort classes below. |
| Gemini thinking (https://ai.google.dev/gemini-api/docs/thinking) | `thinking_level` low/medium/high; some models accept only low/high. The planner never emits a level the router's lineup does not list, and emits `MEDIUM` only for models the router already uses at `Medium`. |
| RouteLLM (https://github.com/lm-sys/RouteLLM) | Route to the strong model only when the expected quality gain beats a cost threshold; the threshold is calibrated on own traffic. Here: flagship only when BOTH importance and difficulty are high; thresholds are recorded with reasons and band edges are calibrated on the measured ledger (`.coord/usage/runs.jsonl`). |

Alternatives compared: (a) keep static per-stage branches (today; no estimate — rejected, it is the receipt), (b) learned router like RouteLLM `mf` (needs preference data we do not have — No-Go now), (c) deterministic feature score + ledger-calibrated bands (Go: explainable, testable, 0 paid tokens).

## Design

Module `v7_harness/coord/schedule_planner.py` (new). Reuses `helper_thinking_router` (U304-B owns it, called only):
`select_optimal_helper_and_thinking` (lane, Ollama task, baseline), `get_official_tool_lineup` (helper, model validation),
`infer_lane_from_card_metadata`, `SUB_PROCESS_STAGES`.

1. **Estimate** (per step): `importance` 0–3, `design_difficulty` 0–3, `impl_difficulty` 0–3, `expected_tokens`, `files`, `risk`, `lane`.
   - importance = 1 (every scheduled card is ordered work) + 1 keypoint words (security, authority, evaluator, gate, schema, canonical, 권한, 보안, 평가기, 정본…) + 1 emphasis (explicit `keypoint`/`codex_exclusive`/P1/`TOP-EMPHASIS`/강조). SP1 research and SP5 merge get −1: their mistakes are cheap to redo and are re-checked by SP2/SP4.
   - design_difficulty = number of distinct design words (architecture, concurrency, atomic, algorithm, estimator, router, 설계, 동시성…), +1 in ARCH_DESIGN, clamp 3.
   - expected_tokens = median of measured ledger rows of the same card family (e.g. `U304*`) → else median of rows of the same lane → else lane prior (only with an empty ledger).
   - impl_difficulty = quartile band of expected_tokens against all measured ledger rows (q25/q50/q75 edges), +1 when the card allows ≥4 files.
   - stage complexity: SP1 = min(1, design), SP2 = design, SP3 = impl, SP4 = max(design, impl), SP5 = 1 if risk words else 0.
2. **Score → tier** (both axes 0–3):
   - `FLAGSHIP` importance ≥2 AND complexity ≥2 → flagship main + `High`.
   - `STANDARD_HIGH` one axis ≥2 → standard main + `High`.
   - `MECHANICAL` complexity 0 and importance ≤1 → standard main + `Low`.
   - else `STANDARD_MEDIUM` → standard main + `Medium`.
   - `IMMINENT_EXHAUSTION` of the acting tool demotes FLAGSHIP to STANDARD_HIGH (same rule as the router's `imminent`).
3. **Assign**: main model from the U304-B lineup (flagship = `keypoint_escalation_model`, standard = `main_model`: codex gpt-6-astra/gpt-6.1-sol, claude opus-5-5 only, antigravity gemini-4-argon only; `MAIN_MODEL_TIERS` is the fallback), validated against the lineup; a tool with no cheaper main runs non-flagship steps at `Medium`, so `High` on Opus 5.5 / Argon stays a budget-paced flagship grant (U304-C-A3, after PR #276); helper = lineup `primary_helper_model` (one per tool, U304-B 1:1); helper effort `Low` when the step fits one Ollama/helper slice (expected_tokens ≤ q25) or is MECHANICAL, else `Medium`; never `High` (high reasoning is the main model's job). Router selection is kept as `router_baseline` for comparison.
4. **Live sub-schedule driver**: `coord schedule --sub plan|advance|complete|show`. Durable state lives in `master_schedule.json["sub_schedule_driver"]` (capacity_planner rewrites `sub_process_schedule.json` whole, while master is read-modify-write and keeps extra keys) and is mirrored to `sub_process_schedule.json["live_driver"]` for the HUD. `plan` imports `card_sub_schedules` cards and, with `--card-file`, the card table rows; `advance` closes the ACTIVE step and opens the next dependency-ready one; master phase gets `sub_progress`/`current_sub_step`. Writes are atomic (tmp + `os.replace`) under an exclusive lock file, after a backup copy in `.work/backup_<date>/`.
5. `coord schedule --master plan` writes `model_assignment` on every non-DONE phase (and with `--card-file` adds missing card phases as READY).
6. **Measured budget is a required input** (윤겸스 2026-11-04 2nd order, card Item 7; routing rule same day). `plan_sub`/`plan_master` take `budget` = {tool: {remaining_5h_tokens, remaining_week_tokens, reset_5h_at, reset_week_at, measured_at, plan}} (U304-D `budget_snapshot()` shape; CLI `--budget-file`, else `usage_budget.budget_snapshot()` once U304-D lands).
   - Fail closed: missing, partial, unparseable, older than `budget_freshness_s` (900 s) or past its weekly reset → `BudgetUnavailable`, nothing written (exit 2).
   - Paced headroom per tool = min(5h remaining, weekly remaining ÷ 5h windows left to the weekly reset); a passed 5h reset leaves only the weekly pace.
   - Flagship allowance = paced headroom × `flagship_pace_share` (Antigravity Ultra 0.5, Codex/Claude $20 plans 0.1 → Argon gets 5× the grants); each grant spends the step's expected tokens.
   - FLAGSHIP routing: Antigravity steps → Gemini 4 Argon High within its share; Codex/Claude flagship (GPT-6 Astra / Opus 5.5) only for declared keypoints within their own share; any other heavy step is rerouted to Antigravity Argon High when its share fits and Antigravity is not the step's judge (author ≠ judge); otherwise STANDARD_HIGH on its own tool ("flagship withheld"). The grant ledger is written to `sub_schedule_driver.budget` / `master.schedule_budget`.

Non-goals: no edit of `helper_thinking_router.py` / `capacity_planner.py`; no paid calls; no measured-savings claim (UNMEASURED).

HUD request (to U304-A by letter): render `live_driver` steps and their `assignment` in the schedule panel and keep `live_driver` when capacity_planner rewrites the sub file.
