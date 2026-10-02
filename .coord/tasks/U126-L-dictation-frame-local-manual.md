```contract
work_id: U126-L
worker: local
goal: A frameless copy of the dictated REPLACE text is the copy (U126, dictated)
inputs:
- v7_harness/adapters/ollama_worker.py sha256=9a643e003c17df11a2a7ce20ff8e7b0296e33e0b57848b8b182bf7d3cef2fb60
allow:
- v7_harness/adapters/ollama_worker.py
acceptance: python -m unittest tests.test_u126_dictation_frame tests.test_u124_edit_rules_for_py tests.test_u22_worker_limits tests.test_u109_def_splice tests.test_u109_local_repair tests.test_u109_worker_accepts_definitions tests.test_u47_n2_crlf_reply tests.test_u47_n1_newline_preserved tests.test_u47_n1d_mixed_endings tests.test_u47_olla_record
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

# Work order: a frameless copy of the dictated REPLACE text is the copy (U126)

- Target file: `v7_harness/adapters/ollama_worker.py`
- Anchor: `_try_apply`

Copy the two edit blocks below into the file exactly, in this order, in this same SEARCH/REPLACE format.
Do not rewrite whole functions. Change nothing else.

===EDIT: v7_harness/adapters/ollama_worker.py===
<<<<<<< SEARCH
def _try_apply(text: str, workspace: Path, task: str) -> tuple[list[str], str]:
=======
def _reframe_dictation(text: str, task: str) -> str | None:
    """U126: the dictated EDIT blocks when the reply gives exactly their REPLACE lines without the frame, else None.

    U125-L2 and U125-L2R replied to a one-block dictation with only the REPLACE text, fenced under `===FILE / path===`
    (a 363-token probe without file context did the same). Fence and `===` lines are dropped; every other non-blank
    line must equal the dictated REPLACE lines in order, indentation included. A dictated FILE block is never reframed.
    """
    task = task.replace("\r\n", "\n")
    if any(m.group("path").strip() != TEMPLATE_PATH for m in BLOCK_RE.finditer(task)):
        return None
    blocks = [m for m in EDIT_RE.finditer(task) if m.group("path").strip() != TEMPLATE_PATH]
    want = [line for m in blocks for line in m.group("replace").split("\n") if line.strip()]
    got = [line for line in text.replace("\r\n", "\n").split("\n")
           if line.strip() and not line.lstrip().startswith(("```", "==="))]
    return "\n\n".join(m.group(0) for m in blocks) + "\n" if blocks and want == got else None


def _try_apply(text: str, workspace: Path, task: str) -> tuple[list[str], str]:
>>>>>>> REPLACE

===EDIT: v7_harness/adapters/ollama_worker.py===
<<<<<<< SEARCH
    if "===FILE:" not in text and "===EDIT:" not in text:
        return [], "model returned no file block"
=======
    if "===FILE:" not in text and "===EDIT:" not in text:
        reframed = _reframe_dictation(text, task)
        if reframed is None:
            return [], "model returned no file block"
        text = reframed
>>>>>>> REPLACE


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
