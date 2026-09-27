```contract
work_id: U47-OLLA-SCOPE-F1
worker: apply
goal: local_search prunes whole repository copies (.coord/pilot stages, .claude/worktrees) before the scan cap and candidate budget, and call_tool never rebinds the tool-name variable (finding 2).
inputs:
- v7_harness/olla_mcp.py sha256=319e7b1d518f7cfe02f0b60aabd4f9f064b078fcf1ee53783c7b7c4c73291179
- tests/test_u17_olla_mcp.py sha256=7dd81df854ca03e5473d91faac863f5fb5ccfd767121e5ae747b7a6d2cab27a1
allow:
- v7_harness/olla_mcp.py
- tests/test_u17_olla_mcp.py
acceptance: C:/Python314/python.exe -m unittest tests.test_u17_olla_mcp
forbidden: design changes; edits outside allow; weakening or deleting existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Card: PLAN U47-OLLA-SCOPE, finding 1 of `.coord/tasks/U47-OLLA-SCOPE-claude-independent-review-20260927.md`.
Measured on the main project root with mocked embeddings: before, 289 of the 300 embedded candidates came from
repository copies; after, 4 (all from the small `.coord/pilot-r2` experiment, intentionally kept).

===FILE: v7_harness/olla_mcp.py===
"""olla MCP 서버 — 로컬 모델을 에이전트의 '도구 목록'에 올린다.

왜: 안내(11회)·요약본 인계·큰 읽기 거부를 다 해도 에이전트는 olla 를 거의 쓰지 않았다. 에이전트는
도구 목록에 있는 것 중에서 고른다. 도구 선택은 요청과 도구 이름·설명의 의미 일치가 가장 강한 예측
변수다(BiasBusters, arXiv:2510.00307; 설명 문구만 바꿔도 선택이 크게 바뀜, arXiv:2505.18135).
셸 명령 `olla` 는 목록에 없어서 Read·Grep 과 경쟁조차 못 했다. 그래서 같은 기능을 MCP 도구로 노출한다.

의존성 없이 표준 입출력 JSON-RPC(한 줄 = 한 메시지)만 구현한다. 판정은 하지 않는다.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
from pathlib import Path
from typing import Any

from v7_harness import olla

PROTOCOL_VERSION = "2025-06-18"
# Keep the existing embedding batch bound, and inspect at most ten filesystem entries per possible candidate. This
# prevents skipped trees from turning one semantic search into an unbounded drive walk while retaining 300 documents.
SEARCH_CANDIDATE_LIMIT = 300
SEARCH_SCAN_LIMIT = SEARCH_CANDIDATE_LIMIT * 10
# (parent, child) directory pairs that hold whole copies of the repository: pilot stages and agent worktrees. The main
# project root has 25,025 entries, 23,132 under .coord/pilot; a root search filled 289 of its 300 candidates with those
# duplicates (4 after pruning), and a copy walked before the real files could exhaust the scan cap. Pairs, not bare
# names, so an ordinary `pilot/` source folder is still searched.
SEARCH_COPY_TREES = {(".coord", "pilot"), (".claude", "worktrees")}

TOOLS = [
    {
        "name": "local_read_map",
        "description": (
            "Read a large file for 0 paid tokens. Returns a line-numbered map of the file (which lines hold "
            "which functions, sections, and facts), written by the local model. Use this FIRST whenever you need "
            "to understand or locate something in a file over ~300 lines, then read only the lines you need. "
            "Cached per file content, so repeat calls are instant."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path of the file."},
                "question": {"type": "string", "description": "What you are looking for (optional, English)."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "local_draft",
        "description": (
            "Draft text for 0 paid tokens with the local model: commit messages, summaries, docstrings, "
            "changelog lines, classifications, first drafts. Prompt in English with the format, length, and one "
            "example. Set korean=true only for text the user will read. Always check the result before using it; "
            "the tool reports invented file or test names."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "instruction": {"type": "string"},
                "files": {"type": "array", "items": {"type": "string"}, "description": "Absolute paths to include."},
                "korean": {"type": "boolean"},
            },
            "required": ["instruction"],
        },
    },
    {
        "name": "local_search",
        "description": (
            "Find files by meaning for 0 paid tokens (local embeddings). Use when you do not know the exact "
            "keyword to grep for. Returns the most similar text files under a folder."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "folder": {"type": "string", "description": "Existing absolute non-root folder path."},
                "top": {"type": "integer"},
            },
            "required": ["query", "folder"],
        },
    },
]


# 도구가 많으면 클라이언트가 MCP 도구를 이름만 보이는 지연 목록(deferred)에 넣는다. Biz 세션(dec0f758)은
# 목록에 local_* 가 있었는데도 0회였다. 서버 안내문(instructions)은 지연돼도 시스템 프롬프트에 들어간다.
INSTRUCTIONS = (
    "olla = local model, 0 paid tokens. Before reading a file over ~300 lines, drafting (commit messages, summaries, "
    "docs), or searching by meaning, call local_read_map / local_draft / local_search. If they are deferred, load all "
    "three first: ToolSearch select:mcp__olla__local_read_map,mcp__olla__local_draft,mcp__olla__local_search"
)

PREFIX = "[올라마] "  # 사용자가 화면에서 로컬 모델이 한 일을 알아보게 한다(2026-09-22 사용자 지시)


def _text(value: str, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": PREFIX + value}], "isError": is_error}


def _needs_gpu(name: str, args: dict[str, Any]) -> bool:
    if name == "local_read_map":
        path = Path(str(args.get("path") or ""))
        try:
            return path.is_file() and not olla._digest_cache_path(path, str(args.get("question") or ""), olla.CHAT_MODEL).is_file()
        except OSError:
            return False
    return name in ("local_draft", "local_search")


def _search_folder(value: Any) -> tuple[Path | None, str | None]:
    """Resolve one explicitly supplied project/subfolder without falling back to the server working directory."""
    raw = value if isinstance(value, str) else ""
    if not raw.strip():
        return None, "local_search requires a non-empty absolute folder"
    supplied = Path(raw).expanduser()
    if not supplied.is_absolute():
        return None, f"local_search folder must be absolute: {supplied}"
    if supplied == Path(supplied.anchor):
        return None, f"local_search refuses a filesystem root: {supplied}"
    try:
        base = supplied.resolve(strict=True)
    except OSError:
        return None, f"no such folder: {supplied}"
    if base == Path(base.anchor):
        return None, f"local_search refuses a filesystem root: {base}"
    if not base.is_dir():
        return None, f"no such folder: {base}"
    return base, None


def call_tool(name: str, args: dict[str, Any]) -> dict:
    from v7_harness.adapters.gpu_priority import BUSY_MESSAGE, pilot_active

    search_base = None
    if name == "local_search":
        search_base, folder_error = _search_folder(args.get("folder"))
        if folder_error:
            return _text(folder_error, True)
    if _needs_gpu(name, args) and pilot_active():  # 파일럿 우선(B74). 캐시된 지도는 GPU 없이 바로 준다
        olla.log_usage("yield_to_pilot", via="mcp")
        return _text(BUSY_MESSAGE, True)
    try:
        if name == "local_read_map":
            path = Path(str(args.get("path") or ""))
            if not path.is_file():
                return _text(f"no such file: {path}", True)
            question = str(args.get("question") or "")
            cache = olla._digest_cache_path(path, question, olla.CHAT_MODEL)
            if cache.is_file():
                digest, cached = json.loads(cache.read_text(encoding="utf-8"))["digest"], True
            else:
                digest, _ = olla.digest_file(path, question, olla.CHAT_MODEL, 900)
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps({"path": path.as_posix(), "digest": digest}, ensure_ascii=False), encoding="utf-8")
                cached = False
            before = round(path.stat().st_size / olla.BYTES_PER_TOKEN)
            after = round(len(digest.encode("utf-8")) / olla.BYTES_PER_TOKEN)
            olla.log_usage("digest", file=str(path.resolve()), paid_tokens_if_read=before, paid_tokens_digest=after,
                           cached=cached, via="mcp")
            return _text(digest + f"\n(map ~{after:,} tokens instead of ~{before:,}; confirm exact lines with a ranged read)")
        if name == "local_draft":
            files = [str(f) for f in args.get("files") or []]
            empty = [f for f in files if Path(f).is_file() and not Path(f).read_text(encoding="utf-8", errors="replace").strip()]
            if empty:
                return _text(f"empty input file (the model would invent content): {', '.join(empty)}", True)
            prompt = str(args.get("instruction") or "")
            if files:
                prompt += "\n" + olla._read_files(files)
            if args.get("korean"):
                prompt = olla.KO_RULES + prompt
            text, usage = olla.worker._generate(olla.CHAT_MODEL, prompt, 900)
            olla.log_usage("ask", ko=bool(args.get("korean")), via="mcp", **usage)
            fake = olla.missing_refs(text, Path.cwd())
            note = f"\n\n[check: references not found, likely invented: {', '.join(fake)}]" if fake else ""
            return _text(text.strip() + note)
        if name == "local_search":
            assert search_base is not None  # validated before the GPU gate, so invalid paths never traverse
            base = search_base
            skip = {".git", ".work", "__pycache__", "node_modules", ".venv"}
            candidates = []
            scanned = 0
            for directory, names, files in os.walk(base):
                # Prune before counting: a repository's .git/.work trees must never consume the useful-search budget.
                parent = Path(directory).name
                names[:] = [child for child in names if child not in skip and (parent, child) not in SEARCH_COPY_TREES]
                for _ in (*names, *files):
                    scanned += 1
                    if scanned > SEARCH_SCAN_LIMIT:
                        return _text(f"local_search scan limit reached: {SEARCH_SCAN_LIMIT} entries", True)
                for filename in files:  # never rebind `name`: it is the tool name used by the fallback reply
                    path = Path(directory) / filename
                    if not path.is_file() or path.suffix not in olla.TEXT_SUFFIXES:
                        continue
                    body = path.read_text(encoding="utf-8", errors="replace")[:2000]
                    if body.strip():
                        candidates.append((path, body))
                    if len(candidates) >= SEARCH_CANDIDATE_LIMIT:
                        break
                if len(candidates) >= SEARCH_CANDIDATE_LIMIT:
                    break
            if not candidates:
                return _text("no text files", True)
            vectors = olla._embed([str(args["query"])] + [body for _, body in candidates])
            query, docs = vectors[0], vectors[1:]
            ranked = sorted(zip(candidates, docs), key=lambda item: olla._cosine(query, item[1]), reverse=True)
            olla.log_usage("find", via="mcp")
            top = int(args.get("top") or 5)
            return _text("\n".join(f"{olla._cosine(query, v):.3f}  {p.as_posix()}" for (p, _), v in ranked[:top]))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return _text(f"local model unreachable: {exc}", True)
    return _text(f"unknown tool: {name}", True)


def handle(message: dict) -> dict | None:
    method, msg_id = message.get("method"), message.get("id")
    if msg_id is None:
        return None  # 알림(notifications/*)에는 답하지 않는다
    if method == "initialize":
        result: dict = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                        "serverInfo": {"name": "olla", "version": "1.0"}, "instructions": INSTRUCTIONS}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = message.get("params") or {}
        result = call_tool(str(params.get("name")), params.get("arguments") or {})
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def main() -> int:
    stdin = sys.stdin.buffer
    for raw in stdin:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            reply = handle(json.loads(line))
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        if reply is not None:
            sys.stdout.buffer.write((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))
            sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
===END===

===FILE: tests/test_u17_olla_mcp.py===
"""U17: olla MCP 서버 — 로컬 모델을 에이전트 도구 목록에 올린다. 실제 프로세스로 JSON-RPC 를 주고받는다."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness import olla, olla_mcp

ROOT = Path(__file__).resolve().parents[1]


class OllaMcpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for name, value in (("USAGE_LOG", Path(self.tmp.name) / "u.jsonl"), ("DIGEST_CACHE_DIR", Path(self.tmp.name) / "c")):
            patch = mock.patch.object(olla, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def test_handshake_and_tool_list_over_a_real_process(self) -> None:
        env = dict(os.environ, PYTHONPATH=str(ROOT), OLLA_USAGE=str(Path(self.tmp.name) / "u.jsonl"))
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ]
        done = subprocess.run([sys.executable, "-m", "v7_harness.olla_mcp"], cwd=ROOT, env=env, timeout=60,
                              input="".join(json.dumps(m) + "\n" for m in messages).encode("utf-8"), capture_output=True)
        replies = [json.loads(line) for line in done.stdout.decode("utf-8").splitlines()]
        self.assertEqual([1, 2], [r["id"] for r in replies])  # 알림에는 답하지 않음
        self.assertEqual("olla", replies[0]["result"]["serverInfo"]["name"])
        # 지연 목록(deferred)에 들어가도 불러오는 방법이 시스템 프롬프트에 남아야 한다(Biz dec0f758: 목록에 있어도 0회)
        for name in ("local_read_map", "local_draft", "local_search"):
            self.assertIn(f"mcp__olla__{name}", replies[0]["result"]["instructions"])
        names = [t["name"] for t in replies[1]["result"]["tools"]]
        self.assertEqual(["local_read_map", "local_draft", "local_search"], names)

    def test_tools_yield_to_a_running_pilot_but_cached_maps_still_work(self) -> None:
        from v7_harness.adapters import gpu_priority

        with mock.patch.object(gpu_priority, "GPU_DIR", Path(self.tmp.name) / "gpu"):
            target = Path(self.tmp.name) / "m.py"
            target.write_text("x = 1\n", encoding="utf-8")
            with mock.patch.object(olla.worker, "_generate", return_value=("- L1-1: x", {})):
                olla_mcp.call_tool("local_read_map", {"path": str(target)})  # 캐시 채움
            with gpu_priority.pilot_holds(60), mock.patch.object(olla.worker, "_generate") as gen:
                busy = olla_mcp.call_tool("local_draft", {"instruction": "x"})
                cached = olla_mcp.call_tool("local_read_map", {"path": str(target)})
            gen.assert_not_called()
        self.assertTrue(busy["isError"])
        self.assertIn("GPU busy", busy["content"][0]["text"])
        self.assertFalse(cached["isError"])

    def test_mcp_exposes_no_write_tool(self) -> None:
        # 쓰기(수정)는 SQLite 파일럿의 관문(staging·manifest·bundle 승인)으로만 한다. MCP 가 쓰기 도구를
        # 내면 관문을 우회하는 두 번째 경로가 생긴다 — 그 충돌을 구조로 막는다.
        for tool in olla_mcp.TOOLS:
            self.assertNotRegex(tool["name"], r"edit|write|apply|patch|delete")
            self.assertNotIn("path_to_write", json.dumps(tool["inputSchema"]))

    def test_read_map_uses_and_fills_the_cache(self) -> None:
        target = Path(self.tmp.name) / "big.py"
        target.write_text("x = 1\n" * 50, encoding="utf-8")
        with mock.patch.object(olla.worker, "_generate", return_value=("- L1-50: assignments", {})) as gen:
            first = olla_mcp.call_tool("local_read_map", {"path": str(target)})
            second = olla_mcp.call_tool("local_read_map", {"path": str(target)})
        self.assertIn("L1-50", first["content"][0]["text"])
        self.assertEqual(first["content"][0]["text"], second["content"][0]["text"])
        self.assertEqual(1, gen.call_count)

    def test_draft_refuses_empty_input_and_flags_invented_names(self) -> None:
        empty = Path(self.tmp.name) / "e.md"
        empty.write_text("", encoding="utf-8")
        refused = olla_mcp.call_tool("local_draft", {"instruction": "x", "files": [str(empty)]})
        self.assertTrue(refused["isError"])
        with mock.patch.object(olla.worker, "_generate", return_value=("run tests.test_nope", {})):
            flagged = olla_mcp.call_tool("local_draft", {"instruction": "x"})
        self.assertIn("likely invented", flagged["content"][0]["text"])

    def test_search_refuses_unsafe_folder_before_traversal_or_embedding(self) -> None:
        file_path = Path(self.tmp.name) / "not-a-folder.txt"
        file_path.write_text("x", encoding="utf-8")
        root = Path(self.tmp.name).anchor
        cases = (
            {},
            {"folder": ""},
            {"folder": "   "},
            {"folder": "relative/path"},
            {"folder": root},
            {"folder": str(Path(self.tmp.name) / "missing")},
            {"folder": str(file_path)},
        )
        with mock.patch("v7_harness.adapters.gpu_priority.pilot_active", return_value=False), \
             mock.patch.object(Path, "rglob") as rglob, mock.patch.object(olla, "_embed") as embed:
            for args in cases:
                with self.subTest(args=args):
                    result = olla_mcp.call_tool("local_search", {"query": "needle", **args})
                    self.assertTrue(result["isError"])
        rglob.assert_not_called()
        embed.assert_not_called()

    def test_search_ranks_a_valid_absolute_subfolder_with_mocked_embeddings(self) -> None:
        base = Path(self.tmp.name) / "project" / "docs"
        base.mkdir(parents=True)
        wanted = base / "wanted.txt"
        wanted.write_text("the semantic needle", encoding="utf-8")
        (base / "other.txt").write_text("unrelated", encoding="utf-8")

        def vectors(texts):
            return [[1.0, 0.0]] + [[1.0, 0.0] if "semantic needle" in text else [0.0, 1.0]
                                   for text in texts[1:]]

        with mock.patch("v7_harness.adapters.gpu_priority.pilot_active", return_value=False), \
             mock.patch.object(olla, "_embed", side_effect=vectors):
            result = olla_mcp.call_tool("local_search", {"query": "needle", "folder": str(base), "top": 1})
        self.assertFalse(result["isError"])
        self.assertTrue(result["content"][0]["text"].splitlines()[0].endswith(wanted.resolve().as_posix()))

    def test_search_scan_cap_counts_irrelevant_paths(self) -> None:
        base = Path(self.tmp.name) / "project"
        base.mkdir()
        irrelevant = []
        for index in range(12):
            path = base / f"skip-{index}.bin"
            path.write_bytes(b"x")
            irrelevant.append(path)
        with mock.patch("v7_harness.adapters.gpu_priority.pilot_active", return_value=False), \
             mock.patch("v7_harness.olla_mcp.os.walk", return_value=[(str(base),
                                                                         [path.name for path in irrelevant], [])]), \
             mock.patch.object(olla_mcp, "SEARCH_SCAN_LIMIT", 5, create=True), \
             mock.patch.object(olla, "_embed") as embed:
            result = olla_mcp.call_tool("local_search", {"query": "needle", "folder": str(base)})
        self.assertTrue(result["isError"])
        self.assertIn("scan limit reached", result["content"][0]["text"])
        embed.assert_not_called()

    def test_search_prunes_repository_copies_before_the_scan_cap(self) -> None:
        # Main project root counterexample: 23,132 of 25,025 entries sat under .coord/pilot, so root search always failed.
        base = Path(self.tmp.name) / "project"
        for copy in (base / ".coord" / "pilot" / "stage", base / ".claude" / "worktrees" / "wt"):
            copy.mkdir(parents=True)
            for index in range(20):
                (copy / f"dup-{index}.md").write_text("semantic needle copy", encoding="utf-8")
        source = base / "src" / "pilot"  # an ordinary folder named pilot is still searched
        source.mkdir(parents=True)
        wanted = source / "wanted.md"
        wanted.write_text("the semantic needle", encoding="utf-8")

        def vectors(texts):
            return [[1.0, 0.0]] + [[1.0, 0.0] if "needle" in text else [0.0, 1.0] for text in texts[1:]]

        with mock.patch("v7_harness.adapters.gpu_priority.pilot_active", return_value=False), \
             mock.patch.object(olla_mcp, "SEARCH_SCAN_LIMIT", 15), \
             mock.patch.object(olla, "_embed", side_effect=vectors):
            result = olla_mcp.call_tool("local_search", {"query": "needle", "folder": str(base), "top": 5})
        self.assertFalse(result["isError"], result["content"][0]["text"])
        lines = result["content"][0]["text"].splitlines()
        self.assertEqual(1, len(lines))
        self.assertTrue(lines[0].endswith(wanted.resolve().as_posix()))

    def test_call_tool_never_rebinds_the_tool_name(self) -> None:
        # A loop `for name in files` once shadowed the tool name, so a fall-through reply would name a file instead.
        # Comprehension variables are excluded: they have their own scope in Python 3 and cannot rebind `name`.
        import ast
        import inspect
        import textwrap

        tree = ast.parse(textwrap.dedent(inspect.getsource(olla_mcp.call_tool)))
        rebinds = [sub.lineno for node in ast.walk(tree)
                   if isinstance(node, (ast.For, ast.Assign, ast.AugAssign, ast.AnnAssign,
                                        ast.With, ast.NamedExpr))
                   for target in ([node.target] if hasattr(node, "target") else getattr(node, "targets", []))
                   + [item.optional_vars for item in getattr(node, "items", []) if item.optional_vars]
                   for sub in ast.walk(target) if isinstance(sub, ast.Name) and sub.id == "name"]
        self.assertEqual([], rebinds)

    def test_unknown_method_and_server_down_are_reported_not_raised(self) -> None:
        self.assertEqual(-32601, olla_mcp.handle({"id": 9, "method": "nope"})["error"]["code"])
        target = Path(self.tmp.name) / "f.py"
        target.write_text("x = 1\n", encoding="utf-8")
        with mock.patch.object(olla.worker, "_generate", side_effect=OSError("refused")):
            down = olla_mcp.call_tool("local_read_map", {"path": str(target)})
        self.assertTrue(down["isError"])


if __name__ == "__main__":
    unittest.main()
===END===

## Output

- Reply with ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.
