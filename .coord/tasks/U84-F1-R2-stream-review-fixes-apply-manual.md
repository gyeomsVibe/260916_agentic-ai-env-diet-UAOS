```contract
work_id: U84-F1-R2
worker: apply
goal: Fix Codex's two U84 findings: archive path from a worktree, and unlocked shared sample appends.
inputs:
- .coord/PLAN.md sha256=b63d7564a9371d2b879c507135d623f4bc367abef340c124610fd7483bb1a163
- v7_harness/coord/stream.py sha256=ac8ceea4a4bd84d0177acba62aff1355e6d7f52d2345525c090ddac048079bb6
- tests/test_u84_stream_desk.py sha256=926b4a1a541f92b0ff97b967eb176e5643db9e8175ba15444149a31a0bc7fc8b
allow:
- v7_harness/coord/stream.py
- tests/test_u84_stream_desk.py
- .coord/PLAN.md
acceptance: python -m unittest tests.test_u84_stream_desk tests.test_u59_shared_desk tests.test_u15_rollover_and_pending
forbidden: design changes; edits outside allow; weakening or deleting existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the EDIT blocks exactly. Both findings are reproduced by the added tests.

===EDIT: v7_harness/coord/stream.py===
<<<<<<< SEARCH
    return {"archived": len(settled), "kept": len(live), "archive": str(archive_file.relative_to(project))}

=======
    # U84-F1 (Codex REJECT of U84): from a worktree the archive is on the desk, outside `project`; relative_to raised
    # after the stream was already rewritten. relpath resolves from either checkout and is unchanged for a plain one.
    return {"archived": len(settled), "kept": len(live), "archive": os.path.relpath(archive_file, project)}

>>>>>>> REPLACE
===EDIT: v7_harness/coord/stream.py===
<<<<<<< SEARCH
        snapshot = [*existing_events, json.loads(line)]

    # 일이 일어난 자리에서 운용 표본을 남긴다(U15 S14). 잠금 밖에서, 실패해도 무시한다.
    from v7_harness.coord.metrics import maybe_sample

    maybe_sample(project, events=snapshot)
    return event

=======
        snapshot = [*existing_events, json.loads(line)]
        # 일이 일어난 자리에서 운용 표본을 남긴다(U15 S14). 실패해도 무시한다.
        # U84-F1 (Codex REJECT of U84): the desk and its worktrees share one samples file, so it is written under the
        # stream lock; unlocked, a concurrent Windows append lost 1 of 48 rows in 1 of 8 runs on 12 busy cores.
        from v7_harness.coord.metrics import maybe_sample

        maybe_sample(project, events=snapshot)
    return event

>>>>>>> REPLACE
===EDIT: .coord/PLAN.md===
<<<<<<< SEARCH
| U84 | DONE-DELEGATED (Codex LIMITED 중 Claude 권한대행 2026-09-29 — Codex 복귀 시 재검토) | claude(대행 설계) · apply(0토큰) | 작업 기록 경로 분리 수정: 워크트리에서 `coord log`·pilot 사건이 그 워크트리의 무시된(gitignored) `.coord/stream`에 쌓여(09-20~09-29 76건) 데스크 codex_brief에 보이지 않았다(`coord deliver`는 U59로 데스크에 감). U59(presence·우편)·U72-L(장부)와 같은 원인 3번째 표면. `stream_dir`과 운용 표본(metrics)을 `shared_desk`로 보낸다. — `v7_harness/coord/stream.py`, `v7_harness/coord/metrics.py`, `tests/test_u84_stream_desk.py` |

=======
| U84 | DONE-DELEGATED (Codex LIMITED 중 Claude 권한대행 2026-09-29 — Codex 복귀 시 재검토) | claude(대행 설계) · apply(0토큰) | 작업 기록 경로 분리 수정: 워크트리에서 `coord log`·pilot 사건이 그 워크트리의 무시된(gitignored) `.coord/stream`에 쌓여(09-20~09-29 76건) 데스크 codex_brief에 보이지 않았다(`coord deliver`는 U59로 데스크에 감). U59(presence·우편)·U72-L(장부)와 같은 원인 3번째 표면. `stream_dir`과 운용 표본(metrics)을 `shared_desk`로 보낸다. — `v7_harness/coord/stream.py`, `v7_harness/coord/metrics.py`, `tests/test_u84_stream_desk.py` |
| U84-F1 | DONE-DELEGATED (Codex LIMITED 중 Claude 권한대행 2026-09-29 — Codex 복귀 시 재검토) | claude(대행 설계) · apply(0토큰) · codex(반례 제공) | U84 Codex REJECT 2건 수정(`.work/u84_verdict/verdict.txt`): (1) 워크트리에서 `archive_settled`가 데스크를 바꾼 뒤 `relative_to`로 실패 → `os.path.relpath`(재현 1/1), (2) 공유된 표본 파일을 잠금 밖에서 동시 기록 → 스트림 잠금 안으로(12코어 부하 8회 중 1회 48→47 재현). — `v7_harness/coord/stream.py`, `tests/test_u84_stream_desk.py` |

>>>>>>> REPLACE
===FILE: tests/test_u84_stream_desk.py===
"""U84: a linked worktree's `coord log` and pilot events land in the main checkout's stream (the desk).

Seen 2026-09-29: the acting conductor ran `coord log --project .` in `.claude/worktrees/<name>`. The event went to that
worktree's gitignored `.coord/stream`, while `coord deliver` from the same folder reached the desk (U59). 76 events
from 2026-09-20 to 09-29 were stranded there, so the desk's codex_brief (brief.py reads the stream) never showed the
acting work Codex must re-review. U59 moved presence and mail, U72-L the ledger; the stream is the same runtime state.
"""

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path

from v7_harness.cli import main
from v7_harness.coord.stream import append_event, archive_settled, read_events, stream_dir

REPO = Path(__file__).resolve().parents[1]


def samples_path(project: Path) -> Path:
    return stream_dir(project) / "metrics" / "samples.jsonl"


def _plan(root: Path) -> None:
    (root / ".coord").mkdir(parents=True, exist_ok=True)
    (root / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")


class StreamDeskTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.main = base / "repo"
        self.tree = self.main / ".claude" / "worktrees" / "w1"
        _plan(self.main)
        _plan(self.tree)
        (self.main / ".git" / "worktrees" / "w1").mkdir(parents=True)
        (self.tree / ".git").write_text(f"gitdir: {(self.main / '.git' / 'worktrees' / 'w1').as_posix()}\n",
                                        encoding="utf-8")

    def test_coord_log_from_a_worktree_lands_on_the_desk(self):
        with redirect_stdout(io.StringIO()):
            code = main(["coord", "log", "--project", str(self.tree), "--actor", "claude", "--kind", "NOTE",
                         "--step", "U84", "--summary", "acting work for Codex re-review"])
        self.assertEqual(0, code)
        self.assertFalse((self.tree / ".coord" / "stream").exists(), "the event was stranded in the worktree")
        events = read_events(self.main)
        self.assertEqual(["U84"], [event["step"] for event in events])

    def test_both_checkouts_read_one_stream(self):
        append_event(self.tree, actor="claude", kind="NOTE", step="W", summary="from the worktree")
        append_event(self.main, actor="claude", kind="NOTE", step="M", summary="from the desk")
        self.assertEqual(stream_dir(self.main), stream_dir(self.tree))
        self.assertEqual(read_events(self.main), read_events(self.tree))
        self.assertEqual({"W", "M"}, {event["step"] for event in read_events(self.main)})

    def test_archive_from_a_worktree_reports_a_path_that_resolves(self):
        # U84-F1 (Codex REJECT of U84): the archive moved to the desk, then relative_to(worktree) raised after the
        # stream had already been rewritten.
        append_event(self.tree, actor="codex", kind="VERDICT", step="V", summary="settled",
                     evidence={"cmd": "unittest", "exit": 0}, now=datetime.now().astimezone() - timedelta(minutes=1))
        append_event(self.tree, actor="claude", kind="NOTE", step="L", summary="live")  # a minute later: stays live
        report = archive_settled(self.tree)
        self.assertEqual((1, 1), (report["archived"], report["kept"]))
        self.assertTrue((self.tree / report["archive"]).is_file())
        self.assertEqual(["L"], [event["step"] for event in read_events(self.main)])

    def test_parallel_events_from_both_checkouts_keep_every_sample(self):
        # U84-F1 (Codex REJECT of U84): samples from the desk and its worktrees now share one file, so they are
        # written under the stream lock. 6 processes x 8 events with the 10-minute spacing off must leave 48 rows.
        child = (
            "import sys\n"
            "from pathlib import Path\n"
            "from v7_harness.coord import metrics\n"
            "from v7_harness.coord.stream import append_event\n"
            "metrics.MIN_INTERVAL_S = -1  # sample every event\n"
            "for n in range(8):\n"
            "    append_event(Path(sys.argv[1]), actor='claude', kind='NOTE', step=f'{sys.argv[2]}-{n}', summary='p')\n"
        )
        procs = [subprocess.Popen([sys.executable, "-c", child, str(self.tree if i % 2 else self.main), f"p{i}"],
                                  cwd=REPO) for i in range(6)]
        self.assertEqual([0] * 6, [proc.wait(timeout=120) for proc in procs])
        self.assertEqual(48, len(read_events(self.main)))
        rows = samples_path(self.main).read_text(encoding="utf-8").splitlines()
        self.assertEqual(48, len(rows), "a concurrent sample append was lost or duplicated")
        self.assertEqual(48, len([json.loads(row) for row in rows]))

    def test_a_plain_project_keeps_its_own_stream(self):
        plain = Path(self._tmp.name) / "plain"
        _plan(plain)
        append_event(plain, actor="claude", kind="NOTE", step="P", summary="plain folder")
        self.assertEqual(plain / ".coord" / "stream", stream_dir(plain))
        self.assertEqual(["P"], [event["step"] for event in read_events(plain)])


if __name__ == "__main__":
    unittest.main()
===END===

## Output

- Reply with ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.
