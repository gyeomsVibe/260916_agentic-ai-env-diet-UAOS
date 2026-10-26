# 43. 사용자 PC 마무리 배포를 명령 하나로 — `deploy_to_this_pc` (U41, 2026-09-25)

- 사용자 지시(2026-09-25): "3대 도구 전역 규칙 배포, 깃 커밋, 깃 푸시가 마무리될 때까지 무승인 절차로 논스톱으로 진행하고, 사용자를 시켜야 할 일은 모두 너의 도우미로 안티그래비티를 사용하여 무승인으로 진행해라."
- 상태: **사용자 PC에서 실행 완료(2026-09-25 15:17, 영수증 `.coord/runs/U41/deploy_receipt_20260925T151707.json`).**
  - 0~12단계가 모두 OK다. 회귀, 훅 설치, 정본 문단, 생성기 Build·SourceCheck·Apply·Check, 세 런타임 규칙 확인, 설치기 점검이 여기에 들어간다.
  - 정본 푸시에 성공했다(`260718_agentic-ai-platform-optimization` `dee64c7..be0ef78 main`).
  - 정본 원본은 `claude.md`(Claude)와 `core.md`(Codex·Antigravity 공용)였다.
  - 경고 2건(설계상 멈추지 않음):
    - 교환원 등록 exit 1: 관리자 권한이 필요하다.
    - 정본 commit exit 1: 앞선 실행이 이미 커밋해 둬서 "커밋할 것 없음"이었다.
  - **발견한 결함(수정함)**: 커밋된 영수증이 `result: DRY_RUN`으로 적혀 있었다.
    - 원인: 영수증을 실행 도중(`receipt_commit` 직전)에 찍어 커밋하는데, 그때 결과 칸이 기본값 `DRY_RUN` 그대로였다.
    - 수정: 실제 실행은 시작부터 `IN_PROGRESS`로 적는다. 커밋본에는 `snapshot_of`로 "중간 사본"임을 표시한다. 최종 결과(`DONE`)는 로컬 파일에 남는다.
    - 이 영수증은 실제로는 정본 푸시까지 성공한 실행이다.
- 바뀐 점(PR #1 병합 뒤): Claude 브랜치가 `main`에 병합됐으므로 **배포는 `main`에서 실행한다.** 스크립트 기본 브랜치도 `main`이다(`--branch`로 바꿀 수 있다).

## 0. 쉽게 말하면

- 사용자 PC에서 남은 일은 모두 **정해진 명령의 순서**다. 테스트 실행, 설치, 정본 규칙에 문단 넣기, 생성기 돌리기, 확인, 커밋, 푸시가 전부다. 판단이 필요 없으므로 AI 모델이 필요 없고, 토큰도 0이다.
- 그래서 사람이나 AI에게 "이것저것 해 줘"라고 시키지 않고 **스크립트 하나**가 순서대로 한다. 각 단계에는 통과 기준(관문)이 있다. 관문 하나라도 실패하면 거기서 멈추고, 어디서 멈췄는지 영수증에 남긴다.
- 누가 실행하나:
  - 사용자 PC에 있는 **Codex**가 실행한다. Codex가 한도·부재면 **Antigravity**가 같은 명령을 실행한다.
  - 클라우드의 Claude는 PC에 손이 닿지 않으므로 직접 실행할 수 없다.
- Antigravity의 AI다운 역할은 따로 있다. 배포가 끝난 뒤 영수증을 **읽기만 하며 검증**하는 1회 호출이다(예산 제한). 만든 사람(Claude)과 실행한 사람(Codex)은 검증자가 될 수 없기 때문이다.

## 1. 명령

```powershell
cd D:\...\260916_agentic-ai-env-diet
git switch main
git pull --ff-only                                              # 병합된 최신 main
python uaos_everywhere/deploy_to_this_pc.py                    # ① 계획만 표시(아무것도 안 바꿈)
python uaos_everywhere/deploy_to_this_pc.py --apply --push     # ② 실행 + 커밋 + 푸시
```

- 정본 저장소 위치의 기본값은 이 저장소 옆의 `260718_agentic-ai-platform-optimization`이다. 다르면 `--canon <경로>`를 준다.
- 정본에서 세 규칙 원본을 하나씩 딱 집어낼 수 없으면 추측하지 않고 멈춘다(`CANON_SOURCES_AMBIGUOUS`). 이때 `--canon-file claude=<경로>`처럼 지정한다.

## 2. 단계와 관문

| # | 단계 | 관문 | 실패하면 |
|---|---|---|---|
| 0 | 정본 원본 찾기 | 런타임마다 원본 1개(`dist`·`scripts`·백업 폴더 제외) | 멈춤. 후보 목록을 영수증에 남김 |
| 1 | 브랜치 확인 | 현재 브랜치가 `main`(또는 `--branch`로 준 브랜치) | 멈춤 |
| 2 | 정본 깨끗함 | `shared/global-rules`에 커밋 안 된 변경이 없음(U29: 관련 없는 변경이 섞이지 않게) | 멈춤 |
| 3 | 가져오기·병합 | `git fetch` 후 `git merge`(재배치 rebase 금지) exit 0 | 멈춤 |
| 4 | 전체 회귀 | `run_regression.py` exit 0 | 멈춤 |
| 5 | 훅·차단 설치 | 설치기 `--apply --no-rules` exit 0(실행기, 출석 훅, Claude 예약 도구 차단) | 멈춤 |
| 6 | 정본에 문단 | 설치기 `--apply --no-rules --portable --rules-file …` exit 0 | 멈춤 |
| 7~10 | 생성기 | `sync-global-rules.ps1 -Mode Build → SourceCheck → Apply → Check`, 각각 exit 0 | 멈춤 |
| 11 | 런타임 확인 | `~/.claude/CLAUDE.md`·`~/.codex/AGENTS.md`·`~/.gemini/GEMINI.md`에 UAOS 문단 있음 | 멈춤 |
| 12 | 설치기 점검 | `--check --no-rules --portable --rules-file …` exit 0 | 멈춤 |
| 13 | 24/7 교환원 | 로그온 작업 등록(Windows) | **경고만**. 관리자 권한 거부면 `shell:startup` 바로가기 안내 |
| 14~19 | (`--push`) 커밋·푸시 | 정본: 이번 원본과 `dist`만 add → commit → push. 이 저장소: 영수증 add → commit → `push origin HEAD:main` | 푸시 실패는 멈춤. "커밋할 것 없음"은 재실행이라 괜찮음 |

영수증은 `.coord/runs/U41/deploy_receipt_<시각>.json`이다. 모든 단계의 명령, 종료 코드, 걸린 시간, 출력 끝부분을 담는다.

## 3. 설계 결정

| 결정 | 이유 |
|---|---|
| **정본에는 이식 가능한 문단**(`python "$HOME/.uaos/uaos.py"`)을 넣는다 | 정본은 공유되고 푸시되는 저장소다. 이 PC의 `C:/Users/…` 경로가 들어가면 개인 경로가 새고 다른 PC에서는 틀린다. `$HOME`은 bash와 PowerShell 모두에서 펼쳐진다 |
| 런타임 규칙 파일은 설치기가 아니라 **생성기**가 쓴다(`--no-rules`) | 설치기와 생성기가 서로 다른 문단을 번갈아 쓰면 끝없이 뒤집힌다(B82). 정본이 문단을 가지면 생성기의 Apply가 세 런타임에 똑같이 배포한다 |
| 정본이 더러우면 멈춘다 | U29에서 정본에 관련 없는 미커밋 변경이 있었다. 이번 커밋에 섞이면 안 된다 |
| 병합만, 재배치 금지 | 다른 사람(Codex)의 로컬 커밋과 체크아웃을 깨지 않는다 |
| 교환원 등록 실패는 경고 | 관리자 권한이 필요할 수 있다. 배포의 본질(규칙·훅)과 분리한다 |

## 4. 검증과 한계

- 테스트: `python -m unittest tests.test_u41_deploy_to_this_pc` → 10 OK. 확인한 것:
  - 정본 원본 찾기(`dist` 무시)
  - 모호하면 멈춤, 지정하면 해결
  - 계획 모드는 아무것도 실행하지 않음
  - 전체 실행 순서와 커밋·푸시 순서
  - 첫 실패에서 멈추고 푸시하지 않음
  - 잘못된 브랜치·더러운 정본은 가장 먼저 멈춤
  - 문단이 빠진 런타임에서 멈춤
  - 정본 문단에 개인 경로 없음
- 전체 회귀(Linux): 748개 중 실패 1(B75).
- **UNKNOWN**:
  - 정본 원본 파일의 실제 이름과 위치(U30 기록에는 `claude.md`만 나온다). 모호하면 스크립트가 멈춘다.
  - 생성기가 `Build` 모드를 지원하는지(U29 기록에는 Build가 있다).
  - Windows PowerShell 경로.
