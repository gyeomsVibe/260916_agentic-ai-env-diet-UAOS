# U236A-L4 (judge claude, deputy for LIMITED codex; Codex re-review owed): exact-model guard, slice 1 re-cut as whole functions (claude_worker.py only)

U236A-L2 failed SPLICE_UNSUPPORTED:Expr: its content was right but statement fragments cannot be spliced. The
splicer replaces or adds whole top-level functions, so this re-cut dictates two whole functions. Contract and
fixed acceptance are unchanged (`.coord/tasks/U236A-L1-manual.md`, rev 2).

```contract
work_id: U236A-L4
worker: local
goal: claude_worker --require-model fails closed when modelUsage keys differ from the pinned full model id
inputs:
- v7_harness/adapters/claude_worker.py sha256=e2fe98b551e26421ab3f8f08dfbeb293cc77d6d2d6fc93638bb90dc0b415079f
- tests/test_u236a_model_pin.py sha256=54441760f3e03595d249e5b257fb190e209e0937742cc52ecbfc053684321dd6
allow:
- v7_harness/adapters/claude_worker.py
context_allow:
- tests/test_u236a_model_pin.py
acceptance: python -m unittest tests.test_u236a_model_pin.WorkerGuardTests tests.test_u38_cost_gate_and_claude_worker tests.test_u68_claude_worker_utf8 tests.test_u44_claude_contract tests.test_u45_general_uaos
forbidden: editing or deleting tests; changing behavior without --require-model; edits outside allow; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 900 seconds
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Exact edits: two whole top-level functions, verbatim

1. A new top-level function placed after `cap_overshoot`:

```python
def model_mismatch(result: dict, pinned: str) -> str:
    """U236a: under --require-model every modelUsage key must be the pinned full id; anything else fails closed."""
    keys = sorted(str(key) for key in (result.get("modelUsage") or {}))
    return "" if keys == [pinned] else f"MODEL_MISMATCH: expected {pinned}, got {keys}"
```

2. Replace the whole top-level function `main` with:

```python
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--prompt", required=True)
    parser.add_argument("--output-format", default="json")
    parser.add_argument("--print-timeout", default="600s")
    parser.add_argument("--add-dir", dest="workspace", required=True)
    parser.add_argument("--model", default=None)
    parser.add_argument("--max-budget-usd", dest="max_budget_usd", default=None)
    parser.add_argument("--require-model", dest="require_model", default=None)
    args, _unknown = parser.parse_known_args(argv)
    args.prompt = resolve_prompt(args.prompt)
    timeout_s = int(str(args.print_timeout).rstrip("s") or 600)
    model = args.model or DEFAULT_MODEL

    def envelope(status: str, response: str, usage: dict, error: str = "", extra: dict | None = None) -> int:
        # U68: ASCII escapes, not ensure_ascii=False. On Windows the pilot's pipe is cp949, and an answer holding
        # U+2014 raised UnicodeEncodeError after the paid call (U67-C1), leaving no envelope. JSON escapes decode back
        # to the same text under any stdout encoding.
        payload = {"status": status, "response": response, "usage": usage, "conversation_id": "claude-worker",
                   "error": error}
        payload.update(extra or {})
        print(json.dumps(payload, ensure_ascii=True))
        return 0 if status == "SUCCESS" else 1

    try:
        cap = float(args.max_budget_usd) if args.max_budget_usd is not None else 0.0
    except ValueError:
        cap = 0.0
    if not cap > 0:
        return envelope("ERROR", "", {}, "NO_USD_CAP: a paid Claude call needs --max-budget-usd > 0 "
                                         "(the contract's remote_budget_usd)")

    # Nothing reported means UNKNOWN to the cost gate, which blocks the run: a failed start is not a free run.
    started = time.monotonic()
    try:
        argv_prompt, stdin = split_for_stdin(args.prompt)
        done = subprocess.run(worker_command(argv_prompt, model, cap), cwd=args.workspace, env=worker_env(),
                              capture_output=True, timeout=timeout_s, input=stdin)
    except subprocess.TimeoutExpired:
        return envelope("ERROR", "", {}, f"claude worker timed out after {timeout_s}s")
    except (OSError, ValueError) as exc:
        return envelope("ERROR", "", {}, f"claude worker could not start: {exc}")
    try:
        result = json.loads(done.stdout.decode("utf-8", errors="replace"))
    except ValueError:
        return envelope("ERROR", "", {}, f"claude returned no JSON (rc={done.returncode}): "
                                         f"{done.stderr.decode('utf-8', errors='replace')[:200]}")
    if not isinstance(result, dict):
        return envelope("ERROR", "", {}, "claude returned a JSON value that is not an object")
    usage = usage_from(result)
    usage["elapsed_s"] = int(time.monotonic() - started)
    overshoot = cap_overshoot(usage, cap)
    if overshoot is not None:
        usage["usd_cap_overshoot_microusd"] = overshoot
    if result.get("is_error") and result.get("subtype") not in ("error_max_turns",):
        return envelope("ERROR", "", usage, str(result.get("subtype") or result.get("result") or "claude error")[:300])
    extra = None
    if args.require_model:
        mismatch = model_mismatch(result, args.require_model)
        if mismatch:
            return envelope("FAILED", "", usage, mismatch)
        extra = {"resolved_models": sorted(str(key) for key in (result.get("modelUsage") or {}))}
    return envelope("SUCCESS", str(result.get("result") or "").strip()[:2000] or "(claude ended without a summary)", usage,
                    extra=extra)
```

## Output

- Reply with two ===EDIT blocks, each holding one whole top-level function above. No explanations. Do not claim
  success; the acceptance command decides.
