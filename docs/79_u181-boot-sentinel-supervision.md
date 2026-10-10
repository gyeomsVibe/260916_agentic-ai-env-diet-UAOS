# 79. 부팅 때부터 감시병(sentinel) 켜기 (U181)

상태: 유지 문서(maintained). 코드 `v7_harness/coord/boot_task.py`, 시험 `tests/test_u181_boot_task.py`.

## 1. 왜 필요한가

지금까지 감시병은 **로그인한 뒤에만** 켜졌다(시작프로그램 바로가기, `~/.uaos/sentinel_*.cmd`). PC가 다시 켜졌는데
아무도 로그인하지 않으면 감시가 없다. U181은 **부팅 직후** 감시병을 켜는 작업 스케줄러(Task Scheduler) 작업을 준비한다.

## 2. 무엇이 만들어지나

| 항목 | 내용 | 이유 |
|---|---|---|
| 트리거 | 부팅 트리거(BootTrigger), 30초 지연 | 디스크와 스케줄러 서비스가 준비된 뒤 시작 |
| 실행 계정 | 내 계정, S4U 방식 | 비밀번호를 저장하지 않고 로그인 전에도 내 권한으로 실행 |
| 권한 | 최소 권한(LeastPrivilege) | 관리자 권한으로 돌지 않는다 |
| 중복 | IgnoreNew | 이미 도는 작업이 있으면 새로 띄우지 않는다 |
| 재시작 | 1분 간격 3회 | 고장 난 런타임이 끝없이 재시작하지 않게 |
| 동작 | `pythonw ~/.uaos/uaos.py coord boot --launch` 하나 | 작업의 동작은 차례로 실행되므로 하나만 둔다 |

`coord boot --launch`는 `~/.uaos/sentinel_*.cmd`가 있는 프로젝트마다 감시 루프를 하나씩 띄우고 기다린다.
로그인 전에는 소리 알림(`--ring`)을 쓰지 않는다.

## 3. 두 실행기가 같이 떠도 안전한 이유

감시 루프는 시작할 때 프로젝트별 수명 잠금(U180S lifetime lease)을 잡는다. 부팅 작업이 먼저 잡으면, 로그인 때
시작프로그램이 띄운 루프는 `LEASE_BUSY_OR_LOCK_ERROR`(종료 코드 3)로 바로 끝난다. 프로젝트당 루프는 항상 하나다.

알아 둘 점: 부팅 루프가 잠금을 잡고 있으면 로그인 때의 `--ring` 루프는 뜨지 않으므로 **소리 알림이 울리지 않는다**.
요약(`.coord/codex_brief.md`)과 로그(`.work/sentinel/sentinel.log`)는 그대로 쓰인다.

## 4. 사용 순서

1. 계획 보기(아무것도 등록하지 않는다):

   ```
   python "%USERPROFILE%\.uaos\uaos.py" coord boot
   ```

   `~/.uaos/boot/UAOS-Sentinel-Boot.xml` 파일 하나가 만들어지고, 등록 명령(`register`)과 해제 명령(`uninstall`),
   대상 프로젝트 목록(`projects`)이 출력된다.
2. 등록: **관리자 권한 명령 프롬프트**에서 출력된 `register` 줄을 실행한다. 부팅 트리거는 관리자만 만들 수 있고,
   S4U 계정 확인 때문에 비밀번호를 한 번 물을 수 있다(저장되지 않는다). 이 단계만 사람이 직접 한다.
3. 해제: 관리자 권한 명령 프롬프트에서 `uninstall` 줄을 실행한다. 시작프로그램 바로가기는 건드리지 않는다.

## 5. 확인 방법

- 시험: `python -m unittest tests.test_u181_boot_task` (실제 실행기 두 개를 띄워 루프가 하나뿐임을 센다).
- 등록 뒤: `schtasks /Query /TN "UAOS\Sentinel-Boot" /V /FO LIST`, 재부팅 후 프로젝트의 `.work/sentinel/sentinel.log`.

## 6. 하지 않는 것

- 코드와 시험은 작업을 등록·삭제하거나 권한을 올리지 않는다.
- 프로젝트 목록은 설치기가 쓴 `sentinel_*.cmd`에서만 읽는다. U180B 등록부(registry)의 정식 위치가 정해지면 그때 잇는다.
