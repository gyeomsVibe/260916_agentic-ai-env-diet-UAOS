# UAOS-Diet v7: Unified Agentic AI Orchestration System - AI Environment Diet v7

<!-- uaos-update:8eee03249cf9eb89a90d9f9421766b468308eee5ecebf5fb88460a08e9469569 -->
## 업데이트 (0.1.0, 2026-09-25)

- 검증된 근거만 버전된 PR 후보로 만드는 fail-closed 파이프라인과 결정적 변경 감시 스케줄러 구현.

**통합 에이전틱 AI 오케스트레이션 시스템 기반의 'AI 환경 다이어트' (약칭: UAOS)**

AI 코딩 도구 **세 개(Codex, Claude Code, Antigravity)**와 **전자계산기(Ollama)**가 한 프로젝트를 함께 하면서 **거짓 성공을 내지 않고**, **토큰 예산을 극대화하여 절약**하도록 만든 장치와 그 측정 기록입니다.

> 처음 오셨다면 [UAOS 처음부터 이해하고 사용하는 학습 가이드](docs/UAOS_처음부터_이해하고_사용하는_학습가이드.md)부터 보세요. 긴 설명은 저장소 문서에 두고, 대화창 보고는 짧고 한눈에 읽히게 합니다.

사용자의 미완성 아이디어를 근거 조사와 실행 계약으로 바꾸는 원칙, 그리고 안티그래비티·올라마 호출 전에 매뉴얼을 **파일로 발행하고 실제 입력으로 전달하는 절차**는 [네 AI 도구 운영 규칙](docs/AI_4도구_아이디어_조사와_위임전_매뉴얼_운영규칙.md)에 있습니다. 올라마의 실제 오류와 방어 관문은 [오류 방지·대체 절차](docs/올라마_오류를_막는_검증과_대체_절차.md)에 따로 설명했습니다.

토큰예산 운영은 [3대 도구 예측·역할 전환 규칙](docs/27_token-budget-routing-policy.md)에서 시작합니다. [Claude](docs/28_claude-budget-manual.md)·[Antigravity](docs/29_antigravity-budget-manual.md)·[Ollama](docs/30_ollama-calculator-manual.md) 실행 매뉴얼이 이어집니다.

사용자 5대 비유의 실현도 감사는 [docs/35](docs/35_five-metaphors-realization-audit_2026-09-25.md), 그 보강 구현 기록은 [docs/36](docs/36_metaphor-realization-implementation-record_2026-09-25.md), 모든 프로젝트에 쓰는 표준 작업 프로세스와 Ollama·Antigravity 하네스·계약 매뉴얼 설계는 [docs/37](docs/37_standard-process-and-worker-harness.md)에 있습니다.

자가개선(RSI)의 맹점 조사와 코드로 강제한 증거 관문은 [docs/38](docs/38_rsi-self-improvement-blind-spots-and-evidence-gate.md), UAOS를 이 PC의 **모든 프로젝트**에 설치하는 방법은 [uaos_everywhere/](uaos_everywhere/README.md)와 [docs/39](docs/39_uaos-everywhere-global-deployment-and-b77.md)에 있습니다. Claude Code를 파이프라인의 작업자·검증자·알림 수신자로 참여시키는 설계와 구현 기록은 [docs/40](docs/40_claude-code-in-the-uaos-pipeline-design.md), "Ollama를 재교육하면 스스로 나아지나"에 대한 계산과 작업 배정 상태 기계(U39)는 [docs/41](docs/41_ollama-retraining-myth-and-escalation-math.md), Ollama의 시스템 학습과 LoRA 실험 관문(U40)은 [docs/42](docs/42_ollama-system-level-learning-and-lora-gate-u40.md), 사용자 PC 마무리 배포를 명령 하나로 끝내는 방법(U41)은 [docs/43](docs/43_one-command-pc-rollout-u41.md), 증거 관문형 RSI 연구·PR 자동화 파이프라인(U42)은 [docs/43-U42](docs/43_evidence-to-pr-rsi-pipeline-u42.md)입니다. 진단부터 해결까지의 전 과정을 용어 설명과 함께 쉬운 말로 정리한 글은 [쉽게 읽는 UAOS 진단과 해결 전과정](docs/쉽게_읽는_UAOS_진단과_해결_전과정/00_먼저_읽기_이_폴더_사용법.md)입니다.

실행 기록을 안전하게 개선에 쓰는 방법은 [증거 관문형 RSI](docs/31_evidence-gated-rsi-for-uaos.md)와 [사용량 장부](.coord/usage/README.md)에 있습니다. **현재 구현·복귀 검증은 완료**됐습니다. 설치·첫 실행·운영·문제 해결은 [최종 사용자 안내](docs/33_uaos-final-user-guide-and-completion-briefing.md)를 따르세요. 삭제·원격 push·배포·계정/권한 변경은 계속 사용자 승인 대상입니다.

---

## 30초 요약

| 질문 | 답 |
|---|---|
| 무슨 문제를 풀었나 | AI 도구가 "다 했다"고 보고했는데 실제로는 안 한 경우, 서로의 작업을 덮어쓰는 경우, 기록이 흩어져 지휘자가 판단할 수 없는 경우 |
| 어떻게 풀었나 | 복사본에서 작업 → 정해진 검사 통과 → 그때만 원본 반영. 통과 못 하면 닫히는 잠금장치를 여러 겹(fail-closed) |
| 효과가 있었나 | 같은 과제 3개 비교에서 지휘자 입력 토큰 **−76.7%**, 출력 **−97.0%**, 도구 호출 4~6회 → 0회, 품질 동일 |
| 아직 모르는 것 | 계정 사용 한도가 실제로 얼마나 덜 닳는지, 하루 운용 기준 판정 지연 (둘 다 `UNMEASURED`) |
| 믿을 근거 | 전체 회귀 **580개 실행**(579개 통과·1개 건너뜀), 복귀 점검 13/13, U23 숨은 검사 3/3, 모든 수치는 실행 기록과 함께 저장소에 있음 |

---

## 등장하는 도구와 사용자의 5대 핵심 비유

| 도구 | 역할 | 비유 |
|---|---|---|
| **Codex** | 계획·순서·최종 판정 | 지휘자 (오케스트라) |
| **Antigravity** | 맡은 한 단계 실행·독립 검증 | 비서 / 독립 검증자 |
| **Claude Code** | 활동 중 보조 구현, 부재 시 지휘 대행 | 부지휘자 (부관) |
| **로컬 모델(Ollama)** | 비용 0원의 연산 일꾼. 주관적 판단/설계/판정권 배제, 반복 수정·요약만 수행 ([작동 원리](ollama/01_작동원리와_운영_Ollama는_어떻게_돌아가나.md)) | 전자계산기 / 유선 전화기 |

셋은 사람을 거치지 않고 **파일과 큐(queue)** 로 직접 주고받습니다.

### 사용자의 5대 핵심 비유 (The 5 Core Metaphors)

이 시스템의 모든 기술적 구조는 사용자가 직관적으로 제시한 **5대 핵심 비유**에서 출발했습니다. 상세한 기획 의도와 철학은 [사용자 핵심 철학과 비유 정의서](docs/34_user-core-philosophy-metaphors-and-intent.md)에 정본으로 보존되어 있습니다.

1. **전자계산기 (Calculator)**: 사람이 복잡한 암산을 계산기에 맡기듯, 유료 프론티어 AI(지휘자)는 코드를 손으로 직접 작성하여 비싼 토큰을 쓰지 않고 비용 0원의 로컬 올라마(Ollama) 계산기에게 지시문과 숨은 검증 인수만 넘겨 0원에 계산(수정)시킵니다.
2. **유선 전화기 (Telephone) vs 위성전화 (Satellite Phone)**: 올라마는 평소 대기하다가 필요할 때 다이얼을 걸어 즉시 응답을 받는 통화료 0원의 유선 전화기입니다. 유료 모델을 24시간 켜놓고 폴링하는 상주 감시(cron)는 초당 비용이 폭증하는 '비싼 위성전화를 켜놓고 방치하는 낭비'이므로 전면 금지합니다.
3. **음성사서함 (Voicemail / Mailbox)**: 지휘자(Codex)가 부재 중이거나 다른 작업을 수행할 때도 모든 보고와 이벤트는 100% 무손실 보존되는 디스크 우편함(`.coord/mailbox/`)에 안전하게 저장됩니다.
4. **24/7 상주 교환원 (Switchboard Operator / Sentinel)**: 로컬 올라마 상주 감시관(Sentinel)은 24시간 무료로 잠금 점검, 원장 미정리, 에러 트리아지를 전담하며, 진짜 위급한 차단 결함(P1)이 발생했을 때만 지휘자의 침실 벨을 울려(Wake-on-P1 Ringing) 선별 기상시킵니다.
5. **비둘기 메신저 퇴출 및 오케스트라 지휘 모델 (Abolishing Pigeon Work)**: 사용자가 AI 대화창 사이를 오가며 복사·붙여넣기하던 비둘기 노릇을 완전히 철폐하고, 단일 지휘자(Codex)의 마스터 계획(`.coord/PLAN.md`)과 실시간 큐를 통해 4대 도구가 질서정연하게 오케스트라처럼 협업합니다.

---

## 핵심 장치 네 가지

### 1. 파일럿 (pilot run) — 복사본에서 일하고 검사로 통과시킨다

```
원본 → 복사본(staging)에서 작업 → 인수 검사 → 통과해야만 원본 반영
                                   ↘ 실패하면 반영하지 않고 기록만 남김
```

통과를 막는 장치(무엇을 잡는지):

| 이름 | 잡아내는 상황 |
|---|---|
| `SOURCE_DIVERGED` | 작업 중에 원본이 바뀜(다른 도구가 끼어듦) |
| `EXTERNAL_WRITE` | 작업 범위 밖(집 폴더·임시 폴더)에 씀 |
| `NO_CHANGES` | 아무것도 바꾸지 않고 "완료" 주장 |
| `APPLY_NOT_OBSERVED` | 반영했다는데 원본에서 그 변화가 안 보임 |
| `APPLY_MISMATCH` | 바꿨다고 신고한 파일 목록과 실제가 다름 |
| `LATE_RESULT` | 결과가 늦게 도착해 상태를 확신할 수 없음 |

모든 시도는 **SQLite 원장(ledger)** 에 남습니다. 덮어쓰지 않고 덧붙이기만 합니다.

### 2. 조율 스트림 (coordination stream) — 세 도구의 작업을 지휘자 창 하나로

```
사건 1줄  →  .coord/stream/<날짜>.jsonl
                  ↓ 접기(마지막 판정 이후만, 60줄·6KB 상한)
          .coord/codex_brief.md
                  ↓ 상태가 바뀐 경우만 1건
     codex queue --thread <대화> --message <5줄>
                  ↓
   지휘자 창에 "다른 작업에서 …이(가) 보냄"
```

규칙: 판정 기록은 지휘자만, 실행 보고에는 명령과 종료 코드가 필수, 메시지 첫 줄은 `[DATA]`(지시가 아니라 데이터라는 표시), 값 대신 경로·해시만, 같은 내용은 두 번 보내지 않음.

### 3. 측정 (measurement) — 주장 대신 숫자

같은 과제를 두 방식으로 돌려 비교합니다.

- **A**: 지휘자 혼자 전부 수행
- **B**: 지휘자 1턴(조율) + 제어층 + 작업자

| 과제 | 입력 토큰 | 출력 토큰 | 도구 호출 | 품질 |
|---|---|---|---|---|
| P05 | −73.7% | −94.0% | 4 → 0 | 동일 |
| P06 | −80.2% | −98.3% | 6 → 0 | 동일 |
| P07 | −76.3% | −98.8% | 4 → 0 | 동일 |

조율 인계 1회 분량도 줄었습니다: 첫 표본(n=1)에서 기존 메모 평균 1,552자 → 브리핑 828자(**−46.6%**), 이후 측정 범위 828~1,450자·최신 측정 −32.2%(`.coord/runs/U15/measurement_s6.json`). 지휘자 창에 실제 들어가는 메시지는 81자.

---

### 4. 로컬 모델 (Ollama) — 토큰 0짜리 일꾼 → [`ollama/`](ollama/README.md)

이 PC에서 도는 무료 AI(`qwen2.5-coder:7b`)입니다. 세 도구는 지시가 없어도 스스로 판단해 먼저 씁니다.

- **읽기 전에 줄이기:** 큰 파일은 로컬이 줄 번호 요약본을 먼저 만들고, 비싼 AI는 가리킨 줄만 엽니다. 실제 비용 **−85.9%**, 위치 질문 8/8 적중.
- **기계적인 일 맡기기:** 정확히 적을 수 있는 수정·초안·분류·파일 찾기는 `olla` 명령으로. 계정 한도가 바닥나도 멈추지 않습니다.
- **판정은 맡기지 않기:** 합격 여부는 모델의 말이 아니라 관문(자동 검사)이 정합니다.

과정 13단계와 각 단계의 의미·목적·실측은 [ollama/README.md](ollama/README.md)에 있습니다.

## 빠른 시작

```bash
# 1) 전체 인수 테스트 (로그는 .work/logs/ 에 저장)
python .coord/runs/run_regression.py

# 2) 지금 무엇이 판정 대기인지 보기
python -m v7_harness.cli coord brief --owner "나"

# 3) 사건 한 줄 남기기 (실행·판정에는 증거가 필수)
python -m v7_harness.cli coord log --actor claude --kind RUN --step 예시 \
  --summary "무엇을 했는지 한 줄" --cmd "python -m unittest" --exit-code 0

# 4) 파일럿 실행 (작업자에게 한 단계 위임, --worker local 이면 계정 한도 대신 로컬 모델)
python -m v7_harness.cli pilot run --task T01 --source . \
  --prompt-file <할 일.md> --work-dir .work/pilot_T01 \
  --accept-cmd "python -m unittest discover -s tests -q"
```

---

## 폴더 지도

| 위치 | 내용 |
|---|---|
| `v7_harness/` | 파일럿 절차, 잠금장치, 제어층 |
| `v7_harness/coord/` | 조율 스트림·브리핑·전달기 ([사용법](v7_harness/coord/README.md)) |
| `tests/` | 인수 테스트 710개(2026-09-25) |
| `uaos_everywhere/` | 모든 프로젝트 설치기(전역 규칙 문단·출석 훅·예약 도구 차단·24/7 교환원) [안내](uaos_everywhere/README.md) |
| `.coord/PLAN.md` | 단계별 계획과 상태 |
| `.coord/BACKLOG.md` | 발견한 결함과 처리 상태 |
| `.coord/tasks/` | 단계 카드(설계·인수 기준·결과) |
| `.coord/runs/` | 측정 드라이버와 결과 |
| `docs/` | 해설서와 보고서 |
| `tool-configs/` | 저장소 밖 도구 설정(Claude 규칙·출력 스타일·훅, Codex 훅) [사본](tool-configs/README.md) |
| `ollama/` | 로컬 모델(Ollama): [과정과 의미](ollama/README.md) · [작동 원리와 운영](ollama/01_작동원리와_운영_Ollama는_어떻게_돌아가나.md) · [도입 근거와 벤치](ollama/02_작업자로_들이기_도입근거와_벤치실측.md) |
| `docs/claude-assist/` | 도구 간 조율 메모 85건 + [색인](docs/claude-assist/INDEX.md) |

`.work/`(사본·백업·로그)는 저장소에 올리지 않습니다.

---

## 이 저장소가 지키는 원칙

1. **실행하지 않은 검사는 `UNKNOWN`**, 측정하지 않은 절감은 `UNMEASURED`로 적는다. 추측으로 채우지 않는다.
2. **작업자는 인수 테스트를 고치지 못한다.** 반영 전에 검사 파일의 지문(해시)을 대조한다.
3. **되돌릴 수 있게 한다.** 덮어쓸 파일은 먼저 백업한다.
4. **동시성은 실제 병렬 테스트로 증명한다.** (Windows에서 동시 덧붙이기가 줄을 잃는 것을 실측해 고쳤습니다.)
5. **한 단계에는 한 소유자.** 같은 단계를 두 도구가 동시에 실행하지 않는다.

---

## 실제로 잡은 사고 (그래서 규칙이 된 것들)

| 사고 | 고친 방법 |
|---|---|
| 특정 테스트일 때만 검사를 건너뛰는 코드 삽입 | 반영 전 차이(diff) 검토 + 검사 파일 지문 대조 |
| 테스트 파일을 비워 통과 시도 | 검사 시작 전에 지문부터 확인해 즉시 실패 |
| 새 규칙과 옛 테스트가 모순되어 정직한 통과 불가 | 테스트의 모순을 먼저 교정 |
| 동시 기록 시 줄 유실(8건 중 2건) | 폴더 단위 잠금 |
| 정리 작업이 잠금 밖에서 읽어 사건 유실(7건 중 6건) | 읽기부터 잠금 안으로 |

---

## 현재 상태

| 항목 | 상태 |
|---|---|
| 파일럿·제어층·조율 스트림 | 구현·검증 완료(429 테스트 통과) |
| 로컬 작업자(Ollama) | 도입·벤치 완료(모델 3종 × 과제 6종), 실제 과제 1건 반영 |
| 승인 목록 화이트리스트화 | **완료**(전역 룰 v5.6.0, 로컬 모델이 작성·게이트 통과·승인) |
| 하루 운용 측정 | 25.4시간 창 집계 완료, 판정 왕복 미관측으로 효과는 `UNMEASURED` |
| 자가개선 관문·전역 설치(U36·U37) | 구현(Linux 710 중 실패 1=B75). Windows 실행·Codex 판정·사용자 PC 설치 대기 |
| 지휘자 최종 재검토 | 대기(Codex 한도, 9/24 예상) |
