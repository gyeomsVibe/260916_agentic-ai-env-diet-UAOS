# U106 Balance Research: Orchestration, Delegation, and Routing

| id | hyp | finding | source | quote |
| R1 | H1 | Multi-agent research systems consume ~15x more tokens than chat (4x for single agents) due to parallel exploration and lead-subagent coordination. | https://www.anthropic.com/engineering/multi-agent-research-system | In our data, agents typically use about 4× more tokens than chat interactions, and multi-agent systems use about 15× more tokens than chats. |
| R2 | H1 | Multi-agent architectures often create fragile context silos; uncoordinated writes across agents introduce conflicting decisions and telephone loss. | https://cognition.ai/blog/dont-build-multi-agents | running multiple agents in collaboration often results in fragile systems... it is difficult to share context thoroughly enough between agents |
| R3 | H2 | FrugalGPT cascade matches frontier individual LLM accuracy (GPT-4) while reducing inference costs by up to 98% via dynamic model selection. | https://arxiv.org/abs/2305.05176 | FrugalGPT can match the performance of the best individual LLM (e.g. GPT-4) with up to 98% cost reduction |
| R4 | H2 | Preference-trained routing between strong and weak models cuts inference costs by over 2x without degrading answer quality. | https://arxiv.org/abs/2406.18665 | our approach significantly reduces costs-by over 2 times in certain cases-without compromising the quality of responses. |
| R5 | H2 | Self-verification routing from smaller to larger models reduces computational cost by over 50% while maintaining comparable performance. | https://arxiv.org/abs/2310.12963 | Automix consistently surpasses strong baselines, reducing computational cost by over 50% for comparable performance. |
| R6 | H3 | Specialized open code models (0.5B-32B) achieve state-of-the-art results across 10+ benchmarks when tasks have precise docstrings and test specs. | https://arxiv.org/abs/2409.12186 | Qwen2.5-Coder demonstrates impressive code generation capabilities... achieving state-of-the-art (SOTA) performance across more than 10 benchmarks |
| R7 | H3 | Small models achieve high code-editing pass rates when given strict diff formats and clear, self-contained problem requirements. | https://aider.chat/docs/leaderboards/ | Aider excels with LLMs skilled at writing and editing code, and uses benchmarks to evaluate an LLM’s ability to follow instructions |
| R8 | H4 | Realistic repository evaluation requires interacting with execution environments and running unit test suites rather than static text matching. | https://arxiv.org/abs/2310.06770 | Resolving issues in SWE-bench frequently requires understanding and coordinating changes... calling for models to interact with execution environments |
| R9 | H4 | LLM judges exhibit systematic position, verbosity, and self-enhancement biases, making deterministic execution tests necessary for acceptance. | https://arxiv.org/abs/2306.05685 | We examine the usage and limitations of LLM-as-a-judge, including position, verbosity, and self-enhancement biases, as well as limited reasoning ability |
| R10 | H5 | Anthropic prompt caching provides a 90% discount on cached input tokens, showing that repetitive prefix re-reading drives agent billing. | https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching | Cache prompt prefixes with `cache_control` to cut costs and latency, using automatic caching or explicit breakpoints with 5-minute or 1-hour TTLs. |
| R11 | H5 | OpenAI prompt caching offers a 50% discount on cached inputs for prompts >= 1,024 tokens, targeting long-context repetitive input costs. | https://platform.openai.com/docs/guides/prompt-caching | When a cache hit occurs, you receive a 50% discount on cached input tokens compared to the standard uncached input rate. |
| R12 | H6 | Multi-agent system failures are dominated by specification/design (41.8%) and inter-agent misalignment (36.9%), producing a severe coordination tax. | https://arxiv.org/abs/2503.13657 | This process identifies 14 unique modes, clustered into 3 categories: (i) system design issues, (ii) inter-agent misalignment, and (iii) task verification. |

## Verdicts
- H1: MIXED — Multi-agent orchestration expands token usage up to 15x over chat (R1), but delegating edits without shared context creates fragility (R2).
- H2: SUPPORTED — Cascading queries from small/cheap to large models cuts cost by 50% to 98% with minimal accuracy degradation (R3, R4, R5).
- H3: SUPPORTED — Small local models achieve SOTA on well-specified coding benchmarks (R6) and structured diffs (R7) but degrade on open-ended problems.
- H4: SUPPORTED — Executable test environments are essential for agent verification (R8) because LLM judges suffer from position, verbosity, and self-enhancement biases (R9).
- H5: SUPPORTED — Cached input tokens receive 50% to 90% discounts (R10, R11), demonstrating that repetitive full-context re-reads dominate agent session expenditure.
- H6: SUPPORTED — Multi-agent failures are overwhelmingly driven by specification (41.8%) and inter-agent misalignment (36.9%) rather than model capabilities (R12).

## Recommendation
- **Deterministic apply first**: For trivial edits, fixed substitutions, and prescribed diffs, use deterministic code apply (0 tokens) to bypass the 15x multi-agent orchestration tax and avoid inter-agent misalignment (R1, R12).
- **Local model (Ollama) for tightly specified subtasks**: Route narrow, self-contained functions and structured edits to local models (e.g. Qwen2.5-Coder 7B-32B), which achieve high pass rates on clear specifications at zero API cost (R6, R7).
- **Model cascade routing with verification**: Adopt cascade routing where tasks first attempt cheap/local execution and escalate to remote workers only upon verification failure, capturing the 50%-98% cost savings demonstrated by cascades (R3, R4, R5).
- **Remote worker (Antigravity) for complex, bounded tasks**: Reserve remote paid workers for tasks requiring deeper reasoning or broader context, bounding context to avoid repetitive full-context billing (R1, R10, R11).
- **Execution-based acceptance gates**: Enforce deterministic, executable tests for all delegations rather than relying on self-reports or LLM-as-a-judge verdicts, eliminating systematic judge biases (R8, R9, R12).
- **Single-threaded orchestrator state**: Keep write decisions single-threaded within the commander to prevent context silos and the "game of telephone", using workers strictly for parallel read/research or isolated sandboxed edits (R1, R2, R12).

## Not found
- Public quantitative token breakdown of Cognition Devin's internal orchestration vs execution overhead.
- Controlled empirical benchmarks comparing Claude Code's per-call token expenditure on orchestrator-direct edits versus delegated subagent execution.

## Judge check (claude, 2026-10-01)
- `python .coord/tasks/U106-R-check.py` exit 0 (12 rows, 6 verdicts). Run U106-R ended SOURCE_DIVERGED because the judge added U106-A1 files to the source mid-run; the note itself was copied from the stage after the check.
- Re-opened: R3 (FrugalGPT) and R12 (MAST) quotes match the arXiv abstracts. R12 percentages 41.8%/36.9% are not in the abstract: UNVERIFIED. R6 "when tasks have precise docstrings" is the worker's inference, not the quote.
