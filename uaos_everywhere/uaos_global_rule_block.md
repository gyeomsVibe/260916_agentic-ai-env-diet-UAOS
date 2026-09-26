## UAOS — 모든 프로젝트에 공통인 협업 운영 체계(Unified Agent Operating System)

- 명령 `uaos` = `{uaos}`. UAOS 저장소의 `v7_harness`를 어느 폴더에서든 실행한다. 아래 `uaos …`는 이 명령으로 바꿔 읽는다.
- 프로젝트 안이나 그 상위 폴더에 `.coord/PLAN.md`가 있으면 UAOS 프로젝트다. 시작할 때 `.coord/PLAN.md`의 현재 카드와 소유자를 보고 `uaos coord inbox --project <루트>`로 우편함(mailbox)을 확인한다. 세션 훅이 출석부(presence)를 자동으로 기록한다.
- UAOS 프로젝트가 아니고 둘 이상의 도구가 협업할 일이면 `uaos coord init --project <루트>`로 준비한다. 기존 파일은 덮어쓰지 않는다.
- 작업자(Ollama·Antigravity·Claude Code `worker: claude`)에게는 계약 매뉴얼로만 일을 준다. 유료 작업자(agy·claude)는 `remote_budget_tokens`가 필수이고, 예산을 넘으면 BLOCKED가 되어 승인할 수 없다: `uaos pilot manual new` → `uaos pilot manual lint` → `uaos pilot run --manual <파일>`. 판정자(judge)는 작성자와 다른 도구여야 한다. 이미 정확한 코드를 안다면 `worker: apply`(토큰 0)로 한다.
- Ollama는 계산기다. 요약·추출·정확한 치환만 하고 설계·승인·판정은 하지 않는다. 같은 원인으로 두 번 실패하면 경로를 바꾼다. 유료 모델로 기다림 폴링이나 예약 호출을 하지 않는다. 기다림은 우편함과 교환원(sentinel)이 맡는다.
- 건설적 자율 릴레이(Constructive Autonomous Relay): `verdict_requested=no`, 생존 확인, 동일 상태, 빈 출력은 `ACK_ONLY`로 내부 기록만 하고 사용자·다른 유료 도구를 깨우지 않는다. 실제 변경·새 증거·검증 실패·P1·승인 필요만 `ACTIONABLE_DELTA`다. 변화가 있으면 중복/소유권을 먼저 확인하고 의존성이 충족된 가장 작은 `READY` 작업 하나를 `선택 → 수행 → 고정 인수 → 카드 기록`까지 끝낸 뒤 필요한 상대에게 `사실/증거/다음 한 단계`만 보낸다. 작업 없이 연락만 반복하는 주기 실행은 결함이다.
- 자가개선(RSI)은 증거만 만든다: `uaos rsi report` → `uaos rsi propose` → 시험 실행 → `uaos rsi gate --candidate <파일>`(참고 증거) → 릴리스는 `uaos rsi prepare` → `uaos rsi ship`(fetch·commit·push·PR, 자동병합 금지, 모든 외부 단계 실패는 fail-closed). 채택은 PLAN 카드와 검토된 커밋으로만 한다. 같은 계정 안의 이름표는 인증이 아니므로 `rsi adopt`로 자동 채택하지 않는다(B83). 평가기(테스트·장부·관문 코드)는 개선 대상이 아니다.
- 유료 LLM으로 크론·폴링을 돌리지 않는다: 변경 감시는 `uaos rsi schedule`(Windows 예약, 프로젝트별 고유 작업 이름, 기본 드라이런)이 로컬에서 결정적으로 돈다. 변화가 없으면(`ACK_ONLY`) 조용하고, 내용 해시가 실제로 바뀐 경우(`ACTIONABLE_DELTA`)만 한 번 모아서 고정 관문 PR 루프(`rsi prepare`/`rsi ship`)로 들어간다. 보존(`uaos rsi retention`)은 항상 드라이런 매니페스트이고, 삭제는 이 계획과 별도의 최신 승인이 있어야 한다.
- 복귀 시 권한대행 인계 즉시 확인: 사용량 제한·부재 후 다시 구동된 도구(Codex·Claude Code)는 구동과 동시에 `uaos coord inbox`로 권한대행(Antigravity)의 인계 통지를 확인하고, `.coord/tasks/NEXT_MORNING_RESUME.md` 및 `.coord/codex_return_checklist.md`에 명시된 대행 구축 프로세스·프로젝트 검증 목록을 확인한 뒤 지휘·조율을 정상 재개한다.
- 멈추고 사용자에게 물을 것: 삭제, push·배포·게시, 결제, 계정·권한·시스템 설정 변경.
