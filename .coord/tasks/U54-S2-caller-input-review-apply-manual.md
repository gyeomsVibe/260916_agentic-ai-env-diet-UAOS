```contract
work_id: U54-S2
worker: apply
goal: Human review of the 21 CALLER_INPUT execution sites from docs/50: decide for each whether model output can become the executable or a shell command, record the verdicts in docs/51, and pin them with a test so a new site forces a new review.
inputs:
- docs/50_u54-tool-execution-firewall-gap-audit.md sha256=a3bd3adbb096f7f6424e0acb1404311429f19c7bcd5c999fa768862a4e80a775
- v7_harness/firewall_audit.py sha256=6919ec12d4fcb181c973afe928799122f8b596a534f392e01b4205b5d442c160
allow:
- docs/51_u54-s2-caller-input-review.md
- tests/test_u54_s2_caller_review.py
acceptance: C:/Python314/python.exe -m unittest tests.test_u54_s2_caller_review tests.test_u54_firewall_audit
forbidden: design changes; edits outside allow; weakening or deleting existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Card: U54-S2 (PLAN, owner codex/user). Taken by the acting conductor under the user's order of 2026-09-28 ('프로젝트 완성될때까지 논스톱 무승인 진행하라'); judge claude (ACTING), Codex re-reviews. Method: read each site's call path on 1685100. Result: command injection 0, DATA_ARG 9 (fixed binary, model text only as one argv value or stdin, no shell), FIXED_PLAN 9 (code-built commands), OPERATOR_COMMAND 3 (receipt-run, olla squeeze, git_worktree fixture; behind platform permission). So no POLICY_DENIED gate has a site to guard now. Test pins per-file CALLER_INPUT counts to the reviewed set and the doc's verdict rows (9/9/3), and GAP stays 0. Red on HEAD (missing module/doc), 9 OK with docs/50 test.

===FILE: docs/51_u54-s2-caller-input-review.md===
# U54-S2 — CALLER_INPUT 21곳 검토: 모델 출력이 실행 명령이 되는 곳이 있는가

> 상태: DONE-ACTING. 작성·판정은 Codex 부재 중 대행한 Claude다. 복귀한 Codex가 재검토한다(`.coord/codex_return_checklist.md`).
> 기준 트리: `origin/claude/docs49-corrections-acting`(1685100). 대상 목록: `docs/50_u54-tool-execution-firewall-gap-audit.md`의 CALLER_INPUT 21행.

## 1. 왜 이 검토가 필요한가 (초보자용 설명)

`docs/50`의 감사기(audit, `v7_harness/firewall_audit.py`)는 코드에서 외부 프로그램을 실행하는 곳(`subprocess.run`, `Popen` 등)을 모두 찾는다.
실행 인자가 코드 안에 고정돼 있으면 FIXED, 같은 함수 안에서 허용 목록 검사가 먼저 돌면 GUARDED로 스스로 분류한다.
감사기가 혼자 판단할 수 없는 곳이 CALLER_INPUT이다. 실행 인자가 **함수를 부른 쪽**에서 들어오기 때문이다.
이런 곳은 사람이(여기서는 대행 판정자가) 호출 경로를 거슬러 올라가 "모델이 쓴 글자가 **실행할 프로그램이나 셸 명령**이 될 수 있는가"를 확인해야 한다.

구분해야 할 두 경우:

- **데이터 인자(data argument)**: 실행 파일은 코드가 정한다(예: `claude`, `codex`, `git`). 모델이 쓴 글은 그 프로그램에 넘기는 프롬프트·메시지 문자열일 뿐이다. 셸(shell)을 거치지 않으므로 글 안에 `; rm -rf`가 있어도 명령으로 실행되지 않는다.
- **명령 주입(command injection)**: 모델이 쓴 글이 실행 파일 이름이 되거나, `shell=True`로 셸에 넘어가거나, 옵션(`--something`)으로 해석되는 경우다. 방화벽(POLICY_DENIED fail-closed 관문)이 필요한 곳은 이쪽이다.

## 2. 판정 요약

- 모델 출력이 실행 파일·셸 명령이 되는 곳(명령 주입): **0곳**
- 고정 실행 파일 + 모델 글은 데이터 인자로만 전달(DATA_ARG): **9곳**
- 코드가 만든 고정 명령, 호출자는 값 몇 개만 채움(FIXED_PLAN): **9곳**
- 사람 운영자(operator)가 명령을 직접 넘기는 도구(OPERATOR_COMMAND): **3곳**
- 따라서 U54-S2 결론: 지금 코드에는 POLICY_DENIED 관문을 새로 끼울 **실행 지점이 없다**. 새 CALLER_INPUT 지점이 생기면 `tests/test_u54_s2_caller_review.py`가 실패해서 이 검토를 다시 하게 만든다.

## 3. 21곳 개별 판정

| 지점 | 판정 | 근거(무엇이 실행되고 모델 글은 어디로 가나) |
|---|---|---|
| `adapters/claude_worker.py:170` | DATA_ARG | `worker_command()`가 `claude` 실행 파일과 고정 옵션을 만든다. 프롬프트는 argv 한 칸 또는 stdin으로만 간다. 셸 없음. |
| `adapters/lane_worker.py:78` | DATA_ARG | `lane_command()`가 Ollama 실행 명령을 만든다. 프롬프트는 argv 한 칸 또는 stdin. |
| `coord/deliver.py:71` | DATA_ARG | `codex queue --thread <id> --message <편지>`. 편지 본문은 `--message` 값 한 칸이다. |
| `coord/deliver.py:195` | DATA_ARG | `claude -p <편지> --output-format json`. 편지는 `-p` 값 한 칸, `--allowedTools`는 발신 코드의 설정값이다. |
| `review.py:128` | DATA_ARG | `review_command()`가 `claude` 고정 명령을 만들고 검토 프롬프트는 값 또는 stdin이다. |
| `review.py:140` | DATA_ARG | 재시도 때 `--resume <session_id>`를 붙인다. session_id는 제공자(provider) JSON에서 오지만 옵션 값 한 칸이고 실행 파일이 아니다. |
| `judge.py:166` | DATA_ARG | `run_resolved()`는 argv[0]을 PATH에서 찾기만 한다. 부르는 쪽(`pilot judge`)의 argv[0]은 `codex`/`agy` 고정, 판정 프롬프트는 값이다. |
| `execution/agy_launcher.py:85` | DATA_ARG | `argv = self.agy_command + built[1:]`. `agy_command`는 설정의 고정 실행 파일, 뒤는 프롬프트 값이다. 너무 긴 프롬프트는 실행 전에 PROMPT_TOO_LONG_FOR_ARGV로 거부된다. |
| `olla.py:945` | DATA_ARG | `python -m v7_harness.olla handoff --transcript <경로> --cwd <경로> --session <id>`. 훅 페이로드 값이 옵션 값으로만 간다. |
| `coord/notify.py:219` | FIXED_PLAN | `command`는 notify가 스스로 만든 `codex` 명령이다. argv[0]만 `shutil.which`로 실제 경로로 바꾼다. |
| `deploy_pc.py:219` | FIXED_PLAN | 배포 계획의 `git add -- <영수증 경로>`. 경로는 코드가 정한 영수증 파일이다. |
| `deploy_pc.py:237` | FIXED_PLAN | 배포 단계 목록(`steps`)은 `deploy_pc`가 코드로 만든다. push 단계에만 ALLOW_PUSH를 준다. 원격 쓰기는 사람 승인 경계다. |
| `global_install.py:417` | FIXED_PLAN | `schtasks /Create …`, `schtasks /Run …`. 작업 이름과 .cmd 경로는 설치기가 정한다. |
| `rsi_release.py:674` | FIXED_PLAN | `rsi schedule`의 예약 작업 명령. 기본 드라이런이고 `--apply`에서만 실행된다. |
| `execution/launcher.py:117` | FIXED_PLAN | `taskkill /F /T /PID <pid>`. pid는 이 프로세스가 띄운 자식이다. |
| `execution/launcher.py:211` | FIXED_PLAN | `python -c <script>`. script는 `build_worker_script()`가 만든 고정 템플릿이다(`custom_script`는 시험용 인자). |
| `olla.py:562` | FIXED_PLAN | `python -m v7_harness.olla digest -f <파일 경로>`. 경로 한 칸만 바뀐다. |
| `judge.py:328` | FIXED_PLAN | 승인 시 `python -m v7_harness.cli pilot run … --approve <bundle_id>`. 모든 값은 판정 기록에서 오고, 승인 관문이 digest·범위·비용을 다시 검사한다. |
| `proof_receipt.py:187` | OPERATOR_COMMAND | `receipt-run -- <명령>`은 운영자가 입력한 명령을 실행하고 영수증을 남기는 도구다. 모델이 이것을 부르려면 자기 셸 도구를 써야 하고, 그 셸 호출은 플랫폼 권한(permission) 관문을 먼저 통과한다. |
| `olla.py:1082` | OPERATOR_COMMAND | `olla squeeze <스크립트>`는 운영자가 지정한 스크립트를 bash로 돌리고 출력만 줄인다. 위와 같은 이유로 플랫폼 권한 관문 뒤에 있다. |
| `isolation/git_worktree.py:62` | OPERATOR_COMMAND | `git <인자들>`. 호출자는 격리 시험 도구이며 base_commit·branch 값을 넘긴다. 모델 출력 경로는 없다. 참고: 값이 `-`로 시작하면 git 옵션으로 읽힐 수 있으니, 이 함수를 모델 입력에 연결하는 변경이 생기면 그때 `--end-of-options` 또는 값 검증을 함께 넣는다. |

## 4. 남은 위험과 다음 관문

- **범위 한계**: 이 판정은 1685100 트리 기준이다. 새 실행 지점은 `tests/test_u54_firewall_audit.py`(요약 수)와 `tests/test_u54_s2_caller_review.py`(파일별 CALLER_INPUT 수)가 잡는다.
- **DATA_ARG의 남은 위험**: 명령 주입은 아니지만, 모델 글이 **다른 에이전트의 프롬프트**가 되는 곳이다(`deliver`, `review`). 여기서의 위험은 프롬프트 주입(prompt injection)이며, 받는 쪽의 권한 모드·허용 도구 목록(`--allowedTools`)과 UAOS 인수(acceptance) 관문이 막는다. 실행 방화벽이 다룰 대상이 아니다.
- **OPERATOR_COMMAND**: 운영자 도구는 원래 명령을 실행하려고 만든 것이다. 막는 곳은 이 코드가 아니라 모델의 셸 호출을 허가하는 플랫폼 권한 설정이다. UAOS는 그 설정을 약하게 만들지 않는다(전역 규칙).
- **U54 3단계(POLICY_DENIED 관문)**: 명령 주입 지점이 0이므로 지금 끼울 곳이 없다. 새로 GAP이나 명령 주입 판정이 생기면 그 지점에 fail-closed 관문을 넣는 카드로 다시 연다.
===FILE: tests/test_u54_s2_caller_review.py===
"""U54-S2: every CALLER_INPUT site has a human review in docs/51; a new or moved one fails until it is reviewed.

Counts per file, not line numbers: an unrelated edit above a call shifts its line without changing what can run.
"""

from __future__ import annotations

import unittest
from collections import Counter
from pathlib import Path

from v7_harness.firewall_audit import audit

ROOT = Path(__file__).resolve().parents[1]
REVIEW_DOC = ROOT / "docs" / "51_u54-s2-caller-input-review.md"
# The 21 CALLER_INPUT sites reviewed in docs/51 on 1685100 (verdicts: DATA_ARG 9, FIXED_PLAN 9, OPERATOR_COMMAND 3).
REVIEWED = {
    "v7_harness/adapters/claude_worker.py": 1,
    "v7_harness/adapters/lane_worker.py": 1,
    "v7_harness/coord/deliver.py": 2,
    "v7_harness/coord/notify.py": 1,
    "v7_harness/deploy_pc.py": 2,
    "v7_harness/execution/agy_launcher.py": 1,
    "v7_harness/execution/launcher.py": 2,
    "v7_harness/global_install.py": 1,
    "v7_harness/isolation/git_worktree.py": 1,
    "v7_harness/judge.py": 2,
    "v7_harness/olla.py": 3,
    "v7_harness/proof_receipt.py": 1,
    "v7_harness/review.py": 2,
    "v7_harness/rsi_release.py": 1,
}
VERDICTS = ("DATA_ARG", "FIXED_PLAN", "OPERATOR_COMMAND")


class CallerInputReviewTest(unittest.TestCase):
    def test_every_caller_input_site_is_reviewed(self):
        found = Counter(s.path for s in audit(ROOT) if s.status == "CALLER_INPUT")
        self.assertEqual(REVIEWED, dict(found),
                         "a CALLER_INPUT site was added, moved or removed: review it in docs/51, then update REVIEWED")

    def test_review_doc_has_one_verdict_row_per_site(self):
        rows = [ln for ln in REVIEW_DOC.read_text(encoding="utf-8").splitlines()
                if ln.startswith("| `") and any(f"| {v} |" in ln for v in VERDICTS)]
        per_file = Counter("v7_harness/" + ln.split("`")[1].rsplit(":", 1)[0] for ln in rows)
        self.assertEqual(REVIEWED, dict(per_file))
        self.assertEqual({"DATA_ARG": 9, "FIXED_PLAN": 9, "OPERATOR_COMMAND": 3},
                         dict(Counter(v for ln in rows for v in VERDICTS if f"| {v} |" in ln)))

    def test_no_command_injection_verdict_and_no_gap(self):
        self.assertEqual([], [s for s in audit(ROOT) if s.status == "GAP"])


if __name__ == "__main__":
    unittest.main()
===END===

## Output

- Reply with ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.
