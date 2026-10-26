# UAOS 최종 사용자 안내와 완료 브리핑

- 상태: 구현 완료, 2026-09-25 Codex 독립 검증
- 범위: 로컬 UAOS 실행·조율·사용량 기록·증거 관문형 RSI
- 승인 제외: 삭제, 원격 push, 배포·공개 게시, 결제, 계정·자격증명·권한·시스템 설정 변경

## 1. 가장 짧은 사용법

1. 프로젝트 루트에서 `.coord/PLAN.md`의 다음 `READY` 작업 하나를 고른다.
2. 바꿀 파일과 기계적 인수 명령을 정한다.
3. 구체적 반복 작업이면 `--worker local`, 설계·탐색이면 `--worker agy`를 쓴다.
4. 먼저 파일럿을 실행하고 `summary.json`의 `verdict_hint=PASS`와 실제 diff를 확인한다.
5. 같은 작업 ID와 번들 ID로 `--approve`해야만 원본에 반영된다.

```powershell
python -m v7_harness.cli pilot run --task U##_NAME --source . --prompt-file .coord/tasks/prompt.md --accept-cmd "python -m unittest tests.test_target" --work-dir .work/pilot_U##_NAME --worker local
python -m v7_harness.cli pilot run --task U##_NAME --source . --prompt-file .coord/tasks/prompt.md --accept-cmd "python -m unittest tests.test_target" --work-dir .work/pilot_U##_NAME --worker local --approve <bundle_id>
```

## 2. 도구별 역할

- Codex: 계획, 승인 경계, 인수 기준, diff 검토, 최종 판정.
- Claude Code: Codex 활동 중 부관, Codex 부재 중 동일 관문을 적용하는 대행자.
- Antigravity: 모호한 설계·탐색 또는 로컬 작업자 실패 후 제한된 원격 작업자. 자기 결과를 단독 승인하지 않는다.
- Ollama: 비용 0원의 전자계산기·유선 전화기. 요약·변환·정확한 치환·테스트 틀 같은 기계적 작업만 수행하며 판정권은 없다.

## 3. 토큰예산 절약 모드

- 남은 사용률을 임의 토큰 수로 환산하지 않는다.
- 고정 프롬프트는 앞에, 작업별 가변 정보는 뒤에 둬 캐시 입력을 안정화한다.
- 한 단계는 한 작업자만 쓴다. 같은 과제를 여러 유료 도구에 중복 위임하지 않는다.
- 로컬 작업자가 3회 같은 원인으로 실패하면 중단하고, 필요할 때만 원격 작업자에게 1회 승격한다.
- 실제 계정 한도 절감은 동일 창 전후 측정 전까지 `UNMEASURED`다.

## 4. 기록과 RSI

- 파일럿 실행은 `.coord/usage/runs.jsonl`에 `uaos-usage-v2` 행을 자동 추가한다.
- 직접 `olla` 명령의 원시 이벤트는 환경 변수 `OLLA_USAGE`가 가리키는 전역 JSONL에 남는다.
- 10개의 같은 유형 유효 표본이 쌓이면 성공률, 재작업률, 벽시계, 토큰, 원격 승격률을 비교한다.
- 개선안은 한 번에 1개만 시험하며 고정 인수·대조군·독립 검증을 통과해야 승격한다.
- P1, 품질 저하, 또는 3배 비용 회귀가 있으면 개선안을 채택하지 않는다.

## 5. 운영 점검

```powershell
python .coord/runs/verify_codex_return.py
python -m unittest discover -s tests -p "test_*.py"
python -m compileall -q v7_harness tests
```

2026-09-25 검증 결과는 복귀 점검 13/13, 전체 회귀 580개 통과·1개 건너뜀, compileall exit 0이다. U23은 밑줄 포함 메시지 ID 복구와 동일 P1 1회 기상 반례를 통과했다. U27은 Windows 다중 프로세스 40건 단위 테스트와 8프로세스×25건 숨은 인수, 잠금 시간초과 fail-closed, 실제 파일럿 자동 append를 통과했다.

## 6. 실패 시

- `SOURCE_DIVERGED`: 다른 쓰기 주체가 원본을 바꿨다. 원인을 확인하고 새 작업 ID로 재실행한다.
- `NEEDS_RECONCILIATION`: `python -m v7_harness.cli pilot reconcile --task <ID> --work-dir <DIR>`로 먼저 정리한다.
- `REWORK`: 번들을 반영하지 말고 인수 로그와 diff를 고친다.
- `BLOCKED`: 같은 원인으로 반복 호출하지 않는다. 외부 상태 변화 또는 사용자 승인 대상인지 구분한다.
- 빈 출력·산출물 없음·자기 완료 보고는 성공 증거가 아니다.

## 7. 완료 판정과 남은 불확실성

로컬 구현과 검증 체계는 완료됐다. R1의 실패 측정은 역사적 표본으로 보존되고 R2/R4가 유효 대체 측정이다. 지휘자 입력 평균 −76.7%, 출력 −97.0%는 해당 3개 통제 과제 결과이며, 실제 구독 계정 한도 절감률과 장기 운영 효과는 아직 `UNMEASURED`다. 이번 최종 수리에서도 Antigravity가 큰 원격 토큰을 사용했으므로 “유료 토큰 0” 또는 “100% 절감”으로 보고해서는 안 된다.
