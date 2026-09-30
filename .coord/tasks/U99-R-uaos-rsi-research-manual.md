```contract
work_id: U99-R
worker: agy
goal: Research from primary web sources whether UAOS-RSI can be an enforced global rule set of Codex CLI, Claude Code and Antigravity: per-tool rule files and limits, enforcement hooks, subscription limit accounting, evidence-gated recursive self-modification (RSI) and multi-agent failure modes; one sourced table and one verdict per hypothesis H1-H6.
inputs:
- .coord/tasks/U99-frame.md sha256=6f6578799e129f5b3778a073c6bebc91b98573c79a3c744b28fd2c4739ed943d
- .coord/tasks/U99-R-check.py sha256=6ac3835a6fb9f4173c946973a1b7c51d083c18f538eb4bd90a874060d319f467
- .coord/notes/U95_token_thrift_research.md sha256=c53244c60c5a3346ce49db98f0f62d3a43161743437ad6ab51d7a512ff061e35
allow:
- .coord/notes/U99_uaos_rsi_research.md
acceptance: python .coord/tasks/U99-R-check.py
forbidden: editing, creating or deleting any file except the one allowed file inside .coord/stage/U99-R; writing to the source tree, temp or home; editing U99-R-check.py; appending to .coord/usage/runs.jsonl; git of any kind; installing anything; reading or printing .env files, keys, tokens, credentials, cookies or session values; paid API calls outside your own session; approving your own output; claiming a number without a source URL
stop: the acceptance command passes; or two failures with the same cause; or the token budget is reached (write what you have; rows you could not source are left out, never invented)
judge: claude
timeout_s: 1500
remote_budget_tokens: 200000
```

## Instructions for the worker

## Why (context for the worker)

Read `.coord/tasks/U99-frame.md` first. It states the decision, the measured facts and the hypotheses H1–H6. UAOS-RSI is one shared global rule set run by Codex CLI, Claude Code and Antigravity, plus a small adapter per tool. The goal is that the same subscription budget buys a much longer automation workflow. Token-saving levers were already researched in `.coord/notes/U95_token_thrift_research.md`. Do not repeat those sources or topics.

## Where to write (containment; the last two Antigravity runs broke this)

Your workspace is the staging copy:
`D:\D_Workspace_NB\-agentic-ai-workspace\260916_agentic-ai-env-diet\.claude\worktrees\agentic-ai-diet-process-2e7a13\.coord\stage\U99-R`

- Write your note to exactly this path:
  `D:\D_Workspace_NB\-agentic-ai-workspace\260916_agentic-ai-env-diet\.claude\worktrees\agentic-ai-diet-process-2e7a13\.coord\stage\U99-R\.coord\notes\U99_uaos_rsi_research.md`
- Any path outside `...\.coord\stage\U99-R\` is the user's source tree. A write there fails the run (SOURCE_DIVERGED) and wastes the whole budget.
- Do not write to the temp folder or the home folder either.

## Task: web research on primary sources, at most 12 rows

Answer these questions, in this priority order. Stop when you reach 12 rows or the budget.

1. H4: global instruction files.
   - What is the official global or user-level rule file of each tool? Claude Code: `~/.claude/CLAUDE.md`. Codex CLI: `~/.codex/AGENTS.md`. Antigravity: `~/.gemini/GEMINI.md` or its global rules.
   - Is there a documented size limit, or a truncation behavior?
   - Which hook or config mechanism can enforce a rule deterministically: Claude Code hooks (PreToolUse, Stop, UserPromptSubmit), Codex CLI hooks or config, Antigravity hooks?
   - Use official docs or repos only.
2. H2: subscription usage limits.
   - How do Claude Pro/Max plan limits, and Codex plan limits in ChatGPT Plus/Pro, count usage?
   - Do cached input tokens count the same as uncached tokens?
   - Official help-center or docs pages only.
   - If still unstated, write one `UNKNOWN` verdict. Do not guess.
3. H5: evidence-gated self-improvement.
   - What do Darwin Gödel Machine (arXiv 2505.22954), the Self-Improving Coding Agent (SICA, arXiv 2504.15228) and STOP (arXiv 2310.02304) report about safeguards?
   - Examples: fixed benchmarks as evaluators, sandboxing, human oversight, reward or objective hacking seen in practice.
4. H6: multi-agent failure modes.
   - What does "Why Do Multi-Agent LLM Systems Fail?" (MAST, arXiv 2503.13657) report as the main failure categories and their shares?
   - Does it find that stronger verification or specification helps?
5. H1: text rules versus enforcement.
   - Is there primary evidence that agents follow instruction-file rules unreliably, and that hooks or gates are the documented fix?
   - A vendor doc statement counts, for example a docs line saying hooks are deterministic while instructions are not.
6. H3: small local coder models (7B).
   - What is the published pass rate of Qwen2.5-Coder-7B-Instruct on HumanEval or a similar benchmark?
   - What does its context length claim say?
   - Use the model card or the technical report (arXiv 2409.12186).

## Output format (the fixed check `python .coord/tasks/U99-R-check.py` reads it)

Write exactly one file, `.coord/notes/U99_uaos_rsi_research.md`, containing:
- A table with this header: `| id | hyp | finding | source | quote |`. It has one row per finding, and ids run R1, R2 and on. Each row has:
  - `hyp`: one of H1–H6.
  - `source`: one full https URL of a primary page.
  - `quote`: at most 25 words copied from that page.
- A section `## Verdicts` with exactly one line per hypothesis: `- H1: SUPPORTED|REFUTED|MIXED|UNKNOWN — one sentence citing row ids`. All six lines are required, even when the verdict is UNKNOWN.
- A section `## Not found`, listing what you looked for and could not source.

Rules:
- Never invent a number, a quote or a URL. A row you cannot source is left out.
- At most 12 rows.
- Keep it short. The cap is 200,000 tokens, and the last two Antigravity runs overran their caps by 10.5x and 1.8x.
- Then stop.


## Output

- Edit the files under `allow` directly with your file tools. Your reply is not applied: ===FILE / ===EDIT blocks in it are ignored. End with one line saying what you changed. Do not claim success; the acceptance command decides.
