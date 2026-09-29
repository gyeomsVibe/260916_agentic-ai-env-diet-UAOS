"""U15 S14: 사건이 기록될 때 운용 표본도 함께 남긴다.

하루 운용 집계에서 23.4시간 공백이 났다. 수집이 Claude 세션의 타이머에 묶여 있어서
세션이 쉬면 표본도 멈췄기 때문이다. OS 예약 작업은 시스템 설정 변경이라 쓰지 않고,
대신 **일이 일어날 때** 표본을 남긴다. 사건이 없으면 표본도 없지만, 그 구간은 실제로
아무 일도 없던 구간이므로 공백이 곧 사실이 된다.

- 위치: `.coord/stream/metrics/samples.jsonl`. 스트림 폴더 아래라 원본 매니페스트에서
  빠지고(파일럿 무해), 하위 폴더라 사건 읽기(`*.jsonl`)에도 섞이지 않는다.
- 빈도: 10분에 1건. 사건이 몰려도 표본이 폭주하지 않는다.
- 실패해도 사건 기록을 막지 않는다. 표본은 부산물이다.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

MIN_INTERVAL_S = 600


def samples_path(project: Path) -> Path:
    return project / ".coord" / "stream" / "metrics" / "samples.jsonl"


def _brief_stats(project: Path) -> dict[str, int]:
    brief = project / ".coord" / "codex_brief.md"
    if not brief.is_file():
        return {"brief_chars": 0, "brief_lines": 0}
    text = brief.read_text(encoding="utf-8")
    return {"brief_chars": len(text), "brief_lines": len(text.splitlines())}


def _cursor_stats(project: Path) -> dict[str, Any]:
    cursor = project / ".work" / "coord" / "codex_notify_cursor.json"
    if not cursor.is_file():
        return {"deliveries_today": 0, "last_sent_at": ""}
    try:
        data = json.loads(cursor.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"deliveries_today": 0, "last_sent_at": ""}
    return {"deliveries_today": int(data.get("sent_today") or 0), "last_sent_at": data.get("last_sent_at", "")}


def maybe_sample(project: Path, *, events: list[dict[str, Any]], now: float | None = None) -> bool:
    """마지막 표본에서 10분이 지났으면 한 줄을 남긴다. 남겼으면 True."""
    try:
        from .hook_context import shared_desk

        # U84: the sample, the brief and the cursor are desk state; a linked worktree's event samples the desk (U59).
        project = shared_desk(Path(project))
        path = samples_path(project)
        moment = time.time() if now is None else now
        if path.is_file() and moment - path.stat().st_mtime < MIN_INTERVAL_S:
            return False
        by_kind: dict[str, int] = {}
        for event in events:
            kind = str(event.get("kind", "?"))
            by_kind[kind] = by_kind.get(kind, 0) + 1
        row = {
            "ts": datetime.fromtimestamp(moment).astimezone().isoformat(timespec="seconds"),
            "source": "event",
            "events_total": len(events),
            "events_by_kind": dict(sorted(by_kind.items())),
            **_brief_stats(project),
            **_cursor_stats(project),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        os.utime(path, (moment, moment))
        return True
    except Exception:  # noqa: BLE001 - 표본은 부산물이다. 사건 기록을 막지 않는다.
        return False
