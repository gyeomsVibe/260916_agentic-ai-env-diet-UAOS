"""U301: UAOS-RSI version-up gate — every merged update carries exactly the version bump its change class requires.

The OS version is the SemVer in `uaos_everywhere/VERSION`; the runtime installer names `~/.uaos/runtime/<VERSION>-<digest>`
after it, so a gated bump is what makes an update visible as a new installed version.

Change classes (most severe wins):
    major  a commit line in base..head starts with `BREAKING CHANGE:` (Conventional Commits footer) or `BREAKING:`
    minor  the global rule block or an agent entry file changed (rules every tool reads at session start)
    patch  harness code (`v7_harness/`, `uaos_everywhere/` scripts) changed
    none   only docs, tests, desk state or other files changed — no bump allowed

Usage:
    uaos version check [--repo R] [--base origin/main] [--head HEAD]   # gate for a card branch; exit 1 on refusal
    uaos version status [--repo R]                                     # repo VERSION vs installed runtime vs rule block
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

VERSION_FILE = "uaos_everywhere/VERSION"
RULE_BLOCK = "uaos_everywhere/uaos_global_rule_block.md"
# Files whose text is loaded as rules: a change alters behavior of every tool, so it is a minor (feature) bump.
RULE_FILES = (RULE_BLOCK, "AGENTS.md", "CLAUDE.md", "GEMINI.md")
CODE_PREFIXES = ("v7_harness/", "uaos_everywhere/")
CODE_SUFFIXES = (".py", ".ps1", ".cmd", ".sh", ".json")
# The rule block states the version it belongs to, so an installed rule text can be matched to its runtime.
HEADER_RE = re.compile(r"<!--\s*uaos-version:\s*(\d+\.\d+\.\d+)\s*-->")
SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
RANK = {"none": 0, "patch": 1, "minor": 2, "major": 3}
# Conventional Commits / semantic-release footer keywords, plus the short form; the highest class wins.
BREAKING_KEYS = ("BREAKING CHANGE:", "BREAKING CHANGES:", "BREAKING:")


def parse(version: str) -> tuple[int, int, int]:
    m = SEMVER_RE.match(version.strip())
    if not m:
        raise ValueError(f"VERSION_INVALID {version!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def bump(version: str, change: str) -> str:
    major, minor, patch = parse(version)
    if change == "major":
        return f"{major + 1}.0.0"
    if change == "minor":
        return f"{major}.{minor + 1}.0"
    if change == "patch":
        return f"{major}.{minor}.{patch + 1}"
    return f"{major}.{minor}.{patch}"


def classify(paths: Sequence[str], messages: Sequence[str] = ()) -> str:
    """Return the most severe change class among the changed paths and commit messages."""
    if any(line.strip().startswith(BREAKING_KEYS) for msg in messages for line in msg.splitlines()):
        return "major"
    change = "none"
    for raw in paths:
        p = raw.replace("\\", "/").lstrip("./")
        if p == VERSION_FILE:
            continue
        if p in RULE_FILES:
            cls = "minor"
        elif p.startswith(CODE_PREFIXES) and p.endswith(CODE_SUFFIXES) and "/__pycache__/" not in p:
            cls = "patch"
        else:
            cls = "none"
        if RANK[cls] > RANK[change]:
            change = cls
    return change


def rule_block_version(text: str) -> str | None:
    m = HEADER_RE.search(text)
    return m.group(1) if m else None


def _strip_header(text: str) -> str:
    return HEADER_RE.sub("", text.replace("\r\n", "\n")).replace("\n\n", "\n")


def evaluate(base_version: str, head_version: str, change: str, header_version: str | None) -> dict[str, Any]:
    """Pure decision: refusals are stable codes so ledgers and tests can count them."""
    required = bump(base_version, change)
    codes: list[str] = []
    if parse(head_version) < parse(required):
        codes.append("VERSION_BUMP_MISSING")
    elif parse(head_version) > parse(required):
        codes.append("VERSION_SKIPPED")
    if header_version != head_version:
        codes.append("RULE_BLOCK_VERSION_MISMATCH")
    return {
        "ok": not codes,
        "codes": codes,
        "change": change,
        "base_version": base_version,
        "head_version": head_version,
        "required_version": required,
        "rule_block_version": header_version,
    }


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True
    ).stdout


def _show(repo: Path, ref: str, path: str) -> str:
    try:
        return _git(repo, "show", f"{ref}:{path}")
    except subprocess.CalledProcessError:
        return ""


def _disk(repo: Path, path: str) -> str:
    return (repo / path).read_text(encoding="utf-8") if (repo / path).is_file() else ""


def check(repo: Path, base: str = "origin/main", head: str | None = None) -> dict[str, Any]:
    """head=None gates the working tree (staged, unstaged, untracked), so `card audit` can run before the commit."""
    rev = head or "HEAD"
    merge_base = _git(repo, "merge-base", base, rev).strip()
    diff_range = merge_base if head is None else f"{merge_base}..{head}"
    paths = [p for p in _git(repo, "diff", "--name-only", diff_range).splitlines() if p.strip()]
    if head is None:
        paths += [p for p in _git(repo, "ls-files", "--others", "--exclude-standard").splitlines() if p.strip()]
    messages = _git(repo, "log", "--format=%B%x00", f"{merge_base}..{rev}").split("\x00")
    base_version = _show(repo, merge_base, VERSION_FILE).strip() or "0.0.0"
    head_version = (_disk(repo, VERSION_FILE) if head is None else _show(repo, head, VERSION_FILE)).strip() or "0.0.0"
    head_block = _disk(repo, RULE_BLOCK) if head is None else _show(repo, head, RULE_BLOCK)
    header = rule_block_version(head_block)
    # Bumping the header comment alone is part of the version-up, not a rule change.
    if RULE_BLOCK in paths and _strip_header(_show(repo, merge_base, RULE_BLOCK)) == _strip_header(head_block):
        paths.remove(RULE_BLOCK)
    result = evaluate(base_version, head_version, classify(paths, messages), header)
    result.update({"base": base, "merge_base": merge_base[:12], "changed_files": len(paths)})
    return result


def status(repo: Path, home: Path | None = None) -> dict[str, Any]:
    """LIVE only when the installed runtime runs the repo VERSION and the rule block declares the same version."""
    home = home or Path.home()
    repo_version = (repo / VERSION_FILE).read_text(encoding="utf-8").strip()
    header = rule_block_version((repo / RULE_BLOCK).read_text(encoding="utf-8")) if (repo / RULE_BLOCK).is_file() else None
    current_path = home / ".uaos" / "runtime" / "current.json"
    installed = ""
    if current_path.is_file():
        try:
            installed = str(json.loads(current_path.read_text(encoding="utf-8")).get("version") or "")
        except ValueError:
            installed = ""
    installed_semver = installed.split("-", 1)[0]
    codes = []
    if installed_semver != repo_version:
        codes.append("RUNTIME_VERSION_DRIFT")
    if header != repo_version:
        codes.append("RULE_BLOCK_VERSION_MISMATCH")
    return {
        "ok": not codes,
        "state": "LIVE" if not codes else "NOT_LIVE",
        "codes": codes,
        "repo_version": repo_version,
        "installed_runtime": installed,
        "rule_block_version": header,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="uaos version", description=__doc__.splitlines()[0])
    subs = parser.add_subparsers(dest="cmd", required=True)
    p_check = subs.add_parser("check", help="Refuse a branch whose VERSION bump does not match its change class")
    p_check.add_argument("--repo", default=".")
    p_check.add_argument("--base", default="origin/main")
    p_check.add_argument("--head", default=None, help="Commit to gate (default: the working tree)")
    p_status = subs.add_parser("status", help="Repo VERSION vs installed runtime vs rule block header")
    p_status.add_argument("--repo", default=".")
    args = parser.parse_args(list(argv) if argv is not None else None)
    repo = Path(args.repo).resolve()
    res = check(repo, args.base, args.head) if args.cmd == "check" else status(repo)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
