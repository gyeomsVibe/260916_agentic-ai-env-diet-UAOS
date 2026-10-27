"""U130: the default card pipeline. Every card manual comes from one template with four stage slots (research, MIA,
execute, verify), each naming its default workers, and `card audit` passes only when the ledger shows a real Ollama
call and an Antigravity audit or review for the card, or a verified skip row. The commit gate and `rsi ship` run the
audit, so a plan without Ollama and Antigravity no longer reaches a PR (closes U130 R1-R4)."""

from __future__ import annotations
import datetime
import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable

from subprocess import TimeoutExpired

from v7_harness import runtime_install
from v7_harness.coord import merge_route
from v7_harness.coord.usage_ledger import record_usage
from v7_harness.coord.presence import read as read_presence

# A card id is "U" + digits + an optional letter (U98-D is card U98); it becomes a file name, so nothing else passes.
CARD_RE = re.compile(r"U\d{1,5}[A-Z]?$")
# Commit message line naming the card; else the branch name `<tool>/u<digits>-...` names it.
CARD_LINE_RE = re.compile(r"^Card:\s*(U\d{1,5}[A-Z]?)\s*$", re.MULTILINE)
BRANCH_RE = re.compile(r"(?:^|/)u(\d{1,5})(?:[-_/]|$)", re.IGNORECASE)
# The four stage slots; a manual lacking one (or its Workers line) is refused by `coord window`.
SLOTS = (("1", "Research"), ("2", "MIA"), ("3", "Execute"), ("4", "Verify"))
# Ledger workers that are the free local model (same set as calculator_gate.LOCAL_AUTHORS) and Antigravity.
LOCAL_WORKERS = frozenset({"ollama", "local", "cascade"})
AGY_WORKERS = frozenset({"agy", "antigravity"})
# A review file counts only with a terminal verdict (U130 audit relay_92fa8200).
AGY_VERDICTS = frozenset({"PASS", "REVISE", "FAIL"})
# Ollama MCP events that ran the model; `digest` ran it only when not served from the cache.
OLLA_MODEL_EVENTS = frozenset({"ask", "edit", "pilot_local"})
SKIP_REASONS = ("OLLAMA_DOWN", "AGY_LIMITED", "TASK_CLASS")
# The slot each machine-checked reason may skip; TASK_CLASS may skip either.
SKIP_SLOT = {"OLLAMA_DOWN": "ollama", "AGY_LIMITED": "agy"}
# TASK_CLASS evidence must say what Ollama/Antigravity cannot do; 20 characters is one short clause.
MIN_EVIDENCE = 20
# /api/tags lists local models for 0 tokens; 3 s is ten times its measured local answer time.
OLLAMA_TAGS = "http://127.0.0.1:11434/api/tags"
PROBE_TIMEOUT_S = 3

TEMPLATE = """# {card} contract manual - {title}

Work ID: {card}. Ollama FIRST at every stage (token thrift alone is reason enough); every Ollama/Antigravity call
and every skipped slot is recorded: `uaos card claim --card {card} --session <session id>` and
`uaos card skip --card {card} --slot ollama|agy --reason OLLAMA_DOWN|AGY_LIMITED|TASK_CLASS --evidence <text>`.

## Receipt

## Stage 1 - Research (Web Deep Research)
Workers: conductor web search (mandatory primary sources: official docs / GitHub URL); Ollama local_draft; Antigravity source audit
Output: .work/cards/{card}_research.md (primary sources & observed facts)

## Stage 2 - MIA (11-Stage Canonical Frame)
Workers: conductor 11-stage flow (기획-검증-큰계획-검증-세부계획-검증-구현계획-검증); Ollama local_read_map; Antigravity design audit
Output: .work/cards/{card}_frame.md

## Stage 3 - Execute (Implementation)
Workers: Ollama (pilot run, worker: local) first; Antigravity for multi-file or Ollama-failed work; worker: apply only per U98-D
Output: pilot runs {card}-L<n>

## Stage 4 - Verify (Debugging & Final Verification)
Workers: fixed acceptance + full suite + debugging / vaccine test; Antigravity review (pilot review --reviewer agy); Ollama local_draft
Gate: uaos card audit --card {card} exits 0 before the PR

## Contract (measurable)

## Allowed files

## Pass command

## Stop conditions

## Result relay (last step)
`uaos card result --card {card} --pr <url> --mergeable yes|no --tests <run>/<fail> --blocker none` writes
.coord/results/{card}.md in this checkout (a card worktree too) and prints one RESULT line; send that line to the user
window (Claude: send_message; Codex/Antigravity: `uaos coord deliver --target claude --card {card} --message "<line>"`).
The user window runs `uaos card results` to collect every checkout's result and batches the merges into one report.
"""


def _check(card: str) -> str:
    if not CARD_RE.fullmatch(card or ""):
        raise ValueError(f"bad card id: {card!r}")
    return card


def card_of(message: str, branch: str) -> str | None:
    match CARD_LINE_RE.search(message):
        case None:
            match BRANCH_RE.search(branch):
                case None:
                    return None
                case m:
                    return f"U{m.group(1)}"
        case m:
            return m.group(1)


def _card_record(desk: Path, card: str) -> Path:
    return Path(desk) / ".coord" / "cards" / f"{_check(card)}.json"


# U267: every user-facing status/result/wait line must carry a human-readable core title, never bare IDs/PRs/SHAs alone.
BARE_ID_LABEL_RE = re.compile(
    r"^[\s\(\)\[\]&,·/|+-]*(?:"
    r"U\d{1,5}[A-Z]?(?:-[A-Za-z0-9]+)?|"
    r"PR\s*#?\d+|"
    r"#\d+|"
    r"[0-9a-f]{7,40}"
    r")(?:[\s\(\)\[\]&,·/|+-]+(?:"
    r"U\d{1,5}[A-Z]?(?:-[A-Za-z0-9]+)?|"
    r"PR\s*#?\d+|"
    r"#\d+|"
    r"[0-9a-f]{7,40}"
    r"))*[\s\(\)\[\]&,·/|+-]*$",
    re.IGNORECASE,
)
CORE_TITLE_PREFIX_RE = re.compile(
    r"^(?:\[?\s*U\d{1,5}[A-Z]?(?:-[A-Za-z0-9]+)?\s*\]?\s*[:\-—–]?\s*|"
    r"(?:feat|fix|refactor|docs|test|chore|perf|ci|build)\s*(?:\([^)]*\))?\s*:\s*)+",
    re.IGNORECASE,
)
STATUS_LINE_RE = re.compile(r"^\s*-\s+([^:\n]+?)\s*:\s*(DONE|REVIEW|ACTIVE|READY|WAITING|BLOCKED|MERGED|PASS|FAIL)\b", re.IGNORECASE)
CORE_TITLE_MAX = 48


def clean_core_title(raw: str | None) -> str:
    """U267: strip leading card-ID or conventional-commit prefixes and normalize whitespace into a concise core title."""
    if not isinstance(raw, str):
        return ""
    text = " ".join(raw.strip().split())
    text = CORE_TITLE_PREFIX_RE.sub("", text).strip(" -—–:·")
    if len(text) > CORE_TITLE_MAX:
        text = text[:CORE_TITLE_MAX - 1].rstrip() + "…"
    return text


def is_bare_id_label(label: str | None) -> bool:
    """U267: True when a status label contains only card IDs, PR numbers, commit SHAs, or punctuation (`U260 (PR #227)`)."""
    if not isinstance(label, str) or not label.strip():
        return True
    cleaned = " ".join(label.strip().split())
    if BARE_ID_LABEL_RE.fullmatch(cleaned):
        return True
    stripped = re.sub(
        r"\b(?:U\d{1,5}[A-Z]?(?:-[A-Za-z0-9]+)?|PR\s*#?\d+|[0-9a-f]{7,40})\b|#\d+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    meaningful = re.sub(r"[\s\(\)\[\]&,·/|+:;\-—–_]+", "", stripped)
    return len(meaningful) < 2


def card_title(project_or_desk: Path | str, card: str) -> str:
    """U267: resolve a card's human-readable core title from `.coord/cards/`, `.work/cards/`, `master_schedule.json`, or `PLAN.md`."""
    if not isinstance(card, str) or not CARD_RE.fullmatch(card):
        return ""
    base = Path(project_or_desk)
    candidates = [base]
    dot = base / ".git"
    if dot.is_file():
        try:
            meta = Path(dot.read_text(encoding="utf-8").split("gitdir:", 1)[1].strip())
            main_root = meta.parent.parent.parent
            if main_root not in candidates:
                candidates.append(main_root)
        except (OSError, IndexError):
            pass
    for root in candidates:
        rec = root / ".coord" / "cards" / f"{card}.json"
        if rec.is_file():
            try:
                title = clean_core_title(json.loads(rec.read_text(encoding="utf-8")).get("title"))
                if title and not is_bare_id_label(title):
                    return title
            except (OSError, ValueError, AttributeError):
                pass
        manual = root / ".work" / "cards" / f"{card}_manual.md"
        if manual.is_file():
            try:
                first = manual.read_text(encoding="utf-8").splitlines()[0]
                m = re.match(rf"^#\s*{re.escape(card)}\s+contract\s+manual\s*-\s*(.+)$", first.strip(), re.IGNORECASE)
                if m:
                    title = clean_core_title(m.group(1))
                    if title and not is_bare_id_label(title):
                        return title
            except (OSError, IndexError):
                pass
        sched = root / ".coord" / "master_schedule.json"
        if sched.is_file():
            try:
                phases = json.loads(sched.read_text(encoding="utf-8")).get("phases") or []
                for ph in phases:
                    if isinstance(ph, dict) and str(ph.get("phase_id") or "") == card:
                        for key in ("title", "name", "summary", "topic"):
                            title = clean_core_title(ph.get(key))
                            if title and not is_bare_id_label(title):
                                return title
            except (OSError, ValueError, AttributeError):
                pass
        plan = root / ".coord" / "PLAN.md"
        if plan.is_file():
            try:
                for line in plan.read_text(encoding="utf-8").splitlines():
                    if card in line and "|" in line:
                        cells = [c.strip() for c in line.strip("|").split("|")]
                        for cell in cells:
                            if cell != card and not CARD_RE.fullmatch(cell) and cell not in ("READY", "ACTIVE", "REVIEW", "DONE", "BLOCKED", "WAITING"):
                                title = clean_core_title(cell)
                                if title and not is_bare_id_label(title) and len(title) >= 4:
                                    return title
            except OSError:
                pass
    return ""


def format_status_line(
    card_or_id: str,
    title: str,
    state: str,
    next_step: str,
    *,
    pr: str | int | None = None,
    detail: str | None = None,
) -> str:
    """U267: format `- <핵심 제목> (<카드ID, PR #번호>): <상태> (<세부 근거>) → <다음 행동>`; refuses bare IDs."""
    core = clean_core_title(title)
    if not core or is_bare_id_label(core):
        raise ValueError(f"BARE_ID_REPORT_FORBIDDEN: status line for {card_or_id!r} requires a human-readable core title, got {title!r}")
    id_part = str(card_or_id or "").strip()
    pr_part = ""
    if pr is not None and str(pr).strip():
        pr_str = str(pr).strip()
        if pr_str.isdigit():
            pr_part = f"PR #{pr_str}"
        elif "/pull/" in pr_str:
            pr_part = f"PR #{pr_str.rsplit('/pull/', 1)[1].split('/')[0]}"
        elif pr_str.upper().startswith("PR"):
            pr_part = pr_str
        else:
            pr_part = f"PR #{pr_str.lstrip('#')}"
    meta = ", ".join(p for p in (id_part, pr_part) if p)
    head = f"{core} ({meta})" if meta else core
    state_str = str(state or "").strip()
    if detail and str(detail).strip():
        state_str = f"{state_str} ({str(detail).strip()})"
    nxt = str(next_step or "").strip() or "종료"
    return f"- {head}: {state_str} → {nxt}"


def validate_user_status_lines(text: str) -> list[str]:
    """U267: return problem codes for any `- <name>: <state> → <next>` line whose `<name>` is only card/PR/SHA IDs."""
    problems: list[str] = []
    for raw_line in (text or "").splitlines():
        m = STATUS_LINE_RE.match(raw_line)
        if not m:
            continue
        label = m.group(1).strip()
        if is_bare_id_label(label):
            problems.append(f"BARE_ID_REPORT_FORBIDDEN: {label!r} lacks a human-readable core title")
    return problems


# U271: one compact BLUF report; the same budget the olla report gate measures (olla.REPORT_MAX_*).
REPORT_MAX_LINES = 5
REPORT_MAX_CHARS = 600
NESTED_RE = re.compile(r"^\s+[-*]\s")


def compact_report_problems(text: str) -> list[str]:
    """U271: why a user report is too long: lines, characters, nested bullets, bare-ID status lines."""
    lines = [line for line in (text or "").splitlines() if line.strip()]
    problems = []
    if len(lines) > REPORT_MAX_LINES:
        problems.append(f"OVER_LINES: {len(lines)} > {REPORT_MAX_LINES}")
    if len(text or "") > REPORT_MAX_CHARS:
        problems.append(f"OVER_CHARS: {len(text or '')} > {REPORT_MAX_CHARS}")
    if any(NESTED_RE.match(line) for line in lines):
        problems.append("NESTED: sub-bullets belong in the PR body or card")
    return problems + validate_user_status_lines(text)


def new_manual(desk, card, title, now: float | None = None) -> dict[str, Any]:
    manual = Path(desk) / ".work" / "cards" / f"{_check(card)}_manual.md"
    if not manual.is_file():
        manual.parent.mkdir(parents=True, exist_ok=True)
        manual.write_text(TEMPLATE.format(card=card, title=title), encoding="utf-8")
        created = True
    else:
        created = False
    record = _card_record(desk, card)
    if not record.is_file():
        record.parent.mkdir(parents=True, exist_ok=True)
        started = time.time() if now is None else now
        record.write_text(json.dumps({"card": card, "title": title, "started_at": started}), encoding="utf-8")
    return {"manual": str(manual), "created": created, "started_at": started_at(desk, card)}


def missing_slots(text: str) -> list[str]:
    missing = []
    for n, name in SLOTS:
        heading = re.search(rf"^##\s*Stage\s*{n}\b[^\n]*\b{name}\b", text, re.MULTILINE | re.IGNORECASE)
        if heading is None:
            missing.append(f"Stage {n} {name}")
        else:
            section = text[heading.end():]
            following = re.search(r"^##\s", section, re.MULTILINE)
            if following is not None:
                section = section[:following.start()]  # a later stage's Workers line does not fill this one
            if not re.search(r"^Workers:\s*\S", section, re.MULTILINE):
                missing.append(f"Stage {n} {name}: Workers line")
    return missing


# U135: a RESULT field is one line without the "|" separator, so the user window can split the line back into fields.
FIELD_RE = re.compile(r"[^|\r\n]+")
# Tests are "<run>/<fail>" counts.
TESTS_RE = re.compile(r"\d+/\d+")
MERGEABLE = ("yes", "no")


def result_line(card, pr, mergeable, tests, blocker) -> str:
    _check(card)
    if mergeable not in MERGEABLE:
        raise ValueError(f"mergeable must be yes or no, got {mergeable!r}")
    if TESTS_RE.fullmatch(tests or "") is None:
        raise ValueError(f"tests must be <run>/<fail>, got {tests!r}")
    for name, value in (("pr", pr), ("blocker", blocker)):
        if FIELD_RE.fullmatch(value or "") is None or not value.strip():
            raise ValueError(f"{name} must be one non-empty line without '|', got {value!r}")
    return f"RESULT {card} | PR {pr.strip()} | MERGEABLE {mergeable} | tests {tests} | blocker {blocker.strip()}"


def write_result(checkout, card, pr, mergeable, tests, blocker, title: str | None = None) -> dict[str, Any]:
    """U135: the result goes in the card's own checkout; a card worktree may not write the base checkout."""
    line = result_line(card, pr, mergeable, tests, blocker)
    path = Path(checkout) / ".coord" / "results" / f"{card}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    resolved_title = clean_core_title(title) if title else card_title(checkout, card)
    heading = f"# {card} — {resolved_title} result ({datetime.date.today().isoformat()})" if resolved_title else f"# {card} result ({datetime.date.today().isoformat()})"
    path.write_text(f"{heading}\n\n{line}\n", encoding="utf-8")
    user_line = (
        format_status_line(
            card,
            resolved_title,
            "REVIEW" if mergeable == "yes" else "BLOCKED",
            "동료 도구 판정·병합" if mergeable == "yes" else f"차단 해소({blocker.strip()})",
            pr=pr,
            detail=f"tests {tests}, mergeable={mergeable}",
        )
        if resolved_title
        else ""
    )
    return {"ok": True, "path": str(path), "line": line, "title": resolved_title, "user_line": user_line}


def _checkouts(project) -> list[Path]:
    """The main checkout and every live worktree, read from .git on disk (no git subprocess)."""
    root = Path(project)
    dot = root / ".git"
    if dot.is_file():
        meta = Path(dot.read_text(encoding="utf-8").split("gitdir:", 1)[1].strip())
        root = meta.parent.parent.parent  # <main>/.git/worktrees/<name> sits three levels below the main checkout
    found = [root]
    for gitdir in sorted((root / ".git" / "worktrees").glob("*/gitdir")):
        checkout = Path(gitdir.read_text(encoding="utf-8").strip()).resolve().parent
        if checkout.is_dir():
            found.append(checkout)
    return found


def collect_results(project) -> list[dict[str, Any]]:
    """U135: the user window's view of every card result; the newest file wins when a card wrote twice."""
    newest: dict[str, tuple[float, dict]] = {}
    for checkout in _checkouts(project):
        for path in sorted((checkout / ".coord" / "results").glob("U*.md")):
            line = next((text for text in path.read_text(encoding="utf-8").splitlines() if text.startswith("RESULT ")),
                        None)
            if line is None or not CARD_RE.fullmatch(path.stem):  # agy audit: only card ids are reported
                continue
            stamp = path.stat().st_mtime
            if path.stem not in newest or stamp > newest[path.stem][0]:
                lines_all = path.read_text(encoding="utf-8").splitlines()
                first_heading = lines_all[0] if lines_all else ""
                m_head = re.match(rf"^#\s*{re.escape(path.stem)}\s+—\s+(.+?)\s+result\s+\(", first_heading)
                resolved_title = clean_core_title(m_head.group(1)) if m_head else card_title(project, path.stem)
                parts = [p.strip() for p in line.split("|")]
                pr_val = parts[1][3:].strip() if len(parts) > 1 and parts[1].startswith("PR ") else ""
                merge_val = parts[2][10:].strip() if len(parts) > 2 and parts[2].startswith("MERGEABLE ") else "yes"
                tests_val = parts[3][6:].strip() if len(parts) > 3 and parts[3].startswith("tests ") else ""
                user_line = (
                    format_status_line(
                        path.stem,
                        resolved_title,
                        "REVIEW" if merge_val == "yes" else "BLOCKED",
                        "동료 도구 판정·병합" if merge_val == "yes" else "차단 해소",
                        pr=pr_val,
                        detail=f"tests {tests_val}, mergeable={merge_val}" if tests_val else f"mergeable={merge_val}",
                    )
                    if resolved_title
                    else ""
                )
                newest[path.stem] = (
                    stamp,
                    {"card": path.stem, "title": resolved_title, "line": line, "user_line": user_line, "path": str(path)},
                )
    return [row for _, row in sorted(newest.values(), key=lambda item: item[1]["card"])]


def started_at(desk, card) -> float | None:
    try:
        value = json.loads(_card_record(desk, card).read_text(encoding="utf-8")).get("started_at")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    except (OSError, ValueError, AttributeError):
        pass
    try:
        tools = json.loads((Path(desk) / ".coord" / "windows" / f"{card}.json").read_text(encoding="utf-8"))["tools"]
        opened = [w.get("opened_at") for w in tools.values() if isinstance(w, dict)]
        opened = [float(v) for v in opened if isinstance(v, (int, float)) and not isinstance(v, bool)]
        return min(opened) if opened else None
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def _jsonl(path) -> list[dict]:
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _ledger(desk) -> Path:
    return Path(desk) / ".coord" / "usage" / "runs.jsonl"


def _row(card, work_id, **fields) -> dict:
    return {
        "schema": "uaos-usage-v2",
        "work_id": work_id,
        "actor": "conductor",
        "model": None,
        "kind": "card",
        "collection_mode": "claimed",
        "input_tokens": 0,
        "output_tokens": 0,
        "wall_time_s": 0.0,
        "outcome": "PASS",
        "receipt": f"card {card}",
        "independent_verifier": None,
        "rsi_eligible": False,
        "exclusion_reason": "CARD_PIPELINE"
    } | fields


def claim(desk, card, session: str, olla_log, now: float | None = None) -> dict[str, Any]:
    start = started_at(desk, card)
    if start is None:
        return {"ok": False, "card": card, "error": "CARD_NOT_OPENED"}
    end = time.time() if now is None else now
    rows = _jsonl(_ledger(desk))
    taken = {r.get("source_key") for r in rows if r.get("kind") == "olla_mcp"}
    n = sum(1 for r in rows if str(r.get("work_id", "")).startswith(f"{card}-olla-"))
    claimed = 0
    for src in _jsonl(olla_log):
        if src.get("session") != session:
            continue
        try:
            ts = datetime.datetime.fromisoformat(str(src.get("ts"))).timestamp()
        except ValueError:
            continue
        if not start <= ts <= end:
            continue
        event = src.get("event")
        if event in OLLA_MODEL_EVENTS:
            tokens = int(src.get("input_tokens") or 0)
        elif event == "digest" and src.get("cached") is False:
            tokens = int(src.get("paid_tokens_if_read") or 0)
        else:
            tokens = 0
        if tokens <= 0:
            continue
        key = f"{session}|{src.get('ts')}|{event}"
        if key in taken:
            continue
        n += 1
        record_usage(Path(desk), _row(
            card, f"{card}-olla-{n}", actor=str(src.get("caller") or "unknown"),
            model=str(src.get("model") or "ollama"), kind="olla_mcp", input_tokens=tokens, output_tokens=int(src.get("output_tokens") or 0),
            wall_time_s=float(src.get("elapsed_s") or 0.0), receipt=str(olla_log), exclusion_reason="CLAIMED_OLLA_MCP",
            worker="ollama", source_key=key, olla_event=event))
        taken.add(key)
        claimed += 1
    return {"ok": True, "card": card, "claimed": claimed}


def _ollama_up() -> bool:
    try:
        urllib.request.urlopen(OLLAMA_TAGS, timeout=PROBE_TIMEOUT_S)
        return True
    except Exception:
        return False


def _agy_state(desk) -> Callable[[], str]:
    return lambda: read_presence(Path(desk), "antigravity").get("state", "UNKNOWN")


def skip(desk, card, slot, reason, evidence, probe=None, agy_state=None) -> dict[str, Any]:
    card = _check(card)
    if slot not in ("ollama", "agy"):
        return {"ok": False, "card": card, "error": "BAD_SLOT"}
    if reason not in SKIP_REASONS or SKIP_SLOT.get(reason, slot) != slot:
        return {"ok": False, "card": card, "error": "BAD_REASON"}
    if not (evidence or "").strip():
        return {"ok": False, "card": card, "error": "NO_EVIDENCE"}
    if reason == "TASK_CLASS" and len(evidence.strip()) < MIN_EVIDENCE:
        return {"ok": False, "card": card, "error": "EVIDENCE_TOO_SHORT"}
    if reason == "OLLAMA_DOWN" and (probe or _ollama_up)():
        return {"ok": False, "card": card, "error": "OLLAMA_UP"}
    if reason == "AGY_LIMITED" and (agy_state or _agy_state(desk))() not in ("LIMITED", "ABSENT"):
        return {"ok": False, "card": card, "error": "AGY_AVAILABLE"}
    record_usage(Path(desk), _row(
        card, f"{card}-skip-{slot}", kind="card_skip", collection_mode="manual", outcome="SKIPPED",
        exclusion_reason="CARD_SKIP", worker=slot, skip_slot=slot, skip_reason=reason, evidence=evidence.strip()))
    return {"ok": True, "card": card, "slot": slot, "reason": reason}


def audit(desk, card, code_paths: Iterable[str] = (), run_dirs: Iterable[Path] | None = None) -> dict[str, Any]:
    card = _check(card)
    desk = Path(desk)
    mine = [r for r in _jsonl(_ledger(desk)) if str(r.get("work_id", "")).split("-")[0] == card]
    code = any(str(p).endswith(".py") for p in code_paths)

    def used(workers):
        return [f"{r['work_id']} ({r.get('worker')}, {int(r.get('input_tokens') or 0)} tokens)" for r in mine
                if r.get("worker") in workers and int(r.get("input_tokens") or 0) > 0]

    ollama_evidence, agy_evidence = used(LOCAL_WORKERS), used(AGY_WORKERS)
    try:
        conv = json.loads((desk / ".coord" / "windows" / f"{card}.json").read_text(encoding="utf-8"))
        conv = conv["tools"]["antigravity"]["id"]
    except (OSError, ValueError, KeyError, TypeError):
        conv = None
    if conv:
        for row in _jsonl(desk / ".coord" / "mailbox" / "delivery" / "agy_auto.jsonl"):
            if row.get("state") == "ANSWERED" and row.get("conversation_id") == conv:
                agy_evidence.append(f"agy reply {row.get('reply_id')}")
    for run_dir in [desk / ".coord"] if run_dirs is None else run_dirs:
        for path in sorted({*Path(run_dir).glob(f"runs/{card}-*/review_agy.json"),
                            *Path(run_dir).glob(f"runs/{card}/review_agy.json")}):
            try:
                review = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if _real_agy_review(review, path.parent.name):
                agy_evidence.append(f"agy review {path.parent.name} {review['verdict']}")
        for path in sorted({*Path(run_dir).glob(f"runs/{card}-*/judge_agy.json"),
                            *Path(run_dir).glob(f"runs/{card}/judge_agy.json")}):
            try:
                judged = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(judged, dict) and judged.get("verdict") == "APPROVE":
                agy_evidence.append(f"agy judge {path.parent.name} APPROVE")
    for folder in (desk / ".coord" / "mailbox" / "inbox", desk / ".coord" / "mailbox" / "ack"):
        for path in sorted(folder.glob("relay_*.json")) if folder.is_dir() else ():
            try:
                payload = (json.loads(path.read_text(encoding="utf-8")) or {}).get("payload") or {}
            except (OSError, ValueError, AttributeError):
                continue
            if (isinstance(payload, dict) and payload.get("actor") == "antigravity"
                    and payload.get("card") == card and payload.get("verdict") in AGY_VERDICTS):
                agy_evidence.append(f"agy letter {path.stem} {payload['verdict']}")
    skips = [r for r in mine if r.get("kind") == "card_skip"]
    for skip in skips:
        slot, reason = skip.get("skip_slot"), skip.get("skip_reason")
        if reason not in SKIP_REASONS or (slot == "ollama" and reason == "TASK_CLASS" and code):
            continue  # U130 relay_92fa8200: a card that changes code cannot claim Ollama is unfit for it
        found = {"ollama": ollama_evidence, "agy": agy_evidence}.get(slot)
        if found is not None:
            found.append(f"skip {reason}: {skip.get('evidence')}")
    missing = [slot for slot, found in (("ollama", ollama_evidence), ("agy", agy_evidence)) if not found]
    return {"card": card, "ok": not missing, "ollama": ollama_evidence, "agy": agy_evidence, "missing": missing}


# U221: "done" is earned from the remote PR and the installed runtime, never from a label or a local ref.
DONE_FIELD_MAX = 160  # one plain sentence in the 3-line report
SHA40_RE = re.compile(r"[0-9a-f]{40}")  # the lower-case full sha that gh returns as headRefOid
RUNTIME_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z._+-]{0,127}")  # runtime_install names: <version>-<12 hex>
# Everything a reader may raise: each means "unknown", and unknown is never done.
DONE_READ_ERRORS = (merge_route.MergeRefused, TimeoutExpired, OSError, ValueError, KeyError, TypeError,
                    AttributeError, runtime_install.RuntimeError_)


def _real_agy_review(review, task: str) -> bool:
    """U192: schema hardening only. Count a record that has review.py's strict agy fields for this run dir's task.
    A hand-copied record still passes: this is not proof an agy run happened (Codex REVISE relay_0e17d7f3)."""
    if not isinstance(review, dict) or review.get("verdict") not in AGY_VERDICTS:
        return False
    usage, conv, bundle = review.get("usage"), review.get("judge_conversation_id"), review.get("bundle_id")
    tokens = usage.get("input_tokens") if isinstance(usage, dict) else None
    return (review.get("reviewer") == "agy" and review.get("task_id") == task and review.get("cost_gate") == "WITHIN"
            and isinstance(conv, str) and bool(conv) and type(tokens) is int and tokens > 0
            and isinstance(bundle, str) and bool(re.fullmatch(r"[0-9a-f]{64}", bundle)) and bundle != "0" * 64)


def _one_line(name, value) -> str:
    """U221: one plain line of at most DONE_FIELD_MAX characters; every str.splitlines separator is refused."""
    if not isinstance(value, str) or not value.strip() or len(value) > DONE_FIELD_MAX or value.splitlines() != [value]:
        raise ValueError(f"{name} must be one non-empty line of at most {DONE_FIELD_MAX} characters")
    return value.strip()


def _done_arg_problems(pr_url, head, runtime=None) -> list[str]:
    """U221: argument problems as a list, so check_done never raises and done_report refuses the same inputs."""
    problems = []
    if not (isinstance(pr_url, str) and merge_route.GITHUB_PR_RE.fullmatch(pr_url)):
        problems.append(f"BAD_PR_URL: {str(pr_url)[:80]!r} is not a https://github.com/<owner>/<repo>/pull/<n> url")
    if not (isinstance(head, str) and SHA40_RE.fullmatch(head)):
        problems.append(f"BAD_HEAD: {str(head)[:80]!r} is not a 40-hex lower-case commit sha")
    if runtime is not None and not (isinstance(runtime, str) and RUNTIME_RE.fullmatch(runtime)):
        problems.append(f"BAD_RUNTIME: {str(runtime)[:80]!r} is not a runtime version name")
    return problems


def done_report(project, card, what, pr_url, head, runtime=None, user_action=None, title: str | None = None) -> str:
    """U221: the 3-line completion report; check_done must pass before it is shown as done."""
    _check(card)
    name, what = _one_line("project", project), _one_line("what", what)
    core_title = clean_core_title(_one_line("title", title)) if title else ""
    if title is not None and (not core_title or is_bare_id_label(core_title)):
        raise ValueError(f"BARE_ID_REPORT_FORBIDDEN: title for {card} must be a human-readable core title, got {title!r}")
    runtime = _one_line("runtime", runtime) if runtime is not None else None
    action = _one_line("user_action", user_action) if user_action else None
    if _done_arg_problems(pr_url, head, runtime):
        raise ValueError("; ".join(_done_arg_problems(pr_url, head, runtime)))
    installed = f"런타임 {runtime}" if runtime else "런타임 설치가 필요 없는 변경"
    last = f"- **남은 일**: {action}" if action else "- 다음: 없음(새 세션부터 적용)"
    card_label = f"{core_title}({card})" if core_title else f"{name} {card} 작업"
    pr_no = pr_url.rsplit("/", 1)[1]  # U271: a short link label instead of a bare 70-character url
    return "\n".join((f"**결과**: {card_label} 완료 — {what}",
                      f"- 근거: [PR #{pr_no}]({pr_url}) 병합 {head[:7]} · {installed}", last))


def _head_ok(view, head) -> bool:
    """U221: head is the PR's headRefOid, or, for a squash or rebase merge, the merge commit that landed it."""
    merge = view.get("mergeCommit")
    landed = merge.get("oid") if isinstance(merge, dict) else None
    return head == view.get("headRefOid") or (landed is not None and head == landed)


def _remote_problems(checkout, pr_url, head, pr_reader) -> list[str]:
    """U221: the PR is MERGED under this url and head; any read failure is a problem (unknown is not done)."""
    try:
        view = pr_reader(int(pr_url.rsplit("/", 1)[1]), Path(checkout))
        state, url, head_ok = view["state"], view["url"], _head_ok(view, head)
    except DONE_READ_ERRORS as exc:
        return [f"REMOTE_UNKNOWN: {type(exc).__name__}: {str(exc)[:120]}"]
    problems = [f"REMOTE_NOT_MERGED: state={state!r}"] if state != "MERGED" else []
    problems += [f"REMOTE_URL_MISMATCH: {url!r}"] if url != pr_url else []
    problems += [] if head_ok else [f"REMOTE_HEAD_MISMATCH: {head[:7]} is neither the PR head nor its merge commit"]
    return problems


def _runtime_problems(runtime, uaos_home, runtime_verify) -> list[str]:
    """U221: the named runtime re-hashes clean against its manifest and is the one current.json points at."""
    if not runtime:
        return []
    home = Path(uaos_home) if uaos_home else Path.home()  # runtime_install keeps its tree under <home>/.uaos
    try:
        runtime_verify(home, runtime)
        current = runtime_install.read_current(home).get("version")
    except DONE_READ_ERRORS as exc:
        return [f"RUNTIME_UNVERIFIED: {runtime}: {type(exc).__name__}: {str(exc)[:120]}"]
    return [] if current == runtime else [f"RUNTIME_NOT_CURRENT: {runtime} != {current}"]


def check_done(checkout, pr_url, head, runtime=None, uaos_home=None, pr_reader=None, runtime_verify=None) -> list[str]:
    """U221: "done" is earned: the PR is MERGED on the remote with this url and head and, when named, the runtime
    verifies. Readers are injectable for tests; the defaults are the reviewed merge_route.pr_view and verify."""
    problems = _done_arg_problems(pr_url, head, runtime)
    if problems:
        return problems
    problems = _remote_problems(checkout, pr_url, head, pr_reader or merge_route.pr_view)
    return problems + _runtime_problems(runtime, uaos_home, runtime_verify or runtime_install.verify)


def sync_project_hub(checkout) -> dict[str, Any]:
    """U240: synchronize docs/00_DOCUMENT_INDEX.md and docs/00_DOCUMENT_HUB.html at card or project finish."""
    from v7_harness.docs_manager import ensure_doc_index, ensure_docs_dir, sync_doc_index

    root = Path(checkout)
    index_md = ensure_doc_index(root)
    sync_doc_index(root)
    hub_html = ensure_docs_dir(root) / "00_DOCUMENT_HUB.html"
    return {"ok": True, "index_md": str(index_md), "hub_html": str(hub_html)}
