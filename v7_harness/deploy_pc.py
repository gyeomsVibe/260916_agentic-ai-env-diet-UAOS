"""U41: one deterministic runner for everything that has to happen on the user's PC to finish the UAOS rollout.

The user asked for a non-stop rollout: the three tools' global rules deployed, commits made, pushes done, and no
task handed back to the user. None of these steps needs a model, so a script does them (0 tokens). Codex runs it;
if Codex is limited, Antigravity may run the same command. After it finishes, Antigravity does one budgeted,
read-only verification of the receipt (manual U41-A1).

Order (each step has a gate; the first failed gate stops the run and the receipt says where):
 1. bring this branch up to date (fetch + merge, never rebase)
 2. full regression            → exit 0
 3. installer --apply --no-rules (launcher, hooks, Claude scheduler deny)
 4. canon: find the three rule sources in the global-rules repository and add the *portable* UAOS block to them
 5. canon generator Build → SourceCheck → Apply → Check (sync-global-rules.ps1), each exit 0
 6. every runtime rule file (~/.claude/CLAUDE.md, ~/.codex/AGENTS.md, ~/.gemini/GEMINI.md) now holds the block
 7. installer --check --no-rules --portable --rules-file <canon sources> → exit 0
 8. 24/7 sentinel logon task (a refusal is a warning with advice, not a stop)
 9. with --push: commit and push the canon change, then commit this run's receipt and push this branch

Why the canon gets the block, not only the runtime files: the generator rewrites the runtime files and would drop a
block that the canon does not carry (B82). The block written to the canon is portable (no C:/Users/... path), because
the canon is a shared, pushed repository and the same text must work on every PC.

Dry run by default. `--apply` executes. Nothing asks the user anything.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .global_install import BLOCK_BEGIN, REPO_ROOT

BRANCH = "main"  # PR #1 merged the Claude branch; the rollout runs from main (--branch overrides)
PROJECT_DIR_NAME = "260916_agentic-ai-env-diet"
CANON_DIR_NAME = "260718_agentic-ai-platform-optimization"


def default_canon(repo: Path = REPO_ROOT) -> Path:
    """Resolve the fixed sibling canon from either the primary checkout or one of its managed worktrees."""
    resolved = Path(repo).resolve()
    for node in (resolved, *resolved.parents):
        if node.name == PROJECT_DIR_NAME:
            return node.parent / CANON_DIR_NAME
    return resolved.parent / CANON_DIR_NAME


DEFAULT_CANON = default_canon()
GENERATOR = Path("shared") / "global-rules" / "scripts" / "sync-global-rules.ps1"
CANON_SOURCE_ROOT = Path("shared") / "global-rules"
# Which canon file feeds which runtime. Exactly one match per runtime, or the run stops (CANON_SOURCES_AMBIGUOUS).
CANON_PATTERNS = {
    "claude": ("claude*.md",),
    # Codex and Antigravity are generated as core + adapter. The portable UAOS block belongs in the shared core
    # exactly once; putting it in each adapter duplicates the same rule lines in both generated runtimes.
    "codex": ("core.md",),
    "antigravity": ("core.md",),
}
# `adapters/` holds per-tool adapters, never a rule source for the block: since canon v5.26.0 it also has claude.md,
# which made the claude pattern ambiguous (CANON_SOURCES_AMBIGUOUS on 2026-09-28) next to the standalone claude.md.
SKIP_DIRS = {"dist", "build", "scripts", "fixtures", "tests", "backup", "backups", ".git", "node_modules", "history",
             "adapters"}
RUNTIME_RULES = {"claude": Path(".claude") / "CLAUDE.md", "codex": Path(".codex") / "AGENTS.md",
                 "antigravity": Path(".gemini") / "GEMINI.md"}


@dataclass
class Step:
    name: str
    command: list[str] | None = None          # a subprocess, or
    cwd: Path | None = None
    action: Callable[[], tuple[int, str]] | None = None  # an in-process check
    fatal: bool = True
    note: str = ""


@dataclass
class Receipt:
    started: str
    host: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    result: str = "DRY_RUN"
    stopped_at: str | None = None
    snapshot_of: str | None = None  # set only in the copy committed mid-run (the push result cannot be in it)


def find_canon_sources(canon: Path, overrides: dict[str, Path] | None = None) -> tuple[dict[str, Path], list[str]]:
    """The canon rule source for each runtime, or the reasons it could not be decided without guessing."""
    overrides = overrides or {}
    found: dict[str, Path] = {}
    problems: list[str] = []
    root = canon / CANON_SOURCE_ROOT
    if not root.is_dir():
        return {}, [f"CANON_NOT_FOUND:{root}"]
    files = [p for p in root.rglob("*.md") if not any(part.lower() in SKIP_DIRS for part in p.relative_to(root).parts[:-1])]
    for runtime, patterns in CANON_PATTERNS.items():
        if runtime in overrides:
            found[runtime] = overrides[runtime]
            continue
        matches = sorted({p for p in files for pattern in patterns if _glob_ci(p.name, pattern)})
        if len(matches) == 1:
            found[runtime] = matches[0]
        else:
            listed = ", ".join(str(m.relative_to(canon)) for m in matches[:6]) or "none"
            problems.append(f"CANON_SOURCES_AMBIGUOUS:{runtime} → {listed} (pass --canon-file {runtime}=<path>)")
    return found, problems


def _glob_ci(name: str, pattern: str) -> bool:
    import fnmatch

    return fnmatch.fnmatch(name.lower(), pattern.lower())


def _git_out(runner: Callable[..., Any], cwd: Path, *args: str) -> tuple[int, str]:
    try:
        done = runner(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                      encoding="utf-8", errors="replace")
    except OSError as exc:
        return 127, str(exc)
    return done.returncode, (done.stdout or "").strip()


def on_branch(runner: Callable[..., Any], repo: Path, branch: str = BRANCH) -> tuple[int, str]:
    code, out = _git_out(runner, repo, "rev-parse", "--abbrev-ref", "HEAD")
    if code != 0:
        return code, out
    return (0, out) if out == branch else (1, f"WRONG_BRANCH: on {out}, expected {branch} (git switch {branch})")


def canon_clean(runner: Callable[..., Any], canon: Path) -> tuple[int, str]:
    """U29: the canon repository had unrelated uncommitted edits once. They must never ride along in this commit."""
    code, out = _git_out(runner, canon, "status", "--porcelain", "--", str(CANON_SOURCE_ROOT))
    if code != 0:
        return code, out
    return (0, "clean") if not out else (1, "CANON_DIRTY: commit or stash these first:\n" + out[:500])


def runtime_rules_hold_block(home: Path) -> tuple[int, str]:
    missing = [str(home / rel) for runtime, rel in RUNTIME_RULES.items()
               if (home / rel.parts[0]).is_dir() and BLOCK_BEGIN.split(" (")[0] not in _read(home / rel)]
    return (1, "missing UAOS block: " + ", ".join(missing)) if missing else (0, "all runtime rule files hold the block")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def build_steps(*, repo: Path, canon: Path, home: Path, python: str, sources: dict[str, Path], push: bool,
                register_sentinel: bool, receipt_path: Path, branch: str = BRANCH,
                runner: Callable[..., Any] = subprocess.run) -> list[Step]:
    installer = [python, str(repo / "uaos_everywhere" / "install_uaos_everywhere.py")]
    unique_sources = list(dict.fromkeys(sources.values()))
    rules_args = [arg for path in unique_sources for arg in ("--rules-file", str(path))]
    generator = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(canon / GENERATOR), "-Mode"]
    steps = [
        Step("on_branch", action=lambda: on_branch(runner, repo, branch)),
        Step("canon_clean", action=lambda: canon_clean(runner, canon)),
        Step("fetch", ["git", "fetch", "origin", branch], repo),
        Step("merge", ["git", "merge", "--no-edit", f"origin/{branch}"], repo, note="merge, never rebase"),
        Step("regression", [python, str(repo / ".coord" / "runs" / "run_regression.py")], repo),
        Step("install_hooks", [*installer, "--apply", "--no-rules"], repo),
        Step("canon_block", [*installer, "--apply", "--no-rules", "--portable", *rules_args], repo,
             note="portable block into the canon sources"),
        *[Step(f"generator_{mode.lower()}", [*generator, mode], canon) for mode in ("Build", "SourceCheck", "Apply", "Check")],
        Step("runtime_rules", action=lambda: runtime_rules_hold_block(home)),
        Step("installer_check", [*installer, "--check", "--no-rules", "--portable", *rules_args], repo),
    ]
    if register_sentinel:
        steps.append(Step("sentinel", [*installer, "--apply", "--register-sentinel", str(repo)], repo, fatal=False,
                          note="a refusal means: run once as administrator, or use the shell:startup shortcut"))
    if push:
        def _to_canon_rel(p: Path) -> str:
            try:
                return str(p.resolve().relative_to(canon.resolve()))
            except ValueError:
                return str(p)

        canon_files = list(dict.fromkeys(_to_canon_rel(path) for path in sources.values()))
        steps += [
            # Only this run's files: the three sources and the generator's dist output (canon_clean made sure no
            # earlier edit is mixed in).
            Step("canon_add", ["git", "add", "--", *canon_files, str(CANON_SOURCE_ROOT / "dist")], canon, fatal=False),
            Step("canon_commit", ["git", "commit", "-m", "feat(rules): add the UAOS block to the three runtime sources (U41)"],
                 canon, fatal=False, note="nothing to commit is fine on a re-run"),
            Step("canon_push", ["git", "push"], canon),
            Step("receipt_commit", ["git", "commit", "-m", "chore(u41): PC deployment receipt", "--", str(receipt_path)],
                 repo),
            Step("repo_push", ["git", "push", "origin", f"HEAD:{branch}"], repo),
        ]
    return steps


def run(steps: list[Step], receipt: Receipt, receipt_path: Path, *, execute: bool,
        runner: Callable[..., Any] = subprocess.run) -> Receipt:
    if execute:
        receipt.result = "IN_PROGRESS"  # the committed mid-run snapshot must never read DRY_RUN (U41 run 20260925T151707)
    for step in steps:
        entry: dict[str, Any] = {"step": step.name, "cwd": str(step.cwd) if step.cwd else None,
                                 "command": step.command, "note": step.note}
        if not execute:
            receipt.steps.append({**entry, "status": "PLANNED"})
            continue
        if step.name == "receipt_commit":
            # All deployment gates, including the canon push, are complete. The remaining commit and repo push
            # only publish this evidence. If either fails, the local receipt is rewritten STOPPED and no remote
            # verifier can mistake an unpublished snapshot for a completed rollout.
            receipt.result = "DONE"
            receipt.snapshot_of = "deployment gates through canon_push; receipt_commit and repo_push publish this snapshot"
            _write(receipt, receipt_path)  # the receipt goes into the commit with every earlier step
            receipt.snapshot_of = None
            runner(["git", "add", "--", str(receipt_path)], cwd=str(step.cwd), capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
        started = time.monotonic()
        if step.action is not None:
            code, output = step.action()
        else:
            try:
                kwargs: dict[str, Any] = {
                    "cwd": str(step.cwd) if step.cwd else None,
                    "capture_output": True,
                    "text": True,
                    "encoding": "utf-8",
                    "errors": "replace",
                }
                # ALLOW_PUSH exists only to pass the repository's remote-write hook. Giving it to tests,
                # installers, generators, fetches, merges, adds, or commits silently broadens their authority.
                if step.name in {"canon_push", "repo_push"}:
                    kwargs["env"] = dict(os.environ, ALLOW_PUSH="1")
                done = runner(step.command, **kwargs)
                code, output = done.returncode, (done.stdout or "") + (done.stderr or "")
            except OSError as exc:
                code, output = 127, f"{type(exc).__name__}: {exc}"
        entry.update(status="OK" if code == 0 else ("WARN" if not step.fatal else "FAILED"), exit=code,
                     seconds=round(time.monotonic() - started, 1), output_tail=output.strip()[-600:])
        receipt.steps.append(entry)
        if code != 0 and step.fatal:
            receipt.result, receipt.stopped_at = "STOPPED", step.name
            break
    else:
        receipt.result = "DONE" if execute else "DRY_RUN"
    if execute:
        _write(receipt, receipt_path)
    return receipt


def _write(receipt: Receipt, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt.__dict__, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _overrides(values: list[str]) -> dict[str, Path]:
    result = {}
    for value in values:
        runtime, _, path = value.partition("=")
        if runtime not in CANON_PATTERNS or not path:
            raise SystemExit(f"--canon-file expects claude|codex|antigravity=<path>, got {value!r}")
        result[runtime] = Path(path)
    return result


def main(argv: list[str] | None = None, *, runner: Callable[..., Any] = subprocess.run) -> int:
    parser = argparse.ArgumentParser(prog="deploy_to_this_pc", description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="Execute the steps (default: print the plan)")
    parser.add_argument("--push", action="store_true", help="Also commit and push the canon change and the receipt")
    parser.add_argument("--branch", default=BRANCH, help="The branch this repository must be on (default: main)")
    parser.add_argument("--canon", type=Path, default=DEFAULT_CANON, help="The global-rules repository")
    parser.add_argument("--canon-file", action="append", default=[], metavar="RUNTIME=PATH")
    parser.add_argument("--no-sentinel", action="store_true", help="Skip the 24/7 sentinel logon task")
    parser.add_argument("--home", type=Path, default=Path.home(), help=argparse.SUPPRESS)
    parser.add_argument("--python", default=sys.executable, help=argparse.SUPPRESS)
    parser.add_argument("--repo", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    parser.add_argument("--receipt-dir", type=Path, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass

    stamp = time.strftime("%Y%m%dT%H%M%S")
    receipt_path = (args.receipt_dir or args.repo / ".coord" / "runs" / "U41") / f"deploy_receipt_{stamp}.json"
    receipt = Receipt(started=stamp, host=platform.system())
    sources, problems = find_canon_sources(args.canon, _overrides(args.canon_file))
    if problems:
        receipt.result, receipt.stopped_at = "STOPPED", "canon_sources"
        receipt.steps.append({"step": "canon_sources", "status": "FAILED", "problems": problems})
        if args.apply:
            _write(receipt, receipt_path)
        print(json.dumps(receipt.__dict__, ensure_ascii=False, indent=2))
        return 1
    steps = build_steps(repo=args.repo, canon=args.canon, home=args.home, python=args.python, sources=sources,
                        push=args.push, register_sentinel=not args.no_sentinel and platform.system() == "Windows",
                        receipt_path=receipt_path, branch=args.branch, runner=runner)
    receipt.steps.append({"step": "canon_sources", "status": "OK",
                          "sources": {k: str(v) for k, v in sources.items()}})
    run(steps, receipt, receipt_path, execute=args.apply, runner=runner)
    out = {**receipt.__dict__, "receipt_path": str(receipt_path) if args.apply else None}
    if not args.apply:
        out["next"] = "run again with --apply (and --push to commit and push); nothing was changed"
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if receipt.result in ("DONE", "DRY_RUN") else 1
