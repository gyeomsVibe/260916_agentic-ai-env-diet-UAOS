"""U349 Phase 0: tests for v7_harness.rsi_selftest (deterministic, zero paid calls, no writes outside temp dirs)."""
from __future__ import annotations

import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from v7_harness import rsi, rsi_selftest as st

REPO = Path(__file__).resolve().parent.parent


def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            s = p.stat()
            out[p.relative_to(root).as_posix()] = (s.st_size, s.st_mtime_ns)
    return out


class T2EvaluatorTests(unittest.TestCase):
    def test_real_patterns_pass_and_digest_is_stable(self) -> None:
        a = st.t2_evaluator_integrity(REPO)
        b = st.t2_evaluator_integrity(REPO)
        self.assertEqual(st.PASS, a.status, a.detail)
        self.assertEqual(a.data["digest"], b.data["digest"])
        self.assertEqual(st.patterns_digest(rsi.EVALUATOR_PATTERNS), a.data["digest"])
        self.assertGreater(a.data["files"], 0)

    def test_digest_is_order_independent_but_content_sensitive(self) -> None:
        self.assertEqual(st.patterns_digest(["a", "b"]), st.patterns_digest(["b", "a"]))
        self.assertNotEqual(st.patterns_digest(["a", "b"]), st.patterns_digest(["a", "c"]))

    def test_red_removing_a_required_evaluator_fails(self) -> None:
        pats = tuple(p for p in rsi.EVALUATOR_PATTERNS if p != "v7_harness/calculator_gate.py")
        r = st.t2_evaluator_integrity(REPO, patterns=pats)
        self.assertEqual(st.FAIL, r.status)
        self.assertIn("v7_harness/calculator_gate.py", r.data["missing"])

    def test_red_target_overlapping_an_evaluator_fails(self) -> None:
        r = st.t2_evaluator_integrity(REPO, target_patterns=("tests/test_x.py",))
        self.assertEqual(st.FAIL, r.status)
        self.assertEqual(["tests/test_x.py"], r.data["overlap"])

    def test_baseline_match_drift_and_unreadable(self) -> None:
        good = st.t2_evaluator_integrity(REPO)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "b.json"
            base.write_text(json.dumps({"digest": good.data["digest"], "files": {}}), encoding="utf-8")
            self.assertEqual(st.PASS, st.t2_evaluator_integrity(REPO, base).status)
            base.write_text(json.dumps({"digest": "0" * 64, "files": {}}), encoding="utf-8")
            self.assertEqual(st.WARN, st.t2_evaluator_integrity(REPO, base).status)
            f = next(iter(sorted(k for k in st.t2_evaluator_integrity(REPO).data.keys())), None)  # noqa: F841
            base.write_text("not json", encoding="utf-8")
            self.assertEqual(st.WARN, st.t2_evaluator_integrity(REPO, base).status)
            self.assertEqual(st.WARN, st.t2_evaluator_integrity(REPO, Path(tmp) / "missing.json").status)

    def test_red_target_glob_covering_a_literal_evaluator_fails(self) -> None:
        # U355-C review: a widened target glob must be caught even though the evaluator entry is a literal path.
        r = st.t2_evaluator_integrity(REPO, target_patterns=("v7_harness/*",))
        self.assertEqual(st.FAIL, r.status)
        self.assertEqual(["v7_harness/*"], r.data["overlap"])

    def test_baseline_null_files_or_deleted_evaluator_warns(self) -> None:
        good = st.t2_evaluator_integrity(REPO)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "b.json"
            base.write_text(json.dumps({"digest": good.data["digest"], "files": None}), encoding="utf-8")
            self.assertEqual(st.WARN, st.t2_evaluator_integrity(REPO, base).status)
            gone = {"v7_harness/__deleted_evaluator__.py": "0" * 64}
            base.write_text(json.dumps({"digest": good.data["digest"], "files": gone}), encoding="utf-8")
            r = st.t2_evaluator_integrity(REPO, base)
            self.assertEqual(st.WARN, r.status)
            self.assertEqual(list(gone), r.data["removed_files"])


class T4GrantCanaryTests(unittest.TestCase):
    def test_legacy_grant_canary_passes_on_this_tree(self) -> None:
        r = st.t4_legacy_grant_canary()
        self.assertIn(r.status, (st.PASS,), r.detail)
        self.assertEqual("ALLOW", r.data["observed"]["push_agy"])
        self.assertEqual("DENY", r.data["observed"]["push_main"])

    def test_red_grant_that_stops_allowing_agy_fails(self) -> None:
        bad = dict(st.LEGACY_GRANT_2026_10_04, branches=["claude/*"])
        r = st.t4_legacy_grant_canary(bad)
        self.assertEqual(st.FAIL, r.status)
        self.assertIn("agy/*", r.detail)

    def test_red_grant_without_never_main_fails(self) -> None:
        bad = dict(st.LEGACY_GRANT_2026_10_04, never=[], branches=["*"])
        r = st.t4_legacy_grant_canary(bad)
        self.assertEqual(st.FAIL, r.status)
        self.assertIn("main", r.detail)

    def test_action_scope_is_checked_when_push_check_has_it(self) -> None:
        from v7_harness.coord import stop_gate

        def fake(project, branch, force=False, action="push"):
            return {"decision": "ALLOW"}  # a regression: the legacy grant would now allow merge
        with mock.patch.object(stop_gate, "push_check", fake):
            r = st.t4_legacy_grant_canary()
        self.assertEqual(st.FAIL, r.status)
        self.assertIn("action=merge", r.detail)

    def test_red_force_push_allowed_fails(self) -> None:
        # U355-C review: the force canary must really pass force=True and assert DENY.
        from v7_harness.coord import stop_gate

        real = stop_gate.push_check

        def fake(project, branch, force=False, **kwargs):
            return {"decision": "ALLOW"} if force else real(project, branch, **kwargs)
        with mock.patch.object(stop_gate, "push_check", fake):
            r = st.t4_legacy_grant_canary()
        self.assertEqual(st.FAIL, r.status)
        self.assertIn("force push", r.detail)
        self.assertEqual("DENY", st.t4_legacy_grant_canary().data["observed"]["force_push"])

    def test_merge_default_that_enforces_grant_fails(self) -> None:
        from v7_harness.coord import merge_route

        def merge(project, pr, head, verdict, *, require_grant=None):  # the pre-U348-R3 default
            return {}
        with mock.patch.object(merge_route, "merge", merge):
            r = st.t4_legacy_grant_canary()
        self.assertEqual(st.FAIL, r.status)
        self.assertIn("require_grant", r.detail)

    def test_fixture_is_removed_and_project_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            before = set(os.listdir(tmp))
            st.t4_legacy_grant_canary(tmp_parent=Path(tmp))
            self.assertEqual(before, set(os.listdir(tmp)))


class T5Tests(unittest.TestCase):
    def test_executables_required_vs_optional(self) -> None:
        only_git = lambda name: "/bin/git" if name == "git" else None  # noqa: E731
        self.assertEqual(st.FAIL, st.t5a_executables(only_git).status)
        no_gh = lambda name: None if name in ("gh", "uv") else f"/bin/{name}"  # noqa: E731
        r = st.t5a_executables(no_gh)
        self.assertEqual(st.WARN, r.status)
        self.assertIn("gh", r.detail)
        self.assertEqual(st.PASS, st.t5a_executables(lambda n: f"/bin/{n}").status)

    def test_ollama_unreachable_and_reachable_and_inventory(self) -> None:
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                self.assertEqual(st.PASS, st.t5b_ollama(Path(tmp), ("127.0.0.1", port)).status)
                db = Path(tmp) / ".coord" / "pilot"
                db.mkdir(parents=True)
                import sqlite3

                conn = sqlite3.connect(db / "coord.sqlite3")
                conn.execute("CREATE TABLE circuit_state (provider TEXT)")
                conn.execute("INSERT INTO circuit_state VALUES ('ollama')")
                conn.commit()
                conn.close()
                r = st.t5b_ollama(Path(tmp), ("127.0.0.1", port))
                self.assertEqual({"circuit_tables": {"circuit_state": 1}}, {"circuit_tables": r.data["circuit_tables"]})
        finally:
            srv.close()
        with tempfile.TemporaryDirectory() as tmp:
            r = st.t5b_ollama(Path(tmp), ("127.0.0.1", port), timeout=0.2)
            self.assertEqual(st.WARN, r.status)
            self.assertIsNone(r.data["circuit_tables"])
            self.assertFalse((Path(tmp) / ".coord").exists(), "inventory must not create the database")

    def test_footprint_and_hygiene(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proj, home = Path(tmp) / "p", Path(tmp) / "h"
            proj.mkdir()
            home.mkdir()
            self.assertEqual(st.SKIP, st.t5c_context_footprint(proj, home).status)
            (proj / "AGENTS.md").write_text("12345", encoding="utf-8")
            (home / ".claude").mkdir()
            (home / ".claude" / "CLAUDE.md").write_text("123", encoding="utf-8")
            r = st.t5c_context_footprint(proj, home)
            self.assertEqual(8, r.data["total"])
            for i in range(31):
                (proj / ".work" / f"wt_{i}").mkdir(parents=True)
            h = st.t5d_hygiene(proj, home)
            self.assertEqual(st.WARN, h.status)
            self.assertEqual(31, h.data["work_worktrees"])
            self.assertEqual(31, len(list((proj / ".work").iterdir())), "hygiene must not delete")


class T1AndDriverTests(unittest.TestCase):
    def test_t1_reports_drift_for_empty_home_and_skips_on_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            r = st.t1_global_drift(Path(tmp), REPO)
            self.assertIn(r.status, (st.WARN, st.PASS), r.detail)
            self.assertGreater(r.data.get("total", 0), 0)
            self.assertEqual([], os.listdir(tmp), "plan must not write into home")
        with mock.patch("v7_harness.global_install.plan", side_effect=RuntimeError("boom")):
            self.assertEqual(st.SKIP, st.t1_global_drift(Path("."), REPO).status)

    def test_cli_json_exit_code_and_zero_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proj, home = Path(tmp) / "p", Path(tmp) / "h"
            proj.mkdir()
            home.mkdir()
            before = (_snapshot(proj), _snapshot(home))
            out = io.StringIO()
            with redirect_stdout(out):
                rc = st.main(["--project", str(proj), "--home", str(home), "--json"])
            report = json.loads(out.getvalue())
            self.assertEqual(0 if report["ok"] else 1, rc)
            self.assertEqual(0, report["paid_tokens"])
            self.assertEqual(["T1", "T2", "T4", "T5a", "T5b", "T5c", "T5d"], [p["id"] for p in report["probes"]])
            self.assertEqual(before, (_snapshot(proj), _snapshot(home)))

    def test_cli_exit_1_when_any_probe_fails(self) -> None:
        fail = st.Probe("T2", st.FAIL, "x")
        with mock.patch.object(st, "run", return_value=[fail]):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(1, st.main(["--project", "."]))

    def test_module_runs_as_python_dash_m(self) -> None:
        done = subprocess.run([sys.executable, "-m", "v7_harness.rsi_selftest", "--json", "--home", tempfile.gettempdir(),
                               "--project", str(REPO)], cwd=str(REPO), capture_output=True, timeout=120)
        self.assertIn(done.returncode, (0, 1), done.stderr.decode("utf-8", "replace")[:300])
        self.assertEqual(0, json.loads(done.stdout.decode("utf-8"))["paid_tokens"])


if __name__ == "__main__":
    unittest.main()
