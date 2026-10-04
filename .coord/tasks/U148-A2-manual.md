```contract
work_id: U148-A2
worker: apply
apply_after: U148-A2R2
goal: U148 daily counts use the Asia/Seoul day and count each answered letter once, written by Ollama from a spec
inputs:
- v7_harness/coord/agy_dispatch.py sha256=SHA_AGY
allow:
- v7_harness/coord/agy_dispatch.py
acceptance: python -c "import json,tempfile,pathlib;from v7_harness.coord import agy_dispatch as a;p=pathlib.Path(tempfile.mkdtemp());l=p/'.coord'/'mailbox'/'delivery'/'agy_auto.jsonl';l.parent.mkdir(parents=True);n=1791126000.0;assert a.seoul_day(n)=='2026-10-05' and a.seoul_day(n-1)=='2026-10-04';rows=[{'ts':n+10,'message_id':'r1','state':'ANSWERED'},{'ts':n+20,'message_id':'r2','state':'FAILED'},{'ts':n+30,'message_id':'r1','state':'ANSWERED'},{'ts':n+40,'message_id':'r3','state':'ANSWERED'},{'ts':n-5,'message_id':'r0','state':'ANSWERED'},{'ts':True,'message_id':'rb','state':'ANSWERED'},{'ts':n+50,'state':'ANSWERED'},[1]];l.write_text(''.join(json.dumps(r)+chr(10) for r in rows)+'bad'+chr(10),encoding='utf-8');assert a.answered_today(p,n+100)==['r3','r1'],a.answered_today(p,n+100)"
forbidden: edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 900
```

Card U148 (Codex review: daily counts name their timezone and dedup rule). Dictation: copy the three edit
blocks below exactly, in this order, and change nothing else. Attempt U148-A2 rewrote a whole region in a
fenced block and failed SPLICE_CURRENT:91 (its first splice left the file unparsable), so this retry dictates
exact SEARCH/REPLACE blocks.

===EDIT: v7_harness/coord/agy_dispatch.py===
<<<<<<< SEARCH
import subprocess
import time
=======
import subprocess
import time
from datetime import datetime, timedelta, timezone
>>>>>>> REPLACE

===EDIT: v7_harness/coord/agy_dispatch.py===
<<<<<<< SEARCH
RESUME_MAX_INPUT = 70_000
=======
RESUME_MAX_INPUT = 70_000

# U148: every daily count names one day for all 3 tools, the user's: Asia/Seoul, a fixed UTC+9 because Korea has had
# no daylight saving since 1988 and Windows Python has no tz database without the tzdata package.
SEOUL = timezone(timedelta(hours=9))


def seoul_day(ts: float) -> str:
    """U148: the Asia/Seoul calendar day of a Unix time, as YYYY-MM-DD."""
    return datetime.fromtimestamp(ts, SEOUL).strftime("%Y-%m-%d")
>>>>>>> REPLACE

===EDIT: v7_harness/coord/agy_dispatch.py===
<<<<<<< SEARCH
def answered_today(project: Path, now: float) -> list[str]:
    """U148: message ids Antigravity answered headless on the local day of `now`, newest first (board line and
    the desk conversation's hook line both read this one ledger)."""
    ledger = _ledger(project)
    if not ledger.is_file():
        return []
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    try:
        with open(ledger, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    kept_ids = []
    for line in reversed(lines):
        try:
            row = json.loads(line)
            if row.get("state") == "ANSWERED" and isinstance(row.get("ts"), (int, float)) and time.strftime("%Y-%m-%d", time.localtime(row["ts"])) == day:
                kept_ids.append(row["message_id"])
        except ValueError:
            continue
    return kept_ids
=======
def answered_today(project: Path, now: float) -> list[str]:
    """U148: message ids Antigravity answered headless on the Asia/Seoul day of `now`, newest first, each id once
    (a letter answered twice is one answer). FAILED rows are not answers. The board line and the desk conversation's
    hook line both read this one ledger."""
    ledger = _ledger(project)
    try:
        lines = ledger.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    day = seoul_day(now)
    kept: list[str] = []
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get("state") != "ANSWERED":
            continue
        ts, message_id = row.get("ts"), row.get("message_id")
        if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not isinstance(message_id, str):
            continue
        if seoul_day(ts) == day and message_id not in kept:
            kept.append(message_id)
    return kept
>>>>>>> REPLACE

