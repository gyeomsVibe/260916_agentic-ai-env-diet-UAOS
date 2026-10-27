# U271-L1 contract manual - 사용자 보고 5줄·600자 압축 아키텍처 전역 정본화

```contract
work_id: U271-L1
worker: local
goal: Add REPORT_MAX_LINES, REPORT_MAX_CHARS, NESTED_RE and compact_report_problems right after validate_user_status_lines in v7_harness/card_pipeline.py
inputs:
  - v7_harness/card_pipeline.py sha256=244138641eb06616552f4519a21d0ee54bfc2bfb26b27c127ee7648d1ff363f5
  - tests/test_u271_compact_report.py sha256=70309a603edcea0ca93f181f5b594e905b4c62d3ae4ab0c3c55a2076d1072a7b
allow:
  - v7_harness/card_pipeline.py
context_allow:
  - tests/test_u271_compact_report.py
acceptance: C:\Python314\python.exe -m unittest tests.test_u271_compact_report.U271CompactReportTests.test_1_budget_is_the_olla_report_gate tests.test_u271_compact_report.U271CompactReportTests.test_2_the_verbose_report_is_refused_for_lines_chars_and_nesting tests.test_u271_compact_report.U271CompactReportTests.test_3_a_compact_report_passes tests.test_u271_compact_report.U271CompactReportTests.test_4_a_bare_id_status_line_is_still_refused tests.test_u267_core_title_reporting_overhaul
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
            problems.append(f"BARE_ID_REPORT_FORBIDDEN: {label!r} lacks a human-readable core title")
    return problems
=======
            problems.append(f"BARE_ID_REPORT_FORBIDDEN: {label!r} lacks a human-readable core title")
    return problems


# U271: one compact BLUF report; the same budget the olla report gate measures (olla.REPORT_MAX_*).
REPORT_MAX_LINES = 5
REPORT_MAX_CHARS = 600
NESTED_RE = re.compile(r"^\s+[-*]\s")


def compact_report_problems(text: str) -> list[str]:
    """U271: why a user report is too long: lines, characters, nested bullets, bare-ID status lines."""
    lines = [line for line in (text or "").splitlines() if line.strip()]
    problems = []
    if len(lines) > REPORT_MAX_LINES:
        problems.append(f"OVER_LINES: {len(lines)} > {REPORT_MAX_LINES}")
    if len(text or "") > REPORT_MAX_CHARS:
        problems.append(f"OVER_CHARS: {len(text or '')} > {REPORT_MAX_CHARS}")
    if any(NESTED_RE.match(line) for line in lines):
        problems.append("NESTED: sub-bullets belong in the PR body or card")
    return problems + validate_user_status_lines(text)
>>>>>>> REPLACE
