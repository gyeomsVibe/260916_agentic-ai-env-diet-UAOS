```contract
work_id: U106-A2
worker: cascade
goal: Antigravity subcontracts to Ollama: prompt preamble, per-run olla call count, paid_reason, pilot run default auto
inputs:
- v7_harness/adapters/agy.py sha256=dd8dcf48569acf0614e6b013cce3200b54c3cab8329354779b5f8fcd31b4604c
- v7_harness/pilot.py sha256=2480c7148235f69ed2c0e310967d273b34bd4d1a80ae05a0bba4546f751c19a7
- v7_harness/delegation.py sha256=d74be71be96dd97e589980f6ea5411af0ae2016dfd317ae2f1db0af1765923bf
- v7_harness/manual.py sha256=67859f46f7ab2b60a8dc7464ada481b336713af42f4d9b3017d7f7a4de33b46c
- v7_harness/cli.py sha256=a3f69c78bf9533f6619e3f4ecd612e12e53527b2f6318de4ace24f9117364a12
- tests/test_u106_subcontract.py sha256=a4282a3b0859e9e572b9dcf98376ab88086316e3a0faa35d84cdb7cc437424d9
allow:
- v7_harness/adapters/agy.py
- v7_harness/pilot.py
- v7_harness/delegation.py
- v7_harness/manual.py
- v7_harness/cli.py
acceptance: python -m unittest tests.test_u106_subcontract tests.test_u106_local_first tests.test_u98d_delegate_first tests.test_b20_model_flag tests.test_u14_adapters tests.test_u34_precision_harness tests.test_u36_evidence_gated_rsi tests.test_u38_cost_gate_and_claude_worker tests.test_u44_claude_contract tests.test_u46_followup_fixes tests.test_u50_context_admission tests.test_u69_admission_gate tests.test_u70_local_qualification tests.test_u45_general_uaos
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 1800
remote_budget_tokens: 800000
```

## Instructions for the worker

Card U106-A2. Goal: the commander picks the fitting worker, and when Antigravity is picked it subcontracts to the free local model (Ollama) through the olla MCP tools; each run records how many olla calls it made. The acceptance test `tests/test_u106_subcontract.py` is fixed; do not edit any test.

Change exactly these five files.

1. `v7_harness/adapters/agy.py`
   a. Below `REQUIRED_HEADLESS_FLAGS = ...` add:
      ```python
      # U106: headless Antigravity runs U105-A1 and U106-R spent 604k and 662k tokens with zero olla tool calls although the
      # tools were registered; the prompt never asked. Kept short: every paid call re-reads it.
      OLLA_SUBCONTRACT = (
          "Subcontract to the free local model first (olla MCP tools, 0 paid tokens): call local_read_map before reading "
          "any file over 300 lines, local_search to find code or text by meaning, and local_draft for boilerplate, "
          "docstrings, summaries or any draft over about 40 lines. Check what they return against the source before you "
          "use it; you still own the result and the acceptance. You may call them at any other time too."
      )
      # olla usage-log events that are real work; hook hints (hint_plan, turn_shape) and digest_prewarm are not.
      OLLA_WORK_EVENTS = frozenset({"digest", "ask", "find", "edit"})
      ```
   b. In the dataclass `AgyRequest`, add a last field `subcontract: bool = False`.
   c. In `build_agy_command`, replace the line
      `    prompt = f"[{request.task_id}] {request.title}\n{request.prompt}"`
      with
      ```python
          preamble = OLLA_SUBCONTRACT + "\n\n" if request.subcontract else ""
          prompt = f"[{request.task_id}] {request.title}\n{preamble}{request.prompt}"
      ```
   d. At the end of the file add:
      ```python
      def count_olla_calls(log_path: Path, start: str, end: str) -> dict[str, dict[str, int]]:
          """olla work events per caller with start <= ts <= end (ISO seconds, local time, as olla.log_usage writes)."""
          counts: dict[str, dict[str, int]] = {}
          try:
              lines = Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()
          except OSError:
              return counts
          for line in lines:
              try:
                  row = json.loads(line)
              except ValueError:
                  continue
              if not isinstance(row, dict) or row.get("event") not in OLLA_WORK_EVENTS:
                  continue
              if not start <= str(row.get("ts", "")) <= end:
                  continue
              by_event = counts.setdefault(str(row.get("caller") or "unknown"), {})
              by_event[row["event"]] = by_event.get(row["event"], 0) + 1
          return counts
      ```

2. `v7_harness/pilot.py`
   a. Change `from v7_harness.adapters.agy import AgyOutcome, AgyRequest` to `from v7_harness.adapters.agy import AgyOutcome, AgyRequest, count_olla_calls`.
   b. Directly above the comment line `        # 5. Staging directory setup` add:
      `        run_started = time.strftime("%Y-%m-%dT%H:%M:%S")  # U106: window for counting this run's olla calls`
   c. In the `AgyRequest(` call under `# 6. AgyRequest`, add the argument line after `model=config.model,`:
      `            subcontract=worker_label(config.agy_command) == "agy",  # U106: only real Antigravity subcontracts to Ollama`
   d. Directly after the block that writes `(runs_dir / "worker")` (the `try:` / `write_text(worker_label(...))` / `except OSError: pass` block), add:
      ```python
              # U106: whether the worker subcontracted to Ollama, beside the summary (key budget).
              try:
                  from v7_harness.olla import USAGE_LOG

                  olla_calls = count_olla_calls(USAGE_LOG, run_started, time.strftime("%Y-%m-%dT%H:%M:%S"))
                  (runs_dir / "olla_calls.json").write_text(json.dumps(olla_calls, sort_keys=True), encoding="utf-8")
              except OSError:
                  pass
      ```

3. `v7_harness/delegation.py` — in `local_first_errors`:
   a. Directly after the `paid_after` check that returns `[]`, add:
      ```python
          # U106: the commander may pick the paid worker by fit, but never silently: at least three words of reason.
          if len(str(contract.get("paid_reason") or "").split()) >= 3:
              return []
      ```
   b. Replace the returned error string with exactly:
      `"LOCAL_FIRST: code work goes to worker: cascade (Ollama first, escalates to the paid worker on a failed acceptance); a paid worker needs paid_after: <work_id of a failed Ollama/local/cascade run of this card> or paid_reason: <why this card needs the paid worker, at least 3 words>"`

4. `v7_harness/manual.py` — in `new_manual`:
   a. Add two keyword parameters after `context_allow: list[str] | None = None,`: `paid_after: str = "",` and `paid_reason: str = "",`.
   b. In the `lines` list, directly after the `remote_budget_usd` entry, add:
      ```python
              *([f"paid_after: {paid_after}"] if paid_after else []),
              *([f"paid_reason: {paid_reason}"] if paid_reason else []),
      ```

5. `v7_harness/cli.py`
   a. In the `p_pilot_run.add_argument("--worker", ...)` line change `default="agy"` to `default="auto"` and prepend to its help text: `auto (default) = the router picks: dictated code -> apply, a specific task -> cascade (Ollama first), else agy; `.
   b. After the `p_manual_new.add_argument("--instructions-file", ...)` line add:
      ```python
          p_manual_new.add_argument("--paid-after", default="", help="U106: work_id of a failed local run of this card")
          p_manual_new.add_argument("--paid-reason", default="", help="U106: why this card needs the paid worker (3+ words)")
      ```
   c. In `cmd_pilot_manual_new`, add to the `new_manual(...)` call after `context_allow=args.context_allow,`:
      `        paid_after=args.paid_after,` and `        paid_reason=args.paid_reason,`

Check: `python -m unittest tests.test_u106_subcontract tests.test_u106_local_first tests.test_u98d_delegate_first` must pass.
Forbidden: editing tests; any other file; network; git.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
