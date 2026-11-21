"""U349 Phase 0: deterministic, zero-paid-token canary self-test for the UAOS-RSI operating system.

Run: `python -m v7_harness.rsi_selftest [--project .] [--home ~] [--json]`

Read-only on the project and the system: it only reads files, runs `git show`/`which`, opens one loopback TCP
connection and a read-only SQLite handle. The only writes are to a private temp directory it creates and removes
itself (the T4 fixture). It never calls a model, never deletes anything outside that temp directory.

Probes (ids follow the MIA-RSI-OS stage plan):
  T1  global hook/rule drift (global_install.plan is documented as "without writing anything")
  T2  rsi.EVALUATOR_PATTERNS integrity + SHA-256 snapshot (optionally against a baseline file)
  T4  real-shaped 2026-10-04 push grant canary: so a grant regression never slips silently
  T5a executables on PATH (git, python, gh, uv)
  T5b Ollama loopback reachability + durable circuit-breaker inventory (read-only)
  T5c fixed-context byte footprint of the three tools' rule files
  T5d runtime install count + .work worktree hygiene count

Exit code: 0 when no probe is FAIL, 1 otherwise. WARN/SKIP never fail the run (they report drift or absence).
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import inspect
import json
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

PASS, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"

# Why these: removing any of them from rsi.EVALUATOR_PATTERNS would let the improvement loop edit its own judge
# (docs/036). The list is the minimum core, not the whole tuple, so adding a pattern never breaks the canary.
REQUIRED_EVALUATOR_PATTERNS = (
    "tests/*",
    ".githooks/*",
    "v7_harness/rsi.py",
    "v7_harness/manual.py",
    "v7_harness/calculator_gate.py",
    "v7_harness/adapters/ollama_worker.py",
    "v7_harness/isolation/*",
)

# A snapshot of what a 2026-10-04 grant looked like on origin/main before the `actions` scopes existed.
LEGACY_GRANT_2026_10_04 = {
    "enabled": True,
    "branches": ["claude/*", "codex/*", "agy/*"],
    "never": ["main", "master"],
    "force": False,
    "merge": False,
    "pr_create": True,
}

TOOL_EXECUTABLES = (("git", True), ("python", True), ("gh", False), ("uv", False))  # (name, required)
OLLAMA_ADDR = ("127.0.0.1", 11434)  # Ollama's documented default loopback port.
OLLAMA_TIMEOUT_S = 0.5  # loopback answers in microseconds; a longer wait only slows the canary down.
HOOK_FILES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md", "uaos_everywhere/uaos_global_rule_block.md")


@dataclass
class Probe:
    id: str
    status: str
    detail: str
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "status": self.status, "detail": self.detail, "data": self.data}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# The T4 fixture's git commands are constants (firewall_audit: FIXED, not CALLER_INPUT); nothing a caller passes runs.
_CFG = ("-c", "user.name=selftest", "-c", "user.email=selftest@invalid", "-c", "commit.gpgsign=false")
_FIXTURE_INIT = ("git", "init", "-q")
_FIXTURE_COMMIT = (("git", "add", ".coord/grants/push.json"), ("git", *_CFG, "commit", "-q", "-m", "grant"),
                   ("git", "update-ref", "refs/remotes/origin/main", "HEAD"))
GIT_TIMEOUT_S = 20  # a local `git init/add/commit` in an empty temp repo takes well under a second.


# --------------------------------------------------------------------------------------------------------- T1
def t1_global_drift(home: Path, repo: Path = REPO_ROOT) -> Probe:
    try:
        from v7_harness import global_install

        changes = global_install.plan(Path(home), sys.executable, repo=Path(repo))
    except Exception as exc:  # noqa: BLE001 - a canary reports, it never crashes the run
        return Probe("T1", SKIP, f"global_install.plan unavailable: {type(exc).__name__}: {exc}"[:200])
    drift = [c for c in changes if c.action in ("CREATE", "UPDATE", "REMOVE")]
    rows = [{"target": c.target, "action": c.action} for c in changes]
    if drift:
        return Probe("T1", WARN, f"{len(drift)} of {len(changes)} global targets differ from the repo rules",
                     {"drift": [r for r in rows if r["action"] in ("CREATE", "UPDATE", "REMOVE")], "total": len(changes)})
    return Probe("T1", PASS, f"{len(changes)} global targets match", {"total": len(changes)})


# --------------------------------------------------------------------------------------------------------- T2
def patterns_digest(patterns: tuple[str, ...] | list[str]) -> str:
    return _sha256("\n".join(sorted(str(p) for p in patterns)).encode("utf-8"))


def t2_evaluator_integrity(repo: Path = REPO_ROOT, baseline: Path | None = None,
                           patterns: tuple[str, ...] | None = None, target_patterns: tuple[str, ...] | None = None) -> Probe:
    try:
        from v7_harness import rsi

        pats = tuple(rsi.EVALUATOR_PATTERNS) if patterns is None else tuple(patterns)
        targets = tuple(rsi.RSI_TARGET_PATTERNS) if target_patterns is None else tuple(target_patterns)
    except Exception as exc:  # noqa: BLE001
        return Probe("T2", FAIL, f"rsi module unreadable: {type(exc).__name__}: {exc}"[:200])
    missing = [p for p in REQUIRED_EVALUATOR_PATTERNS if p not in pats]
    # An improvement target that an evaluator pattern also matches would let the loop change its own judge.
    # Both directions: a target glob ('v7_harness/*') can cover a literal evaluator path, and vice versa (U355-C review).
    overlap = [t for t in targets if any(fnmatch.fnmatchcase(t, e) or fnmatch.fnmatchcase(e, t) for e in pats)]
    digest = patterns_digest(pats)
    files: dict[str, str] = {}
    for p in pats:
        if any(ch in p for ch in "*?["):
            continue
        f = Path(repo) / p
        if f.is_file():
            files[p] = _sha256(f.read_bytes())
    data: dict[str, Any] = {"patterns": len(pats), "digest": digest, "files": len(files)}
    if missing or overlap:
        return Probe("T2", FAIL, f"evaluator protection broken: missing={missing} overlap={overlap}",
                     {**data, "missing": missing, "overlap": overlap})
    if baseline is not None:
        try:
            base = json.loads(Path(baseline).read_text(encoding="utf-8"))
            base_digest = base.get("digest") if isinstance(base, dict) else None
            base_files = base.get("files") if isinstance(base, dict) else None
        except (OSError, ValueError) as exc:
            return Probe("T2", WARN, f"baseline unreadable: {exc}"[:200], data)
        if not isinstance(base_files, dict):
            return Probe("T2", WARN, "baseline malformed: 'files' is not an object", data)
        changed = sorted(k for k, v in files.items() if k in base_files and base_files[k] != v)
        removed = sorted(k for k in base_files if k not in files)  # a deleted evaluator file is drift, not a pass
        if base_digest != digest or changed or removed:
            return Probe("T2", WARN, f"baseline drift: pattern_digest_changed={base_digest != digest} "
                         f"files_changed={changed} files_removed={removed}",
                         {**data, "changed_files": changed, "removed_files": removed})
    return Probe("T2", PASS, f"{len(pats)} evaluator patterns intact, {len(files)} evaluator files hashed", data)


# --------------------------------------------------------------------------------------------------------- T4
def _grant_fixture(parent: Path, grant: dict[str, Any]) -> Path:
    repo = parent / "grant_repo"
    repo.mkdir()
    if subprocess.run(list(_FIXTURE_INIT), cwd=str(repo), stdin=subprocess.DEVNULL, capture_output=True,
                      timeout=GIT_TIMEOUT_S).returncode != 0:
        raise RuntimeError("git init failed")
    (repo / ".coord" / "grants").mkdir(parents=True)
    (repo / ".coord" / "grants" / "push.json").write_text(json.dumps(grant), encoding="utf-8")
    for cmd in _FIXTURE_COMMIT:
        done = subprocess.run(list(cmd), cwd=str(repo), stdin=subprocess.DEVNULL, capture_output=True,
                              timeout=GIT_TIMEOUT_S)
        if done.returncode != 0:
            raise RuntimeError(f"git {cmd[1]} failed: {done.stderr.decode('utf-8', 'replace')[:120]}")
    return repo


def t4_legacy_grant_canary(grant: dict[str, Any] | None = None, tmp_parent: Path | None = None) -> Probe:
    grant = dict(LEGACY_GRANT_2026_10_04) if grant is None else grant
    try:
        from v7_harness.coord import stop_gate
    except Exception as exc:  # noqa: BLE001
        return Probe("T4", SKIP, f"stop_gate unavailable: {type(exc).__name__}: {exc}"[:200])
    params = inspect.signature(stop_gate.push_check).parameters
    has_action = "action" in params
    try:
        with tempfile.TemporaryDirectory(prefix="rsi_selftest_", dir=str(tmp_parent) if tmp_parent else None) as tmp:
            repo = _grant_fixture(Path(tmp), grant)

            def check(branch: str, action: str | None = None, force: bool = False) -> str:
                kwargs: dict[str, Any] = {"action": action} if (action and has_action) else {}
                if force:
                    kwargs["force"] = True
                return str(stop_gate.push_check(repo, branch, **kwargs).get("decision"))

            observed = {"push_agy": check("agy/selftest"), "push_main": check("main"),
                        "force_push": check("agy/selftest", force=True)}
            if has_action:
                observed["pr_create"] = check("agy/selftest", "pr_create")
                observed["merge"] = check("agy/selftest", "merge")
    except Exception as exc:  # noqa: BLE001
        return Probe("T4", SKIP, f"fixture failed: {type(exc).__name__}: {exc}"[:200])
    problems = []
    if observed["push_agy"] != "ALLOW":
        problems.append("legacy grant no longer allows push to agy/*")
    if observed["push_main"] != "DENY":
        problems.append("main is no longer denied")
    if grant.get("force") is not True and observed["force_push"] != "DENY":
        problems.append("force push is allowed although the grant has force:false")
    if has_action:
        if observed["pr_create"] != "ALLOW":
            problems.append("legacy pr_create:true no longer allows pr_create")
        if observed["merge"] != "DENY":
            problems.append("legacy grant (merge:false, no auto_merge_via_coord_merge) must DENY action=merge")
    data = {"observed": observed, "push_check_has_action": has_action}
    # What `coord merge` does by default must not depend on that DENY (U348 R3-P1): merge() enforces only on opt-in.
    try:
        from v7_harness.coord import merge_route

        default = inspect.signature(merge_route.merge).parameters.get("require_grant")
        data["merge_require_grant_default"] = None if default is None else repr(default.default)
        if default is not None and default.default not in (False,):
            problems.append(f"merge(require_grant) default is {default.default!r}: default coord merge would depend on the grant")
    except Exception as exc:  # noqa: BLE001
        data["merge_route"] = f"unreadable: {type(exc).__name__}"
    if problems:
        return Probe("T4", FAIL, "; ".join(problems), data)
    note = "" if has_action else " (push_check has no action scope on this tree: merge/pr_create canary skipped)"
    return Probe("T4", PASS, "2026-10-04 grant behaves as documented" + note, data)


# -------------------------------------------------------------------------------------------------------- T5a
def t5a_executables(which=shutil.which) -> Probe:
    found: dict[str, str | None] = {}
    problems, warns = [], []
    for name, required in TOOL_EXECUTABLES:
        path = which(name) or (which("python3") if name == "python" else None)
        found[name] = path
        if path is None:
            (problems if required else warns).append(name)
    if problems:
        return Probe("T5a", FAIL, f"required executables missing from PATH: {problems}", {"found": found})
    if warns:
        return Probe("T5a", WARN, f"optional executables missing: {warns}", {"found": found})
    return Probe("T5a", PASS, "git, python, gh, uv resolve", {"found": found})


# -------------------------------------------------------------------------------------------------------- T5b
def _circuit_inventory(db: Path) -> dict[str, int] | None:
    """Row counts of tables whose name mentions `circuit`, through a read-only SQLite handle (never creates files)."""
    if not db.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=1)
    except sqlite3.Error:
        return None
    try:
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%circuit%'")]
        return {n: int(conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0]) for n in names}
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def t5b_ollama(project: Path, addr: tuple[str, int] = OLLAMA_ADDR, timeout: float = OLLAMA_TIMEOUT_S) -> Probe:
    reachable = False
    try:
        with socket.create_connection(addr, timeout=timeout):
            reachable = True
    except OSError:
        pass
    inventory = _circuit_inventory(Path(project) / ".coord" / "pilot" / "coord.sqlite3")
    data = {"reachable": reachable, "addr": f"{addr[0]}:{addr[1]}", "circuit_tables": inventory}
    if not reachable:
        return Probe("T5b", WARN, "Ollama loopback is not reachable (local worker route unavailable)", data)
    return Probe("T5b", PASS, "Ollama loopback reachable", data)


# -------------------------------------------------------------------------------------------------------- T5c
def t5c_context_footprint(project: Path, home: Path) -> Probe:
    sizes: dict[str, int] = {}
    for rel in HOOK_FILES:
        f = Path(project) / rel
        if f.is_file():
            sizes[rel] = f.stat().st_size
    for rel in (".claude/CLAUDE.md", ".codex/AGENTS.md", ".gemini/GEMINI.md"):
        f = Path(home) / rel
        if f.is_file():
            sizes[f"~/{rel}"] = f.stat().st_size
    if not sizes:
        return Probe("T5c", SKIP, "no rule files found", {"bytes": {}, "total": 0})
    return Probe("T5c", PASS, f"{len(sizes)} rule files, {sum(sizes.values())} bytes fixed context",
                 {"bytes": sizes, "total": sum(sizes.values())})


# -------------------------------------------------------------------------------------------------------- T5d
def t5d_hygiene(project: Path, home: Path) -> Probe:
    runtime = Path(home) / ".uaos" / "runtime"
    runtimes = sorted(p.name for p in runtime.iterdir() if p.is_dir() and not p.name.startswith(".")) if runtime.is_dir() else []
    work = Path(project) / ".work"
    worktrees = sorted(p.name for p in work.iterdir() if p.is_dir() and p.name.startswith("wt_")) if work.is_dir() else []
    data = {"runtimes": len(runtimes), "work_worktrees": len(worktrees)}
    # Counts are reported, never acted on: deletion is a human-list item (no deletions here).
    if len(runtimes) > 10 or len(worktrees) > 30:
        return Probe("T5d", WARN, f"{len(runtimes)} runtimes, {len(worktrees)} .work worktrees: review for cleanup (manual)", data)
    return Probe("T5d", PASS, f"{len(runtimes)} runtimes, {len(worktrees)} .work worktrees", data)


# ------------------------------------------------------------------------------------------------------- driver
def run(project: Path, home: Path, repo: Path = REPO_ROOT, baseline: Path | None = None) -> list[Probe]:
    probes = [
        t1_global_drift(home, repo),
        t2_evaluator_integrity(repo, baseline),
        t4_legacy_grant_canary(),
        t5a_executables(),
        t5b_ollama(project),
        t5c_context_footprint(project, home),
        t5d_hygiene(project, home),
    ]
    return probes


def summarize(probes: list[Probe]) -> dict[str, Any]:
    counts = {s: sum(1 for p in probes if p.status == s) for s in (PASS, WARN, FAIL, SKIP)}
    return {"ok": counts[FAIL] == 0, "counts": counts, "probes": [p.as_dict() for p in probes], "paid_tokens": 0}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m v7_harness.rsi_selftest", description=__doc__.splitlines()[0])
    parser.add_argument("--project", type=Path, default=Path("."))
    parser.add_argument("--home", type=Path, default=Path.home(), help="Home whose global tool files are inspected")
    parser.add_argument("--baseline", type=Path, default=None, help="Optional T2 baseline JSON {digest, files}; read only")
    parser.add_argument("--json", action="store_true", help="Print one JSON document")
    args = parser.parse_args(argv)
    report = summarize(run(args.project.resolve(), args.home, REPO_ROOT, args.baseline))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for p in report["probes"]:
            print(f"{p['id']:<4} {p['status']:<4} {p['detail']}")
        print(f"ok={report['ok']} {report['counts']} paid_tokens=0")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
