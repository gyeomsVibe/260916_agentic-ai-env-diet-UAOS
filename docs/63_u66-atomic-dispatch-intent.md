# U66 원자적 직접전달 의도

U64-F는 직접 전달 성공 영수증(`delivery/accepted`)이 생긴 뒤 감시자가 편지를 무시하게 했다. 그러나 편지 공개와 성공 영수증 사이에는 실제 Claude 실행 시간이 있어, 감시자가 먼저 읽으면 같은 편지가 차가운 세션과 대화형 세션을 동시에 깨울 수 있었다.

U66은 직접 전달 대상과 실제 변화 여부를 편지 공개 전에 결정하고 `delivery/pending/<message_id>.json`을 먼저 만든다. guard 획득자가 표식 소유권을 다시 기록하며, 경쟁에서 진 호출은 다른 호출의 표식을 지우지 못한다. 감시자는 이 표식이 있는 편지를 건너뛰되 `seen`에는 넣지 않는다. 직접 전달이 성공하면 accepted 영수증이 남아 영구 건너뛰고, 실패하면 소유한 pending을 지워 이미 실행 중인 같은 감시자가 다음 스캔에서 편지를 받는다. 300초 넘은 표식은 충돌한 프로세스의 잔재로 보고 fallback을 허용한다. 원래 편지 바이트와 publish-before-guard 불변식은 유지한다.

고정 인수는 `tests/test_u64f_no_double_wake.py`의 publish-to-receipt 경쟁 재현과 실패 후 fallback 재수신이다. 실제 토큰 절감은 통제 대조 전까지 `UNMEASURED`다.
