"""U286 v4: Antigravity per-account quota facts for the HUD.

Receipt (2026-10-29, 윤겸스): the HUD showed one Antigravity budget computed from ledger tokens against a policy
reference cap, while the user rotates one subscription account and several free accounts, each with its own reset.

Facts only, every value carries its source:
- Registry `.coord/accounts/antigravity_accounts.json` (user-provided): email, plan, optional weekly reset date.
- Live capture: Antigravity writes `RESOURCE_EXHAUSTED (code 429) ... Resets in 167h36m51s` into
  `%APPDATA%/Antigravity/logs/language_server.log` with a glog local timestamp (`E1029 07:52:56`); log time plus the
  duration is the absolute reset time. The line names no account, but every account switch writes
  `[AuthProvider] SetEnableBusinessLogin`, so the 429 lines between two such markers belong to one sign-in session.
  Reset times are not a usable key: one session's resets drift by 30+ minutes (rolling window), which is why the
  first cut that clustered by reset time split one account in two (observed 2026-10-29 08:13).
  Only the session that began at the newest marker is tied to the account signed in now (`app_storage.json` key
  `jetski.onboarding.lastLoginUsername`), and that tie is labelled as such; older sessions stay unidentified.
- Captured waits persist in `.coord/accounts/antigravity_resets.json` because the log restarts with the app.
No token, cookie or credential is read: only the login e-mail key and the 429 and login marker lines.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

STAMP = r"[EWI](\d{2})(\d{2}) (\d{2}):(\d{2}):(\d{2})\.\d+"
RESET_LINE = re.compile(STAMP + r".*?RESOURCE_EXHAUSTED.*?Resets in ((?:\d+h)?(?:\d+m)?(?:\d+s)?)")
LOGIN_LINE = re.compile(STAMP + r".*?\[AuthProvider\] SetEnableBusinessLogin")
ANY_STAMP = re.compile(STAMP)
DURATION = re.compile(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?")
LOGIN_KEY = "jetski.onboarding.lastLoginUsername"


def _duration_s(text: str) -> int | None:
    m = DURATION.fullmatch(text or "")
    if not m or not any(m.groups()):
        return None
    h, mi, s = (int(g or 0) for g in m.groups())
    return h * 3600 + mi * 60 + s


def _stamp(groups: tuple, log_mtime: datetime) -> datetime | None:
    """glog has no year: take the log's year, one year back when the month-day lies after the log's own mtime
    (a December line read in January)."""
    mon, day, hh, mm, ss = (int(x) for x in groups[:5])
    try:
        t = datetime(log_mtime.year, mon, day, hh, mm, ss, tzinfo=log_mtime.tzinfo)
    except ValueError:
        return None
    return t.replace(year=t.year - 1) if t > log_mtime + timedelta(days=1) else t


def parse_log(text: str, log_mtime: datetime) -> tuple[list[dict[str, Any]], str | None]:
    """Log text -> ([{session, observed_at, resets_at}], newest login marker). A 429 before any marker belongs to
    the session that started with the log itself."""
    events: list[dict[str, Any]] = []
    session = newest_login = None
    for line in (text or "").splitlines():
        if session is None:
            first = ANY_STAMP.search(line)
            t0 = _stamp(first.groups(), log_mtime) if first else None
            session = t0.isoformat() if t0 else None
        m = LOGIN_LINE.search(line)
        if m:
            t = _stamp(m.groups(), log_mtime)
            if t:
                session = newest_login = t.isoformat()
            continue
        m = RESET_LINE.search(line)
        if not m:
            continue
        seen, dur = _stamp(m.groups(), log_mtime), _duration_s(m.group(6))
        if seen and dur is not None and session:
            events.append({"session": session, "observed_at": seen.isoformat(),
                           "resets_at": (seen + timedelta(seconds=dur)).isoformat()})
    return events, newest_login


def group_sessions(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One wait per sign-in session; its newest 429 line gives the reset time."""
    waits: dict[str, dict[str, Any]] = {}
    for ev in sorted(events, key=lambda e: e["observed_at"]):
        w = waits.setdefault(ev["session"], {"session": ev["session"], "first_seen": ev["observed_at"], "hits": 0,
                                             "email": None})
        w.update(resets_at=ev["resets_at"], last_seen=ev["observed_at"], hits=w["hits"] + 1)
        w["email"] = ev.get("email") or w["email"]
    return sorted(waits.values(), key=lambda w: w["session"])


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _appdata() -> Path | None:
    v = os.environ.get("APPDATA")
    return Path(v) if v else None


def current_login(appdata: Path | None) -> str | None:
    doc = _read_json(appdata / "Antigravity" / "app_storage.json") if appdata else None
    val = doc.get(LOGIN_KEY) if isinstance(doc, dict) else None
    return str(val) if isinstance(val, str) and "@" in val else None


def antigravity_accounts(root: Path, now: datetime | None = None, appdata: Path | None = None,
                         persist: bool = False) -> dict[str, Any]:
    """Per-account view for the HUD: registry facts plus waits captured from the 429 log."""
    now = now or datetime.now(timezone.utc).astimezone()
    appdata = appdata if appdata is not None else _appdata()
    acc_dir = Path(root) / ".coord" / "accounts"
    registry = _read_json(acc_dir / "antigravity_accounts.json") or {}
    store_path = acc_dir / "antigravity_resets.json"
    stored = [e for e in (_read_json(store_path) or {}).get("events") or [] if isinstance(e, dict) and e.get("session")]
    login = current_login(appdata)

    fresh: list[dict[str, Any]] = []
    newest_login = None
    log = appdata / "Antigravity" / "logs" / "language_server.log" if appdata else None
    if log and log.is_file():
        mtime = datetime.fromtimestamp(log.stat().st_mtime).astimezone()
        fresh, newest_login = parse_log(log.read_text(encoding="utf-8", errors="replace"), mtime)
    # the account signed in now owns the session that began at the newest marker
    if login and newest_login:
        for e in fresh:
            if e["session"] == newest_login:
                e["email"], e["email_source"] = login, "현재 로그인 세션의 429 (계정은 로그인 기록으로 연결)"
    seen = {(e["observed_at"], e["resets_at"]) for e in stored}
    events = stored + [e for e in fresh if (e["observed_at"], e["resets_at"]) not in seen]
    live = [e for e in events if datetime.fromisoformat(e["resets_at"]) > now]
    waits = group_sessions(live)
    for w in waits:
        w["email_source"] = next((e.get("email_source") for e in live if e["session"] == w["session"]
                                  and e.get("email_source")), None)
    if persist and fresh:
        acc_dir.mkdir(parents=True, exist_ok=True)
        store_path.write_text(json.dumps({"schema": "uaos-agy-resets-v2", "events": live}, ensure_ascii=False,
                                         indent=1), encoding="utf-8")

    by_email: dict[str, dict[str, Any]] = {}
    for w in waits:  # sessions are sorted oldest first, so the newest wait of an account wins
        if w.get("email"):
            by_email[w["email"]] = w
    accounts = []
    for a in registry.get("accounts") or []:
        email = str(a.get("email") or "")
        w = by_email.pop(email, None)
        wd = a.get("weekly_reset_date")
        accounts.append({
            "email": email, "plan": a.get("plan") or "", "kind": a.get("kind") or "",
            "signed_in": email == login,
            "blocked": bool(w),
            "resets_at": w["resets_at"] if w else None,
            "reset_source": (w.get("email_source") or "429 로그") if w else None,
            "weekly_reset_date": wd if wd and str(wd) >= now.date().isoformat() else None,
            "weekly_reset_source": a.get("weekly_reset_source") or ("사용자 제공" if wd else None),
        })
    named = {a["email"] for a in accounts if a["blocked"]}
    unassigned = [w for w in waits if not w.get("email") or w["email"] not in named]
    return {"schema": "uaos-agy-accounts-v2", "observed_at": now.isoformat(), "signed_in": login,
            "accounts": accounts, "unassigned_waits": unassigned,
            "registry_present": bool(registry), "log_present": bool(log and log.is_file())}
