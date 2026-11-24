"""U332: the user desk is a router (docs: U329 note section 9.7), common core logic for all 3 tools.

A desk (agy, codex, claude) must not do long work itself: its context grew to ~190k tokens per call that way. Its job
is to turn one user directive into cards and send them on. Every step here keeps its state in files under
`.coord/directives/`, so a replaced or limited desk loses nothing.

Pipeline (one function, `route_directive`):
 1 capture verbatim (byte-exact) + atomic single-router claim   6 split by connectivity (+ depends_on)
 2 concretize (goal, success signal, non-goals, worst cases)    7 assign tool/model/effort (quota UNKNOWN = no paid route)
 3 classify quick vs card                                       8 manuals that link the verbatim directive, open windows
 4 dedupe against running cards                                 9 status: changed items only, 3 lines
 5 council needed? (flag only; the council itself is U329)      10 closing is the conductor's (judge, PR, reinstall)

Worst case first: every external helper (Ollama, U327 model router, U331 card map, window opener) is optional and
injected; a missing or failing one degrades to a deterministic fallback and never blocks capture. Nothing here
calls the network by itself: the default drafter is only used when the caller passes `use_ollama=True`.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable

TOOLS = ("codex", "claude", "antigravity")
SUCCESSION = TOOLS  # authority order of docs/27 section 4; also the order a router hands off in
DIR = Path(".coord") / "directives"
REGISTRY = "cards.json"  # this router's own card registry; U331's `.coord/nav/card_map.json` is read when present
# Why 3: U331 caps open companion cards at 3 per tool; a tool above the same count of open cards gets no new card.
MAX_OPEN_CARDS_PER_TOOL = 3
LOCK_STALE_S = 30.0  # a lock file older than this belongs to a dead process (held for milliseconds in practice)
LOCK_TIMEOUT_S = 10.0
# Why 0.5: below it two cards sharing only generic words would merge; the file-overlap test decides the strong cases.
SIMILARITY_THRESHOLD = 0.5
BORDERLINE_THRESHOLD = 0.3  # same nature and similarity in [0.3, 0.5): a new card linked to the old one, not a merge
QUICK_MAX_CHARS = 160  # a directive this short with no file and no build verb is a call or two, answered at the desk
OPEN_STATES = ("READY", "RUNNING", "WAITING", "LAUNCHING")

_FILE_RE = re.compile(r"[\w./\\-]+\.(?:py|md|json|toml|ya?ml|ps1|sh|js|ts|txt)\b")
_BUILD_RE = re.compile(r"구현|만들|추가|수정|고쳐|개선|리팩|implement|build|add |fix|refactor|create|write", re.I)
_QUESTION_RE = re.compile(r"[?？]\s*$|알려\s*줘|설명|뭐야|어때|왜\b|what|why|how ", re.I)
_DEPENDS_RE = re.compile(r"이후에|끝나면|끝난 뒤|결과를 (?:써서|이용|바탕)|선행|after (?:that|it|the)|then |depends on|based on the result", re.I)
_DESIGN_RE = re.compile(r"방향|설계|아키텍처|정책|바꾸|전환|design|architecture|policy|pivot|redesign", re.I)
_NEGATIVE_RE = re.compile(r"하지 ?(?:말|마)|금지|않는다|않도록|do not|don't|never|no \w+|out of scope", re.I)
_UNIT_RE = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+(.*\S)\s*$")
_TOKEN_RE = re.compile(r"[A-Za-z_]{3,}|[가-힣]{2,}")

WORST_CASE_ROWS = (
    ("peer tool absent or limited", "presence UNKNOWN/LIMITED, no ACK in 10 s", "abstain and continue", "limited-tool handoff"),
    ("quota unknown", "no admitted fresh reading", "no paid route; local-only or BLOCKED", "quota UNKNOWN test"),
    ("directive summary drifts from the original", "manual lacks the directive link or sha mismatch", "audit fails the manual", "manual without link"),
    ("two cards write one file", "owned file sets intersect", "merge into one card or run in sequence", "split rule test"),
)


# --------------------------------------------------------------------------- files, locks

def _dir(project: Path) -> Path:
    path = Path(project) / DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _atomic_write(path: Path, data: bytes) -> None:
    """Write beside the target then replace, so a crash leaves the old file or the new one, never half of it."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
    with open(tmp, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    for attempt in range(40):  # Windows: the target may be open in a reader for a moment
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.01 * (attempt + 1))
    os.replace(tmp, path)


def _write_json(path: Path, data: Any) -> None:
    _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"))


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


class _Lock:
    """Cross-process lock by exclusive file creation (works on Windows and POSIX); a stale file is reclaimed."""

    def __init__(self, path: Path, timeout_s: float = LOCK_TIMEOUT_S) -> None:
        self.path, self.timeout_s = path, timeout_s

    def __enter__(self) -> "_Lock":
        deadline = time.monotonic() + self.timeout_s
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except (FileExistsError, PermissionError):  # Windows reports a file pending delete as PermissionError
                try:
                    if time.time() - self.path.stat().st_mtime > LOCK_STALE_S:
                        self.path.unlink()
                        continue
                except OSError:
                    pass
                if time.monotonic() > deadline:
                    raise TimeoutError(f"desk_router lock busy: {self.path.name}")
                time.sleep(0.01)

    def __exit__(self, *exc: Any) -> None:
        try:
            self.path.unlink()
        except OSError:
            pass


# --------------------------------------------------------------------------- 1. capture + claim

def d_id_path(project: Path, d_id: str) -> Path:
    return _dir(project) / f"{d_id}.md"


def capture(project: Path, raw: bytes | str, *, source_tool: str = "", now: float | None = None,
            event_id: str = "") -> dict[str, Any]:
    """Store the directive byte-exact as `D-0001.md`; ids come from exclusive creation, so a burst is ordered and lossless.

    The `.md` holds only the user's bytes. Metadata lives in `D-0001.json`; a crash between the two leaves a
    directive without metadata, which `list_directives` still reports (the words are never lost).
    """
    from . import desk_ledger

    folder = _dir(project)
    entry = desk_ledger.append_directive(project, raw, tool=source_tool, event_id=event_id, now=now)
    if entry.get("replay"):  # same native event again: the first directive, never a second one
        return {**(_read_json(folder / f"{entry['d_id']}.json", None) or {"d_id": entry["d_id"]}), "replay": True}
    meta = {"d_id": entry["d_id"], "seq": entry["seq"], "sha256": entry["sha256"], "bytes": entry["bytes"], "kind": entry["kind"],
            "received_at": entry["at"], "source_tool": source_tool, "state": "RECEIVED"}
    _write_json(folder / f"{entry['d_id']}.json", meta)
    return meta


def claim(project: Path, d_id: str, tool: str, *, now: float | None = None) -> dict[str, Any]:
    """Atomic single-router claim: exactly one caller creates `<D-ID>.claim.json`; the others become peers."""
    path = _dir(project) / f"{d_id}.claim.json"
    record = {"d_id": d_id, "owner": tool, "claimed_at": time.time() if now is None else now, "history": [], "epoch": 1}
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        # The winner writes its record right after creation; a peer may arrive in that gap, so wait for it briefly.
        for _ in range(100):
            current = _read_json(path, None)
            if isinstance(current, dict) and current.get("owner"):
                return {"won": False, "owner": current["owner"], "role": "peer"}
            time.sleep(0.01)
        return {"won": False, "owner": None, "role": "peer"}
    with os.fdopen(fd, "wb") as handle:
        handle.write(json.dumps(record, ensure_ascii=False).encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    return {"won": True, "owner": tool, "role": "router", "epoch": 1}


def desk_ledger_text(project: Path, d_id: str) -> str:
    from . import desk_ledger

    return desk_ledger.text_of(project, d_id)


def claim_epoch(project: Path, d_id: str) -> int:
    """Fencing token: bumped on every handoff, so a router that lost ownership can tell its writes are stale."""
    record = _read_json(_dir(project) / f"{d_id}.claim.json", None)
    return int(record.get("epoch", 1)) if isinstance(record, dict) else 0


def is_router(project: Path, d_id: str, tool: str, epoch: int) -> bool:
    record = _read_json(_dir(project) / f"{d_id}.claim.json", None)
    return isinstance(record, dict) and record.get("owner") == tool and int(record.get("epoch", 1)) == int(epoch)


def current_owner(project: Path, d_id: str) -> str | None:
    record = _read_json(_dir(project) / f"{d_id}.claim.json", None)
    return record.get("owner") if isinstance(record, dict) else None


def hand_off_if_limited(project: Path, d_id: str, states: dict[str, str], *, now: float | None = None) -> dict[str, Any]:
    """Router handoff: when the owning tool is not ACTIVE, the next ACTIVE tool in authority order becomes the router.

    UNKNOWN counts as not active (fail closed). No ACTIVE tool -> the directive stays owned and is reported BLOCKED.
    """
    path = _dir(project) / f"{d_id}.claim.json"
    with _Lock(path.with_name(path.name + ".lock")), _Lock(_dir(project) / ".registry.lock"):  # registry lock: no commit interleaves
        record = _read_json(path, None)
        if not isinstance(record, dict) or not record.get("owner"):
            return {"handed_off": False, "reason": "NO_CLAIM", "owner": None}
        owner = record["owner"]
        if str(states.get(owner, "UNKNOWN")).upper() == "ACTIVE":
            return {"handed_off": False, "reason": "OWNER_ACTIVE", "owner": owner}
        successor = next((t for t in SUCCESSION if t != owner and str(states.get(t, "UNKNOWN")).upper() == "ACTIVE"), None)
        if successor is None:
            return {"handed_off": False, "reason": "BLOCKED_NO_ACTIVE_TOOL", "owner": owner}
        record["history"] = [*record.get("history", []), {"from": owner, "to": successor, "reason": f"owner {states.get(owner, 'UNKNOWN')}",
                                                          "at": time.time() if now is None else now}]
        record["owner"] = successor
        record["epoch"] = int(record.get("epoch", 1)) + 1
        _write_json(path, record)
        return {"handed_off": True, "reason": "OWNER_NOT_ACTIVE", "from": owner, "owner": successor}


def list_directives(project: Path) -> list[dict[str, Any]]:
    """All captured directives in arrival order (by sequence), including ones whose metadata never got written."""
    folder = _dir(project)
    out = []
    for path in sorted(folder.glob("D-[0-9][0-9][0-9][0-9].md"), key=lambda p: int(p.stem[2:])):
        meta = _read_json(folder / f"{path.stem}.json", None) or {"d_id": path.stem, "seq": int(path.stem[2:]), "state": "NO_METADATA"}
        out.append(meta)
    return out


# --------------------------------------------------------------------------- 2. concretize

def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?。])\s+|\n+", text) if s.strip()]


def deterministic_concretize(text: str) -> dict[str, Any]:
    """The no-model fallback: first sentence is the goal; the success signal is the first line naming a test, gate or number."""
    lines = _sentences(text)
    goal = (lines[0] if lines else text.strip())[:240]
    signal = next((s for s in lines if re.search(r"테스트|통과|gate|test|pass|exit|\d", s, re.I)), "")
    non_goals = [s[:200] for s in lines if _NEGATIVE_RE.search(s)]
    return {"goal": goal,
            "success_signal": signal[:240] or "fixed acceptance test passes and the full test suite shows no new failure",
            "non_goals": non_goals, "worst_cases": [list(row) for row in WORST_CASE_ROWS], "source": "deterministic"}


def concretize(text: str, drafter: Callable[..., str] | None = None, *, project: Path | None = None) -> dict[str, Any]:
    """Ollama drafts, the router checks: a draft is used only if it parses and every field has the right type."""
    if project is not None:
        from . import idea_fullstack

        adapted_drafter: Callable[[str, dict[str, Any]], str] | None = None
        if drafter is not None:
            def _wrapped(prompt: str, schema: dict[str, Any]) -> str:
                try:
                    raw_out = drafter(prompt, schema)
                except TypeError:
                    raw_out = drafter(prompt)
                try:
                    parsed = json.loads(raw_out)
                except Exception:
                    return raw_out
                if (
                    isinstance(parsed, dict)
                    and "problem_statement" not in parsed
                    and isinstance(parsed.get("goal"), str)
                    and isinstance(parsed.get("success_signal"), str)
                    and isinstance(parsed.get("non_goals"), list)
                ):
                    parsed = {
                        "goal": parsed["goal"],
                        "problem_statement": parsed["goal"],
                        "measurable_success_signals": [parsed["success_signal"]],
                        "non_goals": parsed["non_goals"],
                        "risks_and_rollback": [],
                        "candidate_domains": [],
                        "ambiguities": [],
                        "clarification_questions": [],
                    }
                    return json.dumps(parsed, ensure_ascii=False)
                return raw_out
            adapted_drafter = _wrapped

        full = idea_fullstack.concretize_raw_idea(Path(project), text, drafter=adapted_drafter)
        return {
            "goal": full["goal"],
            "success_signal": full["measurable_success_signals"][0],
            "measurable_success_signals": full["measurable_success_signals"],
            "non_goals": full["non_goals"],
            "worst_cases": [list(row) for row in WORST_CASE_ROWS],
            "grounded_files": full["grounded_files"],
            "mia_tier": full["mia_tier"],
            "clarification_questions": full["clarification_questions"],
            "source": full["source"],
        }

    base = deterministic_concretize(text)
    if drafter is None:
        return base
    prompt = ("Return ONLY JSON with keys goal (string), success_signal (string, measurable), non_goals (list of strings), "
              "worst_cases (list of [worst case, detection, fallback, test]). Directive:\n" + text)
    try:
        draft = json.loads(drafter(prompt))
        ok = (isinstance(draft, dict) and isinstance(draft.get("goal"), str) and draft["goal"].strip()
              and isinstance(draft.get("success_signal"), str) and draft["success_signal"].strip()
              and isinstance(draft.get("non_goals"), list) and all(isinstance(x, str) for x in draft["non_goals"])
              and isinstance(draft.get("worst_cases"), list)
              and all(isinstance(r, list) and len(r) == 4 and all(isinstance(c, str) for c in r) for r in draft["worst_cases"]))
    except Exception:  # Ollama down, timeout, bad JSON: all the same answer, the deterministic draft
        return {**base, "source": "deterministic_fallback"}
    if not ok:
        return {**base, "source": "deterministic_fallback"}
    return {"goal": draft["goal"].strip()[:240], "success_signal": draft["success_signal"].strip()[:240],
            "non_goals": draft["non_goals"], "worst_cases": draft["worst_cases"] or base["worst_cases"], "source": "ollama"}


def default_drafter(prompt: str, fmt: dict[str, Any] | str | None = None) -> str:  # pragma: no cover - needs a local Ollama server; tests inject a drafter
    from v7_harness import olla
    from v7_harness.adapters.ollama_vram_guard import (
        choose_vram_safe_ctx,
        estimate_prompt_tokens,
        normalize_keep_alive,
    )

    if not olla._server_up():
        raise RuntimeError("ollama down")
    ctx = choose_vram_safe_ctx(estimate_prompt_tokens(prompt), max_ctx=8192, num_predict=1024)
    body = olla._post(
        "/api/generate",
        {
            "model": olla.CHAT_MODEL,
            "prompt": prompt,
            "stream": False,
            "format": fmt if fmt is not None else "json",
            "keep_alive": normalize_keep_alive("10m"),
            "options": {"num_ctx": ctx, "temperature": 0.1},
        },
        timeout=60,
    )
    return str(body.get("response", ""))


# --------------------------------------------------------------------------- 3. classify

def extract_files(text: str) -> set[str]:
    return {m.replace("\\", "/").lstrip("./") for m in _FILE_RE.findall(text)}


_RESOURCE_RES = (re.compile(r"(?:port|포트)\s*[:=]?\s*(\d{2,5})", re.I),
                 re.compile(r"(?<![A-Za-z])(sqlite|database|db|hook|훅|runtime|재설치|install|release|배포)(?![A-Za-z])", re.I))


def extract_resources(text: str) -> set[str]:
    """Shared non-file resources (a port, a DB, a global hook, runtime install, release): disjoint files can still collide here."""
    out = {f"port:{m}" for m in _RESOURCE_RES[0].findall(text)}
    kinds = {"sqlite": "db", "database": "db", "db": "db", "훅": "hook", "재설치": "runtime", "install": "runtime", "배포": "release"}
    out |= {f"res:{kinds.get(m.lower(), m.lower())}" for m in _RESOURCE_RES[1].findall(text)}
    return out


def classify(text: str) -> str:
    """`quick` = answered at the desk in a call or two; anything with a file, a build verb or real length is a `card`."""
    body = text.strip()
    if extract_files(body) or _BUILD_RE.search(body) and len(body) > QUICK_MAX_CHARS // 2:
        return "card"
    if len(body) <= QUICK_MAX_CHARS and (_QUESTION_RE.search(body) or not _BUILD_RE.search(body)):
        return "quick"
    return "card"


def infer_lane(text: str) -> str:
    try:
        from .helper_thinking_router import infer_lane_from_card_metadata

        return infer_lane_from_card_metadata(title=text, purpose=text, role="implementer", sub_stage="")
    except Exception:
        return "IMPL_CODE"


# --------------------------------------------------------------------------- 4. dedupe

def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text)}


def similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def running_cards(project: Path) -> list[dict[str, Any]]:
    """Open cards from U331's map when it exists (optional import by file), plus this router's own registry."""
    cards: dict[str, dict[str, Any]] = {}
    nav = _read_json(Path(project) / ".coord" / "nav" / "card_map.json", {})
    for item in (nav.get("cards") if isinstance(nav, dict) else None) or []:
        if isinstance(item, dict) and item.get("id"):
            cards[str(item["id"])] = {"id": str(item["id"]), "status": str(item.get("status", "RUNNING")).upper(),
                                      "files": sorted(item.get("files") or item.get("owned_files") or []),
                                      "lane": item.get("lane", ""), "title": item.get("title", ""), "tool": item.get("tool", "")}
    registry = _read_json(_dir(project) / REGISTRY, {})
    for cid, item in (registry.get("cards", {}) if isinstance(registry, dict) else {}).items():
        cards.setdefault(cid, item)
    return [c for c in cards.values() if c.get("status") in OPEN_STATES]


def files_overlap(a: set[str], b: set[str]) -> set[str]:
    """Exact matches plus a bare file name (`stall.py`) matching a path ending in it: letters rarely spell the full path."""
    hit = set(a & b)
    for x in a:
        for y in b:
            if x != y and ("/" not in x or "/" not in y) and x.rsplit("/", 1)[-1] == y.rsplit("/", 1)[-1]:
                hit.add(x if len(x) >= len(y) else y)
    return hit


def find_duplicate(text: str, files: set[str], lane: str, cards: list[dict[str, Any]],
                   resources: set[str] | None = None) -> dict[str, Any] | None:
    """Same owned file or shared resource, or same nature plus similar words: add to that card instead of opening another."""
    best: tuple[float, dict[str, Any], str] | None = None
    for card in cards:
        overlap = files_overlap(files, set(card.get("files") or []))
        shared_res = set(resources or ()) & set(card.get("resources") or [])
        if overlap:
            score, why = 1.0, f"same file: {sorted(overlap)[0]}"
        elif shared_res:
            score, why = 1.0, f"same resource: {sorted(shared_res)[0]}"
        else:
            score = similarity(text, str(card.get("title", "")) + " " + str(card.get("directive_text", "")))
            if card.get("lane") != lane or score < BORDERLINE_THRESHOLD:
                continue
            why = f"same nature {lane}, similarity {score:.2f}"
        if best is None or score > best[0]:
            best = (score, card, why)
    if best is None:
        return None
    # related -> the running card's window gets the verbatim directive; borderline -> a new card linked to the old one
    return {"card": best[1]["id"], "score": best[0], "reason": best[2],
            "kind": "related" if best[0] >= SIMILARITY_THRESHOLD else "borderline"}


# --------------------------------------------------------------------------- 6. split by connectivity

def split_units(text: str) -> list[str]:
    """Numbered or bulleted lines are separate units; text with none is one unit."""
    units = [m.group(1) for line in text.splitlines() if (m := _UNIT_RE.match(line))]
    return units if len(units) > 1 else [text.strip()]


def plan_split(units: list[str]) -> list[dict[str, Any]]:
    """Cards from units. Shared file -> one card. Unknown files -> cannot prove disjoint -> one card (worst case).
    Disjoint files and an explicit result dependency -> two cards, the later one `depends_on` the earlier (it starts
    when the earlier is DONE). Disjoint and independent -> two parallel cards."""
    parent = list(range(len(units)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    files = [extract_files(u) for u in units]
    res = [extract_resources(u) for u in units]
    blind = [i for i, f in enumerate(files) if not f]
    for i in range(len(units)):
        for j in range(i + 1, len(units)):
            if files[i] & files[j] or res[i] & res[j]:
                parent[find(j)] = find(i)
    for i in blind[1:]:
        parent[find(i)] = find(blind[0])
    if blind and len(blind) < len(units):  # a unit with unknown files may touch any other unit's files
        for i in range(len(units)):
            parent[find(i)] = find(blind[0])
    groups: dict[int, list[int]] = {}
    for i in range(len(units)):
        groups.setdefault(find(i), []).append(i)
    ordered = sorted(groups.values(), key=lambda g: g[0])
    cards = []
    for n, members in enumerate(ordered, start=1):
        cards.append({"key": f"C{n}", "units": [units[i] for i in members], "members": members,
                      "files": sorted(set().union(*(files[i] for i in members))), "depends_on": []})
    for n, card in enumerate(cards):
        if n and any(_DEPENDS_RE.search(u) for u in card["units"]):
            card["depends_on"] = [cards[n - 1]["key"]]
    return cards


# --------------------------------------------------------------------------- 7. assign

def _quota_ok(admitted: dict[str, Any] | None, tool: str) -> bool:
    return (admitted or {}).get(tool) is True  # anything but an exact True (None/UNKNOWN/False) fails closed


def select_model(tool: str, *, purpose: str, lane: str, multi_file: bool) -> dict[str, Any]:
    """U327's registry when importable, else the current helper/thinking router; failure returns an explicit UNSET."""
    try:
        from . import model_router  # U327 (optional integration point)

        for name in ("select_model", "select_for_card", "route"):
            fn = getattr(model_router, name, None)
            if callable(fn):
                picked = fn(tool, purpose=purpose, lane_id=lane, multi_file=multi_file)
                if isinstance(picked, dict):
                    return {"source": "model_router", **picked}
    except Exception:
        pass
    try:
        from .helper_thinking_router import select_optimal_helper_and_thinking

        picked = select_optimal_helper_and_thinking(tool, purpose=purpose, lane_id=lane, multi_file=multi_file)
        return {"source": "helper_thinking_router", "model": picked.get("reasoning_model"),
                "effort": picked.get("reasoning_thinking"), "helper_model": picked.get("helper_model")}
    except Exception as error:
        return {"source": "UNSET", "model": None, "effort": None, "error": str(error)[:120]}


def assign_tool(lane: str, states: dict[str, str], admitted: dict[str, Any] | None, open_counts: dict[str, int]) -> dict[str, Any]:
    """First tool in the lane's owner order that is ACTIVE, has admitted quota (exact True) and is not overloaded."""
    try:
        from .participation import LANE_PREFS

        order = LANE_PREFS.get(lane, LANE_PREFS["IMPL_CODE"])["owner"]
    except Exception:
        order = SUCCESSION
    skipped = {}
    for tool in order:
        if str(states.get(tool, "UNKNOWN")).upper() != "ACTIVE":
            skipped[tool] = f"presence {states.get(tool, 'UNKNOWN')}"
        elif not _quota_ok(admitted, tool):
            skipped[tool] = "quota UNKNOWN or not admitted"
        elif open_counts.get(tool, 0) >= MAX_OPEN_CARDS_PER_TOOL:
            skipped[tool] = "overloaded"
        else:
            return {"tool": tool, "paid": True, "skipped": skipped}
    reason = "BLOCKED_QUOTA_UNKNOWN" if any("quota" in v for v in skipped.values()) else "BLOCKED_NO_ACTIVE_TOOL"
    return {"tool": None, "paid": False, "blocked": reason, "skipped": skipped}


# --------------------------------------------------------------------------- 8. manuals

def directive_link(d_id: str, sha: str) -> str:
    return f"Directive: .coord/directives/{d_id}.md (sha256 {sha})"


def build_manual(card: str, title: str, d_id: str, sha: str, concrete: dict[str, Any], unit_text: str, files: list[str],
                 assignment: dict[str, Any], depends_on: list[str]) -> str:
    rows = "\n".join("| " + " | ".join(r) + " |" for r in concrete["worst_cases"])
    non_goals = "\n".join(f"- {n}" for n in concrete["non_goals"]) or "- (none stated; do not widen scope)"
    return (f"# {card} contract manual - {title}\n\n{directive_link(d_id, sha)}\n\n"
            f"Assigned: tool={assignment.get('tool')} model={assignment.get('model')} effort={assignment.get('effort')} "
            f"depends_on={','.join(depends_on) or '-'}\n\n"
            f"## Goal\n{concrete['goal']}\n\n## Success signal\n{concrete['success_signal']}\n\n"
            f"## Non-goals\n{non_goals}\n\n## Owned files\n" + ("\n".join(f"- {f}" for f in files) or "- (unknown: ask before editing)") +
            f"\n\n## This card's part of the directive\n{unit_text}\n\n"
            f"## Worst-case table\n| Worst case | Detection | Fallback | Test |\n|---|---|---|---|\n{rows}\n\n"
            "## Stages\n1. Research\n2. MIA\n3. Execute\n4. Verify\n")


def manual_problems(project: Path, manual_text: str) -> list[str]:
    """Audit hook for U330's `card audit`: a manual must link an existing directive file with a matching sha256."""
    match = re.search(r"^Directive:\s*(\S+)\s+\(sha256 ([0-9a-f]{64})\)\s*$", manual_text, re.M)
    if not match:
        return ["MANUAL_MISSING_DIRECTIVE_LINK"]
    target = (Path(project) / match.group(1)).resolve()
    if not target.is_relative_to((Path(project) / ".coord" / "directives").resolve()):
        return ["DIRECTIVE_PATH_OUTSIDE_PROJECT"]  # a manual may not point the audit at an arbitrary file
    try:
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
    except OSError:
        return ["DIRECTIVE_FILE_MISSING"]
    return [] if actual == match.group(2) else ["DIRECTIVE_SHA_MISMATCH"]


def default_opener(project: Path, card: str, tool: str, title: str, manual_path: Path) -> dict[str, Any]:  # pragma: no cover
    """Opens the card's window through the existing `coord window` API; never raises (a failed open is reported)."""
    from . import windows

    try:
        if tool == "claude":
            return {"opened": False, "pending": "claude_session_needed", **windows.route_window(Path(project), card)}
        result = windows.open_window(Path(project), card, tool, title, manual_path.read_text(encoding="utf-8"))
        return {"opened": bool(result.get("id")), **result}
    except Exception as error:
        return {"opened": False, "error": str(error)[:160]}


# --------------------------------------------------------------------------- the pipeline

def route_directive(project: Path, raw: bytes | str, *, tool: str, states: dict[str, str], admitted: dict[str, Any] | None = None,
                    drafter: Callable[[str], str] | None = None,
                    opener: Callable[[Path, str, str, str, Path], dict[str, Any]] | None = None,
                    allocate_card: Callable[[], str] | None = None, now: float | None = None,
                    event_id: str = "") -> dict[str, Any]:
    project = Path(project)
    meta = capture(project, raw, source_tool=tool, now=now, event_id=event_id)
    d_id, folder = meta["d_id"], _dir(project)
    resume = False
    if meta.get("replay"):  # same native event again: never route, claim or launch twice
        # P1-1: ...unless the first attempt died before it finished. No plan (state RECEIVED/LAUNCHING) means the
        # routing never completed, so the same router resumes it; cards already in the registry are not relaunched.
        if meta.get("plan") or meta.get("state") not in ("RECEIVED", "LAUNCHING", None) or meta.get("kind") == "stop":
            return {"d_id": d_id, "role": "replay", "state": "REPLAY", "cards": (meta.get("plan") or {}).get("cards", [])}
        resume = True
        text = desk_ledger_text(project, d_id) or (raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw)
    else:
        text = (raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw)
    if meta.get("kind") == "stop":  # already propagated to every open card by the ledger append
        return {"d_id": d_id, "role": "router", "router": tool, "state": "STOPPED", "cards": []}
    won = claim(project, d_id, tool, now=now)
    if resume and not won["won"] and won["owner"] == tool:
        won = {"won": True, "owner": tool, "role": "router"}  # my own earlier claim: continue, do not become a peer of myself
    if not won["won"]:
        return {"d_id": d_id, "role": "peer", "router": won["owner"], "state": "PEER", "cards": []}
    epoch = claim_epoch(project, d_id)
    concrete = concretize(text, drafter, project=project)
    files, lane = extract_files(text), infer_lane(text)
    kind = classify(text)
    from . import desk_ledger

    clash = [c for c in desk_ledger.conflicts(desk_ledger.read_since(project, max(0, meta["seq"] - 21))) if f"{d_id}(" in c.split(" overrides ")[0]]
    plan: dict[str, Any] = {"d_id": d_id, "role": "router", "router": tool, "class": kind, "lane": lane, "concrete": concrete,
                            "council": bool(_DESIGN_RE.search(text)) or bool(clash), "conflicts": clash, "cards": []}
    if kind == "quick":
        plan["state"] = "QUICK_AT_DESK"
        if not _commit(project, meta, plan, {}, tool, epoch):
            return {"d_id": d_id, "role": "superseded", "state": "SUPERSEDED", "router": current_owner(project, d_id), "cards": []}
        return plan
    cards_now = running_cards(project)
    dup = find_duplicate(text, files, lane, [c for c in cards_now if c.get("d_id") != d_id], extract_resources(text))
    if dup and dup["kind"] == "borderline":
        plan["linked_to"] = dup["card"]
    if dup and dup["kind"] == "related":
        extra = folder / f"{dup['card']}.addenda.md"
        with _Lock(folder / f".{dup['card']}.addenda.lock"):
            old = extra.read_bytes() if extra.exists() else b""
            _atomic_write(extra, old + f"\n--- {d_id} sha256 {meta['sha256']}\n".encode() + (raw if isinstance(raw, bytes) else raw.encode("utf-8")) + b"\n")
        queue_addendum(project, dup["card"], d_id)  # 9.7-1: applied at the card's next safe checkpoint, not by interrupting it
        plan.update(state="ADDED_TO_EXISTING", duplicate=dup)
        if not _commit(project, meta, plan, {}, tool, epoch):
            return {"d_id": d_id, "role": "superseded", "state": "SUPERSEDED", "router": current_owner(project, d_id), "cards": []}
        return plan
    open_counts: dict[str, int] = {}
    for card in cards_now:
        open_counts[card.get("tool", "")] = open_counts.get(card.get("tool", ""), 0) + 1
    opener = opener or default_opener
    keys: dict[str, str] = {}
    existing_cards: set[str] = set()  # cards a previous attempt already dispatched (never overwritten, never relaunched)
    registry_add: dict[str, Any] = {}
    manuals = _dir(project) / "manuals"
    manuals.mkdir(parents=True, exist_ok=True)
    for spec in plan_split(split_units(text)):
        card_id = allocate_card() if allocate_card else f"{d_id.replace('-', '')}-{spec['key']}"
        keys[spec["key"]] = card_id
        deps = [keys[k] for k in spec["depends_on"]]
        card_files = list(spec["files"]) if spec["files"] else list(concrete.get("grounded_files") or ())
        assign = assign_tool(lane, states, admitted, open_counts)
        chosen = assign["tool"]
        picked = select_model(chosen, purpose=spec["units"][0], lane=lane, multi_file=len(card_files) > 1) if chosen else {}
        assignment = {"tool": chosen, "paid": assign["paid"], "model": picked.get("model"), "effort": picked.get("effort"),
                      "model_source": picked.get("source"), "blocked": assign.get("blocked"), "skipped": assign["skipped"]}
        title = spec["units"][0][:60]
        manual = build_manual(card_id, title, d_id, meta["sha256"], concrete, "\n".join(spec["units"]), card_files, assignment, deps)
        manual_path = manuals / f"{card_id}.md"
        _atomic_write(manual_path, manual.encode("utf-8"))
        if not chosen:
            state, window = "BLOCKED", {"opened": False, "reason": assign.get("blocked")}
        elif deps:
            state, window = "WAITING", {"opened": False, "reason": f"waits for {','.join(deps)}"}  # advance() opens it
        else:
            # ONE atomic step under the registry lock: owner/epoch check + "card not yet dispatched" + durable LAUNCHING
            # intent. Only the caller that gets NEW may launch; a crash after launch leaves LAUNCHING, which a replay
            # never relaunches and which is reconciled against the session readback, not re-opened.
            verdict = _claim_dispatch(project, d_id, tool, epoch, {
                "id": card_id, "title": title, "status": "LAUNCHING", "tool": chosen, "files": card_files,
                "resources": sorted(extract_resources(" ".join(spec["units"]))), "lane": lane, "depends_on": deps, "d_id": d_id})
            if verdict == "FENCED":
                return {"d_id": d_id, "role": "superseded", "state": "SUPERSEDED", "router": current_owner(project, d_id), "cards": plan["cards"]}
            if verdict == "EXISTS":  # already dispatched (replay or a concurrent same-owner caller): never launch twice
                state, window = "LAUNCHING", {"opened": False, "reason": "already dispatched"}
                existing_cards.add(card_id)
            else:
                try:
                    window = opener(project, card_id, chosen, title, manual_path)
                except Exception as error:
                    window = {"opened": False, "error": str(error)[:160]}
                state = "RUNNING" if window.get("opened") else "READY"
                open_counts[chosen] = open_counts.get(chosen, 0) + 1
        entry = {"id": card_id, "title": title, "status": state, "tool": chosen, "files": card_files, "lane": lane,
                 "resources": sorted(extract_resources(" ".join(spec["units"]))),
                 "depends_on": deps, "d_id": d_id, "linked_to": plan.get("linked_to"),
                 "manual": str(manual_path.relative_to(project)).replace("\\", "/"),
                 "directive_text": " ".join(spec["units"])[:400]}
        registry_add[card_id] = entry
        plan["cards"].append({**entry, "assignment": assignment, "window": window})
    plan["state"] = "ROUTED"
    if not _commit(project, meta, plan, {k: v for k, v in registry_add.items() if k not in existing_cards}, tool, epoch):
        return {"d_id": d_id, "role": "superseded", "state": "SUPERSEDED", "router": current_owner(project, d_id), "cards": plan["cards"]}
    try:
        from . import uaos_fullstack_os

        uaos_fullstack_os.sync_routed_plan(project, plan, now=now)
    except Exception:  # noqa: BLE001 - durable OS mirror is additive and never breaks directive routing
        pass
    return plan


def _register(folder: Path, entries: dict[str, Any]) -> None:
    with _Lock(folder / ".registry.lock"):
        registry = _read_json(folder / REGISTRY, {"cards": {}})
        registry.setdefault("cards", {}).update(entries)
        _write_json(folder / REGISTRY, registry)


def _claim_dispatch(project: Path, d_id: str, tool: str, epoch: int, entry: dict[str, Any]) -> str:
    """Atomic dispatch claim: NEW (intent written, caller may launch), EXISTS (already dispatched) or FENCED (not the router)."""
    folder = _dir(project)
    with _Lock(folder / ".registry.lock"):
        if not is_router(project, d_id, tool, epoch):  # handoff also holds this lock, so owner/epoch cannot move under us
            return "FENCED"
        registry = _read_json(folder / REGISTRY, {"cards": {}})
        cards = registry.setdefault("cards", {})
        if entry["id"] in cards:
            return "EXISTS"
        cards[entry["id"]] = entry
        _write_json(folder / REGISTRY, registry)
        return "NEW"


def _commit(project: Path, meta: dict[str, Any], plan: dict[str, Any], entries: dict[str, Any], tool: str, epoch: int) -> bool:
    """Final write of the cards and the directive's plan in ONE transaction that re-checks owner and epoch (False = fenced)."""
    folder = _dir(project)
    with _Lock(folder / ".registry.lock"):
        if not is_router(project, meta["d_id"], tool, epoch):
            return False
        if entries:
            registry = _read_json(folder / REGISTRY, {"cards": {}})
            registry.setdefault("cards", {}).update(entries)
            _write_json(folder / REGISTRY, registry)
        _write_json(folder / f"{meta['d_id']}.json", {**meta, "state": plan["state"], "plan": plan})
    return True


def advance(project: Path, *, opener: Callable[..., dict[str, Any]] | None = None) -> list[str]:
    """Auto-start successors: a WAITING card opens when everything it depends_on is DONE. Returns the started card ids.

    Three phases so the external launch never runs under the registry lock: (1) under the lock, mark each GO card
    LAUNCHING (the durable, fenced intent; a concurrent advance sees it and skips), (2) launch outside the lock,
    (3) under the lock, record the outcome unless a stop or another writer changed the card meanwhile."""
    project, folder, opener = Path(project), _dir(project), opener or default_opener
    claimed: list[tuple[str, dict[str, Any]]] = []
    with _Lock(folder / ".registry.lock"):
        registry = _read_json(folder / REGISTRY, {"cards": {}})
        cards = registry.get("cards", {})
        sig = compute_signals(cards)  # the signalman: a WAITING card starts only on GO (deps DONE, no earlier card on its files)
        for cid, card in cards.items():
            if card.get("status") == "WAITING" and card.get("tool") and sig.get(cid, {}).get("signal") == "GO":
                card["status"] = "LAUNCHING"
                claimed.append((cid, dict(card)))
        if claimed:
            _write_json(folder / REGISTRY, registry)
    started: list[str] = []
    for cid, card in claimed:
        with _Lock(folder / ".registry.lock"):  # a stop committed after this card was pre-claimed cancels it: never launch it
            live = _read_json(folder / REGISTRY, {"cards": {}}).get("cards", {}).get(cid)
        if live is None or live.get("status") != "LAUNCHING":
            continue
        try:
            res = opener(project, cid, card["tool"], card.get("title", cid), project / card["manual"])
        except Exception as error:
            res = {"opened": False, "error": str(error)[:160]}
        with _Lock(folder / ".registry.lock"):
            registry = _read_json(folder / REGISTRY, {"cards": {}})
            current = registry.get("cards", {}).get(cid)
            if current is not None and current.get("status") == "LAUNCHING":  # a stop (STOPPED) is never overwritten
                current["status"] = "RUNNING" if res.get("opened") else "READY"
                _write_json(folder / REGISTRY, registry)
        started.append(cid)
    return started


def set_card_status(project: Path, card: str, status: str) -> None:
    folder = _dir(Path(project))
    with _Lock(folder / ".registry.lock"):
        registry = _read_json(folder / REGISTRY, {"cards": {}})
        if card in registry.get("cards", {}):
            registry["cards"][card]["status"] = status
            _write_json(folder / REGISTRY, registry)


# --------------------------------------------------------------------------- signalman, traffic control, dispatcher helpers (9.7, 9.7-1)

def _authority_rank(tool: Any) -> int:
    return SUCCESSION.index(tool) if tool in SUCCESSION else len(SUCCESSION)


def compute_signals(cards: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """GO / WAIT per open card (pure). Of two open cards touching one file only the better-ranked is GO; a card also
    waits for every depends_on card that is not DONE. Rank: already running first, then authority order, then id.
    A wait cycle (A waits B, B waits A) is cut by rank: the better-ranked card ignores the edge, so one side is GO."""
    open_ = {cid: c for cid, c in cards.items() if c.get("status") in OPEN_STATES}

    def rank(cid: str) -> tuple[int, int, str]:
        c = cards[cid]
        return (0 if c.get("status") in ("RUNNING", "LAUNCHING") else 1, _authority_rank(c.get("tool")), cid)

    def reaches(start: str, goal: str, seen: set[str]) -> bool:
        if start == goal:
            return True
        seen.add(start)
        return any(d not in seen and reaches(d, goal, seen) for d in (cards.get(start, {}).get("depends_on") or []) if cards.get(d, {}).get("status") != "DONE")

    out: dict[str, dict[str, Any]] = {}
    for cid, card in open_.items():
        waits: list[str] = []
        for dep in (card.get("depends_on") or []):
            if cards.get(dep, {}).get("status") == "DONE":
                continue
            cyclic = reaches(dep, cid, set())
            if not (cyclic and rank(cid) < rank(dep)):
                waits.append(dep)
        mine = set(card.get("files") or [])
        my_res = set(card.get("resources") or [])  # P1-2: disjoint files can still collide on a port/db/hook/release
        for oid, other in open_.items():
            collide = mine & set(other.get("files") or []) or my_res & set(other.get("resources") or [])
            if oid != cid and collide and rank(oid) < rank(cid) and oid not in waits:
                waits.append(oid)
        out[cid] = {"signal": "WAIT" if waits else "GO", "waits_for": sorted(waits)}
    return out


def signals(project: Path) -> dict[str, dict[str, Any]]:
    """Compute and persist each open card's signal (`signal`, `waits_for`) so every desk reads the same traffic light."""
    folder = _dir(Path(project))
    with _Lock(folder / ".registry.lock"):
        registry = _read_json(folder / REGISTRY, {"cards": {}})
        cards = registry.get("cards", {})
        out = compute_signals(cards)
        for cid, sig in out.items():
            cards[cid].update(sig)
        _write_json(folder / REGISTRY, registry)
    return out


def propagate_stop(project: Path, d_id: str) -> list[str]:
    """The user said stop at any desk: every open card is halted now (status STOPPED, signal STOP). Only stop does this."""
    folder = _dir(Path(project))
    stopped: list[str] = []
    with _Lock(folder / ".registry.lock"):
        registry = _read_json(folder / REGISTRY, {"cards": {}})
        for cid, card in registry.get("cards", {}).items():
            if card.get("status") in OPEN_STATES:
                card.update(status="STOPPED", signal="STOP", stopped_by=d_id)
                stopped.append(cid)
        _write_json(folder / REGISTRY, registry)
    return stopped


def merge_order(project: Path) -> list[str]:
    """Merge order: dependency order, and among ready cards the smaller change (fewer owned files) first."""
    # the registry is replaced atomically (`_atomic_write`), so an unlocked read sees one whole snapshot, never a torn one
    registry = _read_json(_dir(Path(project)) / REGISTRY, {"cards": {}}).get("cards", {})
    # a STOPPED card never merges, and neither does anything that depends on it (a halted dependency is not "satisfied")
    halted = {cid for cid, c in registry.items() if c.get("status") == "STOPPED"}
    while True:
        more = {cid for cid, c in registry.items() if cid not in halted and halted & set(c.get("depends_on") or [])}
        if not more:
            break
        halted |= more
    cards = {cid: c for cid, c in registry.items() if c.get("status") != "DONE" and cid not in halted}
    order: list[str] = []
    while cards:
        ready = sorted((cid for cid, c in cards.items() if all(d not in cards for d in (c.get("depends_on") or []))),
                       key=lambda cid: (len(cards[cid].get("files") or []), cid))
        if not ready:  # a cycle: cut it by authority order instead of hanging
            ready = sorted(cards, key=lambda cid: (_authority_rank(cards[cid].get("tool")), cid))[:1]
        order.append(ready[0])
        cards.pop(ready[0])
    return order


def recipient_for(project: Path, text: str, *, addressed_card: str = "") -> dict[str, Any]:
    """Misdelivery fix: the recipient is the open card that owns the letter's files (card map), not whoever it was
    addressed to. The addressed card is kept when it owns a file of the letter; otherwise the real owner gets it and the
    addressed card only gets an ACK."""
    cards = running_cards(project)
    files = extract_files(text)
    addressed = next((c for c in cards if c["id"] == addressed_card), None)
    if addressed and files_overlap(files, set(addressed.get("files") or [])):
        return {"deliver_to": addressed_card, "rerouted": False, "reason": "addressed card owns a file of the letter"}
    owner = find_duplicate(text, files, infer_lane(text), cards)
    if owner and owner["kind"] in ("related", "duplicate") and owner["card"] != addressed_card:
        return {"deliver_to": owner["card"], "rerouted": True, "ack_only": addressed_card or None, "reason": owner["reason"]}
    return {"deliver_to": addressed_card or None, "rerouted": False, "reason": "NO_BETTER_OWNER"}


_CARD_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def _safe_card(card: str) -> str:
    """A card id becomes part of a file name: only letters, digits, `_` and `-`, so no traversal or invalid Windows name."""
    # fullmatch, not `$`: `$` also accepts a trailing newline (a card id ending in LF), an invalid Windows file name
    if not isinstance(card, str) or not _CARD_ID_RE.fullmatch(card) or card.upper() in _WIN_RESERVED:
        raise ValueError(f"unsafe card id: {card!r}")
    return card


def queue_addendum(project: Path, card: str, d_id: str) -> None:
    """A related directive waits for the card's next safe checkpoint (9.7-1); it never interrupts the running card."""
    card = _safe_card(card)
    folder = _dir(Path(project))
    path = folder / f"{card}.addenda.json"
    with _Lock(folder / f".{card}.addenda.lock"):
        data = _read_json(path, {"pending": [], "applied": []})
        if d_id not in data["pending"] and d_id not in data["applied"]:
            data["pending"].append(d_id)
        _write_json(path, data)


def take_checkpoint_addenda(project: Path, card: str, *, commit: bool = True) -> list[str]:
    """Called by the card at a safe checkpoint: returns the pending directive ids exactly once (idempotent).

    `commit=False` only peeks; the caller then confirms with `ack_addenda` once it really processed them, so a crash in
    between loses nothing. Nothing is written when nothing is pending."""
    card = _safe_card(card)
    folder = _dir(Path(project))
    path = folder / f"{card}.addenda.json"
    with _Lock(folder / f".{card}.addenda.lock"):
        data = _read_json(path, {"pending": [], "applied": []})
        taken = list(data["pending"])
        if taken and commit:
            data["pending"] = []
            data["applied"] += taken
            _write_json(path, data)
    return taken


def ack_addenda(project: Path, card: str, d_ids: list[str]) -> None:
    """Mark peeked addenda as applied after the card processed them."""
    card = _safe_card(card)
    folder = _dir(Path(project))
    path = folder / f"{card}.addenda.json"
    with _Lock(folder / f".{card}.addenda.lock"):
        data = _read_json(path, {"pending": [], "applied": []})
        want = set(d_ids)  # a repeated id must not be recorded twice
        moved = [d for d in data["pending"] if d in want]
        if moved:
            data["pending"] = [d for d in data["pending"] if d not in moved]
            data["applied"] += moved
            _write_json(path, data)


# --------------------------------------------------------------------------- 9. status for the user

def status_lines(project: Path, *, max_lines: int = 3) -> list[str]:
    """Only items that changed since the last report; BLOCKED first; at most `max_lines` lines (none when <= 0)."""
    if max_lines <= 0:
        return []
    folder = _dir(Path(project))
    registry = _read_json(folder / REGISTRY, {"cards": {}}).get("cards", {})
    seen_path = folder / ".reported.json"
    with _Lock(folder / ".reported.lock"):
        seen = _read_json(seen_path, {})
        now_state = {cid: c.get("status") for cid, c in registry.items()}
        changed = [(cid, c) for cid, c in sorted(registry.items()) if seen.get(cid) != c.get("status")]
        _write_json(seen_path, now_state)
    changed.sort(key=lambda item: item[1].get("status") != "BLOCKED")
    lines = [f"- {c.get('title') or cid} ({cid}): {c.get('status')} -> " + ("needs an active tool with quota" if c.get("status") == "BLOCKED" else "tool " + str(c.get("tool")))
             for cid, c in changed]
    if len(lines) > max_lines == 1:
        lines = lines[:1]  # one line only: keep the top (BLOCKED) item, a count line would hide it
    elif len(lines) > max_lines:
        lines = lines[:max_lines - 1] + [f"- +{len(lines) - max_lines + 1} more changed (see .coord/directives/{REGISTRY})"]
    return lines
