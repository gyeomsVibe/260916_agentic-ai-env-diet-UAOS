# MCP 등록·규칙 정리 결과

사용자 승인: Antigravity Bridge 등 폐기·충돌 MCP 제거, 전역 규칙·메모리·바이브 자가진단 점검.

## 적용

- Codex config.toml의 antigravity-bridge 등록 삭제. 로컬 mcp_servers에는 node_repl만 유지.
- Codex 전역 AGENTS.md의 Bridge 폴백 제거, 폐기 명시.
- 프로젝트 AGENTS.md의 Bridge 조회·자문 허용 제거, CLI/SQLite 경로로 통일.
- 전역 규칙 원본 저장소의 adapters/codex.md, dist/codex/AGENTS.md, GLOBAL_RULES.ko.md에서 Bridge 강제 호출 문구만 수정. 기존 미커밋 변경 5개는 보존.
- Codex memory_summary.md에 폐기 정정 추가. 원시 메모리·역사 기록·다른 프로젝트 지식 삭제 없음.
- Codex mia-vaccine-test/SKILL.md의 init_clinic/run_clinic/write_error_pattern 의존 절차를 로컬 회귀 테스트·재현 스크립트·오류 문서로 교체. 백신테스트 기능과 기존 진단 데이터 보존.

## 설치 범위 확인

- Codex 전역 config.toml: node_repl, antigravity-bridge 중 Bridge 제거.
- Claude 전역 .claude.json 및 프로젝트별 mcpServers: 출력된 등록은 notebooklm-mcp. 관련 없는 서비스라 보존.
- Gemini antigravity, antigravity-ide, config의 mcp_config.json과 CLI settings.json: 조사한 mcpServers에 Bridge·vibe-clinic·memory 등록 없음.
- 현재 제공 도구 이름에도 vibe/clinic/memory MCP 없음. 설치되지 않은 서비스를 삭제했다고 보고하지 않는다.
- 전역 규칙·메모리·MIA 스킬은 MCP 서버 자체가 아니다. 파일 전체 삭제 대신 충돌하는 호출 지시를 정리했다.

## 후속 정리(최신성 기준)

- 실행 중이던 Antigravity Bridge node PID 4064를 종료했다. 종료 후 동일 명령행 프로세스 0건을 확인했다.
- `260718_agentic-ai-platform-optimization/mcp/antigravity-bridge/`를 활성 소스 트리에서 제거했다.
- `handoff/active/agent-swarm-orchestration.md`는 이미 `status: STALE`이고 Bridge 재검증을 다음 행동으로 지시하므로 활성 인계에서 제거했다.
- 이 프로젝트의 구 제안본 `proposals/global-rules-v5/`, `proposals/global-rules-v6-two-ai/`는 Bridge 전용 호출과 Bridge 유지 계획을 담아 최신 정본과 충돌하므로 제거했다.
- MIA 백신테스트의 설치본과 원본에서 vibe-clinic·`init_clinic`·`run_clinic`·`write_error_pattern` 의존을 제거하고 로컬 회귀 테스트·재현 스크립트로 통일했다.
- 공용 MCP README에서 Antigravity Bridge를 현재 연결된 MCP 목록에서 제거했다.
- 위 제거 대상은 `removed-active-paths/`로 이동해 복구 가능하다. 과거 감사·실험 문서는 실행 규칙이 아닌 역사 증거라 그대로 보존했다.

## 검증·복구·제한

- python tomllib로 config.toml 파싱, Bridge 등록 부재 assert: exit 0.
- 수정한 MIA 스킬에서 init_clinic/run_clinic/write_error_pattern 호출 문자열 없음 확인.
- 프로젝트는 Git 저장소가 아니므로 git status는 exit 128. 원본 규칙 저장소의 기존 dirty 상태는 확인하고 보존했다.
- 백업: C:/Users/Kimyoongyeom/.agent-config-backups/20260918-mcp-retirement/ (변경 전 설정·규칙·메모리 요약·MIA 스킬).
- 활성 설정·규칙·MIA 원본/설치본 검색에서 Bridge 및 vibe-clinic 호출 문자열 0건을 확인했다.
- Bridge 소스와 충돌 제안본은 활성 경로에서 제거했지만 백업에서 복구할 수 있다. 현재 대화에 이미 주입된 도구 목록은 앱 재시작 전까지 표시될 수 있으나 등록과 서버 프로세스는 제거됐다.
- 미조사 호스트·다른 사용자·별도 앱 설정까지 모두 정리됐다는 주장은 하지 않는다. 현재 사용자 주요 3도구 설정 기준이다.
- 앱 내 별도 설치 플러그인은 이번 로컬 MCP 등록과 구별된다. 관련 없는 커넥터·플러그인을 일괄 제거하지 않았다.
