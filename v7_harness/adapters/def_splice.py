"""U109: splice whole Python definitions by name, the edit shape a 7B model emits on its own (U107-B)."""
from __future__ import annotations

import ast
import textwrap

def _start(node) -> int:
    return min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])

def _reindent(block: list[str], col: int) -> list[str]:
    return [f"{' ' * col}{line}" if line else "" for line in block]

def _parse(text: str, code: str):
    try:
        return ast.parse(text)
    except SyntaxError as exc:
        raise ValueError(f"SPLICE_{code}:{exc.lineno}") from exc

def _name(stmt) -> str | None:
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return stmt.name
    elif isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
        return stmt.targets[0].id
    elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
        return stmt.target.id
    return None

def splice_definitions(current: str, code: str) -> str:
    lines = current.replace("\r\n", "\n").split("\n")
    if lines and not lines[-1]:
        lines.pop()
        ends = True
    else:
        ends = False
    snippet = textwrap.dedent(code.replace("\r\n", "\n")).strip("\n")
    snip_lines = snippet.split("\n")
    tree = _parse(snippet, "SYNTAX")
    _parse("\n".join(lines), "CURRENT")
    for stmt in tree.body:
        block = snip_lines[_start(stmt) - 1 : stmt.end_lineno]
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            text = "\n".join(block)
            if any(text.strip() == l.strip() for l in lines):
                continue
            hits = [n for n in ast.walk(_parse("\n".join(lines), "CURRENT")) if isinstance(n, (ast.Import, ast.ImportFrom))]
            if hits:
                lines[hits[-1].end_lineno : hits[-1].end_lineno] = block
            elif any(isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str) for n in _parse("\n".join(lines), "CURRENT").body):
                lines[_parse("\n".join(lines), "CURRENT").body[0].end_lineno : _parse("\n".join(lines), "CURRENT").body[0].end_lineno] = block
            else:
                lines[:0] = block
        else:
            name = _name(stmt)
            if name is None:
                raise ValueError(f"SPLICE_UNSUPPORTED:{type(stmt).__name__}")
            defs = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            mod = _parse("\n".join(lines), "CURRENT")
            if isinstance(stmt, defs):
                hits = [n for n in ast.walk(mod) if isinstance(n, defs) and n.name == name]
            else:  # U109-S3: a constant matches only a module-level assignment of the same name
                hits = [n for n in mod.body if isinstance(n, (ast.Assign, ast.AnnAssign)) and _name(n) == name]
            if len(hits) > 1:
                raise ValueError(f"SPLICE_AMBIGUOUS:{name}")
            if len(hits) == 1:
                hit = hits[0]
                lines[_start(hit) - 1 : hit.end_lineno] = _reindent(block, hit.col_offset)
            elif isinstance(stmt, defs):
                guards = [n for n in mod.body if isinstance(n, ast.If) and ast.unparse(n.test) == "__name__ == '__main__'"]
                if guards:
                    at = _start(guards[0]) - 1
                    lines[at:at] = ["", ""] + block + ["", ""]
                else:
                    lines.extend(["", ""] + block)
            else:  # a new constant goes above the first definition, next to the other constants
                firsts = [n for n in mod.body if isinstance(n, defs)]
                at = _start(firsts[0]) - 1 if firsts else len(lines)
                lines[at:at] = block + (["", ""] if firsts else [])
    out = "\n".join(lines) + ("\n" if ends else "")
    _parse(out, "RESULT")
    return out
