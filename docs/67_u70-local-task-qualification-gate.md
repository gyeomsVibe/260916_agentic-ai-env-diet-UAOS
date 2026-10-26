# U70 로컬 모델 작업유형 자격 관문

## 왜 필요한가

U51은 로컬 모델(Ollama)의 자격을 **작업유형(task type)별로, 모델 파일의 digest에 묶어** 기록하는 도구(`model_qualification qualify --record`)를 만들었다. 그러나 그 기록을 읽는 곳이 없었다. 그래서 U67-O1b는 기호 목록 JSON 추출을 `qwen2.5-coder:7b`에 그대로 보냈다. 답은 같은 항목을 되풀이했고 형식도 맞지 않았다.

채점기에도 구멍이 있었다. 참인 항목 하나를 네 번 쓰면 4/4로 계산됐다. 쉬운 줄 하나를 반복하는 것만으로 합격선(QUALIFY_MIN)을 넘을 수 있었다.

## 무엇을 바꿨나

1. **중복은 실패로 센다** — `score_extraction`은 같은 항목의 두 번째 사본부터 통과로 치지 않는다. 기준 커밋 94285bd에서 `alpha`×4는 (4, 4)였고, 이제 (1, 4)다.
2. **매뉴얼의 `task_type:`** — 계약에 `task_type: list_extract` 또는 `verbatim_quote`를 쓸 수 있다. 모르는 값은 lint 오류 `UNKNOWN_TASK_TYPE`이다.
3. **pilot run 관문** — 작업자가 `local` 또는 `cascade`이고 계약에 작업유형이 있으면, Ollama를 부르기 **전에** `local_admission`이 판정한다.
   - 기록 위치: `<source>/.coord/qualification`. `qualify --record`에 이 경로를 주면 된다.
   - 모델: `--model` → 계약의 `model` → `ollama_worker`의 기본 모델 순서로 정한다. 실제 작업자에 넘어가는 순서와 같다.
   - digest는 호출 시점에 Ollama `/api/tags`에서 읽는다. 같은 이름으로 다시 받은 모델은 옛 판정을 물려받지 못한다(`UNQUALIFIED_DIGEST_CHANGED`).
   - `QUALIFIED`만 통과한다. `REJECTED`, `UNQUALIFIED`, digest 변경, Ollama 응답 없음(`MODEL_NOT_INSTALLED`)은 모두 거부한다. 결과는 `state: REFUSED`, `error_class: LOCAL_NOT_QUALIFIED`, 종료 코드 2다.
   - `--approve`는 저장된 번들을 재생할 뿐 모델을 부르지 않으므로 다시 판정하지 않는다.
   - 작업유형이 없는 매뉴얼은 전과 같이 동작한다. 관문은 작업유형을 선언한 작업에만 걸린다.
4. **결정적 경로 `v7_harness/symbols.py`** — 파이썬 파일의 함수·클래스·메서드·대문자 상수를 줄 번호와 함께 AST로 뽑는다. 모델 토큰은 0이다. "이 파일이 무엇을 정의하나"는 이제 모델에 묻지 않는다.
   - 실행: `python -m v7_harness.symbols <파일>`

## 왜 이렇게 정했나

- **통과는 QUALIFIED 하나뿐이다.** 자격 기록이 없다는 것은 "모른다"는 뜻이지 "괜찮다"가 아니다. 로컬 호출은 유료 토큰은 0이지만 벽시계와 검증 비용이 든다. 실패가 예상되는 호출을 막는 쪽이 싸다.
- **digest를 매번 읽는다.** 이름은 사람이 붙인 표시일 뿐이고, 같은 이름 아래 모델 파일이 바뀔 수 있다.
- **Ollama가 응답하지 않으면 거부한다.** 추측으로 허용하지 않는다(fail-closed).

## 운영 상태(2026-09-28)

- 이 데스크에는 아직 `.coord/qualification` 기록이 없다. 따라서 작업유형을 선언한 로컬 작업은 지금 모두 `UNQUALIFIED`로 거부된다.
- 로컬 모델을 다시 쓰려면 먼저 이 명령으로 측정·기록해야 한다.
  - `python -m v7_harness.model_qualification qualify --model qwen2.5-coder:7b --sources <문서 폴더> --record .coord/qualification`
- 절감량은 통제 비교 전까지 `UNMEASURED`다.

## 고정 인수

`tests/test_u70_local_qualification.py`가 확인하는 것:

- 중복 채점
- 판정 여섯 가지: QUALIFIED, REJECTED, digest 변경, 모르는 유형, 미설치, 연결 실패
- pilot run에서 작업자가 시작되지 않음
- 승인 재생과 작업유형 없는 매뉴얼은 관문 밖
- lint
- AST 기호 추출
