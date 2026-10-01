```contract
work_id: U106-R
worker: agy
goal: Primary-source web research on the balance between orchestration and task work, and cost routing across commander, remote worker and local model; sourced table, one verdict per H1-H6, recommendation.
inputs:
- .coord/tasks/U106-frame.md sha256=7922cf93a6ccee6101fb98e89a3883c00ea240aacac6b12548473616ffd1ea9b
- .coord/tasks/U106-R-check.py sha256=b0155eef578be354bf60de11d1d9492fc5a325a51f0d6fab7d12ae8c5a11b37d
allow:
- .coord/notes/U106_balance_research.md
acceptance: python .coord/tasks/U106-R-check.py
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 1800
remote_budget_tokens: 1500000
```

## Instructions for the worker

## Why

Read `.coord/tasks/U106-frame.md` first: the decision, measured facts and hypotheses H1-H6. The user's verdict: the operating system (UAOS-RSI) spent its budget building itself, Antigravity and Ollama were barely used, and "token-thrift" was the default mode in name only. We need primary evidence for how to balance orchestration against task work and how to route work across a paid commander, a paid remote worker and a free local model.

## Where to write

Your workspace is the staging copy `.coord/stage/U106-R` of the source. Write exactly one file inside it: `.coord/notes/U106_balance_research.md`. Any write outside the staging copy (source tree, temp, home) fails the run.

## Task: deep web research on primary sources, at most 12 rows

Priority order; stop at 12 rows or the budget:
1. H1: Anthropic "How we built our multi-agent research system" (token multiples vs single agent and chat), Cognition "Don't Build Multi-Agents", any measurement of orchestration token share.
2. H2: FrugalGPT (arXiv 2305.05176), RouteLLM (arXiv 2406.18665), AutoMix or other cascade/router papers: cost reduction and quality numbers.
3. H3: small local code model results on specified vs underspecified tasks (e.g. Qwen2.5-Coder technical report arXiv 2409.12186, Aider leaderboards, any study on prompt specificity and small-model success).
4. H4: evidence that execution-based tests beat self-reports or LLM judges for accepting agent code (SWE-bench / agent papers, "LLM judges unreliable" studies).
5. H5: prompt caching docs (Anthropic, OpenAI, Google) on cached input pricing/limits, and any evidence that context size per call dominates agent cost.
6. H6: MAST (arXiv 2503.13657) failure shares for specification/coordination; practitioner guidance (Anthropic "Building effective agents") on keeping the simplest orchestrator-worker setup.

## Output format (checked by `python .coord/tasks/U106-R-check.py`)

- Table header `| id | hyp | finding | source | quote |`; ids R1, R2, ...; `hyp` one of H1-H6; `source` one full https URL of a primary page; `quote` at most 25 words copied from it.
- Section `## Verdicts` with exactly one line per hypothesis: `- H1: SUPPORTED|REFUTED|MIXED|UNKNOWN — one sentence citing row ids`. All six lines required.
- Section `## Recommendation` with at most 6 bullets: a concrete routing/balance rule for UAOS-RSI derived only from your rows (cite row ids), e.g. which work goes to deterministic apply, Ollama, Antigravity, and the commander.
- Section `## Not found`.

Rules: never invent a number, quote or URL; leave unsourced rows out; at most 12 rows; keep it short; then stop.


## Output

- Edit the files under `allow` directly with your file tools. Your reply is not applied: ===FILE / ===EDIT blocks in it are ignored. End with one line saying what you changed. Do not claim success; the acceptance command decides.
