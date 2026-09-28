# U48-M1 — 새 실세션 olla 호출 영수증 (2026-09-28)

> 작성·판정: Claude(사용자 위임으로 Codex 권한 대행). 독립 판정이 아니다. 복귀한 Codex가 재검토한다.

## 1. 무엇을 확인했나 (초보자용)

U48-M1은 세 도구(Claude Code·Codex·Antigravity)에 `olla` MCP 서버(로컬 모델을 부르는 전화기)를 다시 등록한 카드다.
2026-09-27에는 등록과 직접 연결(handshake)만 확인했고, **각 도구의 새 세션이 실제로 olla 도구를 부를 수 있는지**는 미확인(UNKNOWN)이었다.
이번에는 각 도구의 실제 세션에서 도구를 한 번씩 불러 보았다.

## 2. 결과

| 도구 | 방법 | 결과 | 근거 |
|---|---|---|---|
| Claude Code | 이 세션에서 `local_draft`·`local_search` 호출 | PASS(호출 성공) | draft: 커밋 제목 1줄(50자, 형식 맞음, 따옴표로 감싼 점만 형식 이탈). search: 결과 3개 반환, 가장 관련 깊은 docs/47은 3위 안에 없음(검색 품질은 별도 문제) |
| Codex | `codex exec -s read-only`로 `olla.local_draft` 1회 요청 | BLOCKED(연결은 됨, 호출은 승인 정책이 막음) | 로그: `mcp: olla/local_draft started` → `(failed)` / `MCP tool call requires approval, but approval policy is never`. codex-cli 0.158.0, 모델 gpt-5.6-sol, 13,297 토큰, 32초 |
| Antigravity | 호출 안 함 | UNKNOWN | 데스크 상태 LIMITED(한도) — 복귀 후 확인 |

## 3. 해석

- Codex 쪽은 서버 등록·기동은 정상이다. 비대화형 `codex exec`는 승인 정책이 `never`라서 **승인이 필요한 MCP 도구 호출을 자동 거부**한다. 이는 안전 장치가 의도대로 동작한 것이다.
- 해결책은 Codex 설정에서 olla 도구를 자동 승인 대상으로 두는 것(예: `mcp_servers.olla`의 도구별 승인 모드)이지만, **승인 관문을 완화하는 권한 변경**이라 에이전트가 하지 않는다. 사용자가 결정한다.
- 대화형 Codex 세션에서는 승인 창이 뜰 것으로 예상하지만 확인하지 않았다(UNKNOWN).
- 참고: 세 도구의 olla는 `0.3.2-ad721a2fc713` 런타임에 고정(PYTHONPATH)돼 있다. 설치 런타임(0.3.0-88ae66f1d520)과 다른 것은 의도된 고정이다.

## 4. 판정

- Claude: PASS. Codex: BLOCKED_BY_APPROVAL_POLICY(사용자 결정 필요). Antigravity: UNKNOWN(LIMITED).
- 카드 상태: REVIEW 유지. 남은 확인 2건은 사용자 결정(Codex 승인 모드)과 Antigravity 복귀 뒤다.
