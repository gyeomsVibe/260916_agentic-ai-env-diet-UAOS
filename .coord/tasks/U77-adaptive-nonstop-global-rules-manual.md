# U77 adaptive nonstop global-rules contract

```contract
work_id: U77
worker: claude
model: claude-sonnet-4-6
goal: Critically review the proposed adaptive re-planning loop, internal-dependency classifier, terminal gate, and three-tool deployment plan without editing files.
inputs:
- shared/global-rules/core.md sha256=19191a6ce2e037693833a9b36edf6f143c62ff7ed9ebedf0d9f733f401a437fa
- shared/global-rules/GLOBAL_RULES.ko.md sha256=06aa222f3ae8ef93ef52bd3062a08ff68827754ef1b684f0270a1ad205f80a96
- shared/global-rules/VERSION sha256=fd0608acdc64617db30b1c7d67306388eb0c747dd9fb73e2ecaa99aaa58a3724
- shared/global-rules/history.md sha256=01a00cd17a8397bab4ef68e0c1b1eef5376aa9fa5c35eeac115712560048079c
- shared/global-rules/README.md sha256=aec1fd2e9f11473b5217d6ee01a5f4a2f7ffce65c23f8a4f67ec16513e8c8f4c
- shared/global-rules/scripts/sync-global-rules.ps1 sha256=613d8ae4d6e1c412785ed806187451edf915900f30529b9e5fe4ee1aacf15db4
allow:
- shared/global-rules/core.md
- shared/global-rules/GLOBAL_RULES.ko.md
- shared/global-rules/VERSION
- shared/global-rules/history.md
- shared/global-rules/README.md
- shared/global-rules/docs/adaptive-nonstop-control-loop.md
- shared/global-rules/tests/u77_adaptive_nonstop_check.py
- shared/global-rules/dist/antigravity/GEMINI.md
- shared/global-rules/dist/codex/AGENTS.md
- shared/global-rules/dist/claude/CLAUDE.md
acceptance: python shared/global-rules/tests/u77_adaptive_nonstop_check.py
forbidden: any file edit; editing frozen tests; network; delete; commit; push; PR; merge; deployment; self-approval
stop: ownership overlap; input hash mismatch; three failures with the same cause
judge: codex
timeout_s: 900
remote_budget_tokens: 20000
remote_budget_usd: 1.00
```

- work_id: U77
- status: ACTIVE
- goal: permanently install a three-tool control loop that re-plans when requirements, evidence, design, ownership, or tool availability changes, and that never turns internal agent work into user `remaining work`.
- exact inputs: the current `shared/global-rules/core.md`, Korean mirror, VERSION, history, README, sync script, generated distributions, and the user's 2026-09-28 failure example.
- source root: `D:/D_Workspace_NB/-agentic-ai-workspace/260718_agentic-ai-platform-optimization`.
- allowed files: `shared/global-rules/core.md`, `GLOBAL_RULES.ko.md`, `VERSION`, `history.md`, `README.md`, `docs/adaptive-nonstop-control-loop.md`, `tests/u77_adaptive_nonstop_check.py`, generated `dist/**`; runtime deployment targets are the three documented home rule files.
- forbidden actions: no remote push, PR, merge, deployment outside the three local rule files, deletion, secret access, permission weakening, or edits to frozen older tests.
- design contract: on material change run observe -> invalidate affected assumptions/cards -> update design and fixed acceptance -> publish a new hash-fixed manual -> execute one smallest dependency-ready step -> independent critique and red-team -> verify -> update ledger -> repeat.
- terminal gate: a turn may stop only for verified objective completion with zero internal dependencies, a necessary human-only boundary not already approved for this scope, or an external block after a durable handoff and zero-token watcher are armed.
- user-work classifier: Codex/Claude/Antigravity approval, worker completion, tests, builds, branch/commit/PR preparation, merge-link production, capacity recovery, and next READY cards are internal dependencies and must never appear as the user's `remaining work`.
- worker: deterministic Codex edit; Ollama is skipped because exact literal edits plus mechanical tests are cheaper to validate than model output.
- independent reviewer: Claude Code receives this full contract through `coord deliver` and returns CRITIC/SELFREFINE/REDTEAM findings only; Codex owns the binding verdict.
- acceptance: `python shared/global-rules/tests/u77_adaptive_nonstop_check.py`; `pwsh -File shared/global-rules/scripts/sync-global-rules.ps1 -Mode SourceCheck`; after Build/Apply, the same test plus `-Mode Check`; SHA-256 equality between each generated distribution and its live runtime target.
- stop condition: ownership overlap, input drift during edit, three same-cause failures, or an unapproved human-only action. Otherwise continue without a new user start command.
- budget: zero paid-worker tokens; deterministic reads, edits, builds, and tests only. Wall time and exits are recorded; savings remain UNMEASURED.
