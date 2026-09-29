```contract
work_id: U87
worker: apply
goal: Give the portable UAOS rule block the formal name UAOS-RSI and each tool adapter its role and budget.
inputs:
- .coord/PLAN.md sha256=49e80dded94b5736e0336baffffc7518f2671b44a4e2124fa81c4215c64e2154
- uaos_everywhere/uaos_global_rule_block.md sha256=2b00731f8b29b5ce6a330ba7192a23826c24648891058144dc0651d3800b63e5
- uaos_everywhere/adapters/claude.md sha256=7f71a86a96264809ab4e9d49486314a3875fa95ca558525a1ee4aad0c80b3028
- uaos_everywhere/adapters/codex.md sha256=c13ae90f52ee20ca329982aa6fd73dffc43f89e09ac837f113987c37ff4ce988
- uaos_everywhere/adapters/antigravity.md sha256=76df9f583ad47f9c85a0919948a4b8b5e730435a6c3bbbe857f98fc05963f90d
allow:
- uaos_everywhere/uaos_global_rule_block.md
- uaos_everywhere/adapters/claude.md
- uaos_everywhere/adapters/codex.md
- uaos_everywhere/adapters/antigravity.md
- tests/test_u87_uaos_rsi_name.py
- .coord/PLAN.md
acceptance: python -m unittest tests.test_u87_uaos_rsi_name tests.test_u45_general_uaos tests.test_u77_adaptive_nonstop tests.test_u37_install_everywhere
forbidden: design changes; edits outside allow; weakening or deleting existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the EDIT blocks exactly. The new test pins the name and the per-tool role and budget lines.

===EDIT: uaos_everywhere/uaos_global_rule_block.md===
<<<<<<< SEARCH
## UAOS — 모든 프로젝트에 공통인 협업 운영 체계(Unified Agent Operating System)

=======
## UAOS-RSI — 모든 agentic AI 환경의 기본 운영체제(Unified Agent Operating System with evidence-gated Recursive Self-Improvement)

>>>>>>> REPLACE
===EDIT: uaos_everywhere/adapters/antigravity.md===
<<<<<<< SEARCH
## Antigravity 역할 어댑터


=======
## Antigravity 역할 어댑터

- UAOS-RSI 역할: 계약 실행자·반례 검토자. Codex와 Claude가 모두 LIMITED/ABSENT일 때만 지휘를 대행한다.
- UAOS-RSI 예산: 실행마다 매뉴얼의 토큰·시간 상한을 지니고, 넘친 실행은 거부된다(반복 RSI 원인이 COST_EXCEEDED).

>>>>>>> REPLACE
===EDIT: uaos_everywhere/adapters/claude.md===
<<<<<<< SEARCH
## Claude Code 역할 어댑터


=======
## Claude Code 역할 어댑터

- UAOS-RSI 역할: 동등한 부지휘자이자 기본 구현자. 카드를 설계해 `worker: apply`(유료 0토큰)나 계약 작업자로 적용하고 전체 테스트·PR·장부를 맡는다.
- UAOS-RSI 예산: 구독 `/usage` 한도. 카드마다 세션 토큰을 기록하고(`card_cost` 관문), 기계적 일은 결정적 apply와 Ollama로 돌리며, 자기 결과 판정에 토큰을 쓰지 않는다(판정은 Codex, 불가하면 UNKNOWN).

>>>>>>> REPLACE
===EDIT: uaos_everywhere/adapters/codex.md===
<<<<<<< SEARCH
## Codex 역할 어댑터


=======
## Codex 역할 어댑터

- UAOS-RSI 역할: 지휘자이자 최종 독립 판정자. 구현은 Claude Code·`worker: apply`·Ollama·Antigravity에 맡긴다.
- UAOS-RSI 예산: 가장 부족한 유료 한도라 계획과 판정에만 쓴다. 부족하면 동시성·보안·전역 규칙 변경의 판정에만 코드만 담은 패킷으로 쓴다(판정 1회 36~46k 토큰, 2026-09-29 실측).

>>>>>>> REPLACE
===EDIT: .coord/PLAN.md===
<<<<<<< SEARCH
| U86 | DONE-DELEGATED (Codex LIMITED 중 Claude 권한대행 2026-09-29 — Codex 복귀 시 재검토) | claude(대행 설계) · apply(0토큰) | 윤겸스 지시(2026-09-29 "처리하라"): 스트림 잠금 `_exclusive`의 60초 mtime 회수를 OS 파일 잠금으로 교체(U83과 같은 결함: 멈춘 보유자 잠금 탈취·죽은 보유자 60초 차단). 잠금 도우미는 deliver.py에서 stream.py로 옮겨 공유. presence.py·thrift.py의 같은 60초 회수는 실패 영수증 전까지 보류. — `v7_harness/coord/stream.py`, `v7_harness/coord/deliver.py`, `tests/test_u86_stream_os_lock.py` |

=======
| U86 | DONE-DELEGATED (Codex LIMITED 중 Claude 권한대행 2026-09-29 — Codex 복귀 시 재검토) | claude(대행 설계) · apply(0토큰) | 윤겸스 지시(2026-09-29 "처리하라"): 스트림 잠금 `_exclusive`의 60초 mtime 회수를 OS 파일 잠금으로 교체(U83과 같은 결함: 멈춘 보유자 잠금 탈취·죽은 보유자 60초 차단). 잠금 도우미는 deliver.py에서 stream.py로 옮겨 공유. presence.py·thrift.py의 같은 60초 회수는 실패 영수증 전까지 보류. — `v7_harness/coord/stream.py`, `v7_harness/coord/deliver.py`, `tests/test_u86_stream_os_lock.py` |
| U87 | DONE-DELEGATED (Codex LIMITED 중 Claude 권한대행 2026-09-29 — Codex 복귀 시 재검토) | claude(대행 설계) · apply(0토큰) | 윤겸스 지시(2026-09-29): 정식 명칭 UAOS-RSI, 모든 agentic AI 환경의 기본 운영체제, 도구별 역할·토큰 예산. 전역 규칙 정본 v6.0.0(platform PR #5)과 같은 내용을 정본이 없는 PC에 설치되는 이식용 규칙 블록·도구 어댑터에도 반영. — `uaos_everywhere/uaos_global_rule_block.md`, `uaos_everywhere/adapters/*.md`, `tests/test_u87_uaos_rsi_name.py` |

>>>>>>> REPLACE
===FILE: tests/test_u87_uaos_rsi_name.py===
"""U87: the portable rule block carries the formal name UAOS-RSI and each tool adapter its role and budget.

User order 2026-09-29: UAOS-RSI is the default operating system of every agentic AI environment, with each tool's role
and token budget set per tool. The global-rules canon (v6.0.0) says so on this PC; this block is what the installer
writes on a PC without that canon, so it must say the same.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from v7_harness.global_install import ADAPTER_SOURCE, RULE_BLOCK_SOURCE, plan

ROOT = Path(__file__).resolve().parents[1]


class UaosRsiNameTests(unittest.TestCase):
    def test_block_heading_is_the_formal_name(self) -> None:
        first = RULE_BLOCK_SOURCE.read_text(encoding="utf-8").splitlines()[0]
        self.assertTrue(first.startswith("## UAOS-RSI — "), first)
        self.assertIn("기본 운영체제", first)

    def test_every_adapter_sets_role_and_budget(self) -> None:
        for tool, path in ADAPTER_SOURCE.items():
            text = Path(path).read_text(encoding="utf-8")
            self.assertEqual(1, text.count("- UAOS-RSI 역할:"), tool)
            self.assertEqual(1, text.count("- UAOS-RSI 예산:"), tool)

    def test_a_plain_home_gets_the_name_and_only_its_own_budget(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            for folder in (".claude", ".codex", ".gemini"):
                (home / folder).mkdir()
            changes = {change.target: change for change in plan(home, "python", repo=ROOT)}
            for tool in ("claude", "codex", "antigravity"):
                text = changes[f"{tool} rules"].new_text
                self.assertIn("## UAOS-RSI — ", text)
                self.assertEqual(1, text.count("- UAOS-RSI 예산:"), tool)


if __name__ == "__main__":
    unittest.main()
===END===

## Output

- Reply with ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.
