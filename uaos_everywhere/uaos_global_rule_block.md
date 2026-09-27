## UAOS — 모든 프로젝트에 공통인 협업 운영 체계(Unified Agent Operating System)

- 명령 `uaos` = `{uaos}`. UAOS 저장소의 `v7_harness`를 어느 폴더에서든 실행한다. 아래 `uaos …`는 이 명령으로 바꿔 읽는다.
- 프로젝트 안이나 그 상위 폴더에 `.coord/PLAN.md`가 있으면 UAOS 프로젝트다. 시작할 때 계획·소유자·`uaos coord inbox --project <루트>`를 확인하고, `uaos coord watch --project <루트> --target <자기 도구>`를 백그라운드로 켜 둔다(새 편지가 오면 끝나며 세션을 깨운다, 0토큰). 도구끼리는 `uaos coord deliver`로 보내고 사용자에게 전달·복사·승인을 부탁하지 않는다.
- UAOS 프로젝트가 아니고 둘 이상의 도구가 협업할 일이면 `uaos coord init --project <루트>`로 준비한다. 기존 파일은 덮어쓰지 않는다.
- 프로젝트 시작 전에 `.coord/PROJECT_MANUAL.md`, 모든 위임 전에 해시 고정 계약 매뉴얼을 발행·lint하고 그 내용 전체를 호출에 전달한다. 유료 작업자는 token/USD/time 상한을 따로 두며 초과 결과는 승인하지 않는다.
- 권한대행은 `Codex ACTIVE → Codex`, 아니면 `Claude ACTIVE → Claude`, 둘 다 LIMITED/ABSENT일 때만 `Antigravity ACTIVE → Antigravity`다. UNKNOWN은 대행 근거가 아니며 `uaos coord route`가 fail-closed 한다. 잔여율·리셋 창을 토큰으로 환산하지 않는다.
- Ollama는 계산기다. 요약·추출·정확한 치환만 하고 설계·승인·판정은 하지 않는다. 같은 원인으로 두 번 실패하면 경로를 바꾼다. 유료 모델로 기다림 폴링이나 예약 호출을 하지 않는다. 기다림은 우편함과 교환원(sentinel)이 맡는다.
- 건설적 자율 릴레이(Constructive Autonomous Relay): `verdict_requested=no`, 생존 확인, 동일 상태, 빈 출력은 `ACK_ONLY`로 내부 기록만 하고 사용자·다른 유료 도구를 깨우지 않는다. 실제 변경·새 증거·검증 실패·P1·승인 필요만 `ACTIONABLE_DELTA`다. 변화가 있으면 중복/소유권을 먼저 확인하고 의존성이 충족된 가장 작은 `READY` 작업 하나를 `선택 → 수행 → 고정 인수 → 카드 기록`까지 끝낸 뒤 필요한 상대에게 `사실/증거/다음 한 단계`만 보낸다. 작업 없이 연락만 반복하는 주기 실행은 결함이다.
- 자가개선(RSI)은 증거만 만든다: `uaos rsi report` → `uaos rsi propose` → 시험 실행 → `uaos rsi gate --candidate <파일>`(참고 증거) → 릴리스는 `uaos rsi prepare` → `uaos rsi ship`(fetch·commit·push·PR, 자동병합 금지, 모든 외부 단계 실패는 fail-closed). 채택은 PLAN 카드와 검토된 커밋으로만 한다. 같은 계정 안의 이름표는 인증이 아니므로 `rsi adopt`로 자동 채택하지 않는다(B83). 평가기(테스트·장부·관문 코드)는 개선 대상이 아니다.
- 유료 LLM으로 크론·폴링을 돌리지 않는다: 변경 감시는 `uaos rsi schedule`(Windows 예약, 프로젝트별 고유 작업 이름, 기본 드라이런)이 로컬에서 결정적으로 돈다. 변화가 없으면(`ACK_ONLY`) 조용하고, 내용 해시가 실제로 바뀐 경우(`ACTIONABLE_DELTA`)만 한 번 모아서 고정 관문 PR 루프(`rsi prepare`/`rsi ship`)로 들어간다. 보존(`uaos rsi retention`)은 항상 드라이런 매니페스트이고, 삭제는 이 계획과 별도의 최신 승인이 있어야 한다.
- 복귀 도구는 우편함·복귀 체크리스트·대행 diff와 인수를 재검토한 뒤에만 지휘를 재개한다.
- 멈추고 사용자에게 물을 것: 삭제, push·배포·게시, 결제, 계정·권한·시스템 설정 변경.
