# 2026-10-09: 독식항해 작업에서 드러난 UAOS 논스톱/RSI 운영 오류

## 사용자에게 보인 현상과 현재 판정

Antigravity는 "Codex M2/M3 지시가 오면 후속 검증"이라고 계속 대기했고, 사용자는 내부 협업을 반복해서 재촉해야 했습니다. 이번 오류는 **계획·사서함·스케줄·실행·검증·설치가 이어지는 연결부의 불일치**입니다. 모든 UAOS 기능이 고장났다고 입증한 것은 아닙니다.

사용자는 이번에 공유 코어 수정의 설치·배포까지 명시 승인했습니다. 이후 요청한 독식항해 v2.4 최종 Package A 제작과, 그 과정에서 Ollama·Antigravity 사용의 모든 관측 오류 기록도 같은 진행 업무에 포함합니다. 이 승인을 삭제·결제·인증 변경·원격 push로 확대하지 않습니다.

## 왜 이번 프로젝트에서 이어지지 않았는가

| 연결부 | 실측 | 결과 |
|---|---|---|
| 사람에게 보이는 계획 | Lotto MASTER_SCHEDULE.md는 M2 READY; PLAN.md는 과거 S01~S05 전부 DONE | 두 원장이 같은 남은 일을 표현하지 않음 |
| 기계 실행 계획 | master_schedule.json 없음 | 실행할 single-owner 단계가 기계 스케줄에 연결되지 않음 |
| 프로젝트 경계 | next_card.coord_root가 하위 Lotto를 Git 공통 루트로 이동 | 다른 하위 프로젝트와 스케줄/claim 경계가 섞일 수 있음 |
| 완료 판정 | 세 도구 모두 설치본 coord next가 DONE/no schedule, exit 0 | 미설정이 완료처럼 보임; 사용자 재시작 의존 유발 |
| 수신/소비 | ACTIONABLE verdict 요청 편지 존재 | 발송·파일 존재는 실제 세션의 처리/ACK 증거가 아님 |
| 검증 | 첫 81개 회귀 OK 뒤 비작성자가 Git 조회 실패의 claim 분리 반례 제시 | 정상 경로 통과만으로 설치하면 안 됨; REWORK 반영 |
| 최종 Package A | 기존 verifier는 errors0/warnings0이나 한국어 지침·파일 수 산정·설치 경로·해시·실행 엔진 계약이 부실 | 49는 tests49가 아니라 manifest 파일 수였음; 잘못된 PASS 해석도 오류 |

따라서 **"보고서를 보냈음", "계획을 썼음", "정적 verifier PASS"는 논스톱 운영 완료가 아닙니다.** 내부 의존성은 실제 계약·단일 소유자·기계 스케줄·수신 소비·독립 인수·설치본 동작으로 끝내야 합니다.

## 모든 관측 오류의 유지 원장

전체 오류 대장은 [UAOS_NONSTOP_PACKAGE_A_WORKFLOW_AUDIT_20261009.md](../../.coord/notes/UAOS_NONSTOP_PACKAGE_A_WORKFLOW_AUDIT_20261009.md)에 사건별로 유지합니다. 재현 원본과 해시는 [UAOS_WAIT_WITH_ACTIONABLE_HANDOFF_20261009.md](../../.coord/notes/UAOS_WAIT_WITH_ACTIONABLE_HANDOFF_20261009.md)에 있습니다.

추가 실패도 기록합니다: worker/판정자 형식 오류·입력 hash 누락, apply 블록 누락, 수정본에 원본 hash 계약을 lint한 오류, 31줄 apply의 delegate-first 차단, pilot task와 manual work_id 불일치, 실제 worker 실행 중 GPU busy, 없는 adapter 경로/문서 색인, Windows TEMP 경로 표기 차이, 전체 회귀 process warning/실패. 게이트의 올바른 차단과 제품 결함을 구분하고 비용 분모에서 실패를 빼지 않습니다.

## RSI 관련 섹션과 작성 장소

- 운영/연구 정본: `docs/31_evidence-gated-rsi-for-uaos.md`, `docs/38_rsi-self-improvement-blind-spots-and-evidence-gate.md`, `docs/43_evidence-to-pr-rsi-pipeline-u42.md`.
- 사건 작성: 이 `docs/rsi/`와 `.coord/notes/`.
- 수정 계약: `.coord/tasks/`, 고정 인수·변경 diff·pilot 영수증: `.work/nonstop_fix_20261009/`.
- 사용/오류/수신/판정 원장: `.coord/usage/`, `.coord/stream/`.
- RSI 실행: `v7_harness/rsi.py`, `v7_harness/rsi_release.py`; 스케줄·Stop/next 연결: `v7_harness/coord/next_card.py`, `stop_gate.py`; 장착: `runtime_install.py`, `global_install.py`.

RSI는 실행 증거에서 제안·실험·관문·릴리스로 넘어가는 절차입니다. 오류 기록이 있다고 자동 수정·설치된 것은 아닙니다. `rsi report → propose → trial → gate → prepare → ship` 각각의 영수증과 승인 범위를 확인해야 합니다. 현재 `ship` 원격 push는 별도 범위이며 요청 없이 수행하지 않습니다.

## 이번 복구의 고정 성공 조건

1. 하위 프로젝트·형제 프로젝트·worktree 스케줄/claim 경계를 보존하고 Git 경계 조회 실패는 fail-closed.
2. 표시된 UAOS 프로젝트에 기계 스케줄이 없으면 DONE 대신 미설정 WAIT를 반환.
3. 세 도구의 Stop 연계는 다음 single-owner 단계가 있을 때만 한 번 진행시키고 기존 무진행 반복/비용 제한 보존.
4. Ollama 출력은 원문·실제 인수로 판정; Antigravity는 실제 CLI/pilot 검토 영수증을 확보. 다른 Codex 하위 검토자를 Antigravity로 세지 않음.
5. 전체 회귀의 실패·skip·timeout은 모두 공개하고 baseline 여부를 재현. source와 설치된 런타임의 exact digest 일치, rollback 버전 보존.
6. Package A는 EN/KO 패리티, 산정 근거, 실제 upload 경로·해시, 실행 가능한/미완성 엔진 경계, 재실행 검증·한 개 최종 ZIP으로 최종화. 실제 GPT Preview/runtime는 미실행이면 그대로 not_run/not_verified.

## 상태

진행 중. 독립 REWORK를 받은 수정은 추가 회귀로 검증 중이며, 아직 이 문서에서 전체 운영 정상화·배포 완료를 선언하지 않습니다. 최종 설치 ID·명령/종료코드·검토 영수증·패키지 해시는 운영 대장에 후속 기록합니다.
