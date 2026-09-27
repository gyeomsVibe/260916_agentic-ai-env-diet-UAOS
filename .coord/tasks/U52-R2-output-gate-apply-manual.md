```contract
work_id: U52-R2
worker: apply
goal: Rework U52-S1b per Codex verdict: hard total cap including the marker; gate wired into the review diff, the pilot acceptance log and the paid judge request; unused mask_observations removed (docs/49 U-TOK-1)
inputs:
- .coord/tasks/U52-R2-prompt.md sha256=8429c3389151fea97f3b9942ea3b99b1753edf160d3a2ef3a51f22de9b3445ba
allow:
- v7_harness/output_gate.py
- tests/test_u52_output_gate.py
- v7_harness/review.py
- v7_harness/pilot.py
- v7_harness/judge.py
- docs/49_article12-ollama-extraction-and-uaos-update-report_2026-09-27.md
acceptance: python -m unittest tests.test_u52_output_gate tests.test_b20_model_flag tests.test_b23_concurrency_summary tests.test_b24_rejected_summary tests.test_b25_db_unavailable tests.test_b26_b21_features tests.test_b30_no_change_verdict tests.test_b38_b52 tests.test_b41_bundle tests.test_b44_live_identity tests.test_b46_b47_hardening tests.test_m2_pilot tests.test_m4_efficiency tests.test_u17_lane_worker tests.test_u18_accept_triage tests.test_u21_calculator tests.test_u33_pilot_autolog_default tests.test_u34_precision_harness tests.test_u36_evidence_gated_rsi tests.test_u38_cost_gate_and_claude_worker tests.test_u44_claude_contract tests.test_u46_followup_fixes tests.test_u47_rw1d_counterexamples tests.test_u48_default_workdir
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

U52-R2: tool-output gate with a hard total cap on three paid-model paths (docs/49 §5 U-TOK-1; Codex verdict on U52-S1b). Apply the blocks exactly. No other change.

===FILE: v7_harness/output_gate.py===
"""U52: tool-output token gate. docs/49 §5 U-TOK-1.

Tool output that reaches a paid model is cut deterministically, never summarized by a model: arXiv 2508.21433 found
plain masking as good as LLM summaries at half the cost (measured on SWE-agent trajectories), and the local model quoted
its source verbatim only 32/67 times in the docs/49 run. A cut is always announced in the text, with the original size
and hash, so a reader never takes a partial output for the whole one; the full text can be kept in a spill file.

U52-R2 (Codex verdict on U52-S1b):
- `max_chars` is a hard cap on the whole result, marker included; S1b kept max_chars and then added the marker
  (gate_output('x'*10000, 1000) returned 1096 chars).
- mask_observations() is removed: no paid-model path in the harness carries a list of earlier observations, so it had
  no production caller. It returns with the first path that does (docs/49 §5 U-TOK-1, open item).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

# Head share of the kept characters. The tail keeps the rest because test runners and tracebacks put the verdict
# and the last error at the end; the head keeps the first failure and the command context.
HEAD_SHARE = 0.4
# Hash prefix length in markers: 12 hex characters is the prefix the repo already uses for bundle ids (brief.py).
HASH_CHARS = 12


@dataclass(frozen=True)
class GateResult:
    text: str
    truncated: bool
    original_chars: int
    sha256: str
    spill_path: str | None = None


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _spill(text: str, spill_path: str | Path | None) -> str | None:
    if spill_path is None:
        return None
    path = Path(spill_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", errors="replace")
    except OSError:
        return None  # the marker still reports size and hash; a missing spill is shown as "not saved"
    return str(path)


def gate_output(text: str, max_chars: int, spill_path: str | Path | None = None) -> GateResult:
    """Return at most `max_chars` characters of `text`, marker included: head and tail around an explicit cut marker.
    When the cap is too small for even the marker, the marker itself is cut, so the cap still holds."""
    text = text or ""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    digest = _sha(text)
    if len(text) <= max_chars:
        return GateResult(text, False, len(text), digest)
    saved = _spill(text, spill_path)
    where = f"full text: {saved}" if saved else "full text not saved"

    def marker(omitted: int) -> str:
        return (f"\n[U52 OUTPUT CUT: {omitted:,} of {len(text):,} chars omitted here; "
                f"sha256 {digest[:HASH_CHARS]}; {where}]\n")

    # The omitted count is part of the marker, so size the marker for the largest count it can show (everything).
    budget = max_chars - len(marker(len(text)))
    if budget <= 0:
        return GateResult(marker(len(text))[:max_chars], True, len(text), digest, saved)
    head_n = int(budget * HEAD_SHARE)
    tail_n = budget - head_n
    body = text[:head_n] + marker(len(text) - head_n - tail_n) + (text[len(text) - tail_n:] if tail_n else "")
    return GateResult(body, True, len(text), digest, saved)
===END===

===FILE: tests/test_u52_output_gate.py===
"""U52: tool-output token gate (docs/49 §5 U-TOK-1)."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from v7_harness import judge
from v7_harness.output_gate import gate_output
from v7_harness.review import MAX_DIFF_CHARS, review_prompt


class GateOutputTest(unittest.TestCase):
    def test_short_text_passes_unchanged(self) -> None:
        result = gate_output("ok\n", 100)
        self.assertEqual(result.text, "ok\n")
        self.assertFalse(result.truncated)

    def test_long_text_keeps_head_and_tail_and_marks_the_cut(self) -> None:
        text = "HEAD" + "x" * 10_000 + "TAIL"
        result = gate_output(text, 1000)
        self.assertTrue(result.truncated)
        self.assertTrue(result.text.startswith("HEAD"))
        self.assertTrue(result.text.endswith("TAIL"))
        self.assertIn("U52 OUTPUT CUT", result.text)
        self.assertIn(hashlib.sha256(text.encode()).hexdigest()[:12], result.text)
        self.assertEqual(result.original_chars, len(text))

    def test_codex_counterexample_total_stays_within_the_cap(self) -> None:
        # Red on U52-S1b: gate_output('x'*10000, 1000) returned 1096 characters.
        self.assertLessEqual(len(gate_output("x" * 10_000, 1000).text), 1000)

    def test_cap_holds_for_every_size_including_caps_smaller_than_the_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spill = Path(tmp) / "a-long-spill-folder-name" / "full.log"
            for cap in (1, 5, 50, 100, 130, 200, 500, 1000, 4000):
                for size in (cap + 1, cap * 2, cap * 10 + 7, 123_457):
                    for path in (None, spill):
                        result = gate_output("y" * size, cap, path)
                        self.assertLessEqual(len(result.text), cap, (cap, size, path))
                        self.assertTrue(result.truncated)

    def test_spill_file_holds_the_full_text(self) -> None:
        text = "a" * 5000
        with tempfile.TemporaryDirectory() as tmp:
            spill = Path(tmp) / "sub" / "full.log"
            result = gate_output(text, 400, spill)
            self.assertEqual(spill.read_text(encoding="utf-8"), text)
            self.assertIn(str(spill), result.text)

    def test_same_input_gives_same_output(self) -> None:
        text = "line\n" * 3000
        self.assertEqual(gate_output(text, 500).text, gate_output(text, 500).text)

    def test_non_positive_cap_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            gate_output("x", 0)


class ReviewPromptTest(unittest.TestCase):
    def test_small_diff_is_called_complete(self) -> None:
        prompt = review_prompt("T1", "contract", "+one line\n")
        self.assertIn("complete change", prompt)
        self.assertNotIn("PARTIAL", prompt)

    def test_oversized_diff_is_called_partial_keeps_its_tail_and_the_cap(self) -> None:
        diff = "+head\n" + "+x\n" * (MAX_DIFF_CHARS // 2) + "+LAST_HUNK\n"
        with tempfile.TemporaryDirectory() as tmp:
            prompt = review_prompt("T1", "contract", diff, Path(tmp) / "review.diff")
            self.assertIn("PARTIAL", prompt)
            self.assertNotIn("complete change", prompt)
            self.assertIn("+LAST_HUNK", prompt)  # the old diff[:MAX] cut dropped this silently
            self.assertEqual((Path(tmp) / "review.diff").read_text(encoding="utf-8"), diff)
            shown = prompt.split("```diff\n", 1)[1].rsplit("\n```", 1)[0]
            self.assertLessEqual(len(shown), MAX_DIFF_CHARS)


MANUAL = """```contract
work_id: T1
worker: apply
goal: g
allow:
- a.py
acceptance: python -c "pass"
judge: antigravity
remote_budget_tokens: 0
```
"""


class JudgeRequestTest(unittest.TestCase):
    """Production caller: the acceptance log a paid judge reads. Red on U52-S1b, which kept only log[-4000:]: the first
    failure at the head of a long log vanished without a mark."""

    def test_paid_judge_request_keeps_head_tail_and_the_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work, source, stage = root / "work", root / "src", root / "stage"
            runs = work / "runs" / "T1"
            for folder in (runs, source, stage):
                folder.mkdir(parents=True)
            (source / "a.py").write_text("X = 1\n", encoding="utf-8")
            (stage / "a.py").write_text("X = 2\n", encoding="utf-8")
            (runs / "worker").write_text("claude", encoding="utf-8")
            log = runs / "acceptance.log"
            log.write_text("FIRST_FAILURE in test_a\n" + "noise line\n" * 2000 + "LAST_LINE FAILED (failures=1)\n",
                           encoding="utf-8")
            (runs / "summary.json").write_text(json.dumps(
                {"agy_workspace": str(stage), "changed_files": ["a.py"], "bundle_id": "b1",
                 "promotion": "DRY_RUN_PASSED", "acceptance_exit": 0, "acceptance_log_path": str(log)}),
                encoding="utf-8")
            manual = root / "m.md"
            manual.write_text(MANUAL, encoding="utf-8")

            def runner(argv, **kwargs):
                class Done:
                    stdout, stderr, returncode = b"{}", b"", 1
                return Done()

            judge.run_judge(task_id="T1", work_dir=work, source=source, manual_path=manual, budget=10_000,
                            runner=runner, approver=lambda *a, **k: None, desk={"codex": {"state": "ABSENT"}})
            request = (runs / "judge_agy_request.md").read_text(encoding="utf-8")
            shown = request.split("last lines)\n```\n", 1)[1].split("\n```", 1)[0]
            self.assertIn("FIRST_FAILURE", shown)
            self.assertIn("LAST_LINE", shown)
            self.assertIn("U52 OUTPUT CUT", shown)
            self.assertLessEqual(len(shown), judge.ACCEPTANCE_TAIL_CHARS)


if __name__ == "__main__":
    unittest.main()
===END===

===FILE: docs/49_article12-ollama-extraction-and-uaos-update-report_2026-09-27.md===
# 49. 기사 12건 올라마 재분석 + 외부 자료 비교 → UAOS 개선·업데이트 보고서

- 작성: Claude Code (Codex 대행 아님, Codex 복귀 시 재검토 대상), 2026-09-27
- 입력: `docs/user-docs/# UAOS 기사 분석 보고서 01~12.md` (13~15번 종합본은 비교 기준으로만 사용)
- 산출물 등급: 유지(maintained) 문서. 추출 원본은 `.work/article_ollama_20260927/`(일회성, 커밋 제외)

---

## 1. 결론 먼저

**UAOS에 새 에이전트나 새 프로바이더 계층을 더하지 말고, "문맥에 무엇이 들어가도 되는가"를 재는 관문 3개를 먼저 넣는다.**

| 순위 | 도입 로직 | 출처 기사 | 현재 코드 상태 | 외부 근거 |
|---|---|---|---|---|
| P1 | 도구 출력 토큰 관문(Tool Output Token Gate) + 오래된 관찰 가리기(observation masking) | 08, 15번 종합 | 없음(`grep tool_output\|masking` 0건) | 관찰 토큰이 턴의 약 84%, 단순 가리기로 비용 절반·성능 동등(arXiv 2508.21433) |
| P1 | 문맥 입장 관문(Context Admission Gate) = 지연 능력 로딩(Lazy Capability Loading) | 08, 04(C10) | 없음(`admission` 0건) | MCP 도구 정의 선로딩 1회 약 7k~50k 토큰, 도구 검색 지연 로딩으로 85% 감소 보고 |
| P1 | 작업별 모델 자격 관문(Model Qualification Gate) + 모델 산출물 고정(pinning) | 06, 11 | 부분(`olla.py` 읽기 비용 추정만 있음) | **이번 실행 자체가 증거**: 4B 로컬 모델의 원문 인용 정확도 32/67=48% |
| P2 | 토큰 톱니(Token Ratchet): 검증된 최저 토큰량을 회귀 상한으로 고정 | 01 | 부분(`rsi.py`에 회귀 관문 있음, 토큰 축은 없음) | claude.ai 3배 개선: 여정 4개(사용량 95%)·지표 13개로 측정 후 고정 |
| P2 | 도구 실행 방화벽(Tool Proposal/Execution Firewall)·작업별 허용목록 | 04, 08 | 부분(`adapters/guard.py`, 전역 규칙) | Ollama·OpenAI 도구 호출은 "요청"일 뿐 실행 권한이 아님 |
| P3 | 능력 증거 등록부(Capability Evidence Registry)·프로브 | 02, 03, 07, 10 | 없음 | OpenAI 호환 선언 ≠ 기능 보장(Ollama 문서도 부분 호환 명시) |
| 보류 | 빠른 판단 평면(Fast Decision Plane), 다중 프로바이더 라이브러리 흡수, OpenClaude 코드 도입 | 12, 07, 10 | — | 12번 추출 6건 모두 인용 불일치, 07번은 유출 코드 라이선스 위험 |

---

## 2. 이번 분석을 어떻게 했나 (재현 가능한 절차)

토큰 예산이 사용 한도에 가깝다는 조건 때문에 **읽기·추출은 올라마, 판단·비교는 Claude**로 나눴다.

1. **기사 1건 = 올라마 새 대화 1회.** 대화 기록을 공유하지 않고 12번 따로 호출했다(`extract.py`, 모델 `qwen3.5-32k`, temperature 0, JSON 형식 강제).
2. **호출마다 작업 매뉴얼 전달.** 작업 ID `U-ART12-EXTRACT-nn`, 입력 SHA-256, 출력 스키마, 금지 행동(원문에 없는 문장 생성), 인수 관문을 프롬프트 머리에 넣었다.
3. **독립 관문 2개로 검증.** (a) `quote`가 원문에 글자 그대로 있는지, (b) 후보 이름이 원문에 있는지 — 둘 다 결정적(deterministic) 파이썬 검사. 올라마의 "성공" 응답은 증거로 치지 않았다.
4. **Claude는 원문 전체를 읽지 않았다.** 제목·판정 줄과 올라마 추출 결과, 코드 `grep` 결과, 웹 검색 8회만 사용했다.

### 측정값

| 항목 | 값 |
|---|---|
| 호출 수 | 12회(실패 0, JSON 파싱 오류 0) |
| 로컬 벽시계 시간 | 합계 360초(1번 72초는 모델 적재 포함, 나머지 21~33초) |
| 로컬 토큰 | 입력 45,037 / 출력 7,053 |
| 후보 추출 | 67건 |
| 인용 원문 일치 | 32건(48%) — 35건은 의역이라 관문에서 탈락 |
| 이름 원문 일치 | 60건(90%) — 탈락 7건은 이름 앞 번호 형식 변형 |
| 기사별 최악 | 12번: 인용 0/6 (긴 원문 20KB, 추상 개념 위주) |

**해석:** 4B급 로컬 모델은 "무엇이 있는지 찾기(이름·목록)"는 90% 신뢰, "그대로 베끼기(인용)"는 48%다. 그래서 UAOS에서 올라마 출력은 **반드시 원문 대조 관문 뒤에서만** 쓰여야 하며, 이것이 P1 "모델 자격 관문"의 직접 근거다.

**Claude 토큰 절감은 측정하지 않았다(UNMEASURED).** 원문 12건(약 187KB)을 Claude가 직접 읽었을 경우와의 대조 실험은 하지 않았다.

---

## 3. 12개 기사별 핵심 (올라마 추출 → 원문 대조 통과분 중심)

| # | 기사 | 문서 자체 판정 | 대조 통과한 핵심 로직 |
|---|---|---|---|
| 01 | Claude.ai 2주 만에 3배 빠르게 | 보강 도입 | 사용자 여정 성능 장부, 대리지표 검증 관문, 성능 톱니 |
| 02 | Ollama OpenAI 호환성 | 도입 | OpenAI 호환 전송 어댑터, 능력 명세(SUPPORTED/UNSUPPORTED/UNVERIFIED), 네이티브 탈출구 |
| 03 | Ollama OpenAI 형식 호출 | 신규 로직 없음 | 프로바이더 교체 불변식(판단 체계는 바뀌면 안 됨) |
| 04 | Ollama 도구 호출 | 강력 도입 | 도구 제안/실행 방화벽, 작업별 도구 허용목록 |
| 05 | Ollama 웹 검색 API | 강력 도입 | 검색 증거 사다리, 검색 권한 방화벽, 외부 전송 최소화, 검색 예산 관문 |
| 06 | Ollama v0.1.33 신모델 | 강력 도입 | 모델 자격 관문(실행 가능 ≠ 작업자 승인) |
| 07 | OpenClaude(유출 코드 파생) | 코드 보류 / 구조만 추출 | 런타임·프로바이더 분리, 도구 호출 정규화 |
| 08 | Function Calling vs MCP | 신규 도입 | MCP 경계 어댑터, 발견/인가 분리, 서버 신뢰 등록부, 지연 능력 로딩, 버전 고정 |
| 09 | MCP로 IntelliJ 연동 | 강력 도입 | 작업공간 범위 고정 |
| 10 | OpenLM 다중 LLM 클라이언트 | 부분 중복 + 보강 | 결과 봉투 정규화, 실패 분류 정규화, 실패 인식 대체 경로, 어댑터 의존성 방화벽 |
| 11 | Ollama Python/JS 라이브러리 | 도입 | 클라이언트 SDK 동작 고정 |
| 12 | Laya(Jev 대안) | "생각할 필요 없는 판단을 LLM에 시키지 않는다" | 인용 통과 0건 → 이름만 확인(C45~C50), 판단 근거로 쓰지 않음 |

---

## 4. 외부 자료와의 비교

### 4.1 기사 내용이 외부 자료로 확인된 것 (사실)

- **01번 수치**: Anthropic은 사용량 95%를 차지하는 여정 4개를 측정해 3,000건 이상 변경을 2주에 배포했고 롤백이 없었다. 예: 새 페이지 입력 가능 시점 p75 3.1초→0.55초. → "측정 먼저, 개선은 작게, 개선치는 고정"이라는 01번 해석과 일치.
- **05·02·04번**: Ollama는 웹 검색 API, OpenAI 호환 엔드포인트의 도구 지원, Anthropic Messages API 호환(2026-01)까지 제공한다. → 로컬 모델에 도구·검색 권한이 "기술적으로" 열렸다는 뜻이며, 그래서 **실행 권한 분리(04번 C09)**가 필수가 된다.
- **07번**: OpenClaude는 2026-03-31 npm 소스맵 유출본의 파생이다. → 코드 직접 도입 보류 판정이 맞다.
- **08번**: MCP 도구 정의를 매 턴 선로딩하면 서버 4개 기준 메시지당 약 7,000토큰, 무거운 구성은 50,000토큰 이상. 지연 로딩(도구 검색)으로 85% 감소, 코드 실행 방식으로 150k→2k(98.7%) 사례.

### 4.2 논문이 더해 준 것 (기사에 없던 근거)

- **The Complexity Trap (arXiv 2508.21433, NeurIPS DL4Code 2025)**: 오래된 도구 관찰을 그냥 가리는 방식이 LLM 요약과 해결률이 같거나 약간 높고 비용은 절반. → UAOS는 **요약 에이전트를 추가하지 말고, 결정적 가리기부터** 해야 한다. 이는 전역 규칙 "결정적 추출 먼저"와 같은 방향.
- **ACON(arXiv 2510.00615)**, **SWE-Pruner(2601.16746)**, **Squeez(2604.04979)**: 압축 지침을 실패 분석으로 개선, 작업 조건부로 도구 출력을 잘라냄. → P2 이후 후보. 모델 학습이 필요 없는 ACON 방식만 UAOS RSI(증거 제안→관문)와 궁합이 맞다.
- **Execution Instability 연구(arXiv 2608.06503)**: 압축이 장기 작업을 불안정하게 만들 수 있다. → 압축 도입 시 반드시 회귀 관문(인수 테스트 동일 통과)을 둔다.

### 4.3 커뮤니티(일화, 증거 아님)

- CLAUDE.md는 매 질의마다 다시 전송되므로 가장 비싼 상시 문맥이라는 경험담이 반복된다. 설정 도중 변경은 프롬프트 캐시를 깨뜨린다. → "상시 적재 문맥 예산"을 따로 재야 한다(15번 종합본 14절과 일치).
- Claude Code를 Ollama로 돌리는 "월 0원" 사례가 많지만 64K 이상 문맥·도구 호출 품질이 전제다. → UAOS의 "올라마 = 계산기" 원칙을 바꿀 근거는 되지 않는다. 이번 실측 인용 정확도 48%가 반례다.

### 4.4 기존 종합본(13~15번)과의 차이

- 15번이 제안한 5개(문맥 입장 관문, 한 번 읽기 공유 증거 캐시, 도구 출력 관문, 공급자별 예산 중개, 토큰 회귀 관문)는 **방향 동의**.
- 차이 1: "한 번 읽기 공유 증거 캐시"는 이미 `olla.py`의 읽기 비용 추정·요약본 우선 규칙(`read_once`, `DIGEST_MIN_TOKENS`)으로 일부 존재 → 신규가 아니라 **확장**이다.
- 차이 2: `broker/core.py`는 프로세스 잠금 중개기이지 예산 중개기가 아니다. 이름이 같아 혼동 위험 → 새 기능은 `budget_broker`가 아닌 다른 이름을 권장.
- 차이 3: 15번은 모델 품질 문제를 다루지 않았다. 이번 실측(인용 48%)으로 **모델 자격 관문을 P1로 올린다.**

---

## 5. 도입 계획 (작은 계약 단위)

각 항목은 "관문(gate)을 먼저 정하고, 통과하면 끝"이다. 코드는 아직 바꾸지 않았다.

### U-TOK-1 도구 출력 토큰 관문 + 관찰 가리기 (P1)
- 무엇: 작업자에게 되돌리는 도구 출력에 상한(예: 결과당 N토큰)을 두고, 넘으면 머리/꼬리+파일 포인터로 대체. 최근 k턴보다 오래된 관찰은 "[생략: 파일경로#해시]"로 가린다.
- 왜 이 방식: 논문상 결정적 가리기가 LLM 요약과 성능 동등·비용 절반. 로컬 모델 요약은 이번 실측처럼 원문 충실도가 낮다.
- 관문: 기존 `pilot` 인수 테스트 통과율 동일 + 같은 작업 3회 평균 입력 토큰 감소를 `usage_ledger` 수치로 비교. 감소 없으면 폐기.

### U-TOK-2 문맥 입장 관문 (P1)
- 무엇: 작업 계약(PLAN 카드)에 `context_allow: [파일, 도구, MCP 서버]`를 두고, 목록 밖 항목은 작업자 호출에 싣지 않는다.
- 관문: 입장 거부된 항목 때문에 인수 실패가 생기면 목록 누락으로 기록(자동 확장 금지). 호출당 입력 토큰을 전후 비교.

### U-MQ-1 작업별 모델 자격 관문 + 고정 (P1)
- 무엇: `(provider, model tag, digest, 작업 유형)`별로 자격 기록. 작업 유형 예: `list_extract`, `verbatim_quote`, `summarize`, `code_edit`.
- 초기값(이번 실측): `qwen3.5-32k` → `list_extract` 90% QUALIFIED, `verbatim_quote` 48% REJECTED.
- 관문: 고정 fixture 12건(이번 기사 12건과 해시)으로 재측정. 모델 digest가 바뀌면 자격 자동 승계 금지.

### U-TOK-3 토큰 톱니 (P2)
- 무엇: `rsi gate`에 토큰 축 추가. 검증된 최저 토큰량을 기준선으로 저장, 품질이 같아도 토큰이 기준선의 1.2배를 넘으면 실패. (1.2 = 실행 간 변동 흡수용 초기값, 3회 측정 후 재조정)
- 전역 규칙의 "3배 회귀 = 실패"보다 촘촘한 조기 경보 역할.

### U-SEC-1 도구 실행 방화벽 명문화 (P2)
- 무엇: 올라마·외부 모델의 tool call은 `PROPOSED` 상태로만 기록하고, 실행은 UAOS 정책 판정 후에만. `POLICY_DENIED`는 대체 경로 없이 종료(10번 C41).

### 도입하지 않을 것
- 빠른 판단 평면(12번): 원문 대조 0/6, 자체 데이터 보정 근거 없음.
- 다중 프로바이더 라이브러리 흡수(07·10번): 어댑터 1개 뒤로 격리하는 원칙만 채택.
- 요약 전용 에이전트 추가: 논문상 가리기 대비 이득 없음.

---

## 6. 확인된 사실 / 가정 / 모름

- **사실**: 올라마 12회 호출 결과·토큰·시간(위 표), 코드 검색 결과(`admission`·`tool_output`·`masking`·`ratchet`·`journey` 0건), 외부 수치(출처 아래).
- **가정**: U-TOK-1/2가 UAOS 작업에서도 논문 수준(비용 약 50%)의 절감을 낸다는 것. 측정 전까지 UNMEASURED.
- **모름**: Claude 쪽 토큰이 실제로 얼마나 절감됐는지(대조 실험 없음), 더 큰 로컬 모델(예: `qwen2.5-coder:7b`)의 인용 정확도.

## 7. 출처

- [How we made claude.ai 3x faster in two weeks](https://claude.dev/blog/how-we-made-claude-ai-faster/) · [Help Net Security 요약](https://www.helpnetsecurity.com/2026/09/24/anthropic-claude-ai-faster/)
- [Ollama Web search 문서](https://docs.ollama.com/capabilities/web-search) · [Ollama Tool support](https://ollama.com/blog/tool-support) · [Ollama OpenAI Compatibility](https://ollama.readthedocs.io/en/openai/)
- [OpenClaude (Gitlawb)](https://github.com/Gitlawb/openclaude) · [Claude Code 유출 요약](https://actionablenotes.substack.com/p/the-claude-code-leak-a-mini-brief)
- [MCP Tool Search 가이드](https://www.atcyrus.com/stories/mcp-tool-search-claude-code-context-pollution-guide) · [MCP 토큰 오버헤드 분석](https://docs.bswen.com/blog/2026-04-24-mcp-token-overhead/) · [Code execution with MCP 98.7%](https://brightbean.xyz/blog/code-execution-mcp-efficient-ai-agents/) · [MCP 토론 #629](https://github.com/orgs/modelcontextprotocol/discussions/629)
- 논문: [The Complexity Trap 2508.21433](https://arxiv.org/abs/2508.21433) · [저장소](https://github.com/JetBrains-Research/the-complexity-trap) · [ACON 2510.00615](https://arxiv.org/abs/2510.00615) · [SWE-Pruner 2601.16746](https://arxiv.org/pdf/2601.16746) · [Squeez 2604.04979](https://arxiv.org/pdf/2604.04979) · [압축 실행 불안정성 2608.06503](https://arxiv.org/html/2608.06503v1) · [Awesome-Agent-Context-Compression](https://github.com/YerbaPage/Awesome-Agent-Context-Compression)
- 커뮤니티(일화): [Claude Code 프롬프트 캐싱 문서](https://code.claude.com/docs/en/prompt-caching) · [Ollama + Claude Code 설정기](https://www.morphllm.com/ollama-claude-code)
===END===

===EDIT: v7_harness/review.py===
<<<<<<< SEARCH
def review_prompt(task_id: str, manual_text: str, diff: str) -> str:
    return (f"[{task_id}] Review this change against its contract. The diff below is the complete change: judge from it. "
            "Read a file only to confirm one specific counterexample, and answer within a few turns.\n\n"
            f"## Contract\n{manual_text}\n\n## Diff\n```diff\n{diff[:MAX_DIFF_CHARS]}\n```\n\n"
            f"Reply with exactly one JSON object: {SCHEMA_HINT}")
=======
def review_prompt(task_id: str, manual_text: str, diff: str, spill_path: str | Path | None = None) -> str:
    # U52: a plain diff[:MAX] cut the tail silently while the prompt called the diff complete; the gate keeps head and
    # tail, marks the cut, and the prompt says the diff is partial so the reviewer reads the changed files instead.
    from .output_gate import gate_output

    gated = gate_output(diff, MAX_DIFF_CHARS, spill_path)
    scope = ("The diff below is PARTIAL (see the U52 OUTPUT CUT marker): read the changed files in the current "
             "directory for the omitted part before judging it. " if gated.truncated else
             "The diff below is the complete change: judge from it. ")
    return (f"[{task_id}] Review this change against its contract. {scope}"
            "Read a file only to confirm one specific counterexample, and answer within a few turns.\n\n"
            f"## Contract\n{manual_text}\n\n## Diff\n```diff\n{gated.text}\n```\n\n"
            f"Reply with exactly one JSON object: {SCHEMA_HINT}")
>>>>>>> REPLACE

===EDIT: v7_harness/review.py===
<<<<<<< SEARCH
    prompt = review_prompt(task_id, manual_text, bundle_diff(Path(source), staging, changed))
=======
    # The spill goes in the run folder, never in staging: a file written there would become part of the bundle.
    prompt = review_prompt(task_id, manual_text, bundle_diff(Path(source), staging, changed), runs / "review.diff")
>>>>>>> REPLACE

===EDIT: v7_harness/pilot.py===
<<<<<<< SEARCH
                    accept_log_path.write_bytes(combined[-4000:])
=======
                    # U52: head+tail with a marked cut instead of a silent tail; the full log sits beside it.
                    from .output_gate import gate_output

                    gated = gate_output(combined.decode("utf-8", "replace"), 4000,
                                        runs_dir / "acceptance.full.log")
                    accept_log_path.write_text(gated.text, encoding="utf-8", errors="replace")
>>>>>>> REPLACE

===EDIT: v7_harness/judge.py===
<<<<<<< SEARCH
    tail = log.read_text(encoding="utf-8", errors="replace")[-ACCEPTANCE_TAIL_CHARS:] if log.is_file() else "(no log)"
=======
    # U52: head+tail with a marked cut; the paid judge must not take a cut log for the whole one.
    from .output_gate import gate_output

    tail = (gate_output(log.read_text(encoding="utf-8", errors="replace"), ACCEPTANCE_TAIL_CHARS).text
            if log.is_file() else "(no log)")
>>>>>>> REPLACE


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
