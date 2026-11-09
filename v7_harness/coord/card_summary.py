"""Deterministic card-purpose summaries shared by OS schedule and result paths."""
import json
import re
from pathlib import Path

HANGUL = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")
IDENTITY = re.compile(r"U\d{1,5}[A-Z]?(?:-[A-Za-z0-9_]+)*$", re.IGNORECASE)
ID_COMPONENT = re.compile(r"\b(?:U\d{1,5}[A-Z]?(?:-[A-Za-z0-9_]+)*|PR\s*#?\d+|[0-9a-f]{7,40})\b|#\d+", re.IGNORECASE)
ROLES = {"VERIFY": ("독립 검증", "Independent verification"), "RELEASE": ("릴리스", "Release")}
STATE_ACTIONS = {
    "PLANNED": ("실행 계획", "Execution planning"), "READY": ("실행 준비", "Ready to execute"),
    "ACTIVE": ("작업 진행", "Work in progress"), "REVIEW": ("독립 검증 대기", "Await independent review"),
    "BLOCKED": ("차단 해소 대기", "Await blocker resolution"), "DONE": ("완료 기록", "Recorded complete"),
}
STAGE_ACTIONS = {
    "SP1_RESEARCH_DRAFT": ("선행 조사·초안", "Research and draft"),
    "SP2_MIA_DESIGN_AUDIT": ("설계·반례 검토", "Design and counterexample audit"),
    "SP3_CODE_EXECUTION": ("구현", "Implementation"),
    "SP4_INDEPENDENT_VERIFY": ("독립 검증", "Independent verification"),
    "SP5_MERGE_AND_RUNTIME": ("병합·런타임 반영", "Merge and runtime integration"),
}


def compact_text(value, limit=100):
    """Normalize a single evidence field without introducing a translation."""
    if value is None:
        return ""
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[:limit-1].rstrip() + "…" if limit > 1 else "…" if limit == 1 else ""


def _id_only(value):
    """Identifiers and their punctuation do not describe a card's purpose."""
    remainder = ID_COMPONENT.sub("", value)
    return not re.sub(r"[\s()\[\]{},/&+|:;._—–-]", "", remainder)


def _pair(row, keys, identity=""):
    """Read explicit language fields or an existing bilingual label, without translation."""
    ko = en = ""
    for key in keys:
        explicit_ko, explicit_en = (compact_text(row.get(key + suffix)) for suffix in ("_ko", "_en"))
        ko = ko or (explicit_ko if explicit_ko != identity and not _id_only(explicit_ko) else "")
        en = en or (explicit_en if explicit_en != identity and not _id_only(explicit_en) else "")
        value = compact_text(row.get(key), 220)
        if value and value != identity and not _id_only(value):
            parts = value.split(" / ", 1)
            if len(parts) == 2 and HANGUL.search(parts[0]) and not HANGUL.search(parts[1]):
                ko, en = ko or parts[0], en or parts[1]
            elif HANGUL.search(value):
                ko = ko or value
            else:
                en = en or value
    return compact_text(ko), compact_text(en) if not HANGUL.search(en) else ""


def _parent_record(project, pid, row):
    parent_id = str(row.get("parent_phase_id") or row.get("parent_card") or pid.split("-", 1)[0])
    if project is None or not IDENTITY.fullmatch(parent_id):
        return {}
    root, record = Path(project), {}
    for path in (root / ".coord/cards" / (parent_id + ".json"), root / ".coord/master_schedule.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            candidates = data.get("phases", []) if path.name == "master_schedule.json" else [data]
            for candidate in candidates:
                if isinstance(candidate, dict) and str(candidate.get("phase_id") or candidate.get("card")) == parent_id:
                    record.update({k: v for k, v in candidate.items() if v and not (
                        k.startswith(("title", "purpose", "goal", "summary")) and isinstance(v, str)
                        and _id_only(v.strip()))})
        except (OSError, ValueError, AttributeError, TypeError):
            continue
    return record


def summary_fields(metadata, project=None):
    """Return maintained display fields; source records remain untouched."""
    row = dict(metadata or {})
    pid = compact_text(row.get("phase_id") or row.get("card_id") or row.get("card") or "UNRECORDED", 60)
    ko, en = _pair(row, ("title", "purpose", "goal", "summary"), pid)
    role = ROLES.get(pid.rsplit("-", 1)[-1].upper())
    if not (ko or en):
        ko, en = _pair(_parent_record(project, pid, row), ("title", "purpose", "goal", "summary"), pid.split("-", 1)[0])
        if role:
            ko = f"{ko or '작업 목적 미등록'} · {role[0]}"
            en = f"{en or 'Purpose not recorded'} · {role[1]}"
    ko, en = ko or "작업 목적 미등록", en or "Purpose not recorded"
    action_ko, action_en = _pair(row, ("current_action", "action", "current_work"))
    state = compact_text(row.get("state") or "UNRECORDED", 24)
    fallback = STAGE_ACTIONS.get(row.get("stage")) or STATE_ACTIONS.get(
        state.upper(), role or ("현재 작업 미등록", "Current work not recorded"))
    if action_ko or action_en:
        fallback = ("한글 현재 작업 미등록", "English current work not recorded")
    return {"card_id": pid, "title_ko": ko, "title_en": en, "action_ko": action_ko or fallback[0],
            "action_en": action_en or fallback[1], "state": state, "display_title": f"{ko} / {en}",
            "pr": compact_text(row.get("pr"), 140)}


def format_card_summary(metadata, project=None, audience="user"):
    """User = compact KO/EN; agent = English. Never invoke a model for reporting."""
    fields = summary_fields(metadata, project)
    pid, state = fields["card_id"], fields["state"]
    if audience == "agent":
        pid, state = (value if value.isascii() else "UNRECORDED" for value in (pid, state))
        return f"- {fields['title_en']} ({pid}): {state} — {fields['action_en']}"
    if audience != "user":
        raise ValueError("audience must be user or agent")
    pr_number = fields["pr"].rstrip("/").rsplit("/", 1)[-1].lstrip("#")
    identity = f"{pid}, PR #{pr_number}" if pr_number.isdigit() else pid
    for limit in (100, 80, 60, 40, 24):
        title_ko, title_en, action_ko, action_en = (
            compact_text(fields[key], limit) for key in ("title_ko", "title_en", "action_ko", "action_en"))
        text = f"- {title_ko} ({identity}): {state} — {title_en} · {action_ko} / {action_en}"
        if len(text) <= 600:
            return text
    raise ValueError("REPORT_OVER_CHARS: required card identity and state cannot fit the compact summary")


def summary_record(metadata, project=None):
    fields = summary_fields(metadata, project)
    return {**fields, "user_summary": format_card_summary(fields),
            "agent_summary": format_card_summary(fields, audience="agent")}
