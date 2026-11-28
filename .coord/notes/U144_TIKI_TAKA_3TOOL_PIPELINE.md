# U144: 3대 도구 티키타카(Tiki-Taka) 고속 협업 프로토콜 및 6단계 MIA 전략 파이프라인
**문서 ID**: `U144-TIKI-TAKA-MIA`  
**작성일자**: 2026-10-03 (KST)  
**작성자**: Antigravity (MIA Strategic Architecture)  
**수신자**: Codex Conductor, Claude Code, 윤겸스  

---

## 1. 개요 및 웹 딥리서치 근거 (Foundations)
- **개념 정의**: "티키타카(Tiki-Taka)"는 축구의 짧고 빠른 패스 연계처럼, 3대 AI 도구(Antigravity, Codex, Claude Code)가 한쪽이 멈추거나 긴 대기 없이 **짧은 턴(Turn) 단위로 증거와 피드백을 실시간 핑퐁(Ping-Pong) 교환하는 고속 상호작용 프로토콜**을 의미한다.
- **연구 및 RFC 근거**:
  - A2A (Agent-to-Agent) 및 MCP 표준 프로토콜의 양방향 메시지 스트리밍 구조.
  - 무한 핑퐁 루프 방지: `max_ping_pong_turns = 5` 상한 및 결정론적 소유권(Deterministic Task Allocation) 부여.
  - 즉시 청각 통지: Windows OS 음향(`winsound`) 기반 0.01초 실시간 인지.

---

## 2. 6단계 세분화 MIA 전략절차 (Enhanced 6-Stage MIA Pipeline)

기존 4단계(Frame-Review-Execute-Verify)를 사용자 지시에 따라 6단계로 확장 구체화한다:

```
[0. 선행 딥리서치] ──> [1. 기획 (Frame)] ──> [2. 큰계획 (Master Plan)]
                                                    │
[5. 최종점검 (Final Check)] <── [4. 세부계획 (Detailed Plan)] <── [3. 중간점검 (Mid-Check)]
```

| 단계 | 주요 산출물 | 티키타카 역할 분담 | 판정 기준 |
|---|---|---|---|
| **0. 선행 딥리서치** | 기술 RFC, GitHub 구현체, 벤치마크 조사 | Antigravity 조사, Ollama 요약 | 1차 출처 2개 이상 확보 |
| **1. 기획 (Frame)** | PRD, Opportunity Brief, Non-goals | Antigravity 초안 ──> Codex 검토 | 가설 및 성공 지표 수립 |
| **2. 큰계획 (Master Plan)** | 전체 토폴로지, 도구별 역할 분담도 | Antigravity 제안 ──> Codex 승인 | 단일 소유권 및 불변식 준수 |
| **3. 중간점검 (Mid-Check)** | 토큰 예산 검수, 통신 신뢰성, RSI 장부 | 3도구 실측치 교차 검증 | 회귀 0건, 장부 누적 일치 |
| **4. 세부계획 (Detailed Plan)** | 계약 매뉴얼, 고정 인수 테스트 코드 | 작성자 계약 ──> 판정자 반례 검증 | `pilot manual lint` 통과 |
| **5. 최종점검 (Final Check)** | 전수 회귀 테스트, 최종 머지/배포 패킷 | 판정자(Codex) 독립 게이트 승인 | 100% PASS, 드리프트 0 |

---

## 3. 3대 도구 티키타카(Tiki-Taka) 릴레이 규칙

1. **단일 턴 핑퐁 상한 (`max_turns = 5`)**:
   - 질문-답변-반례-수정-최종승인이 최대 5턴 이내에 결론나도록 설계.
   - 동일 원인 2회 실패 시 경로 전환(Pivot).
2. **0원 통신 우선 원칙 (Thrift First)**:
   - 일상적 핑퐁 초안 작성은 로컬 Ollama(`local_draft`)를 호출하여 유료 API 토큰 0원 소모.
   - Codex와 Claude, Antigravity는 핵심 게이트 판정 및 최종 코드 검증에만 유료 턴 투입.
3. **수신 즉시 시스템 사운드 송출 (U143 연동)**:
   - `coord deliver` 수신 즉시 Windows `winsound.MessageBeep()` 호출로 사용자/작업자가 즉각 인지.
