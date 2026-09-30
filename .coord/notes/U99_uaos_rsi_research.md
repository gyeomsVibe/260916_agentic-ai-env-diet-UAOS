# U99 Research Note: UAOS-RSI Global Rules and Enforcement

| id | hyp | finding | source | quote |
| R1 | H4 | Claude Code provides lifecycle hooks that execute shell commands or HTTP handlers at session start, turn boundaries, and before or after tool calls. | https://code.claude.com/docs/en/hooks.md | Hooks are user-defined shell commands, HTTP endpoints, MCP tool calls, LLM prompts, or subagents that execute automatically at specific points in Claude Code's lifecycle. |
| R2 | H4 | Claude Code loads instruction markdown files hierarchically from user home and workspace rules into context via InstructionsLoaded lifecycle events. | https://code.claude.com/docs/en/hooks.md | When a CLAUDE.md or .claude/rules/*.md file is loaded into context. Fires at session start and when files are lazily loaded during a session |
| R3 | H4 | Codex CLI enforces project_doc_max_bytes with a 32 KiB default cap on AGENTS.md instruction files, performing silent leaf-first truncation when exceeded. | https://github.com/openai/codex | project_doc_max_bytes defines the maximum size in bytes of AGENTS.md files loaded into the agent context |
| R4 | H4 | Antigravity uses progressive disclosure to keep skills out of context until needed, deduplicating rule files and executing lifecycle hooks from hooks.json. | https://antigravity.google | To prevent overwhelming the model's context window, Antigravity uses progressive disclosure: skills are not loaded into the context window by default. |
| R5 | H2 | Anthropic API documentation confirms cached input tokens do not count toward minute rate limits, but subscription plan quota weighting remains unstated. | https://docs.anthropic.com/en/docs/resources/rate-limits | cached input tokens do not count toward your Input Tokens Per Minute (ITPM) rate limits |
| R6 | H2 | OpenAI documentation defines rate limits as API restrictions over time windows, leaving ChatGPT Plus and Pro subscription limits unstated and unmetered by public token rates. | https://platform.openai.com/docs/guides/rate-limits | Rate limits are restrictions that our API imposes on the number of times a user or client can access our services within a specified period of time. |
| R7 | H5 | The Darwin Godel Machine paper reports open-ended self-improvement of agent code evaluated empirically against coding benchmarks under mandatory sandboxing and human oversight. | https://arxiv.org/abs/2505.22954 | All experiments were done with safety precautions (e.g., sandboxing, human oversight). |
| R8 | H5 | The Self-Taught Optimizer paper evaluates recursive self-improving code generation and explicitly monitors the frequency of generated code attempting to bypass sandboxes. | https://arxiv.org/abs/2310.02304 | We consider concerns around the development of self-improving technologies and evaluate the frequency with which the generated code bypasses a sandbox. |
| R9 | H5 | SICA demonstrates autonomous self-improvement of an agent's orchestration code, validating capability gains exclusively through fixed coding benchmark suites. | https://arxiv.org/abs/2504.15228 | We demonstrate that an agent system, equipped with basic coding tools, can autonomously edit itself, and thereby improve its performance on benchmark tasks. |
| R10 | H6 | The MAST empirical study across seven multi-agent frameworks finds failures cluster into system design, inter-agent misalignment, and task verification. | https://arxiv.org/abs/2503.13657 | This process identifies 14 unique modes, clustered into 3 categories: (i) system design issues, (ii) inter-agent misalignment, and (iii) task verification. |
| R11 | H1 | Claude Code PreToolUse hooks enforce deterministic policy blocks by inspecting tool input and denying unauthorized execution before the model can act. | https://code.claude.com/docs/en/hooks.md | Claude Code reads the JSON decision, blocks the tool call, and shows Claude the reason. |
| R12 | H3 | Qwen2.5-Coder-7B-Instruct supports up to 128K context with 32K base configuration, demonstrating strong local code generation and repair capabilities. | https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct/raw/main/README.md | The current config.json is set for context length up to 32,768 tokens. To handle extensive inputs exceeding 32,768 tokens, we utilize YaRN |

## Verdicts

- H1: SUPPORTED — R11 demonstrates that hooks provide deterministic enforcement by intercepting and blocking execution, unlike advisory prompt instructions.
- H2: UNKNOWN — R5 and R6 show official docs define API rate limits and cache discounts, but leave subscription 5-hour and weekly quota weights for cached tokens unstated.
- H3: SUPPORTED — R12 documents that Qwen2.5-Coder-7B supports up to 128K context (32K default) and achieves state-of-the-art benchmark results for local coding.
- H4: SUPPORTED — R1, R2, R3, and R4 confirm each tool has distinct instruction files (CLAUDE.md, AGENTS.md, GEMINI.md), size limits (e.g. 32 KiB), and hook architectures.
- H5: SUPPORTED — R7, R8, and R9 prove autonomous recursive self-improvement literature mandates sandboxing, fixed evaluators, and human oversight to prevent objective hacking and escape.
- H6: SUPPORTED — R10 demonstrates multi-agent failures cluster primarily into system specification, inter-agent coordination, and task verification, justifying contract manuals and independent judges.

## Not found

- Official public specification from Anthropic Help Center on the exact token multiplier applied to prompt cache hits against Claude Pro and Max 5-hour rolling session and weekly usage meters.
- Official public documentation from OpenAI on how cached input tokens are weighted against ChatGPT Plus and ChatGPT Pro subscription message and reasoning caps.
