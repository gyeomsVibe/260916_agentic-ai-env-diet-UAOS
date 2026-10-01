```contract
work_id: U108-O
worker: local
goal: Exact ast/heading outline of a file: digest_file starts with it and the whole-read denies (Read hook and shell) carry it, so a refused tool opens the right lines next call
inputs:
- v7_harness/olla.py sha256=ea6f3916257c16c1c9d6ffdd421157ff7671bf3e65dec2c68d06f89e2c7654a2
- tests/test_u108_map_first.py sha256=b1c1453adf331b6c0e9c210537235bea4d2f8c8f48c3aaba01a9538c20040e30
allow:
- v7_harness/olla.py
acceptance: python -m unittest tests.test_u108_map_first.OutlineTests tests.test_u17_olla tests.test_u17_olla_mcp tests.test_u103_olla_parity tests.test_u30_olla_evidence tests.test_u47_o3_guard_cleanup
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 1200
remote_budget_tokens: 0
```

## Instructions for the worker

Edit only `v7_harness/olla.py`. Reply with ONE `===EDIT: v7_harness/olla.py===` header followed by ONE ```python fenced
block that holds, complete, each of the definitions below; each replaces the definition with the same name, and new
names are added. Do not output anything else from the file.

1. New constant: `OUTLINE_MAX_LINES = 60  # U108: enough to place every def of a 1,300-line module; keeps a deny short`

2. Change the constant to: `DIGEST_PROMPT_VERSION = "2"  # U108: digests now start with the exact code outline`

3. New function `def code_outline(path: Path) -> str:` (uses `import ast` inside the function body):
   - `.py`: `text = path.read_text(encoding="utf-8", errors="replace")`; `tree = ast.parse(text)`; on SyntaxError or
     ValueError return "". For each node in `tree.body`: FunctionDef/AsyncFunctionDef -> line
     `f"L{start}-{node.end_lineno}: def {node.name}"`; ClassDef -> `f"L{start}-{node.end_lineno}: class {node.name}"`
     and then, for each FunctionDef/AsyncFunctionDef `m` in `node.body`,
     `f"L{mstart}-{m.end_lineno}: def {node.name}.{m.name}"`. `start` is
     `min([node.lineno] + [d.lineno for d in node.decorator_list])` (same for `mstart` with `m`).
   - `.md`: for each line number `i` (1-based) and line that starts with `#`: `f"L{i}: {line.strip()}"`.
   - Any other suffix: return "".
   - Keep at most OUTLINE_MAX_LINES lines; if more, keep the first OUTLINE_MAX_LINES - 1 and add
     `f"... {extra} more"`. Return `"\n".join(lines)`.
   - Wrap the whole body in `try:` ... `except OSError: return ""`.

4. `digest_file`: keep it exactly as now, except the return line becomes:
   `outline = code_outline(path)`
   `exact = f"## exact outline (from the parser)\n{outline}\n## local model notes\n" if outline else ""`
   `return header + "\n" + exact + "\n".join(parts) + "\n", usage_total`

5. `cmd_hook_read`: keep it exactly as now, except the deny reason string ends with
   `f"then Read with offset/limit. {hint}" + _outline_note(Path(file))` instead of `f"then Read with offset/limit. {hint}"`.

6. New function `def _outline_note(path: Path) -> str:`
   `outline = code_outline(path)`; return `f"\nExact outline of {path.name}:\n{outline}"` if outline else "".

7. `shell_read_deny`: keep it exactly as now, except: before the `return json.dumps(...)`, compute
   `big = max(paths, key=lambda p: whole_read_tokens({"tool_input": {"file_path": str(p)}}))`, and append
   `+ _outline_note(big)` to the permissionDecisionReason string (after `(\`sed -n 'A,Bp'\`)."`).

Do not edit tests. Do not touch any other function.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
