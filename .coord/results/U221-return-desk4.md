# U221 복귀 검토와 격리 후보 보정 — maintained

현재 판정: 기존 묶음 REVISE, 수정 후보 한정 인수. 병합·원본 승격·설치는 미완료다.

## 실제 후보와 중단 원인
Claude 원작성자 체크아웃에는 check_done/done_report가 없어 원래 U221 검사 import가 exit1이었다. 그러나 .work/u221/pilot/stage/U221-DONE-FINAL에는3파일 변경이 있는 정확 묶음d34f6aa9…가 남아 있었다. 예전 SUCCEEDED는 DRY_RUN_PASSED이며 실제 승인시도는APPROVER_NOT_JUDGE로거부됐다. agy검토는QUOTA/UNUSABLE, Codex검토도quota거부였다. 이를PASS로바꾸지않았다.

## 독립 검토와 반례
불변 U221 검사SHA acd901b33cead30313a81af830f19864de9cdd9e2d4c50ac2c254cf860d650d7 및 관련4모듈42검사는 기존stage에서exit0이었다. 하지만 모의 런타임 버전에 개행을 넣어 current.json과 일치시키면 CLI가exit0/DONE을반환하며4줄을출력했다. 다른필드도수직탭 등Unicode구분자를허용했다. 원인은runtime이기존필드검증에서빠졌고,다른필드도LF/CR만검사했기때문이다. 테스트PASS만으로완료판정하면안되는실제반례다.

## 최소 보정
원본/기존stage를건드리지않은새복사본에서done_report의2줄(4diff줄)만정확apply작업자로수정했다. runtime을기존160자단일행검증에포함하고splitlines원문대조로모든행구분자를거부한다. 새묶음17313afd…를부모판정후격리복사본에만정상APPLIED했다. 기존42검사exit0,추가음성반례43건차단,불변평가기/원작성자3파일/옛stage해시보존을재확인했다. 새평가기를고쳐통과시킨것이아니다.

## 범위·미완료
제품공유원본/전역설치/계정설정/원래인덱스변경0,실제유료provider호출0. 수정후보는 .work/u221-return/repair-source/v7_harness/card_pipeline.py. 임시후보이며 이문서·계약·고정인수의도가유지기록이다. 기존의진짜감사출처/AUDIT_FIRST/커밋관문은유효하며아직충족하지않았다. quotaUNUSABLE/입력0인provider오류를실제모델실패나감사PASS로위조하지않는다. U228원격push플랫폼거부도그대로이고재시도하지않았다.

## 다음 독립 단계
U222-R 문서참조 후보의 정확 소스·테스트·U221중첩 범위를 같은 방식으로 확인한다. U221은정식감사/통합계약을갖춘새릴리스실행만허용하며,옛묶음을승인해반례를원본에넣지않는다.

근거: .work/u221-return/{inputs.json,owner-tests.log,stage-tests.log,runtime-newline-counterexample.json,red-extra-fields.log,parent-acceptance.log,post-promotion-acceptance.log}; .coord/reviews/U221-return-desk4.json; .coord/reviews/U221-return-repair-codex.json. Git diff와Python unittest공식문서는카드0단계자료로기록했다.
