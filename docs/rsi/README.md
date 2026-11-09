# RSI 자가개선: 운영 절차와 실제 오류 기록

이 폴더는 사용자 제보와 실사용 실패를 RSI 개선 카드에 연결하는 유지 문서입니다. 기록만으로 수정·검증·배포가 완료된 것이 아닙니다.

## 먼저 읽을 곳

- [2026-10-09 독식항해/논스톱 운영 오류 상세 기록](20261009-nonstop-package-a-incident.md)
- [RSI 운영 정본](../31_evidence-gated-rsi-for-uaos.md): 관찰 → 가설 → 고정 인수 → 후보 → 독립 판정 → 승인된 적용
- [자가개선 맹점과 증거 관문](../38_rsi-self-improvement-blind-spots-and-evidence-gate.md)
- [증거에서 PR까지의 릴리스 파이프라인](../43_evidence-to-pr-rsi-pipeline-u42.md)

## 실제 작성·실행 장소

- `.coord/notes/`: 사건별 증거와 운영 감사. 이번 원장은 `UAOS_WAIT_WITH_ACTIONABLE_HANDOFF_20261009.md`, `UAOS_NONSTOP_PACKAGE_A_WORKFLOW_AUDIT_20261009.md`.
- `.coord/tasks/`: 고정 입력 해시·허용 파일·인수·중단 조건·판정자가 있는 수정 계약.
- `.coord/usage/runs.jsonl`: 호출·실패·비용·시간·인수 원장. `user_error_reports.jsonl`, `user_error_receipts.jsonl`은 사용자 제보와 다른 도구 수신 기록.
- `.coord/stream/`: coord log 실행·BLOCKED·판정 영수증.
- `.work/nonstop_fix_20261009/`: 이번 격리 수정·테스트·pilot·원본 백업. 유지해야 할 변경은 Git 추적/설치 manifest와 결합하고 scratch 결과를 runtime authority로 올리지 않음.
- `v7_harness/rsi.py`: report/propose/gate.
- `v7_harness/rsi_release.py`: watch/prepare/ship/schedule/retention.
- `v7_harness/runtime_install.py`, `uaos_everywhere/install_uaos_everywhere.py`: 검증된 런타임 설치·장착 확인. 전역 규칙 정본은 별도 `shared/global-rules` 소유이며 덮어쓰지 않음.

새 오류는 원문·재현 명령/종료코드·원본 해시·영향·미확인·고정 회귀·단일 작성자·독립 판정·설치본 증거를 기록합니다. 다른 도구의 PASS나 편지 발송만으로 FIXED를 선언하지 않습니다.
