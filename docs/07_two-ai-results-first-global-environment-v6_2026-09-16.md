# 2대 AI 성과우선 전역환경 감사와 v6 설계

작성일: 2026-09-16  
대상: Codex, Antigravity  
제외: Claude Code  
보조 엔진 판정: Ollama 사용 중단 및 제거 후보

## 1. 결론

최적 구조는 **Codex가 목표 해석·설계·라우팅·검증·최종 판정을 소유하고, Antigravity가 조사·대량 실행·반복 수정·테스트를 수행하는 단일 지휘 체계**다.

두 도구를 동등한 합의체로 두지 않는다. Codex는 제한된 사용량을 구현 반복에 쓰지 않고, 결과를 좌우하는 판단과 위험 검수에 사용한다. Antigravity는 Codex가 필요하다고 판단할 때 사용자 추가 지시 없이 `antigravity-bridge`로 호출하는 하위 실행 워커다. 단, 사용량이 풍부하다는 이유만으로 호출하지 않는다. **예상 재작업 비용이 직접 수행보다 크면 Antigravity도 사용하지 않는다.**

Ollama는 현재 목표에서는 가치가 부족하다. 로컬·오프라인·기밀 처리라는 별도 목표가 없고, 설치된 3B/4B 모델은 복합 계획과 도구 사용에서 검증 비용을 추가한다. 현재 Codex·Antigravity 설정과 이 프로젝트에서 실제 Ollama 실행 경로도 찾지 못했다. 따라서 v6 라우팅에서는 즉시 제외하며, 모델·앱·백그라운드 서비스를 완전 제거하는 것은 별도의 파괴적 작업 승인 후 수행한다.

MIA 결정: `GO — 2-AI 구조`, `NO-GO — Claude`, `NO-GO — Ollama를 성과 경로에 사용`, `HOLD — 실제 전역 변경·삭제`

## 2. 현재 실측

### Codex

- Plus 계정의 5시간 창 사용량: 92%
- 주간 창 사용량: 49%
- 기본 모델: `gpt-5.6-sol`, reasoning `low`
- 전역 규칙과 실행 설정 사이에 force-push·auto-merge 충돌 존재
- 메모리 기능은 상위 플래그가 켜져 있으나 생성·사용은 꺼져 있어 의도가 불명확
- browser/chrome/computer-use/unified-computer-use가 중첩 활성화

이 수치는 2026-09-16의 순간값이며 영구적인 공급 비율이 아니다. 라우터는 고정 브랜드 우선순위가 아니라 매 작업의 위험·크기·현재 쿼터로 판단해야 한다.

### Antigravity

- bridge 상태 정상, 버전 1.2.4
- bridge 기본값은 `sandbox=true`, `autoApprove=false`
- CLI 설정은 `always-proceed`, non-workspace 허용, commit/push/install 허용
- IDE 전역 설정은 terminal sandbox 비활성, non-workspace 허용, remote control 활성
- 전역 MCP가 config·IDE·CLI에 분산되고 NotebookLM이 중복 등록
- 동일 슬래시 모드 래퍼 10개가 `slash-prompt-modes`와 논리를 중복
- 실제 위임 감사에서도 “파일 수정 금지” 지시와 달리 Antigravity 내부 brain 아티팩트를 생성했으므로, 자기보고가 아니라 외부 검증이 필요

### Ollama

- 장비: i7-9750H, RAM 약 32GB, GTX 1660 Ti
- 설치 모델: `qwen3-embedding:0.6b` 639MB, `qwen2.5-coder:3b` 1.9GB, `qwen3.5:4b` 3.4GB
- 앱과 서버 프로세스가 상주
- 현재 프로젝트·활성 전역 설정에서 Ollama 연결 경로 없음
- 짧은 실측 과정 후 모델 언로드 완료

## 3. P0 충돌

| 규칙 | 실제 설정 | 위험 | v6 판정 |
|---|---|---|---|
| force-push 금지 | `git-always-force-push=true` | 이력 손실 | `false`로 변경 |
| 자동 병합 금지 | `git-pr-watch-auto-merge=true` | 무검토 반영 | `false`로 변경 |
| Antigravity 위임 중 commit/push/install 금지 | CLI allowlist와 `always-proceed` | 외부·비가역 효과 | 기본 금지 |
| 최소 권한 | Antigravity non-workspace allow, sandbox off | 범위 확장 | workspace-only, sandbox on |
| 필요 시 로딩 | 다수 플러그인·MCP 전역 활성 | 도구 선택 혼선 | 프로젝트 범위화 |
| 메모리는 안정 선호만 | 과거 프로젝트 사실과 경로가 전역 요약에 존재 | stale context | 자동 메모리 완전 비활성 |
| 단일 도구 표면 | 브라우저/컴퓨터 제어 플러그인 중복 | 지침·권한 중첩 | unified 한 계열만 유지 |

## 4. 과한 지침과 중복

### 삭제 또는 비활성 후보

- `/ALT3`, `/CRITIC`, `/DEEPDIVE`, `/ELI10`, `/EXPERT`, `/OPTIMIZE`, `/REDTEAM`, `/SELFREFINE`, `/STEPBYSTEP`, `/STRUCTURED` 개별 래퍼 스킬
- GPT 챗봇 제작 전용 global workflows 3개: 일반 Agentic AI 실행에 상주할 이유가 없음
- 전역 NotebookLM 중복 등록
- Antigravity IDE의 전역 Snyk·Supabase: 필요한 프로젝트에서만 활성화
- `vibe-clinic`과 `vibe-diagnosis`의 중복 도구 표면
- Codex legacy browser/chrome/computer-use 중복 플러그인
- 자동 Codex memory와 과거 프로젝트 실행 사실
- Claude Code 관련 모든 역할·라우팅·스킬 배포 대상

### 유지

- 공통 안전 불변식
- `mia-strategic`
- `slash-prompt-modes` 단일 원본
- `systematic-debugging`
- `accidental-data-loss-prevention`
- 프로젝트 단위 전문 스킬은 필요할 때만 로딩
- Codex의 `antigravity-bridge`

### 통합

- Critic, Redteam, Selfrefine 등 사용자 제어 토큰은 `slash-prompt-modes` 하나로 통합
- 장기 사용자 선호는 10줄 안팎의 글로벌 규칙으로 승격하고 자동 memory는 끔
- vibe 자가진단은 독립 MCP가 아니라 실패가 확인된 뒤 호출하는 프로젝트 진단 스킬로 축소

## 5. 성과우선 라우팅

```text
사용자 목표
  → Codex: 성공 기준, 위험, 검증 oracle 결정
  → 직접 처리 비용과 위임 비용 비교
      작고 고위험 판단 중심        → Codex 직접
      조사·반복·대량 구현·테스트   → Antigravity 위임
      10분 미만 단일 저위험 수정   → 현재 활성 도구가 직접
      외부효과·삭제·배포·결제       → 사용자 승인 전 정지
  → Antigravity: 범위 내 실행 + 증거 반환
  → Codex: 위험 diff와 oracle만 검토
  → PASS면 DONE, 아니면 같은 창에서 1회 보완
  → 동일 원인 2회 실패 시 Codex 직접 또는 BLOCKED
```

### Codex 사용량별 보정

- 5시간 창 80% 이상 사용: Codex는 계획·경계·최종 검증만 수행
- 50~80%: 중형 이상 실행은 Antigravity, 작은 고위험 판단은 Codex
- 50% 미만: 10분 미만 저위험 작업은 Codex 직접 가능

퍼센트는 품질보다 우선하지 않는다. Antigravity가 결과를 반복해서 실패하면 쿼터가 많아도 중단한다.

### 위임 손익 계산

Antigravity를 호출하는 조건:

```text
예상 실행 절감 > 위임 준비 + 인계 읽기 + 재검증 + 실패 재작업
```

다음은 위임하지 않는다.

- 사용자 의도를 다시 물어야 하는 모호한 핵심 결정
- 보안·권한·데이터 삭제·배포 승인
- 한두 줄 수정인데 작업 카드 작성이 더 비싼 경우
- 결과를 Codex가 사실상 전부 다시 만들어야 하는 작업

## 6. 2-AI 계약

### Codex — conductor and brain

- 목표를 관찰 가능한 성공 기준으로 바꾼다.
- 하나의 계획과 `[U##]` 순서를 소유한다.
- 실행자, 파일·자원 범위, 검증 oracle을 결정한다.
- Antigravity는 `antigravity-bridge`로만 호출한다.
- 전체 구현을 재생성하지 않고 위험 diff와 검증 증거만 본다.
- 승인·배포·삭제·결제·최종 판정을 위임하지 않는다.

### Antigravity — primary worker

- Codex의 목표·허용 범위·완료 조건만 수행한다.
- 별도 마스터 계획을 만들거나 다음 단계를 시작하지 않는다.
- 위임 중 commit, push, merge, delete, install, 계정·권한 변경을 하지 않는다.
- 결과가 비거나 산출물이 없으면 실패다.
- `결과 / 변경 / 검증과 exit code / 위험 / 다음 행동`만 반환한다.
- 지시와 실제 환경이 충돌하면 추측 실행하지 않고 반환한다.

## 7. 글로벌 룰 구조

글로벌 공통 원본은 30줄 안팎으로 제한한다.

1. 한국어 결과 우선 보고
2. 비밀 비열람·비출력
3. 파괴·외부효과·비용·권한 변경 승인
4. 사용자 변경 보존과 `git status`
5. 관련 검증과 정확한 종료 코드
6. 사실·가정·미확인 분리
7. 비용 절감 주장은 비교 실측 전 `UNMEASURED`

Codex와 Antigravity 파일에는 공통 규칙을 복제하지 않고 역할 차이만 추가한다. 프로젝트의 조율·상태·작업 카드 규칙은 프로젝트 `AGENTS.md`가 소유한다.

## 8. Skills 다이어트

### 전역 활성 최소 세트

- `mia-strategic`: 전략 가설 검증
- `slash-prompt-modes`: 사용자 명시 모드 통합
- `systematic-debugging`: 실제 오류가 발생했을 때만
- `accidental-data-loss-prevention`: 삭제 직전

### 필요 시 로딩 라이브러리

- frontend, React, Python, 문서, 디자인 등 도메인 스킬
- `mia-skill-compiler`, `mia-vaccine-test`
- 제품 기획과 코드 리뷰 전문 스킬

전역 catalog에서 제거하더라도 파일을 즉시 삭제하지 않는다. 먼저 `skills-disabled` 보관소로 이동해 한 주기 관찰한 뒤 삭제한다.

## 9. Memory 다이어트

- Codex 자동 memory는 완전 비활성화해 플래그를 일치시킨다.
- 글로벌에 남길 정보는 언어, 결과 우선, 단일 계획, 승인 경계뿐이다.
- 프로젝트 경로, SHA, 포트, 현재 장애, 임시 결정은 프로젝트 카드에만 둔다.
- raw memory와 rollout summary는 실행 컨텍스트에서 제외한다.
- 비밀 패턴이 감지된 `MEMORY.md`는 내용 확인·이동·삭제 모두 별도 승인과 안전 절차가 필요하다.

## 10. MCP 다이어트

### Codex 전역

- 유지: `antigravity-bridge`
- 플랫폼 내부 의존: `node_repl`은 직접 제거하지 않음
- 프로젝트 범위화: NotebookLM

### Antigravity 전역

- 기본 MCP 없음
- NotebookLM, Snyk, Supabase, vibe-clinic은 필요한 프로젝트 카드가 있을 때만 켬
- 동일 서버를 config·IDE·CLI에 중복 등록하지 않음

## 11. Ollama 판정

공식 Ollama 모델 설명상 `qwen3.5:4b`는 3.4GB 모델이고 `qwen3-embedding:0.6b`는 임베딩 전용이다. 커뮤니티 사례는 작은 모델이 짧은 코딩·분류에는 유용할 수 있으나 아키텍처·계획·복합 도구 사용에서 한계가 크다고 보고한다.

현재 목표에서 불채택하는 이유:

- 무료 실행량은 Antigravity로 이미 확보됨
- 별도 라우터·프롬프트·검증 경로가 필요함
- 3B/4B 출력 검증에 Codex 사용량이 다시 소비됨
- 현재 활성 프로젝트에 임베딩/RAG 파이프라인이 없음
- 앱·서버 프로세스가 상주해 운영 복잡성을 늘림

결론: **성과 경로에서 즉시 제외하고 완전 제거 권고.** 단, 제거는 모델 데이터 약 5.9GB, 앱, 백그라운드 서버와 관련 설정을 삭제하는 파괴적 작업이므로 별도 최종 승인이 필요하다.

## 12. 적용 단계

1. `v6-two-ai` 제안본 검토
2. 현재 전역 설정의 비밀 제외 백업과 해시 기록
3. P0 설정 수정: force-push, auto-merge, Antigravity 과권한
4. 공통 글로벌 룰과 두 어댑터 배포
5. skills를 비활성 보관소로 이동하고 discovery 스모크 테스트
6. memory 완전 비활성 및 프로젝트 상태 분리
7. MCP 전역 중복 비활성화
8. 3개 작업으로 Codex 직접 대비 Antigravity 위임 A/B 측정
9. 기준 통과 후 비활성 항목 삭제
10. 별도 승인 후 Ollama 완전 제거

## 13. 검증 기준

- Antigravity 무범위 수정 0건
- 승인 없는 외부 효과 0건
- 증거 없는 `DONE` 0건
- 동일 작업 중복 수행 0건
- Codex 검토가 전체 구현 재생성 없이 끝남
- A/B 3건에서 위임 총시간 또는 Codex 사용량 중 하나가 개선되고 결함률이 악화되지 않음

절감률은 실험 전까지 `UNMEASURED`다.

## 14. 출처

- [OpenAI 모델 가이드](https://developers.openai.com/api/docs/guides/latest-model)
- [OpenAI Codex 사용 사례](https://developers.openai.com/codex/use-cases)
- [OpenAI Symphony](https://github.com/openai/symphony/blob/main/SPEC.md)
- [Google Antigravity 자율 개발 파이프라인](https://codelabs.developers.google.com/autonomous-ai-developer-pipelines-antigravity)
- [Ollama Qwen3.5](https://ollama.com/library/qwen3.5)
- [Ollama Qwen3 Embedding](https://ollama.com/library/qwen3-embedding)
- [Reddit: 4B 모델의 로컬 코딩 사용 경험](https://www.reddit.com/r/ollama/comments/1s2p13t/can_someone_recommend_a_model_to_run_locally/)
- [Reddit: 작은 로컬 모델의 계획·아키텍처 한계](https://www.reddit.com/r/LocalLLaMA/comments/1rzx47w/local_coding_agent_help/)

## 15. 사실·가정·미확인

### 확인된 사실

- Codex 사용량과 Antigravity bridge 상태를 당일 조회했다.
- 실제 전역 파일과 스킬 목록·해시·MCP 등록을 읽었다.
- P0 설정 충돌과 중복 스킬·MCP를 확인했다.
- 현재 프로젝트에는 Git 저장소가 없다.

### 가정

- Antigravity의 실제 사용 가능량이 Codex보다 충분하다. 정확한 쿼터 API는 확인하지 못했다.
- Claude Code 구독은 사용자가 해지하며 이후 라우팅에서 제외한다.

### 미확인

- 2-AI A/B 작업의 실제 결함률과 총 소요시간
- Antigravity의 정확한 잔여 사용량
- Ollama의 최근 30일 호출 횟수
- 생성 원본 저장소와 배포본 사이의 안전한 동기화 경로

