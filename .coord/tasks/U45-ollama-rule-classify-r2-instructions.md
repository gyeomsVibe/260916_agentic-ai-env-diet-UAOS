# U45 Ollama mechanical process manual R2

Full project constraints in this call: work_id U45; Codex is owner and judge; Ollama has no design, approval, or verdict authority; no deletion, network, push, deploy, credential or permission change; edit only the allowed output; stop on malformed output or timeout.

The complete source data is below. Do not invent or omit lines.

```text
role_claude|deputy-only-after-codex-unavailable
common|contract-before-delegation
role_antigravity|third-line-authority
common|no-quota-percent-to-token-conversion
role_codex|independent-final-verdict
common|retention-never-deletes
role_claude|no-self-judgment
common|unknown-fails-closed
role_antigravity|handoff-for-return-review
role_codex|review-deputy-evidence-on-return
```

Create `docs/research/U45-ollama-rule-classification.md`. The first line is `# U45 mechanical rule classification`. Uppercase each category, sort categories alphabetically, and sort values alphabetically within each category. Write each data line as `CATEGORY|value`. The final line is `COUNTS|` followed by lowercase category counts in the same sorted category order, separated by one space, for example `common=4`. No blank lines, prose, code fences, placeholders, or extra punctuation.
