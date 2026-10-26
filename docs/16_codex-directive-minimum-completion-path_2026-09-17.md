# Codex 지시문 — 최소 완성 경로 v10

> 이 문서 아래 코드 블록 전체를 Codex 조율자 새 대화창 `[M1] U14 P1 재작업`에 붙여 넣는다.

```text
[M1] 최소 완성 경로 전환 — U14 P1 재작업부터

역할: 너는 조율자 Codex다. 사용자 제안 전제(Codex 지휘·Antigravity 실행, SQLite 연결, 무승인 자율 실행, 결과·예산 우선)는 재검토하지 않는다.

1) 먼저 읽기(이것만)
- docs/14_minimum-completion-path-design_2026-09-17.md  ← 새 정본 순서. §2 완료 정의, §3 종료 규칙, §5 단계 설계
- .coord/PLAN.md, .coord/tasks/U14-adapters.md(V1·V2 검증 절)
- 사용량 한도 중 Claude·Antigravity가 대행한 기록: .coord/reviews/U13-claude-coordinator-gate.md, U13 카드 마지막 3개 절

2) 계획 전환(이 대화에서 1회)
- U13 대행 판정(Claude 구현 + Antigravity 독립 검증 + 사용자 승인)을 재확인만 한다. 새 결함 탐색으로 되돌리지 않는다.
- PLAN에 M1(=U14 P1 재작업), M2(실전 파일럿, 기존 U15+U16 통합), M3(적용, 기존 U17)를 반영하고, 기존 U15~U17 후보는 SUPERSEDED로 표시한다.
- .coord/BACKLOG.md를 만들고 docs/14 §7 항목과 U14 P2·P3 4건을 옮긴다.

3) 종료 규칙(반드시 지킴)
- 차단은 P1만: 정상 경로의 거짓 성공·범위 밖 쓰기·권한 우회·데이터 손실이 실제 재현될 때.
- P2·P3는 발견 즉시 BACKLOG에 한 줄 기록하고 진행한다.
- 단계당 독립 검증 최대 2회. 2차는 1차 P1 해결 여부만 본다.
- 재작업은 검증에 적힌 항목만. 새 기능 금지.

4) M1 할 일 (U14 P1 6건만)
 ① caller/callee/mode/intent/purpose: casefold 후 허용 enum 검사
 ② session_id·conversation_id·model: ^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$, 선행 '-' 거부
 ③ task_id·title: 제어 문자 \x00-\x1f\x7f 전부 거부(agy·codex 공통)
 ④ 타임아웃: casefold 후 time[d]?\s*out + partial
 ⑤ ConversationRegistry: 대화 ID 역방향 유일성
 ⑥ usage: 유한·음이 아닌 정수만(bool 제외), 아니면 VALIDATION
- 항목마다 회귀 테스트 추가. 실패 테스트를 먼저 고정하고 Antigravity에 초안 1회 위임, 채택은 실제 diff·테스트로만.
- 범위: v7_harness/adapters/**, tests/test_u14_adapters.py, U14 카드, PLAN.
- 검증: python -W error::ResourceWarning -m unittest tests.test_u14_adapters / discover -s tests -p "test_u1[0-4]*.py" / compileall. 개수·exit 기록.
- 독립 검증: Antigravity 1회, ①~⑥ 해결 여부만 판정(agy -p ... --output-format json --mode plan).
- PASS면 U14(M1) DONE, M2 카드를 READY로 만들고 멈춘다. M2는 열지 않는다.

5) 사용량 절약
- 코드·로그 전문을 읽지 말고 diff·테스트 결과·요약만 본다.
- 한도에 가까우면 즉시 카드에 재개 지점을 기록하고 멈춘다.

6) 보고(7줄 이내)
결과 / 변경 / 검증(명령→exit) / P1 ①~⑥ 상태 / 백로그 이관 수 / 사용량 / 다음: [M2] 실전 파일럿 진행할까요?
```

---

## 다음 대화창용 (M1 DONE 후)

```text
[M2] 실전 파일럿 — docs/14 §5 M2 그대로 수행

- M2-1 AgyProcessLauncher(실제 agy, Job Object, print_timeout+60s, runs/에 원문 저장, parse_agy_result 판정, conversation 고정)
- M2-2 python -m v7_harness.cli pilot run: run-once 잠금 → enqueue → staging → watch roots → engine.execute → assert_unchanged → patch bundle → dry-run → summary.json(7줄)
- M2-3 isolation_mode는 StagingWorkspace 객체에서만 파생(A1 해소)
- M2-4 apply_promotion 실제 구현: 충돌 0·범위 위반 0·삭제 없음·base manifest 재확인·--approve <bundle_id> 필수
- M2-5 샘플 프로젝트 D:\D_Workspace_NB\-agentic-ai-workspace\260916_pilot_sample\ 생성(사용자 승인 1회) → 과제 P01 "함수 1개 추가 + 테스트 통과"
  A: Codex 단독 / B: Codex가 pilot run 1회 + summary 판정
  기록 .coord/runs/P01/ab.json: Codex 5h% 전후·codex exec --json usage·턴 수 / agy usage / 벽시계 / 인수 테스트 exit / 재작업·개입 횟수
- 첫 --approve 반영은 사용자 승인 후.
- 게이트: B 인수 테스트 통과, 거짓 성공 0, 범위 밖 쓰기 0. 절감률은 실측값 그대로 보고.
- 종료 규칙(docs/14 §3) 동일 적용. M3는 열지 않는다.
보고(7줄): 결과 / A·B 비교표 핵심 3수치 / 검증 / 발견 P1 / 백로그 / 사용량 / 다음: [M3] 적용 진행할까요?
```

## 마지막 대화창용 (M2 DONE 후)

```text
[M3] 적용 — docs/14 §5 M3 그대로 수행 (전역 파일은 사용자 승인 후)

- 프로젝트 AGENTS.md, ~/.codex/AGENTS.md, ~/.gemini/GEMINI.md, mia-vaccine-test에 각 5줄 이내 추가·수정. 수정 전 백업·diff 제시.
- 게이트: 새 Codex 세션에서 "P02 과제 해줘" 한 줄로 pilot run이 자동 선택되는지 확인.
보고(7줄): 결과 / 변경 파일 / 신규 세션 확인 / 남은 백로그 / 다음 권고
```
