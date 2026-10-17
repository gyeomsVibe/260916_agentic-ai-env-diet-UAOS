"""U211: a hook whose cwd is inside a pilot stage (`<work-dir>/stage/<task>/`) must resolve to the real project desk.

Receipts (2026-10-18): U209-R2B APPROVAL_MISMATCH and U210 run3 stage pollution. The stage holds a copied `.coord`
but no `.git`, so the U182 nested-project rule and the PLAN walk took the stage for its own project, wrote presence and
stall files into it, and pilot approval then replayed a stage that had changed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from v7_harness.coord.hook_context import find_project, shared_desk
from v7_harness.coord.next_card import coord_root


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "proj"
    (root / ".coord").mkdir(parents=True)
    (root / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    work = root / ".work" / "x"
    (work / "runs" / "T").mkdir(parents=True)
    stage = work / "stage" / "T"
    (stage / ".coord").mkdir(parents=True)
    (stage / ".coord" / "PLAN.md").write_text("# plan copy\n", encoding="utf-8")
    (stage / "v7_harness").mkdir()
    return root.resolve(), stage


def test_find_project_from_stage_resolves_real_project(tmp_path):
    root, stage = _repo(tmp_path)
    assert find_project([stage]) == root
    assert find_project([stage / "v7_harness"]) == root


def test_shared_desk_maps_stage_to_real_project(tmp_path):
    root, stage = _repo(tmp_path)
    assert shared_desk(stage) == root


def test_coord_root_of_stage_is_real_project(tmp_path):
    root, stage = _repo(tmp_path)
    assert coord_root(stage).resolve() == root


def test_stage_without_runs_is_still_a_nested_project(tmp_path):
    # U182 stays: a folder named `stage/<x>` whose parent has no `runs/` is not a pilot stage.
    root = tmp_path / "outer"
    nested = root / "stage" / "app"
    (nested / ".coord").mkdir(parents=True)
    (nested / ".coord" / "PLAN.md").write_text("# nested\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    assert find_project([nested]) == nested.resolve()
    assert coord_root(nested) == nested
