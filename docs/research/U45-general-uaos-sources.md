# U45 범용 UAOS 외부 근거

- 조사일: 2026-09-26. 사실과 설계 추론을 구분한다.

## 1. 공식 문서

- OpenAI, [Rethinking skills and prompts for GPT-6 Astra](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra): skill 설명과 `AGENTS.md`를 짧고 적용 조건이 분명하게 유지하고, 필요한 자료만 점진 공개하라고 권고한다. U45의 공통 최소 핵심+역할 어댑터 분리 근거다.
- OpenAI, [Docs MCP](https://developers.openai.com/learn/docs-mcp): Codex 관련 현재 문서는 읽기 전용 공식 문서 서버와 Docs skill을 우선 사용한다.
- Anthropic, [Claude prompting best practices](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices): 단순 작업에 subagent를 남용하지 말고 성공 기준과 검증을 명확히 한다.
- Anthropic, [Claude Code memory](https://code.claude.com/docs/zh-CN/memory): 짧은 지침이 준수에 유리하고 `CLAUDE.md`/`AGENTS.md` 중복·충돌을 피해야 한다.
- Google, [Gemini CLI Extensions](https://codelabs.developers.google.com/getting-started-gemini-cli-extensions): `GEMINI.md`는 버전 가능한 playbook이며 tool restriction과 함께 배포할 수 있다.

## 2. 논문과 구현

- [Uno-Orchestra](https://arxiv.org/abs/2605.05007): 분해 깊이·작업자·추론 예산을 함께 선택하는 선택적 위임이 고정 오케스트레이션보다 효율적일 수 있다. U45는 학습 라우터 대신 증거가 있는 상태기계를 사용한다.
- [open-multi-agent](https://github.com/open-multi-agent/open-multi-agent/blob/main/AGENTS.md): 위임 권한을 별도 허용하고 하위 작업 사용량을 부모 예산에 귀속한다. U45의 계약 예산·명시적 delegation 관문과 일치한다.

## 3. 일화성 반례

- Reddit의 [10시간 위임 실험](https://www.reddit.com/r/ClaudeCode/comments/1vjfsss/i_ran_a_10_hour_experiment_to_see_if_i_could_save/)은 저가 작업자 결과를 고가 검토자가 고치면서 총비용이 늘 수 있음을 보고한다. 일반화 가능한 증명은 아니며, U45에서 실제 영수증과 3배 회귀 관문을 두는 반례다.
- Reddit의 [multi-agent silent failures](https://www.reddit.com/r/ClaudeCode/comments/1t1cv0r/anyone_running_multiagent_claude_code_workflows/)는 구조화된 checkpoint, 누적 단계 비용, 압축 뒤 계약 재주입 필요성을 제안한다. 일화성 근거이므로 고정 인수로만 채택한다.

