# U65-G 전역 규칙 단일 작성자

## 문제

`shared/global-rules` 정본 생성기와 diet의 `install_uaos_everywhere`가 같은 세 전역 규칙 파일을 각각 생성했다. 현재 PC에서는 diet 설치기 `--check`가 drift 0인 동시에 정본 생성기 `Check`가 세 파일 모두 불일치로 실패했다. 한 작성자가 맞추면 다른 작성자가 다시 어긋나는 구조였다.

## 결정

파일 첫머리에 `<!-- GENERATED from English canonical rules ... -->` 표식이 있으면 정본 생성기가 파일 전체의 유일한 작성자다. diet 설치기는 그 파일의 UAOS 블록을 추가·교체·제거하지 않고, 런타임과 세 도구의 출석 훅만 관리한다. 정본 표식이 없는 개인 파일에서는 기존처럼 UAOS 블록만 보존적으로 관리한다.

## 검증 경계

가짜 HOME에 세 정본 생성 파일을 만들고 `--check`와 `--uninstall`이 바이트를 바꾸지 않는지 검증한다. 실제 PC를 정본 출력으로 바꾸는 Apply와 새 diet 런타임 설치는 시스템 설정 변경이므로 별도 승인 전에는 실행하지 않는다.
