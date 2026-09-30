# U95-R audit (judge: claude acting for Codex, 2026-09-30; mark for Codex re-review)

Run verdict: FAILED, not approvable.
- Cost: 3,136,806 paid tokens against the 300,000 cap (10.5x); 24.4M cache-read tokens. The budget rule rejects it.
- EXTERNAL_WRITE `_b`: caused by the judge (my mutation test copied a file to Git Bash `/tmp` = `%TEMP%` during the paid run), not by Antigravity. The file matched `dist/codex/AGENTS.md` and was deleted.
- Containment: Antigravity wrote `.coord/notes/U95_token_thrift_research.md` in the worktree instead of `.coord/stage/U95-R`. Follow-up card: stage escape for agy research runs.
- Fixed check `python .coord/tasks/U95-R-check.py`: PASS rows=25 (format only, not truth).

Use: rows are leads, usable only where the judge verified them below.

| Row | Source | Verdict |
| - | - | - |
| Q1-1 | code.claude.com/docs/en/prompt-caching.md | VERIFIED: `promptCacheTtl` / `CLAUDE_CODE_PROMPT_CACHE_TTL` take `5m` or `1h`; subagents use `subagentPromptCacheTtl`. |
| Q1-2 | same page | VERIFIED: a Claude subscription within plan usage gets a one-hour TTL for the main conversation by default; subagents and helpers get five minutes. Canon lever corrected (canon PR #10, commit f3f2ca3). |
| Q2-3 | learn.chatgpt.com/docs/config-file/config-reference.md (redirect from developers.openai.com) | VERIFIED names: `tool_output_token_limit`, `model_auto_compact_token_limit`, `project_doc_max_bytes`. No default is stated; whether the global `~/.codex/AGENTS.md` counts toward `project_doc_max_bytes` stays UNKNOWN. |
| Q3-2 | antigravity.google/docs/rules-workflows | UNVERIFIED: the page renders client-side; the fetch returned no text. Treat the 24,000 B and 20k-token limits as hypotheses. |
| Q5-1 | code.claude.com/docs/en/memory.md | VERIFIED: CLAUDE.md is context, not enforced configuration; use a PreToolUse hook to block an action. Supports runtime card U95-T. |

Recommendations not taken: any Codex config change (1h TTL, compaction thresholds, output limits) needs a U95-E A/B measurement with the cost meter before adoption; none is adopted from this run.
