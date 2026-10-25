# U241C-L2 Contract Manual — Wire `auto_render_control_ux` into `user_window.on_prompt`

```contract
work_id: U241C-L2
worker: local
goal: Wire auto_render_control_ux into v7_harness/coord/user_window.on_prompt so Antigravity prompts automatically trigger the Control UX dashboard
inputs:
  - v7_harness/coord/user_window.py sha256=2595eb11ad8df25630338177f149f25bf3d7b726a2133d5988589ece7215d349
  - tests/test_u241_control_ux.py sha256=51422341b054c79587d867317167635b9bf71c948d6e973da287a12d516862fb
allow:
  - v7_harness/coord/user_window.py
context_allow:
  - tests/test_u241_control_ux.py
acceptance: C:\Python314\python.exe -m unittest tests.test_u241_control_ux
forbidden: editing or deleting tests; edits outside allow; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 300 seconds
judge: claude
timeout_s: 300
remote_budget_tokens: 0
```

## Task Specification

Apply this exact edit block:

===EDIT: v7_harness/coord/user_window.py===
<<<<<<< SEARCH
def on_prompt(project: Path, tool: str, thread: str, prompt, *, now: datetime | None = None,
              current: str | None = None) -> str:
    if not thread:
        return ""
=======
def on_prompt(project: Path, tool: str, thread: str, prompt, *, now: datetime | None = None,
              current: str | None = None) -> str:
    if not thread:
        return ""
    try:
        from v7_harness.control_ux import auto_render_control_ux
        auto_render_control_ux(project, tool, str(prompt or ""))
    except Exception:
        pass
>>>>>>> REPLACE
