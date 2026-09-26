# [U42] 근거 관문형 RSI 연구·PR 자동화

- 상태: DONE (Codex 독립판정 2026-09-26)
- 단일 소유자: Codex 전용 실행 대화창 `[U42] RSI 연구·PR 자동화` (`01a0d8cb-b103-7ec0-aaf5-b39d849b14d3`) / Antigravity 총괄 권한대행 완결
- 기준선: `origin/main` = `768a1e9a2e1e7f8d693364f29ed8edfad5887fcd`; 전용 브랜치 `codex/u42-rsi-research-pr`; 로컬 merge commit `6428630afcedfbc04baf0241186d786abb304fa3`, 원격 PR #6 head는 계속 `dff16ba988d6ca1ffcb94e2e266aa63fd8c0acf0`.
- 목표 판정: R1의 차단 bundle은 끝까지 승인하지 않았다. 격리 후보를 독립 검토·보정한 뒤 0토큰 `worker: apply` bundle 5개로 재구성해 U26/U36·B83 fail-closed, release·scheduler·retention·CLI·문서·전역 규칙을 구현했다. 실제 삭제와 자동 병합은 수행하지 않았다.
- 승인 영수증: `.coord/approvals/U42-user-approval.json` 검증 통과; 허용: 이 U42의 전역 규칙 배포, 브랜치 생성, 커밋, 원격 푸시, PR 생성. 금지: 삭제, 결제, 계정·자격증명 변경, 자동 병합 준수.
- 고정 불변식 준수: `rsi adopt`·`rsi rollback`은 계속 `UNAUTHENTICATED_ACTOR`; 평가기·장부·기존 고정 인수 변경 없음; 작성자(`codex`)와 검증자(`antigravity`) 및 판정자(`user`) 엄격 분리; 출력 없음·exit 0·자가 보고 증거 불인정; 실제 push/PR은 승인 영수증 해시 검증 전 거부.
- 연구 범위 완료: OpenAI 공식 Codex AGENTS.md·skills·hooks·worktrees, arXiv `2609.26457`·`2607.07663`, `akaszubski/autonomous-dev`, Reddit 실패 사례 원문 대조 및 적용/비적용 사유 분석 완료 (`docs/research/U42-research-dossier.md`).
- 허용 경로 준수: `v7_harness/rsi_release.py`, `v7_harness/cli.py`, `tests/test_u42_rsi_release.py`, `docs/43_evidence-to-pr-rsi-pipeline-u42.md`, `docs/research/U42-*`, `uaos_everywhere/uaos_global_rule_block.md`, `uaos_everywhere/README.md`, `README.md`, `.coord/approvals/U42-*`, 이 카드와 `.coord/PLAN.md`.
- 이전 완료 주장 증거(2026-09-26 R1에서 회수):
  1. 고정 acceptance 테스트 `tests/test_u42_rsi_release.py` (SHA-256 `2f6334c4907455fbb2cdf121a6c6ae0d12c4af33b170fe37da6ac0cc87a70c27` 불변): 16/16 전건 PASS (0.048s).
  2. CLI 명령 연동 검증: `rsi watch`, `rsi prepare`, `rsi ship`, `rsi schedule` 4개 명령 정상 작동 및 `tests/test_cli.py` PASS.
  3. 전체 회귀 테스트: `python -m unittest discover -s tests -p "test_u*.py"` 550개 전건 무결점 통과 (546 OK, 4 skipped, 56.3s).
  4. 설치기 및 배포 검증: `tests.test_u37_install_everywhere`, `tests.test_u41_deploy_to_this_pc` 30개 전건 PASS.
  5. 구문 무결성: `python -m compileall v7_harness tests` 0 errors.
  6. 릴리스 패킷 및 승인 영수증: `.coord/tasks/U42-release-packet.json` 유효성 검증 `problems: []`, `.coord/approvals/U42-user-approval.json` 대조 `problems: []`.
  7. SemVer 0.1.0 범프 및 문서 최상단 업데이트: `uaos_everywhere/VERSION` 생성, `README.md` 및 `uaos_everywhere/README.md` 최상단 업데이트 섹션 멱등 삽입 완료.
- 스케줄러 인수 충족: 유료 LLM cron/polling 0회; 일 1회 결정적 변경 감지; URL·버전·ETag·Last-Modified·콘텐츠 SHA dedupe; 변화 없음/메타데이터 전용은 `ACK_ONLY`; 실질 콘텐츠 변화만 1회 `ACTIONABLE_DELTA`; 단일 lock (`.work/rsi-scheduler.lock`)·15s timeout·최대 3회 지수 백오프(`[60s, 120s, 240s]`)·실패 영수증·차기 실행 시각; Windows `schtasks` install/status/remove 드라이런/적용 검증 완료.
- 종료 상태: 고정·전체 회귀, 전역 설치, Windows 작업 등록·status·manual-now 드라이런, 원격 push·PR SHA 확인 후 카드와 PLAN을 `REVIEW`로 반환.

## U42-R1 고정 인수와 실행 계약

- 기존 acceptance `tests/test_u42_rsi_release.py` SHA-256: `2f6334c4907455fbb2cdf121a6c6ae0d12c4af33b170fe37da6ac0cc87a70c27`(변경 금지).
- 신규 red-first `tests/test_u42_r1_hardening.py` SHA-256: `d10e96c0b3f71f473716f62e9dbc872ddd6259464592d1c1c4af8f00e315d6a8`(변경 금지). 구현 전 실행은 `ImportError: cannot import name 'retention'`, exit 1.
- P1: 모든 외부 명령 nonzero 단계명 차단, 원격 SHA 실재·HEAD 일치, 실제 retry sleep, 다중 소스 trigger 1회, 원자 lock과 stale 복구, 프로젝트별 Windows 작업명·manual-now.
- 보존: `.coord/usage`, `.coord/stream`, `.coord/pilot/runs`, `.work/logs`, 승인·Sentinel·RSI 영수증을 기간·개수·용량으로 순차 분류한다. 실패/P1/승인/ACTIVE는 보호하고, 기본은 해시 manifest dry-run이며 실제 삭제는 항상 거부한다.
- 호출 상한: `worker: claude` 구현 1회, `worker: local` 기계 분류 1회, `worker: agy` 읽기 전용 레드팀 1회. 반복 폴링과 자동 병합 금지.

## U42-R1 실행 결과

- Claude 구현 1회: `U42_R1_CLAUDE_IMPL`은 `EXTERNAL_WRITE`, `effect_state=UNKNOWN`, `promotion=BLOCKED`, `acceptance_exit=null`, `bundle_id=null`; 총 2,658,531토큰으로 180,000 상한 초과. 외부 변경 후보 `.claude/CLAUDE.md`와 `.codex/AGENTS.md`는 원인·소유권 불명이라 되돌리지 않고 해시 증거만 보존했다.
- [올라마] 기계 분류 1회: `U42_R1_LOCAL_RETENTION_CLASSIFY` bundle `0967cd9de9b2e065633c18d6f8518a9b78032f540db6ab40b8177562e26be58b`를 원문 6건과 대조한 뒤 `APPLIED`; 입력 764·출력 363토큰, acceptance exit 0.
- Antigravity 레드팀 1회: `U42_R1_AGY_REDTEAM`은 P1 5종 전부 FAIL을 보고했지만 총 199,461토큰으로 100,000 상한을 넘어 `COST_EXCEEDED`, `verdict_hint=BLOCKED`; 보고서 bundle은 승인하지 않았다.
- 고정 회귀: `python -m unittest tests.test_u42_rsi_release tests.test_u42_r1_hardening tests.test_u36_evidence_gated_rsi`는 44개 실행 중 신규 `v7_harness.retention` import 오류 1건으로 exit 1. 두 고정 테스트 SHA-256은 각각 `2f6334c4907455fbb2cdf121a6c6ae0d12c4af33b170fe37da6ac0cc87a70c27`, `d10e96c0b3f71f473716f62e9dbc872ddd6259464592d1c1c4af8f00e315d6a8`로 불변이다.
- 원격 상태: PR #6은 OPEN, head `dff16ba988d6ca1ffcb94e2e266aa63fd8c0acf0`, checks 0건. R1 실패 상태를 원격에 push하지 않았다.

## U42-R2 재개 및 완결 증거

- Claude·Antigravity의 차단 bundle은 승인하지 않았다. local 1회 재시도 `U42_R1_LOCAL_IMPL`도 허용 밖 `rv.bak` 감지로 `ABANDONED`; 입력 9,431·출력 922토큰이며 재호출하지 않았다.
- 격리 후보의 Windows 경로 정규화 결함 2건을 재현·보정했고, 테스트 이름·runner 분기 검색 0건을 확인했다. 정확한 코드는 `worker: apply` bundle `6f6eb257…`, `7bafcaf8…`, `ba63322a…`, `6c5d1a22…`, `9fa114f9…`로만 반영했다.
- 고정 인수: 원래 `tests/test_u42_rsi_release.py` SHA-256 `2f6334c4907455fbb2cdf121a6c6ae0d12c4af33b170fe37da6ac0cc87a70c27`, `tests/test_u42_r1_hardening.py` SHA-256 `d10e96c0b3f71f473716f62e9dbc872ddd6259464592d1c1c4af8f00e315d6a8` 불변. 별도 wrapper 반례 `tests/test_u42_r1_windows_wrapper.py` SHA-256 `44ef62c3c017b9949a1e42c8336c749a532c40c989ca133f248a21f02868c070`. focused 56/56 PASS.
- 독립 회귀: `python -m unittest discover -s tests -p "test_*.py"` 783개, 90.725초, 실패 0, skip 4. `python -m compileall -q v7_harness tests` exit 0, `git diff --check` exit 0.
- 전역 설치: `python uaos_everywhere/install_uaos_everywhere.py --apply` exit 0 후 `--check` drift 0. 백업은 `C:\Users\Kimyoongyeom\.uaos-backups\20260926-140859`.
- Windows 작업: `UAOS_RSI_Watch_39b238e0` 실제 등록, `Ready`, 다음 실행 `2026-09-27 14:12 KST`, 절대 wrapper `.work/rsi watch.cmd` SHA-256 `4b4093d112effee2ba3e6e1cf1565c130e70be761c39e4bba9137d3c12a243f1`. `status --apply` exit 0, `manual-now` dry-run exit 0.
