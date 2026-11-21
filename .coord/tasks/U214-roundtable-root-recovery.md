# U214 — 반복 정지·자동 발동·지연의 공통 원인 복구

상태: ACTIVE 진단. 조율자 Codex native `01a14d49-1f61-7f01-9825-53eaa9b70f20`. 제품 source_writer는 아직 없음. U213 병합·설치와 다른 신규 작업은 P1 해결까지 보류한다. 기존 dirty 파일과 U208 안전 STOP은 유지한다.

## MIA 0: 원문 증거와 실제 실패

- 사용자 반복 신고와 첨부 화면: 이미 ACK된 v3/v4/v5 편지마다 Codex 유료 턴이 다시 시작됐고, 세 도구가 기다렸다. 원래 작성자 확인 요청은 다른 Claude 세션이 ACK했다.
- 실제 사서함 `ack/relay_fc6aefbcbe5cde65fddd79990845cf79.json`: requested_owner는 본문에923a686c인데 실제 수신 창은 a6f8e928였다. ACK 파일은 소비자 세션을 증명하지 않는다.
- Claude 원탁 메모 `relay_8fe7abd592dd20640ad3767b5e3d803c`: `.coord/stall/seen.json={}`, queued만 읽는 scanner, accepted 이후 응답 대기와 문서 R0–R6가 관측 밖이라는 구체 가설. 아래 재현으로 독립 검증한다.
- Antigravity 반례 `relay_89507a36d4a2ea0e76fc20cc02e65951`: 역사 accepted 전수 재활성화 금지, quiet lock/live worker 중 소유권 만료 금지, 서로 다른 카드/판정을 같은 thread라는 이유로 합치지 말 것.
- 공식 근거: [Codex hooks](https://learn.chatgpt.com/docs/hooks), [Claude hooks](https://code.claude.com/docs/en/hooks)는 UserPromptSubmit의 사전 차단을 문서화한다. [Microsoft FileSystemWatcher](https://learn.microsoft.com/en-us/dotnet/api/system.io.filesystemwatcher)는 파일 변경 알림 인터페이스, [Python os.open](https://docs.python.org/3/library/os.html#os.open)은 배타 생성 기반 로컬 잠금의 근거다. 알림은 전달 증명이나 exactly-once 보장이 아니다.

## MIA 1–2: 성공·비목표·고정 관문

1. explicit native receiver가 전송·재개·소비·ACK까지 유지되고 다른 세션 ACK가 원본을 제거하지 못한다. 세 도구를 모두 검사한다.
2. ACK된 정확한 relay id+digest는 새 native dispatch/유료 턴을 시작하지 않는다. 서로 다른 카드·버전의 실제 새 산출물은 손실 없이 남는다.
3. 실행/응답 대기는 canonical 상태에 보이며 기한 후 결정적 처리된다. 죽은 작성자를 UNKNOWN으로 영구 대기하지 않는다. 단, live worker/QUIET_LOCK과 SAFETY_GATE는 재배정 금지다.
4. 지휘자는 실제 제한·부재 도구를 제외한 Codex→Claude→Antigravity 순서의 단일 소유자다. 세 도구의 감시자는 읽기·증거 전달만 병행하고 같은 원본을 병렬 수정하지 않는다.
5. 통신 지연은 publish→native ingress→동일 payload의 다음 실행으로 각각 실측한다. 로컬 알림 목표 p95 2초 이내, 잘못된 세션 소비0, 중복 유료 시작0. 실제 플랫폼 시작 시간이 미검증이면 UNKNOWN으로 남긴다. 물리적 지연0은 보장하지 않는다.

비목표: 알림 UI로 정지 오류를 대체, 전면 rewrite, 권한/샌드박스 완화, 유료 폴링, 역사 편지 전수 재실행, 서로 다른 verdict 일괄 소거.

## MIA 3–4: 대안과 결정

| 대안 | 가치·실현성 | 위험·복구 | 결정 |
|---|---|---|---|
| 세 도구 모두 지휘·수정 | 대기 일부 감소, 구현 단순해 보임 | split-brain·동시 쓰기, 기존 소유권 침해 | 제외 |
| 고정 도구 지휘+긴 폴링 | 기존 구조 재사용 | 한도·죽은 세션을 영구 기다림 | 제외 |
| 단일 제한 인식 지휘+수신자 결합+모든 대기의 공통 원장+결정적 감시 | 원인별 작은 증명 가능, 활성 도구가 계속 진행 | native ingress/budget/idempotency 미확인 경로는 그대로 차단; 카드별 역패치 가능 | 채택, 독립 재현 뒤 작은 slice |

## MIA 5–8: 원탁 계약과 단일 작성자

원탁 work_id U214, 입력은 이 문서 전체와 위 실제 relay/사서함 bytes. 허용 산출물은 각자의 `.work/u214/` 진단·계약·한 번의 최종 답장이다. 제품/설정/공유 dirty 파일 쓰기 금지, 새 paid worker/audit subprocess0, 180초. 판단자는 Codex, 구현은 고정 인수와 전용 실행 소유권 확정 후 local pilot 우선이다.

- Claude: 기존 원탁 메모의 accepted-wait 누락을 현재 설치 코드에 대해 재현하고, 즉시 실행 가능한 전용 실행 세션·작업트리를 제시한다. 죽은923a686c 응답을 더 기다리지 않는다. user desk는 조율하며 제품 원본을 쓰지 않는다.
- Antigravity: 위 대안과 receiver/ACK/failover/중복 억제의 최소 반례를 독립 검토한다. 현재 새 U214 작성자는 없으므로 겹치는 구현을 시작하지 않는다.
- Codex: explicit thread 소실, 타 세션 ACK, ACK relay 재-dispatch, 제한 우선순위와 stale waits를 분리 재현한다. 첫 실패 slice의 원문 인수·hash를 고정한다.

원탁이 끝나면 카드별 SOURCE/OWNER/INPUT/ACCEPTANCE/STOP을 고정하고, 전용 실행자가 QUIET_LOCK 아래 한 slice를 수행한다. 작성자 아닌 도구가 정확한 diff와 인수를 판정한다. source local tests, exact-head CI, 표준 merge, runtime identity와 세 도구 live native 증거를 별도 관문으로 처리한다.

## MIA 9–10

아직 제품 수정·기능 완료를 주장하지 않는다. 기존 U210-v5 helper6 PASS는 원인 전체의 완료 증거가 아니다. 단계별 재현·수정·회귀·설치·live 검증을 이 카드와 receipt에 누적한다. 원탁 답장/알림/ACK만으로 이 카드를 종료하지 않는다.
