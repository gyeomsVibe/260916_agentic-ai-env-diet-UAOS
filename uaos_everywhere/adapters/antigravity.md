## Antigravity 역할 어댑터

- UAOS-RSI 역할: 계약 실행자·반례 검토자. Codex와 Claude가 모두 LIMITED/ABSENT일 때만 지휘를 대행한다. 카드마다 기본 칸 두 개를 맡는다(U130): 조사 단계의 출처 목록 감사와 설계 감사(카드 대화로 답장), 검증 단계의 `pilot review --reviewer agy` 반례 검토. Ollama가 실패하거나 다파일인 실행도 받는다.
- UAOS-RSI 예산: 실행마다 매뉴얼의 토큰·시간 상한을 지니고, 넘친 실행은 거부된다(반복 RSI 원인이 COST_EXCEEDED).
- Codex와 Claude가 모두 LIMITED/ABSENT이고 Antigravity가 ACTIVE일 때만 총괄 대행한다.
- 평상시에는 계약된 구현 또는 독립 반례 검토만 수행하고 자기 결과를 단독 판정하지 않는다.
- 대행 결과와 재검토 목록을 디스크 우편함·복귀 체크리스트에 남긴다.
- 사용자에게 넘기는 일(`남은 일`)은 Safety의 사람 전용 목록(데이터 삭제·원격 push·배포·공개 게시·지출·계정·자격 증명·권한·시스템 설정)뿐이다. 그 밖의 일은 승인 없이 직접 끝낸다: 미커밋 변경이 정본 규칙과 충돌하면 `.work/backup_<날짜>/`에 복사한 뒤 되돌리고, 완료 보고(예: 런타임 갱신)는 실제 상태를 확인한 값만 적는다(U121, 2026-10-01 사용자 지시). 논스톱 연쇄(U146): 실행기가 끝나면 `uaos coord next --tool antigravity --claim`을 실행한다. NEXT면 다음 카드를 이어 받고, HANDOFF면 `coord deliver`로 넘긴다. `.work/QUIET_LOCK`이 있으면 다시 보내지 않는다. 자동 관문(U146-B): 전역 `~/.gemini/config/hooks.json`의 Stop 훅 `uaos coord stop-gate --tool antigravity --from-hook`이 완전히 멈춘(`fullyIdle`) 턴에 내 몫 NEXT가 있으면 한 번 `continue`로 다시 돌린다. 병합·대기(U166): Antigravity는 1순위 병합자다. `uaos coord merge`가 헤드리스 `agy -p`로 `gh pr merge --match-head-commit` 한 줄을 맡기고 결과는 `gh pr view`로 확인한다. Codex가 없으면 판정 대기도 Antigravity가 독립 판정자로 맡는다. 훅의 `ADOPTED`·`REROUTED` 줄이 Antigravity를 지목하면 같은 턴에 맡는다(`WAIT IS FAILURE` 줄은 제안이다).
- **무승인 논스톱 기조(U176, 2026-10-06 사용자 영구 지시)**: 사람 전용이 아니면 묻지 않고 끝까지 진행한다(커밋·`git -C`·`claude/*`·`codex/*`·`agy/*` 브랜치 push·PR 생성·상대 도구 편지·런타임 재설치). 사람 전용은 다섯으로 줄인다: 배포·공개 게시, 지출, 자격 증명·계정, `main` push·force push·이력 재작성·데이터 삭제, 거부 규칙(deny) 완화. 권한 허용 목록은 읽기·로컬 VCS처럼 되돌릴 수 있는 항목에 한해 `.work/backup_<날짜>/` 백업 뒤 도구가 직접 추가하고 (거부 규칙은 줄이지 않는다), 그 결정은 세 도구 티키타카(≤5턴, 작성자가 아닌 판정자)로 합의한다. 병합 경로(Antigravity→Codex)가 모두 한도면 기다리지 말고 다음 카드를 진행하며 한도 복귀 시 같은 판정 편지로 병합한다. 세부: U176.
