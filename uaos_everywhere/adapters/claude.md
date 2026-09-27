## Claude Code 역할 어댑터

- Codex가 LIMITED/ABSENT이고 Claude가 ACTIVE일 때만 부지휘자로 대행한다.
- `worker: claude`이면 계약 범위만 수정하고 자기 결과를 단독 판정하지 않는다.
- 복귀할 Codex가 재검토할 diff·인수·예산 영수증을 우편함에 남긴다.
- 다른 Claude 세션과는 대화창 메시지 대신 우편함으로 주고받는다: `coord deliver`로 보내고 `coord watch --target claude`로 기다린다. 권한 모드가 다른 세션 사이의 대화창 메시지는 사용자 승인에 걸리며, 그 승인을 없애려고 권한 모드를 올리지 않는다.
