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
