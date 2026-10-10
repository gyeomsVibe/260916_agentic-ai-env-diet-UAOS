```contract
work_id: U177-A2
worker: apply
apply_after: U177-L1
goal: U177 the local worker cuts a large file from SEARCH lines and definition lines without hand-written anchors; preflight reads admitted snapshots only
inputs:
- v7_harness/adapters/ollama_worker.py sha256=a4302acd256dc752804b9acb0b6ea6ff9773622dec3163484588242cdf245f01
- v7_harness/manual.py sha256=81f521ccb9afd87593df5999f9bf57ff87865c137c75c647d68fd16adc4938c2
- tests/test_u177_slice_without_anchors.py sha256=8a9ff30b50ea3cfe5eae8aadc03f11696e6a3e6d8d40d846ff8e6eb630094f55
allow:
- v7_harness/adapters/ollama_worker.py
- v7_harness/manual.py
acceptance: python -m unittest tests.test_u177_slice_without_anchors tests.test_u107_ollama_slice tests.test_u22_worker_limits tests.test_u109_local_repair tests.test_u123_order_gate tests.test_u38_cost_gate_and_claude_worker tests.test_u50_context_admission tests.test_u69_admission_gate
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Card U177. Design audited by Antigravity: relay_967da2ce469585aa872b265b18d18675 (PASS). Dictation: copy the four
edit blocks below exactly, in this order, and change nothing else. Do not rewrite any file.

===EDIT: v7_harness/adapters/ollama_worker.py===
<<<<<<< SEARCH
def slice_text(name: str, text: str, anchors: list[str], radius: int) -> str | None:
    lines = text.splitlines(keepends=True)
    if not lines or not anchors:
        return None
    patterns = [re.compile(rf"\b{re.escape(a)}\b") for a in anchors]
    hit_lines = [i for i, line in enumerate(lines) if any(p.search(line) for p in patterns)]
=======
# U177 (ledger BLOCKED 20261010T1140-claude-0002): U176-L1 and U176-C1 ended PROMPT_TOO_LARGE with the model never
# called. A dictated SEARCH block already names its lines, and a common word is on hundreds of lines, so the cut also
# reads SEARCH lines and, when word matches overflow, only the line that defines a name (Antigravity audit
# relay_967da2ce). An extension without a pattern has no definition tier.
SEARCH_HEAD_RE = re.compile(r"^===EDIT:\s*([^\n=]+?)\s*===\n<<<<<<< SEARCH\n(.*?)\n=======", re.M | re.S)
_JS_DEF = r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function\*?|class|const|let|var)\s+{a}\b"
DEF_PATTERNS = {
    ".py": r"^\s*(?:async\s+def|def|class)\s+{a}\b|^{a}\s*[:=]",
    ".js": _JS_DEF, ".jsx": _JS_DEF, ".ts": _JS_DEF, ".tsx": _JS_DEF,
    ".md": r"^#+\s.*\b{a}\b",
    ".sh": r"^\s*(?:function\s+{a}\b|{a}\s*\(\))",
}
ANCHOR_SHOWN = 60  # characters of a missing SEARCH line in the error: enough to find it, short enough for one line


def search_literals(task: str) -> dict[str, list[str]]:
    """The first non-blank SEARCH line of every dictated block, per file: each one is an exact place to show."""
    found: dict[str, list[str]] = {}
    for name, body in SEARCH_HEAD_RE.findall(task):
        first = next((line.strip() for line in body.splitlines() if line.strip()), "")
        if first and first not in found.setdefault(name, []):
            found[name].append(first)
    return found


def slice_text(name: str, text: str, anchors: list[str], radius: int, literals=(), definitions: bool = False) -> str | None:
    lines = text.splitlines(keepends=True)
    if not lines or not (anchors or literals):
        return None
    shape = DEF_PATTERNS.get(Path(name).suffix.lower()) if definitions else r"\b{a}\b"
    patterns = [re.compile(shape.format(a=re.escape(a))) for a in anchors] if shape else []
    wanted = set(literals)
    hit_lines = [i for i, line in enumerate(lines) if line.strip() in wanted or any(p.search(line) for p in patterns)]
>>>>>>> REPLACE

===EDIT: v7_harness/adapters/ollama_worker.py===
<<<<<<< SEARCH
def contract_work_id(prompt: str) -> str | None:
=======
def fit_prompt(task: str, named: list[tuple[str, str]], limit: int) -> tuple[str, str, int, str, dict | None]:
    """U177: (rules, prompt, estimated tokens, problem, cut). A prompt over the window is cut around what the task
    names: word matches first, then definition lines only, each at 25, 10 and 3 lines. Korean is about one token per
    3 bytes, so bytes // 3 estimates the size. A non-empty problem means the model must not be called."""
    def render(head: str, context: str) -> str:
        return f"{head}\n\nTASK:\n{task}\n\nCURRENT CONTENTS:{context}\n\nNow output the blocks."

    def size(value: str) -> int:
        return len(value.encode("utf-8")) // 3

    def block(name: str, text: str) -> str:
        return f"\n===CURRENT FILE: {name}===\n{text}\n"

    rules = _rules_for(named, task)
    prompt = render(rules, "".join(block(name, text) for name, text in named))
    estimated = size(prompt)
    if estimated <= limit:
        return rules, prompt, estimated, "", None
    anchors, literals = task_anchors(task), search_literals(task)
    big = [(name, text) for name, text in named if size(block(name, text)) > limit // 4]
    for name, text in big:
        present = {line.strip() for line in text.splitlines()}
        for literal in literals.get(name, []):
            if literal not in present:  # a whole file would only fail later, after the wait (audit relay_92656076)
                return rules, prompt, estimated, f"SEARCH_ANCHOR_NOT_FOUND:{name}:{literal[:ANCHOR_SHOWN]}", None
    cut_rules = DICTATION_RULES if rules is DICTATION_RULES else EDIT_RULES
    for definitions in (False, True):
        for radius in SLICE_WINDOWS:
            parts = []
            for name, text in named:
                cut = slice_text(name, text, anchors, radius, literals.get(name, ()), definitions) \
                    if (name, text) in big else None
                parts.append(cut if cut is not None else block(name, text))
            candidate = render(cut_rules, "".join(parts))
            if size(candidate) <= limit:
                return cut_rules, candidate, size(candidate), "", {"radius": radius, "definitions": definitions,
                                                                   "before": estimated, "after": size(candidate)}
    lines = sum(len(found) for found in literals.values())
    return rules, prompt, estimated, (f"PROMPT_TOO_LARGE: ~{estimated} tokens > {limit}; no cut fits ({len(anchors)} "
                                      f"backticked names, {lines} SEARCH lines): name the functions to edit in "
                                      "backticks, or dictate ===EDIT blocks"), None


def preflight(task: str, workspace: Path) -> str:
    """U177: the problem a local run of this manual would stop on before calling the model, or ''. It reads the same
    admitted snapshots as the run (Codex REWORK relay_af81221a: a direct read let `../outside.py` past admission)."""
    return fit_prompt(task, admitted_context(task, Path(workspace))[:4], NUM_CTX - NUM_PREDICT)[3]


def contract_work_id(prompt: str) -> str | None:
>>>>>>> REPLACE

===EDIT: v7_harness/adapters/ollama_worker.py===
<<<<<<< SEARCH
    named = admitted_context(args.prompt, workspace)[:4]
    whole = "".join(f"\n===CURRENT FILE: {name}===\n{text}\n" for name, text in named)

    # 대상 파일 중 하나라도 길면 찾아서 바꾸기 형식을 요구한다. 짧은 파일은 전체 재작성이
    # 더 안정적이다(벤치 6과제 모두 전체 재작성으로 통과).
    rules = _rules_for(named, args.prompt)
    prompt = f"{rules}\n\nTASK:\n{args.prompt}\n\nCURRENT CONTENTS:{whole}\n\nNow output the blocks."
    # 문맥을 넘는 프롬프트는 모델을 부르지 않고 바로 실패시킨다. 잘린 입력으로 600초를 기다린 뒤 실패하던 것을
    # 즉시 실패로 바꿔 cascade 가 곧바로 agy 로 넘긴다. 한국어가 1글자 3바이트·약 1토큰이라 바이트/3 으로 어림한다.
    estimated = len(prompt.encode("utf-8")) // 3

    if estimated > limit:
        anchors = task_anchors(args.prompt)
        if anchors:
            whole_est = estimated
            for radius in SLICE_WINDOWS:
                blocks: list[str] = []
                for name, text in named:
                    file_block = f"\n===CURRENT FILE: {name}===\n{text}\n"
                    if len(file_block.encode("utf-8")) // 3 > limit // 4:
                        sliced = slice_text(name, text, anchors, radius)
                        blocks.append(sliced if sliced is not None else file_block)
                    else:
                        blocks.append(file_block)
                cand_context = "".join(blocks)
                cand_rules = DICTATION_RULES if rules is DICTATION_RULES else EDIT_RULES
                cand_prompt = f"{cand_rules}\n\nTASK:\n{args.prompt}\n\nCURRENT CONTENTS:{cand_context}\n\nNow output the blocks."
                cand_est = len(cand_prompt.encode("utf-8")) // 3
                if cand_est <= limit:
                    rules = cand_rules
                    prompt = cand_prompt
                    estimated = cand_est
                    _log("context_sliced", work_id=run["work_id"], radius=radius, before=whole_est, after=estimated)
                    break

    if estimated > limit:
        _log("pilot_local", status="PROMPT_TOO_LARGE", elapsed_s=0.0, estimated_tokens=estimated, **run)
        return envelope("ERROR", "", {"input_tokens": 0, "output_tokens": 0}, f"PROMPT_TOO_LARGE: ~{estimated} tokens > {limit}")
=======
    named = admitted_context(args.prompt, workspace)[:4]
    # U177: one function builds the prompt, so `pilot manual lint` can report the same failure before a run.
    rules, prompt, estimated, problem, cut = fit_prompt(args.prompt, named, limit)
    if cut:
        _log("context_sliced", work_id=run["work_id"], **cut)
    if problem:
        _log("pilot_local", status=problem.split(":")[0], elapsed_s=0.0, estimated_tokens=estimated, **run)
        return envelope("ERROR", "", {"input_tokens": 0, "output_tokens": 0}, problem)
>>>>>>> REPLACE

===EDIT: v7_harness/manual.py===
<<<<<<< SEARCH
    judge = contract.get("judge", "").lower()
=======
    judge = contract.get("judge", "").lower()
    if worker in ("local", "cascade"):
        from v7_harness.adapters.ollama_worker import preflight

        problem = preflight(text, project)  # U177: the author learns before a run that the model would not be called
        if problem:
            report.warnings.append(f"LOCAL_{problem}")
>>>>>>> REPLACE



## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
