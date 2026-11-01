# U287: 보조 작업자 통합 사용 기록 계약 (HUD U286과 분리)

유지 문서 · Claude 작성(Codex 권한 위임 중, CODEX_REREVIEW) · Antigravity 판정 대상 · 2026-11-02

## 왜 필요한가

U281로 보조 작업자가 네 갈래가 되었다: Ollama(로컬), Haiku 5.5(Claude 보조),
GPT-6 Luna(Codex 보조), Gemini 3.8 Flash Low(Antigravity 보조). 그런데 사용 기록은
쓰는 곳마다 모양이 달랐고, `coord capacity`의 `_classify_engine`은 `worker`·`model`
글자를 추측해 엔진을 정했다. 같은 기록 형식이 없으면 RSI 장부와 용량 계산이 서로 다른
숫자를 보고, HUD(U286) 화면 배치를 바꿀 때마다 계산이 흔들린다.

U287은 **기록 한 장의 모양(계약)** 만 정한다. 화면 배치는 U286이 맡고, 이 계약은 HUD를
가져오지(import) 않는다. HUD는 계약이 만든 요약을 읽기만 한다.

## 근거

- 필드 이름은 OpenTelemetry 생성형 AI 의미 규약을 따른다: 입력·출력 토큰을 따로 기록하고
  요청 모델을 정확히 남긴다
  ([GenAI spans](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans)).
  해당 규약은 아직 Development 단계이므로 이름만 빌리고 그대로 의존하지는 않는다.
- 전역 규칙: 모든 Ollama·Haiku 시도는 호출자·프로젝트·작업·모델·입력 해시·시간·토큰·오류·관문을
  기록하고 **프롬프트는 남기지 않는다**.
- U281 문서: 보조 모델은 정확히 고정(exact pin)되고 다른 모델로 자동 대체하지 않는다.
  Luna managed 경로는 토큰 영수증이 없어 토큰이 UNKNOWN일 수 있다.

## 계약 `uaos-helper-telemetry-v1`

기록은 기존 장부 `.coord/usage/runs.jsonl`(스키마 `uaos-usage-v2`)에 한 줄로 들어간다.
따라서 기존 잠금·비밀값 검사·워크트리 공용 장부 규칙(U72-L)을 그대로 쓴다.

| 필드 | 뜻 |
|---|---|
| `telemetry` | 항상 `uaos-helper-telemetry-v1` |
| `kind` | 항상 `helper` (RSI의 pilot 성공률 계산에 섞이지 않음) |
| `helper_lane` | `ollama`, `haiku`, `luna`, `flash` 중 하나 |
| `budget_engine` | 이 호출이 차감되는 예산: ollama→ollama, haiku→haiku, luna→codex, flash→antigravity |
| `model` | haiku·luna·flash는 정확한 고정 모델과 같아야 함, ollama는 비어 있지 않은 모델 이름 |
| `actor` / `caller` | 호출한 도구: `codex`, `claude`, `antigravity` |
| `project`, `work_id` | 어느 프로젝트의 어느 작업인지 |
| `input_hash` | 입력의 SHA-256(소문자 64자리 16진수); 프롬프트 원문 대신 남김 |
| `input_tokens`, `output_tokens` | 0 이상 정수, 영수증이 없으면 `null` |
| `token_status` | 둘 다 숫자면 `MEASURED`, 아니면 `UNKNOWN` |
| `wall_time_s`, `outcome`, `error`, `gate`, `receipt` | 시간·결과·오류·통과한 관문·증거 경로 |
| `rsi_eligible` | 독립 검증자가 있고 호출자와 다를 때만 `true` (작성자 ≠ 판정자) |

거부 규칙: 모르는 갈래·호출자, 고정 모델 불일치(`HELPER_MODEL_MISMATCH`), 잘못된 해시,
`prompt`·`messages`·`content`·`completion`·`response_text` 같은 원문 필드는 모두 기록 전에
`UsageRejected`로 막는다.

## 읽는 쪽

- `coord capacity`: `_classify_engine`은 계약 기록이면 글자 추측 대신 `budget_engine`을 쓴다.
  스냅숏에는 `helper_telemetry` 요약(갈래별 호출 수·토큰·UNKNOWN 토큰 호출 수·실패 수, 24시간)이 붙는다.
- RSI: `read_helper_records()`와 `summarize()`로 같은 장부를 읽는다. pilot 지표는 `kind == "pilot"`만
  세므로 보조 기록이 성공률을 오염시키지 않는다.
- HUD(U286): 스냅숏의 `helper_telemetry`를 읽어 표시만 한다.

## 고정 인수

`python -m unittest tests.test_u287_helper_telemetry -v` 가 판정 기준이다.
절감 효과는 측정 전까지 UNMEASURED로 둔다.
