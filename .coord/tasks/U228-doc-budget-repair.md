# U228 — 공유 프로젝트 지침의 문서 예산 회귀 복구 (유지)

0 Research: https://git-scm.com/docs/git-diff (worktree/index 분리) 및 https://docs.ollama.com/api/chat (측정값이 없으면 추정하지 않음). 실제 영수증: 공유 U95/U96 24검사 중 문서예산1FAIL,깨끗한8c23의 동일검사PASS.
1 Frame: 현황 보고만으로 이 고칠 수 있는 회귀까지 WAIT로 묶은 이전 판단을 보정한다. AGENTS16997바이트를 현재 전역14792바이트와 합쳐32KiB 안에2048바이트 여유를 확보한다. 현재 고정 상한15928. 실제 프롬프트 잘림/한도 절감은 주장하지 않는다.
2 Verification: 고정 U96-D 수치/원문 해시30af2e4b/기존 공유 변경을 핀했다. 기존 평가기 수정0,인덱스blob558dbc6e 보존.
3 Alternatives: 숫자 상향은 평가기 약화여서 거부; 공유 원본 전체 초기화는 미커밋 문서 변경 유실로 거부; 선택은 설명문8줄만 의미 보존 압축.
4 Go: Codex가 이번8줄 범위의 단일 조율자/판정자. 기존 작성자의 나머지 파일·링크 수정·인덱스는 보존. 롤백용 원문 .work/backup_20261020_U228/AGENTS.md.
5 Detailed: 허용AGENTS.md의21,23,29,34,35,38,45,61행. 최대8교체(합16diff줄). 커맨드/경로/링크/날짜 전부 보존,나머지행 동일. CLAUDE/GEMINI 및 고정 테스트의 원문 해시 불변.
6 Gate: .work/u228/accept_u228.py(판정자 소유) + 원래 test_u96d_agents_budget. baseline은 예상한 BUDGET 실패. 후보 요구조건과 의미를 Codex가 독립 대조한다.
7 Route: 제한된 Ollama는8줄 초안만,파일 수정/승인 없음. 검증된 정확 치환을20줄 이하 worker:apply로 파일럿 stage에서 실행한다. 읽기 전용 초안 매뉴얼 new/lint PASS. 유료 대체 호출 없음.
8 Preflight: 원문·인덱스·테스트·설치전역·두 도구 파일 해시 핀과 선백업 완료. 파일럿 직전 단일 QUIET_LOCK,실행 중 다른 조율 파일 쓰기 중지.
9 Execution: 후보 생성/범위·의미 대조 → apply매뉴얼lint → 파일럿DRY_RUN → 정확번들 원본 반영. 거부/차단이면 반영하지 않는다.
10 Verification: 고정 U96-D 및 U95/U96 24검사 재실행,실패로그/원본해시/인덱스 보존 증명. 이번 단계는 로컬 문서 복구이며 기존 혼합 소스를 자동 커밋/푸시하지 않는다. U225/U226/U223의 별도 감사 출처 관문은 유지한다.

Deliverables: maintained source AGENTS.md and result .coord/results/U228.md; disposable draft/stage/logs .work/u228. Source writes by apply worker only; conductor judges exact evidence. Stop: hash mismatch,changed protected files,semantic loss,over20diff lines,two same-cause draft failures,or BLOCKED/REJECTED promotion.

## Replan1 — actual mixed-EOL guard failure (evaluator unchanged)
U228-A1 returned FAILED/UNKNOWN/BLOCKED with MIXED_LINE_ENDINGS before writes. Raw input has77CRLF+1bareLF. Source hash30af2e4b unchanged; failed attempt preserved and reconciled ABANDONED. Initial reconcile command had unsupported --source and exited2; corrected command exited0, not hidden.
Smallest input repair: normalize only the single bare LF to CRLF, adding exactly one byte with all78 text lines unchanged, backed up first and hash-pinned. Do not change/bypass the adapter's mixed-EOL guard. This formatting operation changes no permission, authority or instruction. It is a bounded deterministic file-format repair, before the logical apply pilot.
Eight logical prose replacements remain the only content change (16diff lines); the one EOL-only adjustment is separately recorded, total at most18line effects. The original fixed evaluator/size threshold and accept_u228.py hash stay unchanged. The candidate uses uniform CRLF and removes one optional ASCII space to preserve the original15928byte target. No new semantic scope, no other files/index edits.
After the format receipt, issue fresh U228-A2 exact-input manual, rerun stage acceptance, inspect exact bundle and ordinary promotion; never retry U228-A1 or reuse its failed effect as PASS.

## Replan2 — isolated publication after local acceptance
Local promotion remains valid and its source/index unchanged. Clean main a7130d9 retains original document names, so copy no shared file wholesale. Project only the8approved prose replacements while mapping each inline path/link back to the clean source reference. New source baseline/candidate and publication checker are separately pinned in .work/u228/release-baseline.json; originalaccept_u228.py unchanged. Exact scopeAGENTS only/16diff lines,allcommands/links/dates retained,24unchangedchecks plus link existence. No further replan of this card; fail a route rather than weaken gates. Conductor may commit/publish after worker finishes; worker contract forbids network/commit.
