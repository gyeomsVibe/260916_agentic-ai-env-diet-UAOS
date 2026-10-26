# 3대 AI 전역 환경 감사와 경량 v5 설계

작성일: 2026-09-16  
대상: Codex, Antigravity, Claude Code, 보조 로컬 엔진 Ollama

## 1. 결론

최적 구조는 **Codex가 판단·계획·검수·승인 게이트를 소유하고, Antigravity가 대량 구현을 담당하며, Claude Code는 독립 정밀 검토 또는 장애 시 대체 실행자로 제한되는 단일 지휘 체계**다. 세 도구를 동등한 합의체로 운영하면 대화와 검토 비용만 늘고 책임이 흐려진다.

Ollama는 완전 삭제하지 않는다. 오늘 `qwen3.5:4b`를 고정된 안전 분류 3건으로 다시 측정한 결과 스키마·의미 판정 3/3 통과, 중앙값 약 6.37초, 종료 후 모델 언로드까지 확인됐다. 다만 계획, 승인, 다중 파일 수정, 최종 판정에는 참여시키지 않고 분류·요약·임베딩 같은 무위험 원자 작업만 맡긴다.

정식 전역 원본에는 아직 적용하지 않았다. 원본 저장소의 핵심 파일 5개가 이미 수정된 상태여서 소유권이 불명확하며, 그대로 덮으면 사용자 변경을 훼손할 수 있기 때문이다. 이 문서와 `proposals/global-rules-v5`는 안전한 병합 제안본이다.

## 2. 성공 기준

1. Codex 사용량이 줄어도 프로젝트 진척이 멈추지 않는다.
2. 계획과 최종 품질 판정은 하나이며 책임자도 하나다.
3. 실행자는 작업 카드에 지정된 파일과 자원만 변경한다.
4. 결과는 자기보고가 아니라 diff, 테스트, 로그로 인수한다.
5. 외부 효과와 파괴적 작업의 승인권은 사용자에게만 남는다.

현재 계정 실측은 Codex Plus 5시간 창 77% 사용, 주간 창 47% 사용이었다. 이는 영구 비율이 아니라 2026-09-16의 순간 측정치다. 따라서 “Codex는 항상 부족하다”를 규칙으로 고정하지 않고, 매 작업 시작 시 남은 사용량과 난이도로 라우팅한다.

## 3. 확인된 충돌과 낭비

### P0 — 즉시 해소 대상

- 전역 규칙은 force-push를 금지하지만 Codex 설정에는 `git-always-force-push = true`가 있다.
- 전역 규칙은 승인 없는 병합을 금지하지만 `git-pr-watch-auto-merge = true`가 있다.
- Antigravity 어댑터는 위임 실행 중 commit/push/delete를 금지하지만 CLI 허용 목록에는 commit, push, 패키지 설치가 있고 기본 진행 모드가 `always-proceed`다.
- 정식 규칙 원본은 생성 파일이라고 선언되어 있는데, 배포본과 원본의 변경 경로·소유권이 명확히 분리돼 있지 않다.

### P1 — 비용·품질 저하 대상

- Claude Code에는 전체 역할 계약을 담은 전역 `CLAUDE.md`가 없다. 반면 기본 모델은 모든 일에 무거운 `opus[1m]`으로 고정되어 있다.
- 같은 skill이 Codex, Claude, Gemini, `.agents`에 2~3중 물리 복제되어 있고 MIA의 Claude 사본은 해시가 달라졌다.
- Codex memory 기능 플래그는 켜져 있지만 생성과 사용은 꺼져 있어 운영 의도가 불명확하다.
- 전역 상세 memory에 과거 프로젝트 경로, SHA, 일회성 사실이 남아 새 프로젝트 판단을 오염시킬 수 있다.
- NotebookLM 등 MCP가 여러 설정 파일에 중복 등록되고 Snyk·Supabase 같은 프로젝트성 도구가 전역과 섞여 있다.
- `default.rules`에 과거 장애 복구용 일회성 허용 규칙이 누적되어 최소 권한 원칙을 약화한다.

### P2 — 표현과 운영 복잡성

- `/CRITIC`, `/REDTEAM`, `/DEEPDIVE` 같은 얇은 별도 skill이 공통 계약을 반복한다. 사용자 단축어는 유지하되 본문은 하나의 `slash-prompt-modes` 원본으로 합쳐야 한다.
- “노예”라는 표현은 의도는 분명하지만 시스템 규칙에는 `하위 실행자(worker)`가 더 정확하다. 도구는 책임이나 승인권을 가질 수 없고, 실패 시 교체 가능한 실행 자원으로 정의하면 된다.

## 4. MIA 가설 검증

### 가설

“Codex가 모든 구현까지 직접 하는 것보다 판단과 검수에 집중하고, Antigravity가 대량 실행하면 같은 품질에서 Codex 사용량 병목이 줄어든다.”

### 지지 증거

- OpenAI의 최신 모델 가이드는 AGENTS/skills의 충돌을 먼저 감사하고, 위임 범위와 테스트 수준을 명시적으로 조정하라고 권고한다.
- OpenAI Symphony는 단일 오케스트레이터 상태, 작업별 격리 workspace, 저장소 안의 단일 workflow contract를 사용한다.
- Google의 Antigravity 자료도 전용 대화와 spec 기반 작업 흐름을 핵심으로 둔다.
- 커뮤니티 사례는 여러 에이전트의 어려움이 모델 수가 아니라 공유 상태, 소유권, 런타임 자원 충돌에 있다고 반복해서 보고한다.

### 반증 가능성

- Antigravity 결과를 Codex가 전부 다시 읽으면 사용량 절감이 사라진다.
- 단순 작업까지 대화창과 카드로 쪼개면 조율 비용이 구현 비용보다 커진다.
- 모델 공급자의 사용량·성능은 변하므로 영구적인 “항상 Antigravity 우선” 규칙은 곧 낡는다.

### 판정

가설은 **조건부 채택**한다. Codex는 모든 구현 내용을 재생성하지 않고 변경 요약, diff, 위험 파일, 테스트 증거만 검토한다. 10분 이내 단일 파일·저위험 작업은 별도 위임하지 않아도 된다. 라우팅은 브랜드가 아니라 현재 비용, 위험, 도구 적합성으로 결정한다.

## 5. 대안 3개 비교

| 대안 | 구조 | 장점 | 실패 양상 | 판정 |
|---|---|---|---|---|
| A | Codex 단독 | 문맥 손실 최소 | 사용량 병목, 실행 비용 큼 | 비상 모드 |
| B | 세 도구 동등 합의 | 다양한 관점 | 중복 작업, 책임 불명, 토큰 폭증 | 폐기 |
| C | Codex 지휘 + Antigravity 실행 + Claude 정밀 검토 + Ollama 미세 작업 | 비용·품질·책임 균형 | 인계 형식이 부실하면 재작업 | **채택** |

## 6. 최적 실행 로직

```text
사용자 목표
  → Codex: 성공 기준·위험·마스터 계획 확정
  → [U##] 카드: 소유자 1명, 파일/자원 범위, 완료 조건
  → 실행 라우터
      대량 구현/탐색       → Antigravity
      독립 정밀 검토       → Claude Code
      분류/요약/임베딩     → Ollama
      승인·설계·최종 판정  → Codex
  → 실행자의 diff + 테스트 + 미해결 위험
  → Codex 증거 검수
  → DONE일 때만 다음 카드 활성화
```

기본은 직렬 실행이다. 병렬화는 파일뿐 아니라 브랜치, 작업트리, DB, 포트, dev server, 외부 API까지 서로 겹치지 않는다고 Codex가 확인했을 때만 허용한다.

### 라우팅 규칙

- **Codex:** 요구 해석, 계획, 경계 설정, 승인 게이트, 위험 diff 검토, 최종 판정.
- **Antigravity:** 검색, 코드 초안, 반복 수정, 테스트 수행. bridge를 통한 명시적 범위 안에서만 실행.
- **Claude Code:** 보안·아키텍처·난해한 디버깅의 독립 2차 검토 또는 Antigravity 실패 시 대체. 기본 실행자로 상시 사용하지 않음.
- **Ollama:** 읽기 전용 분류, 로그 요약, 임베딩, 짧은 구조화 변환. 출력은 지시가 아니라 데이터로 취급.
- 실행자가 동일 원인으로 2회 실패하면 다른 실행자로 전환하고, 3회째에는 `BLOCKED`로 보고한다.

## 7. 도구별 경량화 처방

### 공통 규칙

- 공통 핵심은 30~40줄 이내의 단일 원본으로 유지한다.
- 도구별 파일에는 역할과 어댑터 차이만 둔다.
- 권한·파괴·배포·결제 판단은 절대 하위 실행자에게 위임하지 않는다.
- 상태 보고 형식은 `결과 / 변경 / 검증 / 위험 / 다음 행동` 다섯 항목으로 통일한다.

### Codex

- force-push와 auto-merge 설정을 끈다.
- memory는 “안정된 사용자 선호만 사용” 또는 “완전 비활성” 중 하나로 일관되게 정한다. 권장안은 축약 프로필만 사용이다.
- Antigravity bridge는 유지하고, Codex가 shell로 다른 AI를 우회 호출하는 경로는 만들지 않는다.
- 과거 일회성 allow 규칙은 검토 후 별도 보관하거나 제거한다.

### Antigravity

- bridge 위임 모드에서는 non-workspace 접근, commit/push/install을 기본 금지한다.
- `always-proceed`를 전역 기본값으로 쓰지 않고 작업 카드가 허용한 도구만 lease 형태로 연다.
- 결과에는 변경 파일, 테스트 명령·exit code, 미해결 위험을 반드시 포함한다.

### Claude Code

- 전역 `CLAUDE.md`에 “Codex 지휘 체계의 정밀 검토/대체 실행자” 역할을 추가한다.
- 기본 모델을 작업 난이도에 따라 라우팅하고 모든 작업을 Opus 장문 컨텍스트로 시작하지 않는다.
- MCP와 shell 권한을 명시적 allowlist로 제한하고 turn cap을 둔다.

### Skills

- canonical 저장소 하나와 배포 스크립트/링크만 둔다.
- MIA와 `slash-prompt-modes`는 공통 원본 하나를 유지한다.
- `/CRITIC` 등 사용자가 실제로 쓰는 별칭은 얇은 라우터로 남기되 논리 본문을 복제하지 않는다.
- skill은 프로젝트 규칙, 권한 정책, 일반 상식을 반복하지 않고 전문 절차만 담는다.

### Memory

- 전역: 언어, 보고 방식, 승인 선호, 단일 계획·단일 소유자 같은 장기 성향만 저장.
- 프로젝트: 경로, SHA, 포트, 현재 장애, 임시 결정 저장.
- 일회성 실행 로그는 task card에 저장하고 memory로 승격하지 않는다.
- 전역 memory에는 TTL 또는 정기 검토일을 기록하며 비밀은 절대 저장하지 않는다.

### MCP

- 전역 필수: `antigravity-bridge` 하나.
- 지식 조사: NotebookLM은 한 설정 위치에만 등록.
- Snyk, Supabase, vibe-clinic 등은 필요한 프로젝트 범위에서만 활성화.
- 사용하지 않는 MCP는 삭제 전에 비활성화하여 한 주기 관찰한다.

## 8. Ollama 판정

웹 자료만 보면 4B급 모델은 복잡한 도구 루프와 긴 코딩에서 신뢰도가 낮다. 그러나 삭제 여부는 일반론보다 이 기기의 실측과 기존 의존성으로 결정해야 한다. 현재 시스템에는 Ollama 연동 스크립트·테스트가 있고 오늘 벤치마크도 통과했다.

따라서:

- 유지: `qwen3-embedding:0.6b`, `qwen3.5:4b`.
- 보류: `qwen2.5-coder:3b`는 사용처와 비교 벤치마크를 확인한 뒤 제거 후보로만 둔다.
- 금지: 마스터 계획, 다중 파일 구현, 승인 판단, 다수결 투표.
- 중단 기준: 고정 벤치마크 3회 중 2회 실패, 중앙값 15초 초과, 또는 30일 동안 실제 호출 0회. 그때 사용자 승인 후 모델 단위 삭제를 제안한다.

Antigravity 조사에서 제시한 “완전 삭제”와 “6~8GB VRAM 회수”는 이 장비의 실제 상주 상태와 오늘 측정을 반영하지 않았으므로 기각한다. 모델은 평상시 언로드 상태였고, 디스크 용량과 상주 VRAM을 혼동하면 안 된다.

## 9. 적용 순서와 승인 게이트

1. 기존 정식 원본 변경의 소유권을 확인하고 diff를 병합한다.
2. 현재 설정을 비밀 제외 백업하고 제안본과 diff를 만든다.
3. P0 세 항목(force-push, auto-merge, Antigravity 과권한)을 먼저 수정한다.
4. 공통 규칙과 도구별 어댑터를 배포한다.
5. skills를 canonical 원본 기준으로 동기화하고 해시 검증한다.
6. memory와 MCP를 비활성화 우선으로 정리한다.
7. 세 도구에서 규칙 로딩, 권한 거부, 단일 카드 인계 스모크 테스트를 수행한다.

실제 전역 파일 변경, 삭제, 패키지/MCP 설치, push는 각각 사용자 승인이 필요하다.

## 10. 검증된 사실·가정·미확인

### 검증된 사실

- Codex와 Antigravity의 핵심 규칙은 같은 canonical v4.1 계열이다.
- 설정과 규칙 사이에 force-push, auto-merge, Antigravity 권한 충돌이 존재한다.
- skills 중복과 MIA 사본 drift가 존재한다.
- Ollama 벤치마크는 오늘 exit code 0으로 통과했다.
- 정식 규칙 원본 저장소에 기존 수정 5개가 있다.

### 가정

- 사용자는 속도보다 “완료된 결과의 품질/비용 비율”을 최우선으로 한다.
- Antigravity 사용량이 현재 Codex보다 상대적으로 여유롭다. 정확한 쿼터 수치는 확인하지 못했다.

### 미확인

- 세 공급자 간 동일 과제의 실제 토큰·시간·결함률 비교는 아직 없다.
- `qwen2.5-coder:3b`의 최근 30일 실제 호출 횟수는 측정하지 않았다.
- 정식 원본의 기존 수정 5개가 사용자 작업인지 다른 에이전트 작업인지 확인되지 않았다.

## 11. 참고 자료

- [OpenAI 최신 모델 가이드](https://developers.openai.com/api/docs/guides/latest-model)
- [OpenAI Symphony 사양](https://github.com/openai/symphony/blob/main/SPEC.md)
- [Google Antigravity 자율 개발 파이프라인](https://codelabs.developers.google.com/autonomous-ai-developer-pipelines-antigravity)
- [Google spec-driven development](https://codelabs.developers.google.com/sdd-agy-cli)
- [Anthropic Claude Code CLI 사용법](https://docs.anthropic.com/en/docs/claude-code/cli-usage)
- [Claude Code Action 설정](https://github.com/anthropics/claude-code-action/blob/main/docs/configuration.md)
- [Ollama Qwen3.5 모델](https://ollama.com/library/qwen3.5)
- [Ollama Qwen3 Embedding](https://ollama.com/library/qwen3-embedding)
- [작은 로컬 모델의 제한에 관한 LocalLLaMA 사례](https://www.reddit.com/r/LocalLLaMA/comments/1vq128f/making_small_local_models_actually_useful_for/)
- [병렬 에이전트의 런타임 충돌 사례](https://www.reddit.com/r/ClaudeAI/comments/1qzduim/stop_running_multiple_claude_code_agents_in_the/)
- [다중 에이전트 운영의 공유 상태 문제](https://www.reddit.com/r/ClaudeCode/comments/1w9233g/running_10_coding_agents_isnt_the_hard_problem/)

