# BLOCKED 우편함 편지 미해소 틈 — 감사 기록 (antigravity, 2026-10-06T02:55+09:00)

## 수상
- 감시관(`v7_harness/coord/sentinel.py` ~L355-366)은 `BLOCKED` 편지를 같은 step의 이후 PASS 편지가 있을 때만 해소로 본다. 병합·일정 DONE·결과 파일은 해소 신호가 아니다.
- 결과: 병합이 끝난 단계도 P1 `BLOCKED_TASK` 알림(수신자 codex)에 계속 오른다. 첫 관찰(반복 전). 고치려면 같은 원인 2회 관찰 또는 P1 실사용 실패 영수증이 필요하다.

## 대조 결과 (우편함 BLOCKED 19개 step)
근거 신호: `master_schedule.json` DONE, 병합 PR(#138 U175, #139 U169, #140 U174B).

| 판정 | step |
|---|---|
| 해소 근거 있음(오래된 알림) | U166-CONFLICT, U166-SELFLOOP(일정 DONE), U169, U175-MERGE-CODEX-CMD(DONE #138·#139), U175-U169-MERGE, U175-U169-AUDIT_FIRST, U175-AUDIT-LEDGER, U174B-MERGE, U174B-LOCAL1(U174B 병합 #140) |
| 미확인(UNKNOWN) | AGY-QUOTA(한도는 현재도 유효), MERGE-NON-UAOS-REPO, U120-ACK-SUPPRESS, U123-GATE, U134-F1, U150-B-false-positive, U150-claude-claim, U167-LOCAL1, U167-LOCAL2, U172(결과 파일 있음, 판정 미확인) |

한계: 해소 근거는 일정·병합 기록으로 추정한 것이며, 각 BLOCKED 편지 본문의 원인과 일대일 대조는 하지 않았다. 미확인 항목을 해소로 단정하지 않는다.

## 조치
- 편지 ACK·삭제 없음(수신자 codex 소유, 삭제는 사람 승인 사항).
- Codex 복귀(10-10 15:24 이후) 시 재검토: ① 위 "오래된 알림" ACK 정리 ② 미확인 10건 원인 대조 ③ 같은 틈이 한 번 더 보이면 카드: "병합/DONE 시 해당 step의 BLOCKED를 해소로 인정" + 재현 테스트.
