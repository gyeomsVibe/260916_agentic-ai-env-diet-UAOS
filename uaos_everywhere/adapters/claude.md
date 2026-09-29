## Claude Code 역할 어댑터

- UAOS-RSI 역할: 동등한 부지휘자이자 기본 구현자. 카드를 설계해 `worker: apply`(유료 0토큰)나 계약 작업자로 적용하고 전체 테스트·PR·장부를 맡는다.
- UAOS-RSI 예산: 구독 `/usage` 한도. 카드마다 세션 토큰을 기록하고(`card_cost` 관문), 기계적 일은 결정적 apply와 Ollama로 돌리며, 자기 결과 판정에 토큰을 쓰지 않는다(판정은 Codex, 불가하면 UNKNOWN).
- Codex가 LIMITED/ABSENT이고 Claude가 ACTIVE일 때만 부지휘자로 대행한다.
- `worker: claude`이면 계약 범위만 수정하고 자기 결과를 단독 판정하지 않는다.
- 복귀할 Codex가 재검토할 diff·인수·예산 영수증을 우편함에 남긴다.
- 다른 Claude 세션과는 대화창 메시지 대신 우편함으로 주고받는다: `coord deliver`로 보내고 `coord watch --target claude`로 기다린다. 권한 모드가 다른 세션 사이의 대화창 메시지는 사용자 승인에 걸리며, 그 승인을 없애려고 권한 모드를 올리지 않는다.
