```contract
work_id: U95-R
worker: agy
goal: Research, from primary sources on the web, which levers cut the paid tokens that Claude Code, Codex CLI and Antigravity spend per step of a long workflow, and whether each lever is enforced by a rule text, a config value, a hook or code; write one sourced table and a recommendation.
inputs:
- .coord/tasks/U95-token-thrift-frame.md sha256=3df2834111d428ce27b62a9145a2457a7b8416019d980056e0a2d989ff2e85c4
- .coord/tasks/U95-R-check.py sha256=bee10de67e6078930b251800bff522f96c45f9817ca2035ed056aebc07c8777f
allow:
- .coord/notes/U95_token_thrift_research.md
acceptance: python .coord/tasks/U95-R-check.py
forbidden: editing, creating or deleting any file except the one allowed file; editing U95-R-check.py; git of any kind; reading or printing .env files, keys, tokens, credentials, cookies or session values; installing anything; paid API calls outside your own session; judging or approving your own output; claiming a number without a source URL
stop: the acceptance command passes; or two failures with the same cause; or the token budget is reached (write what you have, rows you could not source are left out, never invented)
judge: claude
timeout_s: 2400
remote_budget_tokens: 300000
```

## Why (context for the worker)

Read `.coord/tasks/U95-token-thrift-frame.md` first: it holds the measured baseline. In short, Claude re-reads about
140k tokens of context on every paid call, the context right after a compaction is 72–86k, and 5-hour and weekly
limits run out inside one conversation. The owner's goal is a much longer workflow on the same budget, with
token-thrift as the default mode of all three tools. Your research decides which rules and settings the next cards
change, so every row needs a primary source the judge can re-open.

## Questions (at least 2 rows each; more rows are better when each has its own source)

- Q1 Claude Code: what a paid call's input consists of and what controls its size and price: prompt caching and the
  cache lifetime (is a 1-hour cache available in Claude Code, and how is it enabled), automatic compaction and
  `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`, `/compact`, MCP tool definitions and tool search (deferred tools), subagents
  keeping their own context, CLAUDE.md and memory size, and how plan usage limits count cache reads.
- Q2 Codex CLI: `model_auto_compact_token_limit`, `project_doc_max_bytes` and how AGENTS.md files are chained, tool
  output truncation limits, prompt caching, reasoning effort; official openai/codex docs or its GitHub config reference.
- Q3 Antigravity and Gemini CLI: how GEMINI.md and rules are loaded, chat compression thresholds
  (for example `chatCompression.contextPercentageThreshold`), hooks with `injectSteps`, context caching.
- Q4 Offloading mechanical work to a local model (Ollama or similar) in coding-agent setups: measured savings and
  measured quality risks; papers or GitHub projects with numbers, not blog opinions.
- Q5 Enforcement: evidence on whether agents follow cost rules written in instruction files versus settings, hooks or
  code (instruction-following under long prompts; tool choice by description semantics, for example arXiv:2510.00307).
- Q6 Long multi-step workflows on a fixed budget: plan and state kept on disk, subagent context isolation, batching
  tool calls, summarization; measured effects where they exist.

## What to produce

`.coord/notes/U95_token_thrift_research.md` containing:

1. One markdown table whose header is exactly `| id | question | finding | source | quote | tool | enforce |`.
   - `id`: Q1-1, Q1-2, ... Q6-n.
   - `finding`: one sentence, with the number when the source gives one.
   - `source`: one https URL of the primary page (official docs, GitHub source or issue, paper). No search-result URLs.
   - `quote`: at most 25 words copied from that page that support the finding.
   - `tool`: claude, codex, antigravity or all. `enforce`: rule, config, hook, code or none.
2. `## Recommendation`: at most 10 bullets, each naming the lever, the tool, the exact setting or rule text you would
   change, the expected effect with its source row id, and the risk. Mark a lever UNMEASURED when no source measured it.
3. `## Not found`: questions or parts you could not source.

Do not edit any other file. Do not run git. When done, the judge (Claude) runs the acceptance command and re-opens five
of your sources; a row whose quote is not on its page fails the whole review.
