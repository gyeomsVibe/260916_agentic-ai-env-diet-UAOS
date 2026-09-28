"""U37: UAOS in every project — the global installer, hook-aware attendance, `coord init` and the resident sentinel.

All installer tests run against a temporary HOME; nothing touches the real ~/.claude, ~/.codex or ~/.gemini.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from v7_harness import global_install as gi
from v7_harness.cli import main
from v7_harness.coord.hook_context import brief_line, find_project, hook_project, payload_candidates

PYTHON = sys.executable


def _home(root: Path) -> Path:
    home = root / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".codex").mkdir()
    (home / ".gemini" / "config").mkdir(parents=True)
    (home / ".claude" / "CLAUDE.md").write_text("# My rules\n- keep this\n", encoding="utf-8")
    (home / ".claude" / "settings.json").write_text(json.dumps({
        "permissions": {"allow": ["Bash(ls)"], "deny": ["WebFetch"]},
        "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo mine"}]}]},
        "outputStyle": "brief-ko"}), encoding="utf-8")
    (home / ".codex" / "hooks.json").write_text('{"hooks": {}}', encoding="utf-8")
    (home / ".codex" / "config.toml").write_text('model = "gpt"\n[features]\nweb = true\n', encoding="utf-8")
    (home / ".gemini" / "config" / "hooks.json").write_text('{"lint": {"enabled": true, "Stop": []}}', encoding="utf-8")
    return home


def _snapshot(home: Path) -> dict[str, str]:
    return {str(p.relative_to(home)): p.read_text(encoding="utf-8")
            for p in sorted(home.rglob("*")) if p.is_file() and ".uaos" not in p.parts[len(home.parts):][:1]
            and ".uaos-backups" not in p.parts}


def _run(home: Path, *args: str) -> tuple[int, dict]:
    out = io.StringIO()
    with redirect_stdout(out):
        code = gi.main(["--home", str(home), "--python", PYTHON, *args])
    return code, json.loads(out.getvalue())


class InstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.home = _home(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_dry_run_writes_nothing(self) -> None:
        before = _snapshot(self.home)
        code, report = _run(self.home)
        self.assertEqual(0, code)
        self.assertEqual(before, _snapshot(self.home))
        self.assertFalse((self.home / ".uaos").exists())
        actions = {c["target"]: c["action"] for c in report["changes"]}
        self.assertEqual("UPDATE", actions["claude settings"])
        self.assertEqual("CREATE", actions["codex rules"])

    def test_apply_then_check_is_clean_and_keeps_user_settings(self) -> None:
        code, report = _run(self.home, "--apply")
        self.assertEqual(0, code)
        self.assertTrue(report["applied"]["backup_dir"])
        self.assertEqual(0, _run(self.home, "--check")[0])
        settings = json.loads((self.home / ".claude" / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(["WebFetch", *gi.DENY], settings["permissions"]["deny"])
        self.assertEqual(["Bash(ls)"], settings["permissions"]["allow"])
        self.assertEqual("brief-ko", settings["outputStyle"])
        start = settings["hooks"]["SessionStart"]
        self.assertEqual("echo mine", start[0]["hooks"][0]["command"])
        self.assertIn("--tool claude --state ACTIVE", start[1]["hooks"][0]["command"])
        # U38: silent on ordinary prompts; one line only for a P1 hand-off while Codex is away.
        self.assertIn("--say p1", settings["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"])
        rules = (self.home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertTrue(rules.startswith("# My rules\n- keep this\n\n<!-- UAOS:BEGIN"))
        # Hook and rule commands write paths with forward slashes on every OS (bash, cmd and PowerShell all run them).
        self.assertIn((self.home / ".uaos" / "uaos.py").as_posix(), rules)
        self.assertNotIn("{uaos}", rules)
        toml = (self.home / ".codex" / "config.toml").read_text(encoding="utf-8")
        self.assertIn("[features]\nhooks = true\nweb = true", toml)
        agy = json.loads((self.home / ".gemini" / "config" / "hooks.json").read_text(encoding="utf-8"))
        self.assertIn("lint", agy)
        self.assertIn("--say empty-json", agy["uaos-presence"]["PreInvocation"][0]["command"])
        backups = list((self.home / ".uaos-backups").rglob("settings.json"))
        self.assertEqual(1, len(backups))
        self.assertIn("echo mine", backups[0].read_text(encoding="utf-8"))

    def test_second_apply_changes_nothing(self) -> None:
        _run(self.home, "--apply")
        first = _snapshot(self.home)
        _, report = _run(self.home, "--apply")
        self.assertEqual([], report["applied"]["written"])
        self.assertEqual(first, _snapshot(self.home))

    def test_check_reports_a_block_removed_by_the_rules_generator(self) -> None:
        _run(self.home, "--apply")
        (self.home / ".codex" / "AGENTS.md").write_text("# regenerated by sync-global-rules.ps1\n", encoding="utf-8")
        code, report = _run(self.home, "--check")
        self.assertEqual(1, code)
        self.assertEqual(["codex rules"], report["drift"])

    def test_canon_generated_rule_files_have_one_writer(self) -> None:
        _run(self.home, "--apply", "--no-rules")
        marker = "<!-- GENERATED from English canonical rules v5.26.0. Edit the source files, not this deployment. -->\n"
        paths = (self.home / ".claude" / "CLAUDE.md", self.home / ".codex" / "AGENTS.md",
                 self.home / ".gemini" / "GEMINI.md")
        for index, path in enumerate(paths):
            prefix = "\ufeff" if index == 0 else ""
            path.write_text(prefix + marker + f"# canonical {path.name}\n", encoding="utf-8")
        before = {path: path.read_text(encoding="utf-8") for path in paths}

        code, report = _run(self.home, "--check")
        self.assertEqual(0, code)
        self.assertEqual([], report["drift"])
        actions = {change["target"]: change for change in report["changes"]}
        for tool, path in zip(("claude", "codex", "antigravity"), paths):
            self.assertEqual("UNCHANGED", actions[f"{tool} rules"]["action"])
            self.assertIn("canon owns", actions[f"{tool} rules"]["detail"])
            self.assertEqual(before[path], path.read_text(encoding="utf-8"))

        _run(self.home, "--apply", "--uninstall")
        self.assertEqual(before, {path: path.read_text(encoding="utf-8") for path in paths})

    def test_quoted_canon_marker_does_not_transfer_ownership(self) -> None:
        path = self.home / ".codex" / "AGENTS.md"
        original = ("# Personal rules\n"
                    "- documentation quote: <!-- GENERATED from English canonical rules v5.26.0. -->\n")
        path.write_text(original, encoding="utf-8")

        _run(self.home, "--apply")
        installed = path.read_text(encoding="utf-8")
        self.assertTrue(installed.startswith(original.rstrip("\n")))
        self.assertIn(gi.BLOCK_BEGIN, installed)

        _run(self.home, "--apply", "--uninstall")
        self.assertEqual(original, path.read_text(encoding="utf-8"))

    def test_uninstall_restores_the_original_files(self) -> None:
        before = _snapshot(self.home)
        _run(self.home, "--apply")
        _run(self.home, "--apply", "--uninstall")
        after = _snapshot(self.home)
        for name, text in before.items():
            if name.endswith(".json"):
                self.assertEqual(json.loads(text), json.loads(after[name]), name)
            else:
                self.assertEqual(text, after[name], name)
        self.assertFalse((self.home / ".uaos" / "uaos.py").exists())

    def test_uninstall_keeps_a_deny_entry_the_user_had_before(self) -> None:
        settings = self.home / ".claude" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        data["permissions"]["deny"].append("CronCreate")
        settings.write_text(json.dumps(data), encoding="utf-8")
        _run(self.home, "--apply")
        _run(self.home, "--apply", "--uninstall")
        self.assertEqual(["WebFetch", "CronCreate"], json.loads(settings.read_text(encoding="utf-8"))["permissions"]["deny"])

    def test_broken_json_and_hand_disabled_codex_hooks_are_left_alone(self) -> None:
        (self.home / ".claude" / "settings.json").write_text("{broken", encoding="utf-8")
        (self.home / ".codex" / "config.toml").write_text("[features]\ncodex_hooks = false\n", encoding="utf-8")
        _, report = _run(self.home, "--apply")
        actions = {c["target"]: (c["action"], c["detail"]) for c in report["changes"]}
        self.assertEqual("SKIP", actions["claude settings"][0])
        self.assertIn("not valid JSON", actions["claude settings"][1])
        self.assertEqual("SKIP", actions["codex hooks feature"][0])
        self.assertEqual("{broken", (self.home / ".claude" / "settings.json").read_text(encoding="utf-8"))

    def test_missing_tools_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            (home / ".claude").mkdir()
            _, report = _run(home, "--apply")
            actions = {c["target"]: c["action"] for c in report["changes"]}
            self.assertEqual("SKIP", actions["codex (all)"])
            self.assertEqual("SKIP", actions["antigravity (all)"])
            self.assertFalse((home / ".codex").exists())

    def test_hook_commands_run_in_bash_cmd_and_powershell(self) -> None:
        # PowerShell reads a leading quoted string as a value, so a plain path must stay unquoted (Codex b77 review).
        self.assertEqual("C:/Users/Kim/AppData/Local/Programs/Python/Python312/python.exe",
                         gi._arg(r"C:\Users\Kim\AppData\Local\Programs\Python\Python312\python.exe"))
        self.assertEqual('"C:/Program Files/Python312/python.exe"', gi._arg(r"C:\Program Files\Python312\python.exe"))
        _, report = _run(self.home)
        self.assertEqual("", {c["target"]: c["detail"] for c in report["changes"]}["codex hooks"])
        # Only a quoted *first* word breaks PowerShell; a quoted argument after a plain python path is fine.
        spaced = Path(self.temp.name) / "home with space"
        shutil.copytree(self.home, spaced)
        _, report = _run(spaced)
        self.assertEqual("", {c["target"]: c["detail"] for c in report["changes"]}["codex hooks"])
        out = io.StringIO()
        with redirect_stdout(out):
            gi.main(["--home", str(self.home), "--python", "C:/Program Files/Python312/python.exe"])
        details = {c["target"]: c["detail"] for c in json.loads(out.getvalue())["changes"]}
        self.assertIn("PowerShell", details["codex hooks"])
        self.assertIn("PowerShell", details["antigravity hooks"])

    def test_launcher_compiles_for_a_windows_repository_path(self) -> None:
        # Codex U37-W1 on Windows: "C:\\Users\\..." in the launcher docstring raised a unicodeescape SyntaxError.
        from pathlib import PureWindowsPath

        repo = PureWindowsPath(r"C:\Users\Kim\uaos repo\260916_agentic-ai-env-diet")
        text = gi.launcher_text(repo)
        compile(text, "uaos.py", "exec")
        self.assertIn(repr(str(repo)), text)

    def test_extra_rules_file_for_the_canon(self) -> None:
        canon = Path(self.temp.name) / "canon" / "claude.md"
        canon.parent.mkdir()
        canon.write_text("# canon\n", encoding="utf-8")
        _run(self.home, "--apply", "--rules-file", str(canon))
        self.assertIn("<!-- UAOS:END -->", canon.read_text(encoding="utf-8"))

    def test_installed_launcher_runs_the_harness_from_any_folder(self) -> None:
        _run(self.home, "--apply")
        project = Path(self.temp.name) / "other_project"
        (project / ".coord").mkdir(parents=True)
        (project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        (project / "src").mkdir()
        env = {**os.environ, "UAOS_STREAM_AUTOLOG": "0"}
        env.pop("CLAUDE_PROJECT_DIR", None)
        done = subprocess.run(
            [PYTHON, str(self.home / ".uaos" / "uaos.py"), "coord", "presence", "--tool", "codex", "--state", "ACTIVE",
             "--from-hook", "--say", "brief"],
            input=json.dumps({"cwd": str(project / "src")}), capture_output=True, text=True, cwd=str(Path(self.temp.name)),
            env=env, timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertIn("UAOS project other_project", done.stdout)
        self.assertTrue((project / ".coord" / "presence" / "codex.json").is_file())


class SentinelRegistrationTests(unittest.TestCase):
    def test_windows_task_uses_a_short_cmd_and_needs_a_uaos_project(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            project = root / "My Project"
            self.assertIn("NOT_A_UAOS_PROJECT",
                          gi.register_sentinel(project, root, PYTHON, system="Windows", dry_run=False)["error"])
            (project / ".coord").mkdir(parents=True)
            (project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
            calls = []

            def fake_run(command, **kwargs):
                calls.append(command)
                return subprocess.CompletedProcess(command, 0, "SUCCESS", "")

            result = gi.register_sentinel(project, root, PYTHON, run=fake_run, system="Windows", dry_run=False)
            self.assertTrue(result["ok"], result)
            self.assertEqual("UAOS Sentinel My_Project", result["task"])
            create = calls[0]
            self.assertEqual(["schtasks", "/Create"], create[:2])
            self.assertLessEqual(len(create[create.index("/TR") + 1]), 261)
            text = Path(result["cmd_file"]).read_text(encoding="utf-8")
            self.assertIn("coord sentinel --project", text)
            self.assertIn("--loop --interval 60 --ring --write-brief --log", text)
            removed = gi.register_sentinel(project, root, PYTHON, run=fake_run, system="Windows", dry_run=False,
                                           remove=True)
            self.assertEqual(["schtasks", "/Delete"], calls[-1][:2])
            self.assertFalse(Path(removed["cmd_file"]).exists())

    def test_refused_task_gives_advice_and_other_systems_are_told_how(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            project = Path(d)
            (project / ".coord").mkdir()
            (project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
            denied = gi.register_sentinel(project, project, PYTHON, system="Windows", dry_run=False,
                                          run=lambda c, **k: subprocess.CompletedProcess(c, 1, "", "Access is denied."))
            self.assertFalse(denied["ok"])
            self.assertIn("shell:startup", denied["advice"])
            self.assertIn("WINDOWS_ONLY", gi.register_sentinel(project, project, PYTHON, system="Linux")["error"])


class HookContextTests(unittest.TestCase):
    def test_payload_fields_of_the_three_tools(self) -> None:
        self.assertEqual(["/a"], payload_candidates('{"cwd": "/a", "session_id": "x"}'))
        self.assertEqual(["/w1", "/w2"], payload_candidates('{"workspacePaths": ["/w1", "/w2"]}'))
        self.assertEqual(["/w"], payload_candidates('{"workspaceRoots": [{"uri": "file:///w"}]}'))
        self.assertEqual(["C:/work"], payload_candidates('{"workspaceRoots": [{"uri": "file:///C:/work"}]}'))
        self.assertEqual([], payload_candidates("not json"))
        self.assertEqual([], payload_candidates(""))

    def test_project_is_found_by_walking_up_and_outside_projects_stay_silent(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "proj" / ".coord").mkdir(parents=True)
            (root / "proj" / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
            (root / "proj" / "a" / "b").mkdir(parents=True)
            (root / "plain").mkdir()
            self.assertEqual((root / "proj").resolve(), find_project([root / "proj" / "a" / "b"]))
            self.assertIsNone(find_project([root / "plain"]))
            # Antigravity runs the hook inside ~/.gemini/config; the payload still names the workspace.
            payload = json.dumps({"workspacePaths": [str(root / "proj" / "a")]})
            self.assertEqual((root / "proj").resolve(), hook_project(payload, root / "plain", env={}))
            self.assertEqual((root / "proj").resolve(),
                             hook_project("", root / "plain", env={"CLAUDE_PROJECT_DIR": str(root / "proj")}))
            line = brief_line(root / "proj", {"codex": {"state": "ACTIVE"}})
            self.assertIn("inbox 0 (P1 0, RSI reviews 0); desk codex=ACTIVE", line)

    def test_presence_from_hook_never_fails_the_hook(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            out = io.StringIO()
            with redirect_stdout(out), mock.patch("v7_harness.coord.hook_context.read_stdin", return_value="{}"), \
                    mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": ""}):
                code = main(["coord", "presence", "--tool", "claude", "--state", "ACTIVE", "--from-hook",
                             "--project", d, "--say", "none"])
            self.assertEqual((0, ""), (code, out.getvalue()))
            (Path(d) / ".coord").mkdir()
            (Path(d) / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
            out = io.StringIO()
            with redirect_stdout(out), mock.patch("v7_harness.coord.hook_context.read_stdin", return_value="{}"), \
                    mock.patch("v7_harness.coord.presence.mark", side_effect=PermissionError("locked")):
                code = main(["coord", "presence", "--tool", "claude", "--state", "ACTIVE", "--from-hook",
                             "--project", d])
            self.assertEqual(0, code)
            self.assertIn("PermissionError", out.getvalue())
            out = io.StringIO()
            with redirect_stdout(out), mock.patch("v7_harness.coord.hook_context.read_stdin", return_value="{}"):
                main(["coord", "presence", "--tool", "antigravity", "--state", "ACTIVE", "--from-hook",
                      "--project", d, "--say", "empty-json"])
            self.assertEqual("{}\n", out.getvalue())


class CoordInitAndSentinelLoopTests(unittest.TestCase):
    def test_coord_init_prepares_any_project_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".gitignore").write_text("node_modules/", encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(0, main(["coord", "init", "--project", d]))
            self.assertIn("READY", (root / ".coord" / "PLAN.md").read_text(encoding="utf-8"))
            ignore = (root / ".gitignore").read_text(encoding="utf-8")
            self.assertTrue(ignore.startswith("node_modules/\n# UAOS runtime state"))
            self.assertIn(".coord/usage/runs.jsonl", ignore)
            (root / ".coord" / "PLAN.md").write_text("# mine\n", encoding="utf-8")
            out = io.StringIO()
            with redirect_stdout(out):
                main(["coord", "init", "--project", d])
            report = json.loads(out.getvalue())
            self.assertEqual(([], []), (report["created"], report["gitignore_added"]))
            self.assertEqual("# mine\n", (root / ".coord" / "PLAN.md").read_text(encoding="utf-8"))

    def test_second_sentinel_loop_for_one_project_exits(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            pid_file = Path(d) / ".work" / "sentinel" / "loop.pid"
            pid_file.parent.mkdir(parents=True)
            other = subprocess.Popen([PYTHON, "-c", "import time; time.sleep(30)"])
            try:
                pid_file.write_text(str(other.pid), encoding="utf-8")
                out = io.StringIO()
                with redirect_stdout(out):
                    code = main(["coord", "sentinel", "--project", d, "--loop", "--interval", "1",
                                 "--log", str(Path(d) / "s.log")])
                self.assertEqual(0, code)
                self.assertIn("ALREADY_RUNNING", out.getvalue())
                self.assertIn("ALREADY_RUNNING", (Path(d) / "s.log").read_text(encoding="utf-8"))
            finally:
                other.kill()
                other.wait()

    def test_sentinel_log_keeps_one_previous_file(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "s.log"
            log.write_text("x" * 20, encoding="utf-8")
            with redirect_stdout(io.StringIO()), mock.patch("v7_harness.cli.SENTINEL_LOG_MAX_BYTES", 10):
                main(["coord", "sentinel", "--project", d, "--log", str(log)])
            self.assertEqual("x" * 20, (Path(d) / "s.log.1").read_text(encoding="utf-8"))
            self.assertEqual(1, len(log.read_text(encoding="utf-8").splitlines()))


if __name__ == "__main__":
    unittest.main()
