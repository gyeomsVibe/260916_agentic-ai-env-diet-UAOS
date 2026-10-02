# U129 — 카드 창은 사용자가 쓰는 PC 앱에 보여야 한다

작성: Claude (Codex LIMITED 동안 지휘 대행), 2026-10-02. Codex 재검토 대상.

## 1. 무엇이 문제였나 (영수증)

- UAOS는 카드(작업 하나)마다 도구별 전용 창을 하나씩 연다(U114). 기록은 `.coord/windows/<카드>.json`.
- Claude 창은 `claude --bg`(백그라운드 세션, background session)로 열었다.
- 그런데 `--bg` 세션은 **Claude 데스크톱 앱에 나타나지 않는다.** 터미널의 `claude agents` 화면에서만 보인다.
- 그 결과 U129 작업 3건이 사용자 눈에 보이지 않은 채 구독 토큰을 썼다(한 건: 호출 36회, 캐시 읽기 약 330만 토큰, API 단가로 약 US$3). 세 작업은 삭제했다.

## 2. 근거 (1차 자료)

| # | 출처 | 확인한 사실 |
|---|---|---|
| 1 | code.claude.com/docs/en/desktop | 데스크톱과 CLI는 "각자 자기 세션 목록을 가진다". 백그라운드에서 실행 중인 세션은 데스크톱으로 옮기지 않는다. |
| 2 | code.claude.com/docs/en/agent-view | 백그라운드 세션은 로컬 감독 프로세스(supervisor)가 돌리고 `claude agents/attach/logs/stop`으로만 관리한다. 데스크톱 언급 없음. |
| 3 | claudeissues.com 이슈 75624 | 데스크톱 Code 탭에서 `/bg`는 "이 환경에서 사용할 수 없음"으로 답한다(터미널 전용). |
| 4 | 로컬 `claude --help` (2.1.287) | `--bg`의 id는 `claude attach/logs/stop/rm`이 받는다. `--desktop`은 기존 세션을 데스크톱에서 연다. |
| 5 | antigravity.google/docs/cli/headless | `agy -p --conversation <id>`로 대화를 이어 쓴다. 앱 표시 여부는 문서에 없다. |
| 6 | Antigravity 코드랩·CLI 문서 | CLI 대화는 `~/.gemini/antigravity-cli/conversations/`에 저장된다. |
| 7 | 로컬 확인 | 기록된 Antigravity 창 id 2개는 CLI 저장소에만 있고, 앱 저장소(`~/.gemini/antigravity/`, `antigravity-ide/`)에는 없다. |
| 8 | codex.danielvaughan.com (cross-surface session sync) | Codex app-server 스레드는 Codex 데스크톱 앱과 공유된다 → Codex 경로는 그대로 둔다. |

정리 파일: `.work/cards/U129_visible_research.md` (저장소 밖 작업 폴더).

## 3. 결정

| 도구 | 앱에 보이나 | 조치 |
|---|---|---|
| Claude | `--bg`는 안 보임(1·2·3) | `--bg` 실행 경로 삭제. 보이는 데스크톱 세션 id를 기록만 한다. |
| Antigravity | UNKNOWN, 증거상 안 보임(5·6·7) | 코드 변경 없음. PLAN에 표시. 실사용 영수증이 생길 때만 기능 추가. |
| Codex | 보임(8) | 변경 없음. |

검토한 대안:
1. `claude --bg` 유지 + 경고문 → 보이지 않는 토큰 소비가 그대로라 No-Go.
2. `claude --desktop --resume <id>`로 옮기기 → 실행 중인 백그라운드 세션은 옮기지 않는다(근거 1)라 No-Go.
3. **보이는 데스크톱 세션을 지휘자가 열고 그 id만 기록** → 아무 것도 몰래 실행하지 않는다. Go.

## 4. 사용법

1. 지휘자(데스크톱 앱의 Claude)가 보이는 세션을 연다. 데스크톱 앱에서는 spawn_task 칩으로 열고, 사이드바에서 보인다.
2. 그 세션 안의 `CLAUDE_CODE_SESSION_ID`(전체 UUID)를 기록한다.

```powershell
uaos coord window --card U129 --tool claude --title "보이는 창" --session-id 46b09584-c7ba-434e-8714-f4cce3058dbd
```

- `--session-id`가 없으면 아무 것도 실행하지 않고 종료 코드 2와 `NO_VISIBLE_SESSION` 안내문을 낸다.
- 이미 기록된 카드는 `--session-id` 없이도 그 기록을 재사용한다.
- id는 전체 UUID만 받는다(소문자로 저장). 8자리 접두사, 경로, 사이드바 제목은 거부(ValueError).
- `--session-id`는 Claude 전용. Codex·Antigravity는 예전처럼 `--prompt-file`이 필요하다.

## 5. 남은 위험

- `coord deliver`가 카드 창 편지를 `claude -p --resume <id>`로 이어 쓸 때, 사용자가 그 데스크톱 세션을 열어 둔 상태면 기록 충돌 가능성이 있다(Antigravity 감사 지적). 실제 실패 영수증이 없어 이번 카드에서는 고치지 않는다.
- Antigravity 카드 대화(U127)는 앱에 보이지 않을 가능성이 높다. 영수증이 생기면 별도 카드.

## 6. 검증

- 판정자 작성 시험: `tests/test_u129_visible_claude_window.py`(11개) + `tests/test_u114_windows.py`의 Claude 시험 3개 재작성. 수정 전 13개 실패.
- 전체: `python -m unittest discover -s tests` → 1536개 중 실패 1(U129와 무관한 `test_u92` brief-ko 사본 차이), `.work/logs/u129_full.log`.
