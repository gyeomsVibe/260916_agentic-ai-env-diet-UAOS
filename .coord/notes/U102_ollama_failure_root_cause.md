# U102 — Why Ollama failed U101-L1/L2 twice (root cause, evidence, fix)

Question (윤겸스, 2026-09-30): did Ollama fail because we did not understand it and wrote a poor manual?
Verdict: **yes, mainly our manual; the model setup was not the cause.** Judge: claude (Codex re-review owed).

## Evidence

1. Local rerun of the exact U101-L2 prompt (qwen2.5-coder:7b Q4_K_M, worker prompt build, clean workspace).
   The reply put the three constants **above** `from __future__ import annotations` and dropped the docstring.
   A `from __future__` import must be the first statement, so compile fails at line 10 every time.
   The manual described the order in prose ("start with a docstring, then `from __future__`"), then gave the
   constants as the first numbered list. The model copied list order, not the prose.
2. Same task, same model, 5 seeds each (`scratchpad/exp_u102.py`, pass = worker `_apply` accepts + fixed acceptance
   `tests.test_u101_absence_brief` passes):
   - A, prose manual (the real U101-L2 manual), temperature 0.1: **0/5**, all `SYNTAX_ERROR:...:10`.
   - B, skeleton manual (the header lines written out literally, "copy this in this order"), temperature 0.1: **5/5**.
   - A with Qwen's official sampling (temperature 0.7, top_p 0.8, top_k 20, repetition 1.1): **2/5** (randomness
     sometimes lands the right order). B with official sampling: **5/5**.
   Only the manual text changed between A and B; output 623 → 681 tokens, mean 46.5 → 50.3 s per run.
   Raw rows: `.work/u100/u102_exp_results.jsonl`, script `.work/u100/exp_u102.py`.
3. Things ruled out:
   - Context window: `num_ctx` is 16384; the prompt was 2,792 tokens. (Aider measured Ollama's silent 2k default
     truncation as 71.4% → 51.9% on this model family; that trap does not apply here.)
   - Markdown fences: the worker already strips a fence around a whole file (A replies were fenced and still failed
     only on ordering).
4. Why the judge did not see this earlier: the run record kept `response: ""` on every rejection, so the second
   manual only added "no syntax errors", which cannot fix an ordering problem. Fixed by U102-W.

## External sources

- Qwen2.5-Coder-7B-Instruct `generation_config.json` (Hugging Face): temperature 0.7, top_p 0.8, top_k 20,
  repetition_penalty 1.1.
- Aider, "Quantization matters" (2024-11-21): Ollama 2k default context silently truncates; 71.4% vs 51.9%.
- Aider edit formats: weaker models need formats that fit their habits; whole-file for small files.
- ComplexBench (arXiv 2407.03978, NeurIPS 2024): small open models drop most on chained (sequential) constraints
  and on format constraints; ChatGLM3-6B 0.701 (And) → 0.556 (Chain).

## Fix (U102)

- U102-W: the worker keeps the raw reply in `response` on every rejection (apply, 4 lines, test first).
- docs/37 §4-3: lines whose position matters are shown literally (skeleton first); prose only for function bodies;
  read the raw reply before a second attempt.
- Not changed: sampling settings. The official sampling only turned 0/5 into 2/5 by chance; the manual fixed it at
  either setting, and low temperature keeps a failure reproducible.
- U102-N (same PR): the prompt hook no longer shows Claude's own letters (240 of the inbox's evt letters were
  Claude's own; relays from Claude are recognised by `payload.actor`).
