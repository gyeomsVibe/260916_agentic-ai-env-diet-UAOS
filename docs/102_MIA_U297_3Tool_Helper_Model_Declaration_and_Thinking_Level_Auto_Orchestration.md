# MIA U297 — 3대 도구(Codex·Antigravity·Claude Code) 공식 도우미 모델 선언·지정 및 마스터·세부 스케줄 기반 Thinking Level 자동 선정·병렬 오케스트레이션 설계서

- **카드 ID**: `U297`
- **작성일**: 2026-11-02
- **작성 도구**: Antigravity (`mia-strategic` 11단계 전략 프레임워크 엄격 적용)
- **연관 문서**: `docs/98_MIA_Claude_전속일꾼_올라마_Haiku55_전수분석_및_병렬운용_개선설계서.md`, `docs/27_token-budget-routing-policy.md`, `.coord/master_schedule.json`, `.coord/sub_process_schedule.json`

---

## Stage 0. 선행 리서치 (Web Deep Research — 공식 문서 및 1차 출처)

1. **Anthropic Claude Code Subagents & Effort 제어**:
   - 출처: https://docs.anthropic.com/en/docs/claude-code/sub-agents
   - 핵심 사실: Claude Code는 `CLAUDE_CODE_SUBAGENT_MODEL=claude-haiku-5-5` 및 서브에이전트 `effort` (`low`/`medium`/`high`) 설정을 통해 메인 추론 모델(`Claude Opus 5.5`, `Claude Sonnet 5.5`)과 독립된 저비용·고속 도우미 서브에이전트를 병렬 실행한다.
2. **OpenAI / Codex 추론 모델 시리즈 및 `reasoning_effort` (`Low`/`Medium`/`High`)**:
   - 출처: https://platform.openai.com/docs/guides/reasoning
   - 핵심 사실: OpenAI 추론 모델은 `reasoning_effort` (`low`, `medium`, `high`)로 내부 사고 토큰 예산을 제어한다. GPT-6.1 플래그십(`GPT-6.1 Sol`, `GPT-6.1 Terra`), GPT-6 표준 세대(`GPT-6 Astra`, `GPT-6 Sol`, `GPT-6 Luna`), GPT-5.6 경량·안정화(`GPT-5.6 Sol`, `GPT-5.6 Terra`, `GPT-5.6 Luna`) 라인업 중 **`GPT-6 Luna`**(주력)와 **`GPT-5.6 Luna/Terra/Sol`**, **`GPT-6 Sol`**이 토큰 대비 최대 성능의 가성비 도우미 모델 계층을 형성한다.
3. **Google Gemini / Antigravity 추론 모델 및 `thinkingLevel` (`Low`/`Medium`/`High`)**:
   - 출처: https://ai.google.dev/gemini-api/docs/thinking
   - 핵심 사실: Gemini 추론 모델은 `thinking_level` (`Low`, `Medium`, `High`)로 사고 깊이를 조절한다. Antigravity의 추론 모델 라인업(`Gemini 4 Argon`, `Gemini 3.8 Flash`, `Gemini 3.7 Flash`, `Gemini 3.6 Flash`, `Gemini 3.1 Pro`, `Claude Sonnet 5.5 (thinking)`, `Claude Opus 5.5 (thinking)`, `GPT-OSS-120b`) 중 **`Gemini 3.8 Flash`**(주력)와 **`Gemini 3.7/3.6 Flash`**, **`GPT-OSS-120b`**가 토큰 대비 최대 성능의 가성비 도우미 모델 계층을 형성한다.

---

## Stage 1–2. 기획 및 검증 (전수 실측 근거 및 문제 정의)

### 1.1 실측 장부(`.coord/usage/runs.jsonl`) 및 스케줄 전수 분석 결과
- **전체 실행 원장(1,745건)**:
  - `ollama` (`qwen2.5-coder:7b`): 663건 (38.0%)
  - `apply`: 544건 (31.2%)
  - `agy` / `antigravity`: 406건 (23.3%)
  - `claude`: 43건 (2.5%)
  - `codex`: 40건 (2.3%)
  - `haiku-5.5`: 18건 (1.03%, 누적 113,540 tokens)
- **Claude Code 호출자(`caller == "claude"`) 내부 비율 실측**:
  - `claude` (Opus/Sonnet): 34건 (**49.3%**)
  - `ollama` (`qwen2.5-coder:7b`): 33건 (**47.8%**)
  - `haiku-5.5` (`claude-haiku-5-5`): 2건 (**2.9%**)
  - **진단**: 목표 황금비(`Ollama 50% : Haiku 5.5 30% : Opus/Sonnet 20%`) 대비 Ollama(47.8%)는 근접했으나, Haiku 5.5가 **-27.1%p 과소 호출**되어 그 부담이 고비용 메인 모델(49.3%, +29.3%p 초과)로 전가됨.
- **세부 프로세스 스케줄(`capacity_planner.py:1734`) 구조적 결함**:
  - 기존 코드: `test_doc_worker = "haiku" if effective_owner == "claude" else "ollama"`
  - 결함: `antigravity`나 `codex`가 카드를 수행할 때 `SP3_CODE_EXECUTION`에서 `code_lane: ollama`와 `test_doc_lane: ollama`가 동시에 배정되어 단일 로컬 GPU 제한(`MAX_CONCURRENT_OLLA = 1`)과 충돌함.
  - 해결: `antigravity`에는 공식 도우미 모델 `gemini-3.8-flash`를, `codex`에는 공식 도우미 모델 `gpt-6-luna`를 `test_doc_lane` 동반 일꾼으로 배정하여 3대 도구 모두 **로컬 0원 Ollama CLI (코드 슬라이스 50%) || 공식 클라우드 도우미 모델 (테스트·문서 30%) || 코어 추론 모델 (설계·판정 20%)**의 무병목 5:3:2 이원 분리 병렬을 달성한다.

---

## Stage 3–4. 큰 계획 및 4-Lens 대안 비교

| 평가 축 | 대안 A (채택): `helper_thinking_router.py` 신설 + 스케줄러·위임기 통합 | 대안 B (기각): `worker_routing.py` 직접 수정 | 대안 C (기각): 문서 선언만 수행 |
|---|---|---|---|
| **가치(Value)** | 3대 도구 공식 도우미 모델·추론 라인업·Thinking Level을 마스터(141단계)·세부(`SP1`~`SP5`) 스케줄 전체에 자동 바인딩 | 동일 | 런타임 자동화 불가 |
| **실현성(Feasibility)** | 높음 — 평가기 보호 스템(`worker_routing.py`)을 건드리지 않고 기존 U256/U271/U280/U281 테스트 100% 호환 | 불가 — `EVALUATOR_GATE_STEMS` 및 `imported == {'math'}` 위반 | 낮음 |
| **위험(Risk)** | 낮음 — 기존 반환 딕셔너리 키 보존 + 확장 키 추가 | 치명적 — 커밋 게이트 차단 | 재발 위험 높음 |

---

## Stage 5–6. 세부 계획 (3대 도구 공식 도우미 모델·추론 라인업·Thinking Level 매트릭스)

### 5.1 3대 도구 공식 도우미 모델(Helper Model) 및 추론 모델 라인업 선언

| 도구 | 0원 전자계산기 (50%) | 공식 도우미 모델 선언·지정 (30% 가성비 일꾼) | 코어·플래그십 추론 모델 라인업 (20% 핵심 추론) | Thinking Level 제어 |
|---|---|---|---|---|
| **Codex (`codex`)** | `ollama` (`qwen2.5-coder:7b`) | **주력 공식 도우미**: `GPT-6 Luna` (`gpt-6-luna`)<br>**경량·안정화 도우미**: `GPT-5.6 Luna` (`gpt-5.6-luna`), `GPT-5.6 Terra` (`gpt-5.6-terra`), `GPT-5.6 Sol` (`gpt-5.6-sol`)<br>**중급 도우미**: `GPT-6 Sol` (`gpt-6-sol`) | **GPT-6.1 플래그십**: `GPT-6.1 Sol` (`gpt-6.1-sol`), `GPT-6.1 Terra` (`gpt-6.1-terra`)<br>**GPT-6 표준**: `GPT-6 Astra` (`gpt-6-astra`), `GPT-6 Sol` (`gpt-6-sol`), `GPT-6 Luna` (`gpt-6-luna`)<br>**GPT-5.6 경량·안정화**: `GPT-5.6 Sol` (`gpt-5.6-sol`), `GPT-5.6 Terra` (`gpt-5.6-terra`), `GPT-5.6 Luna` (`gpt-5.6-luna`) | `reasoning_effort`: `Low` / `Medium` / `High` |
| **Antigravity (`antigravity`)** | `ollama` (`qwen2.5-coder:7b`) | **주력 공식 도우미**: `Gemini 3.8 Flash` (`gemini-3.8-flash`)<br>**경량·보조 도우미**: `Gemini 3.7 Flash` (`gemini-3.7-flash`), `Gemini 3.6 Flash` (`gemini-3.6-flash`)<br>**오픈소스 도우미**: `GPT-OSS-120b` (`gpt-oss-120b`) | **Gemini 계열**: `Gemini 4 Argon` (`gemini-4-argon`), `Gemini 3.1 Pro` (`gemini-3.1-pro`), `Gemini 3.8/3.7/3.6 Flash`<br>**Claude 계열**: `Claude Sonnet 5.5 (thinking)` (`claude-sonnet-5-5-thinking`), `Claude Opus 5.5 (thinking)` (`claude-opus-5-5-thinking`)<br>**오픈소스 계열**: `GPT-OSS-120b` (`gpt-oss-120b`) | `thinking_level`: `Low` / `Medium` / `High` |
| **Claude Code (`claude`)** | `ollama` (`qwen2.5-coder:7b`) | **주력 공식 도우미**: `Claude Haiku 5.5` (`claude-haiku-5-5`, 12,000 tok 상한) | **Claude 계열**: `Claude Opus 5.5` (`claude-opus-5-5`), `Claude Sonnet 5.5` (`claude-sonnet-5-5`), `Claude Haiku 5.5` (`claude-haiku-5-5`) | `effort`: `Low` / `Medium` / `High` |

### 5.2 카드별 병렬 세션 · 5대 프로세스 레인 · 세부 단계(`SP1`~`SP5`)별 자동 선정 규칙

1. **`SP1_RESEARCH_DRAFT` (선행 리서치·초안 / `ARCH_DESIGN` 입구)**:
   - 계산기: `ollama` (`local_search` + `local_draft`)
   - 도우미 모델 + Thinking Level:
     - `codex`: `gpt-5.6-luna` (`Low`)
     - `antigravity`: `gemini-3.7-flash` (`Low`)
     - `claude`: `claude-haiku-5-5` (`Low`)
   - 추론 모델 + Thinking Level:
     - `codex`: `gpt-6-sol` (`Low`)
     - `antigravity`: `gemini-3.8-flash` (`Low`)
     - `claude`: `claude-sonnet-5-5` (`Low`)
2. **`SP2_MIA_DESIGN_AUDIT` (MIA 11단계 세부설계·반례감사 / `ARCH_DESIGN`)**:
   - 계산기: `ollama` (`local_read_map`)
   - 도우미 모델 + Thinking Level:
     - `codex`: `gpt-6-sol` (`Medium`)
     - `antigravity`: `gemini-3.8-flash` (`Medium`)
     - `claude`: `claude-haiku-5-5` (`Medium`)
   - 추론 모델 + Thinking Level:
     - `codex`: `gpt-6.1-sol` (키포인트) 또는 `gpt-6-astra` (`High`)
     - `antigravity`: `gemini-4-argon` 또는 `claude-opus-5-5-thinking` (`High`)
     - `claude`: `claude-opus-5-5` (`High`)
3. **`SP3_CODE_EXECUTION` (5:3:2 이원 분리 병렬 구현 / `IMPL_CODE`)**:
   - 계산기(50% `code_lane`): `ollama` (`qwen2.5-coder:7b`, `v7_harness/*.py` 20~30줄 슬라이스)
   - 도우미 모델(30% `test_doc_lane`, `tests/*` & `docs/*` 병렬 실행):
     - `codex`: `gpt-6-luna` (`Medium`, 고부하 시 `gpt-5.6-luna` `Low`)
     - `antigravity`: `gemini-3.8-flash` (`Medium`, 오픈소스 벌크 시 `gpt-oss-120b` `Low`)
     - `claude`: `claude-haiku-5-5` (`Medium`, 12,000 tok 캡)
   - 추론 모델(20% 감독·통합):
     - `codex`: `gpt-6-astra` (`Medium`)
     - `antigravity`: `gemini-4-argon` (`Medium`)
     - `claude`: `claude-sonnet-5-5` (`Medium`)
4. **`SP4_INDEPENDENT_VERIFY` (독립 인수검증·교차판정 / `VERIFY_AUDIT`)**:
   - 계산기: `ollama` (`gate_log_summary`)
   - 도우미 모델(사전 트리아지):
     - `codex`: `gpt-5.6-terra` (`Low`)
     - `antigravity`: `gemini-3.7-flash` (`Low`)
     - `claude`: `claude-haiku-5-5` (`Low`)
   - 추론 모델(독립 반례 감사 `author != judge`):
     - `codex`: `gpt-6.1-terra` (`High`)
     - `antigravity`: `gemini-3.1-pro` 또는 `claude-sonnet-5-5-thinking` (`High`)
     - `claude`: `claude-opus-5-5` (`High`)
5. **`SP5_MERGE_AND_RUNTIME` (무승인 PR 병합·런타임 재설치 / `MERGE_RELEASE`)**:
   - 도우미 모델:
     - `codex`: `gpt-5.6-luna` (`Low`)
     - `antigravity`: `gemini-3.6-flash` (`Low`)
     - `claude`: `claude-haiku-5-5` (`Low`)
   - 추론 모델:
     - `codex`: `gpt-5.6-sol` (`Low`)
     - `antigravity`: `gemini-3.8-flash` (`Low`)
     - `claude`: `claude-sonnet-5-5` (`Low`)
6. **`RECOVERY_OPS` (장애·고착·데드락 복구 레인)**:
   - 도우미 모델: `codex` `gpt-5.6-terra` (`Medium`), `antigravity` `gemini-3.7-flash` (`Medium`), `claude` `claude-haiku-5-5` (`Medium`)
   - 추론 모델: `codex` `gpt-6.1-terra` (`High`), `antigravity` `gemini-4-argon` (`High`), `claude` `claude-opus-5-5` (`High`)

---

## Stage 7–8. 구현 계획 및 검증 게이트

- **신규 파일**: `v7_harness/coord/helper_thinking_router.py`
- **연동 파일**:
  - `v7_harness/coord/capacity_planner.py`: `build_capacity_aware_schedule`, `build_sub_process_schedule`, `compute_subworker_optimization`에 3대 도구 공식 도우미 모델·추론 모델·Thinking Level 자동 선정 결과 바인딩 및 `SP3_CODE_EXECUTION` 비-Claude `ollama || ollama` 병목 수정(기존 테스트 호환 키 유지).
  - `v7_harness/delegation.py`: 3대 도구 5:3:2 도우미 병렬 라우팅 헬퍼(`compute_3tool_helper_parallel_plan`) 연동.
  - `v7_harness/cli.py`: `coord helper-matrix` 서브커맨드(또는 `coord capacity` 통합 출력) 지원.
  - `uaos_everywhere/uaos_global_rule_block.md`: 3대 도구 공식 도우미 모델·추론 라인업·Thinking Level 자동 선정 규칙 반영.
- **검증 테스트**: `tests/test_u297_helper_thinking_orchestration.py`
