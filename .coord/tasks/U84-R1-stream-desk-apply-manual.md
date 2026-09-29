```contract
work_id: U84-R1
worker: apply
goal: Route the coord event stream of a linked worktree to the main checkout's desk, like presence, mail and ledger.
inputs:
- .coord/PLAN.md sha256=48d70a109b255fd59a54ca7c000a3cf35122ffa9b3fc714f0387cf21f4a54490
- v7_harness/coord/stream.py sha256=9e2a655c5ebcf480bb2869ff4d68709179bf84cd44faac8117fb50ed6780187d
- v7_harness/coord/metrics.py sha256=d65b5e6f4f80befd1b8efaea51617b5a5959f0735b26c4616d187e86dcf05be8
- v7_harness/coord/hook_context.py sha256=09059a3e8286b098363664157e6bed879423ff74e58321c644e5583c93c95aa4
allow:
- v7_harness/coord/stream.py
- v7_harness/coord/metrics.py
- tests/test_u84_stream_desk.py
- .coord/PLAN.md
acceptance: python -m unittest tests.test_u84_stream_desk tests.test_u59_shared_desk
forbidden: design changes; edits outside allow; weakening or deleting existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the EDIT blocks exactly. The stranded-event receipt becomes tests/test_u84_stream_desk.py.

===EDIT: v7_harness/coord/stream.py===
<<<<<<< SEARCH
def stream_dir(project: Path) -> Path:
    return project / ".coord" / "stream"

=======
def stream_dir(project: Path) -> Path:
    """U84: one stream per repository. A linked worktree's events belong to the main checkout's desk (U59).

    Seen 2026-09-29: `coord log` in `.claude/worktrees/<name>` wrote to that worktree's gitignored stream while
    `coord deliver` from the same folder reached the desk, so 76 acting events never reached the desk's codex_brief.
    """
    from .hook_context import shared_desk

    return shared_desk(Path(project)) / ".coord" / "stream"

>>>>>>> REPLACE
===EDIT: v7_harness/coord/metrics.py===
<<<<<<< SEARCH
    """마지막 표본에서 10분이 지났으면 한 줄을 남긴다. 남겼으면 True."""
    try:
        path = samples_path(project)

=======
    """마지막 표본에서 10분이 지났으면 한 줄을 남긴다. 남겼으면 True."""
    try:
        from .hook_context import shared_desk

        # U84: the sample, the brief and the cursor are desk state; a linked worktree's event samples the desk (U59).
        project = shared_desk(Path(project))
        path = samples_path(project)

>>>>>>> REPLACE
===EDIT: .coord/PLAN.md===
<<<<<<< SEARCH
| U83 | DONE-DELEGATED (Codex LIMITED 중 Claude 권한대행 2026-09-29 — Codex 복귀 시 재검토) | claude(대행 설계) · apply(0토큰) · codex(반례 제공) | 복구 잠금 경쟁 근본 수정(Codex REJECT of U49-G1R, `.work/u49g1r_verdict/verdict.txt`): 60초 넘게 멈춘 보유자의 `.recover` 파일을 다른 호출자가 나이(mtime)로 빼앗고, 재개한 보유자가 무조건 unlink로 새 보유자의 잠금을 지웠다(G1과 같은 원인 2회째). 잠금을 OS 바이트 잠금(Windows msvcrt.locking, POSIX flock)으로 바꿔 보유자 종료·충돌 시 OS가 풀고, 나이 기반 탈취와 unlink를 없앴다. — `v7_harness/coord/deliver.py`, `tests/test_u83_recover_lock.py` |

=======
| U83 | DONE-DELEGATED (Codex LIMITED 중 Claude 권한대행 2026-09-29 — Codex 복귀 시 재검토) | claude(대행 설계) · apply(0토큰) · codex(반례 제공) | 복구 잠금 경쟁 근본 수정(Codex REJECT of U49-G1R, `.work/u49g1r_verdict/verdict.txt`): 60초 넘게 멈춘 보유자의 `.recover` 파일을 다른 호출자가 나이(mtime)로 빼앗고, 재개한 보유자가 무조건 unlink로 새 보유자의 잠금을 지웠다(G1과 같은 원인 2회째). 잠금을 OS 바이트 잠금(Windows msvcrt.locking, POSIX flock)으로 바꿔 보유자 종료·충돌 시 OS가 풀고, 나이 기반 탈취와 unlink를 없앴다. — `v7_harness/coord/deliver.py`, `tests/test_u83_recover_lock.py` |
| U84 | DONE-DELEGATED (Codex LIMITED 중 Claude 권한대행 2026-09-29 — Codex 복귀 시 재검토) | claude(대행 설계) · apply(0토큰) | 작업 기록 경로 분리 수정: 워크트리에서 `coord log`·pilot 사건이 그 워크트리의 무시된(gitignored) `.coord/stream`에 쌓여(09-20~09-29 76건) 데스크 codex_brief에 보이지 않았다(`coord deliver`는 U59로 데스크에 감). U59(presence·우편)·U72-L(장부)와 같은 원인 3번째 표면. `stream_dir`과 운용 표본(metrics)을 `shared_desk`로 보낸다. — `v7_harness/coord/stream.py`, `v7_harness/coord/metrics.py`, `tests/test_u84_stream_desk.py` |

>>>>>>> REPLACE
===FILE: tests/test_u84_stream_desk.py===
"""U84: a linked worktree's `coord log` and pilot events land in the main checkout's stream (the desk).

Seen 2026-09-29: the acting conductor ran `coord log --project .` in `.claude/worktrees/<name>`. The event went to that
worktree's gitignored `.coord/stream`, while `coord deliver` from the same folder reached the desk (U59). 76 events
from 2026-09-20 to 09-29 were stranded there, so the desk's codex_brief (brief.py reads the stream) never showed the
acting work Codex must re-review. U59 moved presence and mail, U72-L the ledger; the stream is the same runtime state.
"""

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from v7_harness.cli import main
from v7_harness.coord.stream import append_event, read_events, stream_dir


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
