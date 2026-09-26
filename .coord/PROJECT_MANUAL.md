# U45 프로젝트 총괄 매뉴얼

- work_id: U45
- 목표: 불특정 소프트웨어 프로젝트에 설치 가능한 UAOS 0.3.0을 만들고, 세 도구의 공통 안전 불변식과 역할별 최소 어댑터를 분리한다.
- 단일 원장: `.coord/PLAN.md`; 현재 카드: `.coord/tasks/U45-general-uaos-budget-manual-core.md`.
- 소유권: Codex가 조율·독립 판정한다. 한 번에 하나의 작업자만 원본을 쓴다.
- 상태기계: Codex ACTIVE이면 Codex, Codex LIMITED/ABSENT이고 Claude ACTIVE이면 Claude, 둘 다 LIMITED/ABSENT이고 Antigravity ACTIVE이면 Antigravity. UNKNOWN은 대행 근거가 아니며 fail-closed 한다.
- 예산: 공급자 잔여율·리셋 창을 토큰으로 환산하지 않는다. 유료 호출은 계약의 token/USD/time 상한을 각각 집행하고 초과 결과를 승인하지 않는다.
- 위임: 각 호출 전에 해시 고정 계약을 파일로 발행·lint하고 그 파일 내용 전체를 실제 호출에 전달한다.
- 검증: 작업자 보고가 아니라 diff, 고정 테스트, 테스트 SHA, 설치 drift, 장부 영수증, 원격 SHA로 판정한다.
- 승인 경계: U45 전역 배포·commit·fetch·push·PR은 사용자 승인됨. 자동 merge, 실제 삭제, 결제, 자격증명·권한 변경은 금지.
- retention: archive candidate와 복구 manifest만 생성한다. 삭제는 이 계획과 별도의 최신 명시 승인이 있어야 한다.
- 중단: 같은 원인 2회 실패, 입력 해시 불일치, 예산 초과, 범위 밖 쓰기, 인수 미실행.

