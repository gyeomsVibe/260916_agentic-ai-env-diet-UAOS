```contract
work_id: U124-L2
worker: local
goal: Ollama copies dictated edits Antigravity U23 style; a copy that differs from the dictation is refused (U124)
inputs:
- v7_harness/adapters/ollama_worker.py sha256=1df20171a36ef67b5dc03ee256874d14fb0792c33cbb3b718941d2fb2a1c1340
allow:
- v7_harness/adapters/ollama_worker.py
acceptance: python -m unittest tests.test_u124_edit_rules_for_py tests.test_u22_worker_limits tests.test_u109_def_splice tests.test_u109_local_repair tests.test_u109_worker_accepts_definitions tests.test_u47_n2_crlf_reply tests.test_u47_n1_newline_preserved tests.test_u47_n1d_mixed_endings tests.test_u47_olla_record
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

# Work order: Ollama copies dictated edits, and a wrong copy is refused (U124)

- Target file: `v7_harness/adapters/ollama_worker.py`
- Anchor: `_apply`

Copy the eight edit blocks below into the file exactly, in this order, in this same SEARCH/REPLACE format.
Do not rewrite whole functions. Change nothing else.

===EDIT: v7_harness/adapters/ollama_worker.py===
<<<<<<< SEARCH
  function, class, or constant COMPLETE; each replaces the one with the same name, and new names are added.
"""
=======
  function, class, or constant COMPLETE; each replaces the one with the same name, and new names are added.
"""

# U124: the TASK already holds the exact blocks (Antigravity's U23 way) and the model only copies them. No fenced
# format here: U124-L re-emitted a whole function that way and dropped three of its lines.
DICTATION_RULES = """
You are copying edits into files. The TASK below already contains the exact edit blocks.

Reply with nothing but those same blocks, copied character for character, in the same order and the same format.

Rules:
- Do not change, shorten, merge, reorder, or add blocks.
- Do not rewrite whole functions or whole files the TASK did not write that way.
- Do not add explanations or markdown fences.
"""
>>>>>>> REPLACE

===EDIT: v7_harness/adapters/ollama_worker.py===
<<<<<<< SEARCH
    return sorted({path for path in found if path != TEMPLATE_PATH})
=======
    return sorted({path for path in found if path != TEMPLATE_PATH})


def _rules_for(named: list[tuple[str, str]], task: str = "") -> str:
    """U124: dictated blocks are copied (DICTATION_RULES). An existing .py file always gets find-and-replace, since a
    whole-file rewrite let the 7B model drop untouched functions (U123-L, U123-L2). Other files keep the length rule."""
    if dictated_paths(task):
        return DICTATION_RULES
    if any(name.endswith(".py") for name, _text in named):
        return EDIT_RULES
    longest = max((len(text.splitlines()) for _name, text in named), default=0)
    return EDIT_RULES if longest >= EDIT_MODE_MIN_LINES else FORMAT_RULES
>>>>>>> REPLACE

===EDIT: v7_harness/adapters/ollama_worker.py===
<<<<<<< SEARCH
def _apply(text: str, workspace: Path, task: str = "") -> list[str]:
    """모델이 돌려준 블록을 작업공간에 쓴다. 작업공간 밖 경로는 거부한다.
=======
def _plan(text: str, workspace: Path, fenced: bool = True) -> tuple[dict[Path, tuple[str, str]], list[str]]:
    """블록을 메모리에서 새 파일 내용으로 바꾼다(쓰지 않는다). 작업공간 밖 경로는 거부한다. U124: _apply 와 받아쓰기 검사가 함께 쓴다.
>>>>>>> REPLACE

===EDIT: v7_harness/adapters/ollama_worker.py===
<<<<<<< SEARCH
    for match in FENCED_EDIT_RE.finditer(text):
=======
    for match in (FENCED_EDIT_RE.finditer(text) if fenced else ()):
>>>>>>> REPLACE

===EDIT: v7_harness/adapters/ollama_worker.py===
<<<<<<< SEARCH
    endings = {target: _line_ending(rel, target) for target, (rel, _content) in pending.items()}
=======
    return pending, written


def _apply(text: str, workspace: Path, task: str = "") -> list[str]:
    """모델이 돌려준 블록을 작업공간에 쓴다.

    U124: when the task itself holds ===EDIT or ===FILE blocks (dictation, Antigravity's U23 way), the model only
    copies them. The task's blocks are planned first, so a SEARCH that does not apply, or FILE and EDIT for one path,
    fails fast (relay_37ea8879). The reply must then give exactly the same files and contents, else DICTATION_MISMATCH
    and nothing is written (U124-L dropped three lines of a function it re-emitted).
    """
    expected = _dictation_plan(task, workspace)
    pending, written = _plan(text, workspace, fenced=expected is None)
    if expected is not None:
        _check_dictation(expected, pending)
    endings = {target: _line_ending(rel, target) for target, (rel, _content) in pending.items()}
>>>>>>> REPLACE

===EDIT: v7_harness/adapters/ollama_worker.py===
<<<<<<< SEARCH
def _line_ending(rel: str, target: Path) -> str:
=======
def _dictation_plan(task: str, workspace: Path) -> dict[Path, tuple[str, str]] | None:
    """Expected contents of the files the task dictates, or None when the task dictates nothing."""
    task = task.replace("\r\n", "\n")
    if not dictated_paths(task):
        return None
    files = {m.group("path").strip() for m in BLOCK_RE.finditer(task)}
    edits = {m.group("path").strip() for m in EDIT_RE.finditer(task)}
    for rel in sorted((files & edits) - {TEMPLATE_PATH}):
        raise ValueError(f"DICTATION_BLOCK_CONFLICT:{rel}")
    try:
        return _plan(task, workspace, fenced=False)[0]
    except ValueError as exc:
        raise ValueError(f"DICTATION_{exc}") from exc


def _check_dictation(expected: dict[Path, tuple[str, str]], pending: dict[Path, tuple[str, str]]) -> None:
    """The reply must change exactly the dictated files, each to exactly the dictated content (line endings aside)."""
    for target in sorted(set(expected) | set(pending)):
        rel = (expected.get(target) or pending[target])[0]
        want = expected[target][1].replace("\r\n", "\n").split("\n") if target in expected else None
        got = pending[target][1].replace("\r\n", "\n").split("\n") if target in pending else None
        if want != got:
            line = 0 if want is None or got is None else next(
                (i + 1 for i, (a, b) in enumerate(zip(want, got)) if a != b), min(len(want), len(got)) + 1)
            raise ValueError(f"DICTATION_MISMATCH:{rel}:{line}")


def _line_ending(rel: str, target: Path) -> str:
>>>>>>> REPLACE

===EDIT: v7_harness/adapters/ollama_worker.py===
<<<<<<< SEARCH
    longest = max((len(text.splitlines()) for _name, text in named), default=0)
    rules = EDIT_RULES if longest >= EDIT_MODE_MIN_LINES else FORMAT_RULES
=======
    rules = _rules_for(named, args.prompt)
>>>>>>> REPLACE

===EDIT: v7_harness/adapters/ollama_worker.py===
<<<<<<< SEARCH
                cand_rules = EDIT_RULES
=======
                cand_rules = DICTATION_RULES if rules is DICTATION_RULES else EDIT_RULES
>>>>>>> REPLACE


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
