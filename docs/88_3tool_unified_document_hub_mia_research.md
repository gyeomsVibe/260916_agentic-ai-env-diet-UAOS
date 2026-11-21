# U233: MIA 11단계 전략 연구 — 3대 도구 통합 문서 허브 (Unified Document Hub) 조사 및 구체적 구현 방안

- 작성일시: 2026-10-25 11:18 (KST)
- 카테고리: 아키텍처 설계 / 문서 관리 표준 (MIA 11-Stage Framework)
- 작성도구: Antigravity (User Desk `24e6eeb5-5daa-48ab-bc69-75b13027cfbf`)

> **핵심 질문에 대한 결론**:
> 1. **"UAOS 시스템 프로젝트 로컬저장소에 각자 저장소에 저장해야 하는가?"** → **아닙니다 (No).** 코드 수정은 충돌 방지를 위해 각 도구의 `git worktree`에서 격리해야 하지만, **사용자가 열람하는 문서(프로젝트 문서 + 프로세스 작업 문서)는 반드시 메인 프로젝트 루트(`shared_desk(project)/docs/`) 단 한 곳**에 모아 저장·색인해야 합니다.
> 2. **"3대 도구가 프로젝트·프로세스 작업 중 생성하는 문서를 한 곳에서 처리할 수 있는가?"** → **가능합니다 (Yes).** 이미 UAOS에 구축된 `shared_desk()`(공유 데스크 해석기)와 `docs_manager.py`(`U222`)를 확장하면, 어느 도구가 어느 worktree/세션에서 문서를 만들든 **`<프로젝트 루트>/docs/`** 및 **`<프로젝트 루트>/docs/00_DOCUMENT_HUB.html`** 한 곳에서 실시간 통합 조회할 수 있습니다.

---

## Stage 0. 사전 근거자료조사 (Web Deep Research & 코드 전수 실측)

### 0.1 1차 출처 웹 리서치 근거
1. **Git Worktree 공식 명세 및 Docs-as-Code 중앙 허브 아키텍처**:
   - [Git Documentation — `git-worktree`](https://git-scm.com/docs/git-worktree): linked worktree는 `$GIT_COMMON_DIR`을 공유하면서 작업 트리만 분리함. 따라서 공유 상태(사서함·출석부·통합 문서 허브)는 `$GIT_COMMON_DIR`의 부모인 메인 체크아웃(`shared_desk`)에 두어야 worktree 간 파편화가 발생하지 않음.
2. **Diátaxis 프레임워크 및 MADR (Markdown Architectural Decision Records)**:
   - [Diátaxis Documentation Framework](https://diataxis.fr/) 및 [MADR GitHub Repository](https://github.com/adr/madr): 엔지니어링 문서는 **영구 프로젝트 문서(Tutorials / How-To / Reference / Explanation)**와 **의사결정·프로세스 기록(ADR / Card Receipts)**으로 구분하되, **단일 마스터 인덱스(`00_DOCUMENT_INDEX.md` + `00_DOCUMENT_HUB.html`)**에서 함께 탐색되어야 함.
3. **UAOS 저장소 실측 증거 (`v7_harness/docs_manager.py`, `v7_harness/cli.py`)**:
   - 현재 3대 도구가 문서를 저장하는 위치가 **4곳으로 파편화**되어 있음:

| 도구 / 구분 | 현재 실제 저장 경로 (파편화 현상) | 사용자가 겪는 문제 |
|---|---|---|
| **Codex** | `C:\Users\Kimyoongyeom\.codex\worktrees\170e\...\.work\<card>\` | 숨김 폴더(`.codex`) 깊숙이 있어 탐색기에서 찾기 불가능 |
| **Claude Code** | `<project>\.claude\worktrees\<name>\.work\<desk>\` | 워크트리별 임시 폴더에 산재되어 어느 파일이 최신인지 알 수 없음 |
| **Antigravity** | `C:\Users\Kimyoongyeom\.gemini\antigravity\brain\<conv-id>\` | 앱 내부 UUID 폴더에 저장되어 프로젝트 폴더(`docs/`)에서 보이지 않음 |
| **UAOS CLI (`docs_manager.py`)** | `Path(args.project) / "docs"` (`cli.py` L2502) | `_DESK_COMMANDS`에 `docs`가 빠져 있어 worktree에서 실행하면 **메인 `docs/`가 아닌 worktree 내부 `docs/`**에 따로 저장됨 |

---

## Stage 1 ~ 2. 기획 (Frame) 및 스코프 검증 게이트 (Gate 1~2: PASS)

- **Problem Statement**: 3대 도구가 프로젝트 문서와 프로세스 문서(카드 매뉴얼, 감사 영수증, 벤치마크, 완료 보고)를 각자의 worktree·AppData·`.work/`에 흩어 저장하여 사용자가 로컬 저장소 어디에 무엇이 있는지 알 수 없음.
- **Measurable Success Signal (정량적 성공 지표)**:
  1. 3대 도구 중 어느 도구가 worktree 안에서 `uaos docs new|publish|sync`를 호출하든 **100% 메인 프로젝트 루트의 `docs/`(`shared_desk(project) / "docs"`)**에 저장됨.
  2. 프로젝트 문서(`docs/NN_<slug>.{md,html}`)와 프로세스 문서(`docs/process/<CARD>_<kind>.{md,html}`)가 모두 **`docs/00_DOCUMENT_INDEX.md`** 및 브라우저용 대시보드 **`docs/00_DOCUMENT_HUB.html`** 한 곳에서 검색·열람됨.
  3. 2개 이상의 실제 OS 프로세스가 동시에 문서를 등록해도 번호 충돌·행 유실이 0건(`_exclusive` 파일 잠금).
- **Non-Goals (비목표)**:
  - `pilot run` 중 코드 스테이징 샌드박스(`.work/pilot/stage/`)나 원본 감시(`QUIET_LOCK`) 격리 규칙은 약화하지 않음(코드 격리는 유지하고, **문서 발행·색인만 공유 루트로 일원화**).

---

## Stage 3 ~ 4. 큰계획 (Master Plan — 3대 대안 4대 렌즈 비교 및 Gate 3~4: Go)

| 평가 렌즈 | 대안 A: 각 도구 저장소/워크트리 개별 저장 (현행) | 대안 B: Git 커밋 시점에만 수동 병합 | **대안 C (채택 — Go): `shared_desk` 기반 실시간 통합 문서 허브 (`docs/` + `docs/process/` + `00_DOCUMENT_HUB.html`)** |
|---|---|---|---|
| **Value (가치성)** | 낮음 (사용자가 4개 경로를 뒤져야 함) | 중간 (PR 병합 전에는 진행 중 문서를 볼 수 없음) | **최상** (작업 중 생성되는 기획서·감사영수증·완료보고서·HTML까지 즉시 `<project>/docs/` 한 곳에서 확인) |
| **Feasibility (실현성)** | 높음 | 중간 | **높음** (`v7_harness/coord/presence.py`의 `shared_desk()`와 `docs_manager.py`의 `_serialized_doc_write` 잠금을 그대로 재사용) |
| **Viability (지속성)** | 낮음 (워크트리 정리 시 문서 유실 위험) | 중간 (충돌 빈발) | **최상** (단일 잠금 파일 `.work/docs_manager.lock`으로 3대 도구 동시 쓰기 직렬화 보장) |
| **Risk / Rollback** | 문서 실종 지속 | 브랜치 오염 | **낮음** (`pilot` 원본 감시 대상에서 `docs/process/` 및 `00_DOCUMENT_HUB.html`을 분리하거나 `shared_desk` 경유로 안전 기록) |

---

## Stage 5 ~ 8. 세부계획 및 구현계획 (구체적 아키텍처 및 모듈별 명세)

### 1. 디렉터리 단일화 구조 (`<프로젝트 루트>/docs/`)
사용자는 오직 **`<프로젝트 루트>/docs/`** 폴더 하나만 열면 됩니다:
- **`docs/00_DOCUMENT_HUB.html`**: 브라우저에서 더블클릭으로 여는 대화형 통합 문서 포털 (탭: `전체` / `프로젝트 설계·보고서(01~88+)` / `프로세스 카드 기록(U01~U233)` / `HTML 대시보드`, 키워드 실시간 필터, 작성 도구 뱃지 표시).
- **`docs/00_DOCUMENT_INDEX.md`**: GitHub 및 마크다운 뷰어용 전체 연대기 색인표.
- **`docs/NN_<slug>.md` 및 `docs/NN_<slug>.html`**: 프로젝트 영구 문서 (자동 순번 `87_`, `88_`, ... 부여, `.md`와 `.html` 모두 지원).
- **`docs/process/<CARD>/`**: 프로세스 진행 중 3대 도구가 생성하는 작업 문서의 단일 미러링 저장소:
  - `manual.md` (`.coord/tasks/<CARD>-manual.md` 생성 시 자동 복사)
  - `review_<tool>.md` (Codex/Claude/Antigravity 감사 영수증 발행 시 자동 복사)
  - `result.md` (`.coord/results/<CARD>.md` 및 `uaos card done` 실행 시 자동 복사)

### 2. 코드 수준 구체적 수정 명세 (3개 파일, ~60줄)

1. **`v7_harness/docs_manager.py` 확장**:
   - **공유 루트 강제 해석**: 모든 진입 함수(`ensure_docs_dir`, `register_new_doc`, `sync_doc_index`, `publish_process_doc`)에서 `from .coord.presence import shared_desk; root = shared_desk(Path(project_root).resolve())`를 호출해 어느 worktree에서 실행하든 메인 프로젝트의 `docs/`를 가리키도록 고정.
   - **`.html` 및 외부 파일 발행(`--ext html`, `--from-file`) 지원**:
     - `register_new_doc(..., ext: str = "md", source_file: Path | None = None)` 추가: Antigravity가 `brain/`에 만든 `.md`/`.html`이나 Claude/Codex가 `.work/`에 만든 보고서를 `uaos docs publish --from-file <경로> --title "<제목>"` 한 줄로 번호 부여 후 `docs/NN_<slug>.{md,html}`에 즉시 복사·등재.
     - `extract_doc_title()`이 `.html` 파일의 `<title>` 또는 `<h1>` 태그도 자동 추출하도록 개선.
   - **프로세스 문서 자동 수집 (`sync_process_docs(root)`)**:
     - `.coord/tasks/*.md`, `.coord/results/*.md`, `.coord/reviews/*`, `.work/*-review/*.md`를 스캔하여 `docs/process/<CARD>/` 아래에 정리하고 `docs/00_DOCUMENT_HUB.html`의 **프로세스 문서 탭**에 자동 색인.
   - **`render_doc_hub_html(root)` 추가**:
     - `sync_doc_index(root)` 실행 시 `docs/00_DOCUMENT_INDEX.md`뿐만 아니라 검색·필터·클릭 열람이 가능한 `docs/00_DOCUMENT_HUB.html`을 항상 함께 생성.

2. **`v7_harness/cli.py` CLI 서브커맨드 보강**:
   - `uaos docs new "<제목>" [--slug ...] [--ext md|html] [--from-file <경로>] [--tool codex|claude|antigravity]`
   - `uaos docs publish --card <U##> --kind <manual|review|result|report> --from-file <경로> --title "<제목>"`
   - `uaos docs sync`: 프로젝트 문서(`01_`~) + 프로세스 문서(`.coord/tasks`, `.coord/results`, `.coord/reviews`) 전수 스캔 → `docs/00_DOCUMENT_INDEX.md` 및 `docs/00_DOCUMENT_HUB.html` 동시 재생성.

3. **`v7_harness/card_pipeline.py` 자동 훅 연동**:
   - `card new`, `card audit`, `card done` 실행 시점에 `docs_manager.sync_doc_index(desk)`를 자동 호출하여, 별도 수동 명령 없이도 카드 생명주기마다 `docs/00_DOCUMENT_INDEX.md`와 `docs/00_DOCUMENT_HUB.html`이 최신 상태로 유지됨.

### 4. UAOS-RSI 운영시스템 전역 기본 규칙 (Universal by Default) 보장 방안

1. **프로젝트 경로 하드코딩 배제 (동적 감지)**:
   - `docs_manager.py`는 특정 저장소 경로를 하드코딩하지 않고, `shared_desk(project_root)`를 통해 임의의 Git 프로젝트 루트를 동적으로 판별합니다.
2. **`uaos coord init` 스캐폴딩 기본 탑재**:
   - 불특정 폴더에서 새 프로젝트 개시 시 생성되는 기본 스캐폴딩(`.coord/`, `.coord/tasks`, `.coord/mailbox`, `.work`, `docs/`)에 **`docs/00_DOCUMENT_HUB.html`** 및 **`docs/process/`**가 기본 생성됩니다.
3. **`uaos_everywhere` 3대 도구 전역 규칙 동기화**:
   - `uaos_everywhere/uaos_global_rule_block.md` 5번 문단에 "프로젝트 문서(`docs/NN_*`) 및 프로세스 작업문서(`docs/process/<CARD>/`)의 단일 허브 집약 및 `00_DOCUMENT_HUB.html` 포털 제공"을 운영체제 전역 기본 규칙으로 명시합니다.
   - `python uaos_everywhere/install_uaos_everywhere.py --apply`를 통해 Codex(`AGENTS.md`), Claude(`CLAUDE.md`), Antigravity(`GEMINI.md`) 및 전역 설정에 배포되어, 어느 프로젝트에서든 세 도구가 문서를 한 곳에만 남기도록 강제됩니다.
4. **코어 런타임(`~/.uaos/runtime/`) 상시 가용**:
   - `~/.uaos/runtime/`에 배포되어 모든 프로젝트와 세션에서 `python "$HOME/.uaos/uaos.py" docs ...` 명령으로 0-token 즉시 실행됩니다.
