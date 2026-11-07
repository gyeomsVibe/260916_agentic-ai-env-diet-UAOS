# RSI 추가 실패 영수증: 문서 가공·실시간 사서함 연계

추가 기록 오류: Lotto coord log에 다른 프로젝트의 절대 ref를 넣어 INVALID_REF를 받았다. 프로젝트 내부 상대 ref로 다시 기록한다. 한 번의 apply_patch도 존재하지 않는 문맥을 지정해 verification failed로 거절되었으며 변경0; 실제 제목 문맥으로 교정했다. 이러한 작성·운영 오류도 숨기지 않는다.

일시: 2026-10-09. 기존 사건: `20261009-nonstop-package-a-incident.md`.
이 기록은 정상화 완료 선언이 아니다. 공유 코어 원인 수정과 실시간 사용 증거를 구분한다.

## 사용자 보고와 실측

- 사용자 보고: Codex가 Antigravity 메시지를 즉각 보지 않아 사용자가 티키타카를 다시 요청해야 한다. U150-B 통지로 접수했다. 자동 알림→현재 활성 턴 소비 지연의 정확한 초 단위 SLA는 아직 계측하지 않았다.
- `relay_b5821fdc44ec09d23b7d23d71daab50e` 결함 감사문 및 `relay_de0a17322a54e4d663b142cd8c5fdeeb` live ping을 이번 턴에 실제 원문 읽음. 내용은 고밀도 결함 및 엔진 지시 대기. 파일 전달만으로 앱 소비 완료라 하지 않는다.
- 이전 watch PID 10568은 현재 프로세스 조회에서 존재하지 않았다. 종료 원인/시각 UNKNOWN. 새 로컬 `coord watch --target codex --policy structured --timeout 14400 --interval 30` PID14432를 숨김으로 재장착했고 살아 있음을 조회했다. stdout/stderr는 Lotto `.work/handoff_review_20261009/`에 보존. 감시 프로세스는 사용자 중계 없이 새 인계에 반응하기 위한 기반이나 항상 즉시 모델 실행의 증거는 아니다.
- 공유 코어의 관찰된 false-DONE/하위 프로젝트 경계 오류는 격리 `next_card.py`에서 세 도구 공통으로 수정됐다. 120 focused tests exit0, 독립 판정 PASS. 설치·전체 최종 회귀·실제 Stop 소비는 아직 별도 미완료다. 앱 wake 경로와 이 원인이 동일하다고 단정하지 않는다.

## 이번에도 발생한 실행·증거 오류

| 오류 | 관찰 증거 | 처리/잔여 |
|---|---|---|
| RSI-TASK-MISSING | 설치 runtime의 rsi schedule status: okfalse/FAILED/TASK_MISSING, UAOS_RSI_Watch_39af1fc5 | 설치된 자가 업데이트 감시가 작동한다고 보고하지 않음; 등록·Last Result0·실제 재시도 검증 필요 |
| OLLAMA-HANDOFF-NO-OUTPUT | 문서 가공 local_draft MCP 호출이 실행 셀71에서 응답 없이 남아 취소 | 초안 미채택; 결정론적 원문 읽기와 반례 검사로 전환. 로컬 모델이 전체를 작성했다고 주장하지 않음 |
| CANCELED-EXEC-DEPENDENCIES | 초안 뒤에 배치한 조사/worker 전달이 취소 때문에 실행되지 않음 | 독립 호출로 재실행; 중요한 조사는 장시간 draft 뒤에 직렬 배치하지 않음 |
| SHELL-CWD-DRIFT | workdir 생략된 호출이 GPT/v2.4에서 시작, 상대 docs/Knowledge 경로 실패 | 이후 explicit workdir + loginfalse 및 절대 경로로 재확인. 파일 부재로 해석하지 않음 |
| PILOT-MISSING-FIXTURES-A2 | stage에 uaos_everywhere/adapters 등의 테스트 입력 없음 | fixture를 명시적으로 준비; evaluator 변경 없이 재실행 |
| APPLY-END-TAG | FILE 블록 끝에 ===END FILE===가 Python에 삽입되어 SyntaxError | 계약 구문을 ===END===로 수정; 실패 시도 보존 |
| PILOT-MISSING-FIXTURES-A3 | 120개 실행 중 settings.json 부재로 errors1/acceptance_exit1 | .claude/settings.json 입력 fixture 준비 후 재실행 필요. worker CLIexit0은 인수PASS 아님 |
| FIRST-FULL-REGRESSION | 2014 tests, failures3, skipped6: CPU35.046875>30, firewall count50vs49, callsite2vs1 | 단일 Git 호출로 count 문제 제거 후 focused120 PASS. unchanged-source 성능 baseline1test exit0/29.958s. 최종 full suite 아직 미실행 |
| DOC-RED-EXPECTED | 문서 검사 첫 실행은 계약JSON 부재 FileNotFoundError exit1 | 실제 JSON/문서 작성 후 exit0; 원문SHA 보존. 의도된 Red와 제품 결함 구분 |

## 실제 Antigravity 리뷰와 비용

실제 agy pilot review 영수증: 격리 checkout `.work/pilot_nonstop/runs/NONSTOP-20261009-A3/review_agy.json`.
verdictPASS, advisorytrue, cost_gateWITHIN, elapsed35s, input27758/output3110/total30868 tokens. Claude/Codex 내장 검토자를 Antigravity로 세지 않았다.
이 판정은 A3의 missing fixture acceptance_exit1을 덮어쓰지 않는다. 코드 검토와 실행 인수 관문 모두 필요하다.

## 가공 문서의 활용과 오류 분류

두 인계문서는 동일 SHA a009f77c7537429599aa5706a7412c4741b95736dac4cf9b4b062889efa7af60. 새 개정판이라고 해석하지 않음.
가공 명세는 Lotto `docs/261009-자료/solo_draw_v3_processed/`에 별도 작성. 원본 Proxy/B3 공백, 강제 include에 의한 disjoint bound 붕괴, epsilon 비추이성, 4자리 hash 충돌, 제약 모집단 부족을 명시했다.
이는 도메인 명세 공백이며 UAOS 런타임 버그와 같은 범주로 섞지 않는다. 파일 크기만으로 고밀도 PASS를 판정하지 않는다.
다음 절차: 수신 감사문 읽음→출처 조사 계약 전체를 Antigravity에 전달→독립 원문 검증→기존 Package A 작성자와 비중복 통합. 시스템 설정/원격 쓰기/원본 덮어쓰기 없이 진행한다.

## 확정된 추가 원인: AGY_AUTO 응답 경로는 실행 작업자가 아니다

`coord deliver`가 PUBLISHED/AGY_ANSWERED를 반환하고 relay_e8a2993ee03c8155b57df34c4e8de917에 ‘Ready for Codex verification’와 출력 경로를 주장했지만, 실제 `.coord/results/SDV3-E0-20261009.md`는 없었다. 고정 shape 검사 exit1 FileNotFoundError. 이 출력은 FAILED이며 채택하지 않는다.
격리 공유 소스 `v7_harness/coord/agy_dispatch.py:231`의 prompt는 명시적으로 `Do not call any tool, read files or run commands`라고 강제한다. 즉 이 경로는 편지에 대한 read-only 답변만 생성하며, 파일 읽기·코드 작성·검증 집행의 경로가 아니다. 실행 계약을 이 경로에 전달한 Codex의 라우팅 오류도 원장에 포함한다.
따라서 이 응답의 ‘입력 hash acknowledged/absence confirmed’는 실제 파일 독해 증거가 아니다. 아카이브 미검색은 그대로 UNKNOWN. 편지 자동응답을 실제 Antigravity 데스크톱 창의 수신/실행으로 표시하지 않는다.
실제 비용은 input19074/output2259/total21333으로 계약의12000 cap보다 높다. contract 문자열만으로 dispatcher의 실제 예산을 제어할 수 없음을 확인했다. 추가 paid 자동응답 반복을 중단하고 실행은 CLI/SQLite pilot, 검토는 검증된 inline source packet으로 분리한다.
공유 코어 후속 카드의 요구: 세 도구 공통으로 RESPONSE_ONLY/NOT_EXECUTED와 실행 영수증을 구분, artifact 존재/hash/고정 인수 없이 ACK/ANSWERED를 완료로 승격 금지, 실행 요청을 read-only auto responder에 잘못 라우팅하면 fail-closed. 메시지의 자기 주장만으로 파일을 생성하지 않는다. 이번 소스 수정은 기존 next_card 경계 수정과 별도 카드이며 아직 장착 완료 아님.

## 최신 검증 보완

원본·가공 문서 검사는 29개 exit0이나 독립 문서 검토가 R1~R4 REWORK를 발견했다. 실제 영수증 저장 시점 경쟁, 해시 배열/default 규칙 누락, 작은 유효 풀을 일괄 거절, 원문 주장 확대 해석이었다. README/JSON 수정으로 저장 증거 확인·정확 직렬화 예시·SMALL_FEASIBLE_POOL 별도 제안·출처 표현 정정을 반영했고 독립 재검토 중이다. 고정 검증기 SHA는 변경하지 않았다.
새 문서JSON SHA ed18dcc2edbe80a2aafa6cdff605e3d91b186be3b3d9724d74302aaa0c300fd0. 기존 E0 계약의4097...입력은 무효이므로 기존 reply를 재활용하지 않는다.
A3 재호출은 worker 실행이 아니라 replayedtrue의 과거 acceptance_exit1이었다. 캐시 결과를 새 PASS로 보고하지 않았다. missing .claude/settings.json fixture를 갖춘 fresh judge 실행은 120 tests/66.617s/exit0. 이 명령은 격리 source root에서 실행했으며 worker stage의 fresh acceptance와는 구분한다.

추가 관찰: coord log VERDICT에서 cmd를 생략해 MISSING_EVIDENCE_CMD/exit1을 받았고 실제 검증 cmd를 넣은 다음 exit0으로 기록했다. cli runtime은 지원되지 않는 subcommand라 exit1; 실제 versioned 설치 진입점은 python -B -m v7_harness.runtime_install이다.
Package A staged 기존 verify_package.py 실행은 CLIexit0인데 실제 errors7/package_integrity_fail이었다. 네 필수문구 불일치, ABSTAIN vs GENERATED_EXACT 두 불일치, full-generation문구 불일치. 테스트를 약화하거나 미실행 엔진을 GENERATED_EXACT로 바꿔 PASS를 만들지 않았다. 임시 정적 개선을 최종 Package A 완료로 보고하지 않는다. 18 RuntimeJSON 합계27567bytes의 완전한 운영 절차·출처·실행성은 추가 독립 검증이 필요하다.
문서 독립 재검토는 R1~R4 해소 후 문서 전용 PASS를 반환했다. 원본과 고정 verifier는 변경하지 않았다. 전체 UAOS final regression은 별도 process에서 진행 중이며 source527...가 아니라 정확한 SHA5264b795a6e2f1c8bd28fbad2361d7f74414d227ecc0ac49ac8f2cec842c289b를 사용한다.
