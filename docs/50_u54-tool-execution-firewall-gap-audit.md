# 50. U54 도구 실행 방화벽 틈 감사 (Tool Execution Firewall Gap Audit)

> 생성 파일(generated). 손으로 고치지 않는다. 다시 만들 때: `C:/Python314/python.exe -m v7_harness.firewall_audit --write`
> 분류 규칙은 `v7_harness/firewall_audit.py` 맨 위 설명(docstring)에 고정돼 있다. 이 감사는 코드를 읽기만 하고 동작은 바꾸지 않는다(docs/49 U-SEC-1 1단계). 호출 지점을 막거나 바꾸는 일은 U54-S2의 별도 계약이다.

## 읽는 법

- 종류(kind): DIRECT는 `subprocess`·`os.system` 직접 호출, INDIRECT는 그 함수를 담은 지역 이름 호출(`runner=subprocess.run` 등, grep으로는 안 보인다), READ는 모델이 제안한 `tool_calls` 필드를 읽는 곳이다.
- 출처(source): MODEL은 모델 제안 표식(marker) 이름이 명령에 닿는 경우, CALLER는 함수 인자에서 오는 경우, FIXED는 상수·모듈 코드에서만 오는 경우다.
- 상태(status): GAP은 검사 없이 모델 제안이 실행될 수 있는 곳, CALLER_INPUT은 호출자가 무엇을 넘기느냐에 달린 곳(검토 대상), GUARDED는 같은 함수 안에서 먼저 검사가 도는 곳, PASS_THROUGH는 제안을 번역·집계만 하는 곳이다.

## 요약

- 전체 지점: 41
- GAP: 0
- CALLER_INPUT: 24
- GUARDED: 2
- FIXED: 11
- PASS_THROUGH: 4

## 전체 목록

| 파일:줄 | 종류 | 호출 | 출처 | 검사 | shell | 상태 |
|---|---|---|---|---|---|---|
| `v7_harness/adapters/claude_worker.py:173` | DIRECT | `subprocess.run` | CALLER | no | no | CALLER_INPUT |
| `v7_harness/adapters/lane_worker.py:79` | DIRECT | `subprocess.run` | CALLER | no | no | CALLER_INPUT |
| `v7_harness/calculator_gate.py:58` | DIRECT | `subprocess.run` | FIXED | no | no | FIXED |
| `v7_harness/calculator_gate.py:64` | DIRECT | `subprocess.run` | CALLER | no | no | CALLER_INPUT |
| `v7_harness/calculator_gate.py:100` | DIRECT | `subprocess.run` | FIXED | no | no | FIXED |
| `v7_harness/calculator_gate.py:106` | DIRECT | `subprocess.check_output` | FIXED | yes | no | FIXED |
| `v7_harness/calculator_gate.py:115` | DIRECT | `subprocess.check_output` | FIXED | yes | no | FIXED |
| `v7_harness/coord/deliver.py:98` | INDIRECT | `execute -> subprocess.run` | CALLER | no | no | CALLER_INPUT |
| `v7_harness/coord/deliver.py:222` | INDIRECT | `execute -> subprocess.run` | CALLER | no | no | CALLER_INPUT |
| `v7_harness/coord/desk_delta.py:35` | DIRECT | `subprocess.run` | CALLER | no | no | CALLER_INPUT |
| `v7_harness/coord/notify.py:219` | INDIRECT | `execute -> subprocess.run` | CALLER | no | no | CALLER_INPUT |
| `v7_harness/coord/thrift.py:63` | DIRECT | `subprocess.run` | CALLER | no | no | CALLER_INPUT |
| `v7_harness/coord/windows.py:46` | DIRECT | `subprocess.Popen` | FIXED | no | no | FIXED |
| `v7_harness/deploy_pc.py:222` | INDIRECT | `runner -> subprocess.run` | CALLER | no | no | CALLER_INPUT |
| `v7_harness/deploy_pc.py:240` | INDIRECT | `runner -> subprocess.run` | CALLER | no | no | CALLER_INPUT |
| `v7_harness/execution/agy_launcher.py:85` | DIRECT | `subprocess.Popen` | CALLER | no | no | CALLER_INPUT |
| `v7_harness/execution/engine.py:250` | READ | `tool_calls` | MODEL | no | no | PASS_THROUGH |
| `v7_harness/execution/launcher.py:117` | DIRECT | `subprocess.run` | CALLER | no | no | CALLER_INPUT |
| `v7_harness/execution/launcher.py:211` | DIRECT | `subprocess.Popen` | CALLER | no | no | CALLER_INPUT |
| `v7_harness/gemini_shim.py:61` | READ | `tool_calls` | MODEL | no | no | PASS_THROUGH |
| `v7_harness/gemini_shim.py:92` | READ | `tool_calls` | MODEL | no | no | PASS_THROUGH |
| `v7_harness/gemini_shim.py:159` | READ | `tool_calls` | MODEL | no | no | PASS_THROUGH |
| `v7_harness/global_install.py:527` | INDIRECT | `run -> subprocess.run` | CALLER | no | no | CALLER_INPUT |
| `v7_harness/global_install.py:567` | INDIRECT | `run -> subprocess.run` | FIXED | no | no | FIXED |
| `v7_harness/isolation/git_worktree.py:62` | DIRECT | `subprocess.run` | CALLER | no | no | CALLER_INPUT |
| `v7_harness/judge.py:166` | DIRECT | `subprocess.run` | CALLER | no | no | CALLER_INPUT |
| `v7_harness/judge.py:328` | INDIRECT | `approver -> subprocess.run` | CALLER | no | no | CALLER_INPUT |
| `v7_harness/olla.py:567` | DIRECT | `subprocess.Popen` | CALLER | no | no | CALLER_INPUT |
| `v7_harness/olla.py:967` | DIRECT | `subprocess.Popen` | CALLER | no | no | CALLER_INPUT |
| `v7_harness/olla.py:1104` | DIRECT | `subprocess.run` | CALLER | no | no | CALLER_INPUT |
| `v7_harness/pilot.py:758` | DIRECT | `subprocess.run` | CALLER | yes | yes | GUARDED |
| `v7_harness/pilot.py:767` | DIRECT | `subprocess.run` | CALLER | yes | no | GUARDED |
| `v7_harness/proof_receipt.py:187` | DIRECT | `subprocess.run` | CALLER | no | no | CALLER_INPUT |
| `v7_harness/review.py:136` | INDIRECT | `runner -> subprocess.run` | CALLER | no | no | CALLER_INPUT |
| `v7_harness/review.py:148` | INDIRECT | `runner -> subprocess.run` | CALLER | no | no | CALLER_INPUT |
| `v7_harness/rsi_release.py:674` | INDIRECT | `run -> subprocess.run` | CALLER | no | no | CALLER_INPUT |
| `v7_harness/snapshot.py:75` | DIRECT | `subprocess.run` | FIXED | no | no | FIXED |
| `v7_harness/snapshot.py:101` | DIRECT | `subprocess.run` | FIXED | no | no | FIXED |
| `v7_harness/snapshot.py:115` | DIRECT | `subprocess.run` | FIXED | no | no | FIXED |
| `v7_harness/snapshot.py:129` | DIRECT | `subprocess.run` | FIXED | no | no | FIXED |
| `v7_harness/snapshot.py:140` | DIRECT | `subprocess.run` | FIXED | no | no | FIXED |

## 틈(gaps): 검사 없이 모델 제안이 닿는 지점

- 없음

## 검토 대상(CALLER_INPUT): 호출자가 모델 출력을 넘기는지 사람이 확인할 지점

- `v7_harness/adapters/claude_worker.py:173` DIRECT `subprocess.run`
- `v7_harness/adapters/lane_worker.py:79` DIRECT `subprocess.run`
- `v7_harness/calculator_gate.py:64` DIRECT `subprocess.run`
- `v7_harness/coord/deliver.py:98` INDIRECT `execute -> subprocess.run`
- `v7_harness/coord/deliver.py:222` INDIRECT `execute -> subprocess.run`
- `v7_harness/coord/desk_delta.py:35` DIRECT `subprocess.run`
- `v7_harness/coord/notify.py:219` INDIRECT `execute -> subprocess.run`
- `v7_harness/coord/thrift.py:63` DIRECT `subprocess.run`
- `v7_harness/deploy_pc.py:222` INDIRECT `runner -> subprocess.run`
- `v7_harness/deploy_pc.py:240` INDIRECT `runner -> subprocess.run`
- `v7_harness/execution/agy_launcher.py:85` DIRECT `subprocess.Popen`
- `v7_harness/execution/launcher.py:117` DIRECT `subprocess.run`
- `v7_harness/execution/launcher.py:211` DIRECT `subprocess.Popen`
- `v7_harness/global_install.py:527` INDIRECT `run -> subprocess.run`
- `v7_harness/isolation/git_worktree.py:62` DIRECT `subprocess.run`
- `v7_harness/judge.py:166` DIRECT `subprocess.run`
- `v7_harness/judge.py:328` INDIRECT `approver -> subprocess.run`
- `v7_harness/olla.py:567` DIRECT `subprocess.Popen`
- `v7_harness/olla.py:967` DIRECT `subprocess.Popen`
- `v7_harness/olla.py:1104` DIRECT `subprocess.run`
- `v7_harness/proof_receipt.py:187` DIRECT `subprocess.run`
- `v7_harness/review.py:136` INDIRECT `runner -> subprocess.run`
- `v7_harness/review.py:148` INDIRECT `runner -> subprocess.run`
- `v7_harness/rsi_release.py:674` INDIRECT `run -> subprocess.run`
