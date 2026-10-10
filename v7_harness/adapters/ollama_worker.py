"""로컬 Ollama 모델을 파일럿 작업자로 쓰는 어댑터.

파일럿은 작업자에게 `-p <프롬프트> --output-format json --print-timeout Ns --add-dir <작업공간>`
형태로 말을 걸고, 작업자가 그 작업공간의 파일을 고친 뒤 JSON 한 덩어리를 찍어 주길 기대한다.
이 스크립트는 그 규격을 로컬 모델에 맞춰 준다.

의도적으로 좁게 만든다. 7B 모델에게 자유로운 편집을 맡기면 거의 실패한다. 대신
"파일 전체를 새로 써 달라"는 한 가지 형식만 받아들이고, 형식을 벗어나면 실패로 끝낸다.
판정은 이 스크립트가 하지 않는다. 파일럿의 인수 검사와 게이트가 한다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# The pilot starts this file by path, not with -m, and does not set PYTHONPATH, so the package import in main()
# failed with ModuleNotFoundError and every `--worker local` run ended BLOCKED (found 2026-09-23 in the e2e bench).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# 서버 주소·모델·문맥 크기는 환경변수로 덮어쓸 수 있다. 기본값은 이 PC의 실측 설정이다
# (GTX 1660 Ti 6GB에서 qwen2.5-coder:7b Q4_K_M 이 VRAM 4.3GB, 문맥 16384로 동작).
HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
API = f"{HOST}/api/generate"
DEFAULT_MODEL = os.environ.get("OLLAMA_WORKER_MODEL", "qwen2.5-coder:7b")
NUM_CTX = int(os.environ.get("OLLAMA_WORKER_NUM_CTX", "16384"))
# 출력 상한. 무한 생성이 600초 시간 초과(PROVIDER_ERROR)로 끝나는 것을 막는다. EDIT 블록은 짧고 150줄 미만 파일 전체 재작성도 약 2k 토큰이라 4096이면 충분하다.
NUM_PREDICT = int(os.environ.get("OLLAMA_WORKER_NUM_PREDICT", "4096"))
KEEP_ALIVE = os.environ.get("OLLAMA_WORKER_KEEP_ALIVE", "30m")
# Fixed seed: the same prompt gives the same output, so a failure can be reproduced and a manual change can be
# compared against the same sample (Ollama API: `seed` makes generation reproducible).
SEED = int(os.environ.get("OLLAMA_WORKER_SEED", "42"))
# U45-F2: a FILE block also ends at an explicit `===END===` line or at the `## Output` section `pilot manual new`
# appends, so a trailing FILE block no longer swallows that text (U45-G2: SYNTAX_ERROR).
BLOCK_RE = re.compile(
    r"^===FILE:\s*(?P<path>[^\n=]+?)\s*===\n(?P<body>.*?)"
    r"(?=^===(?:FILE|EDIT):|^===END===[ \t]*$|^## Output\n\n- (?:Reply with|Edit the files)|\Z)",
    re.M | re.S,
)
EDIT_RE = re.compile(
    r"^===EDIT:\s*(?P<path>[^\n=]+?)\s*===\n<<<<<<< SEARCH\n(?P<search>.*?)\n=======\n(?P<replace>.*?)\n>>>>>>> REPLACE",
    re.M | re.S,
)
# U109-W: the shape qwen2.5-coder:7b emits on its own (U107-B): `===EDIT: path===`, then a fenced block of whole defs.
FENCED_EDIT_RE = re.compile(r"^===EDIT:\s*(?P<path>[^\n=]+?)\s*===\n```[\w+-]*\n(?P<code>.*?)\n```", re.M | re.S)

# 이 줄 수를 넘는 파일은 "찾아서 바꾸기" 형식을 쓰게 한다. 벤치에서 483줄 파일 한 줄 교체가
# 전체 재작성 때문에 118초 걸렸다. 나머지 줄을 다시 쓰는 것은 시간만 들고 틀릴 기회만 늘린다.
EDIT_MODE_MIN_LINES = int(os.environ.get("OLLAMA_WORKER_EDIT_MIN_LINES", "150"))
SLICE_WINDOWS = (25, 10, 3)  # lines kept on each side of an anchor; try wider first, shrink until it fits
ANCHOR_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")  # identifier tokens in backtick spans to anchor slices around

# 7B 모델이 형식 안내의 자리표시자 경로를 그대로 따라 쓰는 일이 있다(U22a 실측: UNKNOWN_DIR:<relative/path>).
# 그런 블록은 실제 편집이 아니므로 건너뛴다. 하나 때문에 나머지 올바른 편집까지 실패하지 않게 한다.
TEMPLATE_PATH = "<relative/path>"

FORMAT_RULES = """
You are editing files inside the given workspace. Reply with nothing but file blocks.

Format, repeated once per file you change:
===FILE: <relative/path>===
<the complete new content of that file>

Rules:
- Output the WHOLE file, not a diff and not a fragment.
- Do not add explanations, markdown fences, or comments about your work.
- Only touch files the task names. Leave every other line of those files byte-identical.
"""

EDIT_RULES = """
You are editing files inside the given workspace. Reply with nothing but edit blocks.

Format, repeated once per change:
===EDIT: <relative/path>===
<<<<<<< SEARCH
<exact lines copied from the current file>
=======
<the lines that replace them>
>>>>>>> REPLACE

Rules:
- SEARCH must match the current file exactly, including indentation, and appear only once.
- Keep SEARCH short: just enough lines to be unique.
- Do not output the rest of the file. Do not add explanations.
- For a .py file you may instead write the ===EDIT: line, then one ```python fenced block holding each changed
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


REPAIRS = int(os.environ.get("OLLAMA_WORKER_REPAIRS", "1"))  # U109: one free retry with the error fed back; a same-seed retry repeats the reply
REPEAT_LIMIT = 8  # U109: one line this many times in a row is a loop (U109-S wrote 300+ copies), not code


def _generate(model: str, prompt: str, timeout_s: int, *, fmt: dict | None = None, seed: int | None = None) -> tuple[str, dict[str, int]]:
    """`fmt` is an Ollama structured-output JSON schema: the model can only emit JSON of that shape."""
    request_body: dict = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": KEEP_ALIVE,
        # 낮은 온도. 이 작업자는 창작이 아니라 지시받은 줄을 그대로 옮기는 손이다.
        "options": {"temperature": 0.1, "num_ctx": NUM_CTX, "num_predict": NUM_PREDICT, "seed": SEED if seed is None else seed},
    }
    if fmt is not None:
        request_body["format"] = fmt
    payload = json.dumps(request_body).encode("utf-8")
    request = urllib.request.Request(API, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        body = json.loads(response.read().decode("utf-8"))
    usage = {
        "input_tokens": int(body.get("prompt_eval_count") or 0),
        "output_tokens": int(body.get("eval_count") or 0),
    }
    return str(body.get("response") or ""), usage


def _target(workspace: Path, raw: str) -> tuple[str, Path]:
    rel = raw.strip().replace("\\", "/")
    target = (workspace / rel).resolve()
    if not str(target).startswith(str(workspace.resolve())):
        raise ValueError(f"PATH_ESCAPE:{rel}")
    if not target.parent.is_dir():
        raise ValueError(f"UNKNOWN_DIR:{rel}")
    return rel, target


DEFINITION_RE = re.compile(r"^[ \t]*(?:async[ \t]+def|def|class)[ \t]+([A-Za-z_]\w*)", re.M)
DELETION_WORDS = re.compile(r"(?i)\b(?:remove|delete|drop|rename|replace)\b|삭제|제거|이름을")
NEGATION_WORDS = re.compile(r"(?i)\b(?:do not|don't|never|must not)\b|금지|하지 마|말 것|않는다")


def _deletion_requested(name: str, task: str) -> bool:
    # A name alone is not a request: "forbidden: do not delete cmd_coord_log" mentions it too.
    named = re.compile(rf"\b{re.escape(name)}\b")
    return any(
        named.search(line) and DELETION_WORDS.search(line) and not NEGATION_WORDS.search(line)
        for line in task.splitlines()
    )


def dictated_paths(text: str) -> list[str]:
    """Paths of the ===FILE/===EDIT blocks written in *text* (placeholder paths excluded)."""
    found = [m.group("path").strip() for m in (*BLOCK_RE.finditer(text), *EDIT_RE.finditer(text))]
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


def _guard(rel: str, target: Path, content: str, task: str) -> None:
    """Deterministic checks on a worker's new file before anything is written.

    A small model can drop whole functions while "rewriting" a file (P08 lost `cmd_coord_log` and passed its
    one-test acceptance), or return prose instead of code. A definition may only disappear when the task names it.
    """
    if target.suffix.lower() != ".py":
        return
    try:
        compile(content, rel, "exec")
    except SyntaxError as exc:
        raise ValueError(f"SYNTAX_ERROR:{rel}:{exc.lineno}") from exc
    if not target.is_file():
        return
    removed = set(DEFINITION_RE.findall(target.read_text(encoding="utf-8"))) - set(DEFINITION_RE.findall(content))
    unrequested = sorted(name for name in removed if not _deletion_requested(name, task))
    if unrequested:
        raise ValueError(f"UNREQUESTED_DELETION:{rel}:{','.join(unrequested[:5])}")


def _plan(text: str, workspace: Path, fenced: bool = True) -> tuple[dict[Path, tuple[str, str]], list[str]]:
    """블록을 메모리에서 새 파일 내용으로 바꾼다(쓰지 않는다). 작업공간 밖 경로는 거부한다. U124: _apply 와 받아쓰기 검사가 함께 쓴다.

    두 형식을 받는다. `===FILE:`는 파일 전체, `===EDIT:`는 찾아서 바꾸기다.
    찾아서 바꾸기는 SEARCH가 정확히 한 번 나올 때만 적용한다. 0번이면 모델이 원문을
    잘못 옮긴 것이고, 2번 이상이면 어디를 바꿀지 모호하다. 둘 다 추측하지 않고 실패로 끝낸다.
    `task` 에 이름이 없는 함수·클래스를 지우거나 문법이 깨진 .py 는 거부한다(_guard).
    """
    # U47-N2: the block patterns expect "\n"; a reply whose own lines end in "\r\n" matched nothing and was dropped in
    # silence. Line endings of the written file are the target file's own (U47-N1), so normalising here loses nothing.
    text = text.replace("\r\n", "\n")
    written: list[str] = []
    pending: dict[Path, tuple[str, str]] = {}
    for match in BLOCK_RE.finditer(text):
        if match.group("path").strip() == TEMPLATE_PATH:
            continue
        rel, target = _target(workspace, match.group("path"))
        # 로컬 모델이 파일 전체를 마크다운 코드 펜스로 감싸 SyntaxError가 발생하는 것을 방지한다.
        # 마크다운(.md) 파일은 코드 펜스 자체가 본문 내용이므로 펜스 제거를 건너뛴다.
        body = match.group("body").rstrip("\n")
        lines = body.splitlines()
        if target.suffix.lower() != ".md" and len(lines) >= 2 and lines[0].strip().startswith("```") and lines[-1].strip() == "```":
            body = "\n".join(lines[1:-1])
        pending[target] = (rel, body + "\n")
        if rel not in written:
            written.append(rel)

    for match in EDIT_RE.finditer(text):
        if match.group("path").strip() == TEMPLATE_PATH:
            continue
        rel, target = _target(workspace, match.group("path"))
        if target in pending:
            current = pending[target][1]
        elif target.is_file():
            current = target.read_text(encoding="utf-8")
        else:
            raise ValueError(f"EDIT_TARGET_MISSING:{rel}")
        search = match.group("search")
        hits = current.count(search)
        if hits != 1:
            raise ValueError(f"EDIT_SEARCH_{'NOT_FOUND' if hits == 0 else 'AMBIGUOUS'}:{rel}")
        pending[target] = (rel, current.replace(search, match.group("replace"), 1))
        if rel not in written:
            written.append(rel)

    for match in (FENCED_EDIT_RE.finditer(text) if fenced else ()):
        from v7_harness.adapters.def_splice import splice_definitions
        rel, target = _target(workspace, match.group("path"))
        if target.suffix.lower() != ".py" or not (target in pending or target.is_file()):
            raise ValueError(f"EDIT_FENCED_NEEDS_EXISTING_PY:{rel}")
        current = pending[target][1] if target in pending else target.read_text(encoding="utf-8")
        pending[target] = (rel, splice_definitions(current, match.group("code")))
        if rel not in written:
            written.append(rel)

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
    for target, (rel, content) in pending.items():
        _guard(rel, target, content, task)
    # 모든 블록이 검증된 뒤에만 쓴다. 중간에 하나라도 실패하면 아무 파일도 바뀌지 않는다.
    for target, (_rel, content) in pending.items():
        # U47-N1: write_text turned every "\n" into "\r\n" on Windows, so an LF file came back CRLF and exact-byte
        # acceptance failed on a correct edit. Keep the line ending the file already uses; a new file gets LF.
        target.write_bytes(content.replace("\r\n", "\n").replace("\n", endings[target]).encode("utf-8"))
    return written


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
    """The one line ending an existing file uses; LF for a new file or one without line breaks.

    U47-N1d: Codex's re-review (2026-09-27) sent b"a\\r\\nb\\n" and got every line back as CRLF. One ending per file
    cannot keep a mixed file's bytes, and guessing per line after a model rewrote it is not reliable, so a file that
    mixes CRLF, LF or a bare CR is refused before anything is written.
    """
    if not target.is_file():
        return "\n"
    data = target.read_bytes()
    crlf = data.count(b"\r\n")
    kinds = [eol for eol, n in (("\r\n", crlf), ("\n", data.count(b"\n") - crlf), ("\r", data.count(b"\r") - crlf)) if n]
    if len(kinds) > 1:
        raise ValueError(f"MIXED_LINE_ENDINGS:{rel}")
    return kinds[0] if kinds else "\n"


def context_files(prompt: str, workspace: Path) -> list[str]:
    """Files whose current content goes with the task. The contract's pinned inputs come first (U45-F3: the local
    worker got the manual but not the input it had to read, and guessed ids 1..38), then the files the task names."""
    def present(raw: str) -> str | None:
        rel = raw.strip().replace("\\", "/")
        return rel if (workspace / rel).is_file() else None

    pinned = [p for p in (present(m) for m in re.findall(r"^- (\S+) sha256=[0-9a-f]{64}\s*$", prompt, re.M)) if p]
    named = sorted({p for p in (present(m) for m in re.findall(r"`([^`\n]+\.(?:md|py|txt))`", prompt)) if p}
                   | {p for p in (present(m) for m in re.findall(r"^===(?:FILE|EDIT):\s*([^\n=]+?)\s*===", prompt,
                                                                 re.M)) if p}
                   | {name for name in ("core.md", "GLOBAL_RULES.ko.md", "VERSION", "history.md")
                      if (workspace / name).is_file() and name in prompt})
    return list(dict.fromkeys([*pinned, *named]))


def admitted_context(prompt: str, workspace: Path) -> list[tuple[str, str]]:
    """U50: context_files() filtered by the manual's context_allow; each denied file is recorded, never dropped
    silently, so an acceptance failure can be traced to a missing file instead of widening the list blindly.
    U50-R2: returns (name, text) read once through a checked handle; callers must not re-open the name (TOCTOU)."""
    from v7_harness.context_admission import admit

    admission = admit(prompt, context_files(prompt, workspace), workspace)
    if admission.escaped:
        _log("context_escape", work_id=contract_work_id(prompt), escaped=admission.escaped)
    if admission.denied:
        _log("context_denied", work_id=contract_work_id(prompt), denied=admission.denied)
    return [(name, admission.snapshots[name]) for name in admission.admitted]


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
    """U47-O2: the work id from the manual's contract block, so a `pilot_local` row can be joined to its pilot run."""
    found = re.search(r"^work_id:\s*(\S+)\s*$", prompt, re.M)
    return found.group(1) if found else None


def _log(event: str, **fields) -> None:
    """로컬 모델 사용 기록을 한 곳(olla 사용 기록)에 모은다. 파일럿과 보조 호출이 따로 세면 합계를 못 낸다."""
    try:
        from v7_harness import olla

        olla.log_usage(event, **fields)
    except Exception:  # noqa: BLE001 — 기록 실패가 파일럿을 막으면 안 된다
        pass


def task_anchors(task: str) -> list[str]:
    seen: set[str] = set()
    anchors: list[str] = []
    for span in re.findall(r"`([^`\n]+)`", task):
        if "/" in span or span.endswith((".py", ".md", ".txt", ".json")):
            continue
        for m in ANCHOR_RE.findall(span):
            if m not in seen:
                seen.add(m)
                anchors.append(m)
    return anchors


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
    if not hit_lines:
        return None

    ranges: list[tuple[int, int]] = []
    for i in hit_lines:
        start = max(0, i - radius)
        end = min(len(lines), i + radius + 1)
        ranges.append((start, end))

    merged: list[tuple[int, int]] = []
    for start, end in ranges:
        if not merged:
            merged.append((start, end))
        else:
            prev_start, prev_end = merged[-1]
            if start <= prev_end:
                merged[-1] = (prev_start, max(prev_end, end))
            else:
                merged.append((start, end))

    parts = [f"\n===CURRENT FILE: {name} (partial: {len(lines)} lines, only the lines below are shown; the rest is omitted)===\n"]
    last_end = 0
    for start, end in merged:
        if start > last_end:
            parts.append(f"... lines {last_end + 1}-{start} omitted ...\n")
        parts.extend(lines[start:end])
        last_end = end
    if last_end < len(lines):
        if parts and not parts[-1].endswith("\n"):
            parts.append("\n")
        parts.append(f"... lines {last_end + 1}-{len(lines)} omitted ...\n")

    return "".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--prompt", required=True)
    parser.add_argument("--output-format", default="json")
    parser.add_argument("--print-timeout", default="600s")
    parser.add_argument("--add-dir", dest="workspace", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--conversation", default=None)
    parser.add_argument("--json-schema", default=None)
    parser.add_argument("--dangerously-skip-permissions", action="store_true")
    args, _unknown = parser.parse_known_args(argv)
    from v7_harness.adapters.long_prompt import resolve_prompt

    args.prompt = resolve_prompt(args.prompt)

    workspace = Path(args.workspace)
    timeout_s = int(str(args.print_timeout).rstrip("s") or 600)

    def envelope(status: str, response: str, usage: dict[str, int], error: str = "") -> int:
        # U68-L: ASCII escapes; a cp949 pilot pipe raised UnicodeEncodeError on U+2014 and lost the envelope (U67-C1).
        print(json.dumps(
            {"status": status, "response": response, "usage": usage, "conversation_id": "ollama-local", "error": error},
            ensure_ascii=True,
        ))
        return 0 if status == "SUCCESS" else 1

    limit = NUM_CTX - NUM_PREDICT
    # U47-O2: every row names the model and the work, so the ledger can be joined to pilot outcomes and distilled.
    run = {"model": args.model, "work_id": contract_work_id(args.prompt)}

    # 과제가 가리키는 파일의 현재 내용을 함께 준다. 7B 모델은 파일을 스스로 찾지 못한다.
    # U50-R2: the admitted text itself travels on; re-reading workspace / name here let a swapped link leak.
    named = admitted_context(args.prompt, workspace)[:4]
    # U177: one function builds the prompt, so `pilot manual lint` can report the same failure before a run.
    rules, prompt, estimated, problem, cut = fit_prompt(args.prompt, named, limit)
    if cut:
        _log("context_sliced", work_id=run["work_id"], **cut)
    if problem:
        _log("pilot_local", status=problem.split(":")[0], elapsed_s=0.0, estimated_tokens=estimated, **run)
        return envelope("ERROR", "", {"input_tokens": 0, "output_tokens": 0}, problem)
    from v7_harness.adapters.gpu_priority import pilot_holds

    started = time.monotonic()
    try:
        with pilot_holds(timeout_s):  # 파일럿이 GPU 를 먼저 쓴다(B74). 보조 호출은 이 동안 양보한다
            text, usage = _generate(args.model, prompt, timeout_s)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        _log("pilot_local", status="ERROR", elapsed_s=round(time.monotonic() - started, 1), **run)
        return envelope("ERROR", "", {"input_tokens": 0, "output_tokens": 0}, f"ollama unreachable: {exc}")
    _log("pilot_local", status="GENERATED", elapsed_s=round(time.monotonic() - started, 1), **run, **usage)

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
    """(written paths, "") on success, ([], reason) when the reply cannot be used."""
    if degenerate(text):
        return [], f"DEGENERATE: one line repeated {REPEAT_LIMIT}+ times in a row"
    if "===FILE:" not in text and "===EDIT:" not in text:
        reframed = _reframe_dictation(text, task)
        if reframed is None:
            return [], "model returned no file block"
        text = reframed
    try:
        written = _apply(text, workspace, task=task)
    except ValueError as exc:
        return [], str(exc)
    return (written, "") if written else ([], "no file written")


if __name__ == "__main__":
    sys.exit(main())
