"""U54: audit-only inventory of places in v7_harness that can run a command, and what feeds them (docs/49 U-SEC-1).

docs/49 called the tool execution firewall "partial" without a list of execution sites. A firewall added before
that list exists could guard the wrong call, so this module only reads code: it changes no behaviour.

Rule (fixed here; docs/50 is generated from it and never edited by hand):

Sites
- DIRECT: a call to subprocess.run / Popen / call / check_call / check_output, os.system, os.exec*, os.spawn*,
  through any import alias.
- INDIRECT: a call to a local name that is bound to one of those functions, either as a parameter default
  (`runner=subprocess.run`) or by assignment (`execute = runner or subprocess.run`). grep cannot see these.
- READ: a read of a model's `tool_calls` / `function_call` field (`x.get("tool_calls")`, `x["tool_calls"]`,
  `x.tool_calls`).

Source of the command (the first positional argument, or the `args=` / `cmd=` keyword, followed through simple
assignments and for-loop targets inside the same function):
- MODEL: it touches an identifier or string key containing one of MODEL_MARKERS, the names this code base uses for
  data a model proposed.
- CALLER: it depends on a parameter of the enclosing function (or `self`), but touches no model marker. Whether a
  caller can pass model output is a question for the gap review, so these are listed but not counted as gaps.
- FIXED: neither. The command comes from constants and module code.

Check
- GUARDED: a call whose name matches GUARD_RE runs earlier in the same function (a pilot allow list, a guard, a
  lint, a manual check).

Status
- FIXED sites are FIXED. MODEL or CALLER sites with a check are GUARDED. MODEL sites without one are GAP.
  CALLER sites without one are CALLER_INPUT. A READ is GAP when its function also holds a site, else PASS_THROUGH
  (the proposal is translated or counted there, not executed).

The markers and the guard pattern are a heuristic. They are named here so a reviewer can argue with them; the grep
cross-check in tests/test_u54_firewall_audit.py keeps an AST miss from shrinking the list silently.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

SUBPROCESS_FUNCS = frozenset({"run", "Popen", "call", "check_call", "check_output"})
OS_PREFIXES = ("exec", "spawn")
# Identifiers this code base uses for model-proposed actions (seen in gemini_shim.py, execution/engine.py, olla.py).
MODEL_MARKERS = ("tool_call", "function_call", "functioncall", "proposal", "model_output", "completion")
READ_KEYS = frozenset({"tool_calls", "function_call", "functionCall"})
GUARD_RE = re.compile(r"(allow|guard|forbid|policy|lint|permit|check_|_check|validate|verify|within)", re.IGNORECASE)
DOC_PATH = Path("docs") / "50_u54-tool-execution-firewall-gap-audit.md"


@dataclass(frozen=True)
class Site:
    path: str
    line: int
    kind: str
    callee: str
    source: str
    guarded: bool
    shell: bool
    status: str


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        inner = _dotted(node.value)
        return f"{inner}.{node.attr}" if inner else node.attr
    return ""


class _Imports(ast.NodeVisitor):
    """Maps local names to the module functions they stand for: `sp` -> subprocess, `run` -> subprocess.run."""

    def __init__(self) -> None:
        self.modules: dict[str, str] = {}
        self.funcs: dict[str, str] = {}

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name in ("subprocess", "os"):
                self.modules[alias.asname or alias.name] = alias.name

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module in ("subprocess", "os"):
            for alias in node.names:
                self.funcs[alias.asname or alias.name] = f"{node.module}.{alias.name}"


def _exec_target(node: ast.AST, imports: _Imports) -> str | None:
    """Return 'subprocess.run' etc. when the expression names an execution function, else None."""
    full = ""
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in imports.modules:
        full = f"{imports.modules[node.value.id]}.{node.attr}"
    elif isinstance(node, ast.Name) and node.id in imports.funcs:
        full = imports.funcs[node.id]
    if not full:
        return None
    module, _, func = full.partition(".")
    if module == "subprocess" and func in SUBPROCESS_FUNCS:
        return full
    if module == "os" and (func == "system" or func.startswith(OS_PREFIXES)):
        return full
    return None


def _names(node: ast.AST) -> set[str]:
    found: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            found.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            found.add(sub.attr)
        elif isinstance(sub, ast.Constant) and isinstance(sub.value, str) and len(sub.value) < 64:
            found.add(sub.value)
    return found


def _has_marker(names: set[str]) -> bool:
    return any(marker in name.lower() for name in names for marker in MODEL_MARKERS)


def _command_expr(call: ast.Call) -> ast.AST | None:
    if call.args:
        return call.args[0]
    for keyword in call.keywords:
        if keyword.arg in ("args", "cmd", "command"):
            return keyword.value
    return None


def _shell(call: ast.Call, imported: str) -> bool:
    if imported == "os.system":
        return True
    return any(k.arg == "shell" and not (isinstance(k.value, ast.Constant) and k.value.value is False)
               for k in call.keywords)


def _is_read(node: ast.AST) -> bool:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" and node.args:
        first = node.args[0]
        return isinstance(first, ast.Constant) and first.value in READ_KEYS
    if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load):  # `msg["tool_calls"] = x` builds, not reads
        key = node.slice
        return isinstance(key, ast.Constant) and key.value in READ_KEYS
    if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
        return node.attr in READ_KEYS
    return False


def _functions(tree: ast.Module) -> list[ast.AST]:
    """Every function, plus the module body as one pseudo-function for top-level code."""
    funcs: list[ast.AST] = [tree]
    funcs += [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    return funcs


def _own_nodes(func: ast.AST) -> list[ast.AST]:
    """Nodes of this function, not of functions nested inside it (they are audited on their own)."""
    out: list[ast.AST] = []
    stack = list(ast.iter_child_nodes(func))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        out.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return out


def _params(func: ast.AST) -> tuple[set[str], dict[str, ast.AST]]:
    if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return set(), {}
    a = func.args
    positional = a.posonlyargs + a.args
    names = {p.arg for p in positional + a.kwonlyargs}
    names |= {p.arg for p in (a.vararg, a.kwarg) if p is not None}
    defaults: dict[str, ast.AST] = {}
    for param, default in zip(positional[len(positional) - len(a.defaults):], a.defaults):
        defaults[param.arg] = default
    for param, default in zip(a.kwonlyargs, a.kw_defaults):
        if default is not None:
            defaults[param.arg] = default
    return names, defaults


def _audit_function(func: ast.AST, nodes: list[ast.AST], imports: _Imports, rel: str) -> list[Site]:
    params, defaults = _params(func)
    assigns: dict[str, set[str]] = {}
    for node in nodes:
        targets: list[ast.AST] = []
        value: ast.AST | None = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and node.value is not None:
            targets, value = [node.target], node.value
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            targets, value = [node.target], node.iter
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    for name in _names(item.optional_vars):
                        assigns.setdefault(name, set()).update(_names(item.context_expr))
        if value is None:
            continue
        for target in targets:
            for sub in ast.walk(target):
                if isinstance(sub, ast.Name):
                    assigns.setdefault(sub.id, set()).update(_names(value))

    # Local names bound to an execution function (INDIRECT sites).
    bound: dict[str, str] = {}
    for name, default in defaults.items():
        target = _exec_target(default, imports)
        if target:
            bound[name] = target
    for node in nodes:
        if isinstance(node, ast.Assign):
            for sub in ast.walk(node.value):
                target = _exec_target(sub, imports)
                if target:
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            bound[t.id] = target

    def closure(start: set[str]) -> set[str]:
        seen = set(start)
        frontier = list(start)
        while frontier:
            name = frontier.pop()
            for nxt in assigns.get(name, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    frontier.append(nxt)
        return seen

    guard_lines = sorted(n.lineno for n in nodes if isinstance(n, ast.Call) and GUARD_RE.search(_dotted(n.func) or ""))
    sites: list[Site] = []
    reads: list[int] = []
    for node in nodes:
        if _is_read(node):
            reads.append(node.lineno)
        if not isinstance(node, ast.Call):
            continue
        direct = _exec_target(node.func, imports)
        indirect = node.func.id if isinstance(node.func, ast.Name) and node.func.id in bound else None
        if not direct and not indirect:
            continue
        callee = direct or f"{indirect} -> {bound[indirect]}"
        expr = _command_expr(node)
        deps = closure(_names(expr)) if expr is not None else set()
        if _has_marker(deps):
            source = "MODEL"
        elif deps & (params | {"self"}):
            source = "CALLER"
        else:
            source = "FIXED"
        guarded = any(line <= node.lineno for line in guard_lines)
        if source == "FIXED":
            status = "FIXED"
        elif guarded:
            status = "GUARDED"
        else:
            status = "GAP" if source == "MODEL" else "CALLER_INPUT"
        sites.append(Site(rel, node.lineno, "DIRECT" if direct else "INDIRECT", callee, source, guarded,
                          _shell(node, direct or bound[indirect]), status))
    executes = bool(sites)  # decided before the reads are appended, so one read never turns the next into a GAP
    for line in sorted(set(reads)):
        sites.append(Site(rel, line, "READ", "tool_calls", "MODEL", False, False, "GAP" if executes else "PASS_THROUGH"))
    return sites


def audit_file(path: Path, root: Path) -> list[Site]:
    rel = path.relative_to(root).as_posix()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
    imports = _Imports()
    imports.visit(tree)
    sites: list[Site] = []
    for func in _functions(tree):
        sites += _audit_function(func, _own_nodes(func), imports, rel)
    return sites


def audit(root: Path, package: str = "v7_harness") -> list[Site]:
    root = Path(root)
    sites: list[Site] = []
    for path in sorted((root / package).rglob("*.py")):
        sites += audit_file(path, root)
    return sorted(set(sites), key=lambda s: (s.path, s.line, s.kind, s.callee))


def render(sites: list[Site]) -> str:
    counts: dict[str, int] = {}
    for site in sites:
        counts[site.status] = counts.get(site.status, 0) + 1
    lines = [
        "# 50. U54 도구 실행 방화벽 틈 감사 (Tool Execution Firewall Gap Audit)",
        "",
        "> 생성 파일(generated). 손으로 고치지 않는다. 다시 만들 때: "
        "`C:/Python314/python.exe -m v7_harness.firewall_audit --write`",
        "> 분류 규칙은 `v7_harness/firewall_audit.py` 맨 위 설명(docstring)에 고정돼 있다. 이 감사는 코드를 읽기만 하고 "
        "동작은 바꾸지 않는다(docs/49 U-SEC-1 1단계). 호출 지점을 막거나 바꾸는 일은 U54-S2의 별도 계약이다.",
        "",
        "## 읽는 법",
        "",
        "- 종류(kind): DIRECT는 `subprocess`·`os.system` 직접 호출, INDIRECT는 그 함수를 담은 지역 이름 호출"
        "(`runner=subprocess.run` 등, grep으로는 안 보인다), READ는 모델이 제안한 `tool_calls` 필드를 읽는 곳이다.",
        "- 출처(source): MODEL은 모델 제안 표식(marker) 이름이 명령에 닿는 경우, CALLER는 함수 인자에서 오는 경우, "
        "FIXED는 상수·모듈 코드에서만 오는 경우다.",
        "- 상태(status): GAP은 검사 없이 모델 제안이 실행될 수 있는 곳, CALLER_INPUT은 호출자가 무엇을 넘기느냐에 "
        "달린 곳(검토 대상), GUARDED는 같은 함수 안에서 먼저 검사가 도는 곳, PASS_THROUGH는 제안을 번역·집계만 하는 곳이다.",
        "",
        "## 요약",
        "",
        f"- 전체 지점: {len(sites)}",
    ]
    for status in ("GAP", "CALLER_INPUT", "GUARDED", "FIXED", "PASS_THROUGH"):
        lines.append(f"- {status}: {counts.get(status, 0)}")
    lines += ["", "## 전체 목록", "", "| 파일:줄 | 종류 | 호출 | 출처 | 검사 | shell | 상태 |", "|---|---|---|---|---|---|---|"]
    for s in sites:
        lines.append(f"| `{s.path}:{s.line}` | {s.kind} | `{s.callee}` | {s.source} | "
                     f"{'yes' if s.guarded else 'no'} | {'yes' if s.shell else 'no'} | {s.status} |")
    gaps = [s for s in sites if s.status == "GAP"]
    review = [s for s in sites if s.status == "CALLER_INPUT"]
    lines += ["", "## 틈(gaps): 검사 없이 모델 제안이 닿는 지점", ""]
    lines += [f"- `{s.path}:{s.line}` {s.kind} `{s.callee}`" for s in gaps] or ["- 없음"]
    lines += ["", "## 검토 대상(CALLER_INPUT): 호출자가 모델 출력을 넘기는지 사람이 확인할 지점", ""]
    lines += [f"- `{s.path}:{s.line}` {s.kind} `{s.callee}`" + (" (shell)" if s.shell else "") for s in review] or ["- 없음"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v7_harness.firewall_audit")
    parser.add_argument("--root", default=".")
    parser.add_argument("--write", action="store_true", help=f"write {DOC_PATH.as_posix()} instead of printing")
    args = parser.parse_args(argv)
    text = render(audit(Path(args.root)))
    if args.write:
        target = Path(args.root) / DOC_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))
        print(target.as_posix())
    else:
        sys.stdout.buffer.write(text.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
