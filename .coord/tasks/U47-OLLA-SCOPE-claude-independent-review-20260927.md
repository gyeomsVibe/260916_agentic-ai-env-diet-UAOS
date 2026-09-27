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

## Correction to finding 1 (17:05, measured) and follow-up bundle

- **Correction.** Finding 1 was wrong as stated. On the real main root (probe `.work/u47os/root_probe.py`, mocked
  embeddings), the current code does **not** error: top-down `os.walk` reaches the 300-candidate budget before the
  3,000 scan cap.
- **The real defect is result quality.** 289 of the 300 embedded candidates came from repository copies under
  `.coord/pilot` and `.claude/worktrees`, and 56 of the 61 directories entered were copies. A copy walked before the
  real files can still exhaust the scan cap.
- **Follow-up F1.** Prune the (parent, child) pairs `(.coord, pilot)` and `(.claude, worktrees)` before counting.
  - After the fix: 4 of 300 candidates come from copies, all from the small `.coord/pilot-r2` experiment, which is
    kept on purpose; 5 of 43 directories entered are copies.
  - A new red→green test confirms that an ordinary `src/pilot/` folder is still searched.
- **Line endings.** Codex's working copies had mixed line endings (CRLF 199 / LF 48 and 97 / 58), which the apply
  worker refuses (`MIXED_LINE_ENDINGS`). Both files were backed up to `.work/backup_20260927/u47os_f1/` and normalized
  to LF, matching HEAD. `git diff` sha256 was identical before and after (`b450ecd3…`).
- **Bundle.** Manual `.coord/tasks/U47-OLLA-SCOPE-F1-apply-manual.md`, bundle
  `da4162331555a91f11be9cf63568f096a211c48b96c096a6a80be65ce5c5fe82`, DRY_RUN acceptance exit 0 (11 tests), stage
  `.work/u47os_run4/stage/U47-OLLA-SCOPE-F1`.
- **Not applied.** The author is Claude, so the bundle waits for the independent codex judge. Apply command:
  `python -m v7_harness.cli pilot run --task U47-OLLA-SCOPE-F1 --worker apply --source . --work-dir .work/u47os_run4 --manual .coord/tasks/U47-OLLA-SCOPE-F1-apply-manual.md --approve da4162331555a91f11be9cf63568f096a211c48b96c096a6a80be65ce5c5fe82 --coord-actor codex`

- **F2 in the same bundle (finding 2).** Loop variables renamed (`filename`, `child`) so `call_tool` never rebinds
  `name`. A new AST test lists every rebinding of `name` in `call_tool`: red on the F1 version (`[60]`), green after.

## Scope and cost

- Reviewer edits: none to source. Wrote only this receipt and `.work/u47_olla_scope_claude_review/*`.
- Paid external calls: 0. Local model calls: 0. Probe plus tests: about 3 minutes wall time.
