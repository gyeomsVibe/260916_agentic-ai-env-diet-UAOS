"""B61: 전체 회귀를 돌리고 실패 이름을 반드시 남긴다.

지난번 회귀에서 실패 1건이 났는데 출력이 섞여 이름을 잡지 못했다. 그 일이 다시 없도록
표준 출력·오류를 `.work/logs/regression-<타임스탬프>.log`에 그대로 저장하고,
실패·오류 이름만 뽑아 화면에 보여준다.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
LOG_DIR = PROJECT / ".work" / "logs"
NAME_RE = re.compile(r"^(?P<kind>FAIL|ERROR):\s*(?P<name>\S+)")


# 시험이 실제 사용자 상태를 더럽힌 일이 세 번 있었다(조율 스트림 8건, olla 사용 기록 21줄, 요약 작업 실제 기동).
# 시험 전후로 이 경로들의 상태를 비교해 바뀌면 통과여도 실패로 본다.
# ~/.cache/olla 는 동시에 돌아가는 다른 세션의 훅도 정상적으로 쓰므로 감시하면 오탐이 난다(실측: Biz항해 세션 기록 2줄).
# 대신 시험 전체를 격리 공간(OLLA_USAGE·OLLA_CACHE)에서 돌리고, 이 프로젝트의 조율 스트림과 사용 장부를 감시한다.
# 사용 장부: source_dir 를 실제 프로젝트로 둔 pilot 시험이 U27 자동 기록으로 가짜 행을 남겼다(B24_TEST·B21_SHELL).
GUARDED = (PROJECT / ".coord" / "stream", PROJECT / ".coord" / "usage")
SANDBOX = PROJECT / ".work" / "test_sandbox"


def snapshot() -> dict[str, tuple[int, int]]:
    state: dict[str, tuple[int, int]] = {}
    for root in GUARDED:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and not path.name.endswith(".lock"):
                stat = path.stat()
                state[str(path)] = (stat.st_size, stat.st_mtime_ns)
    return state


def polluted(before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]) -> list[str]:
    return sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))


# 세 도구의 훅은 `olla` 를 통해 이 코드를 부른다. 편집 도중의 원본을 바로 쓰면 다른 세션의 훅이 깨졌다
# (Biz항해 세션: 편집 중 `NameError: re`). 전체 회귀가 통과한 코드만 배포본으로 복사하고 `olla` 는 배포본을 쓴다.
RELEASE = Path(os.environ.get("OLLA_RELEASE", "D:/AI-Models/olla-release"))


def publish_release() -> Path:
    import shutil

    staging = RELEASE.with_name(RELEASE.name + ".staging")
    shutil.rmtree(staging, ignore_errors=True)
    shutil.copytree(PROJECT / "v7_harness", staging / "v7_harness",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    old = RELEASE.with_name(RELEASE.name + ".old")
    shutil.rmtree(old, ignore_errors=True)
    if RELEASE.exists():
        RELEASE.rename(old)
    staging.rename(RELEASE)
    shutil.rmtree(old, ignore_errors=True)
    return RELEASE


def main() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    before = snapshot()
    stamp = f"{datetime.now().astimezone():%Y%m%dT%H%M%S}"
    log_path = LOG_DIR / f"regression-{stamp}.log"

    SANDBOX.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, OLLA_USAGE=str(SANDBOX / "usage.jsonl"), OLLA_CACHE=str(SANDBOX / "digest"),
               OLLA_GPU_DIR=str(SANDBOX / "gpu"))
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=PROJECT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    log_path.write_text(output, encoding="utf-8")

    failures = [
        f"{match.group('kind')}: {match.group('name')}"
        for line in output.splitlines()
        if (match := NAME_RE.match(line))
    ]
    summary = next((line for line in output.splitlines() if line.startswith("Ran ")), "Ran ?")
    dirty = polluted(before, snapshot())
    verdict = "OK" if completed.returncode == 0 and not dirty else "FAILED"

    print(f"{summary} -> {verdict}")
    print(f"log: {log_path.relative_to(PROJECT)}")
    for item in failures:
        print(item)
    for path in dirty[:10]:
        print(f"POLLUTED: {path}")
    if verdict == "OK" and not RELEASE.is_absolute():
        # 기본값 `D:/…`는 Windows 절대 경로다. POSIX에서는 상대 경로가 되어 저장소 안에 `D:/` 폴더를 만들었다.
        print(f"release SKIPPED: {RELEASE} is not an absolute path on this OS (set OLLA_RELEASE)")
    elif verdict == "OK":
        try:
            print(f"release: {publish_release()}")
        except OSError as exc:  # 배포 실패는 시험 결과를 바꾸지 않되 숨기지 않는다
            print(f"release FAILED: {exc}")
    return completed.returncode or (5 if dirty else 0)


if __name__ == "__main__":
    raise SystemExit(main())
