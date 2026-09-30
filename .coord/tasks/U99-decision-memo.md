# U99 Decision Memo: Enforcing UAOS-RSI as Canonical Multi-Tool Operating System

- **Author**: Antigravity (acting deputy, completing U99 on behalf of conductor Claude Code)
- **Date**: 2026-09-30T22:09:00+09:00
- **Status**: COMPLETE (U99-R verified, U99-M merged via PR #73)
- **Reviewer owed**: Codex (upon return on 2026-10-04)

---

## 1. Decision: GO (Retain Canon v7.2.0 & Enforce via Code Gates)

We decide to **GO**:
1. **Retain UAOS-RSI (canon v7.2.0)** as the unified global operating system core for all three tools (Codex, Claude Code, Antigravity) with tool-specific adapters.
2. **Convert Text Rules to Deterministic Gates & Hooks**:
   - Pure textual guidelines are unreliably followed in long-context sessions (proven by U98-D and U99-M receipts).
   - Enforcement must occur at lifecycle boundaries (hooks, pre-tool gates, lint gates, and fixed test runners).

---

## 2. Hypothesis & Evidence Evaluation (U99-R Synthesis)

| Hypothesis | Status | Evidence & Rationale |
|---|---|---|
| **H1**: Rule text alone is followed unreliably; hooks/code gates are mandatory | **SUPPORTED** | Citations R11 (Claude PreToolUse hooks) & real receipts (U98-D delegation-first gate, U99-M mailbox delta hook). Text instructions failed to prevent conductor dictation or dropped relay letters until deterministic code intercepted them. |
| **H2**: Subscription limit accounting for prompt cache reads | **UNKNOWN** | Official API docs (R5, R6) confirm cache discounts and rate limits, but the exact multiplier/weight applied to 5-hour and weekly subscription limits remains publicly unstated. |
| **H3**: Local 7B coder executes mechanical spec-to-code reliably | **MIXED** | Qwen2.5-Coder-7B succeeds on tightly scoped specs (<=20 lines, concrete names) with fixed acceptance tests (U16, U22c, U94), but fails on large context prompts (>12K tokens) or ambiguous instructions (U21, U98-D L1). |
| **H4**: Distinct tool limits require shared core + adapters | **SUPPORTED** | R1-R4 prove Codex enforces 32 KiB instruction cap (`project_doc_max_bytes`), Claude uses hierarchical rules, Antigravity uses progressive disclosure. A single shared core with per-tool adapters matches all three. |
| **H5**: Safe self-improvement requires strict evidence gates | **SUPPORTED (Bounded)** | Literature (R7 Darwin Gödel Machine, R8 STOP, R9 SICA) confirms self-improving systems require mandatory sandboxing, immutable evaluators, and human merge approval to prevent objective hacking and escape. |
| **H6**: Multi-agent failures cluster into spec & verification | **SUPPORTED** | Empirical study MAST (R10) shows 14 failure modes across 7 frameworks cluster into system design, misalignment, and task verification, justifying UAOS contract manuals, mailbox protocols, and independent judges. |

---

## 3. Realized Deliverables under U99

1. **U99-R (Multi-Tool Research & Evidence Grounding)**:
   - Explored 12 evidence points (R1-R12) across literature, primary documentation, and real ledger logs.
   - Claude verified 3 primary sources and 5 direct citations (R1, R2, R7, R10, R11).
2. **U99-M (Mailbox Delta Hook Session Isolation & Message Body Display)**:
   - Resolved multi-session cursor race condition by isolating cursor files per session (`cursor_for(session_id)`).
   - Resolved missing relay letter text by surfacing `body.get("message")`.
   - Verified 4/4 fixed acceptance tests (`tests/test_u99m_mailbox_delta.py`) and 1,287 full repository regression tests (0 failures).
   - Pushed `claude/u99-mailbox`, opened PR #73, and merged into `main` (commit `568d8e9`).

---

## 4. Next Priorities (Handover to Returning Conductor)

1. Keep `claude -p` / `coord watch` armed for reactive non-polling wakeups (0 paid tokens).
2. Next cards should target remaining friction points:
   - Bounded prompt sizes for local Ollama calls (`local_worker` prompt clamp).
   - Automated card cost telemetry during active runs.
