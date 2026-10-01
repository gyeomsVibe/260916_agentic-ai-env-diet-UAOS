```contract
work_id: U109-R
worker: local
goal: Ollama worker repairs a failed reply once for free: detects a one-line decoding loop, feeds the error back, retries with another seed
inputs:
- v7_harness/adapters/ollama_worker.py sha256=99ed23a6efcb47c4d003c10f76a1a0a0f063cdfe5137f80b7c0e9297e94eb3b4
- tests/test_u109_local_repair.py sha256=5cbe8eef0260990cf6a172ce198004a00175135d0d35ea1034164ac6e1260555
allow:
- v7_harness/adapters/ollama_worker.py
context_allow:
- v7_harness/adapters/ollama_worker.py
acceptance: python -m unittest tests.test_u109_local_repair tests.test_u109_worker_accepts_definitions tests.test_u109_def_splice tests.test_u107_ollama_slice tests.test_u17_lane_worker tests.test_u47_olla_record
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 1200
remote_budget_tokens: 0
```

## Instructions for the worker

Edit only `v7_harness/adapters/ollama_worker.py`. Your reply has two parts, in this order.

PART 1. One `===EDIT: v7_harness/adapters/ollama_worker.py===` header, then one ```python fenced block that holds,
complete, these four definitions (each replaces the one with the same name; new names are added):

REPAIRS = int(os.environ.get("OLLAMA_WORKER_REPAIRS", "1"))  # U109: one free retry with the error fed back; a same-seed retry repeats the reply
REPEAT_LIMIT = 8  # U109: one line this many times in a row is a loop (U109-S wrote 300+ copies), not code

def degenerate(text: str) -> bool:
    """U109: True when one non-blank line repeats REPEAT_LIMIT times in a row (a 7B decoding loop)."""
    previous, run = None, 0
    for line in text.splitlines():
        stripped = line.strip()
        run = run + 1 if stripped and stripped == previous else 1
        previous = stripped
        if stripped and run >= REPEAT_LIMIT:
            return True
    return False

def _try_apply(text: str, workspace: Path, task: str) -> tuple[list[str], str]:
    """(written paths, "") on success, ([], reason) when the reply cannot be used."""
    if degenerate(text):
        return [], f"DEGENERATE: one line repeated {REPEAT_LIMIT}+ times in a row"
    if "===FILE:" not in text and "===EDIT:" not in text:
        return [], "model returned no file block"
    try:
        written = _apply(text, workspace, task=task)
    except ValueError as exc:
        return [], str(exc)
    return (written, "") if written else ([], "no file written")

and `_generate` copied exactly from the current file with two changes: the signature becomes
`def _generate(model: str, prompt: str, timeout_s: int, *, fmt: dict | None = None, seed: int | None = None) -> tuple[str, dict[str, int]]:`
and the options use `"seed": SEED if seed is None else seed`.

PART 2. One SEARCH/REPLACE block for the end of `main`:

===EDIT: v7_harness/adapters/ollama_worker.py===
<<<<<<< SEARCH
    # U102-W: keep the raw reply on every rejection; an empty record hid the U101-L2 cause (constants above __future__).
    if "===FILE:" not in text and "===EDIT:" not in text:
        return envelope("ERROR", text, usage, "model returned no file block")
    try:
        written = _apply(text, workspace, task=args.prompt)
    except ValueError as exc:
        return envelope("ERROR", text, usage, str(exc))
    if not written:
        return envelope("ERROR", text, usage, "no file written")
    return envelope("SUCCESS", f"wrote: {', '.join(written)}", usage)
=======
    # U102-W: keep the raw reply on every rejection; an empty record hid the U101-L2 cause (constants above __future__).
    written, error = _try_apply(text, workspace, args.prompt)
    for attempt in range(1, REPAIRS + 1):
        if not error:
            break
        hint = "you repeated one line; write each statement once" if error.startswith("DEGENERATE") else "fix exactly that"
        repair = (f"{prompt}\n\nYOUR PREVIOUS REPLY:\n{text[:6000]}\n\nIt could not be applied: {error}. "
                  f"Reply again with the complete blocks; {hint}.")
        if len(repair.encode("utf-8")) // 3 > limit:
            break
        _log("pilot_local_repair", attempt=attempt, error=error[:120], **run)
        try:
            with pilot_holds(timeout_s):
                text, more = _generate(args.model, repair, timeout_s, seed=SEED + attempt)
        except (urllib.error.URLError, TimeoutError, OSError):
            break
        usage = {key: usage[key] + int(more.get(key, 0)) for key in usage}
        written, error = _try_apply(text, workspace, args.prompt)
    if error:
        return envelope("ERROR", text, usage, error)
    return envelope("SUCCESS", f"wrote: {', '.join(written)}", usage)
>>>>>>> REPLACE

Nothing else. Do not edit tests or other files.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
