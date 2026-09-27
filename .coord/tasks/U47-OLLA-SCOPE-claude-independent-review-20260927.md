# U47-OLLA-SCOPE — Claude independent review (reference evidence, 2026-09-27 ~17:10)

Reviewer: Claude (acting conductor while Codex is LIMITED). Author: Codex. This is **reference evidence, not a binding
verdict**; binding approval stays with Codex on return (PLAN row: `codex(작성) · claude(독립 검증)`).

Recommendation: **APPROVE-WITH-NOTES** (no defect against the contract; one usability counterexample and one latent
shadowing to fix in a follow-up, not blockers).

## Inputs reviewed

- Worktree `.work/u45_claude`, uncommitted Codex edits:
  - `v7_harness/olla_mcp.py` sha256 `7e969624249caa7875030602f91a566655f1de536013767034a402eb11db60d9`
  - `tests/test_u17_olla_mcp.py` sha256 `84895a738d870c9f7c804245ab34c9dee3ea1d6b4d7d7c039963f4df7979ca80`
- Contract `.coord/tasks/U47-OLLA-SCOPE-contract.md`; author receipt `U47-OLLA-SCOPE-review-receipt-20260927.md`.
- Diff scope: only those two files for this card (other dirty files belong to other cards).

## Fixed checks rerun by the reviewer

- `python -m unittest tests.test_u17_olla_mcp`: Ran 9, OK, 3 of 3 repeats.
- `python -m compileall -q v7_harness/olla_mcp.py`: exit 0.
- `git diff --check -- v7_harness/olla_mcp.py tests/test_u17_olla_mcp.py`: exit 0 (CRLF warnings only).
- `python -m unittest discover -s tests -t .`: Ran 971, OK (skipped=6), 149.8 s, exit 0. The worktree also carries
  other cards' uncommitted edits, so this proves no regression in the combined tree, not this card in isolation.

## Independent counterexamples (`.work/u47_olla_scope_claude_review/probe.py`, model-free, mocked `_embed`)

All 11 invalid folders returned `isError=true` with **0 `os.walk` calls and 0 `_embed` calls**:
`None`, `5` (int), `"  "`, `tests` (relative), `C:` (drive-relative), `C:\`, `C:/`, `C:\Windows\..` (resolves to
root), `\\localhost\C$\` (UNC root), missing path, a regular file.

Valid searches:
- 5,000 files under `.git` plus 2 real files: pruned before counting; `target.md` ranked first (0.707), no error.
- 3,001 non-text entries: `local_search scan limit reached: 3000 entries`, `isError=true`.

## Findings

1. **Usability counterexample (medium).** The scan cap counts entries after pruning. The main project root has
   25,025 non-pruned entries, of which 23,132 are under `.coord/pilot`. So `local_search` on the main project root now
   always errors, although the MCP instructions tell agents to search the project by meaning. This worktree has 841
   entries and works. The contract does allow an error at the cap, so this is **not a contract violation**.
   Follow-up options:
   - add `pilot` (or `.coord/pilot`) to the prune set;
   - or return partial top results with a truncation note instead of an error.
2. **Latent shadowing (low).** `for name in files:` in `call_tool` rebinds the tool-name parameter `name`. It is
   unreachable today, because every `local_search` path returns before `unknown tool: {name}`. Any future
   fall-through would still print a filename there. Fix: rename the loop variable to `filename`.
3. **Pre-existing (low, unchanged by this card).** A file-read `OSError`, such as a PermissionError, is reported as
   `local model unreachable`, which misleads the user.

## Scope and cost

- Reviewer edits: none to source. Wrote only this receipt and `.work/u47_olla_scope_claude_review/*`.
- Paid external calls: 0. Local model calls: 0. Probe plus tests: about 3 minutes wall time.
