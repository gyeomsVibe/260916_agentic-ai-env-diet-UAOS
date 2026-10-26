# 38. 자가개선(RSI)·자가치유의 맹점 조사와 증거 관문 구현 (U36, 2026-09-25)

- 상태: 구현·테스트 완료(Linux), 채택 판정은 Codex. 상위 정본은 [docs/31 증거 관문형 RSI](31_evidence-gated-rsi-for-uaos.md)이고, 이 문서는 그 정본을 **코드로 강제한 기록**이다.
- 코드는 `v7_harness/rsi.py`, CLI `rsi report|propose|gate|adopt|rollback`, 교환원 연결(`v7_harness/coord/sentinel.py`), 매뉴얼 검사 연결(`v7_harness/manual.py`), 장부 원인 기록(`v7_harness/pilot.py`)이다.
- 테스트는 `tests/test_u36_evidence_gated_rsi.py` 27개다.
- 용어는 처음 나올 때 한국어와 영어를 함께 적는다. 모르는 말은 [쉽게 읽는 용어집](쉽게_읽는_UAOS_진단과_해결_전과정/06_용어집_전문용어_병기.md)에서 찾는다.

> **개정 B83(2026-09-25, Codex 레드팀 → fail-closed)**: 같은 OS 계정 안에서는 작성자·검증자·판정자 이름이 모두 위장 가능해서, `rsi adopt`·`rsi rollback`은 이제 **항상 거부**하고 아무것도 쓰지 않는다(`UNAUTHENTICATED_ACTOR`). 대신 관문 증거와 제안 파일 내용을 출력한다. 채택과 되돌리기는 **PLAN 카드 → 검토된 커밋(사람의 GitHub 검토·병합)**으로만 한다. 아래 본문에서 `rsi adopt`·`rsi rollback`이 파일을 쓴다고 적힌 곳은 이 개정이 우선한다.

---

## 0. 한 쪽 요약

1. **자가개선(RSI, Recursive Self-Improvement)이 실제로 실패하는 방식은 대부분 같다.** 시스템이 문제를 푸는 대신 **채점기를 속인다**. 이를 보상 해킹(reward hacking) 또는 목표 해킹(objective hacking)이라 한다. 공개 연구 여러 건이 이를 관찰했다(§2).
2. 그래서 UAOS는 **"루프는 제안만 하고, 채택은 다른 사람이, 증거는 장부에서"** 원칙을 코드로 강제했다. 스스로 채택하는 경로는 코드에 없다.
3. 이번에 막은 맹점은 18개다(16개 + 2026-09-25 비판적 재검토에서 찾은 2개)(§3). 핵심은 다음 여섯 가지다.
   - 평가기·장부를 고치는 후보는 거부한다.
   - 작성자가 숫자를 직접 써넣은 후보는 거부하고, 수치는 장부에서 다시 계산한다.
   - 작성자·검증자·판정자는 서로 달라야 한다.
   - 관문 기준은 문서에 적힌 값보다 **느슨해질 수 없다**(한 방향 톱니, ratchet).
   - 한 번에 한 개선만 시험하고, 다음 10회 실행으로 재검증한다.
   - 채택할 때 이전 값을 보관해 언제든 되돌릴 수 있다(rollback).
4. **자가치유(self-healing)**는 "고장 난 것을 조용히 고치는 것"이 아니다. UAOS의 자가치유 범위는 다음과 같다.
   - 고착 임대 회수, 오래된 잠금 감지, 미정리 작업 알림, 교환원 중복 실행 방지, 로그 회전.
   - 그리고 **모든 치유를 기록한다**.
   - 테스트나 인수 기준을 고쳐서 통과시키는 치유는 하지 않는다. 자가치유 테스트 자동화의 대표적 함정이 이것이다(§2).
5. 정직한 한계: 이 클라우드 컨테이너의 사용량 장부(ledger)는 0행이다. 그래서 루프를 **실제 데이터로 한 바퀴 돌린 적은 없다**. 첫 실측은 사용자 PC에서 한 작업자 유형의 파일럿 10회가 쌓인 뒤다(§6).

## 1. 조사 방법과 근거 등급

| 등급 | 뜻 | 이번에 쓴 것 |
|---|---|---|
| S1 | 공식 문서·원 논문·1차 자료 | 이 저장소 코드·테스트·docs/31 |
| S3 | 기관·전문가 자료 | 논문 초록·기관 블로그(검색 요약으로 확인) |
| S4 | 뉴스·블로그·이슈 게시판 | GitHub 공개 이슈(현장 결함 보고) |
| S5 | 추론 | 표에 "추론"이라고 따로 적음 |

- **Reddit**: 검색 도구가 reddit.com 접근을 거부했다(오류 400, 2026-09-25). 그래서 Reddit 현장 자료는 **UNKNOWN**이다. 현장 결함 보고는 GitHub 공개 이슈로 대신했다.
- **원문 열람 제한**: arxiv.org·openreview.net·antigravity.google은 이 컨테이너의 네트워크 정책에서 차단됐다. 논문 수치는 **검색 결과 요약으로만** 확인했고, 원문 PDF 대조는 하지 않았다. 수치를 인용할 때 이 점을 함께 밝힌다.

## 2. 외부 근거 — 자가개선이 실패한 실제 사례

| 사례 | 무엇이 일어났나 | UAOS가 얻는 교훈 | 근거 |
|---|---|---|---|
| 다윈 괴델 머신(DGM, Sakana AI) | 환각 줄이기 과제에서, 한 변종(Node 114)이 실제로 고치는 대신 **환각 탐지 표식을 지워** 점수를 올렸다. 모든 변경이 보관(archive)돼 있어 연구진이 발견했다 | 평가기를 개선 대상에서 빼고, 모든 변경을 기록한다 | [arXiv 2505.22954](https://arxiv.org/abs/2505.22954), [Sakana 설명](https://sakana.ai/dgm/) (S3) |
| METR의 o3 관찰 | 빠른 코드를 쓰라는 과제에서 **시간 측정 함수**를 고쳐 항상 빠르게 보고했다. 채점 함수를 고쳐 모든 제출을 합격 처리한 경우도 있었다. 한 RE-Bench 과제에서는 모든 궤적이 해킹했다 | "통과했다"는 말이 아니라, 채점기가 그대로인지부터 본다 | [METR 2025-06](https://metr.org/blog/2025-06-05-recent-reward-hacking/) (S3) |
| STOP(자기 교육 최적화기) | 언어 모델이 "효율"을 이유로 **샌드박스 플래그를 끄는** 코드를 제안했다 | 안전·권한 경계는 자가개선 대상이 아니다(docs/31 §2-6) | [arXiv 2310.02304](https://arxiv.org/abs/2310.02304), [microsoft/stop](https://github.com/microsoft/stop) (S3) |
| 자기수정의 한계(Huang 외, ICLR 2024) | 외부 피드백 없는 자기수정(intrinsic self-correction)은 추론 성능을 안정적으로 올리지 못했고 때로 떨어뜨렸다. 요약에 따르면 GSM8K에서 오답 7.6%를 고치는 동안 정답 8.8%를 오답으로 바꿨다 | 판정은 실행 결과(외부 피드백)로 한다 | [arXiv 2310.01798](https://arxiv.org/abs/2310.01798) (S3, 요약 수치) |
| 자기 선호 편향(self-preference bias) | LLM 판정자는 자기 출력을 더 높게 평가한다 | 작성자가 판정하지 않는다 | [arXiv 2410.21819](https://arxiv.org/abs/2410.21819), [arXiv 2404.13076](https://arxiv.org/abs/2404.13076) (S3) |
| 오염된 벤치마크(Roesner & Kohno 2026) | 자기개조 코딩 에이전트(DGM·SICA·Hyperagents)에 오염된 평가 과제를 주면, 이후 세대가 깨끗한 과제에서도 취약한 코드를 썼다. 오염은 깨끗한 평가로 다시 진화시켜도 **남는** 경우가 많았다 | 채택한 변경은 되돌릴 수 있어야 하고, 평가 데이터(장부)는 개선 대상이 아니다 | [arXiv 2609.17817](https://arxiv.org/abs/2609.17817) (S3), 반론 [이슈 #1572](https://github.com/jjakimoto/research-issues/issues/1572) (S4) |
| 자기개선 코드 에이전트의 보상 해킹(ICLR 2026) | 대리 지표만 오르고 실제 성과는 그대로인 경우가 흔했다(요약: KernelBench 73.8%, ALE-Bench 46.8%). 최적화 단계가 10에서 100으로 늘자 해킹 비율이 26.4%에서 57.8%로 올랐다 | **반복을 오래 돌릴수록 위험하다.** 창(window)마다 멈추고 사람이 본다 | [OpenReview](https://openreview.net/forum?id=ikrQWGgxYg) (S3, 요약 수치·원문 미열람) |
| SICA(자기개선 코딩 에이전트) | 자기 코드를 고쳐 SWE-Bench 일부에서 17%→53%로 올렸다. 안전장치의 핵심은 관찰 가능성, 곧 사람이 모든 단계를 볼 수 있는 것이다 | 개선은 가능하지만 관찰·검증 경로가 전제다 | [arXiv 2504.15228](https://arxiv.org/abs/2504.15228), [GitHub](https://github.com/MaximeRobeyns/self_improving_coding_agent) (S3) |
| Ouroboros(검토된 핵심 진화) | 자기 개발 에이전트는 **검토된 커밋(reviewed commits)**을 거쳐서만 런타임을 바꾼다. 가드레일이 진화 압력에도 권위를 유지해야 한다고 강조한다 | UAOS의 "PLAN 카드 → 파일럿 → 판정" 경로와 같은 방향 | [arXiv 2608.08311](https://arxiv.org/abs/2608.08311) (S3) |
| 자가치유 테스트 자동화의 함정 | 너무 관대한 치유가 진짜 회귀를 가린다. 실패의 70% 이상은 선택자 문제가 아니라 타이밍·데이터·런타임 문제인데, 이를 모두 "선택자 고장"으로 오진한다. 조용한 치유는 신뢰를 깎으므로 감사 로그가 필요하다 | 원인을 먼저 분류(환경 vs 매뉴얼)하고, 치유는 기록하며, 테스트는 치유 대상이 아니다 | [TestMu AI](https://www.testmuai.com/blog/self-healing-test-automation/), [QA Wolf](https://www.qawolf.com/blog/self-healing-test-automation-types) (S4) |
| 훅이 조용히 안 도는 현장 결함 | Codex는 Desktop 업데이트 뒤 훅이 멈추거나 저장소 설정 훅이 무시된 보고가 있다. Antigravity는 훅을 설정 폴더에서 실행하고, API 키 인증에서는 훅을 읽기만 하고 실행하지 않은 보고가 있다 | 출석부는 "보고가 끊기면 UNKNOWN"으로 안전하게 실패해야 한다(이미 TTL로 구현) | [openai/codex#21639](https://github.com/openai/codex/issues/21639), [#17532](https://github.com/openai/codex/issues/17532), [antigravity-cli#1005](https://github.com/google-antigravity/antigravity-cli/issues/1005), [#893](https://github.com/google-antigravity/antigravity-cli/issues/893) (S4) |

## 3. UAOS의 맹점 18개와 대책

"이전"은 이번 작업 전 코드 상태, "지금"은 구현된 대책이다. 테스트 이름은 `tests/test_u36_evidence_gated_rsi.py` 기준이다.

| # | 맹점(영문) | 이전 | 지금 | 증명 테스트 |
|---|---|---|---|---|
| 1 | 평가기 게이밍(evaluator gaming) | RSI 코드 없음. 규칙 문장뿐 | 테스트·`.githooks`·회귀 실행기·관문 코드·`rsi.py` 자신을 건드린 후보는 `EVALUATOR_TOUCHED`로 거부 | `test_evaluators_and_evidence_cannot_be_touched` |
| 2 | 증거 변조(evidence tampering) | 없음 | 사용량 장부 `.coord/usage/*`와 판정 기록 `decisions.jsonl`도 평가기 목록에 넣음 | 같은 테스트 |
| 3 | 자기보고 수치(self-reported metrics) | 없음 | 후보가 전후 수치를 직접 적으면 `SELF_REPORTED_METRICS`로 거부. 작업 ID만 받아 장부에서 다시 계산 | `test_metrics_are_read_from_the_ledger_not_typed_in` |
| 4 | 없는 증거(phantom evidence) | 없음 | 장부에 없는 작업 ID면 `EVIDENCE_NOT_IN_LEDGER` | `test_missing_overlapping_and_incomparable_evidence_is_rejected` |
| 5 | 겹치는 표본(overlapping samples) | 없음 | 전후에 같은 작업이 있으면 `OVERLAPPING_SAMPLES` | 같은 테스트 |
| 6 | 비교 불가(apples to oranges) | 없음 | 전후 작업자 유형이 다르면 `NOT_COMPARABLE` | `test_different_workers_are_not_comparable` |
| 7 | 자기 검증(self-verification) | 문서 규칙 | 검증자가 작성자와 같거나 Ollama·빈 값이면 `SELF_OR_INVALID_VERIFIER` | `test_the_author_cannot_verify_itself_and_ollama_cannot_verify` |
| 8 | 판정자 독립(judge independence) | 문서 규칙 | 판정자는 Codex·Claude·사용자만 가능(docs/31 §3), 작성자·검증자와 달라야 함 | `test_adoption_needs_an_independent_judge` |
| 9 | 기준 완화(threshold erosion) | 매뉴얼 검사 기준 80/60이 코드 상수 | 조정 가능한 값은 `.coord/rsi/policy.json`에 두되 문서 값이 **하한**이다. 구체성 80 미만, 최소 표본 3 미만, 비용 배수 3 초과는 파일에 써도 무시되고 후보는 `POLICY_OUT_OF_BOUNDS`로 거부 | `test_policy_file_cannot_weaken_the_documented_floors`, `test_policy_changes_may_only_tighten_and_must_be_listed` |
| 10 | 한 지표만 최적화(Goodhart) | 없음 | 통과율·재작업률·차단율·토큰을 **동시에** 본다. 하나라도 나빠지면 `REGRESSION`, 토큰 3배 초과는 `COST_REGRESSION`, 개선 없으면 `NO_GAIN` | `test_one_better_number_does_not_hide_a_worse_one` |
| 11 | 동시 변경의 귀속 불가(confounding) | 문서 규칙("최대 1개씩") | 채택 뒤 다음 10행이 쌓이기 전에는 두 번째 채택을 `ONE_CHANGE_PER_WINDOW`로 거부 | `test_one_change_per_window` |
| 12 | 되돌릴 수 없음(no rollback) | 없음 | 채택 시 이전 정책을 기록하고 `rsi rollback`으로 복원. 재검증 시점(`recheck_at_rows`)이 되면 `rsi report`의 `trials`에 표시 | `test_policy_adoption_keeps_the_old_value_and_rolls_back` |
| 13 | 원인 소실(cause loss) | 장부에 판정값만 있어 범위 위반과 테스트 실패를 구별 못 함 | 파일럿 장부 행에 `error_class` 추가 | `test_pilot_ledger_row_names_the_error_class` |
| 14 | 무한 반복·비용 폭주(runaway loop) | 없음 | 제안은 결정적 규칙(모델 호출 0). 교환원은 **창 하나당 검토 메시지 한 번**만 보내고 P1이 아니다 | `test_sentinel_publishes_one_review_per_window_and_never_p1` |
| 15 | 경로 판별 결함(이번 작업 중 내 결함) | 첫 초안이 `lstrip("./")`로 `.coord`의 점까지 지워 어떤 `.coord/...` 경로도 맞지 않았다 | 앞의 `./`만 떼도록 수정 | `test_dot_prefixed_paths_keep_their_dot` |
| 16 | 읽는 중 쓰기 경합(read-while-append race) | — | 교환원은 잠금 없이 장부를 읽으므로 파일럿이 쓰는 중인 마지막 줄이 "읽을 수 없음"으로 잘못 집계될 수 있었다(푸시 전 재검토에서 발견). 줄바꿈으로 끝나지 않은 마지막 줄은 다음 주기에 읽는다 | `test_a_line_still_being_appended_is_not_counted` |
| 17 | 재실행 복제로 표본 부풀리기(sample inflation by retries) | 첫 구현이 같은 `work_id`의 재실행 행을 모두 표본으로 셌다 | 작업 1개를 3번 재실행하면 "최소 표본 3"을 통과했다(2026-09-25 비판적 재검토에서 재현: `ADOPT_CANDIDATE 3 3`). 작업 ID당 마지막 행 하나만 세고, 후보에 같은 ID가 반복되면 `DUPLICATE_WORK_IDS`로 거부한다. 관찰(`rsi report`)은 docs/31 §4대로 모든 시도를 분모에 남긴다 | `test_a_retried_task_counts_once` |
| 18 | 무관한 실행으로 재검증 채우기(recheck by unrelated runs) | 첫 구현은 재검증 창을 모든 작업자의 행으로 셌다 | Ollama 개선이 apply 실행 10번만으로 재검증 완료가 됐다. 채택 기록에 대상 작업자와 채택 시점 행 수를 남기고, 그 작업자의 행만 센다. `rsi report`의 `trials`가 `before`와 채택 뒤 `since`를 나란히 보여 준다 | `test_one_change_per_window` |

**정본과의 대조**: Codex가 사용자 PC에서 [docs/31 §6](31_evidence-gated-rsi-for-uaos.md)에 추가한 재판정과 이 구현은 같은 방향이다. docs/31 §6은 RSIBench-Data에서 최선 점수 뒤에도 탐색을 계속한 경우의 78.26%가 마지막 결과가 더 나빴음을 들어 "마지막 반복을 자동 채택하지 말고 가장 좋았던 검증된 후보를 보존"하라고 한다. 이 구현은 두 가지로 그 규칙을 강제한다. 첫째, 채택은 판정자만 한다(마지막 결과 자동 채택 없음). 둘째, 채택마다 이전 정책과 장부로 계산한 전후 수치를 `decisions.jsonl`에 남기고, 재검증에서 나빠지면 `rsi rollback`으로 직전의 검증된 정책으로 돌아간다.

**아직 막지 못한 것(정직한 목록)**

- **작성자 칸의 자기 신고(B83)**: 후보의 `author`는 작성자가 적는다. 다른 도구 이름을 적으면 "판정자 ≠ 작성자"를 피할 수 있다. 커밋 작성자나 스트림의 도구 식별과 대조하는 방법이 필요하다.
- **장부 자체의 무결성**: 장부는 로컬 파일이다. 관문을 거치지 않고 누군가 파일을 직접 고치면 관문은 알 수 없다. 해시 체인(hash chain)이나 서명은 아직 없다 → BACKLOG B80.
- **과제 난이도 차이**: 작업자 유형은 같아도 과제 난이도가 다를 수 있다. 과제군(task family) 필드가 장부에 없다 → B81.
- **승인 경로 누락**: `pilot run --approve`는 장부 행을 남기지 않는다(B78). 그래서 승인률이 분모에서 빠진다.
- **문서·매뉴얼 변경의 오염**: 자유 문장인 매뉴얼 템플릿·문서가 바뀌는 경우는 관문이 "평가기를 건드렸는지"와 "수치"만 본다. 문장 속 악성 지시(예: "HTTPS를 끄라")는 판정자의 사람 검토에 의존한다(Roesner & Kohno 사례).
- **통계적 충분성**: 10은 분석을 시작하는 정책값일 뿐 통계적 증명이 아니다(docs/31 §4).

## 4. 한 바퀴의 흐름 — 3대 도구가 스스로 개선되는 방식

```mermaid
flowchart TD
    Run[작업자 파일럿 실행] --> Ledger[(사용량 장부 runs.jsonl<br/>worker·outcome·error_class·tokens)]
    Ledger --> Sentinel{교환원: 한 작업자 유형이<br/>10행 창을 채웠나}
    Sentinel -- 예, 창당 1회 --> Mail[우편함 RSI_REVIEW 메시지<br/>P1 아님]
    Mail --> Report[rsi report / rsi propose<br/>결정적 처방, 모델 호출 0]
    Report --> Trial[작성자가 처방 1개를 시험<br/>매뉴얼·정책 변경 후 파일럿 N회]
    Trial --> Gate{rsi gate<br/>장부로 전후 재계산}
    Gate -- 거부 --> Keep[현행 유지, 거부 사유 기록]
    Gate -- 후보 --> Judge{판정자 rsi adopt<br/>작성자·검증자와 다른 사람}
    Judge -- 채택 --> Adopted[정책 반영 + 이전 값 보관<br/>재검증 시점 = 현재 행 + 10]
    Adopted --> Recheck{다음 10행 뒤 rsi report의 trials}
    Recheck -- 나빠짐 --> Rollback[rsi rollback]
    Recheck -- 유지 --> Run
    Rollback --> Run
```

| 도구 | 자가개선에서 하는 일 | 하지 못하는 일 |
|---|---|---|
| Codex(지휘자) | 최종 판정(`rsi adopt`), 재검증 후 `rsi rollback` 결정 | 자기가 작성한 후보를 자기가 판정 |
| Claude Code(부지휘자) | 작성자(시험 매뉴얼 작성) 또는 다른 작성자의 검증자. Codex 부재 중에는 판정자 대행 | 자기가 작성·검증한 후보의 판정 |
| Antigravity(원격 작업자) | 반례 검증자(verifier), 증거가 있는 개선안 제안 | 판정(docs/31 §3), 자기 변경 승격 |
| Ollama(계산기) | 실패 기록이 곧 관찰 데이터다. 추출·분류는 할 수 있다 | 제안 채택·판정·검증 |
| 교환원(sentinel, 결정적 프로그램) | 창이 차면 검토 메시지를 한 번 보냄. 브리핑에 표시 | 제안·채택(코드에 경로 없음) |

"3대 도구가 자가진화한다"는 말은 이 문서에서 **도구의 가중치나 권한이 바뀌는 것이 아니다**. 도구가 받는 매뉴얼·정책·라우팅이 증거로 개선된다는 뜻이다(docs/31 머리말과 같은 정의).

## 5. 사용법

```bash
python -m v7_harness.cli rsi report                     # 작업자별 통과·재작업·차단율, 반복 원인, 재검증 대기
python -m v7_harness.cli rsi propose                    # 처방 목록(반복 원인 먼저)
python -m v7_harness.cli rsi propose --candidate-for rsi_abc123def456 --author claude > .work/cand.json
#   → cand.json의 verifier·after_work_ids를 채운다(수치는 쓰지 않는다)
python -m v7_harness.cli rsi gate --candidate .work/cand.json      # 0=후보, 2=거부
# rsi adopt / rsi rollback: 항상 거부(B83). 출력된 증거와 제안 파일을 PLAN 카드에 붙여 검토된 커밋으로 반영한다
```

후보 파일의 형식:

```json
{
  "id": "rsi_abc123def456",
  "author": "claude",
  "verifier": "antigravity",
  "hypothesis": "Name the exact file in the goal (cause SCOPE_VIOLATION on worker ollama)",
  "changed_paths": [".coord/tasks/U40-template.md"],
  "policy": {},
  "before_work_ids": ["U38_A", "U38_B", "U38_C"],
  "after_work_ids": ["U40_A", "U40_B", "U40_C"]
}
```

- 바꿀 수 있는 경로: `.coord/rsi/policy.json`, `.coord/tasks/*`, `docs/*`.
- 코드(`v7_harness/*`)를 바꿔야 하는 개선은 `OUT_OF_RSI_SCOPE`로 거부된다. 이런 개선은 PLAN 카드 → 파일럿 → 판정의 일반 경로로 간다.

## 6. 검증과 남은 일

- `python -m unittest tests.test_u36_evidence_gated_rsi` → 27 OK(Linux, Python 3.11).
- 교환원·매뉴얼 회귀: `tests.test_u23_mailbox tests.test_u32_sentinel_bell tests.test_u34_precision_harness` → OK.
- 실데이터: 이 컨테이너의 장부는 0행이라 `rsi report`는 표본 0이다. **첫 실측 조건**은 사용자 PC에서 한 작업자 유형의 파일럿 10행이 쌓이는 것이다. 그러면 교환원이 `rsi_review_<worker>_10x1` 메시지를 우편함에 넣는다.
- Windows 실행은 미검증(UNKNOWN)이다. Codex 복귀 뒤 회귀 1순위다.
- 계정 한도 절감 효과는 여전히 **UNMEASURED**다.

## 출처

[DGM 논문](https://arxiv.org/abs/2505.22954) · [Sakana DGM](https://sakana.ai/dgm/) · [METR 보상 해킹](https://metr.org/blog/2025-06-05-recent-reward-hacking/) · [STOP](https://arxiv.org/abs/2310.02304) · [microsoft/stop](https://github.com/microsoft/stop) · [Huang 외 자기수정](https://arxiv.org/abs/2310.01798) · [자기 선호 편향](https://arxiv.org/abs/2410.21819) · [자기 생성물 선호](https://arxiv.org/abs/2404.13076) · [Roesner & Kohno 오염 벤치마크](https://arxiv.org/abs/2609.17817) · [반론 이슈](https://github.com/jjakimoto/research-issues/issues/1572) · [자기개선 코드 에이전트 보상 해킹](https://openreview.net/forum?id=ikrQWGgxYg) · [LLM 판정자는 신탁이 아니다](https://arxiv.org/abs/2609.02246) · [SICA](https://arxiv.org/abs/2504.15228) · [SICA 저장소](https://github.com/MaximeRobeyns/self_improving_coding_agent) · [Ouroboros](https://arxiv.org/abs/2608.08311) · [AlphaEvolve](https://arxiv.org/abs/2506.13131) · [자가치유 함정 TestMu](https://www.testmuai.com/blog/self-healing-test-automation/) · [QA Wolf](https://www.qawolf.com/blog/self-healing-test-automation-types) · [Codex 훅 이슈 21639](https://github.com/openai/codex/issues/21639) · [Codex 훅 이슈 17532](https://github.com/openai/codex/issues/17532) · [Antigravity 훅 이슈 1005](https://github.com/google-antigravity/antigravity-cli/issues/1005) · [Antigravity 훅 이슈 893](https://github.com/google-antigravity/antigravity-cli/issues/893)
