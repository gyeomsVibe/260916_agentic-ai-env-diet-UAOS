# 36. 5대 비유 보강 구현 기록 — U32~U35 (자기 비판 포함)

- 작업 ID: `U32a`·`U32b`·`U33`·`U34`·`U35` · 작성: Claude Code(클라우드 세션, Linux·Python 3.11, Codex 부재 중 사용자 직접 지시로 부지휘자 대행)
- 기간: 2026-09-25 KST · 브랜치 `claude/cool-hamilton-yj6wwo` · PR: gyeomsVibe/260916_agentic-ai-env-diet#1
- 선행 문서: [docs/35 감사](35_five-metaphors-realization-audit_2026-09-25.md) → 이 문서(구현 기록) → [docs/37 표준 프로세스·하네스](37_standard-process-and-worker-harness.md)
- 판정권: 이 문서의 모든 변경은 **Codex 복귀 재검토 대상**이다. 작성자(Claude)는 유일한 검증자가 아니다.

---

## 0. 한눈에 보기

| 비유 | docs/35 판정 | 이번 구현 뒤 | 핵심 변경 |
|---|---|---|---|
| 1. 전자계산기 | 부분 | **대폭 보강** | 계약 매뉴얼 검사·강제, 받아쓰기는 모델 없이 적용(0토큰), 요청 밖 삭제·문법 오류 차단, 구조화 출력 스키마·seed 고정 |
| 2. 유선 전화기 | 대체로 | 변화 없음(승인 대기) | 유료 예약 도구 차단 설정을 **비활성 제안 파일**로 준비 — 권한 변경이라 사용자 승인 필요 |
| 3. 음성사서함 | 부분 | **실현** | 유실 경로 전부 봉쇄: 임대 시각, 성공 후에만 삭제, ID당 내용 하나, 손상 파일 격리 |
| 4. 24/7 교환원 | 미흡 | **부분 실현** | 점검 결함 수정, 고착 복구·읽기 전용 점검 연결, 출석부 기반 **실제 벨**(`codex queue`). 상주 서비스 등록은 승인 대기 |
| 5. 비둘기 퇴출 | 부분 | **대폭 보강** | 도구 출석부(만료 포함), 파일럿 결과 스트림 자동 보고 기본 켜짐, 음성사서함 확인·처리 명령 |

재현 스크립트 `python .coord/runs/U31/metaphor_probe.py`의 결과는 P1~P5 모두 **CONFIRMED → NOT_REPRODUCED**로 바뀌었습니다. 새 하네스는 이 클라우드 세션에서 **실제 파일럿 1건(U35-P1)을 끝까지 실행해 승인 반영까지 마쳤고**, 그 과정에서 숨은 결함 1건을 더 찾아 고쳤습니다(§4).

---

## 1. 먼저, 제 분석의 잘못 (자기 비판)

작성자가 스스로의 오류를 지우지 않고 남겨야 다음 판정자가 같은 함정에 빠지지 않습니다.

| # | 앞선 주장(docs/35 또는 첫 분석) | 실제 | 원인 분류 |
|---|---|---|---|
| 1 | "100% 무손실" 문구를 "최소 1회 배달"로 **낮추자** | 사용자 의도는 유실 0이다. "최소 1회 배달 + 같은 ID 중복 제거"는 유실 0을 **참으로 만드는 방법**이지 목표를 낮출 이유가 아니다. 목표는 유지하고 구현을 올렸다 | 의도 오독 |
| 2 | 파일럿 결과의 스트림 자동 보고(P2)가 **없다** | `record_pilot_in_stream`이 U15부터 있었다. 다만 기본값이 꺼져 있고(`--coord-log`), 어느 문서에도 안내되지 않았으며, 과제 ID가 항상 "pilot"으로 기록됐다 | 코드 탐색 누락 |
| 3 | 스트림 기록은 하루치 21건뿐이라 운영이 거의 없다 | git에 올라간 파일 하나만 본 결론이다. 이후 스트림은 `.gitignore` 대상이라 사용자 PC에만 있다 | 표본 한계 과대 해석 |
| 4 | nack 유실(P3)은 중대 결함 | API 수준에서는 맞지만, 현재 호출부(같은 ID는 같은 내용)에서는 드문 경로다. 더 현실적인 유실은 Windows 파일 잠금 등 `OSError`에서 `finally`가 원본을 지우는 경로였다(코드 판독, Windows 미실행) | 심각도 과대 |
| 5 | 계산기 "받아쓰기" 결론 | 표본은 P08·P09 두 건뿐이다. 이번에 `worker: apply` 기록과 경고로 앞으로의 비율을 **측정 가능**하게 했다 | 표본 부족 |
| 6 | 관문 예외율 7/9 | 그중 2건은 제 커밋이었다. 이번 세션의 코드 커밋도 모두 `Calculator-Exempt`다(이 컨테이너에 Ollama 없음). 관문이 실제 파일럿 폴더를 인식하게 고쳐, 앞으로의 정당한 파일럿 결과는 예외 없이 통과한다 | 이해 상충 미표시 |

---

## 2. 무엇을 바꿨나 — 비유별

### 2-1. 음성사서함 (U32a, 커밋 `353fa4c`)

**목표:** 보고가 디스크에 남은 뒤에는 누군가 "처리함(ack)"을 찍기 전까지 절대 사라지지 않는다.

| 유실·오보 경로 | 이전 | 이후 |
|---|---|---|
| 꺼낸 직후 "고착"으로 오판 | 이름 변경은 발행 시각을 유지 → 60초 넘은 메시지는 꺼내자마자 복구 대상 | 꺼낼 때 시각을 갱신(임대 시작). 긴 작업은 `renew()` |
| 거짓 ACK | 꺼낸 파일이 이미 없어도 ack 경로를 "성공"으로 반환 | 예외 `claim lost` |
| nack·복구 중 유실 | `finally`에서 무조건 원본 삭제, POSIX `rename`은 덮어쓰기 | 링크가 **성공한 뒤에만** 원본 삭제. 실패하면 남겨 두고 다음 임대 만료 때 재시도 |
| 같은 ID 다른 내용 | inbox만 검사 | inbox·claimed·ack 전체에서 "한 ID = 한 내용". 이미 처리된 ID의 같은 내용 재발행은 무시(중복 배달 없음) |
| 읽을 수 없는 파일 | `claimed/`에 영원히 숨음 | `bad/`로 격리, 브리핑에 표시 |
| 정전 | 파일만 fsync | POSIX에서 디렉터리도 fsync(Windows는 NTFS 저널) |
| 줄바꿈 ID | `^…$`가 `"abc\n"` 허용 | `fullmatch` |

검증: `tests/test_u32_mailbox_lossless.py` 14개(수정 전 12개 실패), 기존 U23 22개 유지.

### 2-2. 24/7 교환원 (U32b, 커밋 `73ce31d`)

| 결함(재현) | 수정 |
|---|---|
| 미정리 작업 점검이 **항상 빈 결과**(P4). pilot은 `NEEDS_RECONCILIATION`을 `error_class`에 쓰는데 감시관은 `verdict_hint`를 봤다 | pilot의 `next_action` 조건과 같은 판정(`state=FAILED` + `TIMEOUT`/`NEEDS_RECONCILIATION` 또는 `effect_state=UNKNOWN`). `pilot reconcile`이 `ABANDONED`로 바꾸면 경보가 자동으로 꺼진다 |
| `.coord/pilot` 한 곳만 점검 | `.coord/pilot`·`.coord`·`.work/*` 모두(`v7_harness/pilot_dirs.py`) |
| 처리한 보고가 다음 주기에 또 도착(P1) | 커서 동기화 + 우편함의 ID 규칙 |
| 점검하려고 메시지를 꺼냈다 되돌림(소비자 방해) | `peek()` 읽기 전용 |
| 고착 복구 함수가 운영 경로에서 불리지 않음 | 매 주기 `recover_stale_claims(600초)` |
| 누가 꺼낸 기상 메시지를 또 발행 | `has_message()`가 claimed까지 확인 |
| **벨이 없음**(P5) | `ring_bell`: Codex 출석이 ACTIVE(만료 전)일 때만 `codex queue`로 1건. 같은 대기 목록이면 다시 울리지 않음(속도 제한·하루 한도는 기존 `notify` 재사용). 부재·UNKNOWN이면 우편함에 보관했다가 복귀 후 울림. `coord sentinel --ring`(기본 꺼짐) |
| 루프가 한 주기 오류로 죽음 | 오류를 한 줄 JSON으로 남기고 계속 |

**출석부(presence):** `.coord/presence/<도구>.json`에 `{상태, 관측 시각, 만료}`. 만료가 지나면 스스로 UNKNOWN이 된다. `is_codex_absent`는 신선한 출석을 PLAN의 수동 선언보다 우선한다. 명령: `coord presence --tool codex --state ACTIVE --ttl 3600`. 음성사서함은 `coord inbox`로 보고 `coord ack --id <ID>`로 처리 표시한다.

**감시관은 Ollama를 부르지 않는다.** 결정적 규칙만 쓰므로 0토큰이고 판정권 배제 원칙과도 맞다. docs/24·docs/34의 "올라마 기반 교환원" 표현은 이 사실과 다르며, 정정 작업을 U35-O2로 발행했다(§5).

검증: `tests/test_u32_sentinel_bell.py` 16개. 가짜 Codex 세션 기록과 가짜 실행기로 `codex queue --thread <세션> --message "[DATA] from=sentinel …"` 호출 1회를 확인했다.

### 2-3. 비둘기 퇴출 (U33, 커밋 `8cc0a70`)

- 파일럿 결과의 스트림 자동 보고를 **기본으로 켰다**. `--source` 프로젝트에 `.coord/PLAN.md`가 있을 때만 쓰고, 끄려면 `--no-coord-log`를 붙인다.
- 기록 주체는 호출 도구의 환경변수로 자동 식별한다(`CLAUDECODE`·`CODEX_*`·`ANTIGRAVITY*`). 식별이 안 되는 일반 터미널에서는 추측하지 않고 기록하지 않는다(`--coord-actor`로 지정 가능).
- 과제 ID를 정확히 기록하고, 절대 경로 참조 때문에 사건 전체가 버려지던 문제를 고쳤다.
- 테스트 격리: `tests/__init__.py`가 `UAOS_STREAM_AUTOLOG=0`을 설정한다. CLI 테스트 5개가 `--source .`로 실제 저장소를 쓰기 때문이다.

검증: `tests/test_u33_pilot_autolog_default.py` 7개(수정 전 코드에서 실패). 전체 회귀 전후 실제 스트림 해시 불변.

### 2-4. 계산기·작업자 정밀 하네스 (U34, 커밋 `d5972cb`·`a45b1b9`)

사용자 요청 2~5번(거짓 없는 정밀 작업, 최적화된 매뉴얼, 하네스 환경, 토큰 예산)을 코드로 옮긴 부분입니다.

1. **계약 매뉴얼**(`v7_harness/manual.py`, `pilot manual new|lint`): 매뉴얼 첫머리의 ```contract 블록을 기계가 검사한다. 필수 칸, 입력 SHA-256 고정, 허용 범위, 판정자 ≠ 작업자·Ollama, 모호어, 로컬 구체성 80점, cascade의 원격 예산, apply의 블록 존재, 관련 테스트 누락 경고를 본다. 형식과 작성법은 docs/37 §4.
2. **매뉴얼이 실행을 지배**(`pilot run --manual`): 검사에 실패하면 실행을 거부한다(`MANUAL_INVALID`, exit 2). 통과하면 파일 **내용 전체**가 작업자 입력이 되고(경로만 넘기는 실수 불가), 계약의 작업자·인수 명령·허용 범위·시간 상한이 적용된다. 승인은 계약의 판정자만 할 수 있고(`APPROVER_NOT_JUDGE`), cascade 승격은 `cost_gate`(WITHIN/EXCEEDED)로 예산과 대조한다.
3. **허용 범위 강제**: 반영 단계는 원래 `allowed_scopes`를 지원했지만 파일럿이 넘기지 않았다. 이제 범위 밖 변경은 `REWORK`/`SCOPE_VIOLATION`으로 반영하지 않는다(환경 장애가 아니므로 BLOCKED·P1 벨이 아님).
4. **출력 가드**(`ollama_worker._apply`): 모든 블록을 검증한 뒤에만 쓴다(원자적). 문법이 깨진 .py(`SYNTAX_ERROR`)와 **요청하지 않은 함수·클래스 삭제**(`UNREQUESTED_DELETION`)를 거부한다. 삭제 요청은 같은 줄의 이름 + 삭제 동사 + 부정어 없음으로만 인정한다("지우지 말 것"은 요청이 아니다).
5. **받아쓰기는 모델 없이**(`--worker apply`): 지시문에 정확한 코드 블록이 있으면 결정적으로 적용한다. 토큰 0, 환각 0이다. `--worker auto`도 이런 지시문을 apply로 보낸다. 장부에는 `worker: apply`, `model: deterministic`으로 남아 받아쓰기 비율을 잴 수 있다.
6. **구조화 출력·재현성**: 증거 추출(`olla_evidence`)은 Ollama의 `format`에 JSON 스키마를 넘긴다. U29에서 난 코드 펜스·여분 키 실패를 생성 단계에서 막는다(값의 진위는 여전히 원문 부분 문자열 검사로 판정). 로컬 작업자는 `seed`를 고정해 같은 입력에 같은 출력이 나오므로 실패를 재현할 수 있다.
7. **관문 경로**: 계산기 관문이 모든 파일럿 폴더를 인식한다. P08·P09처럼 `.work/pilot_*`에서 반영된 정당한 결과는 예외 줄 없이 통과한다.

검증: `tests/test_u34_precision_harness.py` 30개(수정 전 코드에서 25개 실패). 고정 인수 `test_u30_olla_evidence.py`는 SHA-256 `B620…EE2` 그대로다.

### 2-5. POSIX 위생 (U35, 커밋 `8a0c11f`) — 실제 실행이 찾은 결함

새 하네스로 U35-P1을 실제로 돌리자 `pilot run --source .`가 트레이스백으로 멈췄습니다. 저장소 루트에 **브로커 소켓 19개**(`coordd-root-….sock`)가 있었기 때문입니다.

- 원인 1: POSIX 브로커 주소가 `os.getenv("TEMP", ".")` 기준이었다. Linux에는 보통 `TEMP`가 없어 현재 폴더에 소켓이 생겼고, 비정상 종료 시 남았다(B75와 같은 뿌리) → `tempfile.gettempdir()`
- 원인 2: 매니페스트가 소켓·FIFO를 일반 파일처럼 열었다. 소켓은 ENXIO, FIFO는 **무한 대기** → 일반 파일만 포함

검증: `tests/test_u35_posix_hygiene.py` 3개. 수정 전 코드에서 소켓 테스트는 실패, FIFO 테스트는 멈춰서 60초 제한에 강제 종료됐다.

---

## 3. 검증 요약

| 항목 | 명령 | 결과(Linux, 2026-09-25) |
|---|---|---|
| 신규 테스트 | `python -m unittest tests.test_u32_mailbox_lossless tests.test_u32_sentinel_bell tests.test_u33_pilot_autolog_default tests.test_u34_precision_harness tests.test_u35_posix_hygiene` | 70개 OK |
| 전체 회귀 | `python -m unittest discover -s tests -t .` | 663개(세션 시작 592 + 이번 71) 중 실패 1(B75), 건너뜀 5 |
| 비유 재현 | `python .coord/runs/U31/metaphor_probe.py` | P1~P5 모두 NOT_REPRODUCED |
| 오염 | 회귀 전후 `.coord/stream` 해시·`.coord/usage` | 불변·미생성 |
| Windows 회귀(2026-09-25 Codex 재검토) | `python .coord/runs/run_regression.py` | 최초 663개 중 오류 1·실패 1(exit 1); U35-W1/W2 수정 후 **663개 OK(exit 0, 94.423초)**. 로그 `.work/logs/regression-20260925T054056.log` |

---

## 4. U35-P1 — 새 하네스의 실제 1회 실행

| 단계 | 결과 |
|---|---|
| 매뉴얼 생성 | `pilot manual new` → 입력 `README.md` SHA-256 고정. EDIT 블록 추가 전에는 `NO_BLOCKS_FOR_APPLY`로 거부 |
| 검사 | `pilot manual lint` → 오류 0·경고 0 |
| 1차 실행 | 처음에는 소켓 결함으로 트레이스백 → U35 수정 뒤 `SUCCEEDED`/`PASS`/`DRY_RUN_PASSED`, 변경 `README.md` 1개, 토큰 0 |
| 판정 | 격리 사본과 원본의 diff가 매뉴얼의 세 EDIT와 정확히 일치함을 직접 대조 |
| 승인 | 판정자 Claude가 번들 `e9fcb89b…4d05`로 `APPLIED` |
| 장부(U27) | `{"work_id":"U35-P1","worker":"apply","model":"deterministic","input_tokens":0,"output_tokens":0,"outcome":"PASS","rsi_eligible":false,"exclusion_reason":"PENDING_INDEPENDENT_VERIFICATION"}` |
| 스트림(U33) | `20260924T2014-claude-0001` RUN "…DRY_RUN_PASSED, 변경 1개", `20260924T2015-claude-0001` RUN "…APPLIED, 변경 1개" |

관찰된 빈 곳: 승인 실행은 사용량 장부에 행을 남기지 않는다(승인 재생 경로가 기록 전에 반환). BACKLOG B78로 등록했다.

정정: U35-P1이 README에 넣은 "인수 테스트 660개"는 매뉴얼 발행 시점에 셌던 값인데, 그 뒤 U34 스키마 테스트와 U35 위생 테스트가 추가되고 다시 세어 보니 663개였다. 이 한 줄은 직접 편집으로 663으로 고쳤다. 교훈: **매뉴얼에 적는 수치는 인수 명령이 그 자리에서 세게 해야** 한다(이번 인수는 '660'이라는 문자열만 확인했다).

장부 파일 `.coord/usage/runs.jsonl`은 커밋하지 않았다. 이 파일은 지금까지 git에 올라간 적이 없는 사용자 PC 전용 장부라서, 올리면 사용자 PC의 기존 파일과 충돌해 `git pull`이 멈춘다. 위 행은 이 문서를 영수증으로 삼는다.

---

## 5. U35 실행 계획 — Ollama·Antigravity 역할과 매뉴얼 (요청 7번)

이 컨테이너에는 `ollama`·`agy`·`codex`가 설치돼 있지 않아 실행하지 못했습니다(요청에 따라 **패스**). 매뉴얼 세 개를 발행했고, 이 세션에서 모두 `pilot manual lint`를 통과했습니다. 사용자 PC에서 아래 명령을 그대로 실행하면 됩니다.

| ID | 역할 | 작업자 | 목표 | 판정자 | 매뉴얼 |
|---|---|---|---|---|---|
| U35-O1 | 계산기(추출) | Ollama `olla_evidence` | 이 문서에서 Codex 점검표용 사실 5개를 **원문 그대로** 뽑기(스키마 강제·부분 문자열 검증) | codex | `.coord/tasks/U35-O1-ollama-evidence-manual.md` |
| U35-O2 | 계산기(좁은 편집) | Ollama `--worker local` | docs/24 그림의 "(Ollama 기반 교환원)"을 사실대로 정정 | codex | `.coord/tasks/U35-O2-ollama-docs24-manual.md` |
| U35-A1 | 범위 제한 원격 작업자 | Antigravity `--worker agy` | B75: POSIX 브로커 재기동 시 남은 소켓을 **접속 시험 후** 안전하게 정리 | codex | `.coord/tasks/U35-A1-antigravity-b75-manual.md` |

```bash
# 공통 준비: 출석 표시(Codex가 판정한다)
python -m v7_harness.cli coord presence --tool codex --state ACTIVE --ttl 3600

# U35-O1 (Ollama 추출, 파일 수정 없음) — 결과는 .work/u35/o1.json
python -m v7_harness.cli pilot manual lint --manual .coord/tasks/U35-O1-ollama-evidence-manual.md --source .
python -m v7_harness.olla_evidence --manual .coord/tasks/U35-O1-ollama-evidence-manual.md \
  --evidence docs/36_metaphor-realization-implementation-record_2026-09-25.md \
  --sha256 <매뉴얼 inputs의 SHA-256> --keys mailbox_tests,sentinel_tests,harness_tests,full_suite,u35_bundle \
  --prompt "Copy the five values exactly as they appear." > .work/u35/o1.json

# U35-O2 (Ollama 로컬 편집)
python -m v7_harness.cli pilot run --task U35-O2 --source . --work-dir .work/pilot_U35O2 \
  --manual .coord/tasks/U35-O2-ollama-docs24-manual.md

# U35-A1 (Antigravity, 원격 예산 150k 토큰)
python -m v7_harness.cli pilot run --task U35-A1 --source . --work-dir .work/pilot_U35A1 \
  --manual .coord/tasks/U35-A1-antigravity-b75-manual.md
# 판정은 Codex: summary.json 확인 → Linux에서도 인수 재실행 → --approve <bundle_id>
```

### Windows 실행 결과(2026-09-25)

- `U35-O2`의 원래 입력 SHA-256은 Git LF blob `d94f61af…`이며 Windows 체크아웃(`core.autocrlf=true`)의 실제 SHA-256은 `07c08ff8…`였다. 원래 매뉴얼은 `INPUT_HASH_MISMATCH`로 거부됐다. 허용 파일·인수·판정자를 바꾸지 않고 Windows 바이트만 고정한 `U35-O2-ollama-docs24-windows-manual.md`를 사전 발행해 lint 오류 0을 확인했다.
- Ollama 로컬 파일럿 `U35-O2`는 3,955 입력/56 출력 로컬 토큰으로 한 줄만 바꿨다. Codex가 격리본 diff와 169줄 인수를 직접 검사했고 번들 `49fea0dd…f1508b`를 `APPLIED`했다. 유료 API 토큰 0은 로컬 계산 비용 0이나 계정 절감 실측을 뜻하지 않는다.
- Windows 회귀의 두 결함은 서로 다른 고정 인수로 진단했다. U35-W1은 출석 시각 변환을 UTC epoch+timedelta로 바꿨고, U35-W2는 테스트가 임시 파일의 실제 바이트 해시를 제거하도록 고쳤다. 둘 다 결정적 `--worker apply`(모델 토큰 0)·독립 diff·단독 인수 통과 후 반영했다. 전체 663개 회귀도 통과했다. O2 Windows 매뉴얼은 PR에, W1/W2 원본 매뉴얼과 실행 로그는 로컬 `.work/`에 보존한다. `.coord/usage/runs.jsonl` 원시는 커밋하지 않는다.

---

## 6. 사용자 승인이 필요한 활성화 (적용하지 않고 준비만 함)

| 항목 | 준비물 | 이유 |
|---|---|---|
| 유료 예약 도구 차단(비유 2) | `tool-configs/claude/settings.uaos-proposed.json`의 `permissions.deny` | 도구 권한 변경 |
| 출석부 자동 기록 훅(비유 5) | 같은 파일의 `SessionStart`·`UserPromptSubmit`·`SessionEnd` 훅 | 도구 설정 변경. 승인 전에는 AGENTS.md 규칙("작업 시작 시 `coord presence`")으로 대신한다 |
| 24/7 상주(비유 4) | docs/37 §8의 `schtasks` 명령 | 시스템 설정 변경 |

---

## 7. 남은 위험과 다음 행동

- **Windows 재검증 완료, 환경별 잔여 위험**: Codex가 Windows 전체 회귀 663개를 통과시켰다(§3·§5). 이는 이 체크아웃의 결과이며 POSIX B75와 24/7 상주 동작까지 증명하지 않는다.
- **B75**: 소켓 위치는 고쳤지만 강제 종료 뒤 재기동 실패(EADDRINUSE)는 남았다. U35-A1로 발행했다.
- **B78**: 승인 실행이 장부에 남지 않는다.
- **효과 측정**: 계정 한도 절감은 여전히 `UNMEASURED`다. 측정 방법은 docs/37 §7에 있다(장부의 worker 분포, 받아쓰기 비율, 재작업률, 승격률, 10표본마다 검토).
- **작성자 = 검증자**: 이 세션의 모든 코드는 같은 작성자가 테스트했다. Codex 재검토 목록(PLAN)과 [Codex 인계 메모 72](claude-assist/72_codex-handoff-u32-u35_2026-09-25.md)를 따라 독립 판정이 필요하다.
