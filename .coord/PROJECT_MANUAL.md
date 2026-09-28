# UAOS 프로젝트 완성 매뉴얼

- work_id: U76
- 목표: Codex·Claude Code·Antigravity가 단일 계획과 증거 관문으로 끝까지 이어지고, 결정적 도구와 자격을 통과한 Ollama를 먼저 써서 유료 토큰을 줄이는 UAOS를 완성한다.
- 단일 원장: `.coord/PLAN.md`; 현재 단계는 U76 비용회귀 복구·도구별 절약정책·통제 대조 측정이다.
- 소유권: Codex가 ACTIVE이면 계획·순서·최종 판정을 소유한다. 단계별 작성자는 한 명이며 작성자는 자기 변경의 유일한 검증자가 될 수 없다.
- 상태기계: Codex ACTIVE → Codex, 아니면 Claude ACTIVE → Claude, 둘 다 LIMITED/ABSENT일 때만 Antigravity ACTIVE → Antigravity. UNKNOWN은 대행 근거가 아니다.
- 연속성: `coord watch`와 디스크 우편함이 대기를 맡는다. ACK_ONLY·동일 상태·빈 출력은 유료 모델을 깨우지 않고, ACTIONABLE_DELTA·P1·실패 관문·승인 경계만 깨운다.
- 토큰 예산: 잔여율을 토큰으로 환산하지 않는다. NORMAL/THRIFT/HANDOFF_READY/LOCAL_LOCKDOWN 상태와 도구별 보존 정책을 사용하고 실제 절감은 통제 비교 전 `UNMEASURED`다.
- 완료 관문: U72의 `3.14배 > 3배` 비용 실패를 숨기지 않는다. 같은 입력·인수·작업유형의 통제 대조 10쌍, P1 0, 품질 저하 0, 카드별 3배 회귀 0 전에는 절감 프로세스를 완료라 하지 않는다.
- Ollama: 결정적 추출보다 이득인 해시 고정 기계 작업만 수행한다. 설계·승인·판정은 금지하며 출력은 원문 대조와 고정 인수 전까지 격리한다. 로컬 토큰·벽시계·실패를 기록한다.
- 위임: 모든 Claude·Antigravity·Ollama 호출 전에 프로젝트 매뉴얼과 입력 SHA-256·허용 파일·금지 행동·token/USD/time 상한·인수·중단 조건이 든 계약 매뉴얼을 파일로 발행하고 lint한 뒤 내용 전체를 전달한다.
- 검증: diff, 고정 인수, 테스트 해시, 장부, 원격 SHA가 작업자 보고보다 우선한다. 미실행은 UNKNOWN이고 예산 초과·범위 밖 쓰기·빈 산출물은 승인하지 않는다.
- 승인 경계: `.coord/PLAN.md`와 작업 카드의 로컬 갱신은 무승인이다. 삭제, remote push, deploy/public posting, 결제, 계정·자격증명·권한·시스템 설정 변경은 각각의 최신 명시 승인 없이는 금지한다. 과거 U45 승인은 U67로 이전되지 않는다.
- 중단: 입력 해시 불일치, 중복 소유권, 같은 원인 2회 실패(Ollama) 또는 3회 실패(일반 실행), 고정 인수 변경, 예산 초과, 범위 밖 쓰기, 승인 경계 도달.


