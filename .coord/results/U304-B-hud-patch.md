# U304-B → U304-A HUD patch request (capacity_planner.py rendering)

- From: claude `u304b` (author U304-B). To: owner of `v7_harness/coord/capacity_planner.py` (U304-A, claude `u304a`).
- Why: U304-B may not edit `capacity_planner.py`. The data-source fix (one helper per tool) is done in
  `helper_telemetry.designated_helper_view()` + `quota_sources.measured_accounts()`; two display items remain.

## P1 — stale Codex plan label (user question "GPT-5.4 Codex Astra")

`v7_harness/coord/capacity_planner.py` ~line 67, `DEFAULT_POLICY["subscription_tiers"]["codex"]`:

```diff
-            "plan_name": "ChatGPT Plus ($20/월) · GPT-5.4 Codex Astra",
-            "short_plan": "Plus $20 (Astra)",
+            "plan_name": "ChatGPT Plus ($20/월) · GPT-6.1 Sol (키포인트: GPT-6 Astra)",
+            "short_plan": "Plus $20 (Sol)",
```

Evidence: `~/.codex/models_cache.json` has no "GPT-5.4 Codex Astra"; `~/.codex/config.toml` `model = "gpt-6.1-sol"`;
ledger 7 d: gpt-6.1-sol 1,481 calls. Details: `docs/107_U304B_3도구_도우미모델_1대1_선정_리서치.md` §5.1.

## P2 — Antigravity helper pool label

HUD JS ~line 2762 prints `도우미 풀 (${hq.models[0]})`. With U304-B the helper pool is the pool that contains
`Gemini 3.5 Flash Lite` (the shared Gemini pool), so `models[0]` may print an unrelated name (e.g. "Gemini 2.5 Pro").
Suggested: print the designated helper instead — `q.helpers[0].model` — e.g.

```diff
-`도우미 풀 (${String(hq.models[0]).replace(/ \(.*\)$/, "")}) 남음 ...`
+`도우미 풀 (${q.helpers.length ? q.helpers[0].model : String(hq.models[0])}) 남음 ...`
```

## No change needed

- Helper line `q.helpers.map(h => h.model)` already renders the single designated helper; `h.calls` is `null` for
  Antigravity (basis `designated_only`), which the existing `h.calls ? … : ""` handles.
