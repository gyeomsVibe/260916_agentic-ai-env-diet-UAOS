# U185 MIA 전략절차 기반: 올라마 퍼스트 & 안티그래비티 기본 도구 영구 고정 아키텍처 설계

> **목적**: 사용자의 지적에 의존하는 사후 땜질을 영구 종식하고, Codex와 Claude Code가 착수 시점에 0토큰 로컬 모델(Ollama)과 독립 실행/감사자(Antigravity)를 강제 경유하도록 결정론적 하드 게이트(Pre-Tool Interceptor & State Machine)로 시스템 레벨에서 영구 고정한다.

---

## Stage 0. 사전 근거자료조사 (Deep Evidence Research)
- **공식 1차 출처 (Primary Sources)**:
  1. **Anthropic Claude Code Hooks**: `https://docs.anthropic.com/en/docs/claude-code/hooks`  
     - `PreToolUse` 훅은 도구 실행 전 동기 차단 가능.
     - 훅 프로세스가 **exit code 2**를 반환하면 도구 실행이 원천 거부(Block)되고, `stderr` 에러 메시지가 모델 컨텍스트로 주입되어 경로 전환 강제.
  2. **OpenAI Codex CLI Lifecycle Hooks**: `https://learn.chatgpt.com/docs/hooks` (`.codex/hooks.json`)  
     - `PreToolUse` 이벤트 매처(`Bash`, `Edit`, `Write`)를 통해 도구 실행 전 임의 스크립트 실행 및 차단 가능.
  3. **Python Enum & State Machine Pattern**: `https://docs.python.org/3/library/enum.html`  
     - 원자적 전이 상태 머신을 통하지 않은 임의 단계 건너뛰기 방지.
- **실측 결함 영수증 (Failure Receipts)**:
  1. `v7_harness/card_pipeline.py`: 감사가 작업 종료 후 커밋 시점(`card audit`)에만 동작하는 사후 검사(Late Audit) 구조.
  2. 프롬프트/가이드라인에만 "올라마 퍼스트"를 명시하고, 실행 인터셉터가 없어 유료 모델이 자체 도구(`Edit`, `Bash`)로 즉각 직행.
  3. `card skip --reason TASK_CLASS` 및 양수 토큰 기록만으로 통과되는 허위 통과(False Green) 관문 결함.

---

## Stage 1. 기획 (Frame)
- **Problem Statement**: Codex와 Claude가 로컬 계산기(Ollama)와 독립 감사(Antigravity)를 자율 호출하지 않고 유료 컨텍스트에서 직접 수정하는 UAOS 라우팅 강제력 부재.
- **정량적 성공 지표 (Success Signal)**:
  1. 신규 카드 착수 시 유료 모델의 첫 파일 쓰기/실행 도구 호출 시점에 `PreToolUse` 훅이 동작하여, Ollama 사전 추출 영수증이 없으면 **exit code 2로 강제 차단(BLOCK)**.
  2. 독립 감사/리뷰 슬롯에 Antigravity 실행 영수증(`review_agy.json` 및 서명)이 없으면 `coord merge` 및 PR 단계 원천 봉쇄.
  3. 사용자가 "올라마 써라"라고 지적할 필요가 없는 0-reminder 자율 경로 100% 보장.
- **비목표 (Non-Goals)**:
  - 10줄 미만의 단순 텍스트 조회/결정론적 grep까지 모델을 강제 호출하는 불필요한 오버헤드 유발 금지.
  - 안전 경계(Human-only safety list) 완화 금지.

---

## Stage 2. 기획 검증 (Frame Verification Gate)
- **판정**: **PASS**
- **근거**: 정량 지표(exit 2 차단 및 영수증 기반 허용)가 결정론적이며, 비목표가 명확하여 스코프 팽창 위험 없음.

---

## Stage 3. 큰계획 (Master Plan & 4-Lens Review)
- **대안 비교**:
  1. **대안 A: 프롬프트 및 전역 규칙 강화 (Prose-only)**  
     - Value: 하, Feasibility: 상, Viability: 하, Risk: 모델 망각으로 동일 실패 반복 발생. **[탈락]**
  2. **대안 B: 사후 커밋/머지 감사 강화 (Late Audit Enforcement)**  
     - Value: 중, Feasibility: 상, Viability: 중, Risk: 이미 수만 유료 토큰 소진 후 실패 발견. **[탈락]**
  3. **대안 C: PreToolUse 런타임 하드 인터셉터 + 공유 상태 머신 (Hard Interceptor State Machine)**  
     - Value: 극상, Feasibility: 상, Viability: 상, Risk: 초기 훅 설정 오류 시 일시적 도구 블록(롤백 스크립트로 해소 가능). **[채택]**

---

## Stage 4. 아키텍처 검증 (Architecture Verification Gate)
- **판정**: **GO**
- **근거**: Anthropic 및 Codex 공식 훅 규격(exit 2 차단)과 100% 호환되며, 토큰 소모 전 원천 차단으로 예산 누수 방지.

---

## Stage 5. 세부계획 (Detailed Plan & Contracts)
1. **코어 상태 머신 전이 규칙 (`RoutePlan`)**:
   - `REGISTERED` -> `LOCAL_PREP` (Ollama 필수) -> `LOCAL_CHECKED` -> `EXECUTED` (Ollama/Agy) -> `AGY_CHECKED` (Antigravity 필수) -> `INDEPENDENT_ACCEPTED`
2. **PreToolUse 훅 인터셉터 (`v7_harness/hooks/pre_tool_guard.py`)**:
   - 도구 매처: `Edit`, `Write`, `Bash` (코드/파일 수정 행위 일체)
   - 검증 로직: 현재 활성 카드의 `LOCAL_PREP` 영수증(Ollama) 존재 여부 검사. 부재 시:
     ```
     stderr: [UAOS_ROUTING_VIOLATION] Ollama 사전 작업 영수증이 없습니다. 
     먼저 Ollama(local_draft/local_read_map)로 준비를 수행하십시오.
     exit 2
     ```
3. **Antigravity 독립 감사 관문 (`v7_harness/card_pipeline.py`)**:
   - `AGY_CHECKED` 영수증 검증 시 타 도구의 대리 작성/자기 승인 불인정, 유효한 agy 세션 영수증 필수.

---

## Stage 6. 계약 검증 (Contract Lint & Gate)
- **판정**: **PASS**
- **근거**: `pilot manual lint` 및 `U185-contracts.json` 스키마와 완전 일치.

---

## Stage 7. 구현계획 (Execution Plan & Task Slicing)
- **슬라이싱 (20줄 이하 원칙)**:
  - Step 1: `.claude/settings.json` 및 `.codex/hooks.json`에 `PreToolUse` 인터셉터 등록.
  - Step 2: `v7_harness/hooks/pre_tool_guard.py` 결정론적 검증기 구현.
  - Step 3: `card_pipeline.py` 내 가짜 skip 및 미검증 통과 로직 엄격화.
- **라우팅**: Ollama(기본 템플릿 생성) -> Antigravity(정밀 코드 감사) -> Codex/Claude(인수 테스트 통과 후 병합).

---

## Stage 8. 사전 실행 검증 (Pre-Execution Gate)
- **백업 및 잠금**: `.work/backup_20261011_u185/` 생성 및 `.work/QUIET_LOCK` 획득 후 안전 적용.

---

## Stage 9. 구현 및 증거 확보 (Execution)
- 훅 스크립트 배포 및 가상 호출 시뮬레이션(exit 2 차단 증거 확보).

---

## Stage 10. 디버깅 및 최종검증 (Final Verification & Vaccine Test)
- **백신 테스트**: Ollama를 호출하지 않고 파일 쓰기를 시도할 때 exit 2로 즉각 차단되는지 역검증.
- 차단 성공 영수증 확인 후 도구 자율 병합 수행.
