"""U390 Phase 2: UAOS-RSI Unattended, Zero-Approval, Nonstop, Parallel, RSI 3-Tool Kernel.

Integrates the 6 redesigned OS pillars atop the verified U390 foundation:
1. Unattended durable event-sourced card ledger + crash-lease recovery (Temporal pattern)
2. Zero-approval autonomous flow outside Safety-7 human-only boundaries (negation-safe)
3. Nonstop anti-stall: 12-turn/180KB session rotation, quota auto-thaw, 2-strike reroute, 3-strike quarantine
4. 5-lane disjoint parallel scheduler, <=5-turn tiki-taka tie-breaker, autonomous merge queue
5. Closed-loop evidence-gated RSI synthesizer with immutable evaluator & 3x cost guards
6. Single deterministic zero-token orchestration cycle (`tick_fullstack_os`)
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Callable, Iterator, Sequence

from v7_harness import rsi as rsi_mod
from v7_harness.adapters import ollama_vram_guard
from v7_harness.coord import idea_fullstack, mailbox as mailbox_mod, presence as presence_mod, process_lanes

CARD_STATES: tuple[str, ...] = (
    "INTAKE",
    "CONCRETIZED",
    "SCHEDULED",
    "DISPATCHED",
    "EXECUTING",
    "VERIFYING",
    "JUDGING",
    "MERGE_READY",
    "MERGED",
    "RSI_RECORDED",
    "DONE",
    "PAUSED_QUOTA",
    "BLOCKED",
    "AWAITING_HUMAN_SAFETY",
    "QUARANTINED_FAILURE",
)

FIVE_LANES: tuple[str, ...] = (
    "IMPL_CODE",
    "VERIFY_AUDIT",
    "ARCH_DESIGN",
    "MERGE_RELEASE",
    "RECOVERY_OPS",
)

MERGE_PRIORITY_ORDER: tuple[str, ...] = ("antigravity", "codex", "claude")
SESSION_ROTATE_MAX_TURNS = 12
SESSION_ROTATE_MAX_BYTES = 180_000
MAX_TIKITAKA_TURNS = 5

SAFETY_7_BOUNDARIES: dict[str, tuple[str, ...]] = {
    "DATA_DELETE": ("rm -rf", "영구 삭제", "데이터 삭제", "drop table", "delete production"),
    "REMOTE_PUSH": ("git push", "원격 푸시", "원격 push", "force-push"),
    "DEPLOY_RELEASE": ("프로덕션 배포", "실서버 배포", "deploy to prod", "store submission", "스토어 출시"),
    "PUBLIC_POST": ("공개 게시", "public post", "publish public"),
    "PAID_SPEND": ("유료 결제", "과금 승인", "paid billing", "purchase subscription"),
    "ACCOUNT_CREDENTIAL_PERMISSION": ("계정 변경", "자격 증명 변경", "비밀번호 변경", "api key 발급", "권한 승격"),
    "OS_SYSTEM_SETTING": ("레지스트리 변경", "방화벽 해제", "시스템 설정 변경", "system settings"),
}

IMMUTABLE_EVALUATOR_PATHS: tuple[str, ...] = (
    "v7_harness/calculator_gate.py",
    "v7_harness/rsi.py",
    "v7_harness/judge.py",
    ".githooks/",
)

_NEGATION_NEAR_RE = re.compile(
    r"(?:하지\s*(?:말|마)|금지|제외|않고|않는다|without|never|do not|don't|no )",
    re.I,
)


def _os_dir(project: Path) -> Path:
    path = Path(project) / ".coord" / "fullstack_os"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    for attempt in range(25):
        try:
            os.replace(str(tmp), str(path))
            return
        except PermissionError:
            time.sleep(0.01 * (attempt + 1))
    os.replace(str(tmp), str(path))


@contextmanager
def _os_lock(project: Path, timeout_s: float = 10.0) -> Iterator[None]:
    """Serialize state/journal mutations across threads and processes via live-owner OS kernel lock."""
    with mailbox_mod.fenced_file_lock(
        _os_dir(project) / ".fullstack_os.lock",
        timeout_s=timeout_s,
        label="fullstack_os lock",
    ):
        yield


def load_os_state(project: Path) -> dict[str, Any]:
    path = _os_dir(project) / "state.json"
    default: dict[str, Any] = {"schema": "uaos-fullstack-os-v2", "seq": 0, "cards": {}, "updated_at": 0.0}
    if not path.is_file():
        return default
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict) and isinstance(loaded.get("cards"), dict):
            return loaded
    except (OSError, ValueError):
        pass
    return default


def save_os_state(project: Path, state: dict[str, Any]) -> None:
    _atomic_write_json(_os_dir(project) / "state.json", state)


def append_journal_event(project: Path, event: dict[str, Any]) -> dict[str, Any]:
    journal = _os_dir(project) / "journal.jsonl"
    record = {"ts": time.time(), **event}
    with open(journal, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
    return record


# --------------------------------------------------------------------------- Pillar 2: Zero-Approval Boundary


def classify_autonomy_boundary(action_text: str, *, changed_paths: Sequence[str] = ()) -> dict[str, Any]:
    """Return AUTONOMOUS_GO unless action triggers an unnegated Safety-7 human boundary."""
    text = str(action_text or "")
    clauses = [c.strip() for c in re.split(r"[\n.!?。]+", text) if c.strip()]
    triggered: list[str] = []

    for boundary, phrases in SAFETY_7_BOUNDARIES.items():
        for clause in clauses:
            lowered = clause.lower()
            hit = False
            for phrase in phrases:
                idx = lowered.find(phrase.lower())
                if idx == -1:
                    continue
                window = lowered[max(0, idx - 24) : min(len(lowered), idx + len(phrase) + 20)]
                if _NEGATION_NEAR_RE.search(window):
                    continue
                hit = True
                break
            if hit:
                triggered.append(boundary)
                break

    if triggered:
        return {
            "mode": "HUMAN_APPROVAL_REQUIRED",
            "triggered_boundaries": triggered,
            "changed_paths": list(changed_paths),
            "reason": f"Safety-7 human boundary triggered: {', '.join(triggered)}",
        }
    return {
        "mode": "AUTONOMOUS_GO",
        "triggered_boundaries": [],
        "changed_paths": list(changed_paths),
        "reason": "Internal orchestration requires zero human approval",
    }


# --------------------------------------------------------------------------- Pillar 1 & 3: Durable Recovery & Nonstop


def _recover_inflight_unlocked(state: dict[str, Any], moment: float, lease_ttl_s: float) -> list[str]:
    cards = state.get("cards")
    if not isinstance(cards, dict):
        return []
    recovered: list[str] = []
    for cid, card in cards.items():
        if not isinstance(card, dict):
            continue
        if card.get("status") not in ("DISPATCHED", "EXECUTING"):
            continue
        exp = card.get("step_lease_expires_at")
        if isinstance(exp, (int, float)) and not isinstance(exp, bool) and exp <= moment:
            card["status"] = "SCHEDULED"
            card["admitted"] = False
            card["launch_receipt"] = None
            card["step_lease_expires_at"] = None
            card["recovery_count"] = int(card.get("recovery_count") or 0) + 1
            card["last_recovered_at"] = moment
            recovered.append(cid)
    return recovered


def recover_inflight_cards(
    project: Path,
    *,
    lease_ttl_s: float = 900.0,
    now: float | None = None,
) -> list[str]:
    """Reclaim crashed/expired DISPATCHED or EXECUTING cards back to SCHEDULED idempotently."""
    moment = time.time() if now is None else float(now)
    with _os_lock(project):
        state = load_os_state(project)
        recovered = _recover_inflight_unlocked(state, moment, lease_ttl_s)
        if recovered:
            state["updated_at"] = moment
            save_os_state(project, state)
            append_journal_event(project, {"event": "CRASH_RECOVERED", "cards": recovered, "ts": moment})
        return recovered


def check_session_rotation(turn_count: int, transcript_bytes: int) -> dict[str, Any]:
    """Enforce the canonical 12-turn / 180KB session rotation threshold."""
    turns = max(0, int(turn_count))
    size_b = max(0, int(transcript_bytes))
    reasons: list[str] = []
    if turns >= SESSION_ROTATE_MAX_TURNS:
        reasons.append(f"turn_count>={SESSION_ROTATE_MAX_TURNS}")
    if size_b >= SESSION_ROTATE_MAX_BYTES:
        reasons.append(f"transcript_bytes>={SESSION_ROTATE_MAX_BYTES}")
    return {
        "rotate_required": bool(reasons),
        "reason": "; ".join(reasons) if reasons else None,
        "handoff_schema": "uaos-session-rotate-v1" if reasons else None,
    }


def thaw_expired_quota_cards(state: dict[str, Any], *, project: Path, now: float) -> list[str]:
    """Transition PAUSED_QUOTA cards back to SCHEDULED ONLY when pause_until truly expired."""
    cards = state.get("cards")
    if not isinstance(cards, dict):
        return []
    thawed: list[str] = []
    qsnap = _read_quota_snapshot(project, now=now)
    for cid, card in cards.items():
        if not isinstance(card, dict) or card.get("status") != "PAUSED_QUOTA":
            continue
        if card.get("blocked_reason"):
            continue
        owner = str(card.get("owner") or "").strip()
        if not owner:
            continue
        if (qsnap.get(owner) or {}).get("paused") is True:
            continue
        pause_until = card.get("pause_until")
        if isinstance(pause_until, (int, float)) and not isinstance(pause_until, bool) and float(pause_until) <= float(now):
            card["status"] = "SCHEDULED"
            card["pause_until"] = None
            card["admitted"] = False
            card["launch_receipt"] = None
            card["step_lease_expires_at"] = None
            card["thawed_at"] = now
            thawed.append(cid)
    return thawed


def record_step_failure(
    card: dict[str, Any],
    *,
    cause: str,
    active_tools: Sequence[str],
) -> dict[str, Any]:
    """Two-strike route failover and three-strike quarantine on repeated same-cause failures."""
    norm_cause = str(cause or "UNKNOWN").strip() or "UNKNOWN"
    counts = dict(card.get("failure_counts") or {})
    new_count = int(counts.get(norm_cause) or 0) + 1
    counts[norm_cause] = new_count
    card["failure_counts"] = counts
    card["last_failure_cause"] = norm_cause

    rerouted_to: str | None = None
    if new_count == 1:
        action = "RETRY_WITH_FEEDBACK"
        card["status"] = "SCHEDULED"
    elif new_count == 2:
        current_owner = str(card.get("owner") or "")
        alt = next((t for t in active_tools if t != current_owner), None)
        if alt is not None:
            card["owner"] = alt
            rerouted_to = alt
            if card.get("judge") == alt:
                card["judge"] = next((t for t in active_tools if t != alt), current_owner or "codex")
        card["status"] = "SCHEDULED"
        action = "TWO_STRIKE_REROUTED" if rerouted_to else "TWO_STRIKE_NO_ALT"
    else:
        card["status"] = "QUARANTINED_FAILURE"
        action = "THREE_STRIKE_QUARANTINED"

    return {
        "card_id": card.get("card_id"),
        "cause": norm_cause,
        "count": new_count,
        "action": action,
        "rerouted_to": rerouted_to,
        "status": card["status"],
    }


# --------------------------------------------------------------------------- Pillar 4: Parallel Tiki-Taka & Merge


def record_tikitaka_turn(
    card: dict[str, Any],
    *,
    actor: str,
    evidence_ref: str,
    verdict: str = "",
) -> dict[str, Any]:
    """Track <=5-turn cross-tool review loop and escalate ping-pong to tiebreaker."""
    norm_actor = str(actor or "").strip().lower()
    norm_verdict = str(verdict or "").strip().upper()
    owner = str(card.get("owner") or "").strip().lower()
    if norm_verdict in ("PASS", "APPROVE") and norm_actor == owner:
        raise ValueError(f"SELF_JUDGE_FORBIDDEN: owner={owner} cannot emit {norm_verdict}")

    turns = int(card.get("tikitaka_turns") or 0) + 1
    card["tikitaka_turns"] = turns
    history = list(card.get("tikitaka_log") or [])
    history.append({"turn": turns, "actor": norm_actor, "evidence_ref": evidence_ref, "verdict": norm_verdict})
    card["tikitaka_log"] = history

    escalated = False
    tiebreaker: str | None = None
    if norm_verdict in ("PASS", "APPROVE"):
        card["status"] = "MERGE_READY"
    elif turns >= MAX_TIKITAKA_TURNS:
        escalated = True
        tiebreaker = "codex" if owner != "codex" else "antigravity"
        card["judge"] = tiebreaker
        card["status"] = "JUDGING"

    return {
        "card_id": card.get("card_id"),
        "turn": turns,
        "escalated_to_tiebreaker": escalated,
        "tiebreaker": tiebreaker,
        "status": card.get("status"),
    }


def select_autonomous_merger(*, author: str, judge: str, active_tools: Sequence[str]) -> str:
    """Pick autonomous merger by priority (1. antigravity, 2. codex, 3. claude) after author!=judge."""
    if str(author).lower() == str(judge).lower():
        raise ValueError("MERGE_REFUSED: author cannot be identical to judge")
    active_set = {str(t).lower() for t in active_tools}
    for cand in MERGE_PRIORITY_ORDER:
        if cand in active_set:
            return cand
    return MERGE_PRIORITY_ORDER[0]


# --------------------------------------------------------------------------- Pillar 5: Closed-Loop Evidence-Gated RSI


def validate_rsi_candidate_safety(
    candidate_paths: Sequence[str],
    *,
    baseline_tokens: float | None = None,
    candidate_tokens: float | None = None,
    paired_samples: int = 0,
) -> dict[str, Any]:
    """Enforce immutable evaluator protection, <3x cost ceiling, and UNMEASURED honesty."""
    norms = [str(p).replace("\\", "/").lstrip("./") for p in candidate_paths]
    errors: list[str] = []
    for path in norms:
        lower = path.lower()
        for protected in IMMUTABLE_EVALUATOR_PATHS:
            prot = protected.lower()
            if lower == prot or (prot.endswith("/") and lower.startswith(prot)):
                errors.append(f"EVALUATOR_MUTATION_FORBIDDEN:{path}")
    if (
        baseline_tokens is not None
        and candidate_tokens is not None
        and float(baseline_tokens) > 0
        and float(candidate_tokens) >= float(baseline_tokens) * 3.0
    ):
        errors.append("COST_REGRESSION_3X")
    savings_claim = "MEASURED" if int(paired_samples) >= 10 else "UNMEASURED"
    return {
        "ok": not errors,
        "errors": errors,
        "savings_claim": savings_claim,
        "auto_adopt": False,
    }


def synthesize_rsi_loop(
    project: Path,
    *,
    now: float | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Convert ledger recurring causes and inbox rsi_review alerts into B83-safe PLAN candidates."""
    root = Path(project)
    moment = time.time() if now is None else float(now)
    rows = rsi_mod.load_rows(root)
    policy = rsi_mod.load_policy(root)
    analysis = rsi_mod.analyze(rows, policy)
    proposals = rsi_mod.propose(analysis, policy)

    candidates: dict[str, dict[str, Any]] = {}
    for prop in proposals:
        if not prop.get("recurring") and int(prop.get("count") or 0) < 2:
            continue
        cid = f"RSI-CAND-{str(prop['worker']).upper()}-{str(prop['cause']).upper()}"
        candidates[cid] = {
            "candidate_id": cid,
            "proposal_id": prop["id"],
            "worker": prop["worker"],
            "cause": prop["cause"],
            "count": prop["count"],
            "target": prop["target"],
            "action": prop["action"],
            "evidence": list(prop.get("cause_evidence") or prop.get("evidence") or ()),
            "auto_adopt": False,
            "requires_non_author_plan_card": True,
            "source": "usage_ledger",
        }

    inbox = root / ".coord" / "mailbox" / "inbox"
    if inbox.is_dir():
        for path in sorted(inbox.glob("rsi_review_*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            payload = data.get("payload") if isinstance(data, dict) else None
            if not isinstance(payload, dict):
                continue
            worker = str(payload.get("worker") or "ollama")
            recurring = payload.get("recurring") or []
            for cause in recurring if isinstance(recurring, list) else ():
                cid = f"RSI-CAND-{worker.upper()}-{str(cause).upper()}"
                if cid not in candidates:
                    candidates[cid] = {
                        "candidate_id": cid,
                        "proposal_id": f"inbox:{path.stem}",
                        "worker": worker,
                        "cause": str(cause),
                        "count": int(payload.get("window") or 10),
                        "target": "adapter_guard",
                        "action": str(payload.get("delta") or payload.get("summary") or f"Fix {cause}"),
                        "evidence": [path.name],
                        "auto_adopt": False,
                        "requires_non_author_plan_card": True,
                        "source": "mailbox_rsi_review",
                    }

    ordered = [candidates[k] for k in sorted(candidates)]
    packet = {
        "schema": "uaos-rsi-candidates-v1",
        "generated_at": moment,
        "samples": analysis.get("samples", 0),
        "candidate_count": len(ordered),
        "candidates": ordered,
        "auto_adopt": False,
    }
    if not dry_run:
        _atomic_write_json(_os_dir(root) / "rsi_candidates.json", packet)
    return packet


# --------------------------------------------------------------------------- Pillar 6: Unified Full-Stack Tick


def _allocate_card_id(state: dict[str, Any], raw_sha: str) -> str:
    seq = int(state.get("seq") or 0) + 1
    state["seq"] = seq
    return f"OS-{seq:04d}-{raw_sha[:6]}"


def _blocked_card_record(
    cid: str,
    *,
    blocked_reason: str,
    moment: float,
    source_status: str = "BLOCKED",
    lane: str = "IMPL_CODE",
    goal: str = "",
    mia_tier: str = "MIA-Standard",
    owner: str = "",
    allow_files: Sequence[str] = (),
    d_id: Any = None,
    prev: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a fail-closed BLOCKED card record with zero admission or launch receipt."""
    base = dict(prev) if isinstance(prev, dict) else {}
    safe_owner = owner if isinstance(owner, str) else ""
    safe_judge = "codex" if safe_owner != "codex" else "antigravity"
    safe_turns = base.get("tikitaka_turns")
    turns = int(safe_turns) if isinstance(safe_turns, int) and not isinstance(safe_turns, bool) else 0
    return {
        **base,
        "card_id": cid,
        "status": "BLOCKED",
        "source_status": source_status or "BLOCKED",
        "blocked_reason": str(blocked_reason or "BLOCKED"),
        "admitted": False,
        "launch_receipt": None,
        "step_lease_expires_at": None,
        "lane": str(lane or base.get("lane") or "IMPL_CODE"),
        "goal": str(goal or base.get("goal") or cid),
        "mia_tier": str(mia_tier or base.get("mia_tier") or "MIA-Standard"),
        "owner": safe_owner,
        "judge": safe_judge,
        "allow_files": list(allow_files),
        "d_id": d_id if d_id is not None else base.get("d_id"),
        "completed_stages": list(base.get("completed_stages") or ["STAGE_SPEC"]),
        "tikitaka_turns": turns,
        "failure_counts": dict(base.get("failure_counts")) if isinstance(base.get("failure_counts"), dict) else {},
        "created_at": base.get("created_at") if isinstance(base.get("created_at"), (int, float)) else moment,
    }


def _safe_str(val: Any, default: str = "") -> str:
    if isinstance(val, bool) or val is None:
        return default
    return str(val) if isinstance(val, (str, int, float)) else default


def _mirror_routed_plan_into_state(
    state: dict[str, Any],
    plan: dict[str, Any],
    moment: float,
    *,
    preserve_active: bool = False,
) -> list[str]:
    if not isinstance(plan, dict):
        return []
    cards_dict = state.get("cards")
    if not isinstance(cards_dict, dict):
        cards_dict = {}
        state["cards"] = cards_dict

    concrete = plan.get("concrete") if isinstance(plan.get("concrete"), dict) else {}
    mia_tier_obj = concrete.get("mia_tier") if isinstance(concrete.get("mia_tier"), dict) else {}
    mia_tier = _safe_str(mia_tier_obj.get("tier"), "MIA-Standard") or "MIA-Standard"
    d_id = plan.get("d_id")
    d_id_prefix = _safe_str(d_id, "DIRECTIVE") or "DIRECTIVE"
    lane_default = _safe_str(plan.get("lane"), "IMPL_CODE") or "IMPL_CODE"
    goal_default = _safe_str(concrete.get("goal"))
    synced: list[str] = []

    raw_cards = plan.get("cards")
    if "cards" in plan and raw_cards is not None and not isinstance(raw_cards, list):
        cid = _safe_str(d_id, "MALFORMED-PLAN") or "MALFORMED-PLAN"
        cards_dict[cid] = _blocked_card_record(
            cid,
            blocked_reason="MALFORMED_CARDS_LIST",
            moment=moment,
            lane=lane_default,
            goal=goal_default or cid,
            mia_tier=mia_tier,
            d_id=d_id,
            prev=cards_dict.get(cid),
        )
        return [cid]

    cards = raw_cards if isinstance(raw_cards, list) else []
    if not cards:
        top_state = _safe_str(plan.get("state")).upper()
        top_blocker = plan.get("blocked") or plan.get("blocked_reason")
        if top_state == "BLOCKED" or top_blocker:
            cid = _safe_str(d_id, "BLOCKED-PLAN") or "BLOCKED-PLAN"
            cards_dict[cid] = _blocked_card_record(
                cid,
                blocked_reason=_safe_str(top_blocker or plan.get("reason"), "BLOCKED") or "BLOCKED",
                moment=moment,
                source_status=top_state or "BLOCKED",
                lane=lane_default,
                goal=goal_default or cid,
                mia_tier=mia_tier,
                d_id=d_id,
                prev=cards_dict.get(cid),
            )
            synced.append(cid)
        return synced

    for idx, item in enumerate(cards):
        try:
            if not isinstance(item, dict):
                cid = f"{d_id_prefix}-MALFORMED-{idx}"
                cards_dict[cid] = _blocked_card_record(
                    cid,
                    blocked_reason="MALFORMED_CARD_ITEM",
                    moment=moment,
                    lane=lane_default,
                    goal=goal_default or cid,
                    mia_tier=mia_tier,
                    d_id=d_id,
                    prev=cards_dict.get(cid),
                )
                synced.append(cid)
                continue

            raw_id = item.get("id")
            if not isinstance(raw_id, (str, int)) or isinstance(raw_id, bool) or not str(raw_id).strip():
                cid = f"{d_id_prefix}-MALFORMED-{idx}"
                cards_dict[cid] = _blocked_card_record(
                    cid,
                    blocked_reason="MALFORMED_CARD_ID",
                    moment=moment,
                    lane=lane_default,
                    goal=goal_default or cid,
                    mia_tier=mia_tier,
                    d_id=item.get("d_id") or d_id,
                    prev=cards_dict.get(cid),
                )
                synced.append(cid)
                continue

            cid = str(raw_id).strip()
            malformed_reason: str | None = None

            raw_assignment = item.get("assignment") if "assignment" in item else None
            if raw_assignment is not None and not isinstance(raw_assignment, dict):
                malformed_reason = "MALFORMED_ASSIGNMENT"
                assignment: dict[str, Any] = {}
            else:
                assignment = raw_assignment or {}

            raw_window = item.get("window") if "window" in item else None
            if raw_window is not None and not isinstance(raw_window, dict):
                malformed_reason = malformed_reason or "MALFORMED_WINDOW"
                window: dict[str, Any] = {}
            else:
                window = raw_window or {}

            raw_files = item.get("files") if "files" in item else None
            if raw_files is not None and not isinstance(raw_files, (list, tuple)):
                malformed_reason = malformed_reason or "MALFORMED_FILES"
                clean_files: list[str] = []
            else:
                clean_files = [str(f) for f in (raw_files or ()) if isinstance(f, str) and f.strip()]

            raw_tool = item.get("tool") if ("tool" in item and item.get("tool") is not None) else assignment.get("tool")
            if raw_tool is not None and not isinstance(raw_tool, str):
                malformed_reason = malformed_reason or "MALFORMED_TOOL"
                chosen_tool = ""
            else:
                chosen_tool = raw_tool.strip() if isinstance(raw_tool, str) else ""

            raw_status = (_safe_str(item.get("status"), "READY") or "READY").upper()
            blocked_reason = (
                malformed_reason
                or assignment.get("blocked")
                or item.get("blocked_reason")
                or item.get("blocked")
                or (window.get("reason") if raw_status == "BLOCKED" else None)
                or plan.get("blocked")
            )
            item_lane = _safe_str(item.get("lane"), lane_default) or lane_default
            item_goal = goal_default or _safe_str(item.get("title"), cid) or cid
            item_did = item.get("d_id") if item.get("d_id") is not None else d_id
            prev_rec = cards_dict.get(cid) if isinstance(cards_dict.get(cid), dict) else None

            if malformed_reason or raw_status == "BLOCKED" or blocked_reason or not chosen_tool:
                cards_dict[cid] = _blocked_card_record(
                    cid,
                    blocked_reason=_safe_str(blocked_reason or malformed_reason, "BLOCKED") or "BLOCKED",
                    moment=moment,
                    source_status=raw_status,
                    lane=item_lane,
                    goal=item_goal,
                    mia_tier=mia_tier,
                    owner="" if malformed_reason else chosen_tool,
                    allow_files=clean_files,
                    d_id=item_did,
                    prev=prev_rec,
                )
                synced.append(cid)
                continue

            if preserve_active and isinstance(prev_rec, dict):
                synced.append(cid)
                continue

            if (
                not preserve_active
                and raw_status == "RUNNING"
                and assignment.get("tool") == chosen_tool
                and not assignment.get("blocked")
                and window.get("opened") is True
            ):
                os_status = "DISPATCHED"
                admitted_flag = True
                launch_receipt: dict[str, Any] | None = dict(window)
            else:
                os_status = "SCHEDULED"
                admitted_flag = False
                launch_receipt = None

            judge = "codex" if chosen_tool != "codex" else "antigravity"
            cards_dict[cid] = {
                "card_id": cid,
                "status": os_status,
                "source_status": raw_status,
                "blocked_reason": None,
                "admitted": admitted_flag,
                "launch_receipt": launch_receipt,
                "lane": item_lane,
                "goal": item_goal,
                "mia_tier": mia_tier,
                "owner": chosen_tool,
                "judge": judge,
                "allow_files": clean_files,
                "d_id": item_did,
                "completed_stages": ["STAGE_SPEC"],
                "tikitaka_turns": 0,
                "failure_counts": {},
                "created_at": moment,
            }
            synced.append(cid)
        except Exception as exc:  # noqa: BLE001 - isolate malformed directive card records per record
            cid = f"{d_id_prefix}-ERROR-{idx}"
            cards_dict[cid] = _blocked_card_record(
                cid,
                blocked_reason=f"MALFORMED_RECORD:{type(exc).__name__}",
                moment=moment,
                lane=lane_default,
                goal=goal_default or cid,
                mia_tier=mia_tier,
                d_id=d_id,
                prev=cards_dict.get(cid),
            )
            synced.append(cid)
    return synced


def sync_routed_plan(project: Path, plan: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
    """Mirror cards routed through ``desk_router.route_directive`` preserving source blockers."""
    root = Path(project)
    moment = time.time() if now is None else float(now)
    with _os_lock(root):
        state = load_os_state(root)
        synced = _mirror_routed_plan_into_state(state, plan, moment)
        if synced:
            state["updated_at"] = moment
            save_os_state(root, state)
            append_journal_event(root, {"event": "ROUTED_PLAN_SYNCED", "cards": synced, "d_id": plan.get("d_id"), "ts": moment})
    return {"ok": True, "synced": synced}


def _reconcile_directive_plans_unlocked(project: Path, state: dict[str, Any], moment: float) -> None:
    """Ensure disk route plans and source blockers fail closed per record without aborting valid directives."""
    cards_dict = state.get("cards")
    if not isinstance(cards_dict, dict):
        cards_dict = {}
        state["cards"] = cards_dict

    for cid, card in list(cards_dict.items()):
        if not isinstance(card, dict):
            cards_dict[cid] = _blocked_card_record(str(cid), blocked_reason="MALFORMED_CARD_RECORD", moment=moment)
            continue
        if card.get("blocked_reason") or card.get("status") == "BLOCKED":
            card["status"] = "BLOCKED"
            card["admitted"] = False
            card["launch_receipt"] = None
            card.pop("step_lease_expires_at", None)

    directives_dir = Path(project) / ".coord" / "directives"
    if not directives_dir.is_dir():
        return

    for path in sorted(directives_dir.glob("*.json")):
        if path.name.startswith(".") or path.name == "cards.json":
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        if not isinstance(doc, dict):
            continue
        if "plan" in doc and doc["plan"] is not None and not isinstance(doc["plan"], dict):
            cid = _safe_str(doc.get("d_id"), path.stem) or path.stem
            cards_dict[cid] = _blocked_card_record(
                cid,
                blocked_reason="MALFORMED_DIRECTIVE_PLAN",
                moment=moment,
                d_id=doc.get("d_id") or path.stem,
                prev=cards_dict.get(cid),
            )
            continue
        plan_obj = doc.get("plan") if isinstance(doc.get("plan"), dict) else doc
        enriched = dict(plan_obj)
        enriched.setdefault("d_id", doc.get("d_id") or path.stem)
        if not enriched.get("blocked") and doc.get("blocked"):
            enriched["blocked"] = doc.get("blocked")
        if not enriched.get("state") and doc.get("state"):
            enriched["state"] = doc.get("state")
        _mirror_routed_plan_into_state(state, enriched, moment, preserve_active=True)

    reg_path = directives_dir / "cards.json"
    if reg_path.is_file():
        try:
            reg = json.loads(reg_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            reg = {}
        reg_cards = reg.get("cards") if isinstance(reg, dict) else None
        if isinstance(reg_cards, dict):
            for cid, item in reg_cards.items():
                cid_str = str(cid)
                prev = cards_dict.get(cid_str) if isinstance(cards_dict.get(cid_str), dict) else None
                if not isinstance(item, dict):
                    cards_dict[cid_str] = _blocked_card_record(
                        cid_str,
                        blocked_reason="MALFORMED_CARDS_ENTRY",
                        moment=moment,
                        prev=prev,
                    )
                    continue
                malformed_reason: str | None = None
                raw_assignment = item.get("assignment") if "assignment" in item else None
                if raw_assignment is not None and not isinstance(raw_assignment, dict):
                    malformed_reason = "MALFORMED_ASSIGNMENT"
                    assignment: dict[str, Any] = {}
                else:
                    assignment = raw_assignment or {}

                raw_files = item.get("files") if "files" in item else None
                if raw_files is not None and not isinstance(raw_files, (list, tuple)):
                    malformed_reason = malformed_reason or "MALFORMED_FILES"
                    clean_files: list[str] = list((prev or {}).get("allow_files") or ())
                else:
                    clean_files = [str(f) for f in (raw_files or ()) if isinstance(f, str) and f.strip()] if raw_files is not None else list((prev or {}).get("allow_files") or ())

                raw_tool = item.get("tool") if ("tool" in item and item.get("tool") is not None) else assignment.get("tool")
                if raw_tool is not None and not isinstance(raw_tool, str):
                    malformed_reason = malformed_reason or "MALFORMED_TOOL"
                    chosen_tool = ""
                else:
                    chosen_tool = raw_tool.strip() if isinstance(raw_tool, str) else ""

                raw_status = (_safe_str(item.get("status"), "READY") or "READY").upper()
                item_blocker = malformed_reason or assignment.get("blocked") or item.get("blocked_reason") or item.get("blocked")
                if malformed_reason or raw_status == "BLOCKED" or item_blocker or not chosen_tool:
                    blocker = _safe_str(item_blocker or (prev or {}).get("blocked_reason"), "BLOCKED") or "BLOCKED"
                    cards_dict[cid_str] = _blocked_card_record(
                        cid_str,
                        blocked_reason=blocker,
                        moment=moment,
                        source_status=raw_status or "BLOCKED",
                        lane=_safe_str(item.get("lane"), (prev or {}).get("lane") or "IMPL_CODE") or "IMPL_CODE",
                        goal=_safe_str(item.get("title"), (prev or {}).get("goal") or cid_str) or cid_str,
                        owner="" if malformed_reason else (chosen_tool or _safe_str((prev or {}).get("owner"))),
                        allow_files=clean_files,
                        d_id=item.get("d_id") if item.get("d_id") is not None else (prev or {}).get("d_id"),
                        prev=prev,
                    )
                elif cid_str not in cards_dict:
                    cards_dict[cid_str] = {
                        "card_id": cid_str,
                        "status": "SCHEDULED",
                        "source_status": raw_status,
                        "blocked_reason": None,
                        "admitted": False,
                        "launch_receipt": None,
                        "step_lease_expires_at": None,
                        "owner": chosen_tool,
                        "judge": "codex" if chosen_tool != "codex" else "antigravity",
                        "lane": _safe_str(item.get("lane"), "IMPL_CODE") or "IMPL_CODE",
                        "goal": _safe_str(item.get("title"), cid_str) or cid_str,
                        "allow_files": clean_files,
                        "d_id": item.get("d_id"),
                        "completed_stages": ["STAGE_SPEC"],
                        "tikitaka_turns": 0,
                        "failure_counts": {},
                        "created_at": moment,
                    }


def _read_quota_snapshot(project: Path, *, now: float) -> dict[str, Any]:
    """Read unified_desks quota and pause-lease state safely without failing open."""
    ud_path = Path(project) / ".coord" / "presence" / "unified_desks.json"
    if not ud_path.is_file():
        return {}
    try:
        raw = json.loads(ud_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    desks = raw.get("desks")
    if not isinstance(desks, dict):
        return {}

    snapshot: dict[str, Any] = {}
    for tool, info in desks.items():
        if not isinstance(info, dict):
            continue
        raw_quota = info.get("quota")
        entry: dict[str, Any] = dict(raw_quota) if isinstance(raw_quota, dict) else {}
        pause_iso = info.get("execution_paused_until")
        pause_ts = idea_fullstack.parse_iso_timestamp(pause_iso)
        if pause_ts is not None and pause_ts > float(now):
            entry["paused"] = True
            entry["execution_paused_until"] = pause_iso
        snapshot[str(tool)] = entry
    return snapshot


def tick_fullstack_os(
    project: Path,
    *,
    raw_ideas: Sequence[str] = (),
    existing_locked_files: Sequence[str] = (),
    installed_models: Sequence[str] = (),
    vram_gb: float = 6.0,
    inbox_compact_threshold: int = 500,
    quota_snapshot: dict[str, Any] | None = None,
    observer_only: bool = False,
    admitted: dict[str, bool] | None = None,
    launcher: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    now: float | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute one complete unattended, zero-approval, nonstop, 5-lane + RSI OS cycle."""
    root = Path(project)
    moment = time.time() if now is None else float(now)
    locked = {str(p).replace("\\", "/").lstrip("./") for p in existing_locked_files}
    is_dry_run = bool(dry_run)
    is_observer = bool(observer_only)

    with _os_lock(root):
        state = load_os_state(root)
        _reconcile_directive_plans_unlocked(root, state, moment)
        recovered = _recover_inflight_unlocked(state, moment, lease_ttl_s=900.0)
        tool_info = presence_mod.read_all(root, now=moment)
        tool_states = {t: str(info.get("state") or "UNKNOWN") for t, info in tool_info.items()}
        resolved_quota = quota_snapshot if quota_snapshot is not None else _read_quota_snapshot(root, now=moment)
        brain_labor_summary = idea_fullstack.plan_brain_labor_7d_schedule(
            tool_states=tool_states,
            quota_snapshot=resolved_quota,
            is_keypoint=False,
            now=moment,
        )
        ollama_cellular_audit = ollama_vram_guard.audit_ollama_cellular_harness(installed_models, vram_gb=vram_gb)
        thawed = thaw_expired_quota_cards(state, project=root, now=moment)

        ingested: list[dict[str, Any]] = []
        repo_index = idea_fullstack.scan_repo_surface(root) if raw_ideas else None
        for raw_text in raw_ideas:
            spec = idea_fullstack.concretize_raw_idea(root, raw_text, repo_index=repo_index, now=moment)
            boundary = classify_autonomy_boundary(raw_text, changed_paths=spec["grounded_files"])
            dag = idea_fullstack.build_gear_dag(
                spec,
                tool_states=tool_states,
                quota_snapshot=resolved_quota,
                existing_locked_files=locked,
                now=moment,
            )
            alloc = idea_fullstack.plan_ollama_helper_allocation(
                dag,
                vram_gb=vram_gb,
                installed_models=installed_models,
                tool_states=tool_states,
                quota_snapshot=resolved_quota,
            )
            card_id = _allocate_card_id(state, spec["raw_sha256"])
            impl_units = [u for u in dag["units"] if u["stage"] == "IMPLEMENTATION_SLICE"]
            primary = impl_units[0] if impl_units else dag["units"][0]
            owned_files = sorted({f for u in impl_units for f in u["allow_files"]})
            lane = process_lanes.classify_process_lane(
                {"title": spec["goal"], "goal": spec["goal"], "allowed_files": owned_files}
            )
            status = "AWAITING_HUMAN_SAFETY" if boundary["mode"] == "HUMAN_APPROVAL_REQUIRED" else "SCHEDULED"
            record = {
                "card_id": card_id,
                "status": status,
                "admitted": False,
                "launch_receipt": None,
                "lane": lane,
                "goal": spec["goal"],
                "raw_sha256": spec["raw_sha256"],
                "mia_tier": spec["mia_tier"]["tier"],
                "owner": primary["owner"],
                "judge": primary["judge"],
                "allow_files": owned_files,
                "gear_dag": dag,
                "brain_labor_plan": dag.get("brain_labor_schedule"),
                "resource_plan": alloc,
                "boundary": boundary,
                "completed_stages": [],
                "tikitaka_turns": 0,
                "failure_counts": {},
                "created_at": moment,
            }
            state["cards"][card_id] = record
            ingested.append({"card_id": card_id, "status": status, "lane": lane, "owner": primary["owner"], "judge": primary["judge"]})

        # Separate observer cycles from admission + worker launch (universal gate for raw-idea & routed cards).
        executing_files: set[str] = set(locked)
        for existing in state["cards"].values():
            if isinstance(existing, dict) and existing.get("status") in ("DISPATCHED", "EXECUTING"):
                executing_files.update(existing.get("allow_files") or ())

        dispatched: list[str] = []
        if not is_observer and not is_dry_run:
            for cid in sorted(state["cards"]):
                card = state["cards"][cid]
                if not isinstance(card, dict) or card.get("status") != "SCHEDULED":
                    continue
                if card.get("blocked_reason"):
                    continue
                owner = str(card.get("owner") or "").strip()
                if not owner:
                    continue
                if not (isinstance(admitted, dict) and admitted.get(owner) is True):
                    continue
                if not callable(launcher):
                    continue
                card_files = set(card.get("allow_files") or ())
                if card_files & executing_files:
                    continue
                try:
                    receipt = launcher(dict(card))
                except Exception:  # noqa: BLE001 - failed window launch must keep card SCHEDULED
                    continue
                if not (isinstance(receipt, dict) and receipt.get("opened") is True):
                    continue
                card["admitted"] = True
                card["launch_receipt"] = dict(receipt)
                card["status"] = "DISPATCHED"
                card["step_lease_expires_at"] = moment + 900.0
                executing_files.update(card_files)
                dispatched.append(cid)

        rsi_packet = synthesize_rsi_loop(root, now=moment, dry_run=is_dry_run)

        inbox_dir = root / ".coord" / "mailbox" / "inbox"
        pending_inbox = sum(1 for p in inbox_dir.glob("*.json")) if inbox_dir.is_dir() else 0
        compaction = (
            mailbox_mod.compact_inbox(root, keep_recent_events=100, dry_run=is_dry_run)
            if pending_inbox >= int(inbox_compact_threshold)
            else {"ok": True, "moved_count": 0, "skipped": "BELOW_THRESHOLD"}
        )

        if not is_dry_run:
            state["updated_at"] = moment
            save_os_state(root, state)
            append_journal_event(
                root,
                {
                    "event": "OS_TICK",
                    "recovered": recovered,
                    "thawed": thawed,
                    "ingested": [x["card_id"] for x in ingested],
                    "dispatched": dispatched,
                    "rsi_candidates": rsi_packet["candidate_count"],
                    "compacted": compaction.get("moved_count", 0),
                },
            )

        return {
            "ok": True,
            "dry_run": is_dry_run,
            "tool_states": tool_states,
            "brain_labor_summary": brain_labor_summary,
            "ollama_cellular_audit": ollama_cellular_audit,
            "recovered_cards": recovered,
            "thawed_cards": thawed,
            "ingested": ingested,
            "dispatched": dispatched,
            "rsi_candidates": rsi_packet["candidate_count"],
            "compacted_inbox": compaction.get("moved_count", 0),
        }
