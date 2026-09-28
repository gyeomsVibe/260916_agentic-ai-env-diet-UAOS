```contract
work_id: U77-A
worker: apply
goal: Keep the portable UAOS rule source from overwriting the deployed adaptive re-planning and terminal-gate rules.
inputs:
- uaos_everywhere/uaos_global_rule_block.md sha256=1126beb59eeb81c46b5ac82c5636241fd2b4fecbaaff3d8468a8d1d5c03b3082
- tests/test_u37_install_everywhere.py sha256=c4596292e05327d3b1e2f2c591c70c46f3a6a2207cc6617efb500ef7f0dd25f7
- tests/test_u41_deploy_to_this_pc.py sha256=0b2d0723f08f8f795c5d7cc1cffdf96720ca3529c1ee6561651bd245dda7b050
- tests/test_u45_general_uaos.py sha256=5f04a361fcf053cd0217655d3afc20a05b5d4a22e373deb80b5439331f4bd7c8
allow:
- uaos_everywhere/uaos_global_rule_block.md
- tests/test_u77_adaptive_nonstop.py
acceptance: python -m unittest tests.test_u77_adaptive_nonstop tests.test_u37_install_everywhere tests.test_u41_deploy_to_this_pc tests.test_u45_general_uaos
forbidden: edits outside allow; editing existing tests; network; delete; commit; push; PR; merge; deployment
stop: input hash mismatch; source divergence; no changed files; three failures with the same cause
judge: codex
timeout_s: 300
remote_budget_tokens: 0
```

===EDIT: uaos_everywhere/uaos_global_rule_block.md===
<<<<<<< SEARCH
- 건설적 자율 릴레이(Constructive Autonomous Relay): `verdict_requested=no`, 생존 확인, 동일 상태, 빈 출력은 `ACK_ONLY`로 내부 기록만 하고 사용자·다른 유료 도구를 깨우지 않는다. 실제 변경·새 증거·검증 실패·P1·승인 필요만 `ACTIONABLE_DELTA`다. 변화가 있으면 중복/소유권을 먼저 확인하고 의존성이 충족된 가장 작은 `READY` 작업 하나를 `선택 → 수행 → 고정 인수 → 카드 기록`까지 끝낸 뒤 필요한 상대에게 `사실/증거/다음 한 단계`만 보낸다. 작업 없이 연락만 반복하는 주기 실행은 결함이다.
=======
- 건설적 자율 릴레이: 생존 확인·동일 상태·빈 출력은 `ACK_ONLY`로 조용히 기록한다. 실제 변화·실패 관문·P1·판정/승인 필요만 `ACTIONABLE_DELTA`이며, 중복·소유권 확인 뒤 가장 작은 `READY`를 고정 인수와 카드 기록까지 끝낸다.
- 요구·증거·설계·소유권·도구 상태가 바뀌면 영향받은 가정과 카드를 무효화하고 설계·고정 인수·계약 매뉴얼을 다시 발행한 뒤 실행·독립 비판·검증을 반복한다. 도구 검토·테스트·PR 준비·다음 카드는 내부 의존성이지 사용자 일이 아니며, 사용자에게 다시 시작이나 계속 명령을 요구하지 않는다.
- 매 턴 종료 관문에서 목표 완료와 내부 의존성 0, 미승인 사람 전용 경계, 또는 모든 안전 경로의 외부 차단과 영속 인계·유료 토큰 0 감시 준비 중 하나를 증명한다. 아니면 다음 안전 단계를 계속한다.
>>>>>>> REPLACE

===FILE: tests/test_u77_adaptive_nonstop.py===
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AdaptiveNonstopPortableRulesTest(unittest.TestCase):
    def test_portable_block_preserves_replanning_and_terminal_gate(self):
        text = (ROOT / "uaos_everywhere" / "uaos_global_rule_block.md").read_text(encoding="utf-8")
        for phrase in (
            "요구·증거·설계·소유권·도구 상태",
            "영향받은 가정과 카드",
            "설계·고정 인수·계약 매뉴얼",
            "내부 의존성이지 사용자 일이 아니며",
            "다시 시작이나 계속 명령",
            "종료 관문",
            "영속 인계·유료 토큰 0 감시",
        ):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
