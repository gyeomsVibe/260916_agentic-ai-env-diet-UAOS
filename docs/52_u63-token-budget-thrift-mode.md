# U63 세 도구 맞춤 토큰예산 절약모드

`coord thrift`는 관찰한 잔여율을 토큰으로 환산하지 않고 `NORMAL`(20% 이상), `THRIFT`(7% 초과 20% 미만), `HANDOFF_READY`(7% 이하)만 결정한다. 20%와 7%는 대조 측정 전 `UNMEASURED` 정책값이다.

Codex는 `COMMANDER_RESERVE`로 계획 순서·판정·승인·인계에 예산을 보존한다. Claude Code는 `IMPLEMENTER_RESERVE`로 현재 원자적 수정과 고정 인수만 끝내고 새 리팩터링과 차가운 세션을 멈춘다. Antigravity는 `RESEARCH_RESERVE`로 광범위 검색·브라우저·스크린샷·장문 합성을 멈추고 현재 증거만 압축한다. 세 도구가 모두 불가하면 `LOCAL_LOCKDOWN`으로 유료 호출 없이 우편함과 결정적 검사만 유지한다.

동일 입력은 `ACK_ONLY`이며 패킷과 편지를 중복 생성하지 않는다. 절약모드는 presence를 `LIMITED`로 바꾸지 않으며 기존 권한 승계가 최종 권위다. 복귀 시 `RETURN_REVIEW` 한 건만 내고 Codex가 diff·고정 인수·장부·원격 상태를 재검토한다.
