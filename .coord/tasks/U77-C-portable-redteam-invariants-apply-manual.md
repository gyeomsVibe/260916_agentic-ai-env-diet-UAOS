```contract
work_id: U77-C2
worker: apply
goal: Carry Claude's accepted red-team invariants into the portable UAOS block so non-canonical projects receive the same adaptive safeguards.
inputs:
- uaos_everywhere/uaos_global_rule_block.md sha256=6976b1e00e9d199a5f4e692ddb1b85cfbad0e80f50399fc8e9b55cbf4c4e34ff
- tests/test_u77_adaptive_nonstop.py sha256=5f04d918dbd6832f95d1d52fcf6d7cdf53958675b54b8cd68926fd82d29a0ee5
- tests/test_u37_install_everywhere.py sha256=c4596292e05327d3b1e2f2c591c70c46f3a6a2207cc6617efb500ef7f0dd25f7
- tests/test_u41_deploy_to_this_pc.py sha256=0b2d0723f08f8f795c5d7cc1cffdf96720ca3529c1ee6561651bd245dda7b050
- tests/test_u45_general_uaos.py sha256=5f04a361fcf053cd0217655d3afc20a05b5d4a22e373deb80b5439331f4bd7c8
allow:
- uaos_everywhere/uaos_global_rule_block.md
- tests/test_u77_adaptive_nonstop.py
acceptance: python -m unittest tests.test_u77_adaptive_nonstop tests.test_u37_install_everywhere tests.test_u41_deploy_to_this_pc tests.test_u45_general_uaos
forbidden: edits outside allow; editing existing tests outside U77; weakening human approval boundaries; network; delete; commit; push; PR; merge; deployment
stop: input hash mismatch; source divergence; no changed files; three failures with the same cause
judge: codex
timeout_s: 300
remote_budget_tokens: 0
```

===EDIT: uaos_everywhere/uaos_global_rule_block.md===
<<<<<<< SEARCH
- 요구·증거·설계·소유권·도구 상태가 바뀌면 영향받은 가정과 카드를 무효화하고 설계·고정 인수·계약 매뉴얼을 다시 발행한 뒤 실행·독립 비판·검증을 반복한다. 도구 검토·테스트·PR 준비·다음 카드는 내부 의존성이지 사용자 일이 아니며, 사용자에게 다시 시작이나 계속 명령을 요구하지 않는다.
- 매 턴 종료 관문에서 목표 완료와 내부 의존성 0, 미승인 사람 전용 경계, 또는 모든 안전 경로의 외부 차단과 영속 인계·유료 토큰 0 감시 준비 중 하나를 증명한다. 아니면 다음 안전 단계를 계속한다.
=======
- 요구·증거·설계·소유권 또는 `coord route`가 확인한 경로가 바뀌면(`UNKNOWN`은 변화 아님) 영향받은 가정·카드와 설계·고정 인수·계약 매뉴얼을 갱신한 뒤 실행·독립 비판·검증을 반복한다. 같은 카드는 최대 2회 재계획한 뒤 경로를 한 번 바꾸며 3배 비용 회귀는 실패다. 도구 검토·테스트·PR 준비·다음 카드는 내부 의존성이지 사용자 일이 아니지만, 이 분류는 사람 확인 목록을 바꾸지 않는다. 사용자에게 다시 시작이나 계속 명령을 요구하지 않는다.
- 매 턴 종료 관문에서 목표 완료와 내부 의존성 0, 미승인 사람 전용 경계, 또는 모든 안전 경로의 외부 차단과 영속 인계·유료 토큰 0 감시 준비 중 하나를 증명한다. 감시 만료를 기록하고 재가동하거나 sentinel/schedule에 인계한다. 독립 검토자를 쓸 수 없으면 UNKNOWN으로 남기고 자기 승인하지 않으며 다른 `READY`를 진행한다. 아니면 다음 안전 단계를 계속한다.
- 병합 링크는 실시간 PR이 `OPEN`이고 병합 가능함을 확인한 뒤만 사용자에게 표시하며, 대체·폐쇄되면 같은 보고에서 즉시 밝힌다.
>>>>>>> REPLACE

===EDIT: tests/test_u77_adaptive_nonstop.py===
<<<<<<< SEARCH
            "요구·증거·설계·소유권·도구 상태",
            "영향받은 가정과 카드",
            "설계·고정 인수·계약 매뉴얼",
            "내부 의존성이지 사용자 일이 아니며",
            "다시 시작이나 계속 명령",
            "종료 관문",
            "영속 인계·유료 토큰 0 감시",
        ):
=======
            "요구·증거·설계·소유권 또는",
            "영향받은 가정·카드",
            "설계·고정 인수·계약 매뉴얼",
            "내부 의존성이지 사용자 일이 아니지만",
            "다시 시작이나 계속 명령",
            "종료 관문",
            "영속 인계·유료 토큰 0 감시",
            "`UNKNOWN`은 변화 아님",
            "최대 2회",
            "3배 비용 회귀는 실패",
            "사람 확인 목록을 바꾸지 않는다",
            "감시 만료",
            "자기 승인하지 않으며",
            "`OPEN`이고 병합 가능",
        ):
>>>>>>> REPLACE
