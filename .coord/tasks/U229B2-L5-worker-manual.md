# U229B2-L5 (judge claude, deputy for LIMITED codex; Codex re-review owed): Ollama worker journal

Card manual: `.coord/tasks/U229B2-card-manual.md`. Slice 5: `v7_harness/adapters/ollama_worker.py`. The old body of
`_generate` moves to a new top-level function `_generate_raw` (unknown token counts stay None instead of 0), and
`_generate` becomes a wrapper that journals each local call through `v7_harness.invocation.tracked_call` and returns
the same `(text, usage)` shape as before. Two whole top-level functions, spliced by name.

```contract
work_id: U229B2-L5
worker: local
goal: ollama_worker journals every local generate call (prompt hash only) while _generate keeps its return shape
inputs:
- v7_harness/adapters/ollama_worker.py sha256=eb9c605ea5905a2dd713b712beb10a25c19d9c7dcb3773479e73a0b2072c6535
- v7_harness/invocation.py sha256=62fb6ac1d9eb7b623f26e63f2a0605cfc2aaa0944294bbebc5ecc3396fabadc9
allow:
- v7_harness/adapters/ollama_worker.py
acceptance: python -m unittest tests.test_u229_independent_invocation tests.test_u102w_raw_reply tests.test_u107_ollama_slice tests.test_u108_map_first tests.test_u109_local_repair tests.test_u16_local_worker tests.test_u22_worker_limits tests.test_u34_precision_harness tests.test_u46_followup_fixes tests.test_u50_context_admission tests.test_u68l_worker_envelopes_ascii
forbidden: editing or deleting tests; edits outside allow; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 900 seconds
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Exact edits: two whole top-level functions, verbatim

1. A new top-level function `_generate_raw`:

```python
def _generate_raw(model: str, prompt: str, timeout_s: int, *, fmt: dict | None = None, seed: int | None = None) -> tuple[str, dict[str, int | None]]:
    """`fmt` is an Ollama structured-output JSON schema: the model can only emit JSON of that shape."""
    from v7_harness.invocation import _integer
    request_body: dict = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": KEEP_ALIVE,
        # 낮은 온도. 이 작업자는 창작이 아니라 지시받은 줄을 그대로 옮기는 손이다.
        "options": {"temperature": 0.1, "num_ctx": NUM_CTX, "num_predict": NUM_PREDICT, "seed": SEED if seed is None else seed},
    }
    if fmt is not None:
        request_body["format"] = fmt
    payload = json.dumps(request_body).encode("utf-8")
    request = urllib.request.Request(API, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        body = json.loads(response.read().decode("utf-8"))
    usage = {"input_tokens": _integer(body.get("prompt_eval_count")), "output_tokens": _integer(body.get("eval_count"))}
    return str(body.get("response") or ""), usage
```

2. Replace the whole top-level function `_generate` with:

```python
def _generate(model: str, prompt: str, timeout_s: int, *, fmt: dict | None = None, seed: int | None = None) -> tuple[str, dict[str, int]]:
    import hashlib
    from v7_harness.invocation import tracked_call
    from v7_harness.olla import _caller
    caller = os.environ.get("UAOS_CALLER") or _caller()
    with tracked_call(caller=caller, project=str(Path.cwd()),
                      work_id=os.environ.get("UAOS_WORK_ID", "UNSCOPED"),
                      purpose=os.environ.get("UAOS_PURPOSE", "local_generate"), model=model,
                      input_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                      db=os.environ.get("UAOS_INVOCATION_DB")) as receipt:
        text, usage = _generate_raw(model, prompt, timeout_s, fmt=fmt, seed=seed)
        receipt.update(outcome="SUCCEEDED", error_class=None, input_tokens=usage.get("input_tokens"),
                       output_tokens=usage.get("output_tokens"), provider="ollama")
    return text, {key: int(value or 0) for key, value in usage.items()}
```

## Output

- Reply with one ===EDIT: v7_harness/adapters/ollama_worker.py=== block holding the two whole top-level functions
  above in a ```python fence, copied character for character. No explanations. Do not claim success; the
  acceptance command decides.
