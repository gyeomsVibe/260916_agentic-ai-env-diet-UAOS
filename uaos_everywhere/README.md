# uaos_everywhere — UAOS를 이 PC의 모든 프로젝트에 설치하기

<!-- uaos-update:8eee03249cf9eb89a90d9f9421766b468308eee5ecebf5fb88460a08e9469569 -->
## 업데이트 (0.1.0, 2026-09-25)

- 검증된 근거만 버전된 PR 후보로 만드는 fail-closed 파이프라인과 결정적 변경 감시 스케줄러 구현.

이 폴더 하나로 UAOS를 모든 프로젝트에서 가동한다. 설치되는 것은 다음과 같다.

- 세 AI 도구(Codex·Claude Code·Antigravity)의 전역 규칙에 UAOS 문단.
- 출석부(presence) 자동 훅.
- Claude 유료 예약 도구 차단.
- (선택) 24시간 교환원(sentinel).

| 파일 | 역할 |
|---|---|
| `install_uaos_everywhere.py` | 설치 프로그램. 기본은 미리보기, `--apply`로 설치, `--check`로 점검, `--uninstall`로 제거 |
| `deploy_to_this_pc.py` | 사용자 PC 마무리 배포 한 번에: 회귀 → 훅 설치 → 정본 규칙에 이식 가능한 문단 → 생성기 → 확인 → 교환원 → 커밋·푸시. 계획 모드가 기본, `--apply --push`로 실행(docs/43) |
| `uaos_global_rule_block.md` | 전역 규칙 파일에 들어가는 문단의 원본. `{uaos}`는 설치할 때 실행기 경로로 바뀐다 |

```powershell
python uaos_everywhere/install_uaos_everywhere.py            # 미리보기(아무것도 안 씀)
python uaos_everywhere/install_uaos_everywhere.py --apply    # 설치(원본은 ~/.uaos-backups/<시각>/)
python uaos_everywhere/install_uaos_everywhere.py --check    # 0 = 정상, 1 = 빠진 것(drift) 있음
python uaos_everywhere/install_uaos_everywhere.py --apply --register-sentinel D:\경로\프로젝트   # Windows 24/7 교환원
python uaos_everywhere/install_uaos_everywhere.py --apply --uninstall                            # 되돌리기
```

- 쉬운 설명(따라 하기·문제 해결): [docs/쉽게_읽는_UAOS_진단과_해결_전과정/05](../docs/쉽게_읽는_UAOS_진단과_해결_전과정/05_모든_프로젝트에_UAOS_설치하기.md)
- 기술 기록(설계 이유·위험): [docs/39](../docs/39_uaos-everywhere-global-deployment-and-b77.md)
- U42-R1 스케줄러/보존 하드닝(fail-closed 릴리스, 락 회복, Windows 예약, 삭제 없는 보존 계획): [docs/45](../docs/45_u42_r1_scheduler_and_retention.md)
- 주의: 세 전역 규칙 파일은 정본 생성기(`sync-global-rules.ps1`)가 다시 만든다. 규칙 문단을 정본에도 넣어야 영구 반영된다. 넣지 않으면 `--check`가 drift로 알려 준다.

```powershell
python -m v7_harness.cli rsi schedule --project D:\경로\프로젝트 --action install --apply    # Windows 예약 등록(프로젝트별 고유 작업 이름)
python -m v7_harness.cli rsi schedule --project D:\경로\프로젝트 --action manual-now --apply  # 지금 한 번 수동 실행
python -m v7_harness.cli rsi retention --project D:\경로\프로젝트                              # 보존 계획 드라이런 출력(삭제 없음)
```
