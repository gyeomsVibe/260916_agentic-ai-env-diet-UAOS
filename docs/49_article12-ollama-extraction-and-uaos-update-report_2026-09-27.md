# 49. 기사 12건 올라마 재분석 + 외부 자료 비교 → UAOS 개선·업데이트 보고서

- 작성: Claude Code (Codex 대행 아님, Codex 복귀 시 재검토 대상), 2026-09-27
- 입력: `docs/user-docs/# UAOS 기사 분석 보고서 01~12.md` (13~15번 종합본은 비교 기준으로만 사용)
- 산출물 등급: 유지(maintained) 문서. 추출 원본은 `.work/article_ollama_20260927/`(일회성, 커밋 제외)

---

## 1. 결론 먼저

**UAOS에 새 에이전트나 새 프로바이더 계층을 더하지 말고, "문맥에 무엇이 들어가도 되는가"를 재는 관문 3개를 먼저 넣는다.**

| 순위 | 도입 로직 | 출처 기사 | 현재 코드 상태 | 외부 근거 |
|---|---|---|---|---|
| P1 | 도구 출력 토큰 관문(Tool Output Token Gate) + 오래된 관찰 가리기(observation masking) | 08, 15번 종합 | 없음(`grep tool_output\|masking` 0건) | 관찰 토큰이 턴의 약 84%, 단순 가리기로 비용 절반·성능 동등(arXiv 2508.21433, **SWE-agent 궤적에서만 측정**) |
| P1 | 문맥 입장 관문(Context Admission Gate) = 지연 능력 로딩(Lazy Capability Loading) | 08, 04(C10) | 없음(`admission` 0건) | MCP 도구 정의 선로딩 1회 약 7k~50k 토큰, 도구 검색 지연 로딩으로 85% 감소(**블로그 보고치, 1차 측정 아님, UAOS 미측정**) |
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
- **08번**: MCP 도구 정의를 매 턴 선로딩하면 서버 4개 기준 메시지당 약 7,000토큰, 무거운 구성은 50,000토큰 이상. 지연 로딩(도구 검색)으로 85% 감소, 코드 실행 방식으로 150k→2k(98.7%) 사례. **정정(2026-09-28)**: 85%·98.7%는 아래 출처의 블로그·가이드가 전하는 보고치이며, 이 저장소가 재현하거나 UAOS에서 측정한 값이 아니다(UNMEASURED). U50 관문의 효과 근거로 쓰지 않는다.

### 4.2 논문이 더해 준 것 (기사에 없던 근거)

- **The Complexity Trap (arXiv 2508.21433, NeurIPS DL4Code 2025)**: 오래된 도구 관찰을 그냥 가리는 방식이 LLM 요약과 해결률이 같거나 약간 높고 비용은 절반. **범위(2026-09-28 정정)**: 이 결과는 SWE-agent 궤적(SWE-bench Verified)에서 잰 것이고, UAOS의 `pilot`·`judge` 경로에서는 측정하지 않았다. → UAOS는 **요약 에이전트를 추가하지 말고, 결정적 가리기부터** 해야 한다. 이는 전역 규칙 "결정적 추출 먼저"와 같은 방향.
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

각 항목은 "관문(gate)을 먼저 정하고, 통과하면 끝"이다. 작성 당시(2026-09-27)에는 코드를 바꾸지 않았다. 이후 진행은 5.0절에 적는다.

### 5.0 판정 반영 현황 (2026-09-28 정정)

Codex 판정은 ACCEPT-WITH-CORRECTIONS였다. 그 판정에 따라 이 문서의 계획을 카드 번호에 연결하고, 순서를 U51 → U50 → U52 → U54/U55 계약으로 정했다. 세 카드는 Codex 부재 중 대행 지휘자(Claude, 사용자가 승인자로 지정)가 독립 판정해 적용했다. Codex가 복귀하면 다시 검토할 대상이다.

| 계획 | 카드 | 상태 | 근거 |
|---|---|---|---|
| U-MQ-1 모델 자격 관문 | U51-R2 | 적용(커밋 8526bc5) | 인수 16/16. 위조 `score`와 가짜 `--expect-digest`는 기록 0건(R1b 반려 사유 해소) |
| U-TOK-2 문맥 입장 관문 | U50-R2b | 적용(커밋 1d52fc1) | 311 OK. 입장 뒤 폴더 바꿔치기(TOCTOU) 재현에서 누출 0 |
| U-TOK-1 도구 출력 관문 | U52-R2 | 적용(커밋 36d5ea2) | 246 OK. 표시(marker) 포함 전체 길이 상한을 cap 1~3000에서 한 번도 넘지 않음 |
| U-TOK-1 관찰 가리기(최근 k턴) | U52-M | 미결 | 이전 관찰을 들고 다니는 운영 경로가 없어 `mask_observations`는 삭제했다. 가리기가 붙기 전까지 유료 S2 측정은 막혀 있다 |
| — | U53 | 예약 | 다른 카드가 번호를 쓰고 있다(U53-F1) |
| U-SEC-1 도구 실행 방화벽 | U54 | BACKLOG, 계약 초안만 | 먼저 틈(gap)을 감사(audit)한다. 코드 변경은 다음 단계 |
| U-TOK-3 토큰 톱니 | U55 | BACKLOG, 계약 초안만 | 1.2배라는 값은 3회 측정으로 보정(calibration)하기 전에는 관문으로 쓰지 않는다 |

세 커밋은 PR https://github.com/gyeomsVibe/260916_agentic-ai-env-diet-UAOS/pull/20 에 있다(작성 시점 기준 병합 전).

### U-TOK-1 도구 출력 토큰 관문 + 관찰 가리기 (P1)
- 무엇: 작업자에게 되돌리는 도구 출력에 상한(예: 결과당 N토큰)을 두고, 넘으면 머리/꼬리+파일 포인터로 대체. 최근 k턴보다 오래된 관찰은 "[생략: 파일경로#해시]"로 가린다.
- 왜 이 방식: 논문상(SWE-agent 궤적 한정) 결정적 가리기가 LLM 요약과 성능 동등·비용 절반. 로컬 모델 요약은 이번 실측처럼 원문 충실도가 낮다.
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

- **사실**:
  - 올라마 12회 호출 결과·토큰·시간(위 표)
  - 작성 시점(2026-09-27)의 코드 검색 결과: `admission`·`tool_output`·`masking`·`ratchet`·`journey` 0건. U50~U52 적용으로 이 결과는 이제 달라졌다.
  - 외부 수치(출처 아래)는 보고치다. 85%·98.7%는 블로그 보고이고, 가리기 결과는 SWE-agent 한정이다.
- **가정**: U-TOK-1/2가 UAOS 작업에서도 논문 수준(비용 약 50%)의 절감을 낸다는 것. 측정 전까지 UNMEASURED다. U50·U52 적용은 상한과 안전성만 증명했고, 토큰 절감은 증명하지 않았다.
- **모름**: Claude 쪽 토큰이 실제로 얼마나 절감됐는지(대조 실험 없음), 더 큰 로컬 모델(예: `qwen2.5-coder:7b`)의 인용 정확도.

## 7. 출처

- [How we made claude.ai 3x faster in two weeks](https://claude.dev/blog/how-we-made-claude-ai-faster/) · [Help Net Security 요약](https://www.helpnetsecurity.com/2026/09/24/anthropic-claude-ai-faster/)
- [Ollama Web search 문서](https://docs.ollama.com/capabilities/web-search) · [Ollama Tool support](https://ollama.com/blog/tool-support) · [Ollama OpenAI Compatibility](https://ollama.readthedocs.io/en/openai/)
- [OpenClaude (Gitlawb)](https://github.com/Gitlawb/openclaude) · [Claude Code 유출 요약](https://actionablenotes.substack.com/p/the-claude-code-leak-a-mini-brief)
- [MCP Tool Search 가이드](https://www.atcyrus.com/stories/mcp-tool-search-claude-code-context-pollution-guide) · [MCP 토큰 오버헤드 분석](https://docs.bswen.com/blog/2026-04-24-mcp-token-overhead/) · [Code execution with MCP 98.7%](https://brightbean.xyz/blog/code-execution-mcp-efficient-ai-agents/) · [MCP 토론 #629](https://github.com/orgs/modelcontextprotocol/discussions/629)
- 논문: [The Complexity Trap 2508.21433](https://arxiv.org/abs/2508.21433) · [저장소](https://github.com/JetBrains-Research/the-complexity-trap) · [ACON 2510.00615](https://arxiv.org/abs/2510.00615) · [SWE-Pruner 2601.16746](https://arxiv.org/pdf/2601.16746) · [Squeez 2604.04979](https://arxiv.org/pdf/2604.04979) · [압축 실행 불안정성 2608.06503](https://arxiv.org/html/2608.06503v1) · [Awesome-Agent-Context-Compression](https://github.com/YerbaPage/Awesome-Agent-Context-Compression)
- 커뮤니티(일화): [Claude Code 프롬프트 캐싱 문서](https://code.claude.com/docs/en/prompt-caching) · [Ollama + Claude Code 설정기](https://www.morphllm.com/ollama-claude-code)
