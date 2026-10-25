# U229B2-L6 (judge claude, deputy for LIMITED codex; Codex re-review owed): olla POST journal

Card manual: `.coord/tasks/U229B2-card-manual.md`. Slice 6: `v7_harness/olla.py`. The old body of `_post` moves to a
new top-level function `_post_raw`, and `_post` becomes a wrapper that journals each Ollama POST (embedding included)
through `v7_harness.invocation.tracked_call`, payload hash only. Two whole top-level functions, spliced by name.

```contract
work_id: U229B2-L6
worker: local
goal: olla journals every Ollama POST (payload hash only, never raw text) and still returns the same body
inputs:
- v7_harness/olla.py sha256=7f900fab35961da17f6ca0725668cfccbe68c62ca746db50ddc0870d55947d97
- v7_harness/invocation.py sha256=62fb6ac1d9eb7b623f26e63f2a0605cfc2aaa0944294bbebc5ecc3396fabadc9
- tests/test_u229_olla_embed_journal.py sha256=05c693f9beb392f0eeac936a5df82c151721136d631ea1e94397c5ef0b7806d2
allow:
- v7_harness/olla.py
context_allow:
- tests/test_u229_olla_embed_journal.py
acceptance: python -m unittest tests.test_u229_olla_embed_journal tests.test_u229_independent_invocation tests.test_u17_olla tests.test_u30_olla_evidence tests.test_u103_olla_parity tests.test_u105_mid_turn_notice tests.test_u108_map_first tests.test_u16_local_worker
forbidden: editing or deleting tests; edits outside allow; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 900 seconds
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Exact edits: two whole top-level functions, verbatim

1. A new top-level function `_post_raw`:

```python
def _post_raw(path: str, payload: dict, timeout: int = 900) -> dict:
    request = urllib.request.Request(
        f"{HOST}{path}", data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))
```

2. Replace the whole top-level function `_post` with:

```python
def _post(path: str, payload: dict, timeout: int = 900) -> dict:
    """U229-B2: journal every Ollama POST (embedding included); payload hash only, never raw text."""
    import hashlib
    from v7_harness.invocation import _integer, tracked_call
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    with tracked_call(caller=os.environ.get("UAOS_CALLER") or _caller(), project=str(Path.cwd()),
                      work_id=os.environ.get("UAOS_WORK_ID", "UNSCOPED"),
                      purpose=os.environ.get("UAOS_PURPOSE", "ollama_post"), model=str(payload.get("model") or "unknown"),
                      input_sha256=digest, db=os.environ.get("UAOS_INVOCATION_DB")) as receipt:
        body = _post_raw(path, payload, timeout)
        receipt.update(outcome="SUCCEEDED", error_class=None, provider="ollama",
                       input_tokens=_integer(body.get("prompt_eval_count")), output_tokens=None)
    return body
```

## Output

- Reply with one ===EDIT: v7_harness/olla.py=== block holding the two whole top-level functions above in a
  ```python fence, copied character for character. No explanations. Do not claim success; the acceptance command
  decides.
