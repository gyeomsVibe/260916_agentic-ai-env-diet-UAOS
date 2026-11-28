# ARTICLES-V04-P1 — 합의 증거와 협의 편지 수신 범위

상태: SPEC_REVIEW. 실제 P1 receipt relay_11baee031faaffee4afcf51b38956e6f. 조율·독립 판정 Codex. 명세 작성 Claude. 기존 HTML 수정 작성자 Antigravity 유지. U222-R 코드 작성권을 가져오지 않는다.

## 확인한 원인
1. 원래 거절한 report SHA8e34f18e9c7e08f22ae4feaef17a24d002f4858fd606f9f250bdaab484e008cf가 그대로다. HTML136줄 협의완료,262줄 합의안 주장이 있고 provenance.json은 없다. 기존 ARTICLES-V04-REPORT-REVISION 계약이 이미 수정을 맡고 있으므로 중복 작성자를 만들지 않는다.
2. 설치0.3.0-eb7141da0e28에서 실제 Claude 협의 편지 relay_3ccaca8584ffb309c0bb61eed6638283은 card=DESK-261019, 등록된 Claude card receiver=null. _foreign=true, _replay_bound=false, urgent=false를 읽기 전용 probe로 재현했다. 이를 단순 RESUME cursor 누락으로 단정하지 않는다. 현재 격리 관문이 미등록 card를 제외하는 것은 유지해야 한다.
3. 기존 U202는 오래된 실제 수신자 편지를 ACK 전까지 RESUME_PENDING으로 보존한다. 따라서 모든 도구 대상 편지를 모든 창에 주입하는 제안은 채택하지 않는다. producer metadata와 수신 대상의 관계부터 바로잡는다. 일반 책상 협의는 해당 명시적 native desk로 보내고 task-card transport를 붙이지 않는다. 실행 편지는 등록된 card/window에만 보낸다.

## 대안과 결정
- A: 기존 HTML 정정·실제 회신 대조만 수행. 즉시 피해를 줄이지만 재발 차단은 아직 미증명.
- B: 각 참여자의 최신 동일 work_id/artifact SHA 회신을 대조하는 보고 증거 명세 + 정확한 receiver 범위의 누락 진단. 기존 계약 재사용, 작은 고정 반례로 검증 가능. 선택.
- C: 전 inbox 본문 무제한 주입. 토큰·외부 card 누출·기존 U202 관문 충돌로 REJECT.

## 단계0 근거
공식 GitHub required-review/stale-review 설명: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches . 변경된 diff에 대한 예전 승인을 현재 증거로 쓰면 안 된다는 설계 참고다. GitHub 설정을 변경하거나 로컬 actor 이름표를 인증으로 간주하지 않는다. 현지 실측은 .work/desk261019_2/articles-p1/root-cause-probe.json.

## Claude의 다음 한정 작업
목표: 아래 고정 반례를 명세 JSON으로 구체화. allowed writes는 자신의 .work/articles_v04_p1_spec/spec.json 및 동일 폴더 notes.md만. code/config/HTML/CI/global-rule/계정/모델/평가기/원본 ledger 편집과 구현 호출 금지. 입력은 이 카드 내용, probe JSON, 기존 ARTICLES-V04 두 review/contract JSON뿐. native 현재 세션1회,120초, 원격 worker/API/재위임0. 중간 보고 없이 최종 path+hash+검사 exit만 보낸다. 소유권/입력 SHA가 다르면 STOP.

요구사항:
- consensus record는 work_id, exact artifact_sha256, named_tools, actual message_ids, latest_verdict_by_tool를 포함. 출석/발송/다른 카드 PASS/예전 SHA/유일 작성자 자기판정을 합의나 구현 승인으로 사용하지 않는다. 후속 REVISE는 같은 대상의 예전 AGREE를 무효화한다.
- missing reply, wrong work_id, stale SHA, later REVISE는 각각 consensus=false. 모든 실제 최신 scoped positive가 충족될 때만 true; 이것도 deploy/paid/implementation_go 권한을 만들지 않는다.
- native desk consultation without task card, registered matching card, foreign card, missing card registration, stale cursor, MAX_LINES overflow를 구별한다. 격리 밖 본문 노출0, ACK 전 손실0. eligible manifest/페이지는 제한된 본문+전체 메타데이터 참조로 표현하고 모든 편지 본문을 주입하지 않는다.
- 원래 hook 시점의 cursor·desk generation·window 등록 이력이 없으면 당시 누락의 역사적 원인은 UNKNOWN이라고 명시한다. 현재 probe는 현재 계약상 배제 재현이며 과거 전상태의 증명이 아니다.

산출물 spec.json 필수 키: work_id=ARTICLES-V04-P1, implementation_authorized=false, allowed_writes, consensus_cases(5개), routing_cases(6개), historical_unknowns, source_hashes, proposed_product_scope, stop_conditions. 제품 경로는 제안만, 작성 허가 아님.
고정 인수: python -m json.tool .work/articles_v04_p1_spec/spec.json → exit0 + Codex가 모든 고정 반례/원문/입력 SHA를 대조. 빈·없는 산출물 FAIL. 코드 착수는 별도 linted contract/단일 실행창/비작성자 고정 인수 뒤에만.

## 자동 순서
기존 HTML 정정 검증과 본 읽기 전용 명세 검토는 서로 다른 자원이다. 새 실행 단계는 명세 수신 후 하나씩 결정한다. 현재 원본 코드 변경0, 설치/실행권한 확대0. 실제 비용·절감 UNMEASURED.