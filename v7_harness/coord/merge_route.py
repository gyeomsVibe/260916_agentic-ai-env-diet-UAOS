"""U166: a gated pull request is merged by the first tool that can, never handed to the user.

윤겸스 (2026-10-05): merges go to Antigravity first and Codex second, as a standing house rule; "if you cannot, use
another tool". Claude's own `gh pr merge` is denied by its permission settings (receipt R21), so Claude is not a
merger: it runs this route, and the route hands the one command to the merger tools in order.

The route never trusts a tool's report. It reads the pull request with `gh pr view` before (gate) and after (proof):
only `state == MERGED` with the same head counts. `--match-head-commit` makes GitHub refuse a head that moved.
The gate also needs `--verdict relay_<id>`: a mailbox letter in which a judge tool other than the PR's author passed
this exact head. All tools share one machine and one GitHub account, so the letter's actor is not cryptographic proof;
it is an append-only record a tool must deliberately forge, unlike a trailer the author writes in every commit.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

# Order fixed by 윤겸스 on 2026-10-05: 1st Antigravity, 2nd Codex.
MERGERS = ("antigravity", "codex")
# A merger that a fresh heartbeat or lease marks away is skipped; UNKNOWN is tried, because the proof is the PR state.
AWAY_STATES = ("LIMITED", "ABSENT")
HEAD_RE = re.compile(r"^[0-9a-f]{40}$")
RELAY_RE = re.compile(r"^relay_[0-9a-f]{32}$")
# The verdict is a letter from an independent judge, not a commit trailer: the author writes its own trailers, so a
# trailer is self-approval (Antigravity design audit relay_45a03503, defect 2). The letter must come from a judge tool
# that is not the PR's author, name this exact head, and its first verdict word must be PASS or APPROVE.
JUDGES = ("codex", "antigravity")
VERDICT_WORD_RE = re.compile(r"\b(PASS|APPROVE|REVISE|FAIL|REJECT|BLOCK)\b")
LETTER_DIRS = ("inbox", "claimed", "ack")
# Feature branches are named <tool>/<card>-...; the prefix is the authoring tool.
AUTHOR_PREFIX = {"claude": "claude", "codex": "codex", "antigravity": "antigravity", "agy": "antigravity"}
# One `gh pr merge` finished in 14-40 s in the 2026-10-05 Antigravity run (#124-#127); 300 s leaves room for a cold
# start of either CLI without letting a hung merger hold the route for long.
TOOL_TIMEOUT_S = 300
PR_FIELDS = "state,mergeable,headRefOid,headRefName,url"
LEDGER = Path(".coord") / "merges.jsonl"
# U174-B: the judge letter is same-account data (Codex decision D1, .work/u169/codex_gate_decision.md); a receipt that
# GitHub's OIDC identity signed for the CI workflow is not (https://docs.github.com/en/actions/concepts/security/
# artifact-attestations). U174-A (PR #137) made uaos-tests.yml write and attest receipt.json on every PR head.
CI_WORKFLOW = ".github/workflows/uaos-tests.yml"
CI_ARTIFACT = "uaos-ci-receipt"
RECEIPT_DIR = Path(".work") / "ci_receipts"
GITHUB_PR_RE = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/pull/\d+$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
# Reads answer in 1-5 s; a download and a Sigstore verify fetch bundles, so they get twice the read limit.
GH_READ_S = 60
GH_FETCH_S = 120


class MergeRefused(ValueError):
    pass


def pr_view(pr: int, project: Path, runner: Any = subprocess.run) -> dict[str, Any]:
    done = runner(["gh", "pr", "view", str(pr), "--json", PR_FIELDS], cwd=str(project), capture_output=True,
                  timeout=60)
    if done.returncode != 0:
        raise MergeRefused(f"gh pr view exit {done.returncode}")
    data = json.loads((done.stdout or b"").decode("utf-8", errors="replace"))
    if not isinstance(data, dict):
        raise MergeRefused("gh pr view did not return an object")
    return data


def check_args(pr: Any, head: Any, verdict: Any) -> None:
    """Strict shapes before anything reaches a command line or a prompt (no injection through pr, head, verdict)."""
    if not isinstance(pr, int) or isinstance(pr, bool) or pr <= 0:
        raise MergeRefused("pr must be a positive integer")
    if not isinstance(head, str) or not HEAD_RE.match(head):
        raise MergeRefused("head must be a 40-character commit sha")
    if not isinstance(verdict, str) or not RELAY_RE.match(verdict):
        raise MergeRefused("verdict must be a relay_<32 hex> letter id")


def read_verdict(project: Path, verdict: str) -> dict[str, Any]:
    from .next_card import coord_root

    mailbox = coord_root(Path(project)) / ".coord" / "mailbox"
    for sub in LETTER_DIRS:
        for path in sorted((mailbox / sub).glob(f"{verdict}*.json")):
            try:
                letter = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(letter, dict) and isinstance(letter.get("payload"), dict):
                letter = letter["payload"]  # u23-mailbox-v1 keeps actor and message under payload (PR #128 real use)
            if isinstance(letter, dict) and "message" in letter:
                return letter
    raise MergeRefused(f"verdict letter {verdict} not found")


def gate(view: dict[str, Any], head: str, letter: dict[str, Any]) -> None:
    """Refuse unless the PR is OPEN, MERGEABLE, at `head`, and an independent judge's letter passed this head."""
    if view.get("state") != "OPEN":
        raise MergeRefused(f"state {view.get('state')}")
    if view.get("mergeable") != "MERGEABLE":
        raise MergeRefused(f"mergeable {view.get('mergeable')}")
    if view.get("headRefOid") != head:
        raise MergeRefused("head moved")
    judge = AUTHOR_PREFIX.get(str(letter.get("actor", "")).strip().lower(), "")
    author = AUTHOR_PREFIX.get(str(view.get("headRefName", "")).split("/")[0].lower(), "")
    if not author:
        # An unknown author makes independence UNKNOWN, and UNKNOWN is no ground for acting (Codex judge U166-APPLY3).
        raise MergeRefused(f"PR author unknown from branch {view.get('headRefName')!r}")
    if judge not in JUDGES:
        raise MergeRefused(f"verdict actor {letter.get('actor')!r} is not a judge tool")
    if judge == author:
        raise MergeRefused("verdict comes from the PR's own author")
    message = str(letter.get("message", ""))
    words = VERDICT_WORD_RE.findall(message.upper())
    if head not in message or not words or words[0] not in ("PASS", "APPROVE"):
        raise MergeRefused("verdict letter does not pass this exact head")


def _text(raw: Any) -> str:
    return raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw or "")


def _check_ci_inputs(pr: Any, head: Any, repo: str) -> None:
    """Every value that reaches a gh argv below is a positive int, a 40-hex head, or owner/name."""
    if not isinstance(pr, int) or isinstance(pr, bool) or pr <= 0:
        raise MergeRefused("pr must be a positive integer")
    if not isinstance(head, str) or not HEAD_RE.match(head):
        raise MergeRefused("head must be a 40-character commit sha")
    if not REPO_RE.match(repo):
        raise MergeRefused(f"repo {repo!r} is not owner/name")


def ci_attested(view: dict[str, Any], pr: int, head: str, project: Path, runner: Any) -> str:
    """Return the CI run id whose signed receipt passed this head; NOT_CONFIGURED when the repo has no workflow."""
    match = GITHUB_PR_RE.match(str(view.get("url", "")))
    if not match:
        return "NOT_CONFIGURED"  # not a github.com pull request: no Actions attestation exists for it
    repo = match.group(1)
    _check_ci_inputs(pr, head, repo)
    cwd = str(project)
    probe = runner(["gh", "api", f"repos/{repo}/contents/{CI_WORKFLOW}", "--silent"], cwd=cwd, capture_output=True,
                   timeout=GH_READ_S)
    if probe.returncode != 0:
        if "HTTP 404" in _text(probe.stderr):
            return "NOT_CONFIGURED"
        raise MergeRefused(f"gh api exit {probe.returncode}")  # a network failure is UNKNOWN, not "no workflow"
    diff = runner(["gh", "pr", "diff", str(pr), "--name-only"], cwd=cwd, capture_output=True, timeout=GH_READ_S)
    if diff.returncode != 0:
        raise MergeRefused(f"gh pr diff exit {diff.returncode}")
    if CI_WORKFLOW in _text(diff.stdout).split():
        # A pull_request run uses the PR's own copy of the workflow, so it cannot attest a change to itself.
        raise MergeRefused("PR changes the CI workflow; its own run cannot attest it")
    runs = runner(["gh", "run", "list", "-R", repo, "--workflow", Path(CI_WORKFLOW).name, "--commit", head,
                   "--json", "databaseId,conclusion", "--limit", "20"], cwd=cwd, capture_output=True,
                  timeout=GH_READ_S)
    if runs.returncode != 0:
        raise MergeRefused(f"gh run list exit {runs.returncode}")
    listed = json.loads(_text(runs.stdout) or "[]")
    green = [r.get("databaseId") for r in (listed if isinstance(listed, list) else [])
             if isinstance(r, dict) and r.get("conclusion") == "success"]
    if not green or not isinstance(green[0], int) or isinstance(green[0], bool):
        raise MergeRefused("no green CI run for this head")
    run_id = green[0]
    out = Path(project) / RECEIPT_DIR / f"{pr}-{head[:12]}-{run_id}"
    receipt = out / "receipt.json"
    if not receipt.exists():
        fetched = runner(["gh", "run", "download", str(run_id), "-R", repo, "-n", CI_ARTIFACT, "-D", str(out)],
                         cwd=cwd, capture_output=True, timeout=GH_FETCH_S)
        if fetched.returncode != 0:
            raise MergeRefused(f"gh run download exit {fetched.returncode}")
    # A kept file is verified again on every use: an edited receipt no longer matches its signed digest.
    verified = runner(["gh", "attestation", "verify", str(receipt), "-R", repo, "--signer-workflow",
                       f"{repo}/{CI_WORKFLOW}"], cwd=cwd, capture_output=True, timeout=GH_FETCH_S)
    if verified.returncode != 0:
        raise MergeRefused(f"CI receipt attestation did not verify (exit {verified.returncode})")
    data = json.loads(receipt.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("head") != head or str(data.get("pr")) != str(pr)
            or data.get("repo") != repo or data.get("exit") != 0):
        raise MergeRefused("CI receipt does not pass this exact head")
    return str(run_id)


def merge_command(pr: int, head: str) -> str:
    return f"gh pr merge {pr} --merge --match-head-commit {head}"


def tool_argv(tool: str, pr: int, head: str, project: Path) -> list[str]:
    ask = (f"Run exactly this one shell command in {project} and nothing else, then reply with its exit code only: "
           f"{merge_command(pr, head)}")
    if tool == "antigravity":
        return ["agy", "-p", ask, "--output-format", "json", "--print-timeout", f"{TOOL_TIMEOUT_S}s"]
    if tool == "codex":
        # The default read-only sandbox has no network; workspace-write with network is the narrowest mode gh needs.
        return ["codex", "exec", "-s", "workspace-write", "-c", "sandbox_workspace_write.network_access=true",
                "--skip-git-repo-check", "-C", str(project), ask]
    raise MergeRefused(f"not a merger: {tool}")


def _record(project: Path, row: dict[str, Any]) -> None:
    from .stream import _exclusive

    path = Path(project) / LEDGER
    path.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive(path.with_suffix(".lock")):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def merge(project: Path, pr: int, head: str, verdict: str, *, runner: Any = None,
          now: float | None = None, desk: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Merge `pr` at `head` through Antigravity, then Codex. Returns {"state": MERGED | REFUSED | FAILED_ALL_ROUTES}."""
    project = Path(project)
    if runner is None:
        from ..judge import run_resolved  # U175: codex is an npm shim (codex.cmd); a bare name never starts on Windows
        runner = run_resolved
    moment = time.time() if now is None else now
    if desk is None:
        from .presence import read_all

        desk = read_all(project, now=moment)
    try:
        check_args(pr, head, verdict)
        view = pr_view(pr, project, runner)
        gate(view, head, read_verdict(project, verdict))
        ci_run = ci_attested(view, pr, head, project, runner)
    except (MergeRefused, OSError, subprocess.SubprocessError, ValueError) as exc:
        row = {"ts": moment, "pr": str(pr)[:20], "head": str(head)[:40], "verdict": str(verdict)[:40],
               "state": "REFUSED", "reason": str(exc)[:200], "attempts": []}
        _record(project, row)
        return row
    attempts: list[dict[str, Any]] = []
    for tool in MERGERS:
        if (desk.get(tool) or {}).get("state") in AWAY_STATES:
            attempts.append({"tool": tool, "skipped": (desk.get(tool) or {}).get("state")})
            continue
        try:
            done = runner(tool_argv(tool, pr, head, project), cwd=str(project),
                          env={**os.environ, "UAOS_WORKER": "1"}, capture_output=True, timeout=TOOL_TIMEOUT_S + 60)
            attempt = {"tool": tool, "exit": done.returncode}
        except (OSError, subprocess.SubprocessError) as exc:
            attempt = {"tool": tool, "error": type(exc).__name__}
        try:
            after = pr_view(pr, project, runner)
        except (MergeRefused, OSError, subprocess.SubprocessError, ValueError) as exc:
            after = {"state": f"UNREADABLE {type(exc).__name__}"}
        attempt["pr_state"] = after.get("state")
        attempts.append(attempt)
        if after.get("state") == "MERGED" and after.get("headRefOid") == head:
            row = {"ts": moment, "pr": pr, "head": head, "verdict": verdict, "state": "MERGED", "merged_by": tool,
                   "ci_run": ci_run, "attempts": attempts}
            _record(project, row)
            return row
        if after.get("state") == "CLOSED":
            break
    row = {"ts": moment, "pr": pr, "head": head, "verdict": verdict, "state": "FAILED_ALL_ROUTES",
           "attempts": attempts}
    _record(project, row)
    return row
