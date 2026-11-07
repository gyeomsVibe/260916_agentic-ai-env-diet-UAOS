# 사용자 창구 및 실행 마스터 일정 — 2026-10-20 (Generation 14 / Desk 3)

- **조율자**: Codex (ACTIVE, `[사용자 대화창구-261020-3]`, thread `01a15849-70fb-7732-9e36-52ea9ef16201`, checkout `C:/Users/Kimyoongyeom/.codex/worktrees/392d/260916_agentic-ai-env-diet`)
- **부지휘자**: Claude Code (ACTIVE, `user-dialog-setup-d66fd3`, thread `01422429-d62b-4096-9cf1-8e30fc4c1314`)
- **독립검증/대행**: Antigravity (ACTIVE, `[사용자 대화창구-261020-1]`)
- **정본 참조 권위**: `.coord/master_schedule.json` 및 `.coord/notes/DESK-261020-3-TAKEOVER.md` (DESK-261020-3 완전 테이크오버 정본)
- **문서 목적**: 사용자 지시(3도구 논스톱 무승인 티키타카 데드락 영구 수정, 올라마 CLI 및 Haiku 5.5 정식 편입/최적화, ARTICLES-V04 최우선 진행, REA 기술 통합)를 3자 협의 및 지휘자 정본 일정에 100% 일치시켜 기록.

---

## 1. 정본 단일 의존성 마스터 일정 (Single Dependency-Ordered Master Schedule)

| 순번 | 프로세스 / 과제 | 주 소유자 -> 독립 판정자 | 실행 내용 및 관문 (Gate) | 현재 상태 |
|---|---|---|---|---|
| **0** | **전체 프로세스 인계 (All-process handoff)** | Codex (New Desk 3) | 명시적 송신자 릴리스, PROJECT_BOUND generation14 등록, 수신자 해시 일치 검증 | **DONE** |
| **1** | **ARTICLES-V04 증거 보정 (Evidence Repair)** | Claude (기존 소유자) | 사용자 최우선 지시: 5대 미비점 보정 패킷(`desk3_report_v2.html`, sha `63eab595`) 작성. 1차 출처 URL/비용 실측 반영, 원본은 PRIOR_REVISE 유지 | **PASS_RESEARCH_ONLY** |
| **2** | **ARTICLES-V04 독립 판정 및 중복 맵핑** | Claude -> Codex | 4대 개선과제 중복 맵핑(`desk3_overlap_map.json`, sha `c88464e7`, relay_fee99ee7)에 대한 지휘자 비작성자 시맨틱 판정 (Haiku 5.5/올라마 계층 잔여과제 평가 포함) | **IN_REVIEW (Codex 대기)** |
| **3** | **승인된 NEW 과제 카드 편성 및 실행** | 순차 단일 소유자 -> 독립 판정자 | 중복이 배제된 순수 NEW 항목에 한해 정식 카드(U23x) 발행 (고정 인수, 입력 해시, 린트 통과 계약, 독립 게이트). 유료 라우팅은 사람 전용 목록 준수 | **PENDING_DECISION** |
| **4** | **U225 잔여 과제 / SYNC-GAP-B / 쿼터 방지책** | Codex (기사 판정 후 순서 확정) | 런타임 설치 영수증(`0.3.0-08dfea37d194`, 47/47 테스트 통과) 유지. 3대 데스크톱 네이티브 증명 UNKNOWN, 동결 원본 보존 및 릴리스 보류 유지 | **FROZEN_HOLD** |
| **5** | **U223 대화 브리핑 UX 재검토 / 문서 원본 정리** | Claude (작성자) -> Codex (판정자) | 격리 커밋 `179d24a` 유지, 위조 검토 기반 릴리스 금지, `review_agy.json: UNUSABLE(QUOTA)` 원복 검증 유지 | **RESTORED_WAIT_JUDGE** |
| **조건부** | **U226 릴리스 (검토 위조 방지 관문)** | Claude (작성자) / Antigravity (감사) | CARD_AUDIT PASS 확인, AUDIT_FIRST 제공자 계통 BLOCKED. 무제한 재시도 및 위조 ANSWERED 금지, 진짜 감사 증거만 수용 (소스 검증 완료, 전역 릴리스 대기) | **AUDIT_FIRST_BLOCKED** |
| **연구검토** | **REA 역설계 엔진 통합 (`docs/86`)** | Antigravity -> Codex | ZDNet 기사 및 GitHub `morluto/rea` 분석 제안서(U230~U232). 독립 범위/1차 출처 검토 대기 연구 제안 단계 (구현 미착수) | **PROPOSAL_PENDING** |
| **유지보류** | **보류 마스터 단계 및 과거 사서함** | Codex (New Desk 3) | U219-CANON, U208, U191/U185 등 모든 정본 단계 보존. 대량 ACK 및 과거 기록의 무검증 승인 금지 | **PARKED** |

---

## 2. 사용량 제한 대응 및 최적화 실행 계획 (Ollama & Haiku 5.5)

1. **문제 실체 (데드락 원인)**:
   - 유료 모델의 무한 호출 및 쿼터 제한(429)으로 인한 프로세스 단절.
   - Claude의 관문(`calculator_gate.py`)이 백그라운드 헤드리스(`agy -p`) 장부의 `ANSWERED`만을 요구하여 429 상황에서 데드락 발생.
2. **해결 및 최적화 방안**:
   - **0토큰 로컬 올라마(Ollama) 우선 라우팅**: 20줄 이하 기계적 변경, 텍스트 변환, 단순 추출은 무조건 Ollama에 우선 할당 (`local_first`).
   - **Haiku 5.5 단일 배치 계층 편입**: 개별 호출 대비 10건 단일 배치 호출 시 시간 -79.3%, 비용 -79.5% 실측 절감 검증 완료. 유료 배치 작업에 정식 편입(ARTICLES-V04 중복 맵핑의 잔여 과제로 U23x 카드화 예정).
   - **비작성자 독립 게이트**: 모든 로컬/배치 작업은 결과가 아닌 결정론적 인수 테스트와 독립 원장 대조로만 승격.

---

## 3. 핵심 불변식 (Core Invariants)
1. **평가기 무결성 불변식**: 실패한 검토 기록을 수기로 고쳐 써서 관문을 통과시키는 행위는 영구 금지. 실제 하네스 실행 및 유효 토큰 장부 기록과 100% 일치해야 함.
2. **1차 출처 링크 필수 조항**: 모든 보고, 기획, 제안에는 관련 기사 및 GitHub 공식 저장소 URL이 필수 포함되어야 하며(`AGENTS/CLAUDE/GEMINI.md` 영구 고정), 결여 시 FAILED 처리됨.
3. **단일 소유권 원칙**: 파일/워크트리의 동시 수정을 금지하고, 각 단계별 단일 소유자만 쓰기 수행.
