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
            # U109: a reply with no blocks earns one repair call, which re-sends the same admitted prompt.
            self.assertEqual(len(sent), 1 + ollama_worker.REPAIRS)
            self.assertIn("public note", sent[0])
            for prompt in sent:
                self.assertNotIn("OUTSIDE_SECRET", prompt)

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
