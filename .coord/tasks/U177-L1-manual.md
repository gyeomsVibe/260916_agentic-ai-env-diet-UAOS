```contract
work_id: U177-L1
worker: local
goal: U177 the local worker cuts a large file from SEARCH lines and definition lines without hand-written anchors
inputs:
- v7_harness/adapters/ollama_worker.py sha256=a4302acd256dc752804b9acb0b6ea6ff9773622dec3163484588242cdf245f01
- v7_harness/manual.py sha256=81f521ccb9afd87593df5999f9bf57ff87865c137c75c647d68fd16adc4938c2
- tests/test_u177_slice_without_anchors.py sha256=be6a6002978d3b1e9bff9ff2b79f61d07b694ffe8998f388bce3aac9274425c2
allow:
- v7_harness/adapters/ollama_worker.py
- v7_harness/manual.py
context_allow:
- v7_harness/adapters/ollama_worker.py
- v7_harness/manual.py
acceptance: python -m unittest tests.test_u177_slice_without_anchors tests.test_u107_ollama_slice tests.test_u22_worker_limits tests.test_u109_local_repair tests.test_u123_order_gate tests.test_u38_cost_gate_and_claude_worker
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Card U177. Design audited by Antigravity: relay_967da2ce469585aa872b265b18d18675 (PASS).

Problem: the local worker fails with PROMPT_TOO_LARGE before calling the model when a named file is large and the
task has no usable backtick anchors (ledger BLOCKED 20261010T1140-claude-0002).

Edit v7_harness/adapters/ollama_worker.py and v7_harness/manual.py in place with small search/replace edits. Never
rewrite a whole file. Never edit a test. The tests in tests/test_u177_slice_without_anchors.py state the behaviour.

1. Add a function named search_literals taking the task text and returning a dict from file name to a list of
   strings: for every dictated block (a line "===EDIT: name===" followed by "<<<<<<< SEARCH"), the first non-blank
   line of the SEARCH part, stripped.
2. Give `slice_text` two more parameters, literals (default an empty tuple) and definitions (default False). A line
   is a hit when its stripped text is one of the literals, or when an anchor matches it. With definitions True an
   anchor matches only a line that defines it, by file extension: .py (def, async def, class, or the name at column
   0 followed by = or :), .js .jsx .ts .tsx (function, class, const, let, var, with optional export, default,
   async), .md (a heading line containing the name), .sh (name() or function name). Any other extension gives no
   anchor patterns. It returns None when there are neither anchors nor literals, or no hit.
3. Add a function named fit_prompt taking task, named, limit and returning a tuple (rules, prompt, estimated,
   problem, cut). It builds the same prompt `main` builds today. When the prompt is over the limit: a literal that
   is on no line of its large file gives the problem "SEARCH_ANCHOR_NOT_FOUND:<file>:<first 60 characters>"; else
   it tries word matching at each window of SLICE_WINDOWS, then definitions at each window, and returns the first
   candidate that fits. When nothing fits the problem starts with "PROMPT_TOO_LARGE: ~<estimated> tokens > <limit>"
   and tells the author to name the functions to edit in backticks.
4. `main` calls fit_prompt instead of building the prompt itself, logs context_sliced when cut is set, and returns
   the ERROR envelope with the problem text when problem is not empty.
5. Add a function named preflight taking the task text and the workspace path and returning the problem text that
   fit_prompt gives for the files `context_files` names (first four), or an empty string.
6. In v7_harness/manual.py, the function `lint` appends the warning "LOCAL_" + problem when the contract worker is
   local or cascade and preflight returns a problem.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
