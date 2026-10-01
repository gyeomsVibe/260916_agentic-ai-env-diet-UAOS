"""olla — 세 도구가 어느 프로젝트에서든 로컬 Ollama 모델을 부려 쓰는 공용 명령.

설계 근거(`ollama/01_작동원리와_운영_Ollama는_어떻게_돌아가나.md` §10, `shared/global-rules/REFERENCES.md`):
- FrugalGPT(arXiv:2305.05176)·RouteLLM(ICLR 2025): 싼 모델을 먼저 쓰고 부족할 때만 비싼 모델로
  올리면 비용을 크게 줄이면서 품질을 지킬 수 있다(캐스케이드).
- GitHub의 Ollama 위임 도구들(claude-sidekick, mcp-local-llm 등)의 공통 분업:
  "생각은 비싼 모델이, 기계적인 일은 로컬 모델이".
- 이 프로젝트 벤치: 로컬 모델의 유일한 실패 축은 지시의 모호함이었다.

그래서 이 명령은 **파일럿 밖**에서도 쓰이지만, 파일럿이 해 주던 안전장치 중 핵심 셋을 스스로 한다.
1. 편집 전 백업(`.work/backup_olla_<시각>/`), 2. 편집 결과를 diff로 보여 줌,
3. 판정은 하지 않는다 — 부른 도구가 테스트로 확인한다.

명령:
  olla status                         서버·모델 상태
  olla ask "질문" [-f 파일 ...]        초안·요약·설명·분류 같은 한 번짜리 답
  olla edit -f 파일 ... "지시"         파일을 고치고 diff 출력(백업 후), --dry-run 이면 diff만
  olla find "질문" [-d 폴더]           폴더 안 텍스트 파일을 의미로 검색(임베딩)
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from v7_harness.adapters import ollama_worker as worker

HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
CHAT_MODEL = os.environ.get("OLLA_MODEL", worker.DEFAULT_MODEL)
EMBED_MODEL = os.environ.get("OLLA_EMBED_MODEL", "qwen3-embedding:0.6b")
TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".toml", ".yml", ".yaml", ".ps1", ".sh", ".js", ".ts"}
MAX_FILE_CHARS = 200_000


OUTLINE_MAX_LINES = 60  # U108: enough to place every def of a 1,300-line module; keeps a deny short


def _post(path: str, payload: dict, timeout: int = 900) -> dict:
    request = urllib.request.Request(
        f"{HOST}{path}", data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _get(path: str, timeout: int = 10) -> dict:
    with urllib.request.urlopen(f"{HOST}{path}", timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


# "실제 세션에서 얼마를 아꼈나"는 기록이 없으면 영원히 UNMEASURED 다. 호출·알림을 한 줄씩 남긴다.
# 여러 도구가 동시에 쓰므로 조율 스트림과 같은 파일 잠금을 쓴다(Windows 동시 append 는 줄을 잃는다).
USAGE_LOG = Path(os.environ.get("OLLA_USAGE", Path.home() / ".cache" / "olla" / "usage.jsonl"))


def _caller() -> str:
    names = os.environ.keys()
    if any(n.upper().startswith(("ANTIGRAVITY", "GEMINI_CLI")) for n in names):
        return "antigravity"
    if "CLAUDECODE" in names:
        return "claude"
    if any(n.upper().startswith("CODEX_") for n in names):
        return "codex"
    return "unknown"


def log_usage(event: str, **fields) -> None:
    """최선 노력 기록. 실패해도 명령·훅은 그대로 진행한다."""
    from v7_harness.coord.stream import _exclusive

    # 세션별로 "올라마를 제대로 썼나"를 재려면 세션 번호가 필요하다(Biz항해 세션 분석은 기록을 시간으로만 가를 수 있었다).
    session = fields.pop("session", None) or os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("CODEX_SESSION_ID") or ""
    caller = fields.pop("caller", None) or _caller()
    record = {"ts": datetime.now().isoformat(timespec="seconds"), "event": event, "caller": caller,
              **({"session": session} if session else {}), **fields}
    try:
        USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _exclusive(USAGE_LOG.with_suffix(".lock")):
            with USAGE_LOG.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 — 기록 실패가 작업을 막으면 안 된다
        pass


def _stdin_text() -> str:
    """훅 입력은 UTF-8 JSON 이다. Windows 기본(cp949)으로 읽으면 한글 경로가 깨져 파일을 못 찾고
    훅이 조용히 침묵했다(Biz항해 세션, 2026-09-22: 큰 파일 통째 읽기 2건에 알림 0건)."""
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is None:
        return sys.stdin.read()
    return buffer.read().decode("utf-8", errors="replace")


def _read_files(paths: list[str]) -> str:
    chunks = []
    for raw in paths:
        path = Path(raw)
        if not path.is_file():
            raise FileNotFoundError(raw)
        text = path.read_text(encoding="utf-8", errors="replace")[:MAX_FILE_CHARS]
        chunks.append(f"\n===CURRENT FILE: {raw.replace(os.sep, '/')}===\n{text}\n")
    return "".join(chunks)


def cmd_status(_: argparse.Namespace) -> int:
    try:
        tags = _get("/api/tags")
        loaded = _get("/api/ps")
    except (urllib.error.URLError, OSError) as exc:
        print(json.dumps({"ok": False, "error": f"ollama unreachable: {exc}", "host": HOST}, ensure_ascii=False))
        return 1
    print(json.dumps({
        "ok": True,
        "host": HOST,
        "chat_model": CHAT_MODEL,
        "embed_model": EMBED_MODEL,
        "installed": [m.get("name") for m in tags.get("models", [])],
        "loaded": [{"name": m.get("name"), "vram_gb": round((m.get("size_vram") or 0) / 1e9, 2)} for m in loaded.get("models", [])],
    }, ensure_ascii=False))
    return 0


# 7b 모델은 영어 지시문 속 "in Korean" 한 마디를 무시했다(1/1 영어). 한국어로 규칙·예시를 주면
# 3/3 한국어였다(2026-09-22 실측). 그래서 --ko 는 지시 자체를 한국어로 감싸고, 결과를 검사해 한 번 더 시킨다.
KO_RULES = (
    "반드시 한국어(한글)로만 답하라. 전문 용어는 한국어로 쓰고 필요하면 영어를 괄호로 병기한다(예: 캐시(cache)).\n"
    "요청한 결과만 쓰고 머리말·설명·따옴표를 붙이지 마라.\n\n"
)
KO_MIN_HANGUL_RATIO = 0.3  # 글자(공백·기호 제외) 중 한글 비율. 코드명·영어 병기를 허용하는 하한


def hangul_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    return sum(1 for c in letters if "가" <= c <= "힣") / len(letters) if letters else 0.0


REF_TEST_RE = re.compile(r"\btests\.(test_[A-Za-z0-9_]+)")
REF_PATH_RE = re.compile(r"`([\w./\\-]+\.(?:py|md|json|jsonl|ps1|toml|ya?ml|js|ts))`")


def missing_refs(text: str, root: Path) -> list[str]:
    """답에 나온 테스트 모듈·파일 경로 중 실제로 없는 것. 로컬 모델은 그럴듯한 이름을 지어낸다
    (실측 B71: 정상 입력에서도 테스트 이름 8/12개가 가짜)."""
    missing = [f"tests.{name}" for name in REF_TEST_RE.findall(text) if not (root / "tests" / f"{name}.py").is_file()]
    for raw in REF_PATH_RE.findall(text):
        candidate = Path(raw).expanduser()
        if not (candidate if candidate.is_absolute() else root / candidate).exists() and "~" not in raw:
            missing.append(raw)
    return sorted(set(missing))


GPU_BUSY_EXIT = 6


def _pilot_has_gpu() -> bool:
    """파일럿 로컬 작업자가 GPU 를 쓰는 중이면 보조 호출은 양보한다(B74)."""
    from v7_harness.adapters.gpu_priority import BUSY_MESSAGE, pilot_active

    if pilot_active():
        print(BUSY_MESSAGE, file=sys.stderr)
        log_usage("yield_to_pilot")
        return True
    return False


def cmd_ask(args: argparse.Namespace) -> int:
    # 빈 입력 파일을 주면 모델은 없는 내용을 지어낸다(실측: 0바이트 입력에 무관한 점검표 12항목).
    # 그럴듯한 가짜보다 실패가 낫다.
    empty = [raw for raw in args.file if Path(raw).is_file() and not Path(raw).read_text(encoding="utf-8", errors="replace").strip()]
    if empty:
        print(f"empty input file (the model would invent content): {', '.join(empty)}", file=sys.stderr)
        return 2
    context = _read_files(args.file) if args.file else ""
    prompt = f"{args.prompt}\n{context}" if context else args.prompt
    if args.ko:
        prompt = KO_RULES + prompt
    usage_total = {"input_tokens": 0, "output_tokens": 0}
    attempts = 2 if args.ko else 1
    text = ""
    for attempt in range(attempts):
        try:
            text, usage = worker._generate(args.model, prompt, args.timeout)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"ollama unreachable: {exc}", file=sys.stderr)
            return 1
        for key in usage_total:
            usage_total[key] += usage.get(key, 0)
        if not args.ko or hangul_ratio(text) >= KO_MIN_HANGUL_RATIO:
            break
        prompt = "직전 답이 한국어가 아니었다. 같은 요청을 한국어로만 다시 답하라.\n\n" + prompt
    print(text.strip())
    report = {"model": args.model, **usage_total}
    if args.ko:
        report["hangul_ratio"] = round(hangul_ratio(text), 2)
        report["attempts"] = attempt + 1
    print(json.dumps(report, ensure_ascii=False), file=sys.stderr)
    log_usage("ask", ko=args.ko, attempts=attempt + 1, **usage_total)
    if args.ko and hangul_ratio(text) < KO_MIN_HANGUL_RATIO:
        print("local answer is not Korean after retry — write it yourself", file=sys.stderr)
        return 4
    # 기본으로 켠다: 지어낸 이름을 부른 도구가 그대로 쓰는 것이 가장 비싼 실패다.
    fake = missing_refs(text, Path.cwd())
    if fake:
        print(f"references not found (likely invented): {', '.join(fake)}", file=sys.stderr)
        log_usage("ask_invented_refs", count=len(fake))
        return 5
    return 0


def _backup(files: list[Path], root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    dest = root / ".work" / f"backup_olla_{stamp}"
    for path in files:
        target = dest / path.resolve().relative_to(root.resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    return dest


def cmd_edit(args: argparse.Namespace) -> int:
    root = Path.cwd()
    files = [Path(f) for f in args.file]
    for path in files:
        if not path.is_file():
            print(f"no such file: {path}", file=sys.stderr)
            return 2
        if not str(path.resolve()).startswith(str(root.resolve())):
            # 부른 도구의 작업 폴더 밖은 고치지 않는다. 다른 프로젝트를 건드리는 사고를 막는다.
            print(f"outside the current project: {path}", file=sys.stderr)
            return 2

    before = {p: p.read_text(encoding="utf-8") for p in files}
    longest = max(len(text.splitlines()) for text in before.values())
    rules = worker.EDIT_RULES if longest >= worker.EDIT_MODE_MIN_LINES else worker.FORMAT_RULES
    names = " ".join(f"`{p.as_posix()}`" for p in files)
    prompt = f"{rules}\n\nTASK:\n{args.instruction}\nFiles: {names}\n\nCURRENT CONTENTS:{_read_files(args.file)}\n\nNow output the blocks."
    try:
        text, usage = worker._generate(args.model, prompt, args.timeout)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"ollama unreachable: {exc}", file=sys.stderr)
        return 1

    # 먼저 임시 사본에 적용해 본다. 실패하면 원본은 건드리지 않는다.
    scratch = root / ".work" / f"olla_scratch_{os.getpid()}"
    if scratch.exists():
        shutil.rmtree(scratch)
    for path in files:
        target = scratch / path.resolve().relative_to(root.resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(before[path], encoding="utf-8")
    try:
        written = worker._apply(text, scratch)
    except ValueError as exc:
        shutil.rmtree(scratch, ignore_errors=True)
        print(f"model output rejected: {exc}", file=sys.stderr)
        return 3
    if not written:
        shutil.rmtree(scratch, ignore_errors=True)
        print("model changed nothing", file=sys.stderr)
        return 3

    diffs = []
    after: dict[Path, str] = {}
    for path in files:
        new_text = (scratch / path.resolve().relative_to(root.resolve())).read_text(encoding="utf-8")
        after[path] = new_text
        diffs.extend(difflib.unified_diff(
            before[path].splitlines(keepends=True), new_text.splitlines(keepends=True),
            fromfile=f"a/{path.as_posix()}", tofile=f"b/{path.as_posix()}",
        ))
    shutil.rmtree(scratch, ignore_errors=True)
    sys.stdout.write("".join(diffs) or "(no textual change)\n")

    if args.dry_run:
        print(json.dumps({"applied": False, "dry_run": True, **usage}, ensure_ascii=False), file=sys.stderr)
        return 0
    backup = _backup(files, root)
    for path, new_text in after.items():
        path.write_text(new_text, encoding="utf-8")
    print(json.dumps({"applied": True, "backup": str(backup), **usage}, ensure_ascii=False), file=sys.stderr)
    log_usage("edit", files=len(files), **usage)
    return 0


def _embed(texts: list[str]) -> list[list[float]]:
    body = _post("/api/embed", {"model": EMBED_MODEL, "input": texts})
    return body.get("embeddings") or []


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def cmd_find(args: argparse.Namespace) -> int:
    base = Path(args.dir)
    skip = {".git", ".work", "__pycache__", "node_modules", ".venv"}
    candidates: list[tuple[Path, str]] = []
    for path in base.rglob("*"):
        if any(part in skip for part in path.parts) or not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")[:2000]
        if text.strip():
            candidates.append((path, text))
        if len(candidates) >= args.limit:
            break
    if not candidates:
        print("no text files", file=sys.stderr)
        return 1
    try:
        vectors = _embed([args.query] + [text for _, text in candidates])
    except (urllib.error.URLError, OSError) as exc:
        print(f"ollama unreachable: {exc}", file=sys.stderr)
        return 1
    query, docs = vectors[0], vectors[1:]
    ranked = sorted(zip(candidates, docs), key=lambda item: _cosine(query, item[1]), reverse=True)
    for (path, _), vector in ranked[: args.top]:
        print(f"{_cosine(query, vector):.3f}  {path.as_posix()}")
    return 0


# --- 토큰 0 활용: 추정·요약본·경로 결정 -------------------------------------------------
#
# 로컬 모델의 토큰은 0이다. 그러므로 비싼 모델이 무언가를 "읽기 전에" 로컬이 먼저 읽고 줄이는
# 것이 가장 큰 절감이다(LLMLingua, EMNLP 2023: 작은 모델로 입력 최대 20배 압축, 손실 적음).
# 에이전트는 매 턴 문맥을 다시 보내므로 한 번 읽은 큰 파일은 여러 번 과금된다.

# UTF-8 바이트 ÷ 이 값 ≈ 토큰. 한국어·영어·코드가 섞인 이 저장소에서 보수적으로 잡은 값이다
# (tiktoken 같은 토크나이저 없이 O(1)로 추정; 영어 위주면 실제보다 많게, 한국어 위주면 적게 나온다).
BYTES_PER_TOKEN = 3.0
# 이만큼 넘는 읽기는 먼저 로컬 요약본을 만든다. 요약본(약 40줄) 자체가 수백 토큰이므로
# 이보다 작은 파일은 요약하는 편이 오히려 손해다.
DIGEST_MIN_TOKENS = 3000
# 에이전트는 읽은 내용을 이후 턴마다 다시 보낸다. 몇 턴 더 이어진다고 볼지.
REREAD_TURNS = 3
CHUNK_LINES = 300  # U17 실측: 300줄 8/8 적중(구간 19~42줄), 150줄 7/8 — .coord/runs/U17/bench_digest*.json

LOCAL_KINDS = {
    "summarize": ("요약", "정리", "설명", "summar", "explain", "overview", "describe"),
    "classify": ("분류", "판별", "태그", "classif", "categor", "label"),
    "draft": ("초안", "작성", "문서", "docstring", "주석", "draft", "boilerplate", "readme", "changelog", "commit message"),
    "find": ("찾", "어디", "검색", "find", "where", "locate", "search"),
}


def estimate_tokens(paths: list[str], prompt: str = "") -> dict:
    """비싼 모델이 이 파일들을 읽을 때 드는 토큰을 추정한다."""
    per_file = []
    total_bytes = len(prompt.encode("utf-8"))
    for raw in paths:
        path = Path(raw)
        size = path.stat().st_size if path.is_file() else 0
        total_bytes += size
        per_file.append({"file": raw.replace(os.sep, "/"), "tokens": round(size / BYTES_PER_TOKEN)})
    once = round(total_bytes / BYTES_PER_TOKEN)
    return {"read_once": once, "with_rereads": once * (1 + REREAD_TURNS), "files": per_file}


def _kind(task: str) -> str:
    lowered = task.lower()
    for kind, words in LOCAL_KINDS.items():
        if any(word in lowered for word in words):
            return kind
    return "other"


def decide_route(task: str, paths: list[str]) -> dict:
    """사용자 지시 없이 도구가 스스로 정하는 경로.

    - local-digest-then-self: 읽을 양이 크면 로컬이 먼저 요약본을 만들고, 비싼 모델은 그것만 읽는다.
    - local-edit: 수정 지시가 구체적이면(worker_advice 60점 이상) 로컬이 고친다.
    - local-answer: 요약·분류·초안·찾기는 로컬이 답하고 비싼 모델은 검토만 한다.
    - self: 판단이 필요하고 읽을 양도 작으면 비싼 모델이 직접.
    """
    from v7_harness.adapters.worker_advice import advise

    cost = estimate_tokens(paths, task)
    kind = _kind(task)
    advice = advise(task)
    edit_like = any(w in task.lower() for w in ("change", "rename", "replace", "add", "remove", "fix", "바꿔", "변경", "추가", "삭제", "수정", "교체"))

    if cost["read_once"] >= DIGEST_MIN_TOKENS and kind in ("summarize", "find", "other"):
        route = "local-digest-then-self"
        why = f"읽기 약 {cost['read_once']:,}토큰(재전송 포함 {cost['with_rereads']:,}) — 로컬 요약본을 먼저 읽는다"
    elif edit_like and advice.worker == "local":
        route = "local-edit"
        why = f"수정 지시 구체성 {advice.specificity}/100 — 로컬이 고치고 결과만 검증한다"
    elif kind in ("summarize", "classify", "draft", "find"):
        route = "local-answer"
        why = f"{kind} 과제 — 로컬이 답하고 검토만 한다"
    else:
        route = "self"
        why = f"판단이 필요한 과제(구체성 {advice.specificity}/100)이고 읽을 양이 작다"
    saved = cost["with_rereads"] if route != "self" else 0
    return {"route": route, "reason": why, "kind": kind, "estimated_paid_tokens": cost, "tokens_saved_estimate": saved}


def _digest_chunks(text: str) -> list[tuple[int, int, str]]:
    lines = text.splitlines()
    return [
        (start + 1, min(start + CHUNK_LINES, len(lines)), "\n".join(lines[start:start + CHUNK_LINES]))
        for start in range(0, max(len(lines), 1), CHUNK_LINES)
    ]


def digest_file(path: Path, focus: str, model: str, timeout: int) -> tuple[str, dict]:
    """줄 번호가 달린 요약본. 비싼 모델은 이걸 보고 필요한 구간만 연다."""
    text = path.read_text(encoding="utf-8", errors="replace")
    parts: list[str] = []
    usage_total = {"input_tokens": 0, "output_tokens": 0}
    outline = code_outline(path)
    exact = f"## exact outline (from the parser)\n{outline}\n## local model notes\n" if outline else ""
    for first, last, chunk in _digest_chunks(text):
        numbered = "\n".join(f"{first + i}: {line}" for i, line in enumerate(chunk.splitlines()))
        prompt = (
            "Summarize this part of a file for another engineer who will decide which lines to open.\n"
            "Output at most 8 bullet lines. Each bullet: `L<start>-<end>: <what is there>`.\n"
            "Name functions, classes, constants, and anything related to the focus. No prose outside bullets.\n"
            f"Focus: {focus or 'general structure'}\n\n{numbered}"
        )
        answer, usage = worker._generate(model, prompt, timeout)
        usage_total["input_tokens"] += usage.get("input_tokens", 0)
        usage_total["output_tokens"] += usage.get("output_tokens", 0)
        parts.append(answer.strip())
    header = f"# digest: {path.as_posix()} ({len(text.splitlines())} lines)"
    return header + "\n" + exact + "\n".join(parts) + "\n", usage_total


# 같은 파일·같은 질문을 세 도구가 따로 요약하면 로컬 몇 분이 매번 다시 든다(U17 실측 파일당 약 1분).
# 내용 해시로 묶으므로 파일이 바뀌면 자동으로 무효가 되고, 프로젝트를 가리지 않는다.
DIGEST_CACHE_DIR = Path(os.environ.get("OLLA_CACHE", Path.home() / ".cache" / "olla" / "digest"))
DIGEST_PROMPT_VERSION = "2"  # U108: digests now start with the exact code outline


def _digest_cache_path(path: Path, focus: str, model: str) -> Path:
    key = hashlib.sha256()
    for part in (DIGEST_PROMPT_VERSION, str(CHUNK_LINES), model, focus):
        key.update(f"{len(part)}:{part}".encode("utf-8"))  # 길이 접두로 경계를 모호하지 않게
    key.update(path.read_bytes())
    return DIGEST_CACHE_DIR / f"{key.hexdigest()}.json"


def cmd_estimate(args: argparse.Namespace) -> int:
    print(json.dumps(estimate_tokens(args.file, args.prompt or ""), ensure_ascii=False))
    return 0


def cmd_route(args: argparse.Namespace) -> int:
    print(json.dumps(decide_route(args.task, args.file), ensure_ascii=False))
    return 0


def cmd_digest(args: argparse.Namespace) -> int:
    for raw in args.file:
        path = Path(raw)
        if not path.is_file():
            print(f"no such file: {raw}", file=sys.stderr)
            return 2
        cache = _digest_cache_path(path, args.focus or "", args.model)
        cached = not args.no_cache and cache.is_file()
        if cached:
            saved = json.loads(cache.read_text(encoding="utf-8"))
            digest, usage = saved["digest"].replace(saved["path"], path.as_posix(), 1), {"input_tokens": 0, "output_tokens": 0}
        else:
            if _pilot_has_gpu():
                return GPU_BUSY_EXIT
            try:
                digest, usage = digest_file(path, args.focus or "", args.model, args.timeout)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                print(f"ollama unreachable: {exc}", file=sys.stderr)
                return 1
            try:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps({"path": path.as_posix(), "digest": digest}, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass  # 캐시는 편의일 뿐, 못 써도 요약본은 낸다
        before = round(path.stat().st_size / BYTES_PER_TOKEN)
        after = round(len(digest.encode("utf-8")) / BYTES_PER_TOKEN)
        sys.stdout.write(digest)
        print(json.dumps({
            "file": path.as_posix(),
            "paid_tokens_if_read": before,
            "paid_tokens_digest": after,
            "saved_pct": round((1 - after / before) * 100, 1) if before else 0.0,
            "local_tokens": usage,
            "cached": cached,
        }, ensure_ascii=False), file=sys.stderr)
        log_usage("digest", file=str(path.resolve()), paid_tokens_if_read=before, paid_tokens_digest=after, cached=cached)
    return 0


# 문서만 두면 규칙 준수가 25~40%, 훅으로 걸면 약 95%(agents.md 가이드 인용, REFERENCES.md §4).
# 그래서 "큰 파일은 요약본 먼저"를 Read 직전에 상기시킨다. 막지는 않는다 — 판단은 비싼 모델 몫이다.
def read_hint(event: dict) -> str | None:
    tool_input = event.get("tool_input") or {}
    if tool_input.get("offset") or tool_input.get("limit"):
        return None  # 이미 필요한 줄만 여는 중
    raw = tool_input.get("file_path") or ""
    path = Path(raw)
    try:
        if not raw or not path.is_file():
            return None
        tokens = round(path.stat().st_size / BYTES_PER_TOKEN)
    except OSError:
        return None
    if tokens < DIGEST_MIN_TOKENS or path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".ipynb"}:
        return None
    # 알림만으로는 안 썼다(Biz항해 세션: 알림 도착 후에도 olla 0건). 그래서 로컬이 먼저 일한다:
    # 요약본이 캐시에 있으면 그 자리에서 건네고, 없으면 뒤에서 만들어 두어 다음 읽기부터 쓰게 한다.
    try:
        cached = _digest_cache_path(path, "", CHAT_MODEL)
    except OSError:
        return None
    if cached.is_file():
        try:
            digest = json.loads(cached.read_text(encoding="utf-8"))["digest"]
        except (OSError, ValueError, KeyError):
            digest = ""
        if digest:
            return (f"olla digest of {path.name} (~{tokens:,} tokens, cached, 0 paid tokens). "
                    f"Read only the lines you need with offset/limit:\n{digest[:DIGEST_INLINE_MAX]}")
    started = _prewarm_digest(path, cached)
    return (
        f"olla: {path.name} is about {tokens:,} tokens. "
        + ("A line-numbered digest is being built in the background for next time. " if started else "")
        + "If you only need to locate something, use Grep or Read with offset/limit instead of the whole file."
    )


DIGEST_INLINE_MAX = 2400  # 약 800토큰. 요약본 실측 420~900토큰이므로 대부분 통째로 들어간다
PREWARM_RETRY_S = 900  # 뒤에서 만드는 중이면 15분 안에는 다시 띄우지 않는다


def _prewarm_digest(path: Path, cached: Path) -> bool:
    """요약본을 뒤에서 만든다. 서버가 꺼졌거나 이미 만드는 중이면 하지 않는다."""
    import subprocess

    marker = cached.with_suffix(".pending")
    try:
        if marker.is_file() and time.time() - marker.stat().st_mtime < PREWARM_RETRY_S:
            return False
        from v7_harness.adapters.gpu_priority import pilot_active

        if not _server_up() or pilot_active():  # 파일럿이 GPU 를 쓰는 중이면 예열하지 않는다
            return False
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(path), encoding="utf-8")
        # 낮은 우선순위: 뒤에서 도는 요약이 사용자 작업을 늦추면 안 된다(요약 중 전체 회귀의 30초 예산 테스트가 30.6초로 넘침).
        flags = (getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                 | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0))
        subprocess.Popen([sys.executable, "-m", "v7_harness.olla", "digest", "-f", str(path)],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         cwd=str(Path(__file__).resolve().parents[1]), creationflags=flags, close_fds=True)
        log_usage("digest_prewarm", file=str(path.resolve()))
        return True
    except OSError:
        return False


# 알림(11회)과 요약본 인계만으로는 Biz항해 세션이 올라마를 0번 썼다. 아주 큰 파일의 통째 읽기는 막고
# 요약본·줄 범위로 돌린다. 막아도 offset/limit·Grep 으로는 언제든 읽을 수 있으니 작업이 멈추지 않는다.
DENY_WHOLE_READ_TOKENS = 8000  # 약 24KB. 실측 큰 읽기 11만·1.5만·8천 토큰이 모두 걸리고 3~4천 토큰 문서는 통과


def whole_read_tokens(event: dict) -> int:
    tool_input = event.get("tool_input") or {}
    if tool_input.get("offset") or tool_input.get("limit"):
        return 0
    try:
        path = Path(tool_input.get("file_path") or "")
        return round(path.stat().st_size / BYTES_PER_TOKEN) if path.is_file() else 0
    except OSError:
        return 0


def cmd_hook_read(args: argparse.Namespace) -> int:
    """Claude Code PreToolUse(Read) 훅. 큰 파일은 알리고, 아주 큰 파일의 통째 읽기만 거부한다."""
    try:
        event = json.loads(_stdin_text() or "{}")
        hint = read_hint(event)
        tokens = whole_read_tokens(event)
    except (ValueError, AttributeError):
        return 0
    if not hint:
        return 0
    file = str(Path((event.get("tool_input") or {}).get("file_path", "")).resolve())
    output: dict = {"hookEventName": "PreToolUse", "additionalContext": hint}
    if tokens >= DENY_WHOLE_READ_TOKENS:
        output = {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": (
            f"Whole-file read of ~{tokens:,} tokens refused (limit {DENY_WHOLE_READ_TOKENS:,}). "
            f"Call the local_read_map tool (0 paid tokens; if deferred, first {LOAD_OLLA}) or Grep to find the lines, "
            f"then Read with offset/limit. {hint}" + _outline_note(Path(file)))}
        log_usage("deny_whole_read", file=file, tokens=tokens)
    else:
        log_usage("hint_read", file=file)
    print(json.dumps({"hookSpecificOutput": output}, ensure_ascii=False))
    return 0


# Codex 는 파일을 셸로 읽는다. 그리고 PreToolUse 의 additionalContext 를 아직 받지 않으므로(공식 hooks 문서)
# 읽은 직후(PostToolUse)에 알린다. 이미 읽은 파일은 늦었지만, 이후 턴 재전송과 다음 읽기를 줄인다.
WHOLE_FILE_READERS = {"cat", "type", "get-content", "gc", "more", "bat"}
SHELL_WRAPPERS = {"powershell", "pwsh", "bash", "sh", "cmd", "zsh"}
RANGE_FLAGS = {"-totalcount", "-head", "-tail", "-first", "-last", "-n", "--lines"}


def shell_read_targets(command: str) -> list[str]:
    """`cat big.py`처럼 파일을 통째로 출력하는 명령의 대상. 파이프·범위 지정은 이미 줄인 것으로 본다."""
    targets: list[str] = []
    for segment in command.replace("&&", ";").replace("||", ";").split(";"):
        if "|" in segment:
            continue
        try:
            words = shlex.split(segment, posix=False)
        except ValueError:
            continue
        # `powershell -NoProfile -Command "Get-Content x"` 같은 감싸기를 벗긴다
        if words and Path(words[0]).stem.lower() in SHELL_WRAPPERS:
            words = words[1:]
            while words and words[0][:1] in "-/":
                words = words[1:]
            if len(words) == 1 and " " in words[0]:
                targets.extend(shell_read_targets(words[0].strip("'\"")))
                continue
        if not words or words[0].lower() not in WHOLE_FILE_READERS:
            continue
        args = words[1:]
        if any(a.lower() in RANGE_FLAGS for a in args):
            continue
        targets.extend(a.strip("'\"") for a in args if not a.startswith("-"))
    return targets


def shell_read_deny(paths: list[Path]) -> str | None:
    """U103-O: the Codex PreToolUse deny line for a whole print of >= DENY_WHOLE_READ_TOKENS, like olla-guard's."""
    tokens = max((whole_read_tokens({"tool_input": {"file_path": str(p)}}) for p in paths), default=0)
    if tokens < DENY_WHOLE_READ_TOKENS:
        return None
    log_usage("deny_whole_read", tokens=tokens)
    big = max(paths, key=lambda p: whole_read_tokens({"tool_input": {"file_path": str(p)}}))
    return json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                       "permissionDecisionReason": f"Whole-file read of ~{tokens:,} tokens refused; run `olla digest "
                       "<file>` or local_read_map (0 paid tokens), then print only the needed lines (`sed -n 'A,Bp'`)."
                       + _outline_note(big)}})


def shell_read_hint(event: dict) -> str | None:
    command = (event.get("tool_input") or {}).get("command") or ""
    if isinstance(command, list):
        # ["powershell", "-Command", "Get-Content x"] 처럼 셸이 감싼 형태면 실제 명령만 꺼낸다
        parts = [str(part) for part in command]
        if parts and Path(parts[0]).stem.lower() in SHELL_WRAPPERS:
            parts = [part for part in parts[1:] if part[:1] not in "-/"]
        command = " ".join(parts)
    base = Path(event.get("cwd") or ".")
    paths = [Path(raw) if Path(raw).is_absolute() else base / raw for raw in shell_read_targets(str(command))]
    if event.get("hook_event_name") == "PreToolUse":
        return shell_read_deny(paths)
    for path in paths:
        hint = read_hint({"tool_input": {"file_path": str(path)}})
        if hint:
            return hint.replace("then Read with offset/limit.", "then print only those lines (e.g. `sed -n 'A,Bp'`).")
    return None


def cmd_hook_shell(args: argparse.Namespace) -> int:
    """Codex PostToolUse(Bash) 훅. 어떤 입력에도 0으로 끝나 도구를 막지 않는다."""
    try:
        event = json.loads(_stdin_text() or "{}")
        hint = shell_read_hint(event) if isinstance(event, dict) else None
    except (ValueError, AttributeError, TypeError):
        return 0
    if hint and event.get("hook_event_name") == "PreToolUse":
        print(hint)  # U103-O: already the whole PreToolUse deny
    elif hint:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": hint}}, ensure_ascii=False))
        log_usage("hint_shell")
    return 0


# 규칙이 문맥에 있어도 계획 단계에서 로컬 모델을 빠뜨렸다(2026-09-22, 사용자가 먼저 물어서야 드러남).
# 그래서 지시가 들어오는 순간(UserPromptSubmit) 분업을 먼저 정하게 한 줄을 넣는다. 서버가 꺼져 있으면 말하지 않는다.
# 지연(deferred) MCP 도구는 이 줄 없이는 부를 수 없다(Biz dec0f758: WebSearch 는 불러 쓰고 olla 는 0회).
LOAD_OLLA = "ToolSearch `select:mcp__olla__local_read_map,mcp__olla__local_draft,mcp__olla__local_search`"
PLAN_HINT = (
    f"Local model (0 paid tokens) is up; use its MCP tools (if deferred, load them once: {LOAD_OLLA}; "
    "if absent, `olla` in the shell, "
    "e.g. `olla digest -f <file>`). Before acting, split this task: "
    "understanding/locating in a file over ~300 lines -> `local_read_map`, drafts/summaries/commit messages -> "
    "`local_draft` (English prompt with format+example; korean=true only for user-facing text), "
    "search by meaning -> `local_search`. "
    "Do the rest yourself; verify local output, never let it judge. "
    "Report: no text between tool calls; end in Korean with `**결과**:` / `- 근거:` / "
    "`- **남은 일**:` only if the user must act."
)
# 출력 규칙은 시스템 규칙 파일에 있어도 매 턴 어겼다(실측: Claude 턴당 진행 설명 0~9개, Codex 2~33개).
# 생성 직전에 다시 보이는 이 줄이 가장 가깝다. 지켰는지는 Stop 훅(hook-stop)이 기록해 `olla stats`로 본다.


def turn_shape(transcript: Path) -> dict | None:
    """마지막 사용자 지시 이후 어시스턴트 글 덩어리 수와 최종 보고 길이. Claude·Codex·Antigravity 기록 형식 모두."""
    texts: list[str] | None = None
    for line in transcript.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        kind, message, payload = row.get("type"), row.get("message") or {}, row.get("payload") or {}
        source = row.get("source")
        content = message.get("content")
        if kind == "user" and not row.get("isMeta"):
            if isinstance(content, str) or (isinstance(content, list) and not any(
                    isinstance(b, dict) and b.get("type") == "tool_result" for b in content)):
                texts = []
        elif kind == "USER_INPUT" or source == "USER_EXPLICIT":
            texts = []
        elif kind == "event_msg" and payload.get("type") == "task_started":
            texts = []
        elif texts is not None and kind == "assistant" and isinstance(content, list):
            texts += [b["text"] for b in content if isinstance(b, dict) and b.get("type") == "text" and b.get("text", "").strip()]
        elif texts is not None and kind == "response_item" and payload.get("type") == "message" and payload.get("role") == "assistant":
            text = "".join(c.get("text", "") for c in payload.get("content", []) if isinstance(c, dict))
            if text.strip():
                texts.append(text)
        elif texts is not None and kind == "PLANNER_RESPONSE" and source == "MODEL":
            c = row.get("content")
            if isinstance(c, str) and c.strip():
                texts.append(c)
    if not texts:
        return None
    final = [l for l in texts[-1].splitlines() if l.strip()]
    nested = sum(1 for l in final if l.startswith((" ", chr(9))) and l.strip()[:1] in "-*0123456789")
    return {"narration_blocks": len(texts) - 1, "final_lines": len(final), "final_chars": len(texts[-1]), "nested_lines": nested}


def cmd_hook_stop(args: argparse.Namespace) -> int:
    """Stop 훅: 이번 턴의 출력 모양을 기록하고, 문맥이 크면 인계문을 뒤에서 만든다. 막지 않는다."""
    try:
        event = json.loads(_stdin_text() or "{}")
        path = Path(event.get("transcript_path") or "") if isinstance(event, dict) else Path()
        shape = turn_shape(path) if path.is_file() else None
    except (ValueError, OSError, AttributeError):
        return 0
    # 인계문을 지시(hook-plan) 때만 만들면 한 지시로 오래 도는 세션은 놓친다: Biz 40375870 은 지시 1번에
    # 165호출·188k 까지 자랐지만 인계문 0건(2026-09-23 00:25). 턴이 끝날 때도 재서 만든다(30분 제한은 그대로).
    cwd = str(event.get("cwd") or "") if isinstance(event, dict) else ""
    if cwd and context_size(str(path)) >= CONTEXT_WARN_TOKENS:
        session = os.environ.get("CLAUDE_CODE_SESSION_ID") or str(event.get("session_id") or "")
        _start_handoff(str(path), cwd, session)
    if not shape:
        return 0
    # 막아서 다시 쓰게 하지 않는다: 긴 보고가 이미 화면에 나간 뒤라 사용자는 같은 보고를 두 번 본다
    # (2026-09-22 Biz 화면 캡처). 기록만 하고, 다음 지시 때 hook-plan 이 직전 보고의 수치를 되비춘다.
    log_usage("turn_shape", **shape)
    return 0


REPORT_MAX_LINES = 5  # 결과 1 + 과정 1 + 근거 1~2 + 남은 일 1
# 줄 수만 세면 한 줄에 몰아 쓰거나 하위 목록으로 우회했다(Biz항해 세션 보고: 하위 목록 9줄). 글자·중첩도 본다.
REPORT_MAX_CHARS = 600  # 한 줄 약 120자 × 5줄



def _server_up() -> bool:
    try:
        _get("/api/version", timeout=1)
        return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def cmd_hook_plan(args: argparse.Namespace) -> int:
    """Claude Code·Codex 공통 UserPromptSubmit 훅. 어떤 입력에도 0으로 끝나 막지 않는다."""
    try:
        event = json.loads(_stdin_text() or "{}")
    except ValueError:
        return 0
    if not isinstance(event, dict) or not _server_up():
        return 0
    session = os.environ.get("CLAUDE_CODE_SESSION_ID") or str(event.get("session_id") or "")
    context = (PLAN_HINT + session_scorecard(session)
               + context_size_note(str(event.get("transcript_path") or ""), str(event.get("cwd") or ""), session))
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context}}))
    log_usage("hint_plan")
    return 0


CONTEXT_WARN_TOKENS = 150_000  # Biz 재개 세션 평균 약 17만: 호출마다 이만큼을 다시 읽는다


def _cost_line_given(session: str, bucket: int) -> bool:
    if not USAGE_LOG.is_file():
        return False
    for line in USAGE_LOG.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("event") == "cost_advice" and rec.get("session") == session and rec.get("bucket", -1) >= bucket:
            return True
    return False


def context_size(transcript: str) -> int:
    """마지막 응답의 입력 토큰(새 입력 + 캐시 쓰기 + 캐시 읽기). 기록이 없으면 0."""
    path = Path(transcript)
    if not transcript or not path.is_file():
        return 0
    with path.open("rb") as handle:
        handle.seek(max(0, path.stat().st_size - 400_000))
        tail = handle.read().decode("utf-8", errors="replace").splitlines()
    for raw in reversed(tail):
        try:
            usage = (json.loads(raw).get("message") or {}).get("usage")
        except (ValueError, AttributeError):
            continue
        if usage:
            return sum(usage.get(k, 0) or 0 for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    return 0


def context_size_note(transcript: str, cwd: str = "", session: str = "") -> str:
    """성과 지표는 올라마 호출 수가 아니라 호출당 문맥 크기다. 마지막 응답의 입력 토큰으로 잰다."""
    size = context_size(transcript)
    if not size:
        return ""
    advice = ""
    if size >= CONTEXT_WARN_TOKENS:
        if cwd:
            _start_handoff(transcript, cwd, session)
        # 실측(Biz 23:27): 에이전트는 "새 세션이 싸다"고 말했지만 사용자는 또 이어 열었다. 무엇을 누르고 무엇이 자동인지
        # 알려야 행동이 바뀐다. 그래서 사용자 말로 된 한 줄을 그대로 준다.
        # 매 보고마다 붙이면 보고가 600자를 넘고 같은 말이 반복된다(Biz 캡처: 두 보고 모두 비용 줄).
        # 세션당 10만 토큰 구간마다 한 번만 준다.
        advice = " Every call re-reads it: keep tool output small (ranged reads, --stat, | tail)."
        bucket = size // 100_000
        if session and not _cost_line_given(session, bucket):
            log_usage("cost_advice", bucket=bucket, session=session)
            advice += (" Add this line once, in this turn's report, verbatim: `- 비용: 호출당 약 "
                       f"{size // 1000}k 토큰. 같은 폴더에서 새 대화를 열면 올라마 인계문이 자동으로 들어갑니다.`")
    return f" Context now ~{size // 1000}k tokens per call.{advice}"


# 인계(handoff): Biz 세션은 이어 열기(resume)로 호출마다 약 30만 토큰을 다시 읽었다(2026-09-22 23:03).
# 새 세션이면 수천 토큰이다. 이어 열기를 대신할 인계문을 로컬 모델이 뒤에서 만들고, 같은 폴더에서 새 세션이
# 시작되면 SessionStart 훅이 넣어 준다. 사용자는 새 대화를 열기만 하면 된다.
HANDOFF_DIR = Path.home() / ".cache" / "olla" / "handoff"
HANDOFF_MAX_AGE_S = 24 * 3600  # 하루 지난 인계문은 다른 일일 가능성이 크다
HANDOFF_REFRESH_S = 1800  # 큰 문맥 세션에서 30분마다 새로 쓴다
HANDOFF_MAX_CHARS = 6000  # 약 2천 토큰: 이어 열기 30만 대비 0.7%


def _handoff_path(cwd: str) -> Path:
    # 앱은 대화마다 새 워크트리(<저장소>/.claude/worktrees/<이름>)를 만든다. 실측: 새 Biz 대화가 다른 워크트리에서
    # 시작해 인계문을 못 찾았다(23:54). 워크트리 안이면 저장소 뿌리를 열쇠로 쓴다.
    base = os.path.normcase(os.path.abspath(cwd or "."))
    marker = os.path.normcase(os.path.join(".claude", "worktrees"))
    if marker in base:
        base = base.split(marker)[0].rstrip("\\/")
    key = hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]
    return HANDOFF_DIR / f"{key}.json"


def handoff_facts(transcript: Path) -> dict:
    """세션 기록에서 결정적으로 뽑는다: 사용자 지시, 마지막 보고들, 고친 파일, 커밋. 모델 없이도 인계가 된다."""
    prompts: list[str] = []
    reports: list[str] = []
    files: list[str] = []
    commits: list[str] = []
    for raw in transcript.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        content = (row.get("message") or {}).get("content")
        if row.get("type") == "user" and not row.get("isMeta"):
            text = content if isinstance(content, str) else " ".join(
                b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")
            if text.strip() and not text.lstrip().startswith(("<", "This session", "Caveat:")):  # 훅·시스템 문구 제외
                prompts.append(text.strip()[:400])
        if row.get("type") != "assistant" or not isinstance(content, list):
            continue
        for block in content:
            if block.get("type") == "text" and block.get("text", "").strip():
                reports.append(block["text"].strip()[:700])
            if block.get("type") == "tool_use":
                args = block.get("input") or {}
                if block.get("name") in ("Edit", "Write") and args.get("file_path"):
                    files.append(str(args["file_path"]))
                match = re.search(r"git commit[^\n]*?-m\s+[\"']([^\"'\n]{1,160})", str(args.get("command") or ""))
                if match:
                    commits.append(match.group(1))
    return {"prompts": prompts[-8:], "reports": reports[-4:], "files": list(dict.fromkeys(reversed(files)))[:25],
            "commits": commits[-8:]}


def render_handoff(facts: dict, summary: str) -> str:
    parts = []
    if summary.strip():
        parts += ["## Summary (local model; verify)", summary.strip()]
    # 실측(Biz 인계문 6천 자)에서 지시문이 길어 파일·커밋이 잘렸다. 짧고 확실한 사실을 앞에 둔다.
    files = facts["files"]
    try:  # Biz 경로는 한 줄 230자: 공통 뿌리를 한 번만 적는다
        root = os.path.commonpath(files) if len(files) > 1 else ""
    except ValueError:
        root = ""
    shown = [os.path.relpath(f, root) for f in files] if root else files
    parts += ["## Files edited (newest first)" + (f", under {root}" if root else ""), *[f"- {f}" for f in shown],
              "## Commits", *[f"- {c}" for c in facts["commits"]],
              "## Last reports", *[f"- {r[:400]}" for r in facts["reports"][-2:]],
              "## Recent user requests", *[f"- {p[:250]}" for p in facts["prompts"][-4:]]]
    return "\n".join(parts)[:HANDOFF_MAX_CHARS]


def cmd_handoff(args: argparse.Namespace) -> int:
    transcript = Path(args.transcript)
    if not transcript.is_file():
        return 2
    facts = handoff_facts(transcript)
    summary = ""
    if _server_up():
        prompt = ("Write a handoff note for an AI coding agent that continues this work in a fresh session. English, "
                  "at most 12 lines: Goal (1 line), Done, In progress, Next steps, Open risks. Use only the facts "
                  "below; do not invent file names or results.\n\n" + json.dumps(facts, ensure_ascii=False))
        try:
            summary, usage = worker._generate(CHAT_MODEL, prompt, 300)
            log_usage("ask", purpose="handoff", **usage)
        except (urllib.error.URLError, TimeoutError, OSError):
            summary = ""
    path = _handoff_path(args.cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"cwd": args.cwd, "session": args.session, "created": time.time(),
                                "text": render_handoff(facts, summary)}, ensure_ascii=False), encoding="utf-8")
    log_usage("handoff", chars=len(render_handoff(facts, summary)))
    return 0


def _start_handoff(transcript: str, cwd: str, session: str) -> bool:
    """큰 문맥 세션의 인계문을 뒤에서 만든다. 30분 안에 만든 것이 있으면 다시 만들지 않는다."""
    path = _handoff_path(cwd)
    try:
        if path.is_file() and time.time() - path.stat().st_mtime < HANDOFF_REFRESH_S:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file():
            path.touch()  # 진행 중 표시: 30분 안의 중복 실행을 막는다(있던 인계문은 지우지 않고 시각만 쓴다)
        else:
            os.utime(path)
        flags = (getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                 | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0))
        subprocess.Popen([sys.executable, "-m", "v7_harness.olla", "handoff", "--transcript", transcript, "--cwd", cwd,
                          "--session", session], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, cwd=str(Path(__file__).resolve().parents[1]), creationflags=flags,
                         close_fds=True)
        return True
    except OSError:
        return False


def cmd_hook_start(args: argparse.Namespace) -> int:
    """SessionStart 훅: 같은 폴더의 최근 인계문을 새 세션 문맥에 넣는다. 이어 열기(resume)에는 넣지 않는다."""
    try:
        event = json.loads(_stdin_text() or "{}")
        if event.get("source") not in ("startup", "clear"):
            return 0
        record = json.loads(_handoff_path(str(event.get("cwd") or "")).read_text(encoding="utf-8"))
    except (ValueError, OSError, AttributeError):
        return 0
    if not record.get("text") or record.get("session") == event.get("session_id") \
            or time.time() - float(record.get("created", 0)) > HANDOFF_MAX_AGE_S:
        return 0
    stamp = datetime.fromtimestamp(float(record["created"])).strftime("%m-%d %H:%M")
    context = (f"Handoff from the previous session {str(record.get('session'))[:8]} ({stamp}), built by olla from its "
               f"transcript instead of resuming it. Verify before relying on it.\n{record['text']}")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}},
                     ensure_ascii=False))
    log_usage("handoff_used", chars=len(record["text"]))
    return 0


def session_scorecard(session: str) -> str:
    """이 세션이 지금까지 올라마를 얼마나 썼고 보고를 얼마나 길게 했는지 되비춘다.

    규칙과 알림만으로는 반복해서 어겼다(Biz항해 세션 olla 0건, 보고 5줄 초과 5/11턴). 자기 수치를
    매 지시마다 보여 주는 되먹임(feedback)이 규칙 문장보다 행동을 바꾼다는 가정 — 효과는 turn_shape로 잰다.
    """
    if not session or not USAGE_LOG.is_file():
        return ""
    used = hints = turns = long_turns = 0
    last: dict = {}
    for line in USAGE_LOG.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("session") != session:
            continue
        event = rec.get("event")
        used += event in ("ask", "edit", "digest", "find")
        hints += event in ("hint_read", "hint_shell")
        if event == "turn_shape":
            turns += 1
            last = rec
            long_turns += (rec.get("narration_blocks", 0) > 0 or rec.get("final_lines", 0) > REPORT_MAX_LINES
                           or rec.get("final_chars", 0) > REPORT_MAX_CHARS or rec.get("nested_lines", 0) > 0)
    if not (used or hints or turns):
        return ""
    over = last and (last.get("final_lines", 0) > REPORT_MAX_LINES or last.get("final_chars", 0) > REPORT_MAX_CHARS)
    warn = (f" Your last report was {last.get('final_lines')} lines/{last.get('final_chars')} chars; the limit is "
            f"{REPORT_MAX_LINES} lines/{REPORT_MAX_CHARS} chars, so write the next one shorter the first time.") if over else ""
    return (f" This session so far: olla used {used}x, big-read hints {hints}, "
            f"reports breaking the output rule {long_turns}/{turns}.{warn}")


# Windows 는 작업 위치가 260자를 넘으면 셸과 훅을 아예 띄우지 못한다(Biz항해 세션: Stop 훅 ENOENT → 보고 길이
# 제한이 꺼짐). 그 위치로 들어가기 전에 막는다. 들어간 뒤에는 이 훅조차 못 뜬다.
CWD_MAX_CHARS = 200  # 260 한도에서 하위 경로·파일명 여유 60자


def deep_cd_target(command: str, cwd: str) -> str | None:
    for segment in command.replace("&&", ";").split(";"):
        words = segment.strip().split(maxsplit=1)
        if len(words) == 2 and words[0] in ("cd", "Set-Location", "pushd", "sl"):
            raw = words[1].strip().strip("'\"")
            target = Path(raw) if Path(raw).is_absolute() else Path(cwd or ".") / raw
            if len(str(target)) > CWD_MAX_CHARS:
                return str(target)
    return None


# 발상 전환(2026-09-22): 비싼 모델에게 올라마를 "고르라고" 설득하는 방식은 실패했다(Biz 세션 안내 수십 회, 호출 0).
# 비용도 거기 있지 않았다 — Biz 재개 후 144회 호출에서 유료 입력의 98%는 대화 기록 재읽기(cache read)였다.
# 문맥에 한번 들어간 도구 출력은 이후 모든 호출에서 다시 읽힌다. 그래서 선택을 기다리지 않고, 시끄러운 명령의
# 출력을 훅이 자동으로 줄여 문맥에 넣는다. 전체 출력은 파일로 남겨 필요한 줄만 다시 읽게 한다(정보 손실 없음).
NOISY = re.compile(r"\b(pytest|unittest|run_regression\.py|npm (run )?(test|build)|cargo (test|build)|go test|"
                   r"git(\s+-[Cc]\s+(\"[^\"]*\"|'[^']*'|\S+))*\s+(diff|log|show))\b")  # git -C <경로> log 도 잡는다
QUIET_FLAGS = re.compile(r"--stat|--shortstat|--name-only|--name-status|--oneline|\s-n\s*\d|\s-\d+\b")
SHELL_STATE = re.compile(r"(^|[;&|]\s*)(cd|export|source|\.|pushd|popd|alias|unset)\s|<<|\|")
RUN_DIR = Path.home() / ".cache" / "olla" / "run"
SQUEEZE_MAX_CHARS = 6000  # 약 2천 토큰까지는 그대로 둔다: 줄여도 아낄 게 적고 원문이 가장 정확하다
SQUEEZE_TAIL_LINES = 30
SQUEEZE_SIGNAL_LINES = 40
SIGNAL = re.compile(r"error|fail|traceback|exception|assert|panic|denied|not found|^(\+\+\+|---|@@)", re.I)


def noisy_command(command: str) -> bool:
    """출력이 길어지기 쉬운 명령만 고른다. 셸 상태를 바꾸거나 이미 파이프로 거르는 명령은 건드리지 않는다."""
    return bool(NOISY.search(command)) and not QUIET_FLAGS.search(command) and not SHELL_STATE.search(command)


def squeeze_rewrite(command: str) -> str:
    """원래 명령을 스크립트 파일로 두고 `olla squeeze` 로 감싼다. 따옴표 이스케이프 문제를 피한다."""
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    script = RUN_DIR / f"{hashlib.sha256(command.encode('utf-8')).hexdigest()[:16]}.sh"
    script.write_text(command + "\n", encoding="utf-8", newline="\n")
    return f"olla squeeze --script '{script.as_posix()}'"


def squeeze_text(text: str, full_log: Path) -> str:
    """전체를 파일에 남기고, 신호 줄(오류·실패·diff 머리)과 끝 30줄만 돌려준다. 판정은 하지 않는다."""
    if len(text) <= SQUEEZE_MAX_CHARS:
        return text
    full_log.parent.mkdir(parents=True, exist_ok=True)
    full_log.write_text(text, encoding="utf-8")
    lines = text.splitlines()
    tail_start = max(0, len(lines) - SQUEEZE_TAIL_LINES)
    signals = [f"{i + 1}: {line[:300]}" for i, line in enumerate(lines[:tail_start]) if SIGNAL.search(line)]
    shown = signals[:SQUEEZE_SIGNAL_LINES]
    head = (f"[올라마] output squeezed: {len(lines):,} lines -> {len(shown) + len(lines) - tail_start}; "
            f"full log {full_log.as_posix()} (Read with offset/limit for more)")
    body = ["-- signal lines (line: text) --", *shown] if shown else []
    if len(signals) > len(shown):
        body.append(f"... {len(signals) - len(shown)} more signal lines in the full log")
    return "\n".join([head, *body, f"-- last {len(lines) - tail_start} lines --", *lines[tail_start:]]) + "\n"


def cmd_squeeze(args: argparse.Namespace) -> int:
    script = Path(args.script)
    configured_shell = os.environ.get("SHELL")
    posix_shells = {"bash", "sh", "zsh", "dash", "ksh"}
    bash_path = (configured_shell if configured_shell and Path(configured_shell).stem.lower() in posix_shells
                 else shutil.which("bash"))
    if not bash_path and sys.platform == "win32":
        for candidate in [r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files\Git\usr\bin\bash.exe"]:
            if os.path.exists(candidate):
                bash_path = candidate
                break
    done = subprocess.run([bash_path or "bash", str(script)], stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT)
    text = done.stdout.decode("utf-8", errors="replace")
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    out = squeeze_text(text, Path.home() / ".cache" / "olla" / "out" / f"{stamp}_{script.stem}.log")
    sys.stdout.write(out)
    if out is not text:
        log_usage("squeeze", tokens_before=round(len(text.encode("utf-8")) / BYTES_PER_TOKEN),
                  tokens_after=round(len(out.encode("utf-8")) / BYTES_PER_TOKEN))
    return done.returncode


def cmd_hook_bash(args: argparse.Namespace) -> int:
    """PreToolUse(Bash·PowerShell) 훅: 너무 깊은 cd 는 거부하고, 시끄러운 Bash 명령은 출력 압축으로 감싼다."""
    try:
        event = json.loads(_stdin_text() or "{}")
        command = str((event.get("tool_input") or {}).get("command") or "")
        target = deep_cd_target(command, str(event.get("cwd") or ""))
    except (ValueError, AttributeError, TypeError):
        return 0
    if not target and event.get("tool_name") == "Bash" and noisy_command(command):
        updated = dict(event.get("tool_input") or {})
        updated["command"] = squeeze_rewrite(command)
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "updatedInput": updated}}))
        return 0
    if target:
        log_usage("deny_deep_cd", chars=len(target))
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": (f"cd target is {len(target)} chars (> {CWD_MAX_CHARS}); past 260 the shell and hooks "
                                         "stop on Windows. Stay at the project root and use absolute paths.")}}))
    return 0


FOLLOW_WINDOW_S = 600  # 알림 뒤 10분 안에 같은 파일 요약본을 만들었으면 "따랐다"로 센다


def usage_stats(lines: list[str]) -> dict:
    records = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    by_caller: dict[str, dict] = {}
    for rec in records:
        row = by_caller.setdefault(rec.get("caller", "unknown"), {
            "ask": 0, "edit": 0, "digest": 0, "digest_cached": 0, "paid_tokens_saved": 0,
            "hint_plan": 0, "hint_read": 0, "hint_shell": 0, "hint_read_followed": 0,
            "pilot_local": 0, "yield_to_pilot": 0, "deny_whole_read": 0, "squeeze": 0,
            "turns": 0, "turns_within_rule": 0,
        })
        event = rec.get("event")
        if event in row:
            row[event] += 1
        if event == "squeeze":
            row["paid_tokens_saved"] += max(0, rec.get("tokens_before", 0) - rec.get("tokens_after", 0))
        if event == "turn_shape":
            row["turns"] += 1
            # 규칙(v5.16.0): 도구 호출 사이 글 0개, 최종 보고는 결론 1줄 + 글머리 최대 3줄 + 남은 일 1줄 = 5줄 이내
            row["turns_within_rule"] += 1 if rec.get("narration_blocks", 1) == 0 and rec.get("final_lines", 9) <= 5 else 0
        if event == "digest":
            row["digest_cached"] += 1 if rec.get("cached") else 0
            row["paid_tokens_saved"] += max(0, rec.get("paid_tokens_if_read", 0) - rec.get("paid_tokens_digest", 0))
    for i, rec in enumerate(records):
        if rec.get("event") != "hint_read":
            continue
        start = datetime.fromisoformat(rec["ts"])
        for later in records[i + 1:]:
            if (datetime.fromisoformat(later["ts"]) - start).total_seconds() > FOLLOW_WINDOW_S:
                break
            if later.get("event") == "digest" and later.get("file") == rec.get("file") and later.get("caller") == rec.get("caller"):
                by_caller[rec.get("caller", "unknown")]["hint_read_followed"] += 1
                break
    return {"records": len(records), "by_caller": by_caller,
            "note": "paid_tokens_saved = 한 번 읽기 기준(재전송 제외) 추정치"}


def cmd_stats(args: argparse.Namespace) -> int:
    lines = USAGE_LOG.read_text(encoding="utf-8").splitlines() if USAGE_LOG.is_file() else []
    if args.session:
        # 한 세션만 본다(예: Biz항해 세션 감시). 세션 번호 앞부분만 줘도 된다.
        lines = [line for line in lines if f'"session": "{args.session}' in line]
    print(json.dumps(usage_stats(lines), ensure_ascii=False, indent=2))
    return 0


def agy_hook(event_name: str, event: dict) -> dict | None:
    """Antigravity 훅 형식 어댑터(antigravity.google/docs/hooks). Claude·Codex 와 입출력 모양이 다르다.

    - PreInvocation: 턴의 첫 호출에만 분업 안내를 일시 메시지(ephemeralMessage)로 넣는다.
    - PreToolUse(run_command): 깊은 cd 만 거부한다. 그 밖엔 아무 말도 하지 않는다 — "allow"를 내면
      Antigravity 자체 승인 확인을 건너뛸 수 있어서다.
    - Stop: 최종 보고가 길면 한 번 되돌린다(executionNum 0 일 때만, 무한 반복 방지).
    """
    if event_name == "PreInvocation":
        if event.get("invocationNum", 0) != 0 or not _server_up():
            return None
        log_usage("hint_plan", caller="antigravity", session=str(event.get("conversationId") or ""))
        return {"injectSteps": [{"ephemeralMessage": PLAN_HINT + session_scorecard(str(event.get("conversationId") or ""))}]}
    if event_name == "PreToolUse":
        call = event.get("toolCall") or {}
        args = call.get("args") or {}
        if call.get("name") == "run_command":
            target = deep_cd_target(str(args.get("CommandLine") or ""), str(args.get("Cwd") or ""))
            if target:
                log_usage("deny_deep_cd", chars=len(target))
                return {"decision": "deny", "reason": f"cd target is {len(target)} chars; stay at the project root and use absolute paths."}
        if call.get("name") == "view_file" and not (args.get("StartLine") or args.get("EndLine")):
            read_event = {"tool_input": {"file_path": str(args.get("AbsolutePath") or "")}}
            tokens = whole_read_tokens(read_event)
            if tokens >= DENY_WHOLE_READ_TOKENS:
                hint = read_hint(read_event) or ""
                log_usage("deny_whole_read", tokens=tokens)
                # U111: Antigravity gets the same exact outline as Claude's Read and Codex's shell denies (U108).
                return {"decision": "deny", "reason": (f"Whole-file view of ~{tokens:,} tokens refused; find the lines with "
                                                       f"the olla digest or grep, then view with StartLine/EndLine. {hint}"
                                                       + _outline_note(Path(str(args.get("AbsolutePath") or ""))))}
        return None
    if event_name == "Stop":
        path = Path(str(event.get("transcriptPath") or ""))
        shape = turn_shape(path) if path.is_file() else None
        if not shape:
            return None
        log_usage("turn_shape", caller="antigravity", session=str(event.get("conversationId") or ""), **shape)  # Claude 와 같다: 되돌리면 보고가 두 번 보인다. 다음 지시에서 되비춘다
    return None


def cmd_hook_agy(args: argparse.Namespace) -> int:
    try:
        event = json.loads(_stdin_text() or "{}")
        result = agy_hook(args.event, event) if isinstance(event, dict) else None
    except (ValueError, AttributeError, TypeError, OSError):
        return 0
    if result:
        print(json.dumps(result, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="olla", description="로컬 Ollama 모델을 어느 프로젝트에서든 부려 쓰는 명령")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("ask")
    p.add_argument("prompt")
    p.add_argument("-f", "--file", action="append", default=[])
    p.add_argument("--ko", action="store_true", help="한국어 규칙을 붙이고, 한국어가 아니면 한 번 다시 시킴(실패 시 종료 코드 4)")
    p.add_argument("--model", default=CHAT_MODEL)
    p.add_argument("--timeout", type=int, default=900)
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("edit")
    p.add_argument("instruction")
    p.add_argument("-f", "--file", action="append", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--model", default=CHAT_MODEL)
    p.add_argument("--timeout", type=int, default=900)
    p.set_defaults(func=cmd_edit)

    p = sub.add_parser("estimate", help="비싼 모델이 이 파일들을 읽을 때 드는 토큰 추정")
    p.add_argument("-f", "--file", action="append", default=[])
    p.add_argument("--prompt", default="")
    p.set_defaults(func=cmd_estimate)

    p = sub.add_parser("route", help="이 과제를 로컬로 보낼지 스스로 정함")
    p.add_argument("task")
    p.add_argument("-f", "--file", action="append", default=[])
    p.set_defaults(func=cmd_route)

    p = sub.add_parser("digest", help="큰 파일의 줄 번호 요약본(비싼 모델이 읽기 전에)")
    p.add_argument("-f", "--file", action="append", required=True)
    p.add_argument("--focus", default="")
    p.add_argument("--model", default=CHAT_MODEL)
    p.add_argument("--timeout", type=int, default=900)
    p.add_argument("--no-cache", action="store_true", help="같은 내용·질문의 이전 요약본을 쓰지 않음")
    p.set_defaults(func=cmd_digest)

    p = sub.add_parser("hook-read", help="Claude Code PreToolUse(Read) 훅: 큰 파일이면 요약본을 권함")
    p.set_defaults(func=cmd_hook_read)

    p = sub.add_parser("hook-shell", help="Codex PostToolUse(Bash) 훅: 큰 파일을 통째로 읽었으면 요약본을 권함")
    p.set_defaults(func=cmd_hook_shell)

    p = sub.add_parser("hook-plan", help="UserPromptSubmit 훅: 작업 시작 시 로컬 모델 분업을 먼저 정하게 함")
    p.set_defaults(func=cmd_hook_plan)

    p = sub.add_parser("hook-agy", help="Antigravity 훅 어댑터(PreInvocation·PreToolUse·Stop)")
    p.add_argument("event", choices=["PreInvocation", "PreToolUse", "Stop"])
    p.set_defaults(func=cmd_hook_agy)

    p = sub.add_parser("hook-bash", help="PreToolUse(Bash) 훅: 260자 한도에 가까운 깊은 cd 거부")
    p.set_defaults(func=cmd_hook_bash)

    p = sub.add_parser("handoff", help="세션 기록으로 새 세션용 인계문을 만듦(이어 열기 대신)")
    p.add_argument("--transcript", required=True)
    p.add_argument("--cwd", required=True)
    p.add_argument("--session", default="")
    p.set_defaults(func=cmd_handoff)

    p = sub.add_parser("hook-start", help="SessionStart 훅: 같은 폴더의 최근 인계문을 새 세션에 넣음")
    p.set_defaults(func=cmd_hook_start)

    p = sub.add_parser("squeeze", help="스크립트를 실행하고 긴 출력은 신호 줄·끝 30줄만 보임(전체는 파일), 종료 코드 유지")
    p.add_argument("--script", required=True)
    p.set_defaults(func=cmd_squeeze)

    p = sub.add_parser("hook-stop", help="Stop 훅: 턴의 진행 설명 수·최종 보고 길이 기록")
    p.set_defaults(func=cmd_hook_stop)

    p = sub.add_parser("stats", help="세 도구의 olla 사용 기록 집계(실제 세션 절감 추정)")
    p.add_argument("--session", default="", help="이 세션 번호(앞부분)만 집계")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("find")
    p.add_argument("query")
    p.add_argument("-d", "--dir", default=".")
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--limit", type=int, default=300)
    p.set_defaults(func=cmd_find)
    return parser


def main(argv: list[str] | None = None) -> int:
    # Windows 콘솔 기본 인코딩(cp949)에서는 한국어 답이 깨진다. 부르는 도구가 읽을 수 있게 UTF-8로 고정한다.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass
    args = build_parser().parse_args(argv)
    if args.command in ("ask", "edit", "find") and _pilot_has_gpu():
        return GPU_BUSY_EXIT
    return args.func(args)


def code_outline(path: Path) -> str:
    """U108: exact line ranges from the parser (Python) or headings (Markdown); "" when there is none."""
    import ast

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        lines: list[str] = []
        if path.suffix == ".py":
            try:
                tree = ast.parse(text)
            except (SyntaxError, ValueError):
                return ""
            funcs = (ast.FunctionDef, ast.AsyncFunctionDef)
            for node in tree.body:
                if not isinstance(node, funcs + (ast.ClassDef,)):
                    continue
                start = min([node.lineno] + [d.lineno for d in node.decorator_list])
                kind = "class" if isinstance(node, ast.ClassDef) else "def"
                lines.append(f"L{start}-{node.end_lineno}: {kind} {node.name}")
                if isinstance(node, ast.ClassDef):
                    for m in node.body:
                        if isinstance(m, funcs):
                            mstart = min([m.lineno] + [d.lineno for d in m.decorator_list])
                            lines.append(f"L{mstart}-{m.end_lineno}: def {node.name}.{m.name}")
        elif path.suffix == ".md":
            lines = [f"L{i}: {line.strip()}" for i, line in enumerate(text.splitlines(), 1) if line.startswith("#")]
        else:
            return ""
    except OSError:
        return ""
    if len(lines) > OUTLINE_MAX_LINES:
        extra = len(lines) - (OUTLINE_MAX_LINES - 1)
        lines = lines[: OUTLINE_MAX_LINES - 1] + [f"... {extra} more"]
    return "\n".join(lines)


def _outline_note(path: Path) -> str:
    outline = code_outline(path)
    return f"\nExact outline of {path.name}:\n{outline}" if outline else ""


if __name__ == "__main__":
    sys.exit(main())
