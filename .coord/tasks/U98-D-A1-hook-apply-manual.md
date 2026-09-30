```contract
work_id: U98-D-A1
worker: apply
goal: Hook the Ollama-written delegation gate into manual lint, fix the one error-message defect Ollama left twice, and stop the lint hint that steered code to apply.
inputs:
- v7_harness/manual.py sha256=9702fa5fbb470a57a15a806e62c44031a089ef020aa4801dd7dc752153842a38
- v7_harness/delegation.py sha256=0c86de26b09b74f6bb472a2abf7b786879887ed1ae5bd1a95a3ca3e085a0d0ba
- .coord/PLAN.md sha256=052f3775c577e108a2ab3bdd7c3299f51d0250a1a3b032000023e08a6917efc6
allow:
- v7_harness/manual.py
- v7_harness/delegation.py
- .coord/PLAN.md
acceptance: python -m unittest tests.test_u98d_delegate_first tests.test_u34_precision_harness tests.test_u36_evidence_gated_rsi tests.test_u38_cost_gate_and_claude_worker tests.test_u44_claude_contract tests.test_u45_general_uaos tests.test_u46_followup_fixes
forbidden: design changes; edits outside allow; editing or weakening existing tests; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the blocks below exactly. Ollama wrote `v7_harness/delegation.py` (U98-D-L4, APPLIED). The judge found one defect it repeated in L3 and L4: the refusal message printed the empty `apply_after` value instead of telling the author what to write. The code here is 4 lines, under the 20-line gate it adds.

===EDIT: v7_harness/delegation.py===
<<<<<<< SEARCH
first, and apply only with apply_after: {after}"]
=======
first, and apply only with apply_after: <work_id of that failed run>"]
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/manual.py===
<<<<<<< SEARCH
        report.errors.append("NO_BLOCKS_FOR_APPLY: worker apply needs ===FILE/===EDIT blocks in the manual")
=======
        report.errors.append("NO_BLOCKS_FOR_APPLY: worker apply needs ===FILE/===EDIT blocks in the manual")
    from v7_harness.delegation import delegate_first_errors
    report.errors.extend(delegate_first_errors(text, contract, project))
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/manual.py===
<<<<<<< SEARCH
        report.warnings.append("DICTATION: the manual already contains the exact code; worker: apply does it with 0 tokens")
=======
        report.warnings.append("DICTATION: the manual already contains the exact code, so the delegate only copies it; give it a spec instead (U98-D)")
>>>>>>> REPLACE
===END===

===EDIT: .coord/PLAN.md===
<<<<<<< SEARCH
록. 편지는 확인(ack)·이동·삭제하지 않는다. — `v7_harness/cli.py`, `tests/test_u97i_inbox_brief.py` |
=======
록. 편지는 확인(ack)·이동·삭제하지 않는다. — `v7_harness/cli.py`, `tests/test_u97i_inbox_brief.py` |
| U98-D | REVIEW (Claude 설계, Codex 복귀 시 재검토) | claude(명세·판정) · ollama(구현 L4) · apply(4줄 연결) | 영수증: 09-26~09-30 장부에 apply 174행, Ollama 14행, Antigravity 17행. 유료 지휘자가 코드를 전부 받아쓰게 해 위임 경로가 건너뛰어졌다. 원인은 apply "0토큰" 표기, lint의 DICTATION 힌트, auto→apply 경로이며 위임을 강제하는 관문이 없었다. 조치: `worker: apply` 매뉴얼이 테스트 외 파이썬 코드 20줄 초과를 받아쓰면 lint가 DELEGATE_FIRST로 거부하고, 장부에 실패한 위임 실행(ollama/local/cascade/agy/lane)이 있을 때만 `apply_after: <work_id>`로 허용한다. `pilot run`은 lint를 거치므로 실행에서도 막힌다. 20줄은 정책값(UNMEASURED). Ollama L1·L2는 프롬프트 초과(14,173>12,288)로 막혔고, L3는 결함 3개로 반려, L4 승인. — `v7_harness/delegation.py`, `v7_harness/manual.py`, `tests/test_u98d_delegate_first.py` |
>>>>>>> REPLACE
===END===
