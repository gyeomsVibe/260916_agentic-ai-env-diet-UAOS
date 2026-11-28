"""MODE-SDT acceptance: `coord mode --show` prints SOLO/DUO/TRIO/HALT from presence; UNKNOWN fails closed (docs/140)."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness import cli
from v7_harness.coord import presence
from v7_harness.coord.collab_mode import collab_mode


class CollabModeTest(unittest.TestCase):
    def test_counts_active_tools(self) -> None:
        all_on = {"codex": "ACTIVE", "claude": "ACTIVE", "antigravity": "ACTIVE"}
        self.assertEqual(collab_mode(all_on)["mode"], "TRIO")
        self.assertEqual(collab_mode(all_on)["regime"], "TRIO")
        duo = collab_mode({"codex": "ACTIVE", "claude": "ACTIVE", "antigravity": "LIMITED"})
        self.assertEqual((duo["mode"], duo["regime"], duo["fail_closed"]), ("DUO", "DUO_CODEX_CLAUDE", False))
        solo = collab_mode({"codex": "ABSENT", "claude": "active", "antigravity": "LIMITED"})
        self.assertEqual((solo["mode"], solo["regime"], solo["fail_closed"]), ("SOLO", "SOLO_CLAUDE", False))

    def test_unknown_never_counts_and_fails_closed(self) -> None:
        r = collab_mode({"claude": "ACTIVE", "codex": "LIMITED", "antigravity": "UNKNOWN"})
        self.assertEqual((r["mode"], r["unknown"], r["fail_closed"]), ("SOLO", ["antigravity"], True))
        for bad in (None, {}, {"codex": "bogus"}, {"claude": True}, "ACTIVE"):
            r = collab_mode(bad)  # type: ignore[arg-type]
            self.assertEqual(r["mode"], "HALT")
            self.assertTrue(r["fail_closed"])
            self.assertEqual(r["regime"], "LOCAL_ONLY")

    def test_never_self_approves(self) -> None:
        self.assertIs(collab_mode({"claude": "ACTIVE"})["self_approval"], False)

    def _run(self, project: Path) -> tuple[int, dict]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.cmd_coord_collab_mode(argparse.Namespace(project=str(project), show=True))
        return code, json.loads(out.getvalue())

    def test_cli_empty_desk_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, data = self._run(Path(tmp))
        self.assertEqual((code, data["mode"], data["fail_closed"]), (1, "HALT", True))
        self.assertEqual(data["budget_mode"], "token-thrift")

    def test_cli_reads_presence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            presence.mark(project, "claude", "ACTIVE")
            presence.mark(project, "antigravity", "ACTIVE")
            presence.mark(project, "codex", "LIMITED")
            code, data = self._run(project)
        self.assertEqual((code, data["mode"], data["regime"]), (0, "DUO", "DUO_CLAUDE_AGY"))

    def test_regime_names_match_situational_ops(self) -> None:
        from v7_harness.coord import collab_mode as cm, situational_ops
        self.assertEqual(cm._REGIME, situational_ops._BY_ALIVE)

    def test_cli_presence_error_fails_closed(self) -> None:
        def boom(*_a, **_k):
            raise OSError("desk unreadable")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(presence, "read_all", boom):
            code, data = self._run(Path(tmp))
        self.assertEqual((code, data["mode"], data["fail_closed"]), (1, "HALT", True))

    def test_cli_budget_mode_fallback_is_flagged(self) -> None:
        from v7_harness.coord import mode as budget
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(budget, "current_mode", side_effect=ValueError):
            _code, data = self._run(Path(tmp))
        self.assertEqual((data["budget_mode"], data["budget_mode_fallback"]), ("token-thrift", True))

    def test_mode_runs_on_shared_desk(self) -> None:
        self.assertIn("mode", cli._DESK_COMMANDS)

    def test_parser_wires_show(self) -> None:
        args = cli.build_parser().parse_args(["coord", "mode", "--show"])
        self.assertIs(args.func, cli.cmd_coord_collab_mode)
        self.assertTrue(args.show)


if __name__ == "__main__":
    unittest.main()
