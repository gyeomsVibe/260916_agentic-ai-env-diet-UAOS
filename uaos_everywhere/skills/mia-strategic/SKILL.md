---
name: mia-strategic
description: MIA 전략절차 스킬 — 실측 근거 기반 11단계 표준 전략 실행 프레임워크 (MIA Strategic 11-Stage Framework). 사용자가 "MIA모드 발동", "MIA 전략스킬 발동", "MIA 전략절차 발동", "MIA 전략스킬 해줘", "MIA 전략절차 해줘", "$mia-strategic", 또는 기획·검증·큰계획·검증·세부계획·검증·구현계획·검증·구현·디버깅 및 선행 리서치 기반 전략적 검증을 요청할 때 활성화됩니다.
license: MIT
user-invocable: true
argument-hint: "MIA모드 발동: [사전리서치|기획|검증|큰계획|검증|세부계획|검증|구현계획|검증|구현|디버깅] <목표>"
---

# 🎯 'MIA 전략절차' 스킬 (MIA Strategic 11-Stage Framework)
> **풀네임**: 실측 근거 기반 11단계 표준 전략 실행 및 검증 스킬 (Strategic Evidence-backed 11-Stage Verification Skill)

## 개요
'MIA 전략절차' 스킬은 주관적 추측과 독백을 배제하고, **1차 출처 실측 증거(Observed Evidence)**와 **단계별 독립 검증 관문(Hard Gate)**을 통과하며 문제를 해결하는 최적화된 표준 전략 프레임워크입니다.
사용자 지시에 따라 기존 단계를 엄격한 **[0. 사전 근거자료조사(웹딥리서치)] -> [1. 기획] -> [2. 검증] -> [3. 큰계획] -> [4. 검증] -> [5. 세부계획] -> [6. 검증] -> [7. 구현계획] -> [8. 검증] -> [9. 구현] -> [10. 디버깅 및 최종검증]**의 11단계 절차로 체계화하여, 3대 AI 도구(Codex, Claude Code, Antigravity)가 단 하나의 절차도 누락하거나 축소하지 않고 자율 완결합니다.

사용자가 **"MIA모드 발동"**, **"MIA 전략스킬 발동"**, **"$mia-strategic"**, 또는 단계별 전략 실행을 요청할 때 활성화됩니다.

---

## 11단계 표준 실행 프로세스 (11-Stage Canonical Workflow)

| 단계 (Stage) | 핵심 활동 (Core Activities) | 필수 입력 및 산출물 (I/O) | 독립 검증 관문 (Hard Gate) |
|---|---|---|---|
| **0. 사전 근거자료조사<br>(웹 딥리서치)** | 공식 API 문서, GitHub 오픈소스 구현체, W3C/IETF/OS 기술 표준, 반례 사례 등 1차 출처 심층 웹 검색 | **In**: 사용자 요구/문제 증상<br>**Out**: `Evidence Research Memo`<br>(검색 쿼리, URL, 원문 인용, 팩트/가설/미지수) | **Gate 0: 1차 출처 증거 관문**<br>공식 문서·GitHub URL 1건 이상 및 실측 인용 없이는 1단계 진입 원천 차단 (생략 절대 금지) |
| **1. 기획<br>(Frame)** | 관찰 가능한 문제 정의, 이해관계자 분석, 정량적 성공 지표(Success Signal), 비목표(Non-goals) 정의 | **In**: Evidence Research Memo<br>**Out**: `Opportunity Brief`<br>(성공 신호, 비목표 목록) | **Gate 1: 스코프 경계 관문**<br>측정 불가능한 정성적 목표 배제, 비목표로 스코프 팽창 차단 |
| **2. 검증<br>(Mid-Check 1)** | 기획의 목표 구체성, 성공 신호의 검사 가능성, 비목표 타당성 독립 점검 | **In**: Opportunity Brief<br>**Out**: `Frame Verification Receipt`<br>(`Pass` / `Refine`) | **Gate 2: 기획 검증 게이트**<br>성공 신호가 결정론적으로 측정 가능하지 않으면 큰계획 진입 차단 |
| **3. 큰계획<br>(Master Plan)** | 2~3가지 실질 대안 도출 및 4대 렌즈(Value, Feasibility, Viability, Risk/Rollback) 다각 평가, 아키텍처 수립 | **In**: Frame Verification Receipt<br>**Out**: `Master Architecture Plan`<br>(4대 렌즈 비교표, 마일스톤) | **Gate 3: 대안 비교 관문**<br>단일 안 밀어붙이기 금지, 최소 2개 대안의 4대 렌즈 평가 필수 |
| **4. 검증<br>(Mid-Check 2)** | 큰계획의 실현 가능성, 종속성 충돌, 예산/토큰 한도, 롤백 경로 사전 검증 | **In**: Master Architecture Plan<br>**Out**: `Decision Gate Memo`<br>(`Go` / `Pivot` / `No-Go`) | **Gate 4: 아키텍처 게이트**<br>`Go` 판정 및 명시적 롤백 경로 확보 시에만 세부계획 진행 |
| **5. 세부계획<br>(Detailed Plan)** | 파일·함수 단위 구체적 수정 범위 명세 (`allow` 목록 제한), 고정 인수 테스트 바이트 핀닝 | **In**: Decision Gate Memo<br>**Out**: `Contract Manual & Spec`<br>(수정 파일 목록, 인수 명령어) | **Gate 5: 수정 범위 한정 관문**<br>허용 경로 외 무단 수정·삭제 원천 금지, 인수 테스트 고정 |
| **6. 검증<br>(Mid-Check 3)** | 세부계획의 범위 외 수정 금지 규약 및 계약 매뉴얼 lint 통과 여부 검증 | **In**: Contract Manual & Spec<br>**Out**: `Lint & Scope Verification Log` | **Gate 6: 계약 Lint 게이트**<br>`pilot manual lint` 통과 및 판정자/작업자 명시 확인 |
| **7. 구현계획<br>(Execution Plan)** | 작업자 최적 라우팅 (Ollama 0토큰 계산기 first -> Antigravity 감사 -> Claude/Codex apply/judge), 20줄 슬라이싱 | **In**: Contract Manual & Spec<br>**Out**: `Task Slicing & Route Plan`<br>(단계별 20줄 이하 패치 계획) | **Gate 7: 토큰 절약 라우팅 관문**<br>기계적 반복은 로컬 계산기 우선, 유료 모델 직접 반복 차단 |
| **8. 검증<br>(Mid-Check 4)** | 0토큰 사전 준비 완료 여부, 잠금(`QUIET_LOCK`) 유효성 확인, `.work/backup_<date>/` 생성 검증 | **In**: Task Slicing & Route Plan<br>**Out**: `Pre-Execution Check Receipt` | **Gate 8: 안전 실행 게이트**<br>원본 백업 디렉터리 생성 및 단일 소유자 잠금 확보 필수 |
| **9. 구현<br>(Execution)** | 최소 가역 증거 구현, 고정 인수 테스트 통과, 스테이징 및 번들 생성 | **In**: Pre-Execution Check Receipt<br>**Out**: `Pilot Run Bundle` (Staging/Diff) | **Gate 9: 고정 인수 관문**<br>독립 실행 테스트 exit 0, 빈 출력/미변경(NO_CHANGES) 거부 |
| **10. 디버깅 및 최종검증<br>(Final Verification)** | 독립 인수 관문 실행, 반례 주입 검증(Vaccine Test), 실측 증거 대조, 실패 시 디버깅 루프 수행, 도구 자율 병합 | **In**: Pilot Run Bundle & Evidence<br>**Out**: `Learning Report & Result`<br>(결과, 근거, 남은 일 요약) | **Gate 10: 최종 폐쇄 및 자율 병합 관문**<br>독립 판정자 최종 통과, 사람 병합 대기 제거 후 3대 도구 자율 병합, 동일 원인 2회 실패 시 경로 전환 |

---

## 단계별 상세 운용 수칙 (Detailed Operational Guidelines)

### 0. 사전 근거자료조사 (Deep Evidence Research)
- **절대 생략 불가 규칙**: 최근 3대 도구에서 선행 웹 리서치를 생략하고 바로 코드 편집으로 직행하는 결함이 목격되었음. 본 단계는 **필수 강제 관문**임.
- 블로그나 커뮤니티 주관적 의견을 배제하고, 공식 API 문서, GitHub 실제 동작 오픈소스, RFC/W3C/OS 기술 표준을 1차 출처로 웹 검색/문서 취득 수행.
- 수집된 자료에서 **'확인된 사실(Facts)'**, **'검증할 가설(Hypotheses)'**, **'미지수(Unknowns)'**를 명확히 분리하여 `Evidence Research Memo`에 기록.
- 토큰 절약을 위해 로컬 모델(Ollama) 및 결정론적 추출을 1차 요약/맵핑에 우선 활용.

### 1. 기획 (Frame the Opportunity)
- **Problem Statement**: 풀고자 하는 문제를 사용자가 관찰한 실제 오류/영수증 현상으로 정의.
- **Measurable Success Signal**: 정량적·결정론적으로 판정 가능한 신호 정의 (exit 0, 테스트 100% PASS, 0토큰 달성 등).
- **Non-Goals**: 이번 작업에서 의도적으로 배제할 범위를 선언하여 스코프 팽창 차단.

### 2. 검증 (Frame Verification Gate)
- 기획의 목표 명확성, 측정 지표의 결정론적 검사 가능성을 독립 점검하고 통과 시에만 큰계획 진입.

### 3. 큰계획 (Master Plan & Multi-Lens Review)
- 2~3가지 실질적 대안을 도출하고 4대 렌즈로 객관적 평가:
  - **Value (가치성)**: 사용자 문제 해결 및 토큰/생산성 효율 기여도.
  - **Feasibility (실현가능성)**: 현재 시스템, 도구, 제약조건 하에서 즉시 구현 가능한가?
  - **Viability (지속가능성)**: 유지보수 비용, 운영 안정성, 플랫폼 정책 적합성.
  - **Risk & Rollback (위험도 및 복구)**: 부작용 발생 시 즉시 복구 가능한 롤백 경로 확보.

### 4. 검증 (Architecture Verification Gate)
- 큰계획의 실현 가능성, 종속성 충돌, 예산/토큰 한도를 사전 점검하고 `Go`, `Pivot`, `No-Go` 확정.

### 5. 세부계획 (Detailed Plan & Contract Manual)
- 수정할 파일 경로를 `allowed` 목록으로 엄격히 제한하고 범위 외 수정 및 무단 삭제를 원천 금지.
- 고정 인수 테스트(Acceptance Test)의 SHA256 해시를 핀닝하여 작업자의 임의 완화 차단.

### 6. 검증 (Plan Verification Gate / Lint Check)
- 매뉴얼 lint 검사 통과 및 독립 판정자 지정 확인.

### 7. 구현계획 (Execution Plan & Task Slicing)
- 0토큰 로컬 계산기(Ollama) -> 정밀 감사(Antigravity) -> 적용(Claude/Codex)의 최적 라우팅 수립.
- 20줄 이하 원칙으로 패치 단위를 작게 슬라이싱.

### 8. 검증 (Pre-Execution Gate)
- 실행 전 `.work/backup_<date>/` 백업 디렉터리 생성 및 `.work/QUIET_LOCK` 원자적 획득 확인.

### 9. 구현 (Execution)
- 격리된 스테이징에서 최소 가역 증거 구현 수행.
- 고정 인수 테스트 통과 증거를 포함한 번들 생성.

### 10. 디버깅 및 최종검증 (Debugging, Final Verification & Autonomous Merge)
- 독립 인수 관문 실행 및 반례 주입 검증(Vaccine Test).
- 오류 발생 시 디버깅 루프 수행 (동일 원인 2회 실패 시 경로 전환).
- 실측 증거(diff, exit 0, 테스트 로그)를 보존하고, 통과된 PR은 사람 병합 대기 없이 3대 도구(조율자 Codex 또는 담당 도구)가 자율 병합 수행.

---

## 3대 AI 도구 티키타카(Tiki-Taka) 강제 협업 원칙
1. **역할 분담**:
   - **Codex**: 총괄 조율자 (Conductor) 및 독립 인수 판정자.
   - **Claude Code**: 부지휘자 및 심층 분석/구현 협력자.
   - **Antigravity**: 계약된 정밀 실행자 (Executor) 및 최우선 사용자 컨트롤 인터페이스.
2. **무승인 논스톱 연계 및 도구 자율 병합**: Safety 사람 전용 목록(데이터 삭제, 원격 푸시, 배포, 결제, 권한 변경) 외에는 사용자에게 묻지 않고 파일·사서함 기반으로 스스로 끝까지 완결. 특히 인수 테스트 통과 PR의 병합은 사용자의 수동 개입(사람 병합)을 제거하고 3대 도구가 자율 수행.
3. **전역 배포 및 강제**: 본 11단계 절차는 3대 도구의 전역 스킬 디렉터리 및 UAOS-RSI 운영체제 코어(`uaos_global_rule_block.md`, `card_pipeline.py`)에 동시 설치·배포되어 3대 도구 모두에 강제됨.
