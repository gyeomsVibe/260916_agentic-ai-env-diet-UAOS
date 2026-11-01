# v6 전역 환경 정리 실행 기록

실행일: 2026-09-16 (Asia/Seoul)

## 결론

Codex는 계획·승인·최종 검토를 소유하고 Antigravity는 단계별 단일 실행자로 동작하도록 전역 규칙을 29줄씩으로 축약했다. 자동 메모리는 끄되 기존 기록은 보존했다. 전역 상시 도구는 실제 공통 경로에 필요한 것만 남기고, 중복 명령 스킬·복제 워크플로·Supabase/vibe/Snyk/NotebookLM MCP와 Ollama를 제거했다.

## 백업

- 위치: `C:\Users\Kimyoongyeom\.agent-config-backups\v6-20260916-01`
- `manifest.json`에 원본 경로와 SHA-256을 기록했다.
- 9개 설정/규칙 파일의 복사본 존재와 해시 일치를 수정 전에 확인했다.
- MCP 설정의 자격증명 값은 보고서나 프로젝트에 복사하지 않았다.

## 실제 변경

### 규칙·메모리·권한

- `C:\Users\Kimyoongyeom\.codex\AGENTS.md`: 50줄에서 29줄로 축약.
- `C:\Users\Kimyoongyeom\.gemini\GEMINI.md`: 49줄에서 29줄로 축약.
- 공통 핵심은 결과 우선, 비밀 보호, 행동별 승인, 변경 소유권, 검증 증거다.
- Codex 자동 메모리 생성·사용을 모두 비활성화했다. 기존 메모리 파일은 삭제하지 않았다.
- Codex의 강제 푸시와 PR 자동 병합 기본값을 껐다.
- 중복 브라우저 제어 플러그인 `browser`, `chrome`, `computer-use`를 끄고 `unified-computer-use`만 유지했다.
- 기본 브라우저 CDP 전체 접근을 `allow`에서 `ask`로 바꿨다.
- Antigravity 터미널 샌드박스는 켰고 원격 제어와 장황한 채팅은 껐다.
- 사용자 피드백에 따라 자율 실행 설정을 백업값으로 원복했다: `AUTO`, `TURBO`, 비작업공간 `ALLOW`, CLI `always-proceed`, 기존 자동 허용 43개. Codex가 위임한 범위의 일반 실행은 추가 승인 없이 수행한다.

### 완전 삭제한 중복 자산

- 별칭 래퍼 스킬 10종을 Codex와 Antigravity 양쪽에서 삭제: `alt3`, `critic`, `deepdive`, `eli10`, `expert`, `optimize`, `redteam`, `selfrefine`, `stepbystep`, `structured`.
- Antigravity에 복제돼 있던 전역 워크플로 3종의 두 사본, 총 6개 파일을 삭제.
- 독립 기능 스킬과 시스템/큐레이션 스킬은 상시 프롬프트가 아니라 필요 시 로딩되므로 무차별 삭제하지 않았다.

### MCP 결정

- **Supabase:** 전역 등록과 도구 스키마를 삭제. 원격 Supabase 프로젝트·데이터는 범위 밖이므로 변경하지 않았다.
- **vibe-clinic / vibe-diagnosis:** 전역 등록과 도구 스키마를 삭제. 진단은 버그가 실제 발생했을 때 `systematic-debugging` 같은 작업별 스킬로 실행한다.
- **Snyk:** 전역 MCP를 삭제. Snyk는 SAST, 오픈소스 의존성/라이선스, 컨테이너, IaC, SBOM 스캔을 제공해 기능 가치는 있지만 모든 작업에 상시 노출할 필요는 없다. 이 PC에는 별도 `snyk` 명령도 확인되지 않았다. 보안 감사 프로젝트에서만 다시 설치·등록한다.
- **NotebookLM:** 전역 MCP 등록·스키마, `notebooklm-mcp`/`nlm` 실행 파일, uv 도구 환경과 MCP 로그 캐시를 삭제. NotebookLM 제품 자체는 출처 기반 연구에 가치가 있으나 Gemini에서 NotebookLM 노트북을 직접 활용할 수 있어 별도 비공식 MCP는 중복이다.
- Codex에는 `node_repl`과 `antigravity-bridge`만 남겼다.

Snyk 기능 판단 근거: [Snyk Studio agentic integrations](https://docs.snyk.io/integrations/snyk-studio-agentic-integrations), [Snyk scan overview](https://docs.snyk.io/scan-with-snyk/overview). NotebookLM 판단 근거: [Google: Use NotebookLM notebooks in Gemini](https://support.google.com/notebooklm/answer/17003757).

### Ollama

- winget 등록 `Ollama.Ollama` 0.33.2를 공식 제거 절차로 삭제했다.
- Ollama 프로세스를 종료하고 앱 경로와 `C:\Users\Kimyoongyeom\.ollama\models`를 삭제했다.
- 제거 시점에 모델 디렉터리는 이미 파일 0개로 확인됐다. 따라서 과거 목록의 약 5.9GB와 달리 실행 직전 회수 용량은 측정할 수 없다.
- `.ollama` 아래의 신원 키 등 비밀 파일은 읽거나 삭제하지 않았다.

## 검증 증거

- JSON 5개와 Codex TOML 파싱: 성공, 종료 코드 0.
- 삭제 대상 5개(NotebookLM 실행 파일 2개, uv 환경, Ollama 모델·앱 경로): 모두 `Exists=false`.
- 중복 래퍼 스킬 잔존 디렉터리: 0.
- 복제 워크플로 잔존 파일: 0.
- 세 Antigravity MCP 설정의 활성 서버 이름: 없음.
- Ollama winget 재조회: 설치 패키지 없음. 관련 프로세스·서비스 없음.
- 활성 설정에서 삭제 대상 이름 재검색: 결과 없음(`rg` 종료 코드 1은 무일치를 뜻함).
- `agy health`: 이 CLI에 없는 서브커맨드라 종료 코드 2. 별도 `antigravity-bridge` 실행 파일도 PATH에 없어 브리지 런타임 건강 상태는 `UNKNOWN`; 설정 파싱과 등록 존재만 확인했다.

## 남은 위험과 운영 원칙

- 절감된 토큰·시간은 통제 비교 전까지 `UNMEASURED`다.
- 설정을 읽는 이미 열린 Codex/Antigravity 세션에는 재시작 후 완전히 반영될 수 있다.
- 플랫폼이 강제하는 승인과 파괴·배포·결제 같은 명시적 게이트는 `always-proceed`로 우회하지 않는다.
- Snyk·Supabase·NotebookLM은 제품 가치가 없어서가 아니라 전역 상시 통합의 효율이 낮아 제거했다. 실제 프로젝트의 완료 조건이 요구할 때만 프로젝트 범위로 설치한다.
- 다음부터는 한 단계·한 대화창·단일 소유자·검증 후 다음 단계라는 프로젝트 규칙을 따른다.
