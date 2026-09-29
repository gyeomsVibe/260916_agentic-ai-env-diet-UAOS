```contract
work_id: U91
worker: apply
goal: Make install --check report a scheduled sentinel that runs a checkout instead of the installed runtime.
inputs:
- .coord/PLAN.md sha256=adec2d7a18c6ee18da9d9a592d5061f8d94c67591527b50c180627915d607a64
- v7_harness/global_install.py sha256=75ffcac4a312178067296b5c897877a04755e4f280a17cd61ab599ba90e52a97
allow:
- v7_harness/global_install.py
- tests/test_u91_stale_sentinel_task.py
- .coord/PLAN.md
acceptance: python -m unittest tests.test_u91_stale_sentinel_task tests.test_u90_canon_note tests.test_u87_uaos_rsi_name tests.test_u37_install_everywhere tests.test_u45_general_uaos
forbidden: design changes; edits outside allow; weakening or deleting existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the EDIT blocks exactly. The new test pins which scheduled tasks are stale and that --check counts them.

===EDIT: v7_harness/global_install.py===
<<<<<<< SEARCH
# ---------------------------------------------------------------- entry point

=======
# U91: the query uses PowerShell property names, which (unlike schtasks CSV headers) are not translated.
SENTINEL_TASK_QUERY = (
    "Get-ScheduledTask | ForEach-Object { [pscustomobject]@{ name = $_.TaskName; "
    "run = (($_.Actions | ForEach-Object { \"$($_.Execute) $($_.Arguments)\" }) -join ' | ') } } "
    "| ConvertTo-Json -Compress"
)
STALE_SENTINEL_ADVICE = (
    "Replace it: run this installer with --register-sentinel <project> --apply (the runtime sentinel at every logon), "
    "then delete the old task in Task Scheduler. Changing scheduled tasks waits for the user."
)


def stale_sentinel_tasks(*, run: Callable[..., Any] = subprocess.run, system: str | None = None) -> list[dict[str, str]] | None:
    """U91: scheduled tasks that start `coord sentinel` from a checkout instead of the installed runtime.

    Seen 2026-09-29: a hand-made "UAOS Sentinel 30m" task ran `python -m v7_harness.cli coord sentinel` in the desk
    checkout, dozens of merges behind, so the U88 P1 fix never reached the always-on sentinel, and its loop lock made
    the runtime sentinel skip with ALREADY_RUNNING. Only the launcher (~/.uaos/uaos.py, through the sentinel_*.cmd this
    installer writes) follows reinstalls. None means the query failed: unknown, never reported as clean.
    """
    system = system or platform.system()
    if system != "Windows":
        return []
    try:
        # 60 s: Get-ScheduledTask over a few hundred tasks took about 2 s here; the margin covers a cold PowerShell.
        done = run(["powershell", "-NoProfile", "-Command", SENTINEL_TASK_QUERY], capture_output=True, text=True,
                   timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0 or not (done.stdout or "").strip():
        return None
    try:
        data = json.loads(done.stdout)
    except json.JSONDecodeError:
        return None
    # ConvertTo-Json writes a single task as an object, several as a list.
    tasks = data if isinstance(data, list) else [data]
    stale = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        command = str(task.get("run") or "")
        if "coord sentinel" in command and "uaos.py" not in command:
            stale.append({"name": str(task.get("name")), "run": command[:300]})
    return stale


# ---------------------------------------------------------------- entry point

>>>>>>> REPLACE
===EDIT: v7_harness/global_install.py===
<<<<<<< SEARCH
    if args.check:
        output["drift"] = [c.target for c in pending]
        code = 1 if pending else 0

=======
    if args.check:
        output["drift"] = [c.target for c in pending]
        code = 1 if pending else 0
        # U91: scheduled tasks belong to this PC's real user; a test or staging --home has none to check.
        if Path(args.home).resolve() == Path.home().resolve():
            stale = stale_sentinel_tasks()
            if stale is None:
                output["sentinel_tasks"] = "UNKNOWN"
            elif stale:
                output["drift"] += [f"stale sentinel task: {task['name']}" for task in stale]
                output["stale_sentinel_advice"] = STALE_SENTINEL_ADVICE
                code = 1

>>>>>>> REPLACE
===EDIT: .coord/PLAN.md===
<<<<<<< SEARCH
| U90 | DONE-DELEGATED (사용자 지시 2026-09-29 '너는 codex' — Claude가 Codex 권한으로 수행, Codex 복귀 시 재검토) | claude(설계) · apply(0토큰) | 실사용 영수증: v6.0.0·U88 병합 뒤 설치 점검 2회 모두 '규칙 블록을 정본에도 넣으라'는 낡은 안내 출력. v6.0.0부터 정본이 core.md·adapters로 UAOS-RSI를 직접 담으므로 안내를 따르면 규칙이 중복되고 크기 상한을 넘는다. 안내를 `NOTES` 상수로 바꿔 정본 원본 수정을 가리키고, 정본 없는 PC의 변경 설명도 고침. — `v7_harness/global_install.py`, `tests/test_u90_canon_note.py` |

=======
| U90 | DONE-DELEGATED (사용자 지시 2026-09-29 '너는 codex' — Claude가 Codex 권한으로 수행, Codex 복귀 시 재검토) | claude(설계) · apply(0토큰) | 실사용 영수증: v6.0.0·U88 병합 뒤 설치 점검 2회 모두 '규칙 블록을 정본에도 넣으라'는 낡은 안내 출력. v6.0.0부터 정본이 core.md·adapters로 UAOS-RSI를 직접 담으므로 안내를 따르면 규칙이 중복되고 크기 상한을 넘는다. 안내를 `NOTES` 상수로 바꿔 정본 원본 수정을 가리키고, 정본 없는 PC의 변경 설명도 고침. — `v7_harness/global_install.py`, `tests/test_u90_canon_note.py` |
| U91 | DONE-DELEGATED (사용자 지시 2026-09-29 '너는 codex' — Claude가 Codex 권한으로 수행, Codex 복귀 시 재검토) | claude(설계) · apply(0토큰) | P1 영수증(2026-09-29 12:53): U88 병합 뒤 P1 wake 재발. 원인: 수동 예약 작업 'UAOS Sentinel 30m'이 데스크 체크아웃(768a1e9, 수십 병합 뒤)에서 `python -m v7_harness.cli coord sentinel`을 실행하고, 그 루프 잠금 때문에 런타임 감시자(sentinel_*.cmd)가 로그온마다 ALREADY_RUNNING으로 건너뜀. `--check`가 런타임(uaos.py)을 쓰지 않는 감시자 예약 작업을 드리프트로 보고(질의 실패는 UNKNOWN). 예약 작업 교체 자체는 사람 경계라 윤겸스 승인 대기. — `v7_harness/global_install.py`, `tests/test_u91_stale_sentinel_task.py` |

>>>>>>> REPLACE
===FILE: tests/test_u91_stale_sentinel_task.py===
"""U91: `--check` reports a scheduled sentinel that runs a checkout instead of the installed runtime.

Seen 2026-09-29: after U88 merged, the P1 wake came back. A hand-made "UAOS Sentinel 30m" task ran
`python -m v7_harness.cli coord sentinel` in the desk checkout, dozens of merges behind, and its loop lock made the
runtime sentinel (sentinel_*.cmd via ~/.uaos/uaos.py) skip with ALREADY_RUNNING at every logon.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from v7_harness import global_install
from v7_harness.global_install import stale_sentinel_tasks

STALE = {"name": "UAOS Sentinel 30m",
         "run": 'C:\\Python314\\python.exe -m v7_harness.cli coord sentinel --project "D:\\p" --loop --interval 1800'}
CURRENT = {"name": "UAOS Sentinel p", "run": "C:\\Users\\u\\.uaos\\sentinel_p.cmd "}
LAUNCHER = {"name": "UAOS direct", "run": 'python.exe "C:\\Users\\u\\.uaos\\uaos.py" coord sentinel --project "D:\\p"'}
OTHER = {"name": "Backup", "run": "robocopy a b"}


class _Done:
    def __init__(self, returncode: int, stdout: str) -> None:
        self.returncode, self.stdout, self.stderr = returncode, stdout, ""


def _run(payload: object, returncode: int = 0):
    def run(argv, **_kwargs):
        return _Done(returncode, payload if isinstance(payload, str) else json.dumps(payload))
    return run


class StaleSentinelTaskTests(unittest.TestCase):
    def test_only_a_checkout_sentinel_is_stale(self) -> None:
        found = stale_sentinel_tasks(run=_run([STALE, CURRENT, LAUNCHER, OTHER]), system="Windows")
        self.assertEqual(["UAOS Sentinel 30m"], [task["name"] for task in found])

    def test_a_single_task_object_is_read(self) -> None:
        self.assertEqual(1, len(stale_sentinel_tasks(run=_run(STALE), system="Windows")))

    def test_a_failed_query_is_unknown_not_clean(self) -> None:
        self.assertIsNone(stale_sentinel_tasks(run=_run("", returncode=1), system="Windows"))
        self.assertIsNone(stale_sentinel_tasks(run=_run("not json"), system="Windows"))
        self.assertEqual([], stale_sentinel_tasks(run=_run([STALE]), system="Linux"))

    def test_check_counts_a_stale_task_as_drift(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            with mock.patch.object(global_install, "stale_sentinel_tasks", return_value=[STALE]), \
                    mock.patch.object(global_install.Path, "home", return_value=home), redirect_stdout(io.StringIO()) as out:
                code = global_install.main(["--check", "--no-rules", "--home", str(home)])
            report = json.loads(out.getvalue())
            self.assertEqual(1, code)
            self.assertIn("stale sentinel task: UAOS Sentinel 30m", report["drift"])
            self.assertIn("--register-sentinel", report["stale_sentinel_advice"])

    def test_check_with_another_home_does_not_query_this_pc(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(global_install, "stale_sentinel_tasks", side_effect=AssertionError("queried")), \
                    redirect_stdout(io.StringIO()):
                global_install.main(["--check", "--no-rules", "--home", d])


if __name__ == "__main__":
    unittest.main()
===END===

## Output

- Reply with ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.
