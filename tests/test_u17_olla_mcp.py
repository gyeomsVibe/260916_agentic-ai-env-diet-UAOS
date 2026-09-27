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

    def test_file_errors_are_not_reported_as_an_unreachable_model(self) -> None:
        base = Path(self.tmp.name) / "project"
        base.mkdir()
        locked, wanted = base / "locked.txt", base / "wanted.txt"
        locked.write_text("locked needle", encoding="utf-8")
        wanted.write_text("the semantic needle", encoding="utf-8")
        real_read = Path.read_text

        def read(path, *args, **kwargs):
            if path.name == "locked.txt":
                raise PermissionError(13, "Permission denied", str(path))
            return real_read(path, *args, **kwargs)

        with mock.patch("v7_harness.adapters.gpu_priority.pilot_active", return_value=False), \
             mock.patch.object(Path, "read_text", read), \
             mock.patch.object(olla, "_embed", side_effect=lambda texts: [[1.0]] * len(texts)):
            found = olla_mcp.call_tool("local_search", {"query": "needle", "folder": str(base)})
        self.assertFalse(found["isError"], found["content"][0]["text"])  # the locked file is skipped, not fatal
        self.assertIn(wanted.resolve().as_posix(), found["content"][0]["text"])
        self.assertNotIn("locked.txt", found["content"][0]["text"])

        with mock.patch.object(olla, "digest_file", side_effect=PermissionError(13, "Permission denied", str(wanted))):
            denied = olla_mcp.call_tool("local_read_map", {"path": str(wanted)})
        self.assertTrue(denied["isError"])
        self.assertIn("local file error", denied["content"][0]["text"])
        with mock.patch.object(olla, "digest_file", side_effect=ConnectionRefusedError(10061, "refused")):
            down = olla_mcp.call_tool("local_read_map", {"path": str(wanted)})
        self.assertIn("local model unreachable", down["content"][0]["text"])

    def test_unknown_method_and_server_down_are_reported_not_raised(self) -> None:
        self.assertEqual(-32601, olla_mcp.handle({"id": 9, "method": "nope"})["error"]["code"])
        target = Path(self.tmp.name) / "f.py"
        target.write_text("x = 1\n", encoding="utf-8")
        with mock.patch.object(olla.worker, "_generate", side_effect=OSError("refused")):
            down = olla_mcp.call_tool("local_read_map", {"path": str(target)})
        self.assertTrue(down["isError"])


if __name__ == "__main__":
    unittest.main()
