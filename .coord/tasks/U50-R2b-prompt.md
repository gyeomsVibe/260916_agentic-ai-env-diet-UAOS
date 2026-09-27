U50-R2b: context admission gate with checked content snapshots (docs/49 §5 U-TOK-2; Codex TOCTOU verdict on U50-R1). Apply the blocks exactly. No other change.

===FILE: v7_harness/context_admission.py===
"""U50: context admission gate. docs/49 §2·§5 U-TOK-2.

The manual's optional `context_allow:` list names the extra files (patterns) a worker call may see. When the list is
present, a file reaches the call only if it is a pinned input, sits under `allow` (the worker has to see what it
edits), or matches `context_allow`; everything else the prompt happens to mention is left out and recorded as denied.
Nothing widens the list automatically: if a denial makes the acceptance fail, the fix is a new manual with a wider
list, and the denial record shows what was missing. A manual without `context_allow` keeps the old behaviour, except
that a file outside the workspace ("..", absolute path, symlink or junction) is never read in either mode.

U50-R2 (Codex TOCTOU verdict on U50-R1): admission used to return names and the caller re-read `workspace / name`
later, so a junction swapped in after the check leaked the file behind it. Admission now reads each admitted file once,
through one open handle whose final path (the path the operating system actually opened, links resolved) must lie
under the workspace, and hands out that text. Callers never open an admitted name again.
"""

from __future__ import annotations

import fnmatch
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

PINNED_RE = re.compile(r"^- (\S+) sha256=[0-9a-f]{64}\s*$", re.M)


@dataclass
class Admission:
    active: bool
    admitted: list[str] = field(default_factory=list)
    denied: list[str] = field(default_factory=list)
    escaped: list[str] = field(default_factory=list)
    # name -> text read through the checked handle; the only content a caller may use.
    snapshots: dict[str, str] = field(default_factory=dict)


def _norm(path: str) -> str:
    return path.strip().replace("\\", "/")


def _lexical_ok(rel: str) -> bool:
    pure = PurePosixPath(rel)
    return bool(rel) and not pure.is_absolute() and not re.match(r"^[A-Za-z]:", rel) and ".." not in pure.parts


def inside(workspace: Path, path: str) -> bool:
    """U50-R1 (Codex counterexample docs/../../outside.txt): a candidate is readable only if it is relative, has no
    "..", and still lies under the workspace after resolve() follows symlinks and junctions (reparse points).
    A pre-filter only: the read in snapshot() re-checks the path of the handle it actually opened."""
    rel = _norm(path)
    if not _lexical_ok(rel):
        return False
    root = Path(workspace).resolve()
    try:
        (root / rel).resolve().relative_to(root)
    except (ValueError, OSError):
        return False
    return True


def _fd_path(fd: int) -> str | None:
    """The final path of an open file: what the OS opened after following every link. None = cannot tell (refuse)."""
    if os.name == "nt":
        import ctypes
        import msvcrt
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD,
                                                       wintypes.DWORD]
        kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
        handle = msvcrt.get_osfhandle(fd)
        # 32767 = the longest extended-length path Windows accepts, so one call always fits.
        buffer = ctypes.create_unicode_buffer(32768)
        length = kernel32.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
        if not length or length >= len(buffer):
            return None
        path = buffer.value
        if path.startswith("\\\\?\\UNC\\"):
            return "\\\\" + path[8:]
        return path[4:] if path.startswith("\\\\?\\") else path
    if sys.platform.startswith("linux"):
        try:
            return os.readlink(f"/proc/self/fd/{fd}")
        except OSError:
            return None
    if sys.platform == "darwin":
        import fcntl

        try:
            # F_GETPATH = 50 on macOS: the kernel's path for the vnode behind the descriptor; MAXPATHLEN = 1024.
            raw = fcntl.fcntl(fd, 50, b"\0" * 1024)
            return raw.split(b"\0", 1)[0].decode("utf-8", "surrogateescape")
        except OSError:
            return None
    return None


def _under(path: str, root: Path) -> bool:
    # normpath, not realpath: resolving the handle's path again would follow the (possibly swapped) links a second time.
    try:
        Path(os.path.normcase(os.path.normpath(path))).relative_to(Path(os.path.normcase(str(root))))
    except ValueError:
        return False
    return True


def snapshot(workspace: Path, path: str) -> str | None:
    """Read one workspace file as text, or None when it is not provably inside. The check is on the open handle, so a
    link swapped in between any earlier check and this read is caught, and the text returned is the text checked."""
    rel = _norm(path)
    if not _lexical_ok(rel):
        return None
    root = Path(workspace).resolve()
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(root / rel, flags)
    except OSError:
        return None
    with os.fdopen(fd, "r", encoding="utf-8") as handle:
        real = _fd_path(fd)
        if real is None or not _under(real, root):
            return None
        try:
            return handle.read()
        except (OSError, UnicodeDecodeError):
            return None


def matches(path: str, patterns: list[str]) -> bool:
    """fnmatch on the posix path; a pattern ending in "/" admits everything under that folder."""
    path = _norm(path)
    for raw in patterns:
        pattern = _norm(raw)
        if not pattern:
            continue
        if pattern.endswith("/"):
            if path.startswith(pattern):
                return True
        elif fnmatch.fnmatchcase(path, pattern) or PurePosixPath(path) == PurePosixPath(pattern):
            return True
    return False


def admit(prompt: str, candidates: list[str], workspace: Path, read: bool = True) -> Admission:
    """Split candidates into admitted and denied by the contract in the prompt; order is kept, denials are sorted.
    The workspace boundary is checked first and in every mode, before any pattern match or read. With read=True each
    admitted file is also snapshotted; a file whose checked read fails moves to escaped."""
    from v7_harness.manual import parse_contract

    escaped = sorted(p for p in candidates if not inside(workspace, p))
    candidates = [p for p in candidates if p not in escaped]
    contract = parse_contract(prompt) or {}
    result = Admission(active="context_allow" in contract, escaped=escaped)
    if not result.active:
        result.admitted = list(candidates)
    else:
        pinned = {_norm(m) for m in PINNED_RE.findall(prompt)}
        patterns = [*contract.get("allow", []), *contract.get("context_allow", [])]
        for path in candidates:
            if _norm(path) in pinned or matches(path, patterns):
                result.admitted.append(path)
            else:
                result.denied.append(path)
        result.denied.sort()
    if read:
        for path in list(result.admitted):
            text = snapshot(workspace, path)
            if text is None:
                result.admitted.remove(path)
                result.escaped = sorted({*result.escaped, path})
            else:
                result.snapshots[path] = text
    return result
===END===

===FILE: tests/test_u50_context_admission.py===
"""U50: context admission gate (docs/49 §5 U-TOK-2)."""

from __future__ import annotations

import contextlib
import hashlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness import manual
from v7_harness.adapters import ollama_worker
from v7_harness.context_admission import admit, inside, matches, snapshot


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _names(admitted: list[tuple[str, str]]) -> list[str]:
    return [name for name, _text in admitted]


def _workspace(root: Path) -> None:
    (root / "src").mkdir()
    (root / "docs").mkdir()
    (root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / "docs" / "big.md").write_text("filler line\n" * 2000, encoding="utf-8")
    (root / "docs" / "note.md").write_text("note\n", encoding="utf-8")
    (root / "core.md").write_text("rules\n" * 500, encoding="utf-8")
    (root / "ids.txt").write_text("1\n2\n", encoding="utf-8")


def _prompt(root: Path, context_allow: list[str] | None) -> str:
    lines = ["```contract", "work_id: T", "inputs:", f"- ids.txt sha256={_sha(root / 'ids.txt')}",
             "allow:", "- src/a.py"]
    if context_allow is not None:
        lines += ["context_allow:", *[f"- {item}" for item in context_allow]]
    lines += ["```", "Edit `src/a.py`; see `docs/big.md`, `docs/note.md` and core.md."]
    return "\n".join(lines)


class ParseAndLintTest(unittest.TestCase):
    def test_context_allow_is_a_list_and_does_not_leak_into_allow(self):
        contract = manual.parse_contract("```contract\nallow:\n- a.py\ncontext_allow:\n- docs/note.md\n```")
        self.assertEqual(["a.py"], contract["allow"])
        self.assertEqual(["docs/note.md"], contract["context_allow"])

    def test_lint_rejects_wide_or_escaping_items(self):
        with tempfile.TemporaryDirectory() as d:
            for bad in ("*", "**", "../secret.md", "C:/x.md", "/etc/x"):
                text = manual.new_manual(Path(d), work_id="T", worker="apply", goal="Write `a.py`.", inputs=[],
                                         allow=["a.py"], acceptance="python -c 1", judge="codex",
                                         context_allow=[bad])
                errors = manual.lint(text, Path(d)).errors
                self.assertTrue(any(e.startswith("CONTEXT_ALLOW_TOO_WIDE") for e in errors), (bad, errors))

    def test_new_manual_emits_the_list_only_when_given(self):
        with tempfile.TemporaryDirectory() as d:
            kw = dict(work_id="T", worker="apply", goal="g", inputs=[], allow=["a.py"], acceptance="c", judge="codex")
            self.assertNotIn("context_allow", manual.new_manual(Path(d), **kw))
            text = manual.new_manual(Path(d), context_allow=["docs/"], **kw)
            self.assertEqual(["docs/"], manual.parse_contract(text)["context_allow"])


class AdmissionTest(unittest.TestCase):
    def test_matches_glob_folder_and_exact(self):
        self.assertTrue(matches("docs/a.md", ["docs/*.md"]))
        self.assertTrue(matches("docs/sub/a.md", ["docs/"]))
        self.assertTrue(matches("src\\a.py", ["src/a.py"]))
        self.assertFalse(matches("docs/a.md", ["src/"]))

    def test_without_context_allow_behaviour_is_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _workspace(root)
            prompt = _prompt(root, None)
            legacy = ollama_worker.context_files(prompt, root)
            with mock.patch.object(ollama_worker, "_log") as log:
                self.assertEqual(legacy, _names(ollama_worker.admitted_context(prompt, root)))
            log.assert_not_called()

    def test_disallowed_files_are_left_out_and_recorded(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _workspace(root)
            prompt = _prompt(root, ["docs/note.md"])
            with mock.patch.object(ollama_worker, "_log") as log:
                admitted = _names(ollama_worker.admitted_context(prompt, root))
            self.assertEqual(["ids.txt", "docs/note.md", "src/a.py"], admitted)
            log.assert_called_once_with("context_denied", work_id="T", denied=["core.md", "docs/big.md"])

    def test_empty_list_admits_only_inputs_and_allow(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _workspace(root)
            result = admit(_prompt(root, []), ollama_worker.context_files(_prompt(root, []), root), root)
            self.assertTrue(result.active)
            self.assertEqual(["ids.txt", "src/a.py"], result.admitted)

    def test_denial_record_is_deterministic(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _workspace(root)
            prompt = _prompt(root, [])
            first = admit(prompt, ["docs/note.md", "core.md", "docs/big.md"], root).denied
            second = admit(prompt, ["docs/big.md", "docs/note.md", "core.md"], root).denied
            self.assertEqual(first, second)
            self.assertEqual(["core.md", "docs/big.md", "docs/note.md"], first)

    def test_admission_shrinks_the_context_sent_to_the_model(self):
        # The gate measured here is the byte size of the CURRENT FILE context (the part of the local call that the
        # list controls); input tokens per call are estimated from it the way main() does (bytes // 3).
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _workspace(root)

            def context_bytes(prompt: str) -> int:
                with mock.patch.object(ollama_worker, "_log"):
                    admitted = ollama_worker.admitted_context(prompt, root)[:4]
                return sum(len(text.encode("utf-8")) for _name, text in admitted)

            before = context_bytes(_prompt(root, None))
            after = context_bytes(_prompt(root, ["docs/note.md"]))
            self.assertLess(after, before // 10, (before, after))


def _link_dir(link: Path, target: Path) -> None:
    """A directory reparse point without admin rights: a junction on Windows, a symlink elsewhere."""
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


class BoundaryTest(unittest.TestCase):
    """U50-R1: Codex's counterexample. Red on U50-S1b: docs/../../outside.txt was admitted under context_allow docs/."""

    def _layout(self, tmp: str) -> tuple[Path, Path]:
        ws = Path(tmp) / "ws"
        (ws / "docs").mkdir(parents=True)
        (ws / "docs" / "note.md").write_text("note\n", encoding="utf-8")
        secret = Path(tmp) / "secret"
        secret.mkdir()
        (secret / "s.md").write_text("private\n", encoding="utf-8")
        (Path(tmp) / "outside.txt").write_text("outside\n", encoding="utf-8")
        _link_dir(ws / "docs" / "link", secret)
        return ws, secret

    def _prompt(self, context_allow: bool) -> str:
        head = "```contract\nwork_id: T\nallow:\n- docs/note.md\n"
        head += "context_allow:\n- docs/\n" if context_allow else ""
        return head + "```\nRead `docs/../../outside.txt`, `docs/link/s.md` and `docs/note.md`."

    def test_traversal_and_junction_never_reach_the_model(self):
        for context_allow in (True, False):
            with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ollama_worker, "_log") as log:
                ws, _ = self._layout(tmp)
                prompt = self._prompt(context_allow)
                # Precondition: the old candidate list really contains both escapes.
                self.assertIn("docs/../../outside.txt", ollama_worker.context_files(prompt, ws))
                admitted = _names(ollama_worker.admitted_context(prompt, ws))
                self.assertEqual(["docs/note.md"], admitted, context_allow)
                log.assert_any_call("context_escape", work_id="T",
                                    escaped=["docs/../../outside.txt", "docs/link/s.md"])

    def test_inside_rejects_absolute_and_drive_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws, secret = self._layout(tmp)
            self.assertTrue(inside(ws, "docs/note.md"))
            for bad in ("../outside.txt", "docs/../../outside.txt", "docs/link/s.md", str(secret / "s.md"),
                        "C:/Windows/win.ini", "/etc/passwd", ""):
                self.assertFalse(inside(ws, bad), bad)


class SwapTest(unittest.TestCase):
    """U50-R2: Codex's TOCTOU counterexample on U50-R1. The check passed on a real folder; the folder was then swapped
    for a junction to a secret folder and main() re-read workspace / name, so OUTSIDE_SECRET reached the model."""

    def _layout(self, tmp: str) -> tuple[Path, Path]:
        ws = Path(tmp) / "ws"
        (ws / "docs" / "sub").mkdir(parents=True)
        (ws / "docs" / "sub" / "s.md").write_text("public note\n", encoding="utf-8")
        secret = Path(tmp) / "secret"
        secret.mkdir()
        (secret / "s.md").write_text("OUTSIDE_SECRET\n", encoding="utf-8")
        return ws, secret

    @staticmethod
    def _swap(ws: Path, secret: Path) -> None:
        (ws / "docs" / "sub").rename(ws / "docs" / "sub_old")
        _link_dir(ws / "docs" / "sub", secret)

    def _prompt(self) -> str:
        return ("```contract\nwork_id: T\nallow:\n- docs/note.md\ncontext_allow:\n- docs/\n```\n"
                "Read `docs/sub/s.md`.")

    def test_swap_after_admission_never_reaches_the_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws, secret = self._layout(tmp)
            real = ollama_worker.admitted_context
            sent: list[str] = []

            def admitted_then_swapped(prompt: str, workspace: Path):
                result = real(prompt, workspace)
                self._swap(ws, secret)  # the attacker's window: after the check, before any later read
                return result

            def fake_generate(model: str, prompt: str, timeout_s: int, **_kw):
                sent.append(prompt)
                return "no blocks", {"input_tokens": 0, "output_tokens": 0}

            with mock.patch.object(ollama_worker, "admitted_context", admitted_then_swapped), \
                    mock.patch.object(ollama_worker, "_generate", fake_generate), \
                    mock.patch.object(ollama_worker, "_log"), \
                    mock.patch("v7_harness.adapters.gpu_priority.pilot_holds",
                               lambda _t: contextlib.nullcontext()), \
                    contextlib.redirect_stdout(io.StringIO()):
                ollama_worker.main(["-p", self._prompt(), "--add-dir", str(ws)])
            self.assertEqual(len(sent), 1)
            self.assertIn("public note", sent[0])
            self.assertNotIn("OUTSIDE_SECRET", sent[0])

    def test_swap_between_check_and_open_is_caught_on_the_handle(self):
        from v7_harness import context_admission

        with tempfile.TemporaryDirectory() as tmp:
            ws, secret = self._layout(tmp)
            real_open = os.open
            swapped: list[bool] = []

            def open_after_swap(path, flags, *args):
                if not swapped:
                    swapped.append(True)
                    self._swap(ws, secret)  # inside() already approved the real folder
                return real_open(path, flags, *args)

            with mock.patch.object(context_admission.os, "open", open_after_swap):
                result = admit(self._prompt(), ["docs/sub/s.md"], ws)
            self.assertEqual(swapped, [True])
            self.assertEqual([], result.admitted)
            self.assertEqual(["docs/sub/s.md"], result.escaped)
            self.assertEqual({}, result.snapshots)

    def test_snapshot_reads_inside_and_refuses_links_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws, secret = self._layout(tmp)
            self.assertEqual("public note\n", snapshot(ws, "docs/sub/s.md"))
            _link_dir(ws / "docs" / "out", secret)
            for bad in ("docs/out/s.md", "../secret/s.md", str(secret / "s.md"), "docs/missing.md", ""):
                self.assertIsNone(snapshot(ws, bad), bad)


if __name__ == "__main__":
    unittest.main()
===END===

===FILE: docs/49_article12-ollama-extraction-and-uaos-update-report_2026-09-27.md===
# 49. 기사 12건 올라마 재분석 + 외부 자료 비교 → UAOS 개선·업데이트 보고서

- 작성: Claude Code (Codex 대행 아님, Codex 복귀 시 재검토 대상), 2026-09-27
- 입력: `docs/user-docs/# UAOS 기사 분석 보고서 01~12.md` (13~15번 종합본은 비교 기준으로만 사용)
- 산출물 등급: 유지(maintained) 문서. 추출 원본은 `.work/article_ollama_20260927/`(일회성, 커밋 제외)

---

## 1. 결론 먼저

**UAOS에 새 에이전트나 새 프로바이더 계층을 더하지 말고, "문맥에 무엇이 들어가도 되는가"를 재는 관문 3개를 먼저 넣는다.**

| 순위 | 도입 로직 | 출처 기사 | 현재 코드 상태 | 외부 근거 |
|---|---|---|---|---|
| P1 | 도구 출력 토큰 관문(Tool Output Token Gate) + 오래된 관찰 가리기(observation masking) | 08, 15번 종합 | 없음(`grep tool_output\|masking` 0건) | 관찰 토큰이 턴의 약 84%, 단순 가리기로 비용 절반·성능 동등(arXiv 2508.21433) |
| P1 | 문맥 입장 관문(Context Admission Gate) = 지연 능력 로딩(Lazy Capability Loading) | 08, 04(C10) | 없음(`admission` 0건) | MCP 도구 정의 선로딩 1회 약 7k~50k 토큰, 도구 검색 지연 로딩으로 85% 감소 보고 |
| P1 | 작업별 모델 자격 관문(Model Qualification Gate) + 모델 산출물 고정(pinning) | 06, 11 | 부분(`olla.py` 읽기 비용 추정만 있음) | **이번 실행 자체가 증거**: 4B 로컬 모델의 원문 인용 정확도 32/67=48% |
| P2 | 토큰 톱니(Token Ratchet): 검증된 최저 토큰량을 회귀 상한으로 고정 | 01 | 부분(`rsi.py`에 회귀 관문 있음, 토큰 축은 없음) | claude.ai 3배 개선: 여정 4개(사용량 95%)·지표 13개로 측정 후 고정 |
| P2 | 도구 실행 방화벽(Tool Proposal/Execution Firewall)·작업별 허용목록 | 04, 08 | 부분(`adapters/guard.py`, 전역 규칙) | Ollama·OpenAI 도구 호출은 "요청"일 뿐 실행 권한이 아님 |
| P3 | 능력 증거 등록부(Capability Evidence Registry)·프로브 | 02, 03, 07, 10 | 없음 | OpenAI 호환 선언 ≠ 기능 보장(Ollama 문서도 부분 호환 명시) |
| 보류 | 빠른 판단 평면(Fast Decision Plane), 다중 프로바이더 라이브러리 흡수, OpenClaude 코드 도입 | 12, 07, 10 | — | 12번 추출 6건 모두 인용 불일치, 07번은 유출 코드 라이선스 위험 |

---

## 2. 이번 분석을 어떻게 했나 (재현 가능한 절차)

토큰 예산이 사용 한도에 가깝다는 조건 때문에 **읽기·추출은 올라마, 판단·비교는 Claude**로 나눴다.

1. **기사 1건 = 올라마 새 대화 1회.** 대화 기록을 공유하지 않고 12번 따로 호출했다(`extract.py`, 모델 `qwen3.5-32k`, temperature 0, JSON 형식 강제).
2. **호출마다 작업 매뉴얼 전달.** 작업 ID `U-ART12-EXTRACT-nn`, 입력 SHA-256, 출력 스키마, 금지 행동(원문에 없는 문장 생성), 인수 관문을 프롬프트 머리에 넣었다.
3. **독립 관문 2개로 검증.** (a) `quote`가 원문에 글자 그대로 있는지, (b) 후보 이름이 원문에 있는지 — 둘 다 결정적(deterministic) 파이썬 검사. 올라마의 "성공" 응답은 증거로 치지 않았다.
4. **Claude는 원문 전체를 읽지 않았다.** 제목·판정 줄과 올라마 추출 결과, 코드 `grep` 결과, 웹 검색 8회만 사용했다.

### 측정값

| 항목 | 값 |
|---|---|
| 호출 수 | 12회(실패 0, JSON 파싱 오류 0) |
| 로컬 벽시계 시간 | 합계 360초(1번 72초는 모델 적재 포함, 나머지 21~33초) |
| 로컬 토큰 | 입력 45,037 / 출력 7,053 |
| 후보 추출 | 67건 |
| 인용 원문 일치 | 32건(48%) — 35건은 의역이라 관문에서 탈락 |
| 이름 원문 일치 | 60건(90%) — 탈락 7건은 이름 앞 번호 형식 변형 |
| 기사별 최악 | 12번: 인용 0/6 (긴 원문 20KB, 추상 개념 위주) |

**해석:** 4B급 로컬 모델은 "무엇이 있는지 찾기(이름·목록)"는 90% 신뢰, "그대로 베끼기(인용)"는 48%다. 그래서 UAOS에서 올라마 출력은 **반드시 원문 대조 관문 뒤에서만** 쓰여야 하며, 이것이 P1 "모델 자격 관문"의 직접 근거다.

**Claude 토큰 절감은 측정하지 않았다(UNMEASURED).** 원문 12건(약 187KB)을 Claude가 직접 읽었을 경우와의 대조 실험은 하지 않았다.

---

## 3. 12개 기사별 핵심 (올라마 추출 → 원문 대조 통과분 중심)

| # | 기사 | 문서 자체 판정 | 대조 통과한 핵심 로직 |
|---|---|---|---|
| 01 | Claude.ai 2주 만에 3배 빠르게 | 보강 도입 | 사용자 여정 성능 장부, 대리지표 검증 관문, 성능 톱니 |
| 02 | Ollama OpenAI 호환성 | 도입 | OpenAI 호환 전송 어댑터, 능력 명세(SUPPORTED/UNSUPPORTED/UNVERIFIED), 네이티브 탈출구 |
| 03 | Ollama OpenAI 형식 호출 | 신규 로직 없음 | 프로바이더 교체 불변식(판단 체계는 바뀌면 안 됨) |
| 04 | Ollama 도구 호출 | 강력 도입 | 도구 제안/실행 방화벽, 작업별 도구 허용목록 |
| 05 | Ollama 웹 검색 API | 강력 도입 | 검색 증거 사다리, 검색 권한 방화벽, 외부 전송 최소화, 검색 예산 관문 |
| 06 | Ollama v0.1.33 신모델 | 강력 도입 | 모델 자격 관문(실행 가능 ≠ 작업자 승인) |
| 07 | OpenClaude(유출 코드 파생) | 코드 보류 / 구조만 추출 | 런타임·프로바이더 분리, 도구 호출 정규화 |
| 08 | Function Calling vs MCP | 신규 도입 | MCP 경계 어댑터, 발견/인가 분리, 서버 신뢰 등록부, 지연 능력 로딩, 버전 고정 |
| 09 | MCP로 IntelliJ 연동 | 강력 도입 | 작업공간 범위 고정 |
| 10 | OpenLM 다중 LLM 클라이언트 | 부분 중복 + 보강 | 결과 봉투 정규화, 실패 분류 정규화, 실패 인식 대체 경로, 어댑터 의존성 방화벽 |
| 11 | Ollama Python/JS 라이브러리 | 도입 | 클라이언트 SDK 동작 고정 |
| 12 | Laya(Jev 대안) | "생각할 필요 없는 판단을 LLM에 시키지 않는다" | 인용 통과 0건 → 이름만 확인(C45~C50), 판단 근거로 쓰지 않음 |

---

## 4. 외부 자료와의 비교

### 4.1 기사 내용이 외부 자료로 확인된 것 (사실)

- **01번 수치**: Anthropic은 사용량 95%를 차지하는 여정 4개를 측정해 3,000건 이상 변경을 2주에 배포했고 롤백이 없었다. 예: 새 페이지 입력 가능 시점 p75 3.1초→0.55초. → "측정 먼저, 개선은 작게, 개선치는 고정"이라는 01번 해석과 일치.
- **05·02·04번**: Ollama는 웹 검색 API, OpenAI 호환 엔드포인트의 도구 지원, Anthropic Messages API 호환(2026-01)까지 제공한다. → 로컬 모델에 도구·검색 권한이 "기술적으로" 열렸다는 뜻이며, 그래서 **실행 권한 분리(04번 C09)**가 필수가 된다.
- **07번**: OpenClaude는 2026-03-31 npm 소스맵 유출본의 파생이다. → 코드 직접 도입 보류 판정이 맞다.
- **08번**: MCP 도구 정의를 매 턴 선로딩하면 서버 4개 기준 메시지당 약 7,000토큰, 무거운 구성은 50,000토큰 이상. 지연 로딩(도구 검색)으로 85% 감소, 코드 실행 방식으로 150k→2k(98.7%) 사례.

### 4.2 논문이 더해 준 것 (기사에 없던 근거)

- **The Complexity Trap (arXiv 2508.21433, NeurIPS DL4Code 2025)**: 오래된 도구 관찰을 그냥 가리는 방식이 LLM 요약과 해결률이 같거나 약간 높고 비용은 절반. → UAOS는 **요약 에이전트를 추가하지 말고, 결정적 가리기부터** 해야 한다. 이는 전역 규칙 "결정적 추출 먼저"와 같은 방향.
- **ACON(arXiv 2510.00615)**, **SWE-Pruner(2601.16746)**, **Squeez(2604.04979)**: 압축 지침을 실패 분석으로 개선, 작업 조건부로 도구 출력을 잘라냄. → P2 이후 후보. 모델 학습이 필요 없는 ACON 방식만 UAOS RSI(증거 제안→관문)와 궁합이 맞다.
- **Execution Instability 연구(arXiv 2608.06503)**: 압축이 장기 작업을 불안정하게 만들 수 있다. → 압축 도입 시 반드시 회귀 관문(인수 테스트 동일 통과)을 둔다.

### 4.3 커뮤니티(일화, 증거 아님)

- CLAUDE.md는 매 질의마다 다시 전송되므로 가장 비싼 상시 문맥이라는 경험담이 반복된다. 설정 도중 변경은 프롬프트 캐시를 깨뜨린다. → "상시 적재 문맥 예산"을 따로 재야 한다(15번 종합본 14절과 일치).
- Claude Code를 Ollama로 돌리는 "월 0원" 사례가 많지만 64K 이상 문맥·도구 호출 품질이 전제다. → UAOS의 "올라마 = 계산기" 원칙을 바꿀 근거는 되지 않는다. 이번 실측 인용 정확도 48%가 반례다.

### 4.4 기존 종합본(13~15번)과의 차이

- 15번이 제안한 5개(문맥 입장 관문, 한 번 읽기 공유 증거 캐시, 도구 출력 관문, 공급자별 예산 중개, 토큰 회귀 관문)는 **방향 동의**.
- 차이 1: "한 번 읽기 공유 증거 캐시"는 이미 `olla.py`의 읽기 비용 추정·요약본 우선 규칙(`read_once`, `DIGEST_MIN_TOKENS`)으로 일부 존재 → 신규가 아니라 **확장**이다.
- 차이 2: `broker/core.py`는 프로세스 잠금 중개기이지 예산 중개기가 아니다. 이름이 같아 혼동 위험 → 새 기능은 `budget_broker`가 아닌 다른 이름을 권장.
- 차이 3: 15번은 모델 품질 문제를 다루지 않았다. 이번 실측(인용 48%)으로 **모델 자격 관문을 P1로 올린다.**

---

## 5. 도입 계획 (작은 계약 단위)

각 항목은 "관문(gate)을 먼저 정하고, 통과하면 끝"이다. 코드는 아직 바꾸지 않았다.

### U-TOK-1 도구 출력 토큰 관문 + 관찰 가리기 (P1)
- 무엇: 작업자에게 되돌리는 도구 출력에 상한(예: 결과당 N토큰)을 두고, 넘으면 머리/꼬리+파일 포인터로 대체. 최근 k턴보다 오래된 관찰은 "[생략: 파일경로#해시]"로 가린다.
- 왜 이 방식: 논문상 결정적 가리기가 LLM 요약과 성능 동등·비용 절반. 로컬 모델 요약은 이번 실측처럼 원문 충실도가 낮다.
- 관문: 기존 `pilot` 인수 테스트 통과율 동일 + 같은 작업 3회 평균 입력 토큰 감소를 `usage_ledger` 수치로 비교. 감소 없으면 폐기.

### U-TOK-2 문맥 입장 관문 (P1)
- 무엇: 작업 계약(PLAN 카드)에 `context_allow: [파일, 도구, MCP 서버]`를 두고, 목록 밖 항목은 작업자 호출에 싣지 않는다.
- 관문: 입장 거부된 항목 때문에 인수 실패가 생기면 목록 누락으로 기록(자동 확장 금지). 호출당 입력 토큰을 전후 비교.

### U-MQ-1 작업별 모델 자격 관문 + 고정 (P1)
- 무엇: `(provider, model tag, digest, 작업 유형)`별로 자격 기록. 작업 유형 예: `list_extract`, `verbatim_quote`, `summarize`, `code_edit`.
- 초기값(이번 실측): `qwen3.5-32k` → `list_extract` 90% QUALIFIED, `verbatim_quote` 48% REJECTED.
- 관문: 고정 fixture 12건(이번 기사 12건과 해시)으로 재측정. 모델 digest가 바뀌면 자격 자동 승계 금지.

### U-TOK-3 토큰 톱니 (P2)
- 무엇: `rsi gate`에 토큰 축 추가. 검증된 최저 토큰량을 기준선으로 저장, 품질이 같아도 토큰이 기준선의 1.2배를 넘으면 실패. (1.2 = 실행 간 변동 흡수용 초기값, 3회 측정 후 재조정)
- 전역 규칙의 "3배 회귀 = 실패"보다 촘촘한 조기 경보 역할.

### U-SEC-1 도구 실행 방화벽 명문화 (P2)
- 무엇: 올라마·외부 모델의 tool call은 `PROPOSED` 상태로만 기록하고, 실행은 UAOS 정책 판정 후에만. `POLICY_DENIED`는 대체 경로 없이 종료(10번 C41).

### 도입하지 않을 것
- 빠른 판단 평면(12번): 원문 대조 0/6, 자체 데이터 보정 근거 없음.
- 다중 프로바이더 라이브러리 흡수(07·10번): 어댑터 1개 뒤로 격리하는 원칙만 채택.
- 요약 전용 에이전트 추가: 논문상 가리기 대비 이득 없음.

---

## 6. 확인된 사실 / 가정 / 모름

- **사실**: 올라마 12회 호출 결과·토큰·시간(위 표), 코드 검색 결과(`admission`·`tool_output`·`masking`·`ratchet`·`journey` 0건), 외부 수치(출처 아래).
- **가정**: U-TOK-1/2가 UAOS 작업에서도 논문 수준(비용 약 50%)의 절감을 낸다는 것. 측정 전까지 UNMEASURED.
- **모름**: Claude 쪽 토큰이 실제로 얼마나 절감됐는지(대조 실험 없음), 더 큰 로컬 모델(예: `qwen2.5-coder:7b`)의 인용 정확도.

## 7. 출처

- [How we made claude.ai 3x faster in two weeks](https://claude.dev/blog/how-we-made-claude-ai-faster/) · [Help Net Security 요약](https://www.helpnetsecurity.com/2026/09/24/anthropic-claude-ai-faster/)
- [Ollama Web search 문서](https://docs.ollama.com/capabilities/web-search) · [Ollama Tool support](https://ollama.com/blog/tool-support) · [Ollama OpenAI Compatibility](https://ollama.readthedocs.io/en/openai/)
- [OpenClaude (Gitlawb)](https://github.com/Gitlawb/openclaude) · [Claude Code 유출 요약](https://actionablenotes.substack.com/p/the-claude-code-leak-a-mini-brief)
- [MCP Tool Search 가이드](https://www.atcyrus.com/stories/mcp-tool-search-claude-code-context-pollution-guide) · [MCP 토큰 오버헤드 분석](https://docs.bswen.com/blog/2026-04-24-mcp-token-overhead/) · [Code execution with MCP 98.7%](https://brightbean.xyz/blog/code-execution-mcp-efficient-ai-agents/) · [MCP 토론 #629](https://github.com/orgs/modelcontextprotocol/discussions/629)
- 논문: [The Complexity Trap 2508.21433](https://arxiv.org/abs/2508.21433) · [저장소](https://github.com/JetBrains-Research/the-complexity-trap) · [ACON 2510.00615](https://arxiv.org/abs/2510.00615) · [SWE-Pruner 2601.16746](https://arxiv.org/pdf/2601.16746) · [Squeez 2604.04979](https://arxiv.org/pdf/2604.04979) · [압축 실행 불안정성 2608.06503](https://arxiv.org/html/2608.06503v1) · [Awesome-Agent-Context-Compression](https://github.com/YerbaPage/Awesome-Agent-Context-Compression)
- 커뮤니티(일화): [Claude Code 프롬프트 캐싱 문서](https://code.claude.com/docs/en/prompt-caching) · [Ollama + Claude Code 설정기](https://www.morphllm.com/ollama-claude-code)
===END===

===EDIT: v7_harness/manual.py===
<<<<<<< SEARCH
LIST_KEYS = ("inputs", "allow")
=======
# U50: context_allow is optional; without it a list key would swallow its "- " items into the previous list.
LIST_KEYS = ("inputs", "allow", "context_allow")
>>>>>>> REPLACE

===EDIT: v7_harness/manual.py===
<<<<<<< SEARCH
            report.errors.append(f"ALLOW_TOO_WIDE:{item}")
=======
            report.errors.append(f"ALLOW_TOO_WIDE:{item}")
    # U50: a wildcard list would admit the whole workspace and undo the gate.
    for item in contract.get("context_allow", []):
        if not _safe_relative(item) or item.strip().replace("\\", "/") in ("*", "**", "*/", "**/", "**/*"):
            report.errors.append(f"CONTEXT_ALLOW_TOO_WIDE:{item}")
>>>>>>> REPLACE

===EDIT: v7_harness/manual.py===
<<<<<<< SEARCH
    instructions: str = "",
) -> str:
=======
    instructions: str = "",
    context_allow: list[str] | None = None,
) -> str:
>>>>>>> REPLACE

===EDIT: v7_harness/manual.py===
<<<<<<< SEARCH
        *[f"- {item}" for item in allow],
        f"acceptance: {acceptance}",
=======
        *[f"- {item}" for item in allow],
        *(["context_allow:", *[f"- {item}" for item in context_allow]] if context_allow is not None else []),
        f"acceptance: {acceptance}",
>>>>>>> REPLACE

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
        remote_budget_usd=args.remote_budget_usd,
        instructions=instructions,
    )
=======
        remote_budget_usd=args.remote_budget_usd,
        instructions=instructions,
        context_allow=args.context_allow,
    )
>>>>>>> REPLACE

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
    p_manual_new.add_argument("--allow", action="append", default=[], required=True)
=======
    p_manual_new.add_argument("--allow", action="append", default=[], required=True)
    p_manual_new.add_argument("--context-allow", action="append", default=None,
                              help="U50: extra file or pattern the worker may see (repeatable); omit to keep all")
>>>>>>> REPLACE

===EDIT: v7_harness/adapters/ollama_worker.py===
<<<<<<< SEARCH
def contract_work_id(prompt: str) -> str | None:
=======
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


def contract_work_id(prompt: str) -> str | None:
>>>>>>> REPLACE

===EDIT: v7_harness/adapters/ollama_worker.py===
<<<<<<< SEARCH
    named = context_files(args.prompt, workspace)
    context = "".join(
        f"\n===CURRENT FILE: {name}===\n{(workspace / name).read_text(encoding='utf-8')}\n"
        for name in named[:4]
    )
=======
    # U50-R2: the admitted text itself travels on; re-reading workspace / name here let a swapped link leak.
    named = admitted_context(args.prompt, workspace)[:4]
    context = "".join(f"\n===CURRENT FILE: {name}===\n{text}\n" for name, text in named)
>>>>>>> REPLACE

===EDIT: v7_harness/adapters/ollama_worker.py===
<<<<<<< SEARCH
    longest = max((len((workspace / name).read_text(encoding="utf-8").splitlines()) for name in named[:4]), default=0)
=======
    longest = max((len(text.splitlines()) for _name, text in named), default=0)
>>>>>>> REPLACE
