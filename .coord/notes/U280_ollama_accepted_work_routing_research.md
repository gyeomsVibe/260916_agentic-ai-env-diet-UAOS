# Ollama CLI 수행 성공률 연구와 UAOS-RSI 개선안

유지 산출물 · 2026-10-28 · Codex 작성 · 독립 판정 전 후보 (U280 통합본)

## 결론과 적용 범위

호출 빈도보다 **독립 인수된 작업당 전체 비용**을 최적화한다. 현재 기록만으로
업데이트가 성공률 하락의 원인이라고 확정할 수 없다. 원장에는 중복과 검증 전
PASS가 섞여 있고, 업데이트 시점·작업 난이도·모델 설정을 고정한 대조군이 없다.
따라서 숫자를 부풀리거나 실패를 삭제하지 않고 원본을 보존하며 분석한다.

이번 조사에서는 연구 보고서, 재현 가능한 원장 감사, 제한적 라우팅 후보를 만든다.
U277/U279 소스는 기존 Claude 소유자에게 남긴다. 설치된 런타임의 admission HOLD와
기존 고정 평가기는 유지한다. 보고서 작성과 런타임 배포 완료는 별개다.

## 1. 조사 방법과 증거 경계

전체 검색 범위는 정본 `.coord/usage/runs.jsonl`, 현재 master_schedule,
Ollama 작업 어댑터, 과거 U16/U17/U19/U23 보고서와 최신 인계이다.
원장 분석 코드는 `.work/ollama_research_261028/audit_ledger.py`,
해시와 집계는 같은 폴더의 `ledger_audit.json`이다. 프롬프트·비밀은 수집하지 않았다.
worker=ollama/local만 집계한 값이며 모든 MCP/global 로그가 합쳐졌다는 뜻은 아니다.
분석은 읽기 전용이다. 결과 라벨과 독립 검증자의 이름만으로 실제 인수를 인정하지 않는다.

공개자료 검색어: Ollama structured outputs/tool calling/context length,
Aider Ollama edit formats/quantization, small language model agent tool calling,
Reddit local coding agent bounded tasks. 공식 문서·저장소·논문과 커뮤니티 경험을 구분했다.

## 2. 원장 전수 집계에서 확인한 사실

| 항목 | 관찰값 | 해석 한계 |
|---|---:|---|
| 전체 원장 행 | 1625 | 이 파일의 스냅샷 |
| Ollama/local 행 | 590 | provider 호출 횟수와 같지 않음 |
| 완전히 동일한 행 제거 후 | 586 | 동일 work_id 재시도는 임의 제거하지 않음 |
| 완전 중복 행 | 4 | 원본 삭제 없이 분석에서만 중복 제거 |
| 같은 work_id/receipt에 여러 행 | 17그룹 | 재시도인지 재수집인지 미확정 |
| PASS 라벨 | 279 | 독립 인수 성공률 아님 |
| BLOCKED / REWORK | 188 / 78 | 실패 분모에서 제외하지 않음 |
| 독립 검증자 라벨이 있는 행 | 48 | 원래 검토 산출물 확인 필요 |

2026-10-28의 기록은 REWORK 5행이다. U279-F1/F2는 입력 약 10k 토큰,
벽시계 약 2분이며 AssertionError가 기록됐다. U277-A9-R3는 같은 ID가 서로
다른 receipt/시간으로 등장한다. 이를 2개 독립 실패나 1개 재수집으로 단정할 수 없다.
U279-F1 원래 summary는 정본의 해당 상대경로에 없었다. worktree별 원본 탐색이 필요하다.

최근 PASS 가운데 U273/U275 동일 receipt가 반복된다. verifier 라벨·짧은 응답시간·
큰 입력토큰이 함께 나타나는 사례는 캐시/요약/재수집 가능성도 있다. 조작이라고 단정하지
않고 원시 영수증이 없는 수치는 성공률이나 절감 효과의 근거에서 제외한다.

## 3. 성공 가능성이 높았던 업무 패턴

다음 순위는 역사적 근거 강도와 현재 구조 적합성이다. 전 유형을 동일 실험으로
비교한 통계적 성공률 순위는 아직 아니다.

| 패턴 | 프로젝트 근거 | 실사용 기준 |
|---|---|---|
| 위치 맵 → 필요한 구간 원문 읽기 | U17 보고: 위치 8/8, 150줄 조각 7/8 | 줄번호·심볼을 parser/원문으로 재검증 |
| 단일 입력 분류·초안 | 인수와 별개로 좁은 전처리 용도 | 인용·숫자·파일명은 원문 대조 |
| 한 함수의 작은 패치 | U19 역사적 10과제 보고 6/10→7/10 | exact SEARCH, 단일 소유자, 변경 범위·인수 고정 |
| 정확한 받아쓰기 | U124의 원문 동등성 방어 | 이미 정답 패치가 있으면 결정적 적용이 우선 |
| 대형 파일 전체 재작성·자율 설계 | NO_FILE_BLOCK, SPLICE, 구문 실패 기록 | 기본 위임 대상에서 제외; 먼저 업무를 재분할 |

U17/U19 값은 과거 문서의 보고치이며 이번에 원래 실험을 재실행한 값이 아니다.
맵 출력이 줄번호를 제시해도 내용의 진실성을 보장하지 않는다.

## 4. 이번 세션의 반례

local_read_map은 구조 탐색 요청에 `watcher_live(claude)`를 ACTIVE로 취급하겠다는
행동 지시형 문장을 반환했다. 이것은 요청한 지도도, 권위 있는 상태 판정도 아니다.
parser의 outline과 원문만 이용하고 그 문장은 폐기했다. 파일 내용이 모델의 지시로
승격되는 경로를 막아야 한다.

local_draft는 원장 중복 PASS 행을 삭제하라고 제안했고, 부분 CPU offload를
효율화하라는 문장은 원인·조치가 불명확했다. 두 제안은 채택하지 않았다.
원장 불변성과 명시적 측정이 필요하다는 독립 판단을 적용했다. 모델이 답했다는
사실은 작업 성공을 뜻하지 않는다. 이 두 보조 호출의 내부 provider 토큰은 UNKNOWN이며
MCP 공용 로그와 중복 없이 대조하기 전에는 원장에 추정치를 추가하지 않는다.

## 5. 공개자료: 실제 적용 원리와 한계

1. [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs):
JSON schema를 format으로 전달하고 결과를 검증한다. 출력 모양 강제는 의미적 정확성이나
파일 수정 인수를 대신하지 않는다. cloud와 local의 지원 차이도 구분한다.
2. [Ollama tool calling](https://docs.ollama.com/capabilities/tool-calling):
모델의 tool call과 호스트의 실행·결과 전달은 별도 단계다. UAOS의 단일 생성 작업자에
자율 도구 루프를 추가하는 것은 개선안의 전제조건이 아니다.
3. [Ollama context](https://docs.ollama.com/context-length),
[FAQ](https://docs.ollama.com/faq): 실제 할당 context와 CPU/GPU 분할을 확인한다.
문서 간 기본값 설명이 다르므로 설치 버전의 관찰값을 우선한다. 이번 `ollama ps`는
qwen2.5-coder:7b, context16384, CPU/GPU 혼합을 보였다. context만 늘리는 방안은
메모리·시간 회귀를 일으킬 수 있어 실측 전 채택하지 않는다.
4. [Aider Ollama 연동](https://aider.chat/docs/llms/ollama.html),
[편집 오류](https://aider.chat/docs/troubleshooting/edit-errors.html),
[GitHub](https://github.com/Aider-AI/aider): context와 편집 형식은 별개의 성공 조건이다.
전체 파일 출력은 형식상 쉬워도 토큰·누락 위험이 커진다. UAOS에는 짧은 고유 SEARCH와
한 함수 범위를 적용하고, Aider 자체를 설치하거나 현재 하네스를 교체하지 않는다.
5. [Aider 양자화 실험](https://aider.chat/2024/11/21/quantization.html):
같은 모델 계열도 서비스·양자화·context에 따라 결과가 달랐다. 이 실험은 32B이며
현재 7B와 직접 비교할 수 없다. 다른 모델의 벤치 수치를 UAOS 성공률로 옮기지 않는다.
6. [Local Coding Agent 저장소](https://github.com/pvnc228/local-coding-agent):
상위 agent가 좁은 목표·허용 파일·검사를 넘기고 호스트가 diff와 실제 외부 테스트를
확인하는 구조다. Codex/Claude/Antigravity 연동을 문서화한다. README 기능 설명은
실제 UAOS 통합 성능 증명이 아니며, 외부 코드는 설치·실행하지 않았다.
7. [Reddit 원글과 댓글](https://www.reddit.com/r/LocalLLaMA/comments/1vq128f/making_small_local_models_actually_useful_for/):
글쓴이는 작은 GPU에서 context 팽창·schema 실패를 경험하고 micro-patch 위임을 설명한다.
댓글은 allowed files, test command, hard context cap을 강조한다. 자기 보고 사례이며
속도·모델명·성공률은 검증된 벤치로 취급하지 않는다. 기술 설계의 근거는 위 1차 자료다.
8. [Small Language Models are the Future of Agentic AI](https://arxiv.org/abs/2506.02153):
반복되는 전문 호출에 작은 모델을 배치하는 이종 구조를 주장하는 position paper다.
UAOS 절감률이나 qwen7b 인수 성공률을 직접 측정한 논문은 아니다.
9. [Beyond Fluent Generation](https://arxiv.org/abs/2609.07370):
작은 모델에서 복구 parser를 허용한 점수와 raw JSON 적합성이 크게 다름을 보고한다.
2B 미만 CPU 실험을 현재 GPU 7B의 성능으로 일반화하지 않는다. 형식 복구 성공과
엄격한 원본 형식 통과를 별도 집계해야 한다는 반례로 사용한다.
10. [TinyLLM](https://arxiv.org/abs/2511.22138): BFCL 기반 모델·기법별 차이를 보고한다.
UAOS 실사용이나 파인튜닝 도입의 효용을 입증하지 않는다. 데이터·하드웨어·과제 이동을
고려해 이번에는 재학습보다 하네스와 업무 계약을 먼저 개선한다.

## 6. 원인 가설과 반증 조건

| 가설 | 근거 | 반증 또는 추가 확인 |
|---|---|---|
| 호출 비율 목표가 부적합한 일을 local로 보냄 | capacity 정책에 비율 중심 문구 | 실제 dispatch와 정책 변경 커밋 시점 대조 |
| 긴 계약이 짧은 코드 과제보다 어려움 | U279 입력 약10k, 인수 실패 | 동일 과제·고정seed·같은 인수의 작은 계약 비교 |
| 메모리 압박·GPU 경쟁 | live 혼합 offload, timeout 역사 | 단일 실행 lease, prompt/output 크기·지연·offload 측정 |
| 자유로운 출력 형식이 원문을 손상 | splice/no block/dictation 실패 | schema/원문동등성 검사와 frozen acceptance 동시 통과 |
| 성공률 자체가 중복으로 왜곡 | 원장 중복·모호한 attempt 그룹 | 원시 receipt identity·hash·provider usage join |

## 7. 대안 비교와 결정

| 대안 | 가치 | 실행성 | 위험·롤백 | 결정 |
|---|---|---|---|---|
| 사용비율을 강제하고 context 증가 | 호출수 증가 | 쉽지만 효과 미확인 | CPU offload·재시도 증가, 설정 복구 필요 | No-Go |
| 업무 적합성·고정 계약·증거별 라우팅 | 인수된 일 중심 | 기존 pilot 활용 | 새 helper만 격리해 롤백 가능 | Go: 작은 후보 |
| 모델 대형화·파인튜닝·새 agent 설치 | 잠재 성능 개선 | 하드웨어·표본 부족 | 비용·환경·회귀 큼 | Research More |

선택: 결정적 추출/적용 → 원문 검증 가능한 local 전처리 → 한 함수 패치 →
실패 원인별 재분할 또는 Claude/Codex. AGY는 사용자가 알린 제한 해제 전 배정하지 않는다.
동일 원인 두 번 실패하면 local 재시도를 중지한다. 자동 paid 승격은 금지한다.

## 8. 저가 모델의 위치

[OpenAI 공식 모델 문서](https://learn.chatgpt.com/docs/models)는 GPT-6 Luna를
좁고 반복적인 대량 작업의 효율 모델로 안내한다. 따라서 Codex 쪽 Haiku 대응 후보는
`gpt-6-luna`이다. 실제 계정 가용성·독립 인수·사용량 절감은 아직 미측정이다.
API mini 가격을 구독 한도 절감률로 환산하지 않는다. GPT-5.4-mini는 문서상
ChatGPT 로그인 Codex에서 은퇴했으므로 현재 기본 후보로 삼지 않는다.

Haiku5.5는 요청대로 우선 검토하되 기존 cache-inclusive hard cap과 모델 identity
검증을 통과해야 한다. 과거 초과 영수증을 지우거나 상한을 올려 성공으로 바꾸지 않는다.
독립 판정·보안·복잡한 동시성은 작은 모델에게 넘기지 않는다.

## 9. MIA 단계별 실행과 현재 관문

0 연구: 위 공식 URL·저장소·논문·관찰값 수집 완료.
1 기획: 성공 신호는 **같은 인수의 matched pair에서 품질 비열화, P1=0, 전체비용 회귀 없음**.
2 검증: 원장만으로 causal 성공률 판단 불가를 명시. 독립 검토 대기.
3 큰계획: 세 대안 비교, 업무 적합성 경로 선택.
4 검증: 새 helper는 소스/런타임과 격리, 고정 평가기 변경 금지.
5 상세: 한 개의 순수 라우팅 함수 후보, 입력은 관찰된 상태/과제/실패 횟수.
6 검증: 계약 lint와 독립 검토 통과 후에만 구현.
7 구현계획: 20줄 이내, 원장 쓰기·provider 실행·자동 승격 없음.
8 사전검증: writer/QUIET_LOCK 확인, 기존 파일 수정 시 백업.
9 구현: isolated pilot, 고정 인수와 음성시험; 미실행은 UNKNOWN.
10 최종: Claude가 Codex 후보를 검토하거나 역으로 작성/판정 분리.
대조 10쌍은 기존 요구의 최소 유효 표본 기준이며 통계적 충분성을 뜻하지 않는다.
과제 유형·입력 hash·모델 digest·seed·context·output cap·인수 hash를 고정한다.
주 지표는 독립 인수율, 모든 시도 포함 wall time/accepted step, paid tokens/accepted step.
format-pass, provider-success, applied, accepted, released는 각각 따로 기록한다.

## 10. Antigravity 업무 인계와 순서

사용자 지시를 Claude native session에 전달했고 응답을 받았다. 해당 창은 소스 작성자가
아니며 도구 실행이 승인 제약으로 막혀 있다고 보고했다. 이 응답은 전체 Claude 부재나
다른 소유자의 작업 중단을 뜻하지 않는다. 기존 U277 작성 세션의 소유권을 보존한다.
이전 Codex 창에 새 PRIMARY 이전을 통보했고 정본 `.work/desk_261028_ollama/`로
인계 파일을 받았다. 다른 사용자 창을 추가 생성하지 않았다.

| 순서 | 업무 | 담당/상태 | 다음 관문 |
|---|---|---|---|
| 1 | Ollama 근거·라우팅 | 이 Codex 창 | 독립 연구 검토 → 작은 후보 |
| 2 | U277 저장소 identity/session | 기존 Claude 작성자·Codex 판정 | 정확한 head의 frozen gate |
| 3 | U276 provenance | Claude·Codex 교차 | UNKNOWN effect의 정식 해소 |
| 4 | U278 console/runtime | Codex, Claude 검토 | 전체 진입점·native focus·회귀 |
| 5 | U279 wake filter | 기존 Claude 계약 담당 | 독립 candidate 검증, U277 배포 종속 |
| 6 | U256/U259/U267 및 AGY DONE 후보 | 읽기전용 전수 재조정 | live PR와 source acceptance 대조 |

정본 master_schedule의 일부 이전 상태와 최신 takeover 증거가 충돌한다. dirty 정본을
덮어써 일괄 DONE/READY로 바꾸지 않는다. 각 변화는 owner와 exact artifact 기준으로
합의하고 적용한다. 단순 ACK나 watcher 생존을 작업 완료로 인정하지 않는다.

## 11. 후속 실측·독립 검증·최종 상태

이 절은 앞 절의 중간 UNKNOWN/대기 상태를 최신 관찰로 보완한다.

전역 `invocations.sqlite3`도 읽기 전용으로 조사했다. local 관련385행 중 프로젝트
경로316행은 SUCCEEDED310/FAILED4/STARTED2였으나 **316행 전부 acceptance=UNVERIFIED**였다.
프로젝트 원장과 이 provider 원장은 identity join 전 더하지 않는다.
비밀·프롬프트 없는 필드를 `global_local_journal_audit.json`에 보존했다.

U17 보관 원본 `bench_digest_7b.json`은 300줄 설정에서 위치8/8적중,412.8초를 기록했다.
U19 `e2e_local_after.log`는10과제 중7PASS,총65.8초다. off-by-one/default-arg/None-guard/
parse-kv/dedupe-order/class-method/table-format이 통과했고 cross-file rename/
constant-extract/import-bug는 실패했다. 원본 hash와 기계 추출 결과는
`historical_receipts.json`에 남겼다. 이는 이번 재실험이나 보편적 성공률이 아니다.

이번 두 보조 작업은 전역 journal에서 qwen2.5-coder:7b의3 provider호출(맵2chunk,초안1)로
확인됐다. 합계 입력18369/출력467토큰,provider 벽시계 합258.295초다. 전체 도구 대기시간이나
유료 사용량이 아니다. provider SUCCEEDED와 달리 요청의 의미적 인수는 거부했다.
`provider_journal_excerpt.json`이 입력 hash별 근거다. 원래 원장 행을 수정하지 않았다.

Claude 독립 REVISE로 조건 우선순위/evaluator보호/무변경 deterministic조건을 보완했다.
revision2의19줄 순수 함수는 PASS_CONTRACT를 받았다. apply-only 파일럿 bundle
`603269fbf64ab7a1fcc59eaa6b804b4e0fccb194f344c50c248d365cad5fc6d5`는 허용 파일1개만
바꾸고 원래18+추가4사례를 통과했다. 원래 인수 SHA256
`1469c61eb472fe98d1e1eca3725e7bc3fb1f4972aff431ee3333c821d1cd618e`는 불변이다.
첫 lint는 apply블록누락/잘못된CLI플래그로 실패했으며 수정 후 lint exit0이었다.
stage의 `.work`제외 때문에 절대경로 transport를 만들었고22assertion은 바꾸지 않았다.

Claude 임시 실행창은 Python권한 제약으로 실제 테스트 판정을 보류했다. 사용자가 요청한
저가 Codex모델의 작은 실증으로 GPT-6 Luna 독립 검토자를 사용했다. 검토자는22인수와
AST/해시를 직접 실행해 exit0,PASS_SOURCE_ONLY로 판정했다. 검토자의 초기 경로/상태조회
2건은 exit1이었고 재확인 후 통과했다. 사용량 절감은 UNMEASURED다.

후속 조사에서 기존 `v7_harness/worker_routing.py`가 이미 공용 bounded planner를
제공함을 확인했다. **새 후보는 격리 proof로 보존하고 중복 planner로 승격하지 않는다.**
기존 planner와의 계약 통합이 채택 경로다. 라이브 dispatch연결/full regression/
같은 과제 대조/독립 admission 전에는 운영체제 최적화 완료나 성공률 상승을 주장하지 않는다.
설치 런타임은 변경하지 않았다.

AGY소유 schedule항목49개를 전수 추출해 U259/U267 READY와 DONE_SCOPED를 따로 보존했다.
열린PR250(CI SUCCESS)/224(CI FAILURE)를 현재 조회했다. PR250 CI성공은 기존 frozen실패를
해제하지 않는다. Claude relay7a10/afbfc 합의로 Claude는 U278/U276/AGY감사, Codex는
master/U277판정/U280/merge를 맡는다. 역할 편지는 digest검증 후 ACK했다.

card skip은 프로세스exit0이지만 JSON `ok=false,AGY_AVAILABLE`을 반환했다. 사용자의
AGY제한 통보와 runtime가용성 판단이 충돌한다. 이를 우회해 제한된AGY를 호출하거나
card audit통과로 위장하지 않았다. 연구와 격리후보 검증은 완료했으며 채택/배포는 HOLD다.

## 12. U280 통합: `v7_harness/worker_routing.py` 고정 우선순위 계약 통합

`DESK-261028-4-ollama-research.md` 31–35행의 결론("기존 `worker_routing.py`가 이미 bounded planning을 제공하므로 중복 모듈을 만들지 않고 고정 계약으로 통합한다")에 따라, `v7_harness/worker_routing.py`에 순수 결정론적 적합성 판정 함수 `evaluate_ollama_task_fit(...)`을 통합했다.

우선순위(First-Match Precedence):
1. 평가기·보안·합의·관문 파일 접촉 또는 판정 업무 → `REFUSE_LOCAL_EVALUATOR_OR_GATE` (`worker='conductor'`, `local_qualified=False`)
2. 무변경 또는 이미 정확한 받아쓰기(dictation) 패치·정확 추출 → `DETERMINISTIC_APPLY_FIRST` (`worker='deterministic'`, `local_qualified=False`)
3. 동일 원인 로컬 실패 2회 이상(`same_cause_failures >= 2`) → `QUARANTINE_LOCAL_SAME_CAUSE` (`worker=None`, `local_qualified=False`)
4. 전체 파일 재작성·20줄 초과 변경·다중 파일 아키텍처·다중 함수 패치 → `ESCALATE_BOUNDED_SLICE_REQUIRED` (`worker='conductor'`, `local_qualified=False`)
5. 원문 대조(`source_verified=True`)가 보장된 좁은 맵·초안·요약·분류 전처리 → `ALLOW_LOCAL_PREPROCESS` (`worker='local'`, `local_qualified=True`)
6. 단일 함수·20줄 이하·고유 SEARCH 블록(`exact_search_block=True`)·고정 인수(`pinned_acceptance=True`) 패치 → `ALLOW_LOCAL_MICRO_PATCH` (`worker='local'`, `local_qualified=True`)
