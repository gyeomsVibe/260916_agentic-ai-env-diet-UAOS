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


def write_result(checkout, card, pr, mergeable, tests, blocker) -> dict[str, Any]:
    """U135: the result goes in the card's own checkout; a card worktree may not write the base checkout."""
    line = result_line(card, pr, mergeable, tests, blocker)
    path = Path(checkout) / ".coord" / "results" / f"{card}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {card} result ({datetime.date.today().isoformat()})\n\n{line}\n", encoding="utf-8")
    return {"ok": True, "path": str(path), "line": line}


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
                newest[path.stem] = (stamp, {"card": path.stem, "line": line, "path": str(path)})
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
        for path in sorted(Path(run_dir).glob(f"runs/{card}-*/review_agy.json")):
            try:
                review = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(review, dict) and review.get("verdict") in AGY_VERDICTS:
                agy_evidence.append(f"agy review {path.parent.name} {review['verdict']}")
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
