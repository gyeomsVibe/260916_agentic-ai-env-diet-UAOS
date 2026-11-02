# [U295] 3대 도구 공식 도우미 모델·추론 모델 라인업 선언 및 마스터·세부 스케줄 기반 Thinking Level 자동 선정·병렬 오케스트레이션

- **State**: `ACTIVE`
- **Owner**: `antigravity`
- **Reviewer**: `claude`
- **Branch**: `agy/u295-helper-thinking-orchestration`
- **Worktree**: `.work/wt_u295_helper_thinking_orchestration`

## 핵심 목표
1. **Codex·Antigravity·Claude Code 공식 도우미 모델(Helper Model) 및 추론 모델 라인업 선언·지정**:
   - `codex`: 계산기 `ollama`(`qwen2.5-coder:7b`) + 공식 도우미 `gpt-6-luna`(주력), `gpt-5.6-luna`, `gpt-5.6-terra`, `gpt-5.6-sol`, `gpt-6-sol` + 추론 라인업 `gpt-6.1-sol`, `gpt-6.1-terra`, `gpt-6-astra`, `gpt-6-sol`, `gpt-6-luna`, `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna` + Thinking Level (`Low`/`Medium`/`High`).
   - `antigravity`: 계산기 `ollama`(`qwen2.5-coder:7b`) + 공식 도우미 `gemini-3.8-flash`(주력), `gemini-3.7-flash`, `gemini-3.6-flash`, `gpt-oss-120b` + 추론 라인업 `gemini-4-argon`, `gemini-3.1-pro`, `claude-sonnet-5-5-thinking`, `claude-opus-5-5-thinking`, `gpt-oss-120b` + Thinking Level (`Low`/`Medium`/`High`).
   - `claude`: 계산기 `ollama`(`qwen2.5-coder:7b`) + 공식 도우미 `claude-haiku-5-5`(12K 캡) + 추론 라인업 `claude-opus-5-5`, `claude-sonnet-5-5` + Thinking Level (`Low`/`Medium`/`High`).
2. **마스터 스케줄(`.coord/master_schedule.json`) 및 세부 프로세스 스케줄(`.coord/sub_process_schedule.json`) 전수 파악 기반 자동 선정**:
   - 카드별 병렬 세션, 역할별(`conductor`, `implementer`, `reviewer`, `merger`, `recovery`), 5대 레인(`IMPL_CODE`, `VERIFY_AUDIT`, `ARCH_DESIGN`, `MERGE_RELEASE`, `RECOVERY_OPS`), 세부 단계(`SP1`~`SP5`)별 도우미 모델·추론 모델·Thinking Level(`Low`/`Medium`/`High`) 자동 최적화.
3. **Claude Code의 Ollama CLI + Haiku 5.5 5:3:2 병렬 운용 전수분석 및 최적화**:
   - 실측 장부(1,745건) 전수 분석을 통해 Haiku 5.5 과소 호출 편차(-27.1%p) 진단 및 이원 분리 병렬 자동 승격 로직 구현.
