```contract
work_id: U148-B1
worker: apply
apply_after: U148-B1R2
goal: U148 the in-app line shows today's Ollama calls and Antigravity's headless answers, written by Ollama from a spec
inputs:
- v7_harness/coord/board.py sha256=SHA_BOARD
- v7_harness/coord/agy_dispatch.py sha256=SHA_AGY2
allow:
- v7_harness/coord/board.py
acceptance: python -c "import os,json,time,tempfile,pathlib;from v7_harness.coord import board as b;from v7_harness.coord.agy_dispatch import seoul_day;t=pathlib.Path(tempfile.mkdtemp());u=t/'u.jsonl';os.environ[b.OLLA_USAGE_ENV]=str(u);os.environ[b.AGY_BRAIN_ENV]=str(t/'n');os.environ[b.CLAUDE_PROJECTS_ENV]=str(t/'c');p=t/'p';(p/'.coord').mkdir(parents=True);d=seoul_day(time.time())+'T12:00:00';rows=[{'ts':d,'event':e} for e in ['ask','digest','hint_plan']]+[{'ts':d,'event':'pilot_local','status':'ERROR'},{'ts':d,'event':'pilot_local','status':'PROMPT_TOO_LARGE'},{'ts':'2026-01-01T00:00:00','event':'ask'},{'ts':5,'event':'ask'},[1]];u.write_text(''.join(json.dumps(r)+chr(10) for r in rows)+'bad'+chr(10),encoding='utf-8');s=b.status_line(p,'claude',[]);assert '올라마 오늘 3회' in s and 'Antigravity 답장 0통' in s,s;u.write_text(''.join(json.dumps({'ts':d,'event':'find'})+chr(10) for _ in range(14)),encoding='utf-8');assert '올라마 오늘 10회 이상' in b.status_line(p,'codex',[])"
forbidden: edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 900
```

Card U148 (the user sees Ollama's and Antigravity's share of the work). Dictation: copy the three edit blocks
below exactly, in this order, and change nothing else. Two model attempts failed the fixed acceptance on dictated
lines they dropped: U148-B1 left out the dict check (AttributeError on a list row), U148-B1R2 left out the
`answered_today` import (NameError). So this retry applies exact SEARCH/REPLACE blocks.

===EDIT: v7_harness/coord/board.py===
<<<<<<< SEARCH
AGY_BRAIN_ENV = "UAOS_AGY_BRAIN"
=======
AGY_BRAIN_ENV = "UAOS_AGY_BRAIN"
OLLA_USAGE_ENV = "OLLA_USAGE"  # the override olla.py reads; default ~/.cache/olla/usage.jsonl, shared by all 3 tools
# U148: olla usage events that are real local-model calls (hints, plans and turn shapes are not calls). Each row is
# one call; olla writes no call id, so rows are not deduplicated. A failed call (status ERROR) still ran and counts.
OLLAMA_CALLS = ("ask", "edit", "digest", "find", "pilot_local", "pilot_local_repair")
# A preflight refusal never reached the model (Codex: a zero-input preflight is not a call), so it does not count.
OLLAMA_PREFLIGHT = ("PROMPT_TOO_LARGE",)
OLLAMA_STEP = 10  # the line shows tens past 10, so the remembered state changes once per 10 calls, not every call
>>>>>>> REPLACE

===EDIT: v7_harness/coord/board.py===
<<<<<<< SEARCH
def status_line(project: Path, tool: str, letters: list[str], now: float | None = None) -> str:
=======
def ollama_calls_today(now: float) -> int:
    """U148: local-model calls on the Asia/Seoul day of `now`, from the usage log every tool's olla writes.
    olla stamps rows in the machine's local time without a zone; that time is the user's, Asia/Seoul."""
    from v7_harness.coord.agy_dispatch import seoul_day

    path = Path(os.environ.get(OLLA_USAGE_ENV) or (Path.home() / ".cache" / "olla" / "usage.jsonl"))
    day = seoul_day(now)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return 0
    count = 0
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        # A row may be a JSON list or number, and a ts may be a number, so both are checked before use.
        if not isinstance(row, dict) or not isinstance(row.get("ts"), str):
            continue
        if row.get("event") in OLLAMA_CALLS and row.get("status") not in OLLAMA_PREFLIGHT \
                and row["ts"].startswith(day):
            count += 1
    return count


def status_line(project: Path, tool: str, letters: list[str], now: float | None = None) -> str:
>>>>>>> REPLACE

===EDIT: v7_harness/coord/board.py===
<<<<<<< SEARCH
    return f"[UAOS] {mail}{others}"
=======
    from v7_harness.coord.agy_dispatch import answered_today

    calls = ollama_calls_today(moment)
    ollama = f"올라마 오늘 {calls}회" if calls < OLLAMA_STEP else f"올라마 오늘 {calls - calls % OLLAMA_STEP}회 이상"
    return f"[UAOS] {mail}{others} · {ollama} · Antigravity 답장 {len(answered_today(project, moment))}통"
>>>>>>> REPLACE
