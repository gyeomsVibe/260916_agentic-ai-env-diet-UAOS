```contract
work_id: U109-S
worker: local
goal: New pure module def_splice.py: splice whole Python definitions by name so Ollama's natural edit shape becomes a file deterministically
inputs:
- tests/test_u109_def_splice.py sha256=173d5b7dcd414dc9152e6ebe91a797cb79cb35952e547d1da773d4e5bab2310c
allow:
- v7_harness/adapters/def_splice.py
context_allow:
- tests/test_u109_def_splice.py
acceptance: python -m unittest tests.test_u109_def_splice
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Create ONE new file `v7_harness/adapters/def_splice.py` (about 90 lines). Standard library only (`ast`, `textwrap`).

Start the file with:
"""U109: splice whole Python definitions by name, the edit shape a 7B model emits on its own (U107-B)."""
from __future__ import annotations

import ast
import textwrap

Write these functions exactly as described.

1. `def _start(node) -> int:` return `min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])` (1-based line of the first decorator or of the statement).

2. `def _reindent(block: list[str], col: int) -> list[str]:` return each line prefixed with `" " * col` when the line is not blank; blank lines stay "".

3. `def _parse(text: str, code: str):` try `ast.parse(text)`; on SyntaxError raise `ValueError(f"SPLICE_{code}:{exc.lineno}")` from exc.

4. `def _name(stmt) -> str | None:` for FunctionDef, AsyncFunctionDef, ClassDef return `stmt.name`; for Assign with exactly one target that is `ast.Name` return its `id`; for AnnAssign whose target is `ast.Name` return its `id`; else None.

5. `def splice_definitions(current: str, code: str) -> str:`
   - `lines = current.replace("\r\n", "\n").split("\n")`. If the last item is "" remove it (remember `ends = True`), else `ends = False`.
   - `snippet = textwrap.dedent(code.replace("\r\n", "\n")).strip("\n")`; `snip_lines = snippet.split("\n")`; `tree = _parse(snippet, "SYNTAX")`.
   - `_parse("\n".join(lines), "CURRENT")` once to check the current file parses.
   - For each `stmt` in `tree.body`, in order (re-parse the current text at the start of each step:
     `mod = _parse("\n".join(lines), "CURRENT")`):
     - `block = snip_lines[_start(stmt) - 1 : stmt.end_lineno]`.
     - If `stmt` is `ast.Import` or `ast.ImportFrom`: `text = "\n".join(block)`; if `text.strip()` equals
       `l.strip()` for any `l` in `lines`, continue. Otherwise find top-level imports in `mod.body`; if any, insert
       `block` after line `end_lineno` of the last one (`lines[last.end_lineno:last.end_lineno] = block`); if none,
       insert at index `mod.body[0].end_lineno` when `mod.body[0]` is a docstring
       (`isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant) and isinstance(b.value.value, str)`), else at 0.
     - Else `name = _name(stmt)`; if None raise `ValueError(f"SPLICE_UNSUPPORTED:{type(stmt).__name__}")`.
     - If `stmt` is FunctionDef/AsyncFunctionDef/ClassDef: `hits = [n for n in ast.walk(mod) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == name]`.
       Else (assignment): `hits = [n for n in mod.body if _name(n) == name and isinstance(n, (ast.Assign, ast.AnnAssign))]`.
     - If `len(hits) > 1`: raise `ValueError(f"SPLICE_AMBIGUOUS:{name}")`.
     - If `len(hits) == 1`: `hit = hits[0]`; `lines[_start(hit) - 1 : hit.end_lineno] = _reindent(block, hit.col_offset)`.
     - If no hit and it is a definition: insert `["", ""] + block + ["", ""]`  before the first top-level statement
       that is `ast.If` whose `ast.unparse(test)` is `__name__ == '__main__'`, at index `_start(that) - 1`;
       if there is no such guard, append `["", ""] + block` to the end of `lines`.
     - If no hit and it is an assignment: insert `block` before the first top-level def/class
       (index `_start(first) - 1`, followed by `["", ""]`); if there is none, append `block` at the end.
   - Before returning, strip runs of more than two blank lines created by insertion is NOT required; do not do it.
   - `out = "\n".join(lines) + ("\n" if ends else "")`; `_parse(out, "RESULT")`; return `out`.

Do not edit any other file. Do not add tests. No print statements.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
