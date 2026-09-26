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

# 이 줄 수를 넘는 파일은 "찾아서 바꾸기" 형식을 쓰게 한다. 벤치에서 483줄 파일 한 줄 교체가
# 전체 재작성 때문에 118초 걸렸다. 나머지 줄을 다시 쓰는 것은 시간만 들고 틀릴 기회만 늘린다.
EDIT_MODE_MIN_LINES = int(os.environ.get("OLLAMA_WORKER_EDIT_MIN_LINES", "150"))

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
- Do not output the rest of the file. Do not add explanations or markdown fences.
"""


def _generate(model: str, prompt: str, timeout_s: int, *, fmt: dict | None = None) -> tuple[str, dict[str, int]]:
    """`fmt` is an Ollama structured-output JSON schema: the model can only emit JSON of that shape."""
    request_body: dict = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": KEEP_ALIVE,
        # 낮은 온도. 이 작업자는 창작이 아니라 지시받은 줄을 그대로 옮기는 손이다.
        "options": {"temperature": 0.1, "num_ctx": NUM_CTX, "num_predict": NUM_PREDICT, "seed": SEED},
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


def _apply(text: str, workspace: Path, task: str = "") -> list[str]:
    """모델이 돌려준 블록을 작업공간에 쓴다. 작업공간 밖 경로는 거부한다.

    두 형식을 받는다. `===FILE:`는 파일 전체, `===EDIT:`는 찾아서 바꾸기다.
    찾아서 바꾸기는 SEARCH가 정확히 한 번 나올 때만 적용한다. 0번이면 모델이 원문을
    잘못 옮긴 것이고, 2번 이상이면 어디를 바꿀지 모호하다. 둘 다 추측하지 않고 실패로 끝낸다.
    `task` 에 이름이 없는 함수·클래스를 지우거나 문법이 깨진 .py 는 거부한다(_guard).
    """
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

    for target, (rel, content) in pending.items():
        _guard(rel, target, content, task)
    # 모든 블록이 검증된 뒤에만 쓴다. 중간에 하나라도 실패하면 아무 파일도 바뀌지 않는다.
    for target, (_rel, content) in pending.items():
        # U47-N1: write_text turned every "\n" into "\r\n" on Windows, so an LF file came back CRLF and exact-byte
        # acceptance failed on a correct edit. Keep the line ending the file already uses; a new file gets LF.
        eol = "\r\n" if target.is_file() and b"\r\n" in target.read_bytes() else "\n"
        target.write_bytes(content.replace("\r\n", "\n").replace("\n", eol).encode("utf-8"))
    return written


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
        print(json.dumps(
            {"status": status, "response": response, "usage": usage, "conversation_id": "ollama-local", "error": error},
            ensure_ascii=False,
        ))
        return 0 if status == "SUCCESS" else 1

    # 과제가 가리키는 파일의 현재 내용을 함께 준다. 7B 모델은 파일을 스스로 찾지 못한다.
    named = context_files(args.prompt, workspace)
    context = "".join(
        f"\n===CURRENT FILE: {name}===\n{(workspace / name).read_text(encoding='utf-8')}\n"
        for name in named[:4]
    )

    # 대상 파일 중 하나라도 길면 찾아서 바꾸기 형식을 요구한다. 짧은 파일은 전체 재작성이
    # 더 안정적이다(벤치 6과제 모두 전체 재작성으로 통과).
    longest = max((len((workspace / name).read_text(encoding="utf-8").splitlines()) for name in named[:4]), default=0)
    rules = EDIT_RULES if longest >= EDIT_MODE_MIN_LINES else FORMAT_RULES
    prompt = f"{rules}\n\nTASK:\n{args.prompt}\n\nCURRENT CONTENTS:{context}\n\nNow output the blocks."
    # 문맥을 넘는 프롬프트는 모델을 부르지 않고 바로 실패시킨다. 잘린 입력으로 600초를 기다린 뒤 실패하던 것을
    # 즉시 실패로 바꿔 cascade 가 곧바로 agy 로 넘긴다. 한국어가 1글자 3바이트·약 1토큰이라 바이트/3 으로 어림한다.
    estimated = len(prompt.encode("utf-8")) // 3
    limit = NUM_CTX - NUM_PREDICT
    # U47-O2: every row names the model and the work, so the ledger can be joined to pilot outcomes and distilled.
    run = {"model": args.model, "work_id": contract_work_id(args.prompt)}
    if estimated > limit:
        _log("pilot_local", status="PROMPT_TOO_LARGE", elapsed_s=0.0, estimated_tokens=estimated, **run)
        return envelope("ERROR", "", {"input_tokens": 0, "output_tokens": 0}, f"PROMPT_TOO_LARGE: ~{estimated} tokens > {limit}")
    from v7_harness.adapters.gpu_priority import pilot_holds

    started = time.monotonic()
    try:
        with pilot_holds(timeout_s):  # 파일럿이 GPU 를 먼저 쓴다(B74). 보조 호출은 이 동안 양보한다
            text, usage = _generate(args.model, prompt, timeout_s)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        _log("pilot_local", status="ERROR", elapsed_s=round(time.monotonic() - started, 1), **run)
        return envelope("ERROR", "", {"input_tokens": 0, "output_tokens": 0}, f"ollama unreachable: {exc}")
    _log("pilot_local", status="GENERATED", elapsed_s=round(time.monotonic() - started, 1), **run, **usage)

    if "===FILE:" not in text and "===EDIT:" not in text:
        return envelope("ERROR", "", usage, "model returned no file block")
    try:
        written = _apply(text, workspace, task=args.prompt)
    except ValueError as exc:
        return envelope("ERROR", "", usage, str(exc))
    if not written:
        return envelope("ERROR", "", usage, "no file written")
    return envelope("SUCCESS", f"wrote: {', '.join(written)}", usage)


if __name__ == "__main__":
    sys.exit(main())
