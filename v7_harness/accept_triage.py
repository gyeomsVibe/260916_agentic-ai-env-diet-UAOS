"""U18: 인수(acceptance) 실패를 CODE / INFRA / UNKNOWN 으로 나눈다.

cascade 는 REWORK 면 lane 으로 한 번 더 보낸다. 실패가 작업자 코드 탓이 아니라 환경 탓(INFRA)이면
lane 도 같은 이유로 실패하므로 보내지 않고 BLOCKED 로 멈춘다.

잘못 분류했을 때의 비용이 비대칭이다.
- INFRA 를 CODE 로 보면: lane 1회 낭비(지금과 같은 동작).
- CODE 를 INFRA 로 보면: 고칠 기회를 잃는다(지금보다 나빠짐).
그래서 INFRA 는 "작업 대상 코드가 거의 만들 수 없는" 강한 신호가 있을 때만 붙이고, 나머지는
UNKNOWN 으로 둬 지금처럼 승격시킨다. 시간 초과(124)는 작업자가 무한 루프를 넣어도 나므로 UNKNOWN.
connection refused·PermissionError 는 테스트 대상 코드가 흔히 내므로 INFRA 신호에서 뺐다
(260912 R2 반례: "Retry 3 failed: Connection refused" 가 코드 실패 로그 안에 섞여 판정을 뒤집었다).
실측 근거: U17 e2e 실패 로그 15건은 전부 코드 결함(SyntaxError 12·AssertionError 2·NameError 1)이었다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

# 코드 결함 신호. 하나라도 있으면 CODE — 환경 어휘가 섞여 있어도 이긴다.
# unittest 의 "FAILED (errors=N)" 은 넣지 않는다: 테스트 모듈 import 실패(PYTHONPATH)도 errors 로 집계된다.
_CODE = [re.compile(p, re.MULTILINE) for p in (
    r"\bAssertionError\b",
    r"^FAIL: ",
    r"^FAILED \(.*\bfailures=\d+",
    r"^\s*E\s+assert\b",
    r"^=+ .*\b\d+ failed\b.*=+\s*$",
    r"^(SyntaxError|IndentationError|NameError|TypeError|AttributeError|ValueError|KeyError|IndexError"
    r"|ZeroDivisionError|RecursionError|UnboundLocalError)\b",
    r"^ImportError: cannot import name\b",
)]

# U85: a traceback's final line naming an exception by its module path, e.g. `v7_harness.coord.stream.StreamRejected:`.
_QUALIFIED_EXC = re.compile(r"^((?:[A-Za-z_]\w*\.)+)[A-Za-z_]\w*: ", re.MULTILINE)
_MISSING_MODULE = re.compile(r"ModuleNotFoundError: No module named '([^']+)'")
_MISSING_FILE = re.compile(r"can't open file '([^']+)': \[Errno 2\]")
# 환경 신호(강함). 테스트 대상 코드가 내기 어려운 것만 둔다.
# 테스트 코드가 SQLite 트랜잭션·파일 핸들을 누수시킬 수 있어 잠금/핸들 오류는 INFRA에서 제외(UNKNOWN으로 분류).
_INFRA = [re.compile(p, re.IGNORECASE) for p in (
    r"is not recognized as an internal or external command",
    r": command not found",
    r"EADDRINUSE|address already in use|WinError 10048",
    r"No space left on device|ENOSPC",
    r"DLL load failed",
)]


def _module_cls(name: str, staging: Path | None, changed_files: list[str], changed_texts: list[str]) -> str:
    parts = name.split(".")
    if staging is not None:
        rel = Path(*parts)
        if (staging / rel).is_dir() or (staging / rel.with_suffix(".py")).is_file():
            # 모듈 파일은 있는데 import 가 안 된다 → 경로(PYTHONPATH·cwd) 문제. U17 에서 실제로 났다.
            return "INFRA"
    stems = {Path(p).stem for p in changed_files} | {Path(p).parent.name for p in changed_files}
    if any(part in stems for part in parts):
        return "CODE"  # 작업자가 그 모듈을 지우거나 옮겼다
    if any(re.search(rf"^\s*(import|from)\s+{re.escape(parts[0])}\b", t, re.MULTILINE) for t in changed_texts):
        return "CODE"  # 작업자가 없는 패키지를 import 했다
    return "INFRA"  # 작업자와 무관한 패키지가 환경에 없다


def _project_exception(output: str, staging: Path | None) -> str | None:
    """U85: the first exception whose defining module is a staged file: the code under test or its test raised it.

    Seen 2026-09-29: U83 (MailboxRejected) and U84-F1 (StreamRejected) were UNKNOWN, so RSI reported a recurring cause
    with no remedy. Library exceptions (sqlite3, subprocess) are not staged files and stay UNKNOWN.
    """
    if staging is None:
        return None
    for m in _QUALIFIED_EXC.finditer(output):
        module = Path(*m.group(1).rstrip(".").split("."))
        if (staging / module.with_suffix(".py")).is_file() or (staging / module / "__init__.py").is_file():
            return m.group(0).strip()
    return None


def classify(output: str, exit_code: int | None, changed_files: Iterable[str] = (),
             changed_texts: Iterable[str] = (), staging: Path | None = None) -> tuple[str, str]:
    """Return (class, signature). class is CODE, INFRA or UNKNOWN."""
    changed_files, changed_texts = list(changed_files), list(changed_texts)
    for pat in _CODE:
        m = pat.search(output)
        if m:
            return "CODE", m.group(0).strip()[:120]
    signature = _project_exception(output, staging)
    if signature:
        return "CODE", signature[:120]
    m = _MISSING_MODULE.search(output)
    if m:
        return _module_cls(m.group(1), staging, changed_files, changed_texts), m.group(0)[:120]
    m = _MISSING_FILE.search(output)
    if m:
        # staging 내부면 작업자가 생성해야 할 파일 누락(CODE), 외부면 환경 결함(INFRA)으로 분류.
        if staging is not None:
            raw_path = Path(m.group(1))
            resolved = raw_path.resolve() if raw_path.is_absolute() else (Path(staging) / raw_path).resolve()
            is_inside = resolved.is_relative_to(Path(staging).resolve())
            return ("CODE" if is_inside else "INFRA"), m.group(0)[:120]
        worker_moved = Path(m.group(1)).name in {Path(p).name for p in changed_files}
        return ("CODE" if worker_moved else "INFRA"), m.group(0)[:120]
    for pat in _INFRA:
        m = pat.search(output)
        if m:
            return "INFRA", m.group(0)[:120]
    if exit_code == 124:
        return "UNKNOWN", "acceptance timeout"
    return "UNKNOWN", ""
