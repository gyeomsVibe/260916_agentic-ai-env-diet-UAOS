```contract
work_id: U304-C-L1
worker: local
goal: Implement classify() in schedule_planner.py from the tier spec
inputs:
- v7_harness/coord/schedule_planner.py sha256=37779c2cc46be91d7910cff9033a1dbc7e2a6f79d6f60d72cbcf803774330417
allow:
- v7_harness/coord/schedule_planner.py
acceptance: python -m pytest tests/test_u304c_schedule_planner.py -q
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: antigravity
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Replace the body of `classify(estimate, *, exhaustion_risk="SAFE")` in v7_harness/coord/schedule_planner.py (currently `raise NotImplementedError`). Change nothing else.

Spec: imp = int(estimate["importance"]), cx = int(estimate["complexity"]) (both 0..3).
- imp >= 2 and cx >= 2 -> tier "FLAGSHIP", effort "High", rule key "flagship"
- elif imp >= 2 or cx >= 2 -> "STANDARD_HIGH", "High", "standard_high"
- elif cx == 0 and imp <= 1 -> "MECHANICAL", "Low", "mechanical"
- else -> "STANDARD_MEDIUM", "Medium", "standard_medium"
- If tier is FLAGSHIP and str(exhaustion_risk or "").upper() == "IMMINENT_EXHAUSTION": tier becomes "STANDARD_HIGH" and demoted = True (else demoted False).
- reason = THRESHOLDS.get(rule_key, {}).get("rule", "otherwise: one axis at 1, none at 2 -> balanced medium effort")
Return {"tier": tier, "effort": effort, "rule": reason, "demoted_for_exhaustion": demoted, "score": round((imp / 3) * (cx / 3), 3)}.
Use one ===EDIT block whose SEARCH is exactly the line `    raise NotImplementedError("U304-C-L1: Ollama slice")`.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
