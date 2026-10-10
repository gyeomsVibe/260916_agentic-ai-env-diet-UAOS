"""Work manuals as contracts: checked before a delegated run, enforced during it (U34).

A manual is one markdown file. It starts with a fenced ```contract block of `key: value` lines, followed by
free prose instructions for the worker. The pilot sends the whole file as the prompt (the content, never a path),
so the contract the harness enforces and the text the worker reads cannot drift apart.

Why a checker: the four-tool rules require every Ollama/Antigravity call to carry a manual with a work id, one goal,
pinned inputs, allowed files, forbidden actions, limits, an acceptance command, stop conditions and a judge. Those
manuals were prose, so nothing checked them, and the "allowed files" line was never enforced (a worker could change
any file and still pass). Every check here is deterministic and costs no model tokens.

    ```contract
    work_id: U35_EXAMPLE
    worker: local            # local | apply | agy | lane | cascade
    goal: Replace TIMEOUT = 30 with TIMEOUT = 60 in `pkg/config.py`.
    inputs:
    - pkg/config.py sha256=<64 hex>
    allow:
    - pkg/config.py
    acceptance: python -m unittest tests.test_config
    forbidden: design changes, edits outside allow, editing tests
    stop: two failures with the same cause; input hash mismatch
    judge: codex              # codex | claude | antigravity — never the worker's own tool, never ollama
    timeout_s: 180
    remote_budget_tokens: 0   # >0 only when a cascade may escalate to the paid remote worker
    ```
"""

from __future__ import annotations

import hashlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

CONTRACT_RE = re.compile(r"^```contract[ \t]*\r?\n(?P<body>.*?)^```", re.M | re.S)
REQUIRED = ("work_id", "worker", "goal", "inputs", "allow", "acceptance", "forbidden", "stop", "judge", "timeout_s")
# U50: context_allow is optional; without it a list key would swallow its "- " items into the previous list.
LIST_KEYS = ("inputs", "allow", "context_allow")
WORKERS = ("local", "apply", "agy", "lane", "cascade", "claude")
# Workers that spend a paid account (B85). lane runs Claude Code on the local model, so it is not one of them.
REMOTE_WORKERS = ("agy", "claude")
JUDGES = ("codex", "claude", "antigravity", "user")
# Workers that edit files with their own tools. The harness reads the staged files, never their reply text, so
# telling them to reply with blocks makes them change nothing (U44 probe: NO_CHANGES on the first real claude run).
TOOL_WORKERS = ("agy", "lane", "claude")
# The tool that does the work cannot be the one that accepts it.
WORKER_TOOL = {"agy": "antigravity", "lane": "claude", "claude": "claude"}
MAX_TIMEOUT_S = 3600
# docs/24·docs/30: a local model gets a manual that scores at least 80 for concreteness.
LOCAL_MIN_SPECIFICITY = 80
REMOTE_MIN_SPECIFICITY = 60
SHA_RE = re.compile(r"sha256[=:]\s*([0-9a-fA-F]{64})")


@dataclass
class ManualReport:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    contract: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "errors": self.errors, "warnings": self.warnings, "contract": self.contract}


def parse_contract(text: str) -> dict[str, Any] | None:
    match = CONTRACT_RE.search(text)
    if match is None:
        return None
    contract: dict[str, Any] = {}
    current_list: str | None = None
    for raw in match.group("body").splitlines():
        # A comment needs two spaces before "#", so "issue #12" inside a goal survives.
        line = re.sub(r"\s{2,}#.*$", "", raw).rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.startswith("- ") and current_list is not None:
            contract[current_list].append(stripped[2:].strip())
            continue
        key, sep, value = stripped.partition(":")
        if not sep:
            continue
        key = key.strip().lower()
        value = value.strip()
        if key in LIST_KEYS:
            contract[key] = [item.strip() for item in value.split(",") if item.strip()] if value else []
            current_list = key
        else:
            contract[key] = value
            current_list = None
    return contract


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_relative(item: str) -> bool:
    candidate = item.replace("\\", "/")
    return bool(candidate) and not candidate.startswith("/") and ".." not in PurePosixPath(candidate).parts \
        and not re.match(r"^[A-Za-z]:", candidate)


def related_tests(project: Path, allow: list[str]) -> list[str]:
    """Test modules that import an allowed .py file. P08's acceptance ran one new test and missed that
    tests/test_u15_coord_cli.py covered the command the worker deleted."""
    modules = []
    for item in allow:
        path = PurePosixPath(item.replace("\\", "/"))
        if path.suffix == ".py" and not path.name.startswith("test_") and "*" not in item:
            modules.append(".".join(path.with_suffix("").parts))
    tests_dir = Path(project) / "tests"
    if not modules or not tests_dir.is_dir():
        return []
    found = []
    for test in sorted(tests_dir.glob("test_*.py")):
        try:
            text = test.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if any(re.search(rf"\b{re.escape(module)}\b", text) for module in modules):
            found.append(f"tests.{test.stem}")
    return found


def lint(text: str, project: Path) -> ManualReport:
    from v7_harness.adapters.ollama_worker import dictated_paths
    from v7_harness.adapters.worker_advice import VAGUE_TERMS, advise

    project = Path(project)
    report = ManualReport(ok=False)
    contract = parse_contract(text)
    if contract is None:
        report.errors.append("NO_CONTRACT: the manual needs a ```contract block (see v7_harness/manual.py)")
        return report
    report.contract = contract

    for key in REQUIRED:
        value = contract.get(key)
        if value in (None, "", []):
            report.errors.append(f"MISSING:{key}")

    worker = contract.get("worker", "")
    judge = contract.get("judge", "").lower()
    if worker in ("local", "cascade"):
        from v7_harness.adapters.ollama_worker import preflight

        problem = preflight(text, project)  # U177: the author learns before a run that the model would not be called
        if problem:
            report.warnings.append(f"LOCAL_{problem}")
    if worker and worker not in WORKERS:
        report.errors.append(f"UNKNOWN_WORKER:{worker}")
    if judge and judge not in JUDGES:
        report.errors.append(f"JUDGE_NOT_ALLOWED:{judge} (Ollama and the worker never judge)")
    if worker in WORKER_TOOL and judge == WORKER_TOOL[worker]:
        report.errors.append(f"SELF_JUDGE:{judge} cannot accept work done by --worker {worker}")

    goal = contract.get("goal", "")
    vague = [term for term in VAGUE_TERMS if term in goal.lower()]
    if vague:
        report.errors.append(f"VAGUE_GOAL:{','.join(vague)}")
    if len(goal) > 400:
        report.errors.append("GOAL_TOO_LONG: one goal, one sentence")

    # U70: a task type names what the local model is asked to do, so the pilot can check its qualification first.
    task_type = contract.get("task_type", "")
    if task_type:
        from v7_harness.model_qualification import TASK_TYPES

        if task_type not in TASK_TYPES:
            report.errors.append(f"UNKNOWN_TASK_TYPE:{task_type} (known: {', '.join(TASK_TYPES)})")

    for item in contract.get("inputs", []):
        rel = item.split()[0] if item.split() else ""
        pinned = SHA_RE.search(item)
        target = project / rel
        if not _safe_relative(rel):
            report.errors.append(f"INPUT_ESCAPE:{rel}")
        elif not target.is_file():
            report.errors.append(f"INPUT_MISSING:{rel}")
        elif pinned is None:
            report.errors.append(f"INPUT_UNPINNED:{rel} (add sha256=<hex>)")
        elif pinned.group(1).lower() != _sha256(target):
            report.errors.append(f"INPUT_HASH_MISMATCH:{rel}")

    allow = contract.get("allow", [])
    for item in allow:
        if not _safe_relative(item) or item.strip() in ("*", "**"):
            report.errors.append(f"ALLOW_TOO_WIDE:{item}")
    # U50: a wildcard list would admit the whole workspace and undo the gate.
    for item in contract.get("context_allow", []):
        if not _safe_relative(item) or item.strip().replace("\\", "/") in ("*", "**", "*/", "**/", "**/*"):
            report.errors.append(f"CONTEXT_ALLOW_TOO_WIDE:{item}")

    try:
        timeout = int(contract.get("timeout_s", ""))
        if not 0 < timeout <= MAX_TIMEOUT_S:
            raise ValueError
    except ValueError:
        if contract.get("timeout_s"):
            report.errors.append(f"TIMEOUT_INVALID:{contract.get('timeout_s')}")
    budget_raw = contract.get("remote_budget_tokens", "0") or "0"
    try:
        budget = int(budget_raw)
        if budget < 0:
            raise ValueError
    except ValueError:
        budget = 0
        report.errors.append(f"BUDGET_INVALID:{budget_raw}")
    if worker == "cascade" and budget <= 0:
        report.errors.append("CASCADE_WITHOUT_BUDGET: set remote_budget_tokens or use worker: local")
    if worker in REMOTE_WORKERS and budget <= 0:
        # B85: an agy run with no budget spent 655,207 tokens and nothing compared it with anything.
        report.errors.append(f"REMOTE_WITHOUT_BUDGET: worker {worker} needs remote_budget_tokens > 0")
    if worker == "claude":
        # Codex audit: a pre-spend cap (`claude --max-budget-usd`). The token gate only acts after the money is spent.
        usd_raw = str(contract.get("remote_budget_usd") or "")
        try:
            usd = float(usd_raw) if usd_raw else 0.0
        except ValueError:
            usd = -1.0
        if usd <= 0 or usd != usd:
            report.errors.append("REMOTE_WITHOUT_USD_CAP: worker claude needs remote_budget_usd > 0")

    blocks = dictated_paths(text)
    if worker == "apply" and not blocks:
        report.errors.append("NO_BLOCKS_FOR_APPLY: worker apply needs ===FILE/===EDIT blocks in the manual")
    from v7_harness.delegation import delegate_first_errors, local_first_errors
    report.errors.extend(delegate_first_errors(text, contract, project))
    report.errors.extend(local_first_errors(contract, project))  # U106: Ollama first for code work
    if blocks and allow:
        from v7_harness.isolation.errors import ScopeExpansionError
        from v7_harness.isolation.security import check_scope_confinement

        for path in blocks:
            try:
                check_scope_confinement(path, allow)
            except ScopeExpansionError:
                report.errors.append(f"BLOCK_OUTSIDE_ALLOW:{path}")
    if blocks and worker in ("local", "cascade"):
        report.warnings.append("DICTATION: the manual already contains the exact code, so the delegate only copies it; give it a spec instead (U98-D)")

    # A forbidden line such as "no refactoring" names vague words on purpose; it must not lower the score.
    specificity = advise(re.sub(r"(?m)^\s*forbidden:.*$", "", text)).specificity
    # The thresholds can only tighten through an adopted RSI policy (floors 80/60 are enforced in v7_harness.rsi).
    from v7_harness.rsi import load_policy

    policy = load_policy(project)
    local_min = max(LOCAL_MIN_SPECIFICITY, int(policy["local_min_specificity"]))
    remote_min = max(REMOTE_MIN_SPECIFICITY, int(policy["remote_min_specificity"]))
    if worker in ("local", "cascade") and specificity < local_min:
        report.errors.append(f"LOW_SPECIFICITY:{specificity}<{local_min} for a local model")
    elif worker in ("agy", "lane") and specificity < remote_min:
        report.warnings.append(f"LOW_SPECIFICITY:{specificity}<{remote_min}")

    covering = related_tests(project, allow)
    acceptance = contract.get("acceptance", "")
    missing = [module for module in covering if module not in acceptance and "discover" not in acceptance]
    if missing:
        report.warnings.append(f"RELATED_TESTS_NOT_IN_ACCEPTANCE:{' '.join(missing[:6])}")

    report.ok = not report.errors
    return report


def new_manual(
    project: Path,
    *,
    work_id: str,
    worker: str,
    goal: str,
    inputs: list[str],
    allow: list[str],
    acceptance: str,
    judge: str,
    timeout_s: int = 180,
    remote_budget_tokens: int = 0,
    remote_budget_usd: float = 0.0,
    forbidden: str = "design changes; edits outside allow; editing or deleting tests; network; commit/push",
    stop: str = "two failures with the same cause; input hash mismatch; no output",
    instructions: str = "",
    context_allow: list[str] | None = None,
    paid_after: str = "",
    paid_reason: str = "",
) -> str:
    """A manual skeleton with the input hashes computed now, so the worker is pinned to these exact bytes."""
    project = Path(project)
    pinned = [f"- {rel} sha256={_sha256(project / rel)}" for rel in inputs]
    lines = [
        "```contract",
        f"work_id: {work_id}",
        f"worker: {worker}",
        f"goal: {goal}",
        "inputs:",
        *pinned,
        "allow:",
        *[f"- {item}" for item in allow],
        *(["context_allow:", *[f"- {item}" for item in context_allow]] if context_allow is not None else []),
        f"acceptance: {acceptance}",
        f"forbidden: {forbidden}",
        f"stop: {stop}",
        f"judge: {judge}",
        f"timeout_s: {timeout_s}",
        f"remote_budget_tokens: {remote_budget_tokens}",
        *([f"remote_budget_usd: {remote_budget_usd:g}"] if remote_budget_usd > 0 else []),
        *([f"paid_after: {paid_after}"] if paid_after else []),
        *([f"paid_reason: {paid_reason}"] if paid_reason else []),
        "```",
        "",
        "## Instructions for the worker",
        "",
        instructions or "- Change only the files under `allow`. Keep every other line byte-identical.",
        "",
        "## Output",
        "",
        output_rule(worker),
        "",
    ]
    return "\n".join(lines)


def output_rule(worker: str) -> str:
    if worker in TOOL_WORKERS:
        return ("- Edit the files under `allow` directly with your file tools. Your reply is not applied: ===FILE / "
                "===EDIT blocks in it are ignored. End with one line saying what you changed. Do not claim success; "
                "the acceptance command decides.")
    return "- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides."


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Lint a work manual")
    parser.add_argument("manual")
    parser.add_argument("--source", default=".")
    args = parser.parse_args(argv)
    report = lint(Path(args.manual).read_text(encoding="utf-8"), Path(args.source))
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
