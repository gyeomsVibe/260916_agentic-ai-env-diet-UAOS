"""U69: refuse a paid call before it starts when its contract cannot pay for even the cheapest call seen so far.

The cost gate (B85) judges a paid run after it has spent. U67-C1 showed the gap: a Claude review under a 12,000-token
contract spent 485,172 tokens and $0.43 before the gate threw the result away. Every Claude call re-reads a fixed
context (system prompt, tools, the staged files it opens) as cache reads, so a call has a floor no contract can go under.

The floor is measured, not guessed: the smallest complete spend the project's own usage ledger holds for that worker
and call kind. The minimum is a lower bound, so the gate only refuses a budget that no recorded call has ever fit; it
never refuses a call that might fit. Without a sample the call is admitted as UNMEASURED, because refusing then would
make the first measurement impossible.

Decisions:
- ADMIT: every dimension that has a floor fits its budget.
- ADMIT_UNMEASURED: no complete sample yet for this worker and kind.
- REFUSE: a budget is below its floor; the reason names the dimension, e.g. BUDGET_BELOW_FLOOR:tokens:12000<124769.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .pilot import COST_TOKEN_KEYS

LEDGER = Path(".coord") / "usage" / "runs.jsonl"


def _whole(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def ledger_rows(project: Path) -> list[dict[str, Any]]:
    """Every readable row of the project's usage ledger. Unreadable lines are skipped: they carry no spend to learn."""
    from .coord.usage_ledger import ledger_file

    # U72-L: a worktree reads the desk ledger it writes to, so its floor is the repository's floor.
    path = ledger_file(Path(project))
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    rows = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def observed_floor(rows: list[dict[str, Any]], worker: str, kind: str) -> dict[str, int] | None:
    """The cheapest complete spend for *worker* and *kind*: tokens always, micro-dollars and seconds when reported.

    A row counts only when all four token kinds are whole numbers. A row that omitted cache reads would look cheaper
    than the call really was and pull the floor down to a value no real call reaches.
    """
    tokens: list[int] = []
    microusd: list[int] = []
    seconds: list[int] = []
    for row in rows:
        if row.get("worker") != worker or row.get("kind") != kind:
            continue
        counts = [_whole(row.get(key)) for key in COST_TOKEN_KEYS]
        if any(count is None for count in counts):
            continue
        tokens.append(sum(counts))  # type: ignore[arg-type]
        if _whole(row.get("cost_microusd")) is not None:
            microusd.append(row["cost_microusd"])
        wall = row.get("wall_time_s")
        if isinstance(wall, (int, float)) and not isinstance(wall, bool) and wall >= 0:
            seconds.append(int(wall))
    if not tokens:
        return None
    floor = {"tokens": min(tokens), "samples": len(tokens)}
    if microusd:
        floor["microusd"] = min(microusd)
    if seconds:
        floor["seconds"] = min(seconds)
    return floor


def admit(project: Path, *, worker: str, kind: str, budget_tokens: int, budget_usd: float = 0.0,
          timeout_s: int = 0) -> dict[str, Any]:
    """Compare the contract's token, dollar and time budgets with the observed floor, before any spend."""
    floor = observed_floor(ledger_rows(project), worker, kind)
    if floor is None:
        return {"decision": "ADMIT_UNMEASURED", "worker": worker, "kind": kind, "floor": None}
    reasons = []
    if budget_tokens < floor["tokens"]:
        reasons.append(f"BUDGET_BELOW_FLOOR:tokens:{budget_tokens}<{floor['tokens']}")
    cap_microusd = int(round(budget_usd * 1_000_000))
    if cap_microusd > 0 and "microusd" in floor and cap_microusd < floor["microusd"]:
        reasons.append(f"BUDGET_BELOW_FLOOR:usd:{budget_usd:g}<{floor['microusd'] / 1_000_000:g}")
    if timeout_s > 0 and "seconds" in floor and timeout_s < floor["seconds"]:
        reasons.append(f"BUDGET_BELOW_FLOOR:seconds:{timeout_s}<{floor['seconds']}")
    return {"decision": "REFUSE" if reasons else "ADMIT", "worker": worker, "kind": kind, "floor": floor,
            "reasons": reasons}
