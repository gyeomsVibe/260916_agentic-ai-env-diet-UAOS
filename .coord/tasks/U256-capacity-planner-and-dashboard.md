# U256: 3-Tool Unified Token/Capacity Store, Capacity-Aware Master Scheduler & Dynamic Visual Dashboard (maintained)

## Stage 0. Pre-Research (Primary Sources)
1. **OpenTelemetry GenAI Semantic Conventions (`gen_ai.usage.*`)**:
   - https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-metrics/
   - https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/
   - Standardized attributes (`gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.usage.cache_read.input_tokens`) provide vendor-neutral token budget accounting across heterogeneous LLM providers.
2. **Anthropic Claude Code CLI & Session Window Accounting**:
   - https://code.claude.com/docs/en/cli-reference
   - Rolling 5-hour session capacity framework + weekly caps; local session transcripts (`~/.claude/projects/**/*.jsonl`) record per-message `input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, and `output_tokens`.
3. **UAOS-RSI Canonical Token Budget Policy (`docs/35_token-budget-routing-policy.md`, `v7_harness/budget_route.py`)**:
   - Never fabricate token counts from provider quota percentages (`%`); keep measured transcript/ledger token budgets and observed provider quota snapshots in strictly separate fields.

## Stages 1–8. Frame, 4-Lens Alternatives, Contract & Slicing
- **Problem**: All 3 tools (`Codex`, `Claude Code`, `Antigravity`) and the user need a unified, always-accessible store of used tokens, remaining 5-hour budget capacity, and usable card counts (`usable_cards_capacity`) so Master Schedule and Collaboration Schedule creation automatically adapts to remaining tool capacity and renders a dynamic visual dashboard when the user asks `"현재 진행상황을 보고해줘"`.
- **Selected Architecture (Option B — Dual-Persisted Project + Global Capacity Registry with Deficit-Weighted Scheduler & Generative UI Widget)**:
  - Persists `<project>/.coord/usage/capacity_snapshot.json` + `~/.uaos/usage/global_capacity_registry.json`.
  - Computes 5h/24h/7d windows across `codex`, `claude`, `antigravity`, `haiku`, and `ollama`.
  - Assigns `master_schedule.json` phases by highest remaining active capacity while enforcing `author != judge` and 60% Ollama/Haiku offload.
  - Provides `python -m v7_harness.cli coord capacity --project . --html <path>` for terminal gauge bars and interactive HTML/Tailwind dynamic charts.

## Stages 9–10. Verification
- `python -m unittest tests.test_u256_capacity_planner_and_dashboard -v` (3/3 PASS, exit 0).
