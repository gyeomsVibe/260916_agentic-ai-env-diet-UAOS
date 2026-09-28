"""U70: the deterministic route for "list what this Python file defines".

U67-O1b asked a local model for this list as JSON and got duplicates and an unusable format. The parser answers the
same question exactly, for zero model tokens, so a list of a Python file's symbols never needs a model at all.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path


def symbols(text: str) -> list[dict[str, object]]:
    """Top-level functions, classes (with their methods) and UPPER_CASE constants, in source order."""
    tree = ast.parse(text)
    rows: list[dict[str, object]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            rows.append({"kind": "function", "name": node.name, "line": node.lineno})
        elif isinstance(node, ast.ClassDef):
            rows.append({"kind": "class", "name": node.name, "line": node.lineno})
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    rows.append({"kind": "method", "name": f"{node.name}.{item.name}", "line": item.lineno})
        else:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(
                node, ast.AnnAssign) else []
            for target in targets:
                # Constants by the project's own convention: an UPPER_CASE module name.
                if isinstance(target, ast.Name) and target.id.isupper():
                    rows.append({"kind": "constant", "name": target.id, "line": node.lineno})
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="symbols", description="List a Python file's symbols without a model")
    parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    try:
        rows = symbols(args.path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        return 1
    print(json.dumps({"ok": True, "file": str(args.path), "symbols": rows}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
