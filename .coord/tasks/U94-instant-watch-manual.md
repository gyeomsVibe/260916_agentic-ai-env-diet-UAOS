```contract
work_id: U94-INSTANT-WATCH-02
worker: local
goal: Reduce DEFAULT_INTERVAL_S from 30.0 to 2.0 in v7_harness/coord/watch.py to eliminate coordination delay.
inputs:
- v7_harness/coord/watch.py sha256=7eb50c9488483ac83ad8177502b24c5f0266cd396db049c58fd03b97b71d8c6e
allow:
- v7_harness/coord/watch.py
acceptance: python D:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/.work/u94/accept_watch.py
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: antigravity
timeout_s: 180
remote_budget_tokens: 0
```

## Instructions for the worker

- Change only the files under `allow`. Keep every other line byte-identical.

## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
