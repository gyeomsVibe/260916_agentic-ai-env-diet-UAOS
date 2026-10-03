"""계산기 원칙 관문. Claude·Codex(지휘자)는 코드를 손으로 쓰지 않고
Antigravity·Ollama(계산기)에 pilot 으로 맡긴다. 커밋에 올라간 `v7_harness/` 아래 .py 파일은 APPLIED 된 pilot 결과물과
내용이 같아야 하고, 그 묶음(bundle)에는 같은 bundle_id 의 독립 검토 PASS(Antigravity 또는 Codex)가 있어야 하며, 커밋에는
Antigravity 감사 답장을 가리키는 `Audit: relay_<id>` 줄이 있어야 한다(U123). `Calculator-Exempt` 예외는 코드에 더는 통하지 않는다.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

GATED_PREFIX = "v7_harness/"
LOCAL_AUTHORS = frozenset({"ollama", "local", "cascade"})  # U123: the free Ollama routes that must write the fix first
REVIEWERS = ("agy", "codex")  # U123: independent reviewers; the conductor and the author never approve alone
FAILED_OUTCOMES = frozenset({"FAIL", "FAILED", "BLOCKED", "UNUSABLE", "REWORK", "REJECTED"})  # same set as delegation.py
AUDIT_RE = re.compile(r"^Audit:\s*(relay_[0-9a-f]+)\s*$", re.MULTILINE)  # U123: the Antigravity audit reply id
# U130 (agy audit relay_92fa8200): new runtime code under these prefixes needs a card whose `card audit` passes.
CARD_GATED = ("v7_harness/", "uaos_everywhere/")


def _review_ok(task_dir: Path, bundle_id, ledger_rows) -> bool:
    """U123: PASS by an independent reviewer for this exact bundle; a non-Ollama author also needs a failed Ollama
    run of the same card that really called the model (U122-F1: PROMPT_TOO_LARGE had input_tokens 0)."""
    card = task_dir.name.split("-")[0]
    for reviewer in REVIEWERS:
        try:
            record = json.loads((task_dir / f"review_{reviewer}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(record, dict) or record.get("verdict") != "PASS":
            continue
        if not isinstance(bundle_id, str) or not bundle_id or record.get("bundle_id") != bundle_id:
            continue
        if record.get("author_worker") in LOCAL_AUTHORS:
            return True
        for row in ledger_rows:
            if (isinstance(row, dict) and str(row.get("work_id") or "").split("-")[0] == card
                    and row.get("worker") in LOCAL_AUTHORS and row.get("outcome") in FAILED_OUTCOMES
                    and int(row.get("input_tokens") or 0) > 0):
                return True
    return False


def _digest(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def applied_digests(pilot_dir: Path, ledger_rows=()) -> dict[str, set[str]]:
    pilot_dir = Path(pilot_dir)
    result: dict[str, set[str]] = {}
    runs_dir = pilot_dir / "runs"
    if not runs_dir.is_dir():
        return result
    for task_dir in runs_dir.iterdir():
        if not task_dir.is_dir():
            continue
        summary_path = task_dir / "summary.json"
        if not summary_path.is_file():
            continue
        try:
            with summary_path.open("r", encoding="utf-8") as f:
                summary = json.load(f)
        except Exception:
            continue
        if not isinstance(summary, dict) or summary.get("promotion") != "APPLIED":
            continue
        if not _review_ok(task_dir, summary.get("bundle_id"), ledger_rows):
            continue
        changed = summary.get("changed_files")
        if not isinstance(changed, list):
            continue
        for path in changed:
            if not isinstance(path, str):
                continue
            stage_file = pilot_dir / "stage" / task_dir.name / path
            if stage_file.is_file():
                try:
                    result.setdefault(path, set()).add(_digest(stage_file.read_bytes()))
                except Exception:
                    continue
    return result


def parent_digests(paths: list[str]) -> dict[str, set[str]]:
    """U75 (docs/47 §2-2): during a merge, a file equal to HEAD's or MERGE_HEAD's version adds nothing new, because
    each parent already passed this gate. Outside a merge this returns {} so ordinary commits are unchanged."""
    merge = subprocess.run(["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"], capture_output=True, text=True)
    if merge.returncode != 0:
        return {}
    result: dict[str, set[str]] = {}
    for parent in ("HEAD", "MERGE_HEAD"):
        for path in paths:
            shown = subprocess.run(["git", "show", f"{parent}:{path}"], capture_output=True)
            if shown.returncode == 0:  # a path new in this merge has no parent version and stays gated
                result.setdefault(path, set()).add(_digest(shown.stdout))
    return result


def check(staged: dict[str, bytes], message: str, pilot_dir: Path | list[Path],
          parents: dict[str, set[str]] | None = None, ledger_rows=None) -> list[str]:
    # U123: the Calculator-Exempt line no longer skips this check; it let code bypass the audit/Ollama/review order.
    digests: dict[str, set[str]] = {path: set(found) for path, found in (parents or {}).items()}
    for directory in pilot_dir if isinstance(pilot_dir, list) else [pilot_dir]:
        for path, found in applied_digests(directory, ledger_rows or []).items():
            digests.setdefault(path, set()).update(found)
    violations: list[str] = []
    for path, content in staged.items():
        if path.startswith(GATED_PREFIX) and path.endswith(".py"):
            if _digest(content) not in digests.get(path, set()):
                violations.append(f"{path}: not an APPLIED pilot bundle with an independent PASS review (Ollama "
                                  "author, or a real failed Ollama run of the card) or equal to a merge parent")
    return violations


def audit_errors(message: str, gated_paths: list[str], agy_auto_path: Path) -> list[str]:
    """U123: new v7_harness code names the answered Antigravity audit reply it follows (`Audit: relay_<id>`)."""
    if not gated_paths:
        return []
    match = AUDIT_RE.search(message)
    if match is None:
        return ["AUDIT_FIRST: add an `Audit: relay_<id>` line naming the answered Antigravity audit reply"]
    try:
        lines = Path(agy_auto_path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return [f"AUDIT_FIRST: no Antigravity reply ledger at {agy_auto_path}"]
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("state") == "ANSWERED" and row.get("reply_id") == match.group(1):
            return []
    return [f"AUDIT_FIRST: {match.group(1)} is not an answered Antigravity reply"]


def _current_branch() -> str:
    """U130: the checked-out branch names the card when the message has no `Card:` line (fixed argv, no input)."""
    return subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True).stdout.strip()


def card_errors(message: str, new_paths: list[str], desk: Path, run_dirs, branch: str | None = None) -> list[str]:
    """U130: new runtime code belongs to a card (`Card: U##` line, else a `u<digits>` branch) whose `card audit`
    shows a real Ollama call and an Antigravity audit or review, or a verified skip row."""
    if not new_paths:
        return []
    from v7_harness import card_pipeline

    card = card_pipeline.card_of(message, _current_branch() if branch is None else branch)
    if card is None:
        return ["CARD_AUDIT: name the card with a `Card: U##` line (or commit on a u<digits> branch)"]
    result = card_pipeline.audit(desk, card, code_paths=new_paths, run_dirs=run_dirs)
    return [f"CARD_AUDIT: {card} has no {slot} evidence; use it, then `uaos card claim`, or `uaos card skip --card "
            f"{card} --slot {slot}`" for slot in result["missing"]]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Calculator gate check")
    parser.add_argument("--commit-msg", type=Path)
    parser.add_argument("--install", action="store_true", help="set git core.hooksPath to .githooks")
    # Default: every pilot work dir (.coord/pilot, .coord, .work/*). P08/P09 ran in .work/pilot_P08 and had to
    # use Calculator-Exempt although they were APPLIED pilot output.
    parser.add_argument("--pilot-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.install:
        # 새 클론은 훅이 꺼진 채 시작한다. 한 번 실행하면 이 저장소의 커밋이 관문을 거친다.
        subprocess.run(["git", "config", "core.hooksPath", ".githooks"], check=True)
        print("core.hooksPath = .githooks")
        return 0
    if args.commit_msg is None:
        parser.error("--commit-msg or --install is required")

    diff_out = subprocess.check_output(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        text=True,
    )
    staged_paths = [p for p in diff_out.splitlines() if p.strip()]

    staged: dict[str, bytes] = {}
    for path in staged_paths:
        if path.startswith(GATED_PREFIX) and path.endswith(".py"):
            staged[path] = subprocess.check_output(["git", "show", f":{path}"])

    message = args.commit_msg.read_text(encoding="utf-8")
    if args.pilot_dir is not None:
        pilot_dirs: list[Path] = [args.pilot_dir]
    else:
        from v7_harness.pilot_dirs import discover

        pilot_dirs = discover(Path("."))
    from v7_harness.coord.hook_context import shared_desk

    desk = shared_desk(Path("."))
    rows = []
    try:
        for line in (desk / ".coord" / "usage" / "runs.jsonl").read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    parents = parent_digests(list(staged))
    violations = check(staged, message, pilot_dirs, parents, ledger_rows=rows)
    new_code = [p for p, body in staged.items() if _digest(body) not in parents.get(p, set())]
    violations += audit_errors(message, new_code, desk / ".coord" / "mailbox" / "delivery" / "agy_auto.jsonl")
    card_paths = [p for p in staged_paths if p.endswith(".py") and p.startswith(CARD_GATED)]
    card_parents = parent_digests(card_paths)
    new_card_code = [p for p in card_paths
                     if _digest(subprocess.check_output(["git", "show", f":{p}"])) not in card_parents.get(p, set())]
    violations += card_errors(message, new_card_code, desk, pilot_dirs)

    for v in violations:
        print(v, file=sys.stderr)

    if violations:
        print(
            'order: Antigravity audit letter (ACTIONABLE_DELTA) -> pilot run --worker local -> pilot review '
            '--reviewer agy -> --approve -> uaos card audit; commit with "Audit: relay_<reply id>"',
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
