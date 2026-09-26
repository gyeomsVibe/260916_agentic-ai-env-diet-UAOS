```contract
work_id: U45_LOCAL_RULE_CLASSIFY
worker: local
goal: Copy each exact rule bullet into the prescribed COMMON or ROLE row in docs/research/U45-ollama-rule-classification.md.
inputs:
- .coord/PROJECT_MANUAL.md sha256=bebe9ed7a40600f64a008eeb643f1d4d38736ee7727fcc55cd0d9fa921871674
- .coord/tasks/U45-ollama-rule-classify-instructions.md sha256=bb6889e9d2997439803b573d94b8faa955d370c9b383bd5c62c1dc57680e15ad
- uaos_everywhere/uaos_global_rule_block.md sha256=d0ea7ebf5d1f6e845fd1f352477adfb8b432b55fe08849561d0d6c2bffe962f4
- uaos_everywhere/adapters/codex.md sha256=4ab201dabbf2a644578cd22768a59a43287081daea1da65fcf75475c4cc65d6e
- uaos_everywhere/adapters/claude.md sha256=afb353dcc71ca9051723d1067ab55f1097948aae5199fce489524a8bf251dcee
- uaos_everywhere/adapters/antigravity.md sha256=d9d0e2618977234028a9616c240f4c172e9f4b24e1fecad9efad329d21479b16
- .work/u45_verify_ollama_classification.py sha256=a526089722919d7027ce1c25ca4cb9eff5984500f42497089353344f263e2a66
allow:
- docs/research/U45-ollama-rule-classification.md
acceptance: python .work/u45_verify_ollama_classification.py
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

# U45 Ollama mechanical process manual

The full project manual is part of this call:

- work_id: U45
- Goal: portable UAOS 0.3.0 with one common invariant block and three minimal role adapters.
- Owner/judge: Codex. Ollama has no design, approval, or verdict authority.
- Safety: no deletion, network, push, deploy, credentials, permissions, or edits outside allow.
- Stop: same-cause failure twice, input mismatch, malformed output, or timeout.

Perform one mechanical classification only. Read the four pinned Markdown inputs. Create `docs/research/U45-ollama-rule-classification.md` with exactly:

1. Heading `# U45 mechanical rule classification`.
2. One `COMMON | <exact bullet>` row for every bullet in `uaos_global_rule_block.md`, preserving source order and exact text.
3. Under headings `## codex`, `## claude`, `## antigravity`, one `ROLE | <exact bullet>` row for every bullet in the matching adapter, preserving source order and exact text.
4. Final line `COUNTS | common=<n> codex=<n> claude=<n> antigravity=<n>`.

Do not summarize, translate, rewrite, infer, or judge. The acceptance command compares every row with the source.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
