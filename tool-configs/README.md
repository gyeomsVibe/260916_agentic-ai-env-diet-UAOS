# 도구 설정 사본 (tool-configs)

저장소 밖(사용자 홈)에 있어 버전 관리가 안 되던 설정의 사본입니다. 잃어버리거나 새 PC로 옮길 때 이 폴더에서 복원합니다. 전역 규칙 정본(Codex·Antigravity)은 `260718.../shared/global-rules`에 있고, 여기에는 그 생성기가 배포하지 않는 것만 둡니다.

| 사본 | 원래 위치 | 내용 |
|---|---|---|
| `claude/CLAUDE.md` | `~/.claude/CLAUDE.md` | **갱신 안 함.** 전역 규칙 v6.0.0부터 `260718.../shared/global-rules` 생성기가 `~/.claude/CLAUDE.md`를 배포하므로, 이 파일은 그 이전(v9.1 한국어 규칙)의 기록일 뿐이다. 복원은 생성기의 `-Mode Apply`로 한다 |
| `claude/output-styles/brief-ko.md` | `~/.claude/output-styles/` | 매 요청에 붙는 보고 양식(2026-10-02부터 3줄: 결과 1줄 + 근거·위험·남은 일 중 줄 2개 이하). 홈 파일을 고치면 같은 커밋에서 이 사본도 고친다(`tests/test_u92_tool_configs_brief_ko.py`) |
| `claude/settings.hooks.json` | `~/.claude/settings.json`의 `outputStyle`·`env`만 | 자동 압축 22%(1M 창 약 220k). 훅 없음 |
| `codex/hooks.json` | `~/.codex/hooks.json` | 비어 있음 |
| `antigravity/hooks.json`, `mcp_config.json` | `~/.gemini/config/` | 비어 있음 |
| `bin/olla`, `bin/olla.cmd` | `D:/AI-Models/bin/` | 퇴역. 어느 도구에도 연결돼 있지 않음 |
| `claude/settings.uaos-proposed.json` | (없음 — 제안) | **비활성·승인 대기.** 유료 예약 도구 차단(`permissions.deny`)과 출석부 훅. 승인되면 이 프로젝트의 `.claude/settings.json`에 넣는다(docs/37 §8) |

올라마(olla) 연결은 2026-09-23에 3대 도구 모두에서 뺐습니다. 근거는 `.coord/runs/U17/mia_strategic_20260923.md`의 Retire 절을, 되돌릴 때는 `.work/backup_20260923/olla_removal/`의 원본과 이 폴더의 git 기록을 보세요.

권한 목록 등 나머지 설정은 담지 않습니다. 비밀값은 없습니다.
