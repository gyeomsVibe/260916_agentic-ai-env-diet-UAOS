```contract
work_id: U54
worker: apply
goal: Audit-only inventory of every model-reachable execution site in v7_harness and whether a policy check precedes it; generated gap list in docs/50; no behaviour change (docs/49 U-SEC-1 step 1).
inputs:
- v7_harness/adapters/guard.py sha256=ee396958eb2b05723a7aa58fd6b6b66f03e22aa8f1cc426bd17a2d9059af5b8e
- v7_harness/gemini_shim.py sha256=f39d9ac89778623165d5976c957ef7f86950a239dc6940baf27f9866ccca2c48
- v7_harness/execution/engine.py sha256=daf3f876c9e6cb69c2f4d124f80fecc6094b43f201a896887fbd0121d3d0ae23
allow:
- v7_harness/firewall_audit.py
- tests/test_u54_firewall_audit.py
- tests/fixtures/u54_sample.py
- docs/50_u54-tool-execution-firewall-gap-audit.md
acceptance: C:/Python314/python.exe -m unittest tests.test_u54_firewall_audit
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

## Instructions for the worker

Status: DRAFT contract (BACKLOG, docs/49 §5.0). It is not runnable yet. The author adds the ===FILE blocks when the card is
picked up, then rebuilds and re-lints this manual. Judge codex. The author never approves its own bundle.

Card: U54, the first step of docs/49 U-SEC-1 (tool execution firewall).

What:
- Audit only, no behaviour change.
- The contract fixes the method: a new stdlib-only module v7_harness/firewall_audit.py walks v7_harness/**/*.py with `ast` and lists every place that can run a model-proposed action. The seeds are:
  - subprocess.* / os.system / os.exec* / os.spawn* calls;
  - handlers that read a model's `tool_calls` field (seen today in gemini_shim.py and execution/engine.py);
  - writes to paths taken from model output.
- For each site it records:
  - file:line
  - the callee
  - whether the command, arguments or path can come from model output, or only from fixed code and the manual. The rule is fixed in the module docstring.
  - whether an existing policy check runs before it: the pilot allow list, adapters/guard.py, or the manual's forbidden list.
- It writes docs/50_u54-tool-execution-firewall-gap-audit.md. The table there is generated, never hand-edited. The doc ends with a "gaps" list: every model-reachable site with no check before it.

Why audit first: docs/49 marked U-SEC-1 as "partial" (guard.py plus global rules) without an inventory. A firewall added before the gap list exists could guard the wrong call.

Tests (tests/test_u54_firewall_audit.py):
1. The fixture module tests/fixtures/u54_sample.py has one guarded subprocess call, one unguarded call built from a `tool_calls` argument, and one constant command. The audit classifies them exactly GUARDED, GAP, FIXED.
2. On the real tree, every subprocess/os.system site that `grep -rn` finds is also in the audit output. This is a second signal, so an AST miss cannot shrink the list silently.
3. Two runs produce byte-identical doc output, so the audit is deterministic.

Red first: on HEAD, test 1 fails with an import error.

Out of scope: blocking or changing any call site. That is U54-S2, and it needs its own contract after Codex reads the gap list.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
