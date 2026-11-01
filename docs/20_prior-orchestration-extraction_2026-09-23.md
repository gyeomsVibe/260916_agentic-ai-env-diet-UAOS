# 20. 이전 오케스트레이션 시도에서 추려 온 설계 교훈 (2026-09-23)

- 작성: Claude Code, Codex 부재 중 대행(Codex 한도 재설정 9/24 13:41, `.coord/PLAN.md` 117행). **Codex 복귀 시 재검토 대상.**
- 역할 전제: Claude Code는 Codex 활동 중에는 Codex의 지휘를 받는 부관(비서), 부재 중에는 대신 지휘하는 동등한 부지휘자(AGENTS.md).
- 판정 표기: **보유**(우리에게 이미 있음) / **채택**(가져올 것, 관문 포함) / **버림**(이유 포함).

## 0. 출처

| 기호 | 출처 | 범위 |
|---|---|---|
| S1 | 대화 "2608023_3대 AI 병렬 협업 시스템 구축" (세션 `ee0f1ff7`, 260823 프로젝트) | 사용자·어시스턴트 발화 전부. 설정 스키마 덤프(약 4,900줄)는 잡음이라 제외 |
| S2 | 대화 "Trinity-ACE Protocol 설계" (세션 `07193751`, 260912 프로젝트) | 1,031줄 전부 |
| R1 | `gyeomsVibe/260823_codex-3p-orchestrator` HEAD `fa0e57b` (로컬 사본 = 원격) | 추적 파일 전부. 이전 체계는 태그 `c3p-v2-archive`에만 남아 있음 |
| R2 | `gyeomsVibe/260912_multi-party-ai-agent-real-time-orchestration-mcp` HEAD `6da7cd9` + 보관 커밋 `117efb8` | `central_hub/*`, `harness/*`, `tests/*`, `docs/22~24`. docs 16·17·21은 로컬 모델 요약(§6)으로 보충 |

## 1. 두 프로젝트가 끝난 방식 (가장 큰 교훈)

- R1 C3P는 해체됐다(`docs/C3P_RETIREMENT_DECISION.md`). 해체 근거는 다음 다섯 가지다.
  1. 역할에 위계가 생기면 투표할 대상이 없다.
  2. 문서 62개, Python 약 8,000줄, 테스트 37개에 매 호출 훅이 붙어 규모에 비해 가치가 없었다.
  3. 규칙 본문에 검증되지 않은 "85% 절감"이 들어 있었다.
  4. "1회 승인하면 다른 도구도 자동 승인"이라는 규칙이 경계별 승인 원칙과 충돌했다.
  5. 도구 자체 기능으로 대체할 수 있었다.
- R2 Trinity-ACE는 README에 "88 tests 통과"와 "85% 절감"을 적었지만, 이후 자체 재검토(`docs/22`)에서 다음 결함이 드러났다.
  - 실제 실행기를 부르지 않고 `SUCCESS`와 `VERIFIED_GREEN`을 고정으로 반환했다.
  - Ollama 하나만 살아 있어도 `3-ALIVE`로 판정했다.
  - Dummy 계약으로 짠 테스트는 실제 WorktreePool과 맞지 않았다.
  - 작업이 성공해도 산출물을 `discard=True`로 지웠다.
- 결론: **테스트 수와 선언은 증거가 아니다.** 우리 규칙 "실행 안 한 검사는 UNKNOWN, 측정 안 한 절감은 UNMEASURED"는 두 프로젝트의 실패 원인을 정확히 막는다. → **보유**. 유지만 하면 된다.

## 2. 이미 가진 것 (가져올 필요 없음)

| 교훈 (출처) | 우리 쪽 대응 |
|---|---|
| exit 0이라도 출력이 비었거나 status가 ERROR면 실패 (R1 AGENTS 5항, R2 `117efb8:central_hub/antigravity_executor.py:122`) | `v7_harness/adapters/agy.py:115` `parse_agy_result`: exit 0 + ERROR, SUCCESS + exit≠0, 형식 이탈은 모두 실패 |
| 성공은 한 함수가 증거로 판정: 실행 SUCCESS·exit 0 **그리고** 검증 증거 (R2 `117efb8:trinity_orchestrator.py:62` `derive_overall_status`) | `v7_harness/pilot.py:545-651`: 실행 성공 + 감시 오류 없음 + dry-run 통과 + 인수 exit 0이어야 PASS |
| 변경 없음은 성공이 아님 | `pilot.py:649` `NO_CHANGES` → REWORK |
| 성공 산출물을 자동 병합·폐기하지 않음 (R2 `worktree_pool.py:245` DIRTY 거부, docs/22 Step 2) | bundle을 보존하고 같은 bundle_id를 `--approve`로 줄 때만 반영 (`pilot.py:654`) |
| 원본이 기준선과 달라지면 멈춤 | `SOURCE_DIVERGED`, `EXTERNAL_WRITE`, `WATCH_SCAN_UNAVAILABLE` |
| 멱등성 원장, 리스, 만료 후 재전달 (R2 `mcp_server_adapter.py:110,311`) | U12 lease/fence, `pilot reconcile`, `NEEDS_RECONCILIATION` |
| 읽음 증명은 ack로, 쓰기 증명은 해시로 (S2 채널 프로토콜) | U15 `coord/stream.py`: 증거 강제, 해시 커서 |
| 단계당 대화창 하나, 쓰기 소유자 하나, 카드 필수 필드 (R2 `docs/23`) | AGENTS.md `[U##]` 규칙, `.coord/tasks/*` 카드, QUIET_LOCK |
| 같은 원인으로 반복 실패하면 멈춤 (R1: 2회, R2: 3회) | PLAN 107행: 동일 외부 실행 실패 3회 → BLOCKED |
| 인수 테스트를 작업자가 고치지 못하게 함 (S2: 테스트 변조 사례) | lane의 `--disallowedTools "Edit(test_*.py)"`, 숨은 인수(hidden acceptance) |
| 원자적 쓰기, `encoding="utf-8"`(cp949 로캘), 재실행 시 "w" 덮어쓰기 금지 (S1) | U10~U13 테스트와 `_write_summary` |
| 한 번의 승인을 다른 작업·도구로 넘기지 않음 (R1) | 전역 규칙 "멈추고 물을 것", AGENTS.md 승인 조항 |

## 3. 채택 (우선순위 순, 관문 포함)

### A1. REWORK의 원인을 나눈 뒤 cascade로 승격 — P1

- 교훈: 인프라 실패(모듈 없음, 포트 충돌, 파일 잠금, 타임아웃)를 코드 결함으로 보고 코드를 고치게 하면 헛바퀴를 돈다. R2는 이를 3단 분류와 편집 허가 여부로 막았다(`central_hub/triage_classifier.py`).
  - 끝부분 20줄에 가중치 2를 준다.
  - 러너의 명확한 단언 출력만 코드 결함 판정을 이긴다(`:45`).
  - 분류할 수 없으면 `MANUAL_INSPECTION`, `code_edit_permitted=False`로 보낸다(`:227`).
  - 느슨한 정규식 `\d+ failed`는 "Retry 3 failed: Connection refused"와도 맞아 판정을 다시 뒤집었다(S2 T-1).
- 우리 현황: 인수 exit이 0이 아니면 원인과 무관하게 REWORK다(`pilot.py:640-643`). cascade는 REWORK면 곧바로 lane으로 한 번 더 돈다(`cli.py:265`).
  - 인수 실패가 `ModuleNotFoundError`(U17에서 실제로 난 PYTHONPATH 누락)이거나 GPU 경합으로 난 타임아웃 124(U17 const_extract, 601초)여도 lane이 같은 환경에서 다시 돈다. 이득 없이 벽시계 시간만 쓴다.
- 채택안:
  - `acceptance.log`의 끝부분을 분류해 summary에 `rework_class`(`CODE` / `INFRA` / `UNKNOWN`)를 넣는다.
  - cascade는 `CODE`에서만 승격한다. `INFRA`는 `BLOCKED`(원인 `ACCEPT_INFRA`)로 바꾸고 원인만 보고한다.
  - 분류기는 R2 패턴 중 러너 단언 우선 규칙, 강한/약한 인프라 신호, 동점이면 UNKNOWN 규칙만 가져온다(표준 라이브러리 약 60줄).
- 관문:
  - 양방향 반례 각 2건 이상이 먼저 Red였다가 Green이 된다. 인프라 반례는 ModuleNotFoundError와 타임아웃이고, 코드 반례는 AssertionError와 "Retry 3 failed: Connection refused"가 섞인 pytest 로그다.
  - 기존 U17 10과제 cascade 결과(9/10)가 나빠지지 않는다.
  - 고정 테스트 해시가 바뀌지 않는다.

### A2. 인수 명령이 실행조차 안 되면 REWORK가 아니라 BLOCKED — P1

- 교훈: 검증기는 실행 파일이 없으면 `NOT_CONFIGURED`, 프로세스를 띄우지 못하면 `FAILED`로 따로 표시한다(R2 `117efb8:central_hub/command_verifier.py`). 검증을 돌리지 못한 것을 코드 실패로 적지 않는다.
- 우리 현황: `pilot.py:629-630` `except Exception: acceptance_exit = 1`이 실행 실패를 REWORK로 만든다. cascade가 이 경우에도 승격한다.
- 채택안: 실행 예외를 `acceptance_exit=None`, `verdict_hint="BLOCKED"`, `error_class="ACCEPT_NOT_RUN"`으로 기록하고 예외 이름을 `error_detail`에 남긴다.
- 관문: 존재하지 않는 명령을 인수 명령으로 준 반례가 BLOCKED로 끝나고 cascade가 승격하지 않는다.

### A3. 작업자 버전 지문과 버전이 바뀔 때 스모크 재검증 — P2

- 교훈: R1은 Codex 버전과 Windows 빌드를 로그온 때와 30분마다 비교한다. 바뀌면 경계 검사 7개를 다시 돌리고, 통과한 경우에만 "마지막 정상 버전"으로 올린다(`tools/maintain-codex-sandbox-after-updates.ps1`). 실패는 종료 코드 10으로 남는다.
- 우리 근거: agy 동작은 버전마다 달랐다.
  - 1.2.4: exit 0인데 status가 ERROR(503)였고, 파일은 실제로 써져 있었다.
  - 1.2.9: 상대 경로 view_file이 실패했다.
  - Ollama 0.34.2: Anthropic 엔드포인트가 생겼다.
- 채택안:
  - summary에 `worker_version`(agy `--version`, Ollama 모델 digest, claude 버전)을 넣는다.
  - 직전 PASS 때와 버전이 다르면 첫 실행을 P01 스모크로 돌린다.
  - 예약 작업은 만들지 않고, pilot 실행 시점에만 비교한다(상주 프로세스 금지, S1 교훈).
- 관문: 버전 문자열을 강제로 바꾸는 반례에서 스모크가 요구된다.

### A4. Codex 부재를 증거로 판정 — P2

- 교훈: 응답하지 않는 도구를 동의나 생존으로 치지 않는다(R2 `docs/23`). 도구별 상태에는 `observed_at`, `evidence_type`, `expires_at`을 둔다(R2 `docs/22` Step 5).
- 우리 현황: "Codex 부재"는 PLAN 117행의 사람 메모(한도 재설정 시각)에만 있다. 역할 전환(부관 ↔ 부지휘자)의 근거가 흩어져 있다.
- 채택안: 새 파일을 만들지 않는다. PLAN의 "한도 현황" 줄에 `codex: ABSENT(QUOTA) until 2026-09-24T13:41+09:00, observed_by=<도구>, observed_at=<시각>` 한 줄 형식을 고정한다. 시각이 지나면 상태를 `UNKNOWN`으로 본다. 그다음 첫 판정 전에 Codex 응답을 확인하고, 응답이 없을 때만 대행을 이어간다.
- 관문: 문서 규칙이므로 PLAN 갱신 1회로 끝난다(측정 대상 아님).

### A5. agy 호출 고정비를 반영해 작은 과제를 묶기 — P3

- 교훈: agy는 한 줄 프롬프트에도 입력 약 19k 토큰을 쓰고 캐시 읽기는 0이었다(R2 `117efb8:antigravity_executor.py:13`, agy 1.2.3 실측). edit 모드 실패 한 번에 115k 토큰이 들었다(S2).
- 채택안: 작업자 선택 기준에 "agy로 보낼 과제가 여러 개면 한 프롬프트로 묶는다"를 덧붙인다. 근거 숫자는 1.2.3 한 번의 실측이므로 현재 버전 값은 `UNMEASURED`로 적는다.

### A6. 정리 실패를 삼키지 않기 — P3

- 교훈: `except: pass`로 정리 실패를 숨기면 초록 테스트 뒤에 결함이 남는다(S2: 녹색 스위트가 치명 결함 4건을 가렸다. 잠금 TOCTOU, 경로 탈출, 판정 뒤집힘, `:memory:` 기본값).
- 우리 현황: `pilot.py:199`(리스 해제 실패), `:278`, `:356`(summary 읽기 실패), `:637`(인수 로그 쓰기 실패)이 조용히 넘어간다. 리스는 나중에 reconcile이 잡으므로 데이터 손상은 없다. 원인 기록만 빠져 있다.
- 채택안: 각 위치에서 summary에 `cleanup_warnings`로 예외 이름만 남긴다. 판정은 바꾸지 않는다.

## 4. 버림 (이유)

| 항목 (출처) | 버리는 이유 |
|---|---|
| 투표·정족수·CALL_OUT/WHISTLEBLOW·지정 반대자·방해 분류 T1~T7 (R1 태그, S1) | 위계가 있으면 투표할 대상이 없다(R1 해체 근거 1). 이견은 "증거를 붙인 이견 기록"으로 충분하다 |
| MCP 허브·소켓 브로커·SSE·270초 킵얼라이브·Memory Vault `ref://` (R2 `hub_daemon.py`, `mcp_server_adapter.py`) | 우리는 MCP를 퇴역시켰다(docs/19, 호출 0회 실측). Antigravity Bridge 사용 금지와도 충돌한다 |
| git worktree 풀 (R2 `worktree_pool.py`) | staging 복사 + manifest 비교 + dry-run이 이미 격리한다. Windows에서 git worktree 정리는 파일 핸들 잠금으로 "failed to remove … Invalid argument"가 난다(R2 실측). 다만 그 오류 문자열과 `GIT_ASK_YESNO=false`(`:105`)는 우리 promotion에서 git을 쓸 때 참고한다 |
| Ollama 3b "0원 노예"에 15초 fail-fast (R2 README, `harness/ollama_worker.py`) | 우리 실측은 과제당 17~43초였고 3b는 6/8로 7b보다 낮았다. 15초 상한이면 거의 모든 과제가 승격된다 |
| "85% 절감", "토큰 95% 절감" 같은 수치 (R1·R2) | 측정 근거가 없다(R1이 `EXPLORATORY_UNVERIFIED`로 확인) |
| 고착 잠금 자동 해제 (S2) | "막힌 실패는 시끄럽고 안전하지만, 뚫린 실패는 조용하다." 우리 QUIET_LOCK은 PID 부재 또는 60분 초과이고 해제 사실을 기록한 경우에만 해제하므로 그대로 둔다 |
| 예약 작업의 자동 ACL 삭제 (R1 진단 문서) | 정상 capability SID까지 지웠다. 자동 삭제는 금지하고 읽기 전용 감사만 둔다 |
| 전역 규칙 두 번째 정본 (S1) | 원본은 260718 `shared/global-rules` 하나. 두 정본은 이미 한 번 실수였다 |
| 상주 감시자·래퍼 (S1) | 상주 감시자가 사실상 "두뇌"가 되고 세션과 함께 죽는다. 알림의 지속 경로는 훅이다 |

## 5. 기억할 반례와 수치

- R2에서 93 tests OK는 잘못된 Dummy 계약도 통과시켰다(docs/24). 승인 근거는 실패 주입의 Red→Green 기록과 실제 실행 영수증이다.
- R1: `codex exec`는 설정 파일의 샌드박스 값을 무시하고 전체 접근으로 실행됐다(260915 보고서 5-2). 우리는 `codex exec`를 띄우지 않는다.
- R1: Windows 샌드박스에서 `.git` 쓰기 거부는 제품이 설계한 경계다. ACL을 지워 통과시키는 것은 복구가 아니다.
- R2 docs/22: 세션을 다시 열기만 해도 1시간 캐시 입력 203,825 토큰, 약 $2.36이 들었다. 세션 재개도 비용 관측 대상이다.

## 6. 로컬 모델(olla) 보충 요약

(아래는 `olla ask --model qwen3.5-32k`가 만든 요약을 Claude가 원문과 대조해 확인한 항목만 싣는다.)

- 실행 기록: 문서 3개를 순차 처리했다. 유료 토큰은 0이다.

| 문서 | 걸린 시간 | 입력 / 출력 토큰 | 대조 결과 |
|---|---|---|---|
| R2 docs/16 (311줄) | 147초 | 7,989 / 5,348 | 8건 대조, 8건 일치 |
| R2 docs/17 | 142초 | 3,829 / 6,663 | 10건 대조, 10건 일치 |
| R2 docs/21 (103줄) | 141초 | 2,498 / 7,013 | 7건 대조, 7건 일치 |

- 한계: 문맥 16k(`ollama ps` CONTEXT 16384) 때문에 원문 뒷부분이 빠졌을 수 있다. 여기에는 원문 행을 직접 확인한 항목만 싣는다.

**docs/16: 테스트 25개가 모두 통과한 상태에서 결함 4건을 확정**
- 확정 근거(9·183행): 잠금 경합 3회 중 3회 모두 ACQUIRED가 나왔다.
- 교정 결과(207행): 통과 테스트가 64개 + 하위 테스트 9개가 됐다.
- 잠금은 `INSERT … ON CONFLICT DO NOTHING` 뒤 `rowcount == 1`일 때만 획득으로 본다(45행).
- `:memory:` 기본값은 연결마다 스키마를 잃는다. 공유 캐시 URI나 연결 1개로 고정해야 한다(99행).
- 캐시 유지 신호(keep-alive)는 손익분기가 약 62.5분이라는 외부 글이 있다(111·190행). 270초마다 보내면 하루 약 320회 유료 요청이 된다. 이 수치는 우리가 측정하지 않았다.
- 헤드리스 CLI를 새로 띄울 때마다 새 캐시 쓰기 비용이 든다. 동시 기동은 세마포어로 1~2개로 제한하고, 들어온 카드는 5초 동안 모아 한 번에 처리한다(135행).
- 우리 쪽: A5(작은 과제 묶기)의 근거를 보강한다.

**docs/17: 판정 Pivot(7행). 테스트 88개 통과는 모의 계약의 통과일 뿐(32·101행)**
- worktree는 파일 충돌만 분리한다. 공용 포트·DB·설정은 분리하지 않는다(21·48행). 대안으로 슬롯별 포트·임시 폴더·DB 이름공간을 제시했다(84행).
  - 우리 쪽: staging 복사도 파일만 격리한다. 포트와 DB는 AGENTS.md의 "같은 포트·DB 동시 수정 금지" 규칙이 막는다(**보유**). 병렬 pilot을 열 때는 이 규칙이 전제가 된다.
- 성공으로 치려면 실행기 버전, 기준 SHA, diff 해시, 테스트 종료 코드가 모두 기록돼야 한다(92행).
  - 우리 쪽: A3 `worker_version`의 근거다.
- 보안 경계는 토큰 보유 여부보다 권한 축소(capability 축소)가 먼저다(58행).

**docs/21: Antigravity 초안. 이후 docs/22가 일부를 뒤집었다**
- 잠금을 획득하지 못하면 즉시 `HALTED_LOCK_CONFLICT`로 중단한다(33·69행). docs/22가 이를 유지했다.
- CLI는 비대화형 플래그로 60초 상한을 두고 강제 회수한다(38·79행). 이 값에는 근거가 없다.
  - 우리 쪽 실측: lane 17~43초, local 타임아웃 601초. 60초 상한은 **버림**.
- 환경변수 부재·인증 만료·파이프 EOF로 CLI가 즉시 죽는다(45행).
  - 우리 쪽: A1 INFRA 분류에 인증 만료 패턴을 추가한다.
- 패치가 실패하면 "디렉터리 즉시 파기"(53행)하도록 했다. docs/22가 "export 전 discard 금지"로 뒤집었다. 우리도 bundle을 보존하므로 **버림**.
- 모델 요약이 `UNVERIFIED`로 붙인 항목은 원문에서도 제안 단계일 뿐이다. 실측으로 인정하지 않는다.

## 7. 다음 행동 (PLAN U18 후보)

- A1과 A2를 한 단계 U18 "REWORK 원인 분류와 cascade 승격 조건"으로 묶는다. 바꿀 내용을 구체적으로 적을 수 있으므로 작업자는 `--worker cascade`(local 먼저)로 하고, 판정은 §3의 관문으로 한다.
- A3~A6은 U18이 DONE이 된 뒤 BACKLOG로 둔다.
- Codex 복귀 시 이 문서와 AGENTS.md 역할 조항 수정을 재검토한다.
