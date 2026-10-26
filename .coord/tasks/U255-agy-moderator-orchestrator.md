```contract
work_id: U255
worker: local
goal: Implement Antigravity 6-Persona Moderator/Caretaker/Repairman/Chief & Ollama/Haiku 5.5 Orchestrator
inputs:
- v7_harness/coord/agy_moderator.py sha256=0995e3d972f4ad16d6c83e7245a17b8a5ba99bf2ff6528e5a3c6f278bbeec43e
- tests/test_u255_agy_moderator_orchestrator.py sha256=dcb9c785fa5108fc4e2c985af7ec735c492772830744ec1333c26c627d344077
allow:
- v7_harness/coord/agy_moderator.py
- tests/test_u255_agy_moderator_orchestrator.py
acceptance: C:\Python314\python.exe -B -m unittest tests.test_u255_agy_moderator_orchestrator -v
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 180
remote_budget_tokens: 0
```

## Instructions for the worker

- Change only the files under `allow`. Keep every other line byte-identical.

## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
