# U271-L2 contract manual - 사용자 보고 5줄·600자 압축 아키텍처 전역 정본화

```contract
work_id: U271-L2
worker: local
goal: Shorten the two report lines built at the end of done_report in v7_harness/card_pipeline.py to the U271 compact shape
inputs:
  - v7_harness/card_pipeline.py sha256=244138641eb06616552f4519a21d0ee54bfc2bfb26b27c127ee7648d1ff363f5
  - tests/test_u271_compact_report.py sha256=70309a603edcea0ca93f181f5b594e905b4c62d3ae4ab0c3c55a2076d1072a7b
allow:
  - v7_harness/card_pipeline.py
context_allow:
  - tests/test_u271_compact_report.py
acceptance: C:\Python314\python.exe -m unittest tests.test_u271_compact_report tests.test_u221_done_truthful tests.test_u267_core_title_reporting_overhaul tests.test_u135_result_relay
forbidden: editing or deleting tests; edits outside allow; edits to any other function; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 300 seconds
judge: antigravity
timeout_s: 300
remote_budget_tokens: 0
```

## Task

Copy this one edit block exactly. Do not change any other line of the file.

===EDIT: v7_harness/card_pipeline.py===
<<<<<<< SEARCH
    installed = f"런타임 {runtime}에 설치됐습니다" if runtime else "런타임 설치가 필요 없는 변경입니다"
    last = f"- **남은 일**: {action}" if action else "- 다음: 사용자가 할 일은 없습니다. 새 세션부터 바로 적용됩니다."
    card_label = f"{core_title}({card})" if core_title else f"{card} 작업"
    return "\n".join((f"**결과**: {name}의 {card_label}이 완료됐습니다 — {what}",
                      f"- 근거: 변경이 {pr_url} 로 병합됐고(커밋 {head[:7]}), {installed}.", last))
=======
    installed = f"런타임 {runtime}" if runtime else "런타임 설치가 필요 없는 변경"
    last = f"- **남은 일**: {action}" if action else "- 다음: 없음(새 세션부터 적용)"
    card_label = f"{core_title}({card})" if core_title else f"{name} {card} 작업"
    pr_no = pr_url.rsplit("/", 1)[1]  # U271: a short link label instead of a bare 70-character url
    return "\n".join((f"**결과**: {card_label} 완료 — {what}",
                      f"- 근거: [PR #{pr_no}]({pr_url}) 병합 {head[:7]} · {installed}", last))
>>>>>>> REPLACE
