```contract
work_id: U127-L1
worker: local
goal: windows.py gains window_entry, record_window and a PermissionError retry for parallel record writers (U127)
inputs:
- .work/u127_spec_windows.md sha256=552cba9123088cb386ce1af3f11a60ba6e47222ffcef8af76cd76df066e68836
allow:
- v7_harness/coord/windows.py
acceptance: python -m unittest tests.test_u127_agy_card_window.CardWindowRecordTest tests.test_u114_windows tests.test_u115_card_window_route tests.test_u115_claude_full_session
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

# Work order: read and write one tool's window in a card record (U127, part 1)

- Target file: `v7_harness/coord/windows.py`
- Anchors: `import subprocess`, `CLAUDE_TIMEOUT_S`, `_load`, `window_for`

Make four ===EDIT blocks in this order. Change nothing else. Leave two blank lines between functions.

Block 1. SEARCH the two lines `import subprocess` and `import time`; REPLACE with `import subprocess`, `import threading`, `import time`.

Block 2. SEARCH the line `CLAUDE_TIMEOUT_S = 120`; REPLACE with that line followed by:

    # U127: a record read or replace retries with 10 ms, 20 ms, ... back-off (about 2 s over 20 tries) while a parallel
    # writer swaps it; the parallel test (8 threads x 10 writes) hit PermissionError on the first try without it.
    RECORD_TRIES = 20

Block 3. SEARCH the two lines of `_load`:

    def _load(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}

REPLACE with a new function `_retry` first, then `_load` changed to use it:
- `def _retry(op: Callable[[], Any]) -> Any:` with docstring
  `"""U127: Windows refuses to open or replace a record while a parallel writer swaps it; retry with back-off."""`
  It loops `for attempt in range(RECORD_TRIES)`: `return op()`; on `PermissionError`, re-raise when
  `attempt == RECORD_TRIES - 1`, otherwise `time.sleep(0.01 * (attempt + 1))`.
- `_load` keeps its signature and returns `_retry(lambda: json.loads(path.read_text(encoding="utf-8"))) if path.is_file() else {}`.

Block 4. SEARCH the two lines of `window_for`:

    def window_for(project: Path, card: str, tool: str) -> str | None:
        return _load(_record_path(project, card)).get("tools", {}).get(tool, {}).get("id")

REPLACE with those same two lines followed by two new functions:

1. `window_entry(project: Path, card: str, tool: str) -> dict[str, Any]`
   - Docstring: `"""U127: the card's window entry for one tool ({} when there is none)."""`
   - Return `dict(_load(_record_path(project, card)).get("tools", {}).get(tool) or {})`.

2. `record_window(project: Path, card: str, tool: str, window_id: str, *, now: float | None = None, **extra: Any) -> dict[str, Any]`
   (split the signature over two lines after `now: float | None = None,`)
   - Docstring: `"""U127: write one tool's window for a card and keep the other tools' windows (the U114 record format)."""`
   - `path = _record_path(project, card)` (this raises ValueError for a bad card id) and `record = _load(path)`.
   - `entry = {"id": window_id, "opened_at": time.time() if now is None else now, **extra}`.
   - `old = record.get("tools", {}).get(tool) or {}`; if `old.get("id") == window_id and "opened_at" in old`, set
     `entry["opened_at"] = old["opened_at"]`.
   - `record = {"card": card, "title": record.get("title") or f"[{card}]", "tools": {**record.get("tools", {}), tool: entry}}`.
   - `path.parent.mkdir(parents=True, exist_ok=True)`.
   - Comment: `# U127-A audit: each writer has its own temp file, so two letters for one card never swap a half-written record.`
   - `tmp = path.with_name(f"{path.stem}.{os.getpid()}.{threading.get_ident()}.tmp")`, then write the JSON
     (`ensure_ascii=False, indent=2`, utf-8) with `tmp.write_text(...)`.
   - `try: _retry(lambda: tmp.replace(path))`; `except PermissionError: tmp.unlink(missing_ok=True); raise`.
   - `return entry`.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
