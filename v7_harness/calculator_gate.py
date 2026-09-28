"""계산기 원칙 관문. Claude·Codex(지휘자)는 코드를 손으로 쓰지 않고
Antigravity·Ollama(계산기)에 pilot 으로 맡긴다. 커밋에 올라간 `v7_harness/` 아래 .py 파일은 APPLIED 된 pilot 결과물과
내용이 같아야 한다. 예외는 커밋 메시지의 `Calculator-Exempt: <이유>` 줄로만 허용하고 이유가 커밋에 남는다.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

GATED_PREFIX = "v7_harness/"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def applied_digests(pilot_dir: Path) -> dict[str, set[str]]:
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
          parents: dict[str, set[str]] | None = None) -> list[str]:
    exempt_pattern = re.compile(r"^Calculator-Exempt:\s*\S")
    for line in message.splitlines():
        if exempt_pattern.match(line):
            return []

    digests: dict[str, set[str]] = {path: set(found) for path, found in (parents or {}).items()}
    for directory in pilot_dir if isinstance(pilot_dir, list) else [pilot_dir]:
        for path, found in applied_digests(directory).items():
            digests.setdefault(path, set()).update(found)
    violations: list[str] = []
    for path, content in staged.items():
        if path.startswith(GATED_PREFIX) and path.endswith(".py"):
            if _digest(content) not in digests.get(path, set()):
                violations.append(f"{path}: not produced by an APPLIED pilot bundle or equal to a merge parent")
    return violations


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
    violations = check(staged, message, pilot_dirs, parent_digests(list(staged)))

    for v in violations:
        print(v, file=sys.stderr)

    if violations:
        print(
            'delegate via: python -m v7_harness.cli pilot run --worker auto --task <ID> --source . --prompt-file <md> --accept-cmd "<test>" --work-dir .coord/pilot',
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
