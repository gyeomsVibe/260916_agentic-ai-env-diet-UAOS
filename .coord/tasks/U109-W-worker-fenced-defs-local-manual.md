```contract
work_id: U109-W
worker: local
goal: Ollama worker applies a fenced block of whole definitions after ===EDIT (its natural shape) via def_splice, and the edit rules offer that shape
inputs:
- v7_harness/adapters/ollama_worker.py sha256=830a434174953cbc91b8160bc7a6a2ddd8dec0d8e8ff3444154cb27c7e7028c0
- tests/test_u109_worker_accepts_definitions.py sha256=0d752e53bcf61ed6083e51176b822814c590da2a3e439b39a3a1ca0e03606bbd
allow:
- v7_harness/adapters/ollama_worker.py
context_allow:
- v7_harness/adapters/ollama_worker.py
acceptance: python -m unittest tests.test_u109_worker_accepts_definitions tests.test_u109_def_splice tests.test_u107_ollama_slice tests.test_u17_lane_worker tests.test_u47_olla_record
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the blocks below exactly.

===EDIT: v7_harness/adapters/ollama_worker.py===
<<<<<<< SEARCH
    r"^===EDIT:\s*(?P<path>[^\n=]+?)\s*===\n<<<<<<< SEARCH\n(?P<search>.*?)\n=======\n(?P<replace>.*?)\n>>>>>>> REPLACE",
    re.M | re.S,
)
=======
    r"^===EDIT:\s*(?P<path>[^\n=]+?)\s*===\n<<<<<<< SEARCH\n(?P<search>.*?)\n=======\n(?P<replace>.*?)\n>>>>>>> REPLACE",
    re.M | re.S,
)
# U109-W: the shape qwen2.5-coder:7b emits on its own (U107-B): `===EDIT: path===`, then a fenced block of whole defs.
FENCED_EDIT_RE = re.compile(r"^===EDIT:\s*(?P<path>[^\n=]+?)\s*===\n```[\w+-]*\n(?P<code>.*?)\n```", re.M | re.S)
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/adapters/ollama_worker.py===
<<<<<<< SEARCH
- Do not output the rest of the file. Do not add explanations or markdown fences.
"""
=======
- Do not output the rest of the file. Do not add explanations.
- For a .py file you may instead write the ===EDIT: line, then one ```python fenced block holding each changed
  function, class, or constant COMPLETE; each replaces the one with the same name, and new names are added.
"""
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/adapters/ollama_worker.py===
<<<<<<< SEARCH
        pending[target] = (rel, current.replace(search, match.group("replace"), 1))
        if rel not in written:
            written.append(rel)
=======
        pending[target] = (rel, current.replace(search, match.group("replace"), 1))
        if rel not in written:
            written.append(rel)

    for match in FENCED_EDIT_RE.finditer(text):
        from v7_harness.adapters.def_splice import splice_definitions
        rel, target = _target(workspace, match.group("path"))
        if target.suffix.lower() != ".py" or not (target in pending or target.is_file()):
            raise ValueError(f"EDIT_FENCED_NEEDS_EXISTING_PY:{rel}")
        current = pending[target][1] if target in pending else target.read_text(encoding="utf-8")
        pending[target] = (rel, splice_definitions(current, match.group("code")))
        if rel not in written:
            written.append(rel)
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
