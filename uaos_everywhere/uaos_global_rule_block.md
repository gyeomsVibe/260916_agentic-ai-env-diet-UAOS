## UAOS — 모든 프로젝트에 공통인 협업 운영 체계(Unified Agent Operating System)

- 명령 `uaos` = `{uaos}`. UAOS 저장소의 `v7_harness`를 어느 폴더에서든 실행한다. 아래 `uaos …`는 이 명령으로 바꿔 읽는다.
- 프로젝트 안이나 그 상위 폴더에 `.coord/PLAN.md`가 있으면 UAOS 프로젝트다. 시작할 때 계획·소유자·`uaos coord inbox --project <루트>`를 확인하고, `uaos coord watch --project <루트> --target <자기 도구>`를 백그라운드로 켜 둔다(새 편지가 오면 끝나며 세션을 깨운다, 0토큰). 도구끼리는 `uaos coord deliver`로 보내고 사용자에게 전달·복사·승인을 부탁하지 않는다.
- UAOS 프로젝트가 아니고 둘 이상의 도구가 협업할 일이면 `uaos coord init --project <루트>`로 준비한다. 기존 파일은 덮어쓰지 않는다.
- 프로젝트 시작 전에 `.coord/PROJECT_MANUAL.md`, 모든 위임 전에 해시 고정 계약 매뉴얼을 발행·lint하고 그 내용 전체를 호출에 전달한다. 유료 작업자는 token/USD/time 상한을 따로 두며 초과 결과는 승인하지 않는다.
- 권한대행은 `Codex ACTIVE → Codex`, 아니면 `Claude ACTIVE → Claude`, 둘 다 LIMITED/ABSENT일 때만 `Antigravity ACTIVE → Antigravity`다. UNKNOWN은 대행 근거가 아니며 `uaos coord route`가 fail-closed 한다. 잔여율·리셋 창을 토큰으로 환산하지 않는다.
- Ollama는 계산기다. 요약·추출·정확한 치환만 하고 설계·승인·판정은 하지 않는다. 같은 원인으로 두 번 실패하면 경로를 바꾼다. 유료 모델로 기다림 폴링이나 예약 호출을 하지 않는다. 기다림은 우편함과 교환원(sentinel)이 맡는다.
- 건설적 자율 릴레이: 생존 확인·동일 상태·빈 출력은 `ACK_ONLY`로 조용히 기록한다. 실제 변화·실패 관문·P1·판정/승인 필요만 `ACTIONABLE_DELTA`이며, 중복·소유권 확인 뒤 가장 작은 `READY`를 고정 인수와 카드 기록까지 끝낸다.
- 요구·증거·설계·소유권 또는 `coord route`가 확인한 경로가 바뀌면(`UNKNOWN`은 변화 아님) 영향받은 가정·카드와 설계·고정 인수·계약 매뉴얼을 갱신한 뒤 실행·독립 비판·검증을 반복한다. 같은 카드는 최대 2회 재계획한 뒤 경로를 한 번 바꾸며 3배 비용 회귀는 실패다. 도구 검토·테스트·PR 준비·다음 카드는 내부 의존성이지 사용자 일이 아니지만, 이 분류는 사람 확인 목록을 바꾸지 않는다. 사용자에게 다시 시작이나 계속 명령을 요구하지 않는다.
- 매 턴 종료 관문에서 목표 완료와 내부 의존성 0, 미승인 사람 전용 경계, 또는 모든 안전 경로의 외부 차단과 영속 인계·유료 토큰 0 감시 준비 중 하나를 증명한다. 감시 만료를 기록하고 재가동하거나 sentinel/schedule에 인계한다. 독립 검토자를 쓸 수 없으면 UNKNOWN으로 남기고 자기 승인하지 않으며 다른 `READY`를 진행한다. 아니면 다음 안전 단계를 계속한다.
- 병합 링크는 실시간 PR이 `OPEN`이고 병합 가능함을 확인한 뒤만 사용자에게 표시하며, 대체·폐쇄되면 같은 보고에서 즉시 밝힌다.
- 자가개선(RSI)은 증거만 만든다: `uaos rsi report` → `uaos rsi propose` → 시험 실행 → `uaos rsi gate --candidate <파일>`(참고 증거) → 릴리스는 `uaos rsi prepare` → `uaos rsi ship`(fetch·commit·push·PR, 자동병합 금지, 모든 외부 단계 실패는 fail-closed). 채택은 PLAN 카드와 검토된 커밋으로만 한다. 같은 계정 안의 이름표는 인증이 아니므로 `rsi adopt`로 자동 채택하지 않는다(B83). 평가기(테스트·장부·관문 코드)는 개선 대상이 아니다.
- 유료 LLM으로 크론·폴링을 돌리지 않는다: 변경 감시는 `uaos rsi schedule`(Windows 예약, 프로젝트별 고유 작업 이름, 기본 드라이런)이 로컬에서 결정적으로 돈다. 변화가 없으면(`ACK_ONLY`) 조용하고, 내용 해시가 실제로 바뀐 경우(`ACTIONABLE_DELTA`)만 한 번 모아서 고정 관문 PR 루프(`rsi prepare`/`rsi ship`)로 들어간다. 보존(`uaos rsi retention`)은 항상 드라이런 매니페스트이고, 삭제는 이 계획과 별도의 최신 승인이 있어야 한다.
- 복귀 도구는 우편함·복귀 체크리스트·대행 diff와 인수를 재검토한 뒤에만 지휘를 재개한다.
- 멈추고 사용자에게 물을 것: 삭제, push·배포·게시, 결제, 계정·권한·시스템 설정 변경.
