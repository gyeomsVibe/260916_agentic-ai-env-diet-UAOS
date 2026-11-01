# [정본] 사용자의 추상적 아이디어, 직관적 비유 및 핵심 철학 정의서
(User's Abstract Ideas, Metaphorical Concepts, and Core Philosophy)

- 문서 상태: 정본(Maintained Canonical) v1.0.0
- 제정 목적: 기술적인 코드 diff와 테스트 스펙 뒤에 반드시 보존되어야 할 **사용자의 직관적 구상 프로세스, 핵심 비유, 철학적 정의**를 정제하여 깃 커밋(Git Commit)과 프로젝트 원장에 영구 각인함.
- 상위 규약: `AGENTS.md`, `docs/01_unified-agent-orchestration-design.md`, `docs/27`, `docs/31`
- 대상 독자: 코덱스(Codex, 지휘자), 클로드 코드(Claude Code, 부지휘자), 안티그래비티(Antigravity, 독립검증자)

---

## 1. 제정 배경: 기술 구현보다 앞서는 '사용자의 의도(Intent)'

코드는 언제든 리팩터링되거나 재작성될 수 있지만, **"왜 이 시스템이 이렇게 설계되었는가?"**를 규정하는 사용자의 직관과 비유는 한 글자도 유실되어서는 안 된다.
최근 U23~U27 구현 과정에서 방대한 코드와 테스트가 추가되었으나, 커밋 메시지와 산출물에서 사용자가 직접 창안한 **'전자계산기', '유선 전화기', '음성사서함', '교환원', '비둘기 메신저 퇴출'**이라는 본질적 비유와 추상적 정의가 탈락할 위험이 발견되었다.
이에 코덱스가 깃 저장소에 커밋 및 푸시를 수행할 때 반드시 반영해야 할 핵심 철학을 정제하여 선언한다.

---

## 2. 사용자가 비유한 5대 핵심 개념과 공학적 정의

### 1) 전자계산기 (The Electronic Calculator) — 0원 단순 연산 일꾼
- **사용자의 직관**: 사람이 복잡한 암산을 머리로 끙끙 앓으며 직접 계산하지 않고 전자계산기를 두드리듯, 유료 프론티어 AI(지휘자)는 코드를 손수 타이핑하며 비싼 토큰을 태우지 않고 0원짜리 로컬 올라마(Ollama) 계산기에게 지시문과 검증 인수만 넘겨 0원에 계산(수정)시킨다.
- **철학적 정의**: 올라마는 스스로 생각하거나 계획을 세울 수 없으며, 전략적 가치 판단이나 설계 능력이 0인 '순수 계산기'이자 '3대 도구의 토큰절약도구'다.
- **공학적 구현**:
  - `pilot run --worker local` 및 `olla ask -f <파일>`
  - 지휘자는 구체성 80점 이상의 세밀한 작업명령서(`docs/24`, `docs/32`)와 숨은 인수 테스트만 작성하고 구현 코드는 손으로 쓰지 않음.
  - 커밋 관문(`calculator_gate.py`)을 통해 파일럿을 거치지 않은 임의 수정을 차단.

### 2) 유선 전화기 (The Landline Telephone) vs 위성전화 (Satellite Phone)
- **사용자의 직관**: 올라마는 평소 유휴 상태로 대기하다가 지휘자가 필요할 때 수화기를 들고 다이얼을 돌리면(CLI 명령어 호출) 즉시 연결되어 연산 결과를 반환하는 '통화료 0원의 유선 전화기'다.
- **철학적 정의**: 유료 LLM을 24시간 켜놓고 15분마다 cron으로 상태를 감시하게 하는 것은, 통화료가 초당 폭증하는 '비싼 위성전화를 켜놓고 방치하는 극도의 낭비'다.
- **공학적 구현**:
  - 유료 LLM의 주기적 상주 폴링(cron) 전면 영구 금지.
  - 필요할 때만 단발성으로 호출하는 On-Demand 유선 전화기 아키텍처 확립.

### 3) 음성사서함 (The Voicemail / Mailbox) — 100% 무손실 비동기 버스
- **사용자의 직관**: 지휘자(Codex)가 자리를 비웠거나(한도 초과/부재 중) 다른 작업에 몰두하고 있을 때, 안티그래비티와 올라마가 만든 모든 결과와 보고서는 100% 무손실 보존되는 '음성사서함'에 안전하게 녹음되어야 한다.
- **철학적 정의**: 대화창에 억지로 메시지를 밀어 넣어 에러를 내거나 큐를 오염시키지 않고, 물리 디스크 기반의 영구 사서함에 보관했다가 지휘자가 복귀했을 때 차례대로 꺼내 듣는 무손실 완충 장치.
- **공학적 구현**:
  - 디스크 기반 우편함(`.coord/mailbox/`, Maildir 구조: `tmp/` -> `inbox/` -> `claimed/` -> `ack/`).
  - Windows 파일시스템 동시성 결함(원자적 하드링크, 밑줄 ID 보존)을 완비하여 데이터 유실 0건 보장.

### 4) 24/7 상주 교환원 (The Switchboard Operator / Sentinel)
- **사용자의 직관**: 로컬 올라마 기반 상주 감시관(Sentinel)은 전화국에서 24시간 대기하는 '무료 상주 교환원'이다.
- **철학적 정의**: 평소에는 잠금 고착(60분 초과), 프로세스 충돌, 원장 미정리, 에러 분류를 0원에 묵묵히 처리하다가, 진짜 위급한 차단 결함(P1)이나 사용자 승인 대상이 발생했을 때만 지휘자의 침실 벨을 울려(Wake-on-P1 Ringing) 1회 선별 기상시킨다.
- **공학적 구현**:
  - `v7_harness/coord/sentinel.py`
  - 60줄 초압축 건강진단서(`.coord/codex_brief.md`)를 발행하여 지휘자의 인지 부하 최소화.

### 5) 비둘기 메신저 퇴출 및 오케스트라 지휘 모델 (Abolishing Pigeon Work)
- **사용자의 직관**: 사용자가 여러 AI 대화창 사이를 오가며 대화 내용을 복사해서 이리저리 전달하던 고통스러운 '비둘기 메신저 노릇'을 완전히 없앤다.
- **철학적 정의**: 하나의 오케스트라처럼 단일 지휘자(Codex)가 전체 악보(`.coord/PLAN.md`)를 소유하고, 부지휘자(Claude Code), 비서 겸 독립 검증자(Antigravity), 계산기 악기(Ollama)가 각자의 악보 범위에서만 연주하는 질서정연한 조율.
- **공학적 구현**:
  - U15 조율 스트림(`.coord/stream/`) 및 실시간 큐(`codex queue`).
  - 단일 소유권 불변식(`WIP=1`, 동시 수정 금지).

---

## 3. 사용자의 추상적 아이디어와 핵심 원칙

1. **토큰 다이어트 (Token Diet)**:
   - 단순한 비용 절감이 아닌, "지능의 수준에 맞는 비대칭적 적재적소 배치" 철학.
   - 비싼 프론티어 모델은 '고도의 판단과 설계, 인수 판정'에만 집중하고, 기계적이고 반복적인 코딩 노동은 '비용 0원의 로컬 모델'에 전담시켜 계정 한도를 극대화함.

2. **계산기 원칙 (Calculator Principle)**:
   - "지휘자는 코드를 손으로 직접 쓰지 않는다."
   - 사람이 복잡한 수식을 계산기로 풀듯, 지휘자는 명세와 숨은 인수만 정의하고 코드는 도구에게 맡김.

3. **증거 관문형 자가개선 (Evidence-Gated RSI)**:
   - AI가 자기 자신을 스스로 칭찬하며 멋대로 코드를 고치는 '자가당착(Reward Hacking)'을 원천 차단.
   - 객관적이고 결정론적인 인수 테스트(Acceptance Gate)와 실사용 영수증 장부(`.coord/usage/runs.jsonl`)를 통과한 증거만이 채택됨.

4. **의도 보존 (Intent Ledger)**:
   - 모든 기술 구현의 최상위 권위는 사용자의 원문 발언과 구상 프로세스에 있음.
   - 문서나 커밋에서 기술적 스펙보다 사용자의 기획 의도와 직관적 비유가 먼저 서술되어야 함.

---

## 4. 코덱스(Codex) 깃 커밋 및 푸시 필수 반영 지침

코덱스는 본 프로젝트의 변경 사항을 깃(Git)에 커밋하고 푸시할 때, 아래 템플릿 요소를 커밋 메시지 본문에 반드시 포함해야 한다.

```text
feat(uaos): integrate user-defined core philosophy, metaphors, and orchestration architecture

[User Core Philosophy & Metaphors]
1. Calculator Principle: Commanders (Codex, Claude) do not write code by hand;
   local Ollama operates as a cost-free electronic calculator executing rote edits.
2. Landline Telephone Model: Ollama stands by as an on-demand 0-won telephone;
   24/7 paid LLM polling (satellite phone) is permanently abolished.
3. Voicemail (Disk Mailbox): Atomic disk spooling (.coord/mailbox/) preserves
   100% of inter-agent messages losslessly during commander absence.
4. Switchboard Operator (Sentinel): 24/7 local Ollama sentinel monitors locks
   and triages errors at 0 cost, alerting commanders only on P1 blocks (Wake-on-P1).
5. Abolishing Pigeon Work: Single master plan (PLAN.md) and in-window queue
   eliminate manual copy-paste relaying between fragmented AI sessions.

[Technical Accomplishments]
- U23 Mailbox Foundation & Sentinel Collision Recovery (39/39 OK)
- U25 Token Budget Routing Policy & 3-Tool Manuals (docs/27~30)
- U26 Evidence-Gated RSI Framework (docs/31)
- U27 Usage Ledger Automation & 32k ctx olla pilot (579 OK regression)
- Fully aligned with user intent and single-writer isolation invariants.
```
