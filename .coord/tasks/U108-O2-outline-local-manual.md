```contract
work_id: U108-O2
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

Edit only v7_harness/olla.py. Reply with ONE "===EDIT: v7_harness/olla.py===" header followed by ONE python fenced
block that holds, complete, each of the definitions below; each replaces the definition with the same name, and new
names are added. Do not output anything else from the file. The definitions named here are `OUTLINE_MAX_LINES`,
`DIGEST_PROMPT_VERSION`, `code_outline`, `digest_file`, `cmd_hook_read`, `_outline_note`, `shell_read_deny`.

1. New constant, exactly:

    OUTLINE_MAX_LINES = 60  # U108: enough to place every def of a 1,300-line module; keeps a deny short

2. Changed constant, exactly:

    DIGEST_PROMPT_VERSION = "2"  # U108: digests now start with the exact code outline

3. New function, exactly:

    def code_outline(path: Path) -> str:
        """U108: exact line ranges from the parser (Python) or headings (Markdown); "" when there is none."""
        import ast

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            lines: list[str] = []
            if path.suffix == ".py":
                try:
                    tree = ast.parse(text)
                except (SyntaxError, ValueError):
                    return ""
                funcs = (ast.FunctionDef, ast.AsyncFunctionDef)
                for node in tree.body:
                    if not isinstance(node, funcs + (ast.ClassDef,)):
                        continue
                    start = min([node.lineno] + [d.lineno for d in node.decorator_list])
                    kind = "class" if isinstance(node, ast.ClassDef) else "def"
                    lines.append(f"L{start}-{node.end_lineno}: {kind} {node.name}")
                    if isinstance(node, ast.ClassDef):
                        for m in node.body:
                            if isinstance(m, funcs):
                                mstart = min([m.lineno] + [d.lineno for d in m.decorator_list])
                                lines.append(f"L{mstart}-{m.end_lineno}: def {node.name}.{m.name}")
            elif path.suffix == ".md":
                lines = [f"L{i}: {line.strip()}" for i, line in enumerate(text.splitlines(), 1) if line.startswith("#")]
            else:
                return ""
        except OSError:
            return ""
        if len(lines) > OUTLINE_MAX_LINES:
            extra = len(lines) - (OUTLINE_MAX_LINES - 1)
            lines = lines[: OUTLINE_MAX_LINES - 1] + [f"... {extra} more"]
        return "\n".join(lines)

4. New function, exactly:

    def _outline_note(path: Path) -> str:
        outline = code_outline(path)
        return f"\nExact outline of {path.name}:\n{outline}" if outline else ""

5. `digest_file`: copy it from the current file unchanged, except replace its last line
       return header + "\n" + "\n".join(parts) + "\n", usage_total
   with these three lines:
       outline = code_outline(path)
       exact = f"## exact outline (from the parser)\n{outline}\n## local model notes\n" if outline else ""
       return header + "\n" + exact + "\n".join(parts) + "\n", usage_total

6. `cmd_hook_read`: copy it from the current file unchanged, except the line
       f"then Read with offset/limit. {hint}")}
   becomes
       f"then Read with offset/limit. {hint}" + _outline_note(Path(file)))}

7. `shell_read_deny`: copy it from the current file unchanged, except: right after the log_usage line add
       big = max(paths, key=lambda p: whole_read_tokens({"tool_input": {"file_path": str(p)}}))
   and add + _outline_note(big) right after the last string literal of the permissionDecisionReason value, before
   the closing }}) of the json.dumps call. Keep both string literals of that reason unchanged.

Do not edit tests. Do not touch any other definition.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
