# U281: Luna와 Antigravity Flash 보조 작업자

유지 문서 · Codex/Claude 교차 검토 · 2026-10-29

## 범위와 현재 상태

사용자는 GPT-6 Luna와 Antigravity의 적합한 보조 모델을 기존 Haiku 작업자와 같은
계층에 추가하고 병합·런타임 반영·실가동을 요청했다. 이 변경은 기존 공용
`worker_routing.py`를 확장한다. 별도 모델 실행기나 예산 우회 경로를 만들지 않는다.

| 계층 | 모델 | 경로와 경계 |
|---|---|---|
| 결정적 처리 | 모델 없음 | 정확한 추출·해시·검사는 계속 최우선 |
| 로컬 작업자 | qwen2.5-coder:7b | 기존 자격·범위·문맥 상한 유지 |
| Claude 보조 | claude-haiku-5-5 | 기존 동작·자격·예산 관문 유지 |
| Codex 보조 | gpt-6-luna | 명시적 remote_model 선택; 네이티브 managed smoke 응답 확인 |
| Antigravity 보조 | gemini-3.8-flash-low | 현재 CLI 목록에 존재; Gemini 주간 한도 때문에 실제 추론 보류 |

READY는 **선택 제안**이다. 모든 경로는 execution_authorized=false를 유지하며,
부모의 계약·고정 인수·실제 모델/사용량·비용 판정 없이 실행 권한을 부여하지 않는다.
사용량이나 비용이 UNKNOWN이면 자동 실행 자격으로 승격하지 않는다. 작은 모델은
최종 승인·보안·복잡한 동시성 판정을 맡지 않는다. 다른 모델로 자동 대체하지 않는다.

## 모델 선정 근거

[OpenAI Models](https://learn.chatgpt.com/docs/models)와
[Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)는 Luna의
좁고 반복적인 작업 용도와 모델 고정 설정을 설명한다. Codex 프로필은
`.codex/agents/uaos-luna-worker.toml`이며, 부모 권한을 바꾸지 않고 지원되는 기능만 제한한다.

[Antigravity Models](https://antigravity.google/docs/models)와
[Headless mode](https://antigravity.google/docs/cli/headless/)에 따라 Flash3.8을 선택했다.
실제 `agy models`에서도 `gemini-3.8-flash-low`를 확인했다. API의 Flash-Lite는 이
구독 CLI 목록에 없어 선택하지 않았다. GPT-OSS는 문서상 가까운 제거 일정이 있어
장기 기본 보조 모델로 선택하지 않았다. API 가격을 구독 한도 절감률로 바꾸지 않는다.

## 실제 실행 경로와 발견된 제약

Luna managed worker는 도구를 쓰지 않고 지정된 JSON 결과를 반환했다. 이는 모델의
가용성과 고정 출력 smoke 확인이며 성능 벤치마크가 아니다. 해당 managed 경로는
호출별 토큰 영수증을 제공하지 않아 비용 관문은 UNKNOWN이다.

Flash의 사용자 정의 에이전트 프로필은 공식 위치에 복사해 바이트를 확인했으나,
현재 CLI의 `--agent uaos-flash-worker` 조회가 반복해서 unknown agent를 반환했다.
mainAgent 플래그만 바꾸는 한 번의 가설 검증도 실패했고 원래 바이트를 복구했다.
같은 실패를 더 반복하지 않는다. Claude는 기존 `AgyRequest.model`과
`pilot run --model`을 이용하는 모델 지정 경로로 전환하는 데 동의했다.
따라서 현재 CLI에서 Flash 작업에 `--agent` 사용이나 에이전트 발견 성공을 가정하지 않는다.
`.agents/agents/uaos-flash-worker.md`는 지원 클라이언트용 선언 자료이며, 파일 배치와
현재 클라이언트에서의 활성화는 별도 상태다.

모델 지정 경로는 기존 pilot의 허용 경로·변경 거부·모델 신원·비용 관문을 유지해야 한다.
네이티브 `/usage`는 Gemini 주간 잔량 0%, 초기화 시각 2026-11-01T05:51:11Z를 보고했다.
한국 시각으로 11월 1일 14:51:11이다. 한도 밖 추론·유료 크레딧·다른 모델 대체를 실행하지 않았다.

## 독립된 읽기 전용 카탈로그 런타임

기존 UAOS 전체 admission HOLD를 해제하지 않는다. 검토된 `worker_routing.py`와
작은 `scripts/helper_router.py`만 별도의 내용 주소 기반 런타임에 배치한다.
기존 `~/.uaos/runtime/current.json`과 전체 실행기는 바꾸지 않는다.

카탈로그는 부모가 제공한 task/availability JSON을 표준입력으로 받아 선택 결과만
반환한다. provider 호출·프로세스 생성·소스 변경 기능은 없다. 부모는 설치된
`~/.uaos/helper_router.py`를 반드시 `python -I`로 호출한다. 격리 모드가 아니면
shadow 가능한 모듈을 import하기 전에 거부한다. 번들 ID는 원격 병합 커밋과
파일 SHA256을 포함하며, 검증한 모듈 바이트를 그대로 실행해 재읽기 경합을 피한다.

이 런타임은 조회 경로의 실제 설치이지, Flash 추론 성공이나 전체 UAOS 배포 승인이 아니다.
부모는 반환된 worker/model을 기존 네이티브 경로에 전달하고 별도 인수를 수행한다.

## 검증과 보존된 실패

로컬 Ollama의 첫 파일럿은 인수를 통과했지만, 독립 추가 검사에서 모델 ID가 list일 때
TypeError가 재현됐다. 수정 파일럿은 기존 인수와 추가 음성시험을 통과했다.
기존 Haiku 평가기를 바꾸지 않았다. 계약 lint가 20줄보다 큰 apply를 거부한 기록을
보존하고 수정 제안도 로컬 작업자를 거쳤다. 원래 worker 모듈은 정확한 번들로 반영했다.

전체 unittest는 stage에서 Git 상대경로 문서 검사 1건이 실패했다. 원본 체크아웃에서
그 검사가 통과함을 확인한 뒤 전체를 다시 실행해 2779개, skip7, exit0을 확인했다.
이후 새 카탈로그 경계에 8개 독립 검사를 추가했다. 관련 29개 unittest와 잘못된 모델
입력 4개가 통과했다. 이 숫자를 하나의 전체 실행 결과로 합쳐 표시하지 않는다.

Claude의 추가 검토는 가짜 json.py/hashlib.py가 해시 검사 전에 import될 수 있다는
반례를 제시했다. `-I`와 사전 거부를 적용했으며, 악성 추가 모듈·비격리 호출·파일 변조·
manifest 변조를 검사한다. 원래 4개 카탈로그 사례의 기대값은 유지하고 실행 인자에
격리 모드만 추가했다. 최종 PR의 CI와 검토 커밋을 배포 영수증에 별도로 기록한다.

Claude의 후속 P2는 조회 파일 자체를 교체하면 내부 검사를 건너뛸 수 있다는 점이었다.
`scripts/helper_launcher.py`는 실행 전에 조회 파일의 고정 SHA256을 확인하고,
확인한 바이트를 그대로 실행한다. 정상 런처와 변조된 조회 파일에 대한 2개 검사가
통과했고 Claude는 최종 PASS_SOURCE를 반환했다. 이는 신뢰된 외부 런처까지 교체할 수
있는 주체를 막는 보안 경계라는 주장이 아니며, 전체 런타임 HOLD도 해제하지 않는다.

## 남은 관문

Flash의 실제 추론 인수는 주간 한도 복구 뒤에만 가능하다. Luna의 자동 실행 자격은
호출별 사용량과 예산 관문이 확인돼야 한다. 전체 UAOS의 기존 보안·원본·런타임 HOLD는
별도 소유자가 해소한다. 모델 목록, 파일 복사, smoke 응답, 인수, 병합, 배포를 구분한다.
