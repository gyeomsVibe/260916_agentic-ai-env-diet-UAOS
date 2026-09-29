```contract
work_id: U85
worker: apply
goal: Classify an acceptance error raised as a staged project's own exception as CODE instead of UNKNOWN.
inputs:
- .coord/PLAN.md sha256=5b35d46f770823e556d611a34b393772cbded113f76ddc320c56f57b8321bf0b
- v7_harness/accept_triage.py sha256=88cdf5d6248dda38ffbe573888f1f496f7eda8dad20a6af6ff6c9dddfa277980
- tests/test_u18_accept_triage.py sha256=69ac89e36e2c950c5afe11ffdb6820a9ed423363baa9472e35bd25ca6490bf58
allow:
- v7_harness/accept_triage.py
- tests/test_u85_project_exception.py
- .coord/PLAN.md
acceptance: python -m unittest tests.test_u85_project_exception tests.test_u18_accept_triage
forbidden: design changes; edits outside allow; weakening or deleting existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the EDIT blocks exactly. The two real UNKNOWN logs become the reproducing tests.

===EDIT: v7_harness/accept_triage.py===
<<<<<<< SEARCH
_MISSING_MODULE = re.compile(r"ModuleNotFoundError: No module named '([^']+)'")

=======
# U85: a traceback's final line naming an exception by its module path, e.g. `v7_harness.coord.stream.StreamRejected:`.
_QUALIFIED_EXC = re.compile(r"^((?:[A-Za-z_]\w*\.)+)[A-Za-z_]\w*: ", re.MULTILINE)
_MISSING_MODULE = re.compile(r"ModuleNotFoundError: No module named '([^']+)'")

>>>>>>> REPLACE
===EDIT: v7_harness/accept_triage.py===
<<<<<<< SEARCH
def classify(output: str, exit_code: int | None, changed_files: Iterable[str] = (),

=======
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

>>>>>>> REPLACE
===EDIT: v7_harness/accept_triage.py===
<<<<<<< SEARCH
            return "CODE", m.group(0).strip()[:120]
    m = _MISSING_MODULE.search(output)

=======
            return "CODE", m.group(0).strip()[:120]
    signature = _project_exception(output, staging)
    if signature:
        return "CODE", signature[:120]
    m = _MISSING_MODULE.search(output)

>>>>>>> REPLACE
===EDIT: .coord/PLAN.md===
<<<<<<< SEARCH
| U84-F1 | DONE-DELEGATED (Codex LIMITED 중 Claude 권한대행 2026-09-29 — Codex 복귀 시 재검토) | claude(대행 설계) · apply(0토큰) · codex(반례 제공) | U84 Codex REJECT 2건 수정(`.work/u84_verdict/verdict.txt`): (1) 워크트리에서 `archive_settled`가 데스크를 바꾼 뒤 `relative_to`로 실패 → `os.path.relpath`(재현 1/1), (2) 공유된 표본 파일을 잠금 밖에서 동시 기록 → 스트림 잠금 안으로(12코어 부하 8회 중 1회 48→47 재현). — `v7_harness/coord/stream.py`, `tests/test_u84_stream_desk.py` |

=======
| U84-F1 | DONE-DELEGATED (Codex LIMITED 중 Claude 권한대행 2026-09-29 — Codex 복귀 시 재검토) | claude(대행 설계) · apply(0토큰) · codex(반례 제공) | U84 Codex REJECT 2건 수정(`.work/u84_verdict/verdict.txt`): (1) 워크트리에서 `archive_settled`가 데스크를 바꾼 뒤 `relative_to`로 실패 → `os.path.relpath`(재현 1/1), (2) 공유된 표본 파일을 잠금 밖에서 동시 기록 → 스트림 잠금 안으로(12코어 부하 8회 중 1회 48→47 재현). — `v7_harness/coord/stream.py`, `tests/test_u84_stream_desk.py` |
| U85 | DONE-DELEGATED (Codex LIMITED 중 Claude 권한대행 2026-09-29 — Codex 복귀 시 재검토) | claude(대행 설계) · apply(0토큰) | RSI 검토 `rsi_review_apply_10x15`(apply 반복 원인 UNKNOWN 2회: U83·U84-F1) 대응: 인수 로그의 예외가 스테이징된 모듈에서 정의된 프로젝트 예외(`MailboxRejected`·`StreamRejected`)면 CODE로 분류한다. sqlite3·subprocess 같은 라이브러리 예외는 UNKNOWN 유지. 같은 창의 CODE 2회(U84·U84-F1-R1)는 대행자 테스트 작성 오류를 무료 dry-run 인수가 잡은 것으로 정상 동작(개선 없음). — `v7_harness/accept_triage.py`, `tests/test_u85_project_exception.py` |

>>>>>>> REPLACE
===FILE: tests/test_u85_project_exception.py===
"""U85: an acceptance error raised as the project's own exception is CODE, not UNKNOWN.

Seen 2026-09-29: U83 (`v7_harness.coord.mailbox.MailboxRejected`) and U84-F1 (`v7_harness.coord.stream.StreamRejected`)
failed their acceptance with a project exception, both from a wrong test fixture. Triage called them UNKNOWN, so the RSI
window for apply reported "recurring UNKNOWN" with no remedy on file. The exception is defined in a staged module, so it
comes from the code under test or its test, which is CODE. Library and environment exceptions stay UNKNOWN.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from v7_harness.accept_triage import classify

# Tails of the real U83 and U84-F1 acceptance logs (paths shortened).
U83 = ('ERROR: test_x (tests.test_u83_recover_lock.RecoverLockTests.test_x)\nTraceback (most recent call last):\n'
       '  File "stage\\U83\\v7_harness\\coord\\mailbox.py", line 95, in __init__\n'
       '    raise MailboxRejected("root must exist and be a directory")\n'
       'v7_harness.coord.mailbox.MailboxRejected: root must exist and be a directory\n\nFAILED (errors=4)\n')
U84F1 = ('ERROR: test_y (tests.test_u84_stream_desk.StreamDeskTest.test_y)\nTraceback (most recent call last):\n'
         '  File "stage\\U84-F1\\v7_harness\\coord\\stream.py", line 179, in _validate\n'
         '    raise StreamRejected("MISSING_EVIDENCE_CMD")\n'
         'v7_harness.coord.stream.StreamRejected: MISSING_EVIDENCE_CMD\n\nFAILED (errors=1)\n')
SQLITE = ('ERROR: test_z (tests.t.T.test_z)\nTraceback (most recent call last):\n'
          '  File "stage\\X\\v7_harness\\db.py", line 9, in put\n    conn.execute(sql)\n'
          'sqlite3.OperationalError: database is locked\n\nFAILED (errors=1)\n')


class ProjectExceptionTriageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.staging = Path(self.tmp.name)
        for module in ("v7_harness/coord/mailbox.py", "v7_harness/coord/stream.py", "v7_harness/db.py"):
            (self.staging / module).parent.mkdir(parents=True, exist_ok=True)
            (self.staging / module).write_text("", encoding="utf-8")
        (self.staging / "v7_harness" / "__init__.py").write_text("", encoding="utf-8")

    def test_real_u83_and_u84f1_logs_are_code(self) -> None:
        self.assertEqual(("CODE", "v7_harness.coord.mailbox.MailboxRejected:"),
                         classify(U83, 1, staging=self.staging))
        self.assertEqual(("CODE", "v7_harness.coord.stream.StreamRejected:"),
                         classify(U84F1, 1, staging=self.staging))

    def test_a_package_level_exception_is_code(self) -> None:
        log = "ERROR: t\nv7_harness.WorkerFailed: boom\n\nFAILED (errors=1)\n"
        self.assertEqual("CODE", classify(log, 1, staging=self.staging)[0])

    def test_library_and_environment_exceptions_stay_unknown(self) -> None:
        self.assertEqual("UNKNOWN", classify(SQLITE, 1, staging=self.staging)[0])
        log = "ERROR: t\nsubprocess.TimeoutExpired: Command 'x' timed out after 5 seconds\n\nFAILED (errors=1)\n"
        self.assertEqual("UNKNOWN", classify(log, 1, staging=self.staging)[0])

    def test_without_staging_nothing_changes(self) -> None:
        self.assertEqual("UNKNOWN", classify(U83, 1)[0])

    def test_infra_signals_still_win_over_a_bare_project_name_elsewhere(self) -> None:
        log = "'agy' is not recognized as an internal or external command\n"
        self.assertEqual("INFRA", classify(log, 1, staging=self.staging)[0])


if __name__ == "__main__":
    unittest.main()
===END===

## Output

- Reply with ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.
