# 108. UAOS-RSI 구독별 토큰예산 할당 및 고가모델 운용 매뉴얼 (U304-D)

- 범위: OS 전체(모든 프로젝트, Claude Code·Codex·Antigravity 3도구 공통). 카드 전용 문서가 아니다.
- 구현: `v7_harness/coord/usage_budget.py`, 명령 `uaos coord budget`, 시험 `tests/test_u304d_usage_budget.py`.
- 상태: maintained(의도·시험 기록 유지). 2026-11-04 윤겸스 2차 지시(Item 7)로 작성.
- 작성자 claude, 판정자 antigravity(작성자 ≠ 판정자). Codex 복귀 뒤 재검토 대상.

---

## 1. 왜 이 문서가 있는가 (한 문단 요약)

UAOS-RSI의 근본 목적은 **"3도구의 부족한 구독 예산으로 최대 성과를 내되, 결과물 품질은 절대 낮추지 않는다"**이다.
지금까지 Claude만 "Ollama 50 : 도우미 30 : 핵심 20"이라는 **고정 표시**를 갖고 있었고, Codex·Antigravity는 비율이 없었다.
게다가 그 비율은 측정값이 아니라 글자였다. 이 문서와 코드는 다음 세 가지를 바꾼다.

1. **장부(ledger)**: 구독 계정마다 5시간·주간 창의 사용률, 남은 양, 초기화(reset) 시각을 계속 기록한다.
2. **할당기(allocator)**: 도구마다 *자기 구독과 자기 측정값으로* 작업 비율과 속도(pacing)를 계산한다. 3도구가 같은 규칙을 쓴다.
3. **고가 모델 규칙 — 요금제마다 다르게**:
   - $20 요금제(Claude Pro, ChatGPT Plus): Opus 5.5 xhigh / GPT-6 Astra High는 드문 **한방처방**이다.
     서면 입장 조건을 통과한 핵심 단계에서만, 사용 상한(10 %) 안에서 쓴다.
   - Google AI Ultra(Antigravity): $20 요금제보다 최상위 모델 한도가 약 5배다. 그래서 Gemini 4 Argon High는
     드문 처방이 아니라 **고품질 작업의 주력 경로(main route)**다. 측정된 주간 풀이 허락하는 만큼 자주 쓰고,
     속도만 조절해 주간 풀이 초기화까지 버티게 한다(속도 조절 없이 쓰면 약 2일에 소진 — 사용자 영수증).
   - 그 밖의 일반 작업은 3도구 모두 비용 효율 모델(토큰당 싸고 성능 좋은 모델)로 한다.

그리고 **마스터·세부 스케줄을 쓰는 모든 코드는 반드시 `budget_snapshot()`을 읽어야 하며**, 신선한 스냅숏 없이
쓴 스케줄은 실패 처리(fail closed)된다.

---

## 2. 용어 (처음 보는 사람용)

| 용어 | 뜻 |
|---|---|
| 5시간 창 (5h window) | 공급자가 5시간 단위로 다시 채워 주는 사용 한도. 초기화 시각이 지나면 0 %부터 다시 쌓인다. |
| 주간 창 (7d window) | 7일(10080분) 단위 한도. 5시간 창이 다시 차도 주간 창은 그대로다. |
| 사용률 (used %) | 공급자 화면이 보여 주는 숫자. **유일한 권위값**이다. |
| 보정 (calibration) | 장부가 센 토큰 수 ÷ 공급자 사용률 변화 = "1 %당 토큰 수". 표본 수(n)와 함께만 쓴다. |
| 지속가능 속도 (sustainable) | 남은 % ÷ 초기화까지 남은 시간. 이 속도로 쓰면 정확히 초기화 순간에 0이 된다. |
| 실측 소모 속도 (burn) | 실제로 % 가 줄어든 속도(%/시간). |
| 여유비 (headroom) | 지속가능 ÷ 실측. 1 이상이면 초기화까지 버팀, 1 미만이면 먼저 바닥난다. |
| 핵심(core) / 도우미(helper) / 로컬(local) | 도구의 주력 유료 모델 / 같은 구독의 싼 모델 / 내 PC의 Ollama(유료 토큰 0). |
| 한방처방 (flagship) | $20 요금제의 드문 최고가 경로(Opus 5.5 xhigh, GPT-6 Astra High). |
| 주력 경로 (main route) | Ultra 요금제의 Argon High. 입장 심사 없이, 측정된 속도 안에서 고품질 작업에 자주 쓴다. |

---

## 3. 구독과 모델 (2026-11-04 기준)

| 도구 | 구독 | 핵심 모델 | 도우미 | 한방처방 | 계정 |
|---|---|---|---|---|---|
| Claude Code | Claude Pro $20 | claude-opus-5-5 (medium) | claude-haiku-5-5 | claude-opus-5-5 (xhigh) | 1 |
| Codex | ChatGPT Plus $20 | gpt-6.1-sol (medium) | gpt-6-luna | gpt-6-astra (high) | 1 |
| Antigravity | Google AI Ultra (화면 표시 "Pro 대비 5x") | gemini-4-argon (medium) | gemini-3.5-flash-lite | gemini-4-argon (high) | 5 (구독 1 + 무료 4) |

- 모델 배정은 U304-B 결론(`helper_thinking_router`)과 같다. 고가 경로는 3도구 모두 "핵심 모델(또는 상위 모델)을
  High 이상"이다. 다만 **얼마나 자주 쓰는지**는 요금제마다 다르다(6장).
- "Pro 대비 5x"는 화면 표시 문구다. **토큰 수로 바꾸지 않는다**. Ultra 주력 경로의 계획 목표(최소 5배 빈도)에만 쓰고,
  실제 빈도는 측정된 주간 풀이 정한다.

### 3.1 요금제 한도 (공식 문서가 밝힌 것만, 9.1 출처)

| 요금제 | 5시간 창 | 주간 창 | 공식 숫자 | 이 문서의 처리 |
|---|---|---|---|---|
| Claude Pro $20 | 있음 (Claude·Claude Code 공용) | 있음 | 비공개 | 사용률 %만 측정해 기록, 토큰으로 바꾸지 않음 |
| ChatGPT Plus $20 (Codex) | 있음 — 5시간당 메시지 추정치: GPT-6 Astra 5–45, GPT-6.1 Sol 15–160, GPT-6 Luna 350–3,000 | "적용될 수 있음" | 메시지 범위만 공개 | 사용률 %와 메시지 범위 둘 다 기록; Astra가 가장 적어 한방처방 대상 |
| Google AI Ultra (Antigravity) | 있음 — "5시간마다 갱신" | 있음 — "가장 높은 주간 한도" | 비공개 (화면 표시 "Pro 대비 5x") | 5x는 계획 목표에만 사용, 실제 빈도는 측정된 주간 풀 |

- 왜 숫자를 지어내지 않는가: 세 요금제 모두 토큰 수를 공개하지 않는다. 남은 % 를 토큰으로 바꾸면 근거 없는 숫자가 생기므로
  (전역 규칙 "remaining-quota % 를 토큰으로 바꾸지 않는다"), 토큰이 필요하면 측정한 보정값(Δtokens/Δ%)만 쓴다.
- 결과: $20 두 요금제는 Opus 5.5 xhigh·GPT-6 Astra High를 드물게(상한 10%, 6.1–6.2) 쓰고, Ultra는 Argon High를
  주력 경로로(목표 50% = $20 상한의 5배, 6.3) 쓰되 측정된 풀이 실제 상한이다.

---

## 4. 측정 원천 (전부 읽기 전용, 유료 토큰 0, 자격 증명 읽지 않음)

| 원천 | 무엇을 주나 | 담당 코드 |
|---|---|---|
| Codex 롤아웃 `~/.codex/sessions/**/rollout-*.jsonl` `rate_limits` | Codex 5h·7d 사용률, 초기화 시각 | `quota_sources.codex_quota` (U303) |
| cockpit-tools 캐시 `~/.antigravity_cockpit/cache/quota_api_v1_plugin/*/*.json` | Antigravity 계정별 풀(pool) 잔량, 초기화 | `quota_sources.antigravity_quota`, `usage_budget.antigravity_account_pools` |
| Claude statusLine 기록 `~/.uaos/usage/claude_rate_limits.jsonl` | Claude 5h·7d 사용률 | `quota_sources.claude_quota` (U303-B) |
| Claude 데스크톱 사용량 카드(`get_usage`) 또는 `/usage` 읽기 → `coord budget --action observe` | statusLine 기록기가 없을 때의 Claude 사용률 | `usage_budget.record_observation` |
| `~/.uaos/usage/ledger.sqlite3` `contributions` | 모델별 7일 호출 수·출력 토큰, Claude 토큰 사건 | `quota_sources.model_mix_7d`, `usage_budget.claude_events` |
| `~/.uaos/usage/invocations.sqlite3` `attempts` | 호출 도구별 Ollama·도우미 시도(성공/실패, 토큰) | `usage_budget.offload_attempts` |
| U286 계정 등록부 | Antigravity 5계정의 요금제·종류·429 차단 | `agy_accounts.antigravity_accounts` |

**지켜야 할 규칙**: 남은 %를 토큰으로 바꾸는 것은 보정값(1 %당 토큰)과 표본 수가 있을 때뿐이다. 보정이 없으면
화면에 `uncalibrated`가 나오고 토큰 칸은 `-`이다. 측정되지 않은 비율은 `UNMEASURED`로 표시하고 추측값을 넣지 않는다.

### 4.1 장부 파일

`~/.uaos/usage/budget_ledger.sqlite3` (SQLite, WAL 모드). 표 세 개:

- `observations`: 도구·계정·창(5h/7d)·사용률·초기화·관측 시각·출처. 같은 관측은 한 번만 들어간다(UNIQUE).
- `burn_receipts`: 모델별 소모 속도 영수증. 예: Argon High 연속 사용 시 Ultra 주간 풀 100 %/48 h = 2.083 %/h
  (윤겸스 영수증 2026-11-04).
- `snapshots`: 스냅숏마다 도구별 상태·여유비·비율·한방처방 몫 요약. 시간이 지나며 계속 쌓이는 연속 장부다.

**왜 SQLite인가**: Windows에서 여러 프로세스가 같은 텍스트 파일에 동시에 덧붙이면 줄이 사라진다(전역 규칙).
SQLite는 프로세스 사이의 쓰기를 스스로 직렬화한다. 시험 `test_eight_processes_append_without_losing_rows`가
**실제 프로세스 8개 × 40행 = 320행**을 동시에 써서 320행이 모두 남는 것을 확인한다.

---

## 5. 계산 방법

### 5.1 속도(pacing) — 초기화까지 버티는가

```
지속가능 속도 S = 남은 % ÷ 초기화까지 남은 시간(h)
실측 속도 B   = ① 같은 초기화 창 안의 장부 관측 두 점 기울기 (10분 이상 떨어지고 3점 이상 상승)
                ② 없으면 창 평균 = 관측 시점 사용률 ÷ 관측 시점까지 창이 열려 있던 시간
여유비 k     = S ÷ B          (k ≥ 1 버팀, k < 1 먼저 바닥)
바닥 예상    = 남은 % ÷ B 시간 뒤
```

- 도구의 여유비는 **더 빡빡한 창**이 정한다(5h와 7d 중 작은 값). 한 창이라도 0 %가 남으면 그 도구는 `LIMITED`.
- 관측이 없으면 여유비는 `None`(중립)이다. 낙관하지 않는다: 비율은 측정된 그대로 두고 한방처방도 열지 않는다.

**숫자 근거**

| 값 | 이유 |
|---|---|
| 기울기 최소 간격 10분 | Claude·Codex 사용률은 정수라 2분에 1점이면 30 %/h로 읽히는 반올림 잡음이 생긴다. |
| 기울기 최소 상승 3점 | 정수 반올림 오차 ±1점을 기울기 오차 1/3 이하로 묶는다. 실측 영수증: 주간 82→83 %를 11분에 읽으면 5.5 %/h로, 창 평균(0.89 %/h)의 6배였다. |
| 기울기 조회 6시간 | 5시간 창 하나 + 여유. 더 오래된 점은 다른 작업 속도를 말한다. |
| 초기화 일치 허용 600초 | 같은 창의 초기화 시각이 관측마다 초~분 단위로 흔들린다. |
| 관측 낡음 6시간 | 6시간 지난 읽기는 5시간 창을 설명하지 못한다. 값은 보여 주되 `STALE`로 표시한다. |

### 5.2 작업 비율 할당 — 같은 규칙, 도구마다 다른 결과

1. **측정 비율**: 지난 7일 단계 수를 로컬(그 도구가 부른 Ollama 성공) / 도우미 / 핵심으로 센다.
2. **품질 경계(3도구 공통)**: 로컬 ≤ 50 %, 도우미 ≤ 30 %, 핵심 ≥ 20 %.
   이 숫자는 Claude의 기존 표시 "50:30:20"을 **목표가 아니라 품질 한계**로 읽은 것이다.
   - 로컬 50 %: Ollama는 고정 입력의 기계적 연산만 한다(전역 규칙). 단계 절반을 넘기면 판단이 필요한 단계까지 넘어간다.
   - 도우미 30 %: 사용자가 정한 표시의 상한.
   - 핵심 20 %: 설계·판정·인수는 유료 모델의 일이다(전역 규칙 "paid models design/judge/accept").
3. **단계당 비용**: 핵심 1, 도우미 `c_h`, 로컬 0.
   - Codex `c_h`: OpenAI 공식 Plus 5시간당 메시지 추정치의 중간값 비율(Sol 87.5 ÷ Luna 1675 = 0.052, Terra 0.547),
     실제 사용한 도우미 호출 수로 가중 평균. 출처 https://learn.chatgpt.com/docs/pricing
   - Claude·Antigravity `c_h`: 공급자가 토큰당 한도 가중치를 공개하지 않는다. 측정 가능한 것은 호출당 출력 토큰 비율뿐이고,
     이 값이 1 이상이면(2026-11-04 Claude 1.04) **도우미 절약을 주장하지 않는다**(c_h = 1로 계산).
4. **여유비 k ≥ 1**: 측정 비율을 그대로 둔다(품질을 깎을 이유가 없음).
5. **k < 1**: 단계당 유료 비용을 k배로 낮춰야 한다. 순서대로 옮긴다.
   핵심→도우미(품질이 핵심에 가장 가까움) → 핵심→로컬 → 도우미→로컬. 경계는 넘지 않는다.
6. 경계까지 옮겨도 모자라면 **품질을 더 깎지 않고 속도를 늦춘다**: `paid_step_rate` = 목표 비용 ÷ 남은 비용.
   예: 0.5면 유료 단계를 지금의 절반 속도로 진행한다(남는 시간은 로컬 준비·검증·다른 도구로 돌린다).

### 5.3 실측 예시 (2026-11-04 01:09 KST, 이 PC)

| 도구 | 창 | 사용 | 남은 시간 | 실측 B | 지속가능 S | 여유비 | 결과 비율 / 속도 |
|---|---|---|---|---|---|---|---|
| Claude | 7d | 83 % | 74.8 h | 0.891 %/h (창 평균) | 0.227 %/h | 0.255 | Ollama 50 : 도우미 10 : 핵심 40, 유료 속도 0.50 |
| Codex | 7d | 100 % | 19.9 h | 소진 | 0 | 0 | `LIMITED` (2026-11-04 22:03 KST 초기화까지) |
| Antigravity | 7d (Gemini 풀) | 76.9 % | 108.7 h | 1.629 %/h (창 평균) | 0.213 %/h | 0.13 | Ollama 50 : 도우미 1 : 핵심 49, 유료 속도 0.26 |

교차 확인: Antigravity 창 평균 1.63 %/h는 사용자 영수증 "Argon High는 주간 풀을 약 2일에 소진"(2.08 %/h)과 같은 크기다.
측정과 영수증이 서로 맞는다.

같은 시각 Antigravity 주력 경로(6.3): 단계당 비용 0.0466 %/단계(창 평균 1.63 %/h ÷ 측정 34.6 단계/h),
빈도 = (23.1 − 10) ÷ 0.0466 ÷ 108.7 h = **시간당 Argon High 2.6단계, 5시간에 12단계**(유료 단계의 7.4 %).
5배 목표(50 %)에는 못 미친다. 이번 주 풀이 이미 77 % 쓰였기 때문이며, 측정값이 목표보다 우선한다.
같은 시각 Opus·Astra 한방처방 몫은 0(속도 뒤처짐·Codex 소진)이므로, 실제 빈도는 이미 $20 요금제의 5배 이상이다.

---

## 6. 고가 모델 규칙 (요금제별)

요약: $20 요금제의 Opus 5.5 xhigh·GPT-6 Astra High는 **드문 한방처방**(6.1·6.2), Ultra의 Argon High는
**측정 속도로 조절하는 주력 경로**(6.3)다. 근거는 윤겸스 정정 지시(2026-11-04): Ultra는 $20 요금제의 약 5배 최상위 모델
한도를 주므로 Argon High 계획 빈도는 Opus·Astra의 최소 5배여야 하고, 목표는 "토큰 예산당 최대 성과 = 측정된 여유가 허락하는
만큼 최고 모델을 자주 쓰기"다.

### 6.1 $20 요금제 입장 조건 (모두 통과해야 함, `flagship_gate`)

| 규칙 | 조건 | 숫자 근거 |
|---|---|---|
| R0 신선도 | 스냅숏 나이 ≤ 15분 | 5.1의 최고 실측 속도(Claude 5h ≈ 14 %/h)로 15분 = 약 3.5점. 판정이 바뀌는 5점 단위보다 작다. |
| R1 중요도 × 난이도 | 각 1~5, 곱 ≥ 16 | 16 = 두 요소 모두 "높음(4)" 이상. 3 × 5 = 15는 일부러 떨어진다: 한 축만으로 고가 모델을 사지 못한다. |
| R2 싼 경로 불충분 | 싼 경로의 실패한 `work_id`가 있거나, 핵심 단계 종류 | 종류: `architecture_decision`, `final_verdict`, `security_review`, `merge_gate`, `root_cause_after_two_failures`(같은 원인 2회 실패 뒤, 전역 규칙과 같은 2회). |
| R3 예산 | 할당기가 한방처방 몫 > 0을 주고, 이번 5시간 상한 미사용 | 아래 6.2. |

하나라도 떨어지면 그 단계는 **비용 효율 핵심 모델**(Opus medium, Sol medium)로 간다.

### 6.2 $20 요금제 사용 상한 (`flagship_allowance`)

| 항목 | 값 | 근거 |
|---|---|---|
| $20 요금제(Claude Pro, ChatGPT Plus) 상한 | 유료 단계의 10 % | UAOS 카드 한 장은 MIA 11단계. 카드당 핵심 1단계 = 1/11 ≈ 9 % → 10 %. |
| 주간 예비분 | 10 %포인트 | 카드 한 장의 판정+검증 실행 몫. 남은 주간이 10 % 이하면 한방처방 0. |
| 5시간 최소 잔량 | 20 % | 그 아래는 남은 실행을 검증용으로 남긴다. |
| 몫 계산(영수증 있음) | 지속가능 %/h × (남은 − 예비)/남은 ÷ 영수증 %/h | 고가 모델만 돌렸을 때도 초기화까지 버티는 가동률. $20 요금제에 측정 영수증이 생기면 쓰는 경로(Argon High는 6.3). |
| 몫 계산(영수증 없음) | (여유비 − 1) ÷ (f − 1) | 핵심 단계 s를 f배 비싼 고가 모델로 바꾸면 소모가 s(f−1)만큼 는다. 남는 여유(k−1) 안에서만 허용. |
| f (Codex) | 3.5 | 공식 추정치 Sol 87.5 ÷ Astra 25 메시지/5h. |
| f (Claude) | 3.5 (빌림) | Opus xhigh 대 medium 비율은 공개되지 않음. 유일한 공식 측정값이자 가장 큰 값(Codex)을 빌려 몫을 작게 잡는다. |
| 5시간 단계 상한 | ⌊몫 × 측정된 5시간당 유료 단계⌋, 최소 1 | 예산이 조금이라도 허락하면 "한방" 한 번은 쏠 수 있다. |
| 여유비 < 1 또는 미측정 | 몫 0 | 바닥이 먼저 오는 중에는 고가 모델을 쓰지 않는다. |

### 6.3 Ultra 주력 경로: Argon High 빈도 (`main_route_allowance`)

Argon High에는 R1(중요도×난이도)·R2(싼 경로 실패) 심사가 **없다**. 고품질이 필요한 단계는 누구나 쓸 수 있고,
측정 속도(R0 신선도 + R3 5시간 단계 상한)만 지킨다. 계산:

```
빈도(단계/시간) = (측정된 남은 주간 % − 예비 10 %포인트) ÷ 측정된 Argon High 1단계 비용(%) ÷ 초기화까지 남은 시간
1단계 비용(%)   = ① 보정이 있을 때: 측정 토큰/단계 ÷ 보정 토큰/1 %   (사용자 공식의 토큰 형태)
                  ② 측정 창 소모 속도(%/h) ÷ 측정 유료 단계/시간(7일 단계 ÷ 168 h)  (같은 양을 % 단위로)
                  ①②가 둘 다 있으면 더 비싼 쪽 (풀이 초기화까지 버티는 쪽)
몫(share)       = 빈도 ÷ 측정 유료 단계/시간   (최대 1 = 모든 유료 단계)
5시간 상한      = ⌊빈도 × 5⌋, 1 미만이면 몫 0
```

| 항목 | 값 | 근거 |
|---|---|---|
| 계획 목표 | 유료 단계의 50 % 이상 | Ultra ≈ $20 요금제의 5배 한도 → 한방처방 상한 10 % × 5. **목표일 뿐**, 측정 풀이 더 적게 허락하면 측정값을 따르고 `below 5x target`으로 표시한다. |
| 상한 | 100 % | 주력 경로이므로 인위적 상한이 없다. 측정 속도가 유일한 한계. |
| 주간 예비분 | 10 %포인트 | 카드 한 장의 판정+검증 몫이며, 영수증(100 %/48 h) 기준 연속 Argon High 약 4.8시간 = 주말에 남겨 두는 작업 세션 하나. 이 덕분에 풀이 초기화 전에 0이 되지 않는다. |
| 두 측정이 다를 때 더 비싼 쪽 | — | 2026-11-04 실측: 보정 경로 0.019 %/단계(보정 n=1) vs 소모 경로 0.047 %/단계. 표본이 적은 쪽을 믿고 과사용하면 주간 풀이 먼저 바닥난다. |
| 영수증 가동률 | 교차 확인용 | 지속가능 %/h × 쓸 수 있는 비율 ÷ 2.083 %/h. 계산에는 쓰지 않고 `receipt_duty`로 보여 준다. |
| 공백 | effort 미기록 | Antigravity 장부는 단계마다 medium/high를 구분하지 않는다. 그래서 ②의 단계 비용은 실제 사용 혼합의 평균이다(사용자 보고: 대부분 Argon High). effort가 기록되면 High 단계만의 비용으로 바뀐다. |

**$20 요금제와의 관계**: 같은 스냅숏에서 Ultra 몫이 Opus·Astra 몫의 5배 이상인지 시험이 확인한다
(`test_ultra_main_route_frequency_from_burn_per_step`). 속도 조절 없이 쓰면 2일에 풀을 비우지만, 이 공식은
"남은 % ÷ 남은 시간"으로 빈도를 깎으므로 그 일을 막는다.

---

## 7. 사용법

### 7.1 현황 보기

```bash
uaos coord budget --project <프로젝트 루트>            # 15분 안의 스냅숏이 있으면 그것, 없으면 새로 계산
uaos coord budget --project <프로젝트 루트> --refresh  # 새로 계산
uaos coord budget --project <프로젝트 루트> --json     # 전체 JSON
```

출력의 각 줄: 창별 사용/남음/초기화/실측 속도[근거]/지속가능 속도/남은 토큰[보정 근거], 측정 7일 단계 수, 계산된 비율과
유료 속도, 한방처방 몫·상한·막힌 이유, 오프로드로 아낀 양, Antigravity 계정 5개(이메일은 가림).

### 7.2 Claude 사용률 기록 (statusLine 기록기가 없을 때)

Claude 세션은 데스크톱 사용량 카드(`get_usage`) 또는 `/usage`를 읽고 그대로 기록한다(유료 토큰 0).

```bash
uaos coord budget --action observe --tool claude --window 5h --used-pct 65 --resets-at 2026-11-03T17:49:59Z --source ccd_get_usage
```

같은 관측을 두 번 넣어도 한 번만 남는다. 두 번 이상 기록하면 기울기(실측 속도)가 생긴다.

### 7.3 고가 모델 입장 심사

```bash
uaos coord budget --action gate --tool codex --importance 5 --difficulty 4 --keypoint-class final_verdict
```

종료 코드 0 = 허용(모델·추론강도 출력), 1 = 거부(떨어진 규칙 목록과 대신 쓸 핵심 모델 출력).
`--tool antigravity`는 R1·R2를 건너뛰고 측정 속도(R0·R3)만 본다.

### 7.4 스케줄 작성 코드의 의무 (마스터·세부 공통)

```python
from v7_harness.coord.usage_budget import budget_snapshot, stamp_schedule, validate_schedule_budget

snap = budget_snapshot(project_root)          # 반드시 먼저 호출
schedule = stamp_schedule(schedule, snap)     # 낡은 스냅숏이면 BudgetSnapshotError (fail closed)
# ... 단계마다 snap["tools"][tool]["split"]["shares"], ["paid_step_rate"], ["flagship"] 사용
validate_schedule_budget(schedule)            # 읽는 쪽: 도장 없거나 15분 넘으면 거부
```

오류 코드: `BUDGET_SNAPSHOT_MISSING`(도장/스냅숏 없음), `BUDGET_SNAPSHOT_STALE`(15분 초과), `BUDGET_SNAPSHOT_SCHEMA`.
U304-C `schedule_planner`와 U304-B `helper_thinking_router`의 고정 `target_parallel_ratio`는 그 PR들이 병합된 뒤
별도 배선 커밋으로 이 값을 읽게 바꾼다(다른 카드 파일은 이 카드 브랜치에서 고치지 않는다).

---

## 8. 측정되지 않은 것 (정직한 공백)

| 항목 | 상태 | 해소 방법 |
|---|---|---|
| Claude statusLine 기록기 | `~/.claude/settings.json`에 `statusLine` 없음 → 기록 파일 없음 | 설치 전까지 `observe`로 기록. 설치는 Claude 설정 변경이라 별도 카드. |
| Claude·Antigravity 도우미의 토큰당 한도 가중치 | 공개되지 않음 → 도우미 절약 `UNMEASURED` | 같은 창에서 도우미만 쓴 구간의 % 변화를 장부로 측정. |
| Antigravity 보정(1 %당 토큰) | U303이 보정한 풀이 선택 모델 풀일 때만 재사용 | 같은 Gemini 풀의 이력 쌍이 3개 이상 쌓이면 자동. |
| 무료 계정 4개 | cockpit 캐시가 2026-08-24 값(STALE) | cockpit-tools에서 계정을 한 번씩 새로고침하면 갱신된다. |
| 오프로드 품질 | 시도 기록의 인수(acceptance)가 모두 `UNVERIFIED` | 판정자 인수 결과를 기록하면 로컬 몫 상한을 측정값으로 바꿀 수 있다. |
| Ollama 절약 % | 로컬 토큰 ÷ 보정된 1 %당 토큰 — "같은 글을 핵심 모델이 최소 한 번 읽고 썼을 것"이라는 하한 | — |

---

## 9. 조사 근거 (Stage 0)와 대안 비교

### 9.1 공식 근거

- Antigravity 요금제: https://antigravity.google/docs/plans — Ultra "가장 넉넉한 한도, 5시간마다 갱신" + "가장 높은 주간 한도",
  Pro "5시간마다 갱신, 주간 한도까지". 구체 숫자는 비공개.
- Codex 요금·한도: https://learn.chatgpt.com/docs/pricing — Plus 5시간당 로컬 메시지 추정 GPT-6 Astra 5–45, GPT-6.1 Sol
  15–160, Terra 35–285, GPT-6 Luna 350–3,000. "주간 한도도 적용될 수 있음".
- Claude Pro 한도: https://support.claude.com/en/articles/11145838-using-claude-code-with-your-pro-or-max-plan —
  "5시간 세션 한도와 주간 한도", Claude와 Claude Code가 같은 한도를 쓴다. 숫자는 비공개.
- 병렬 쓰기: SQLite 잠금·WAL https://www.sqlite.org/wal.html, https://www.sqlite.org/lockingv3.html ;
  Python `msvcrt.locking` 문서 https://docs.python.org/3/library/msvcrt.html (바이트 범위 잠금은 덧붙이기 위치와 어긋날 수 있어 채택하지 않음).
- 기존 수집기: U303 `quota_sources.py`(보정 공식 Δtokens/Δ%), U286 `agy_accounts.py`.

### 9.2 대안 비교와 결정

| 대안 | 가치 | 실현성 | 위험 | 결정 |
|---|---|---|---|---|
| A. 고정 비율 표시 유지 (50:30:20 복사) | 낮음: 바닥나는 도구를 못 막음 | 즉시 | 측정과 무관한 글자 | No-Go |
| B. 공급자 %를 정해진 상한 토큰으로 환산해 배분 | 중간 | 쉬움 | 전역 규칙 위반(보정 없는 % → 토큰), 상한 숫자가 비공개 | No-Go |
| C. 실측 속도·여유비로 비율과 속도를 계산, 경계는 품질 한계, 고가 모델은 서면 입장 조건 | 높음 | 기존 수집기 재사용으로 가능 | 관측이 드물면 중립값 → 기록 빈도가 품질을 정함 | **Go** |

---

## 10. 고정 인수 기준 (판정자 실행)

- `python -m pytest tests/test_u304d_*.py -q` 종료 0 (병렬 프로세스 8개 장부 시험 포함).
- 전체 `python -m pytest -q -x` 종료 0, 로그 `.work/` 보관.
- 이 PC에서 `uaos coord budget --refresh`가 3도구 모두 측정 숫자를 출력.
- 스케줄 도장 없는/15분 넘은 스냅숏은 `BudgetSnapshotError`.
