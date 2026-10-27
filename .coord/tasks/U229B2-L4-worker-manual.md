# U229B2-L4 (judge claude, deputy for LIMITED codex; Codex re-review owed): Claude worker journal

Card manual: `.coord/tasks/U229B2-card-manual.md`. Slice 4: `v7_harness/adapters/claude_worker.py` journals every
paid call (start before dispatch, terminal row on every exit) through `v7_harness/invocation.py` (L1-L3, applied).
Two imports, four new whole top-level functions, and the whole `main` replaced. `main` keeps U236a's `extra` and
`--require-model` guard; MODEL_MISMATCH also sets `journal_failure`.

```contract
work_id: U229B2-L4
worker: local
goal: claude_worker journals each paid call start and terminal outcome, failing closed when the journal cannot start or finish
inputs:
- v7_harness/adapters/claude_worker.py sha256=2953a50253a93bf0b5c8c369f87f7c568af00906bd3ee1f9024e4de19d11f7e7
- v7_harness/invocation.py sha256=62fb6ac1d9eb7b623f26e63f2a0605cfc2aaa0944294bbebc5ecc3396fabadc9
- tests/test_u229_claude_journal_worker.py sha256=6b5721c9b4371eb26cc21c0a046851ad11ae3453f1162c3df5a33e9261779b69
allow:
- v7_harness/adapters/claude_worker.py
context_allow:
- tests/test_u229_claude_journal_worker.py
acceptance: python -m unittest tests.test_u229_claude_journal_worker tests.test_u229_independent_invocation tests.test_u236a_model_pin tests.test_u38_cost_gate_and_claude_worker tests.test_u68_claude_worker_utf8 tests.test_u44_claude_contract tests.test_u45_general_uaos
forbidden: editing or deleting tests; edits outside allow; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 900 seconds
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Exact edits: two imports, four new whole top-level functions, and the whole `main`, verbatim

```python
import hashlib
import math


def _journal_start(args, model: str) -> str:
    from v7_harness.invocation import start_attempt
    from v7_harness.olla import _caller

    return start_attempt(caller=os.environ.get("UAOS_CALLER") or _caller(),
                         project=str(Path(args.workspace).resolve()),
                         work_id=os.environ.get("UAOS_WORK_ID", "UNSCOPED"),
                         purpose=os.environ.get("UAOS_PURPOSE", "claude_worker"), model=model,
                         input_sha256=hashlib.sha256(args.prompt.encode("utf-8")).hexdigest(),
                         db=os.environ.get("UAOS_INVOCATION_DB"))


def _journal_usage(result: dict) -> dict:
    raw = result.get("usage")
    raw = raw if isinstance(raw, dict) else {}
    counts = {key: value if type(value := raw.get(key)) is int and value >= 0 else None
              for key in USAGE_KEYS}
    inputs = [counts[key] for key in USAGE_KEYS if key != "output_tokens"]
    values = {"input_tokens": sum(inputs) if all(v is not None for v in inputs) else None,
              "output_tokens": counts["output_tokens"], "cache_creation_input_tokens": counts["cache_creation_input_tokens"],
              "cache_read_input_tokens": counts["cache_read_input_tokens"], "provider": "claude_cli_unverified"}
    cost = result.get("total_cost_usd")
    if type(cost) in (int, float) and math.isfinite(cost) and cost >= 0:
        values["cost_usd"] = cost  # provider-reported list estimate; no OAuth/billing assertion
    return values


def _journal_finish(attempt: str | None, status: str, result: dict, failure: str | None) -> None:
    if attempt is None:
        return
    from v7_harness.invocation import finish_attempt

    finish_attempt(attempt, outcome="SUCCEEDED" if status == "SUCCESS" else "FAILED",
                   error_class=failure, db=os.environ.get("UAOS_INVOCATION_DB"), **_journal_usage(result))


def _journal_abort(attempt: str | None, exc: BaseException) -> None:
    from v7_harness.invocation import _exception

    _journal_finish(attempt, "ERROR", {}, _exception(exc))


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
    attempt, journal_result, journal_failure = None, {}, None

    def envelope(status: str, response: str, usage: dict, error: str = "", extra: dict | None = None) -> int:
        try:
            _journal_finish(attempt, status, journal_result, journal_failure)
        except Exception:  # durable terminal-write failure cannot be reported as worker success
            status, response, error = "ERROR", "", "INVOCATION_JOURNAL_TERMINAL_FAILED"
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

    try:
        attempt = _journal_start(args, model)
    except Exception:  # fail closed before command construction/provider dispatch; no diagnostic body
        return envelope("ERROR", "", {}, "INVOCATION_JOURNAL_START_FAILED")

    # Nothing reported means UNKNOWN to the cost gate, which blocks the run: a failed start is not a free run.
    started = time.monotonic()
    try:
        argv_prompt, stdin = split_for_stdin(args.prompt)
        done = subprocess.run(worker_command(argv_prompt, model, cap), cwd=args.workspace, env=worker_env(),
                              capture_output=True, timeout=timeout_s, input=stdin)
    except subprocess.TimeoutExpired:
        journal_failure = "TIMEOUT"
        return envelope("ERROR", "", {}, f"claude worker timed out after {timeout_s}s")
    except (OSError, ValueError) as exc:
        journal_failure = "PROCESS_ERROR"
        return envelope("ERROR", "", {}, f"claude worker could not start: {exc}")
    except BaseException as exc:
        _journal_abort(attempt, exc)
        raise
    try:
        result = json.loads(done.stdout.decode("utf-8", errors="replace"))
    except ValueError:
        journal_failure = "PARSE_ERROR"
        return envelope("ERROR", "", {}, f"claude returned no JSON (rc={done.returncode}): "
                                         f"{done.stderr.decode('utf-8', errors='replace')[:200]}")
    except BaseException as exc:
        _journal_abort(attempt, exc)
        raise
    if not isinstance(result, dict):
        journal_failure = "RESPONSE_FORMAT"
        return envelope("ERROR", "", {}, "claude returned a JSON value that is not an object")
    journal_result = result
    try:
        usage = usage_from(result)
    except Exception:
        journal_failure = "USAGE_FORMAT"
        return envelope("ERROR", "", {}, "claude returned invalid usage metadata")
    usage["elapsed_s"] = int(time.monotonic() - started)
    overshoot = cap_overshoot(usage, cap)
    if overshoot is not None:
        usage["usd_cap_overshoot_microusd"] = overshoot
    if result.get("is_error") and result.get("subtype") not in ("error_max_turns",):
        journal_failure = "PROVIDER_ERROR"
        return envelope("ERROR", "", usage, str(result.get("subtype") or result.get("result") or "claude error")[:300])
    extra = None
    if args.require_model:
        mismatch = model_mismatch(result, args.require_model)
        if mismatch:
            journal_failure = "MODEL_MISMATCH"
            return envelope("FAILED", "", usage, mismatch)
        extra = {"resolved_models": sorted(str(key) for key in (result.get("modelUsage") or {}))}
    return envelope("SUCCESS", str(result.get("result") or "").strip()[:2000] or "(claude ended without a summary)", usage,
                    extra=extra)
```

## Output

- Reply with one ===EDIT: v7_harness/adapters/claude_worker.py=== block holding the two imports and the five whole
  top-level functions above in a ```python fence, copied character for character. No explanations. Do not claim
  success; the acceptance command decides.
