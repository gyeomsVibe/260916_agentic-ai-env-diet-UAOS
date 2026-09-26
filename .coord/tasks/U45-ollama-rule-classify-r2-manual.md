```contract
work_id: U45_LOCAL_RULE_CLASSIFY_R2
worker: local
goal: Normalize the ten provided catalog rows into sorted uppercase categories and counted rows in docs/research/U45-ollama-rule-classification.md.
inputs:
- .coord/PROJECT_MANUAL.md sha256=bebe9ed7a40600f64a008eeb643f1d4d38736ee7727fcc55cd0d9fa921871674
- .coord/tasks/U45-ollama-rule-classify-r2-instructions.md sha256=8abd8ceb9f33119a03cd227ca173d5d5ddb3818d67514284443f1ca1c4ac6269
- docs/research/U45-rule-catalog-input.txt sha256=4eaaa66ac609e9fea7f03d567d4bcba89a5f6ce7040a704b819a4ca624fc379b
- tests/accept_u45_ollama_classification.py sha256=f0302e444cc344a87e5481110a2c4ea390eb88c9e372254bd969fb449c10d776
allow:
- docs/research/U45-ollama-rule-classification.md
acceptance: python tests/accept_u45_ollama_classification.py
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

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


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
