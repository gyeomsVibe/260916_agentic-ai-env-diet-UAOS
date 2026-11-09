# UAOS 실제 운영 감사 — 논스톱 복구 및 독식항해 Package A

- 사용자 지시: 올라마·안티그래비티를 이용하는 이번 과정의 모든 관측 오류를 이 UAOS 프로젝트에 기록.
- 작업: 공유 코어 설치·배포 복구와 독식항해 v2.4 최종 Package A 제작. 이번 범위의 오류를 기록하며 미관측 오류까지 전수 확인했다고 주장하지 않음.
- 원장: UAOS_WAIT_WITH_ACTIONABLE_HANDOFF_20261009.md와 coord stream. 이 문서는 실측·실패·미확인 구분 대장.

| 사건 | 관측 증거 | 상태/조치 |
|---|---|---|
| UAOS-NEXT-FALSE-DONE | 활성 인계·M2 READY에도 세 도구 DONE/no schedule, Git 공통 루트로 중첩 프로젝트 합침 | 재현; 공유 next_card.py 수정 후보, 81 초점 회귀 OK, 독립 검토·설치 대기 |
| USER-RESTART-DEPENDENCY | 사용자: 무승인 논스톱 티키타카가 안 되는 것도 오류 | 오류 접수; 설치·배포까지 사용자 재시작 요청 없이 진행 |
| OLLAMA-CODE-DRAFT-INVALID | 로컬 초안에 find_project 누락, undefined main/scoped, git 인자 오류, 잘못된 Path 호출 | 소스 반영 전 거부; 작은 결정적 apply 경로로 전환 |
| MANUAL-LINT-INVALID-WORKER | UNKNOWN_WORKER:codex / JUDGE_NOT_ALLOWED / INPUT_UNPINNED | 계약 형식 정정; 테스트/게이트 완화 없음 |
| MANUAL-LINT-NO-BLOCKS | apply 계약에 ===EDIT 블록 없어서 실패 | 실제 원문 기반 두 블록 추가 |
| MANUAL-LINT-HASH-MISMATCH | 원본 입력 해시 계약을 이미 수정한 소스에 lint하여 INPUT_HASH_MISMATCH | 원본 백업 입력 스냅샷에서 lint 및 pilot 재실행; 원본/수정본 해시를 섞지 않음 |
| WINDOWS-FIXTURE-PATH | TEMP 짧은 이름 KIMYOO~1과 Git 장경로 반환 비교 | fixture 경로 resolve 후 테스트 동결; 구현 후 기대값 완화 안 함 |
| ERROR-LEDGER-STDOUT-ENCODING | Python stdout에서 한글이 깨져 보임 | JSONL를 PowerShell로 재확인: 저장된 원문 정상; 기록 손상 아님 |
| PATH-DISCOVERY-ERRORS | global-rules 스크립트 경로, master_schedule.py, antigravity_worker.py/agy_worker.py 없음; rg의 Windows wildcard 경로 오류 | rg --files로 실제 경로 sync-global-rules.ps1, next_card.py, adapters/agy.py 확인; 빈 결과를 완료로 오인 안 함 |
| FULL-SUITE-PROCESS-WARNING | Python ResourceWarning: subprocess still running, 전체 회귀 로그 | 최종 회귀 종료 상태와 잔여 프로세스 확인 필요; 경고를 숨기지 않음 |
| INDEPENDENT-REVIEW-REWORK | 81개 OK지만 Git --show-toplevel 실패 시 worktree 로컬 스케줄로 우회·claim 분리 가능 | 비작성자 REWORK; 새 실패 경로 고정 회귀와 fail-closed 수정 추가 |
| DELEGATE-FIRST-GATE | 31줄 dictated apply가 20줄 상한에 걸림; MCP 초안 거부는 pilot 실패 영수증이 아니므로 apply_after 대체 불가 | 게이트 우회 안 함; 실제 local pilot로 경로 전환 |
| HISTORICAL-OLLAMA-TIMEOUT | 이전 바이블 읽기 지도·초안 두 요청이 장시간 완료되지 않아 스크립트 종료 | 결과 미사용; 원문 대조로 답변. 이번 계약 초안 호출은 응답 수신했으나 판정권 없음 |

## 도구별 증거와 비증거

- Ollama: 계약 초안/코드 초안 실제 MCP 호출. 코드 초안은 오류로 격리. 로컬 모델은 최종 판단하지 않음. 실제 유료 토큰 절감은 UNMEASURED.
- Codex: 재현·고정 인수·설치·최종 패키지 판정 담당. 내장 Codex 하위 검토자는 Antigravity로 세지 않음.
- Antigravity: 실제 CLI/pilot 검토 영수증, 인계 발송, 수신 소비를 각각 기록해야 함. 기존 static PASS·보낸 편지만으로 실제 앱 소비/운영 정상화라 하지 않음.
- Claude Code: 같은 공유 코어의 next/Stop 시험 대상으로 포함. 이번에 실제 Claude 대화가 작업한 것처럼 보고하지 않음.

## 후속 결과

- 진행 중. 최종 설치 ID·해시·관문 명령/종료코드·Antigravity 검토/사용량·패키지 SHA-256을 여기와 원장에 추가한다.
