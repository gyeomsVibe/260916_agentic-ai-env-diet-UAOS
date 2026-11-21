"""U327: release-adaptive model and thinking-level router.

Model ids, roles, thinking levels and rollout state are data in `model_registry.json`. A new model release is a
registry edit (lifecycle shadow -> canary -> active) and needs no `.py` change. Pure functions: nothing here calls a
network or a paid model; quota is a gate only and is never converted into tokens.

select_model = profile the card nature -> filter by constraints and quota -> argmax weighted fitness score.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import os
import re
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REGISTRY_ENV = "UAOS_MODEL_REGISTRY"
DEFAULT_REGISTRY_PATH = Path(__file__).with_name("model_registry.json")
TOOLS = ("codex", "antigravity", "claude", "ollama")
ROLES = ("primary", "helper", "calculator")
LIFECYCLES = ("shadow", "canary", "active", "rolled_back")
LEVELS = ("Low", "Medium", "High")
STATUSES = ("active", "deprecated")
RISK_POLICIES = ("strict", "med")  # strict = default: no extra thinking down-step
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# Quota band states, best to worst. The worse of the 5h and weekly bands wins.
_STATE_RANK = {"OK": 0, "BOOTSTRAP": 1, "UNKNOWN": 2, "LIMITED": 3}
# Order used to pick an independent shadow judge: never the shadow's own tool nor the incumbent's.
JUDGE_ORDER = ("codex", "claude", "antigravity")


def registry_path(path: str | Path | None = None) -> Path:
    return Path(path or os.environ.get(REGISTRY_ENV) or DEFAULT_REGISTRY_PATH)


def _vendor_url_ok(url: str, allow: tuple[str, ...]) -> bool:
    """https only, and the host must be a vendor domain or one of its subdomains (host suffix, not substring)."""
    parts = urlsplit(str(url or ""))
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(host == d or host.endswith("." + d) for d in allow)


def validate_registry(reg: dict[str, Any]) -> None:
    allow = tuple(reg.get("source_allowlist") or ())
    if not allow:
        raise ValueError("registry has no source_allowlist")
    seen_ids: set[tuple[Any, Any]] = set()
    for m in reg.get("models") or ():
        mid = m.get("model_id")
        if not isinstance(mid, str) or not mid.strip():
            raise ValueError(f"model_id must be a non-empty string: {mid!r}")
        if (m.get("tool"), mid) in seen_ids:
            raise ValueError(f"{mid}: duplicate model_id for tool {m.get('tool')!r}")
        seen_ids.add((m.get("tool"), mid))
        # thinking_param_name is only meaningful for a paid model (a local Ollama calculator has no effort parameter)
        for key in ("display",) + (("thinking_param_name",) if m.get("paid", True) else ()):
            if not isinstance(m.get(key), str) or not m[key].strip():
                raise ValueError(f"{mid}: {key} must be a non-empty string")
        if m.get("status") not in STATUSES:
            raise ValueError(f"{mid}: status must be active|deprecated")
        if "released_at" not in m or (m["released_at"] is not None and not _ISO_DATE.fullmatch(str(m["released_at"]))):
            raise ValueError(f"{mid}: released_at must be present as YYYY-MM-DD or null")
        if isinstance(m.get("relative_cost"), bool) or not isinstance(m.get("relative_cost"), (int, float)) or m["relative_cost"] < 0:
            raise ValueError(f"{mid}: relative_cost must be a number >= 0")
        if not isinstance(m.get("capabilities"), dict) or not m["capabilities"]:
            raise ValueError(f"{mid}: capabilities missing")
        if m.get("tool") not in TOOLS:
            raise ValueError(f"{mid}: unknown tool {m.get('tool')!r}")
        if m.get("lifecycle") not in LIFECYCLES:
            raise ValueError(f"{mid}: unknown lifecycle {m.get('lifecycle')!r}")
        if not set(m.get("roles") or ()) or not set(m["roles"]) <= set(ROLES):
            raise ValueError(f"{mid}: bad roles {m.get('roles')!r}")
        if not set(m.get("thinking_levels") or ()) <= set(LEVELS):
            raise ValueError(f"{mid}: bad thinking_levels")
        pct = m.get("traffic_pct")
        if isinstance(pct, bool) or not isinstance(pct, (int, float)) or not 0 <= pct <= 100:
            raise ValueError(f"{mid}: traffic_pct out of range")
        if not _vendor_url_ok(m.get("source_url"), allow):
            raise ValueError(f"{mid}: source_url not on the official allowlist")
        if not str(m.get("why") or "").strip():
            raise ValueError(f"{mid}: missing why")


def load_registry(path: str | Path | None = None) -> dict[str, Any]:
    target = registry_path(path)
    deadline = time.monotonic() + 2.0  # Windows: a reader can hit PermissionError while a writer's os.replace lands
    while True:
        try:
            reg = json.loads(target.read_text(encoding="utf-8"))
            break
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)
    validate_registry(reg)
    return reg


def save_registry(reg: dict[str, Any], path: str | Path | None = None) -> None:
    """Validate, then replace the file atomically (temp file + os.replace)."""
    validate_registry(reg)
    target = registry_path(path)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=target.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(reg, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def profile_task(card_nature: str | None, reg: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    profiles = reg["task_profiles"]
    raw = str(card_nature or "").strip()
    key = raw if raw in profiles else reg.get("nature_aliases", {}).get(raw) or reg.get("nature_aliases", {}).get(raw.upper())
    if key not in profiles:
        key = "code_gen"  # the commonest card nature (IMPL_CODE); unknown natures must not escalate to the costly profile
    return key, profiles[key]


def _band_state(band: Any) -> str:
    if isinstance(band, dict):
        if str(band.get("state", "")).upper() in _STATE_RANK:
            return str(band["state"]).upper()
        return "OK" if band.get("admit_paid") is True else "UNKNOWN"
    return "UNKNOWN"


def quota_view(q: Any) -> tuple[str, float | None]:
    """(state, used_pct) for one tool. 5h and weekly bands are tracked separately and the worse one wins; a flat
    {"state": ...} entry is read as both bands. Missing, malformed or UNKNOWN stays UNKNOWN (fail closed)."""
    if isinstance(q, bool):
        return ("OK" if q else "UNKNOWN"), None
    if not isinstance(q, dict):
        return "UNKNOWN", None
    if any(k in q for k in ("five_hour", "seven_day")):
        # A partial reading is not an OK reading: a missing band is UNKNOWN, so the worse-wins rule fails closed.
        bands = [q.get(k) for k in ("five_hour", "seven_day")]
    else:
        bands = [q]
    state = max((_band_state(b) for b in bands), key=_STATE_RANK.__getitem__)
    used = [b["used_pct"] for b in bands if isinstance(b, dict) and isinstance(b.get("used_pct"), (int, float))]
    return state, (max(used) if used else None)


def weighted_token_use(rows: list[dict[str, Any]] | None, reg: dict[str, Any]) -> float:
    """Sum of tokens x the model's relative_cost, so a primary/helper mix is measured in one capacity unit."""
    cost = {m["model_id"]: float(m["relative_cost"]) for m in reg["models"]}
    # An unknown model_id is charged the priciest known weight: undercounting would let BOOTSTRAP admit past its cap.
    worst = max(cost.values(), default=1.0)
    return sum(float(r.get("tokens", 0)) * cost.get(r.get("model_id"), worst) for r in (rows or ()))


def _quota_gate(quota_state: dict[str, Any] | None, tool: str, spent_weighted: float, policy: dict[str, Any]) -> tuple[bool, bool]:
    """(admitted, bootstrap). Fail closed: paid work needs an OK reading, or BOOTSTRAP for a tool that has no quota
    receipt yet, whose health and auth are both OK, and whose card is still under the hard per-card cap."""
    q = (quota_state or {}).get(tool)
    state, _ = quota_view(q)
    if state == "OK":
        return True, False
    if state == "BOOTSTRAP" and isinstance(q, dict):
        first_receipt_missing = int(q.get("receipts", 0)) == 0
        healthy = str(q.get("health", "")).upper() == "OK" and str(q.get("auth", "")).upper() == "OK"
        under_cap = spent_weighted < float(policy.get("bootstrap_card_cap_tokens", 0))
        return (first_receipt_missing and healthy and under_cap), True
    return False, False


def _pressure(quota_state: dict[str, Any] | None, tool: str, policy: dict[str, Any]) -> bool:
    _, used = quota_view((quota_state or {}).get(tool))
    return used is not None and used >= float(policy.get("pressure_used_pct", 70.0))


def bucket(card_id: str, model_id: str) -> int:
    """Deterministic 0..99 traffic bucket, so one card always sees the same side of a canary."""
    return int(hashlib.sha256(f"{card_id}|{model_id}".encode("utf-8")).hexdigest()[:8], 16) % 100


def fitness(entry: dict[str, Any], profile: dict[str, Any], pressure: bool = False) -> float:
    weights = dict(profile["weights"])
    if pressure and "cost" in weights:
        weights["cost"] = weights["cost"] * 2.0  # quota pressure: cheaper models weigh double; no token conversion
    caps = entry.get("capabilities") or {}
    score = sum(w * float(caps.get(k, 0.0)) for k, w in weights.items())
    if profile.get("prefer_local") and not entry.get("paid", True):
        score += 0.1  # local bonus: Ollama costs 0 paid tokens; kept small so a clearly better paid model can still win
    return round(score, 6)


def pick_thinking_level(entry: dict[str, Any], desired: str, pressure: bool, pin: bool = False, med_step: bool = False) -> str | None:
    """At most ONE down-step in total: quota pressure (unless pinned) and the med risk policy do not stack."""
    levels = [lv for lv in LEVELS if lv in (entry.get("thinking_levels") or ())]
    if not levels:
        return None
    idx = LEVELS.index(desired if desired in LEVELS else "Medium")
    if (pressure and not pin) or med_step:
        idx = max(0, idx - 1)
    return min(levels, key=lambda lv: (abs(LEVELS.index(lv) - idx), LEVELS.index(lv)))


def _eligible(m: dict[str, Any], tool: str | None, constraints: dict[str, Any]) -> bool:
    if m["status"] != "active" or m["lifecycle"] == "rolled_back":  # deprecated models are skipped by data alone
        return False
    if tool and m["tool"] != tool:
        return False
    if m.get("keypoint_only") and not constraints.get("keypoint"):
        return False
    roles = constraints.get("roles")
    if roles and not set(roles) & set(m["roles"]):
        return False
    if m["model_id"] in (constraints.get("exclude_models") or ()):
        return False
    if constraints.get("allow_paid") is False and m.get("paid", True):
        return False
    caps = m.get("capabilities") or {}
    for key, floor in (constraints.get("min_capability") or {}).items():
        if float(caps.get(key, 0.0)) < float(floor):
            return False
    return True


def select_model(
    tool: str | None,
    card_nature: str | None,
    constraints: dict[str, Any] | None = None,
    quota_state: dict[str, Any] | None = None,
    *,
    registry: dict[str, Any] | None = None,
    registry_file: str | Path | None = None,
) -> dict[str, Any]:
    """Pick one model and thinking level. `tool=None` ranks every tool. Constraint keys: roles, keypoint,
    exclude_models, allow_paid, min_capability {cap: floor}, card_id (canary/shadow bucket)."""
    cons = dict(constraints or {})
    reg = registry if registry is not None else load_registry(registry_file)
    policy = reg.get("rollout_policy", {})
    nature, profile = profile_task(card_nature, reg)
    card_id = str(cons.get("card_id") or "")
    risk = str(cons.get("risk_policy") or "strict")
    if risk not in RISK_POLICIES:
        raise ValueError(f"risk_policy must be one of {RISK_POLICIES}")
    # med: one thinking-effort down-step, only on the first attempt. It touches effort alone, never acceptance gates.
    med_step = risk == "med" and int(cons.get("retry", 0)) == 0
    spent = weighted_token_use(cons.get("card_usage"), reg)
    blocked_paid: list[str] = []
    bootstrap_tools: set[str] = set()
    ranked: list[tuple[float, dict[str, Any]]] = []
    shadows: list[tuple[float, dict[str, Any]]] = []
    for m in reg["models"]:
        if not _eligible(m, tool, cons):
            continue
        if m.get("paid", True):
            admitted, bootstrap = _quota_gate(quota_state, m["tool"], spent, policy)
            if not admitted:
                blocked_paid.append(m["model_id"])
                continue
            if bootstrap:
                bootstrap_tools.add(m["tool"])
        score = fitness(m, profile, _pressure(quota_state, m["tool"], policy))
        if m["lifecycle"] == "shadow":
            shadows.append((score, m))
        elif m["lifecycle"] == "active" or bucket(card_id, m["model_id"]) < float(m["traffic_pct"]):
            ranked.append((score, m))  # canary joins only inside its traffic bucket
    if not ranked:
        return {"route": "NONE", "tool": tool, "model_id": None, "thinking_level": None, "nature": nature,
                "reason": "no admissible model: paid routes need an explicit fresh quota OK (UNKNOWN fails closed)",
                "blocked_paid": blocked_paid, "shadow_eval": None}
    # Highest score; ties go to the cheaper (higher cost capability), then to the id, so the result is deterministic.
    ranked.sort(key=lambda sm: (-sm[0], -float((sm[1].get("capabilities") or {}).get("cost", 0.0)), sm[1]["model_id"]))
    score, best = ranked[0]
    pressure = _pressure(quota_state, best["tool"], policy)
    shadow_eval = None
    for s_score, s in sorted(shadows, key=lambda sm: (-sm[0], sm[1]["model_id"])):
        pct = float(s["traffic_pct"] or policy.get("shadow_traffic_pct", 5))
        if bucket(card_id, s["model_id"]) < pct:
            judge = next((t for t in JUDGE_ORDER if t not in (s["tool"], best["tool"])), None)
            shadow_eval = {"model_id": s["model_id"], "tool": s["tool"], "score": s_score, "judge_tool": judge,
                           "note": "old result is returned; the shadow output is judged in the background by an independent tool"}
            break
    return {
        "route": "paid" if best.get("paid", True) else "local",
        "tool": best["tool"], "model_id": best["model_id"], "display": best.get("display", best["model_id"]),
        "lifecycle": best["lifecycle"], "score": score, "nature": nature,
        "thinking_level": pick_thinking_level(best, profile.get("thinking", "Medium"), pressure,
                                              pin=nature == "architecture", med_step=med_step),
        "thinking_param_name": best.get("thinking_param_name", ""),
        "risk_policy": risk, "acceptance_weakened": False,
        "bootstrap": best["tool"] in bootstrap_tools,
        "bootstrap_cap_tokens": int(policy.get("bootstrap_card_cap_tokens", 0)) if best["tool"] in bootstrap_tools else None,
        "weighted_tokens_spent": spent,
        "reason": profile["why"], "blocked_paid": blocked_paid, "shadow_eval": shadow_eval,
    }


# ---------------------------------------------------------------- lifecycle: shadow -> canary -> active, rollback

def evaluate_rollout(
    entry: dict[str, Any], metrics: dict[str, Any], baseline: dict[str, Any], policy: dict[str, Any]
) -> dict[str, Any]:
    """Decide rollback / promote / hold from measured metrics {samples, quality, cost, error_rate, timeout_rate}."""
    if entry["lifecycle"] not in ("shadow", "canary"):
        return {"action": "hold", "reason": f"lifecycle {entry['lifecycle']} is not under rollout"}
    if int(metrics.get("samples", 0)) < int(policy["min_samples"]):
        return {"action": "hold", "reason": "not enough samples"}
    q, bq = float(metrics["quality"]), float(baseline["quality"])
    c, bc = float(metrics["cost"]), float(baseline["cost"])
    if float(metrics.get("error_rate", 0.0)) > float(baseline.get("error_rate", 0.0)) + float(policy["error_spike_abs"]):
        return {"action": "rollback", "reason": "error spike vs incumbent"}
    if float(metrics.get("timeout_rate", 0.0)) > float(policy["timeout_rate_max"]):
        return {"action": "rollback", "reason": "timeout rate above limit"}
    if q < bq - float(policy["quality_drop_abs"]):
        return {"action": "rollback", "reason": "quality drop vs incumbent"}
    if not ((q >= bq and c <= bc) or q >= bq * (1.0 + float(policy["quality_gain_rel"]))):
        return {"action": "hold", "reason": "no promotion criterion met"}
    steps = [int(s) for s in policy["steps_pct"]]
    cur = int(entry["traffic_pct"]) if entry["lifecycle"] == "canary" else 0
    nxt = next((s for s in steps if s > cur), steps[-1])
    return {"action": "promote", "reason": "quality and cost criteria met", "next_traffic_pct": nxt,
            "next_lifecycle": "active" if cur >= steps[-1] else "canary"}


def apply_rollout_decision(reg: dict[str, Any], tool: str, model_id: str, decision: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of the registry with the decision applied (pure)."""
    out = copy.deepcopy(reg)
    entry = next((m for m in out["models"] if m["tool"] == tool and m["model_id"] == model_id), None)
    if entry is None:
        raise KeyError(f"{tool}/{model_id} not in registry")
    if decision["action"] == "rollback":
        entry.update(lifecycle="rolled_back", traffic_pct=0, rollback_reason=decision["reason"])
    elif decision["action"] == "promote":
        entry.update(lifecycle=decision["next_lifecycle"], traffic_pct=decision["next_traffic_pct"])
        entry.pop("rollback_reason", None)
    return out


def advance_rollout(
    tool: str, model_id: str, metrics: dict[str, Any], baseline: dict[str, Any], registry_file: str | Path | None = None
) -> dict[str, Any]:
    """Load the registry, evaluate one rollout step, persist the result atomically and return the decision.

    The whole read-modify-write runs under an OS-held lock (released by the kernel when the holder exits, never
    by an age guess, so a paused-but-alive holder keeps it), and the write is a compare-and-swap on the registry
    `revision` counter: if another writer changed the file since this call read it, the write is refused
    (RegistryConflict) instead of overwriting."""
    with _registry_lock(registry_file):
        reg = load_registry(registry_file)
        entry = next((m for m in reg["models"] if m["tool"] == tool and m["model_id"] == model_id), None)
        if entry is None:
            raise KeyError(f"{tool}/{model_id} not in registry")
        decision = evaluate_rollout(entry, metrics, baseline, reg["rollout_policy"])
        if decision["action"] != "hold":
            _commit_if_revision(apply_rollout_decision(reg, tool, model_id, decision), int(reg.get("revision", 0)), registry_file)
        return decision


class RegistryConflict(RuntimeError):
    """The registry file changed between this call's read and its write (a stale holder tried to write)."""


def _commit_if_revision(new_reg: dict[str, Any], read_revision: int, registry_file: str | Path | None) -> None:
    """Fencing token = the registry `revision`. Re-read the file just before writing; refuse unless it is still the
    revision this call started from, then write revision + 1."""
    current = json.loads(registry_path(registry_file).read_text(encoding="utf-8"))
    if int(current.get("revision", 0)) != read_revision:
        raise RegistryConflict(f"registry revision moved {read_revision} -> {current.get('revision', 0)}; write refused")
    new_reg["revision"] = read_revision + 1
    save_registry(new_reg, registry_file)


_LOCK_WAIT_S = 10.0  # a rollout step takes milliseconds; 10 s only bounds how long a caller queues behind a live holder
_THREAD_LOCK = threading.Lock()


def _os_lock(fh: Any) -> bool:
    """Try to take an exclusive OS lock on byte 0 of the open file; the kernel drops it when the process exits."""
    try:
        if os.name == "nt":
            import msvcrt

            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _os_unlock(fh: Any) -> None:
    if os.name == "nt":
        import msvcrt

        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def _registry_lock(registry_file: str | Path | None):
    """Cross-process OS lock on `<registry>.lock` plus an in-process thread lock. The lock file is never deleted and
    never judged stale by age: a holder that is merely paused still owns the lock, a crashed one loses it."""
    lock_path = registry_path(registry_file).with_name(registry_path(registry_file).name + ".lock")
    with _THREAD_LOCK:
        fh = open(lock_path, "a+b")
        try:
            deadline = time.monotonic() + _LOCK_WAIT_S
            while not _os_lock(fh):
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"registry lock busy: {lock_path}")
                time.sleep(0.02)
            try:
                yield
            finally:
                _os_unlock(fh)
        finally:
            fh.close()


# ---------------------------------------------------------------- day-0 lineup seats (used by helper_thinking_router)

def seat_model(reg: dict[str, Any], tool: str, seat: str) -> dict[str, Any] | None:
    """Best active entry of `tool` for a seat (primary/helper/calculator), ranked by that seat's profile."""
    profile = reg["task_profiles"][reg["seat_profiles"][seat]]
    cands = [m for m in reg["models"] if m["tool"] == tool and m["lifecycle"] == "active" and m["status"] == "active"
             and seat in m["roles"] and not m.get("keypoint_only")]
    if not cands:
        return None
    return max(cands, key=lambda m: (fitness(m, profile), m["model_id"]))


def keypoint_model(reg: dict[str, Any], tool: str) -> dict[str, Any] | None:
    """Best active keypoint_only entry of `tool`, ranked by the primary seat's profile (never by JSON list order)."""
    profile = reg["task_profiles"][reg["seat_profiles"]["primary"]]
    cands = [m for m in reg["models"] if m["tool"] == tool and m["lifecycle"] == "active" and m["status"] == "active" and m.get("keypoint_only")]
    if not cands:
        return None
    return max(cands, key=lambda m: (fitness(m, profile), m["model_id"]))
