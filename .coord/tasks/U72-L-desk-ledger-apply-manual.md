```contract
work_id: U72-L
worker: apply
goal: Route every usage-ledger write and read in a linked worktree to the main checkout's desk ledger, and add coord usage-collect to recover rows stranded in worktree copies, append-only and idempotent under parallel runs
inputs:
- v7_harness/coord/usage_ledger.py sha256=29be48a9b8d4693ccc89ca7f71bae5dc4645bd88cc6f5586563871794ee6902d
- v7_harness/admission.py sha256=65c958d74d04e7d71c8c74d05fc79e5405e60d985105387cf35837cce022cdd3
- v7_harness/rsi.py sha256=74b212f234a70b315c23a6e8fa8a6e0e1c8b9f0c494b2383c6dc989622588a8b
- v7_harness/cli.py sha256=5839c6352f624cf26eaac9832987ef3a8bdefe34e234296cd92baff820d38a6e
allow:
- v7_harness/coord/usage_ledger.py
- v7_harness/admission.py
- v7_harness/rsi.py
- v7_harness/cli.py
- tests/test_u72l_desk_ledger.py
- docs/59_u72l-desk-ledger.md
acceptance: python -m unittest tests.test_u72l_desk_ledger tests.test_u54_firewall_audit tests.test_u54_s2_caller_review tests.test_u69_admission_gate
forbidden: design changes; edits outside allow; weakening or deleting existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

U72 gate 'no ledger omission' fails: the desk ledger stops at U44-FIX6B because worktree pilots wrote into uncommitted worktree copies (142 orphan rows in 35 worktrees, dry run). On 58ba50b record_usage from a linked worktree writes to the worktree. Judge claude (ACTING while Codex is LIMITED); Codex re-reviews. Write the six files below exactly.

===FILE: v7_harness/coord/usage_ledger.py===
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{20,}"),
]

REQUIRED_KEYS = (
    "schema",
    "work_id",
    "actor",
    "model",
    "kind",
    "collection_mode",
    "input_tokens",
    "output_tokens",
    "wall_time_s",
    "outcome",
    "receipt",
    "independent_verifier",
    "rsi_eligible",
    "exclusion_reason",
)

NULLABLE_KEYS = {
    "model",
    "input_tokens",
    "output_tokens",
    "wall_time_s",
    "independent_verifier",
    "exclusion_reason",
}

NON_NULLABLE_KEYS = set(REQUIRED_KEYS) - NULLABLE_KEYS

NON_EMPTY_STRING_KEYS = (
    "schema",
    "work_id",
    "actor",
    "kind",
    "collection_mode",
    "outcome",
    "receipt",
)

NULLABLE_STRING_KEYS = (
    "model",
    "independent_verifier",
    "exclusion_reason",
)


class UsageRejected(Exception):
    """Raised when a usage record fails validation or secret check."""
    pass


def _check_secrets(obj: Any) -> None:
    if isinstance(obj, str):
        for pat in SECRET_PATTERNS:
            if pat.search(obj):
                raise UsageRejected("secret detected in usage record")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _check_secrets(k)
            _check_secrets(v)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _check_secrets(item)


def record_usage(
    project_root: Path,
    entry: dict[str, Any],
    lock_timeout_s: float = 10.0,
) -> Path:
    if not isinstance(entry, dict):
        raise UsageRejected("entry must be a dict")

    for k in REQUIRED_KEYS:
        if k not in entry:
            raise UsageRejected(f"missing required key: {k}")
        if k in NON_NULLABLE_KEYS and entry[k] is None:
            raise UsageRejected(f"key cannot be null: {k}")

    # schema validation
    if entry["schema"] != "uaos-usage-v2":
        raise UsageRejected("schema must equal 'uaos-usage-v2'")

    # non-empty string validation
    for k in NON_EMPTY_STRING_KEYS:
        val = entry[k]
        if not isinstance(val, str) or len(val.strip()) == 0:
            raise UsageRejected(f"{k} must be a non-empty string")

    # nullable string validation
    for k in NULLABLE_STRING_KEYS:
        val = entry[k]
        if val is not None and not isinstance(val, str):
            raise UsageRejected(f"{k} must be a string or null")

    # rsi_eligible validation
    if not isinstance(entry["rsi_eligible"], bool):
        raise UsageRejected("rsi_eligible must be bool")

    # token counts validation
    for token_key in ("input_tokens", "output_tokens"):
        val = entry[token_key]
        if val is not None:
            if isinstance(val, bool) or not isinstance(val, int) or val < 0:
                raise UsageRejected(f"{token_key} must be a non-negative integer or null")

    # wall_time_s validation
    wall_time = entry["wall_time_s"]
    if wall_time is not None:
        if isinstance(wall_time, bool) or not isinstance(wall_time, (int, float)) or wall_time < 0:
            raise UsageRejected("wall_time_s must be a non-negative number or null")

    # Secret check on all values/strings
    _check_secrets(entry)

    # Immutability & ts handling
    record = dict(entry)
    if "ts" not in record or record["ts"] is None:
        record["ts"] = time.time()
    elif isinstance(record["ts"], bool) or not isinstance(record["ts"], (int, float)) or record["ts"] < 0:
        raise UsageRejected("ts must be a non-negative number")

    try:
        line = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    except (TypeError, ValueError) as err:
        raise UsageRejected(f"failed to serialize usage record: {err}") from err

    for pat in SECRET_PATTERNS:
        if pat.search(line):
            raise UsageRejected("secret detected in usage record")

    with _ledger_lock(Path(project_root), lock_timeout_s) as target_file:
        with open(target_file, "ab") as f:
            f.write(line.encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        return target_file


def ledger_file(project_root: Path) -> Path:
    """U72-L: the one ledger of a repository. A linked worktree's rows belong to the main checkout's desk (U59).

    Seen 2026-09-28: every pilot run from `.work/<id>` worktrees appended to that worktree's copy of the tracked
    `runs.jsonl`, which is never committed, so U68-U71 left no row in the desk ledger that admission and RSI read.
    """
    from .hook_context import shared_desk

    return shared_desk(Path(project_root)) / ".coord" / "usage" / "runs.jsonl"


class _ledger_lock:
    """The ledger's exclusive lock file; yields the ledger path. Fails closed with UsageRejected on timeout."""

    def __init__(self, project_root: Path, lock_timeout_s: float) -> None:
        self.target_file = ledger_file(project_root)
        self.lock_timeout_s = lock_timeout_s

    def __enter__(self) -> Path:
        self.target_file.parent.mkdir(parents=True, exist_ok=True)
        self.fd = _acquire(self.target_file.with_name("runs.jsonl.lock"), self.lock_timeout_s)
        return self.target_file

    def __exit__(self, *exc: Any) -> None:
        _release(self.fd, self.target_file.with_name("runs.jsonl.lock"))


def _acquire(lock_file: Path, lock_timeout_s: float) -> int:
    t_end = time.time() + lock_timeout_s
    fd: int | None = None
    while True:
        try:
            fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            break
        except (FileExistsError, PermissionError):
            if time.time() >= t_end:
                break
            time.sleep(0.005)

    if fd is None:
        raise UsageRejected("usage ledger lock timeout")
    return fd


def _release(fd: int, lock_file: Path) -> None:
    try:
        os.close(fd)
    except OSError:
        pass
    unlink_end = time.time() + 1.0
    while time.time() < unlink_end:
        try:
            os.unlink(str(lock_file))
            break
        except FileNotFoundError:
            break
        except OSError:
            time.sleep(0.002)


def _row_key(line: str) -> str | None:
    """A row's identity: its parsed JSON in canonical form, so CRLF checkouts and key order do not split one row."""
    try:
        row = json.loads(line)
    except ValueError:
        return None
    if not isinstance(row, dict):
        return None
    return json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _rows(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return [line.strip() for line in text.splitlines() if line.strip()]


def linked_worktrees(desk: Path) -> list[Path]:
    """Every linked checkout of this repository, read from `<desk>/.git/worktrees/<name>/gitdir`.

    Git records each linked worktree there as the path of its `.git` file. Reading those files needs no subprocess,
    so this adds no command-execution site to the U54 firewall audit.
    """
    trees = []
    for record in sorted((Path(desk) / ".git" / "worktrees").glob("*/gitdir")):
        try:
            marker = Path(record.read_text(encoding="utf-8").strip())
        except (OSError, UnicodeDecodeError):
            continue
        if marker.name == ".git" and marker.parent.is_dir():
            trees.append(marker.parent)
    return trees


def collect(project_root: Path, *, trees: list[Path] | None = None, apply: bool = False,
            lock_timeout_s: float = 10.0) -> dict[str, Any]:
    """U72-L: find rows that exist only in a worktree's ledger copy and, with apply, append them to the desk ledger.

    A row counts once however many worktrees hold it. The rows are appended byte for byte as their worktree wrote
    them (never re-validated or re-stamped: the ledger is append-only history). The whole read-compare-append runs
    under the ledger lock, so two collectors at once still append each row once.
    """
    desk = ledger_file(Path(project_root)).parent.parent.parent
    trees = linked_worktrees(desk) if trees is None else trees
    with _ledger_lock(desk, lock_timeout_s) as target_file:
        known = {key for key in map(_row_key, _rows(target_file)) if key}
        orphans: list[str] = []
        by_tree: dict[str, int] = {}
        for tree in trees:
            for line in _rows(Path(tree) / ".coord" / "usage" / "runs.jsonl"):
                key = _row_key(line)
                if key is None or key in known:
                    continue
                _check_secrets(json.loads(line))
                known.add(key)
                orphans.append(line)
                by_tree[str(tree)] = by_tree.get(str(tree), 0) + 1
        if apply and orphans:
            data = target_file.read_bytes() if target_file.is_file() else b""
            prefix = b"\n" if data and not data.endswith(b"\n") else b""
            with open(target_file, "ab") as f:
                f.write(prefix + "".join(line + "\n" for line in orphans).encode("utf-8"))
                f.flush()
                os.fsync(f.fileno())
    return {"ledger": str(target_file), "trees": len(trees), "orphans": len(orphans), "by_tree": by_tree,
            "appended": len(orphans) if apply else 0, "mode": "APPLY" if apply else "DRY_RUN"}
===FILE: v7_harness/admission.py===
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
===FILE: v7_harness/rsi.py===
"""Evidence-gated self-improvement (RSI) for UAOS: observe → propose → try → gate → judge → (rollback).

The loop proposes; it never adopts itself. Why it stops short of self-adoption (docs/38):
- Self-improving agents game their evaluators: the Darwin Gödel Machine removed its own hallucination-detection markers,
  METR saw o3 patch a scorer and a timer, STOP disabled its sandbox flag "for efficiency".
- Without external feedback, self-correction does not reliably help (Huang et al., ICLR 2024), and LLM judges prefer
  their own outputs (self-preference bias).
- A poisoned evaluation set keeps contaminating later generations of a self-modifying agent (Roesner & Kohno 2026).
So every candidate is judged on executed evidence read from this project's own ledger (never on numbers the author
types in), by a verifier other than its author, without touching the evaluators or the evidence, and a judge who is
neither the author nor the verifier makes the final call. Adopted policy changes keep the previous value for rollback.

What may evolve: the knobs in `.coord/rsi/policy.json` (only toward stricter values), manual templates, task cards and
docs. Code and evaluators change only through the normal reviewed path (PLAN card → pilot → judge), never through here.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import statistics
import time
from collections import Counter
from pathlib import Path
from typing import Any

POLICY_PATH = Path(".coord") / "rsi" / "policy.json"
DECISIONS_PATH = Path(".coord") / "rsi" / "decisions.jsonl"
LEDGER_PATH = Path(".coord") / "usage" / "runs.jsonl"

DEFAULT_POLICY: dict[str, Any] = {
    # docs/24·docs/30: a local model gets a manual that scores at least 80 for concreteness.
    "local_min_specificity": 80,
    "remote_min_specificity": 60,
    # docs/27·docs/31: analyze after 10 comparable samples; below 3 nothing is concluded.
    "window": 10,
    "min_samples": 3,
    # docs/27 §4: a run that costs more than 3x the previous comparable run fails the cost gate.
    "max_cost_ratio": 3.0,
}
# The documented values are floors (or a ceiling for the cost ratio). A policy may only get stricter: a loop that could
# lower min_samples to 1 or raise the cost ratio to 100 would be grading its own homework.
POLICY_BOUNDS: dict[str, tuple[float, float]] = {
    "local_min_specificity": (80, 100),
    "remote_min_specificity": (60, 100),
    "window": (10, 100),
    "min_samples": (3, 50),
    "max_cost_ratio": (1.0, 3.0),
}

# Things the gate never lets the loop change: the evaluators, the evidence and the loop itself.
EVALUATOR_PATTERNS = (
    "tests/*",
    ".githooks/*",
    ".coord/runs/run_regression.py",
    ".coord/usage/*",
    str(DECISIONS_PATH.as_posix()),
    "v7_harness/rsi.py",
    "v7_harness/manual.py",
    "v7_harness/calculator_gate.py",
    "v7_harness/olla_evidence.py",
    "v7_harness/accept_triage.py",
    "v7_harness/adapters/ollama_worker.py",
    "v7_harness/isolation/*",
)
# Things the loop may change (through the gate and the judge). fnmatch's `*` also crosses `/`.
RSI_TARGET_PATTERNS = (POLICY_PATH.as_posix(), ".coord/tasks/*", "docs/*")

# docs/31 §3: Antigravity may verify someone else's change; the final call is Codex's (Claude while Codex is absent).
VERIFIERS = ("codex", "claude", "antigravity")
JUDGES = ("codex", "claude", "user")

# Deterministic remedies per failure cause. Adding a remedy is a reviewed code change, not something the loop does.
REMEDIES: dict[str, tuple[str, str]] = {
    "UNREQUESTED_DELETION": ("manual_template", "Ask for ===EDIT blocks, quote the SEARCH text, add the tests that import the file to acceptance; if the code is already known use worker: apply"),
    "SYNTAX_ERROR": ("manual_template", "Split the task per file and quote the exact SEARCH text; for dictated code use worker: apply"),
    "SCOPE_VIOLATION": ("manual_template", "Name the exact file in the goal and keep allow to that file"),
    "EDIT_SEARCH_NOT_FOUND": ("manual_template", "Copy the SEARCH lines verbatim from the pinned input into the manual"),
    "EDIT_SEARCH_AMBIGUOUS": ("manual_template", "Extend the SEARCH text until it is unique"),
    "PROMPT_TOO_LARGE": ("manual_template", "Split the input or summarise it first (olla read map); keep one file per manual"),
    "NO_CHANGES": ("manual_template", "State one concrete verb and the exact file; read-only tasks need --allow-no-changes"),
    "PROVIDER_ERROR": ("environment", "Check that the Ollama service and model are up; do not escalate to a paid worker automatically"),
    "EXECUTION_ERROR": ("environment", "Check the worker command and the Ollama service before retrying"),
    "TIMEOUT": ("manual_template", "Split the task or raise timeout_s in the contract; reconcile the run first"),
    "ACCEPT_INFRA": ("environment", "Fix the environment (interpreter, PYTHONPATH, missing tool) before retrying; the worker is not at fault"),
    "ACCEPT_NOT_RUN": ("environment", "Make the acceptance command runnable in the staging directory"),
    "SOURCE_DIVERGED": ("environment", "Keep a single writer during pilot runs (QUIET_LOCK); retry after the other writer finishes"),
}


class RsiRefused(Exception):
    """An adoption or rollback that the rules do not allow. Carries the read-only gate evidence when there is some."""

    def __init__(self, message: str, *, evidence: dict[str, Any] | None = None, proposed_policy: str | None = None):
        super().__init__(message)
        self.evidence = evidence
        self.proposed_policy = proposed_policy


# B83 (Codex red team, 2026-09-25): author, verifier and judge are strings any tool on this OS account can write, and
# so are git authors and stream actors. No in-process check can make them an authentication boundary, so the loop
# never writes the policy or the decision log. The boundary is a reviewed commit (a human GitHub review and merge).
UNAUTHENTICATED_ACTOR = ("UNAUTHENTICATED_ACTOR: author, verifier and judge are unauthenticated names on this OS "
                         "account (B83), so nothing is written. Put the gate evidence and the proposed file in a PLAN "
                         "card; the change lands as a reviewed commit.")


# ---------------------------------------------------------------- policy


def policy_violations(values: dict[str, Any]) -> list[str]:
    """Keys that are unknown, not numbers, or outside the bounds (weaker than the documented floors)."""
    problems: list[str] = []
    for key, value in values.items():
        if key not in POLICY_BOUNDS:
            problems.append(f"POLICY_UNKNOWN_KEY:{key}")
            continue
        low, high = POLICY_BOUNDS[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            problems.append(f"POLICY_NOT_A_NUMBER:{key}")
        elif not low <= value <= high:
            problems.append(f"POLICY_OUT_OF_BOUNDS:{key}={value} (allowed {low}..{high}; the floors are the documented values)")
    if isinstance(values.get("min_samples"), (int, float)) and isinstance(values.get("window"), (int, float)):
        if values["min_samples"] > values["window"]:
            problems.append("POLICY_INCONSISTENT:min_samples>window")
    return problems


def load_policy(project: Path) -> dict[str, Any]:
    """The documented defaults, overridden by `.coord/rsi/policy.json` only where the stored value is within bounds."""
    policy = dict(DEFAULT_POLICY)
    path = Path(project) / POLICY_PATH
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return policy
    if not isinstance(stored, dict):
        return policy
    for key in DEFAULT_POLICY:
        if key in stored and not policy_violations({key: stored[key]}):
            policy[key] = stored[key]
    if policy["min_samples"] > policy["window"]:
        policy["min_samples"], policy["window"] = DEFAULT_POLICY["min_samples"], DEFAULT_POLICY["window"]
    return policy


# ---------------------------------------------------------------- observe


def load_rows(project: Path) -> list[dict[str, Any]]:
    """Pilot rows of the project's usage ledger, oldest first. Unreadable lines are counted, never silently dropped."""
    from .coord.usage_ledger import ledger_file

    # U72-L: the desk ledger, also when RSI runs inside a linked worktree.
    path = ledger_file(Path(project))
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    # A last line without its newline is still being appended by a pilot (the sentinel reads without the ledger
    # lock); it is read on the next cycle instead of being counted as unreadable.
    for line in lines[:-1] if not text.endswith("\n") else lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            rows.append({"kind": "pilot", "outcome": "UNREADABLE", "worker": "unknown"})
            continue
        if isinstance(row, dict) and row.get("kind") == "pilot":
            rows.append(row)
    rows.sort(key=_ts)
    return rows


def _ts(row: dict[str, Any]) -> float:
    ts = row.get("ts")
    return float(ts) if isinstance(ts, (int, float)) and not isinstance(ts, bool) else 0.0


def _cause(row: dict[str, Any]) -> str | None:
    if row.get("outcome") == "PASS":
        return None
    error_class = row.get("error_class")
    if error_class and error_class != "NONE":
        return str(error_class)
    detail = str(row.get("error_detail") or "")
    for known in REMEDIES:
        if known in detail:
            return known
    return str(row.get("rework_class") or row.get("outcome") or "UNKNOWN")


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    outcomes = Counter(str(row.get("outcome")) for row in rows)
    tokens = [
        row["input_tokens"] for row in rows
        if isinstance(row.get("input_tokens"), int) and not isinstance(row.get("input_tokens"), bool)
    ]
    return {
        "n": n,
        "pass_rate": round(outcomes["PASS"] / n, 3) if n else None,
        "rework_rate": round(outcomes["REWORK"] / n, 3) if n else None,
        "blocked_rate": round(outcomes["BLOCKED"] / n, 3) if n else None,
        "median_input_tokens": statistics.median(tokens) if tokens else None,
    }


def analyze(rows: list[dict[str, Any]], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = policy or DEFAULT_POLICY
    window = int(policy["window"])
    by_worker: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_worker.setdefault(str(row.get("worker") or "unknown"), []).append(row)
    workers: dict[str, Any] = {}
    for worker, worker_rows in sorted(by_worker.items()):
        recent = worker_rows[-window:]
        causes = Counter(cause for cause in (_cause(row) for row in recent) if cause)
        info = metrics(recent)
        if info["n"] < int(policy["min_samples"]):
            status = "INSUFFICIENT_SAMPLES"
        elif info["n"] < window:
            status = "PARTIAL_WINDOW"
        else:
            status = "WINDOW_READY"
        workers[worker] = {
            **info,
            "total": len(worker_rows),
            "status": status,
            "causes": causes.most_common(),
            # docs rule: the same cause twice means change the route, not retry longer.
            "recurring": sorted(cause for cause, count in causes.items() if count >= 2),
            "recent_work_ids": [row.get("work_id") for row in recent][-5:],
        }
    total = len(rows)
    return {
        "samples": total,
        "window": window,
        "dictation_share": round(len(by_worker.get("apply", [])) / total, 3) if total else None,
        "workers": workers,
        "note": "Account savings stay UNMEASURED without before/after usage snapshots (docs/27).",
    }


def local_usage(usage_log: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """U47-D1: the local model's `pilot_local` rows, without the fake ones, joined to the pilot ledger by work_id.

    A row with exactly 1 input and 1 output token is a test leftover (docs/48 §2: 64 of 193). It stays in the file and
    is counted as `fake_rows`, never summed. Unreadable lines are counted, not silently dropped.
    """
    path = Path(usage_log)
    ledger_ids = {str(row["work_id"]) for row in rows if row.get("work_id")}
    real: dict[str, Any] = {"runs": 0, "input_tokens": 0, "output_tokens": 0, "wall_s": 0.0,
                            "by_status": Counter(), "by_model": Counter()}
    out: dict[str, Any] = {"source": str(path), "present": path.is_file(), "rows": 0, "unreadable": 0,
                           "fake_rows": 0, "joined": 0, "unjoined": 0, "no_work_id": 0}
    lines = path.read_text(encoding="utf-8").splitlines() if out["present"] else []
    for line in lines:
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            out["unreadable"] += 1
            continue
        if not isinstance(rec, dict) or rec.get("event") != "pilot_local":
            continue
        out["rows"] += 1
        tokens_in, tokens_out = rec.get("input_tokens"), rec.get("output_tokens")
        if tokens_in == 1 and tokens_out == 1:
            out["fake_rows"] += 1
            continue
        real["runs"] += 1
        real["input_tokens"] += tokens_in if isinstance(tokens_in, int) and not isinstance(tokens_in, bool) else 0
        real["output_tokens"] += tokens_out if isinstance(tokens_out, int) and not isinstance(tokens_out, bool) else 0
        elapsed = rec.get("elapsed_s")
        real["wall_s"] += float(elapsed) if isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool) else 0.0
        real["by_status"][str(rec.get("status") or "unknown")] += 1
        real["by_model"][str(rec.get("model") or "unknown")] += 1
        work_id = rec.get("work_id")
        if not work_id:
            out["no_work_id"] += 1
        elif str(work_id) in ledger_ids:
            out["joined"] += 1
        else:
            out["unjoined"] += 1
    real["wall_s"] = round(real["wall_s"], 1)
    real["by_status"] = dict(real["by_status"])
    real["by_model"] = dict(real["by_model"])
    out["real"] = real
    out["note"] = ("Local tokens use no paid API tokens but are not zero total cost (local inference, wall time, "
                   "electricity); account savings stay UNMEASURED.")
    return out


# ---------------------------------------------------------------- propose


def propose(analysis: dict[str, Any], policy: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Deterministic proposals from the analysis. A proposal is a hypothesis for the judge, not a change."""
    policy = policy or DEFAULT_POLICY
    proposals: list[dict[str, Any]] = []
    for worker, info in analysis["workers"].items():
        if info["status"] == "INSUFFICIENT_SAMPLES":
            continue
        for cause, count in info["causes"]:
            target, action = REMEDIES.get(cause, ("review", f"No remedy on file for {cause}; the judge reviews the receipts"))
            proposals.append({
                "worker": worker,
                "cause": cause,
                "count": count,
                "recurring": cause in info["recurring"],
                "target": target,
                "action": action,
                "evidence": info["recent_work_ids"],
            })
        if (
            worker in ("local", "ollama")
            and info["status"] == "WINDOW_READY"
            and info["rework_rate"] is not None
            and info["rework_rate"] > 0.5
        ):
            current = int(policy["local_min_specificity"])
            raised = min(current + 5, int(POLICY_BOUNDS["local_min_specificity"][1]))
            proposals.append({
                "worker": worker,
                "cause": "HIGH_REWORK_RATE",
                "count": info["n"],
                "recurring": True,
                "target": "policy",
                "action": (f"Raise local_min_specificity from {current} to {raised} in {POLICY_PATH.as_posix()}, "
                           "or route this task family to worker: apply / agy"),
                "policy": {"local_min_specificity": raised},
                "evidence": info["recent_work_ids"],
            })
    for proposal in proposals:
        key = f"{proposal['worker']}|{proposal['cause']}|{proposal['target']}"
        proposal["id"] = "rsi_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    proposals.sort(key=lambda p: (not p["recurring"], -p["count"], p["id"]))
    return proposals


def candidate_template(proposal: dict[str, Any], author: str) -> dict[str, Any]:
    """A candidate file to fill after the trial runs. The metrics are computed from the ledger, never typed in."""
    return {
        "id": proposal["id"],
        "author": author,
        "verifier": "<codex|claude|antigravity, not the author>",
        "hypothesis": f"{proposal['action']} (cause {proposal['cause']} on worker {proposal['worker']})",
        "changed_paths": [POLICY_PATH.as_posix()] if proposal.get("policy") else ["<.coord/tasks/... or docs/...>"],
        "policy": proposal.get("policy", {}),
        "before_work_ids": list(proposal.get("evidence") or []),
        "after_work_ids": ["<work_ids of the trial runs, at least min_samples>"],
    }


# ---------------------------------------------------------------- gate


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in patterns)


def gate(candidate: dict[str, Any], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Decide from metrics whether a tried change may go to the judge. Use gate_from_ledger for real candidates.

    candidate = {"id", "author", "verifier", "changed_paths": [...], "policy": {optional new knob values},
                 "before": {n, pass_rate, rework_rate, blocked_rate, median_input_tokens}, "after": {same keys}}
    """
    policy = policy or DEFAULT_POLICY
    reasons: list[str] = []
    paths = [str(path) for path in candidate.get("changed_paths") or []]
    if not paths:
        reasons.append("NO_CHANGE_LISTED")
    touched = [path for path in paths if _matches(path, EVALUATOR_PATTERNS)]
    if touched:
        reasons.append("EVALUATOR_TOUCHED:" + ",".join(touched[:5]))
    outside = [path for path in paths if path not in touched and not _matches(path, RSI_TARGET_PATTERNS)]
    if outside:
        reasons.append("OUT_OF_RSI_SCOPE:" + ",".join(outside[:5]) + " (use the reviewed PLAN/pilot path)")
    proposed = candidate.get("policy") or {}
    if not isinstance(proposed, dict):
        reasons.append("POLICY_NOT_AN_OBJECT")
    else:
        reasons.extend(policy_violations({**policy, **proposed}))
        if proposed and POLICY_PATH.as_posix() not in [p.replace("\\", "/").removeprefix("./") for p in paths]:
            reasons.append(f"POLICY_CHANGE_NOT_LISTED:{POLICY_PATH.as_posix()}")

    author = str(candidate.get("author") or "").lower()
    verifier = str(candidate.get("verifier") or "").lower()
    if verifier not in VERIFIERS or verifier == author:
        reasons.append(f"SELF_OR_INVALID_VERIFIER:{verifier or 'none'} (author {author or 'unknown'})")

    before = candidate.get("before") or {}
    after = candidate.get("after") or {}
    minimum = int(policy["min_samples"])
    if (before.get("n") or 0) < minimum or (after.get("n") or 0) < minimum:
        reasons.append(f"INSUFFICIENT_SAMPLES:before={before.get('n', 0)},after={after.get('n', 0)},min={minimum}")
    else:
        # Several metrics at once: optimizing one number while another gets worse is how gaming shows up (Goodhart).
        if (after.get("pass_rate") or 0) < (before.get("pass_rate") or 0):
            reasons.append(f"REGRESSION:pass_rate {before.get('pass_rate')}→{after.get('pass_rate')}")
        for rate in ("rework_rate", "blocked_rate"):
            if (after.get(rate) or 0) > (before.get(rate) or 0):
                reasons.append(f"REGRESSION:{rate} {before.get(rate)}→{after.get(rate)}")
        before_tokens, after_tokens = before.get("median_input_tokens"), after.get("median_input_tokens")
        if before_tokens and after_tokens and after_tokens > float(policy["max_cost_ratio"]) * before_tokens:
            reasons.append(f"COST_REGRESSION:{before_tokens}→{after_tokens}")
        improved = (
            (after.get("pass_rate") or 0) > (before.get("pass_rate") or 0)
            or (after.get("rework_rate") or 0) < (before.get("rework_rate") or 0)
            or (before_tokens and after_tokens and after_tokens < before_tokens)
        )
        if not improved and not any(reason.startswith("REGRESSION") for reason in reasons):
            reasons.append("NO_GAIN")
    return {
        "id": candidate.get("id"),
        "decision": "REJECT" if reasons else "ADOPT_CANDIDATE",
        "reasons": reasons,
        "before": before,
        "after": after,
        "next": ("advisory evidence only: put it in a PLAN card; the change lands as a reviewed commit (B83)"
                 if not reasons else "keep the current policy"),
    }


def gate_from_ledger(project: Path, candidate: dict[str, Any], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """The gate on executed evidence: before/after metrics are recomputed from the ledger rows named by work_id."""
    policy = policy or load_policy(project)
    reasons: list[str] = []
    if "before" in candidate or "after" in candidate:
        reasons.append("SELF_REPORTED_METRICS: name before_work_ids/after_work_ids; the gate reads the ledger itself")
    before_ids = [str(i) for i in candidate.get("before_work_ids") or []]
    after_ids = [str(i) for i in candidate.get("after_work_ids") or []]
    repeated = sorted({i for i in before_ids if before_ids.count(i) > 1} | {i for i in after_ids if after_ids.count(i) > 1})
    if repeated:
        reasons.append("DUPLICATE_WORK_IDS:" + ",".join(repeated[:5]))
    overlap = sorted(set(before_ids) & set(after_ids))
    if overlap:
        reasons.append("OVERLAPPING_SAMPLES:" + ",".join(overlap[:5]))
    rows = load_rows(project)
    known = {str(row.get("work_id")) for row in rows}
    missing = [work_id for work_id in before_ids + after_ids if work_id not in known]
    if missing:
        reasons.append("EVIDENCE_NOT_IN_LEDGER:" + ",".join(missing[:5]))
    # One sample per task: a retried work_id leaves several ledger rows, and counting them all let a single task
    # meet min_samples on its own. The latest row (rows are sorted by ts) is that task's outcome.
    latest = {str(row.get("work_id")): row for row in rows}
    before_rows = [latest[i] for i in dict.fromkeys(before_ids) if i in latest]
    after_rows = [latest[i] for i in dict.fromkeys(after_ids) if i in latest]
    before_workers = {str(row.get("worker")) for row in before_rows}
    after_workers = {str(row.get("worker")) for row in after_rows}
    if before_rows and after_rows and before_workers != after_workers:
        reasons.append(f"NOT_COMPARABLE:workers {sorted(before_workers)} vs {sorted(after_workers)}")
    measured = {key: value for key, value in candidate.items() if key not in ("before", "after")}
    result = gate({**measured, "before": metrics(before_rows), "after": metrics(after_rows)}, policy)
    result["reasons"] = reasons + result["reasons"]
    result["workers"] = sorted(after_workers or before_workers)
    result["decision"] = "REJECT" if result["reasons"] else "ADOPT_CANDIDATE"
    if result["reasons"]:
        result["next"] = "keep the current policy"
    return result


# ---------------------------------------------------------------- judge, record, rollback


def read_decisions(project: Path) -> list[dict[str, Any]]:
    path = Path(project) / DECISIONS_PATH
    if not path.is_file():
        return []
    decisions = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            decisions.append(item)
    return decisions


def record_decision(project: Path, decision: dict[str, Any]) -> Path:
    path = Path(project) / DECISIONS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **decision}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def adopt(project: Path, candidate: dict[str, Any], judge: str) -> dict[str, Any]:
    """Fail closed (B83). Computes the read-only ledger gate as evidence, then refuses before writing anything.

    The refusal carries the gate verdict and, for a policy candidate, the exact proposed policy.json text, so the
    change can go through the normal PLAN card → reviewed commit path.
    """
    verdict = gate_from_ledger(project, candidate)
    proposed = None
    if isinstance(candidate.get("policy"), dict) and candidate["policy"]:
        proposed = json.dumps({**load_policy(project), **candidate["policy"]}, ensure_ascii=False, indent=2,
                              sort_keys=True) + "\n"
    raise RsiRefused(UNAUTHENTICATED_ACTOR, evidence=verdict, proposed_policy=proposed)


def open_trials(project: Path, rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Adoptions not rolled back yet: whether their re-check window is complete, and the window measured since."""
    rows = load_rows(project) if rows is None else rows
    decisions = read_decisions(project)
    rolled = {item.get("id") for item in decisions if item.get("action") == "ROLLED_BACK"}
    trials = []
    for item in decisions:
        if item.get("action") == "ADOPTED" and item.get("id") not in rolled:
            workers = [str(w) for w in item.get("workers") or []]
            recheck = int(item.get("recheck_at_rows") or 0)
            start = int(item.get("rows_at_adoption", max(0, recheck - int(DEFAULT_POLICY["window"]))))
            relevant = [row for row in rows if not workers or str(row.get("worker")) in workers]
            due = len(relevant) >= recheck
            trials.append({"id": item.get("id"), "workers": workers, "recheck_at_rows": recheck,
                           "rows_now": len(relevant), "due": due, "before": item.get("before"),
                           # Runs since the adoption; compare with "before" and `rsi rollback` if it is worse.
                           "since": metrics(relevant[start:]) if due else None})
    return trials


def rollback(project: Path, judge: str, reason: str) -> dict[str, Any]:
    """Fail closed (B83): a rollback writes the policy too. It proposes the previous policy and writes nothing."""
    previous = None
    for item in reversed(read_decisions(project)):
        if item.get("action") == "ADOPTED" and item.get("previous_policy"):
            previous = json.dumps(item["previous_policy"], ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            break
    raise RsiRefused(UNAUTHENTICATED_ACTOR, proposed_policy=previous)


# ---------------------------------------------------------------- sentinel hook


def rsi_review_messages(
    project: Path, analysis: dict[str, Any], policy: dict[str, Any] | None = None
) -> list[tuple[str, dict[str, Any]]]:
    """Mailbox messages (not P1), one per worker that completed a new analysis window. The id names the window,
    so the sentinel publishes each window once and never repeats it after it is read."""
    policy = policy or load_policy(project)
    messages = []
    for worker, info in analysis["workers"].items():
        window_count = info["total"] // int(policy["window"])
        if info["status"] != "WINDOW_READY" or window_count == 0:
            continue
        message_id = f"rsi_review_{worker}_{int(policy['window'])}x{window_count}"
        summary = (f"RSI window {window_count} for {worker}: pass {info['pass_rate']}, rework {info['rework_rate']}, "
                   f"recurring {','.join(info['recurring']) or 'none'} — run `rsi propose`")
        messages.append((message_id, {"kind": "RSI_REVIEW", "step": "RSI", "summary": summary[:200], "actor": "sentinel"}))
    return messages
===FILE: v7_harness/cli.py===
"""
Command-line interface for v7 harness.

Provides unified commands for:
- context lease validation
- intent ledger operations & integrity verification
- proof receipt execution
- deterministic snapshot capture
- next-stage eligibility evaluation
- A/B benchmark execution
- concise reporting
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Optional

from .benchmark_hook import BenchmarkHook
from .context_lease import ContextLease, ContextLeaseValidator
from .intent_ledger import IntentLedger
from .proof_receipt import ProofReceiptStore, run_with_receipt
from .reporter import generate_report
from .snapshot import take_snapshot
from .stage_evaluator import AcceptanceCheck, StageEvaluator

# 로컬 계산기가 멈추면(시간 초과·공급자 오류) 다음 계산기로 넘긴다 (실측 2026-09-23: qwen2.5-coder 7b 가 cli.py 과제에서 600초 PROVIDER_ERROR).


def cmd_lease_check(args: argparse.Namespace) -> int:
    lease_path = Path(args.file)
    if not lease_path.exists():
        print(f"Error: lease file '{lease_path}' does not exist.", file=sys.stderr)
        return 1

    with open(lease_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        leases = [ContextLease.from_dict(d) for d in data]
    else:
        leases = [ContextLease.from_dict(data)]

    validator = ContextLeaseValidator()
    results, valid_ids = validator.validate_lease_set(leases, target_scope=args.scope)

    all_valid = len(valid_ids) == len(leases)
    for lid, res in results.items():
        status = "VALID" if res.valid else "INVALID"
        print(f"[{status}] Lease {lid}: errors={res.errors}, warnings={res.warnings}")

    return 0 if all_valid else 2


def cmd_ledger_append(args: argparse.Namespace) -> int:
    ledger = IntentLedger(args.ledger_file)
    entry = ledger.append(
        task_id=args.task_id,
        actor=args.actor,
        category=args.category,
        content=args.content,
        rationale=args.rationale,
        assumption=args.assumption,
        invalidation_condition=args.invalidation_condition,
    )
    print(f"Appended entry: {entry.entry_id} (hash: {entry.entry_hash[:12]}...)")
    return 0


def cmd_ledger_verify(args: argparse.Namespace) -> int:
    ledger = IntentLedger(args.ledger_file)
    valid, reason = ledger.verify_integrity()
    if valid:
        print(f"Ledger integrity OK: {len(ledger.entries)} entries verified.")
        return 0
    else:
        print(f"Ledger integrity FAILED: {reason}", file=sys.stderr)
        return 1


def cmd_receipt_run(args: argparse.Namespace) -> int:
    cmd = list(args.cmd)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("Error: No command specified for receipt-run.", file=sys.stderr)
        return 2
    store = ProofReceiptStore(args.store) if args.store else None
    receipt = run_with_receipt(
        command=cmd,
        task_id=args.task_id,
        actor=args.actor,
        receipt_store=store,
    )
    print(json.dumps(receipt.to_dict(), indent=2, ensure_ascii=False))
    return receipt.exit_code


def cmd_snapshot(args: argparse.Namespace) -> int:
    snap = take_snapshot(target_path=args.target_path, force_non_git=args.force_non_git)
    if args.output:
        out_p = Path(args.output)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(snap.to_dict(), f, indent=2, ensure_ascii=False)
        print(f"Snapshot written to {out_p} (hash: {snap.snapshot_hash[:12]}..., type: {snap.snapshot_type})")
    else:
        print(json.dumps(snap.to_dict(), indent=2, ensure_ascii=False))
    return 0


def cmd_eval_next(args: argparse.Namespace) -> int:
    evaluator = StageEvaluator()
    # Dummy or CLI checks
    check = AcceptanceCheck(
        criterion_id="ALL",
        description="CLI passed checks",
        passed=not args.has_failures,
    )
    pending_actions = args.pending_actions or []
    eligibility = evaluator.evaluate_eligibility(
        current_task_id=args.current_task_id,
        checks=[check],
        pending_actions=pending_actions,
        next_task_candidate=args.next_task,
    )
    print(json.dumps(eligibility.to_dict(), indent=2, ensure_ascii=False))
    return 0 if eligibility.is_eligible else 1


def cmd_benchmark(args: argparse.Namespace) -> int:
    hook = BenchmarkHook(args.name)

    def dummy_baseline():
        sum(i * i for i in range(100_000))

    def dummy_candidate():
        sum(i * i for i in range(50_000))

    res = hook.run_comparison(dummy_baseline, dummy_candidate)
    print(json.dumps(res.to_dict(), indent=2, ensure_ascii=False))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    verification_str: Optional[str] = None
    if args.verification is not None:
        verification_str = ", ".join(args.verification)

    checks = [] if verification_str is not None else [("CLI test", 0)]
    rep = generate_report(
        result=args.result,
        changed=args.changed or [],
        checks=checks,
        risks=args.risks,
        next_action=args.next_action,
        user_action_required=args.user_action_required,
        verification=verification_str,
    )
    print(rep.to_concise_markdown())
    return 0


def manual_project(manual: Path) -> Path:
    """U45-F1: the project a manual's paths are relative to, when no --source is given: the nearest folder above the
    manual that holds .coord/PLAN.md, else the current folder. Lint run from another cwd used to report INPUT_MISSING
    for files that exist under the pilot source (U45-O1b)."""
    for folder in Path(manual).resolve().parents:
        if (folder / ".coord" / "PLAN.md").is_file():
            return folder
    return Path(".")


def mandatory_watch_roots(work_dir: Path, source_dir: Path) -> list[Path]:
    """Shallow roots a worker must not write into during a run.

    U45-F5: the work dir's parent used to be watched always. When that parent is a shared `.work/` folder, the
    conductor keeps writing its own notes there during a paid run (U45-G7 a001: two conductor files flagged, run
    abandoned, $0.319 lost). A shared `.work/` is therefore not watched; home, temp, the source's parent and the stage
    stay watched. A worker writing a sibling file inside `.work/` goes unseen, and `.work/` is never committed.
    """
    work = work_dir.resolve()
    return list(dict.fromkeys([
        Path.home().resolve(),
        Path(tempfile.gettempdir()).resolve(),
        *([] if work.parent.name == ".work" else [work.parent]),
        source_dir.resolve().parent,
        (work_dir / "stage").resolve(),
    ]))


def _admission(source_dir: Path, worker: str, contract: Optional[dict]) -> dict:
    """U69 admission for a paid pilot run under *contract* (see v7_harness/admission.py)."""
    from .admission import admit

    contract = contract or {}
    try:
        usd = float(contract.get("remote_budget_usd") or 0)
    except ValueError:
        usd = 0.0
    return admit(source_dir, worker=worker, kind="pilot", budget_tokens=int(contract.get("remote_budget_tokens") or 0),
                 budget_usd=usd, timeout_s=int(contract.get("timeout_s") or 0))


def cmd_pilot_run(args: argparse.Namespace) -> int:
    task_id = args.task
    source_dir = Path(args.source)
    if not source_dir.exists():
        print(f"Error: source directory '{source_dir}' does not exist.", file=sys.stderr)
        return 1

    # U34: a manual is a contract. It is linted before anything runs and its fields drive the run, so the
    # worker receives exactly the checked text and cannot change files outside `allow`.
    contract: Optional[dict] = None
    manual_path = getattr(args, "manual", None)
    if manual_path:
        from .manual import lint

        mfile = Path(manual_path)
        if not mfile.is_file():
            print(f"Error: manual '{mfile}' does not exist.", file=sys.stderr)
            return 1
        prompt = mfile.read_text(encoding="utf-8")
        report = lint(prompt, source_dir)
        if not report.ok:
            print(json.dumps({"task_id": task_id, "state": "REFUSED", "error_class": "MANUAL_INVALID",
                              "verdict_hint": "BLOCKED", "manual_errors": report.errors,
                              "manual_warnings": report.warnings}, indent=2, ensure_ascii=False))
            return 2
        contract = report.contract
        for warning in report.warnings:
            print(f"[manual] {warning}", file=sys.stderr)
        if contract.get("work_id") != task_id:
            # U45-F7: refuse before any worker runs. A warning here let a paid run finish first (U45-G7r, $0.263 lost).
            print(json.dumps({"task_id": task_id, "state": "REFUSED", "error_class": "MANUAL_TASK_MISMATCH",
                              "verdict_hint": "BLOCKED", "manual_work_id": contract.get("work_id")},
                             indent=2, ensure_ascii=False))
            return 2
        if args.approve:
            approver = getattr(args, "coord_actor", None) or detect_actor()
            # An approver the harness cannot identify used to pass silently (B85 review). Name it with --coord-actor.
            # This is a speed bump, not authentication: on one OS account every name can be forged (B83).
            if approver is None or approver != contract["judge"].lower():
                print(json.dumps({"task_id": task_id, "state": "REFUSED",
                                  "error_class": "APPROVER_UNKNOWN" if approver is None else "APPROVER_NOT_JUDGE",
                                  "verdict_hint": "BLOCKED", "judge": contract["judge"], "approver": approver},
                                 indent=2, ensure_ascii=False))
                return 2
    elif args.prompt_file:
        pfile = Path(args.prompt_file)
        if not pfile.is_file():
            print(f"Error: prompt file '{pfile}' does not exist.", file=sys.stderr)
            return 1
        prompt = pfile.read_text(encoding="utf-8")
    elif args.prompt:
        prompt = args.prompt
    else:
        print("Error: one of --manual, --prompt-file or --prompt must be provided.", file=sys.stderr)
        return 2

    # 실행 전에 지시문의 구체성을 알려 준다. 막지는 않는다. 벤치에서 로컬 모델이 실패한
    # 유일한 축이 모호함이었으므로, 고르기 전에 한 줄이라도 보이는 편이 낫다.
    from .adapters.ollama_worker import dictated_paths
    from .adapters.worker_advice import advise

    advice = advise(prompt)
    chosen = contract["worker"] if contract else getattr(args, "worker", "agy")
    # auto: 지휘자가 코드를 이미 적었으면(받아쓰기) 모델 없이 그대로 적용하고, 아니면 구체성으로 고른다.
    if chosen == "auto":
        if dictated_paths(prompt):
            chosen = "apply"
        else:
            chosen = "cascade" if advice.worker == "local" else "agy"
        routed = {"worker": chosen, "specificity": advice.specificity}
    else:
        routed = None
    if advice.worker != chosen and chosen != "apply":
        print(
            f"[조언] 지시문 구체성 {advice.specificity}/100 → --worker {advice.worker} 권장"
            f" (현재 {chosen}): {'; '.join(advice.reasons[:2])}",
            file=sys.stderr,
        )

    # U38: a Claude worker spends the same subscription as the Claude commander. When Claude reports LIMITED, the
    # commander keeps the remaining quota (docs/40 §2-1).
    uses_claude = chosen == "claude" or (chosen == "cascade" and getattr(args, "escalate_to", "agy") == "claude")
    if uses_claude and not args.approve:
        from .coord.presence import read as read_presence

        if read_presence(source_dir, "claude")["state"] == "LIMITED":
            print(json.dumps({"task_id": task_id, "state": "REFUSED", "error_class": "CLAUDE_LIMITED",
                              "verdict_hint": "BLOCKED",
                              "message": "Claude presence is LIMITED; its quota is kept for the commander"},
                             indent=2, ensure_ascii=False))
            return 2

    # B85 rework (Codex): a paid worker runs only under a contract. Without a manual there is no budget and no dollar
    # cap, and an approval could promote a run nothing ever measured.
    from .manual import REMOTE_WORKERS

    if chosen in REMOTE_WORKERS and contract is None:
        print(json.dumps({"task_id": task_id, "state": "REFUSED", "error_class": "REMOTE_WITHOUT_MANUAL",
                          "verdict_hint": "BLOCKED", "worker": chosen,
                          "message": "paid workers (agy, claude) need --manual with remote_budget_tokens"},
                         indent=2, ensure_ascii=False))
        return 2

    # U69: refuse before the call when the contract cannot pay for the cheapest call this worker has made here.
    # An --approve replays the saved bundle and spends nothing, so it is not admitted again.
    if chosen in REMOTE_WORKERS and not args.approve:
        admission = _admission(source_dir, chosen, contract)
        if admission["decision"] == "REFUSE":
            print(json.dumps({"task_id": task_id, "state": "REFUSED", "error_class": "ADMISSION_REFUSED",
                              "verdict_hint": "BLOCKED", "worker": chosen, "admission": admission},
                             indent=2, ensure_ascii=False))
            return 2

    # U70: a contract that names a task type reaches the local model only when this model artifact is QUALIFIED for
    # it. U67-O1b sent a JSON extraction to a model that fails that format; the gate would have refused it for free.
    task_type = (contract or {}).get("task_type", "")
    if chosen in ("local", "cascade") and task_type and not args.approve:
        from .adapters.ollama_worker import DEFAULT_MODEL as LOCAL_MODEL
        from .model_qualification import local_admission

        local_model = getattr(args, "model", None) or (contract or {}).get("model") or LOCAL_MODEL
        status = local_admission(source_dir, model=local_model, task_type=task_type)
        if status != "QUALIFIED":
            print(json.dumps({"task_id": task_id, "state": "REFUSED", "error_class": "LOCAL_NOT_QUALIFIED",
                              "verdict_hint": "BLOCKED", "worker": chosen, "model": local_model,
                              "task_type": task_type, "qualification": status},
                             indent=2, ensure_ascii=False))
            return 2

    work_dir = Path(args.work_dir) if args.work_dir else Path(".coord")
    mandatory_roots = mandatory_watch_roots(work_dir, source_dir)
    explicit_roots = [Path(w).resolve() for w in args.watch_root] if args.watch_root else []
    watch_roots = list(dict.fromkeys(mandatory_roots + explicit_roots))
    agy_cmd = resolve_worker_command(chosen, args.agy_command)
    # Pre-spend hard cap for a Claude worker (Codex): the contract's dollar cap goes to `claude --max-budget-usd`.
    # The token gate after the run stays; dollars are never inferred from tokens (model and cache prices differ).
    usd_cap = str(contract.get("remote_budget_usd") or "") if contract else ""

    def _with_cap(command: list[str], worker: str) -> list[str]:
        return [*command, "--max-budget-usd", usd_cap] if worker == "claude" and usd_cap else command

    agy_cmd = _with_cap(agy_cmd, chosen)

    from .pilot import PilotConfig, run_pilot

    allowed = list(contract["allow"]) if contract else []
    allowed += list(getattr(args, "allow", None) or [])
    remote_budget = int(contract.get("remote_budget_tokens") or 0) if contract else None
    config = PilotConfig(
        task_id=task_id,
        title=args.title or f"Pilot task {task_id}",
        prompt=prompt,
        source_dir=source_dir,
        work_dir=work_dir,
        agy_command=agy_cmd,
        watch_roots=watch_roots,
        print_timeout_s=int(contract["timeout_s"]) if contract else args.print_timeout,
        approve_bundle_id=args.approve,
        accept_cmd=args.accept_cmd or (contract["acceptance"] if contract else None),
        # U38: a contract may name its model (e.g. a Claude worker's Haiku or Sonnet); --model on the command line wins.
        model=getattr(args, "model", None) or ((contract.get("model") or None) if contract else None),
        allow_no_changes=getattr(args, "allow_no_changes", False),
        allowed_scopes=allowed or None,
        # B85: every paid run is checked against the contract budget, not only a cascade escalation.
        remote_budget_tokens=(remote_budget or None) if chosen in REMOTE_WORKERS else None,
    )

    from .broker.core import BrokerAlreadyRunning
    from .isolation.errors import SourceDivergenceError

    try:
        summary = run_pilot(config)
    except BrokerAlreadyRunning:
        summary = {
            "task_id": task_id,
            "state": "FAILED",
            "error_class": "BROKER_ALREADY_RUNNING",
            "effect_state": "NONE",
            "verdict_hint": "BLOCKED",
            "message": "Another broker is currently running on this work directory.",
        }
    except SourceDivergenceError as exc:
        summary = {
            "task_id": task_id,
            "state": "FAILED",
            "error_class": "SOURCE_DIVERGED",
            "effect_state": "NONE",
            "verdict_hint": "BLOCKED",
            "message": f"Source directory diverged from staging baseline: {exc}",
        }
    except sqlite3.DatabaseError as exc:
        summary = {
            "task_id": task_id,
            "state": "FAILED",
            "error_class": "DB_UNAVAILABLE",
            "effect_state": "UNKNOWN",
            "verdict_hint": "BLOCKED",
            "message": f"Database error or corruption: {exc}. Recovery hint: run 'python -m v7_harness.cli pilot reconcile --task {task_id}' or backup coord.sqlite3.",
        }

    # cascade: 싼 local 을 먼저 쓰고 실패 종류에 따라 한 번만 넘긴다. A/B(2026-09-23, 10과제): local 6/10·51.8초,
    # lane 9/10·218초(4.2배), 계산상 cascade 10/10·2.7배. 같은 id 재실행은 원장이 막으므로 단계마다 id가 다르다.
    # U39 (docs/41 §5): deterministic → Ollama once → Antigravity once. Only a format-only failure gets one more local
    # try, inside the same local budget; a semantic failure never loops locally; a remote failure goes to splitting.
    # The approval run stays on the original task. Every stage runs under its own task id.
    def _run(cfg: Any) -> dict[str, Any]:
        try:
            return run_pilot(cfg)
        except (BrokerAlreadyRunning, SourceDivergenceError, sqlite3.DatabaseError) as exc:
            return {"task_id": cfg.task_id, "state": "FAILED", "error_class": type(exc).__name__,
                    "effect_state": "UNKNOWN", "verdict_hint": "BLOCKED", "message": str(exc)}

    if chosen == "cascade" and not args.approve:
        from .routing import classify_failure, local_tokens, next_route

        failure = classify_failure(summary)
        used_local = local_tokens(summary)
        trace = [f"local:{failure or 'PASS'}"]
        route = next_route("local", failure, local_attempts=1, local_tokens=used_local)
        if route == "local_retry":
            config.task_id = f"{task_id}-retry"
            summary = _run(config)
            failure = classify_failure(summary)
            used_local += local_tokens(summary)
            trace.append(f"local_retry:{failure or 'PASS'}")
            route = next_route("local_retry", failure, local_attempts=2, local_tokens=used_local)
        if route == "remote":
            first = summary
            escalate_to = getattr(args, "escalate_to", "agy")
            escalation = (_admission(source_dir, escalate_to, contract)
                          if escalate_to in REMOTE_WORKERS and remote_budget else None)
            if escalate_to in REMOTE_WORKERS and not remote_budget:
                # B85 rework: no contract budget, no paid escalation (lane runs the local model and stays allowed).
                summary["escalation"] = "REFUSED:REMOTE_WITHOUT_MANUAL"
                trace.append("refused")
            elif escalation is not None and escalation["decision"] == "REFUSE":
                # U69: the same admission as a direct paid run; the local result stays the answer.
                summary["escalation"] = "REFUSED:ADMISSION:" + ";".join(escalation["reasons"])
                summary["admission"] = escalation
                trace.append("refused")
            else:
                config.task_id = f"{task_id}-{escalate_to}"
                config.agy_command = _with_cap(resolve_worker_command(escalate_to, None), escalate_to)
                config.remote_budget_tokens = (remote_budget or None) if escalate_to in REMOTE_WORKERS else None
                summary = _run(config)
                summary["cascade_from"] = {"task_id": task_id, "verdict_hint": first.get("verdict_hint"),
                                           "error_class": first.get("error_class"), "escalated_to": escalate_to}
                remote_failure = classify_failure(summary)
                trace.append(f"remote:{remote_failure or 'PASS'}")
                if next_route("remote", remote_failure, local_attempts=2, local_tokens=used_local) == "split":
                    trace.append("split")
        elif route == "stop":
            trace.append("stop")
        summary["route"] = trace
    # The pilot gates the budget itself (B85). This covers a summary that came back without the gate.
    if remote_budget and "cost_gate" not in summary and (chosen in REMOTE_WORKERS or "cascade_from" in summary):
        from .pilot import evaluate_cost_gate

        summary["cost_gate"] = evaluate_cost_gate(summary.get("agy_usage"), remote_budget)
        if summary["cost_gate"] != "WITHIN":
            summary["verdict_hint"] = "BLOCKED"
            summary["error_class"] = "COST_UNKNOWN" if summary["cost_gate"] == "UNKNOWN" else "COST_EXCEEDED"

    # U33: 보고는 기억이 아니라 실행 끝에서 저절로 남는다(비둘기 퇴출). 기록 대상은 --source 프로젝트이고,
    # .coord/PLAN.md 가 있는 UAOS 프로젝트일 때만 쓴다. 예전에 기본을 켰을 때 CLI 를 부르는 테스트가 실제
    # 스트림에 사건 8건을 흘렸다. 테스트 패키지는 UAOS_STREAM_AUTOLOG=0 으로 끈다(tests/__init__.py).
    if getattr(args, "coord_log", False) and os.environ.get("UAOS_STREAM_AUTOLOG", "1") != "0":
        coord_project = Path(getattr(args, "coord_project", None) or source_dir)
        actor = getattr(args, "coord_actor", None) or detect_actor()
        if (coord_project / ".coord" / "PLAN.md").is_file() and actor:
            record_pilot_in_stream(coord_project, summary, actor=actor, task=summary.get("task_id") or task_id)

    if routed is not None:
        summary["routed_by"] = routed
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    # ACCEPT_INFRA·ACCEPT_NOT_RUN으로 state가 SUCCEEDED여도 BLOCKED 판정이면 1 반환
    if summary.get("verdict_hint") == "BLOCKED":
        return 1
    return 0 if summary.get("state") == "SUCCEEDED" else 1


def cmd_pilot_manual_lint(args: argparse.Namespace) -> int:
    from .manual import lint

    source = Path(args.source) if args.source else manual_project(Path(args.manual))
    report = lint(Path(args.manual).read_text(encoding="utf-8"), source)
    print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    return 0 if report.ok else 1


def cmd_pilot_manual_new(args: argparse.Namespace) -> int:
    from .manual import lint, new_manual

    source = Path(args.source)
    instructions = Path(args.instructions_file).read_text(encoding="utf-8") if args.instructions_file else ""
    text = new_manual(
        source,
        work_id=args.work_id,
        worker=args.worker,
        goal=args.goal,
        inputs=args.input,
        allow=args.allow,
        acceptance=args.accept,
        judge=args.judge,
        timeout_s=args.timeout,
        remote_budget_tokens=args.remote_budget,
        remote_budget_usd=args.remote_budget_usd,
        instructions=instructions,
        context_allow=args.context_allow,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    report = lint(text, source)
    print(json.dumps({"written": str(out), **report.as_dict()}, indent=2, ensure_ascii=False))
    return 0 if report.ok else 1


def cmd_pilot_reconcile(args: argparse.Namespace) -> int:
    from .pilot import reconcile_pilot

    work_dir = Path(args.work_dir) if args.work_dir else Path(".coord")
    try:
        report = reconcile_pilot(work_dir=work_dir, task_id=args.task)
    except sqlite3.DatabaseError as exc:
        report = {
            "task_id": args.task,
            "state": "FAILED",
            "error_class": "DB_UNAVAILABLE",
            "message": f"Database corruption detected during reconcile: {exc}. Recovery hint: restore coord.sqlite3 from backup.",
        }
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="v7_harness", description="v7 Minimal Automation Harness")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # lease-check
    p_lease = subparsers.add_parser("lease-check")
    p_lease.add_argument("--file", required=True)
    p_lease.add_argument("--scope", default=None)
    p_lease.set_defaults(func=cmd_lease_check)

    # ledger-append
    p_lapp = subparsers.add_parser("ledger-append")
    p_lapp.add_argument("--ledger-file", required=True)
    p_lapp.add_argument("--task-id", required=True)
    p_lapp.add_argument("--actor", required=True)
    p_lapp.add_argument("--category", required=True)
    p_lapp.add_argument("--content", required=True)
    p_lapp.add_argument("--rationale", default=None)
    p_lapp.add_argument("--assumption", default=None)
    p_lapp.add_argument("--invalidation-condition", default=None)
    p_lapp.set_defaults(func=cmd_ledger_append)

    # ledger-verify
    p_lver = subparsers.add_parser("ledger-verify")
    p_lver.add_argument("--ledger-file", required=True)
    p_lver.set_defaults(func=cmd_ledger_verify)

    # receipt-run
    p_run = subparsers.add_parser("receipt-run")
    p_run.add_argument("--task-id", required=True)
    p_run.add_argument("--actor", required=True)
    p_run.add_argument("--store", default=None)
    p_run.add_argument("cmd", nargs=argparse.REMAINDER)
    p_run.set_defaults(func=cmd_receipt_run)

    # snapshot
    p_snap = subparsers.add_parser("snapshot")
    p_snap.add_argument("--target-path", default=None)
    p_snap.add_argument("--output", default=None)
    p_snap.add_argument("--force-non-git", action="store_true")
    p_snap.set_defaults(func=cmd_snapshot)

    # eval-next
    p_eval = subparsers.add_parser("eval-next")
    p_eval.add_argument("--current-task-id", required=True)
    p_eval.add_argument("--next-task", default="U08")
    p_eval.add_argument("--has-failures", action="store_true")
    p_eval.add_argument("--pending-actions", nargs="*", default=[])
    p_eval.set_defaults(func=cmd_eval_next)

    # benchmark
    p_bench = subparsers.add_parser("benchmark")
    p_bench.add_argument("--name", default="sample_bench")
    p_bench.set_defaults(func=cmd_benchmark)

    # report
    p_rep = subparsers.add_parser("report")
    p_rep.add_argument("--result", required=True)
    p_rep.add_argument("--changed", nargs="*", default=[])
    p_rep.add_argument("--verification", nargs="*", default=None, help="Explicit verification items or summary")
    p_rep.add_argument("--risks", default="None")
    p_rep.add_argument("--next-action", default="Proceed to review")
    p_rep.add_argument("--user-action-required", action="store_true")
    p_rep.set_defaults(func=cmd_report)

    # pilot run
    p_pilot = subparsers.add_parser("pilot")
    p_pilot_subs = p_pilot.add_subparsers(dest="pilot_subcommand", required=True)
    p_pilot_run = p_pilot_subs.add_parser("run")
    p_pilot_run.add_argument("--task", "--task-id", dest="task", required=True, help="Pilot task ID (e.g. P01)")
    p_pilot_run.add_argument("--source", "--source-dir", dest="source", required=True, help="Source directory path")
    p_pilot_run.add_argument("--prompt-file", default=None, help="Path to prompt file")
    p_pilot_run.add_argument("--prompt", default=None, help="Prompt text directly")
    p_pilot_run.add_argument("--title", default=None, help="Task title")
    p_pilot_run.add_argument("--work-dir", default=".coord", help="Work directory (default: .coord)")
    p_pilot_run.add_argument("--approve", default=None, help="Approve bundle ID for live promotion")
    p_pilot_run.add_argument("--watch-root", action="append", default=[], help="Watch roots for external write detection")
    p_pilot_run.add_argument("--print-timeout", type=int, default=600, help="Print timeout in seconds")
    p_pilot_run.add_argument("--agy-command", nargs="*", default=None, help="Custom worker command prefix (overrides --worker)")
    p_pilot_run.add_argument("--worker", choices=["agy", "local", "lane", "cascade", "auto", "apply", "claude"], default="agy", help="claude = Claude Code on the paid account (needs a manual with remote_budget_tokens; judge codex or user); agy = remote worker (uses account quota); local = this machine's Ollama model, one-shot; lane = Claude Code tool loop on the local model; apply = apply the ===FILE/===EDIT blocks written in the prompt, no model (0 tokens)")
    p_pilot_run.add_argument("--manual", default=None,
                             help="Work manual with a ```contract block: linted first, then its worker, acceptance, allow list and timeout drive the run")
    p_pilot_run.add_argument("--allow", action="append", default=[],
                             help="Path or glob the worker may change (repeatable); anything else is rejected as SCOPE_VIOLATION")
    # cascade 승격 대상 작업자(lane의 e2e 실패 빈발로 기본값은 agy)
    p_pilot_run.add_argument("--escalate-to", choices=["agy", "lane", "claude"], default="agy", help="Worker for cascade second stage when local gets REWORK (default: agy)")
    p_pilot_run.add_argument("--coord-log", dest="coord_log", action="store_true", default=True,
                             help="Record this run in the coordination stream (.coord/stream); on by default")
    p_pilot_run.add_argument("--no-coord-log", dest="coord_log", action="store_false",
                             help="Do not record this run in the coordination stream")
    p_pilot_run.add_argument("--coord-project", default=None,
                             help="Project whose coordination stream records this run (default: the --source project)")
    p_pilot_run.add_argument("--coord-actor", choices=["codex", "claude", "antigravity", "user"], default=None,
                             help="Who ran this pilot (default: detected from the calling tool's environment)")
    p_pilot_run.add_argument("--model", default=None, help="Model name to pass to agy (e.g. gemini-3.7-flash)")
    p_pilot_run.add_argument("--accept-cmd", default=None, help="Acceptance test command to run in staging")
    p_pilot_run.add_argument("--allow-no-changes", action="store_true", default=False, help="Allow PASS verdict even when no files were changed (for read-only tasks)")
    p_pilot_run.set_defaults(func=cmd_pilot_run)

    # pilot manual: U34 work-manual contracts
    p_pilot_manual = p_pilot_subs.add_parser("manual")
    p_manual_subs = p_pilot_manual.add_subparsers(dest="manual_subcommand", required=True)
    p_manual_lint = p_manual_subs.add_parser("lint")
    p_manual_lint.add_argument("--manual", required=True)
    p_manual_lint.add_argument("--source", default=None,
                               help="Project the manual's paths are relative to (default: the folder above the manual "
                                    "that holds .coord/PLAN.md, else the current folder)")
    p_manual_lint.set_defaults(func=cmd_pilot_manual_lint)
    p_manual_new = p_manual_subs.add_parser("new")
    p_manual_new.add_argument("--out", required=True, help="Manual file to write")
    p_manual_new.add_argument("--source", default=".")
    p_manual_new.add_argument("--work-id", required=True)
    p_manual_new.add_argument("--worker", required=True, choices=["local", "apply", "agy", "lane", "cascade", "claude"])
    p_manual_new.add_argument("--goal", required=True)
    p_manual_new.add_argument("--input", action="append", default=[], help="Input file to pin by SHA-256 (repeatable)")
    p_manual_new.add_argument("--allow", action="append", default=[], required=True)
    p_manual_new.add_argument("--context-allow", action="append", default=None,
                              help="U50: extra file or pattern the worker may see (repeatable); omit to keep all")
    p_manual_new.add_argument("--accept", required=True, help="Acceptance command")
    p_manual_new.add_argument("--judge", required=True, choices=["codex", "claude", "antigravity", "user"])
    p_manual_new.add_argument("--timeout", type=int, default=180)
    p_manual_new.add_argument("--remote-budget", type=int, default=0)
    p_manual_new.add_argument("--remote-budget-usd", type=float, default=0.0,
                              help="Dollar cap for worker claude (claude --max-budget-usd); lint requires it > 0")
    p_manual_new.add_argument("--instructions-file", default=None, help="Prose instructions to append")
    p_manual_new.set_defaults(func=cmd_pilot_manual_new)

    # pilot reconcile
    p_pilot_review = p_pilot_subs.add_parser("review", help="U38: read-only advisory review of a bundle by Claude Code")
    p_pilot_review.add_argument("--task", required=True)
    p_pilot_review.add_argument("--work-dir", required=True)
    p_pilot_review.add_argument("--source", default=".")
    p_pilot_review.add_argument("--manual", required=True, help="The contract manual the bundle was built from")
    p_pilot_review.add_argument("--reviewer", default="claude", choices=["claude", "agy"],
                                help="agy = Antigravity CLI, read-only, token budget only (U46-J1, docs/47)")
    # U47-C2 (2026-09-28): still required, but the help names the decided value; a measured claude review took
    # 94,953 counted tokens (cache reads included) and $0.176, so 80,000 failed as UNUSABLE (docs/47 §1-1 C2).
    p_pilot_review.add_argument("--budget", type=int, required=True,
                                help="Token budget for the review call, cache reads included; "
                                     "claude review: 120000 (U47-C2)")
    # Not required by argparse any more: run_review refuses a claude review without it (agy has no dollar option).
    p_pilot_review.add_argument("--budget-usd", type=float, default=0.0,
                                help="Dollar cap passed to claude --max-budget-usd (checked before spending); "
                                     "required for --reviewer claude; claude review: 0.25 (U47-C2)")
    p_pilot_review.add_argument("--model", default=None)
    p_pilot_review.add_argument("--timeout", type=int, default=600)
    p_pilot_review.set_defaults(func=cmd_pilot_review)

    # U46-J4: binding judgement by the contract's judge tool through its CLI, only while Codex is LIMITED/ABSENT.
    p_pilot_judge = p_pilot_subs.add_parser("judge", help="U46-J4: Antigravity judges a bundle via its CLI while Codex is away")
    p_pilot_judge.add_argument("--task", required=True)
    p_pilot_judge.add_argument("--work-dir", required=True)
    p_pilot_judge.add_argument("--source", default=".")
    p_pilot_judge.add_argument("--manual", required=True, help="The contract manual the bundle was built from")
    p_pilot_judge.add_argument("--project", default=None, help="Project whose presence desk says Codex is away")
    p_pilot_judge.add_argument("--judge", default="agy", choices=["agy", "codex"])
    p_pilot_judge.add_argument("--budget", type=int, default=None,
                               help="Token cap; default scales with the diff: clamp(30,000 + 3 x diff chars, "
                                    "100,000, 250,000) (U47-J5: R1c's 34 KB bundle cost 114,644)")
    p_pilot_judge.add_argument("--timeout", type=int, default=600)
    p_pilot_judge.add_argument("--no-apply", action="store_true", help="Record the verdict without running --approve")
    p_pilot_judge.set_defaults(func=cmd_pilot_judge)

    p_pilot_rec = p_pilot_subs.add_parser("reconcile")
    p_pilot_rec.add_argument("--task", "--task-id", dest="task", required=True, help="Pilot task ID to reconcile")
    p_pilot_rec.add_argument("--work-dir", default=".coord", help="Work directory (default: .coord)")
    p_pilot_rec.set_defaults(func=cmd_pilot_reconcile)

    # coord: U15 조율 스트림
    p_coord = subparsers.add_parser("coord")
    p_coord_subs = p_coord.add_subparsers(dest="coord_subcommand", required=True)

    p_coord_log = p_coord_subs.add_parser("log")
    p_coord_log.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_log.add_argument("--actor", required=True, choices=["codex", "antigravity", "claude"])
    p_coord_log.add_argument("--kind", required=True, choices=["PLAN", "RUN", "VERDICT", "BLOCKED", "HANDOFF", "NOTE"])
    p_coord_log.add_argument("--step", required=True, help="Step or task id (e.g. U15-S4)")
    p_coord_log.add_argument("--summary", required=True, help="One line, 200 chars max")
    p_coord_log.add_argument("--ref", action="append", default=[], help="Evidence path (repeatable)")
    p_coord_log.add_argument("--cmd", default=None, help="Command that produced the evidence")
    p_coord_log.add_argument("--exit-code", dest="exit_code", type=int, default=None, help="Exit code of that command")
    p_coord_log.add_argument("--bundle", default=None, help="Bundle id when a promotion is involved")
    p_coord_log.set_defaults(func=cmd_coord_log)

    p_coord_status = p_coord_subs.add_parser("status")
    p_coord_status.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_status.set_defaults(func=cmd_coord_status)

    p_coord_brief = p_coord_subs.add_parser("brief")
    p_coord_brief.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_brief.add_argument("--owner", default=None, help="Current step owner")
    p_coord_brief.add_argument("--lock", default=None, help="Active lock, if any")
    p_coord_brief.add_argument("--pending", action="append", default=[], help="Item waiting for a Codex verdict (repeatable)")
    p_coord_brief.add_argument("--next", action="append", default=[], help="Next candidate (repeatable)")
    p_coord_brief.add_argument("--write", action="store_true", default=False, help="Write .coord/codex_brief.md instead of printing")
    p_coord_brief.set_defaults(func=cmd_coord_brief)

    p_coord_notify = p_coord_subs.add_parser("notify")
    p_coord_notify.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_notify.add_argument("--actor", required=True, choices=["codex", "antigravity", "claude"])
    p_coord_notify.add_argument("--headline", required=True, help="One line for the Codex window")
    p_coord_notify.add_argument("--thread", default=None, help="Codex session id (default: newest session for this project)")
    p_coord_notify.add_argument("--pending", action="append", default=[], help="Verdict-waiting item (default: read from PLAN)")
    p_coord_notify.add_argument(
        "--verdict-requested",
        choices=["yes", "no", "auto"],
        default="auto",
        help="Override verdict_requested (yes/no/auto; auto sets no if codex is absent)",
    )
    p_coord_notify.add_argument("--send", action="store_true", default=False, help="Actually queue it (default: dry run)")
    p_coord_notify.set_defaults(func=cmd_coord_notify)

    p_coord_archive = p_coord_subs.add_parser("archive")
    p_coord_archive.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_archive.set_defaults(func=cmd_coord_archive)

    p_coord_deliver = p_coord_subs.add_parser("deliver", help="Durable direct tool delivery")
    p_coord_deliver.add_argument("--project", default=".")
    p_coord_deliver.add_argument("--actor", required=True, choices=["codex", "claude", "antigravity"])
    p_coord_deliver.add_argument("--target", default=None, choices=["codex", "claude"])
    p_coord_deliver.add_argument("--message", required=True)
    p_coord_deliver.add_argument("--thread", default="")
    p_coord_deliver.set_defaults(func=cmd_coord_deliver)

    p_coord_sentinel = p_coord_subs.add_parser("sentinel")
    p_coord_sentinel.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_sentinel.add_argument("--once", action="store_true", default=False, help="Run single cycle and exit")
    p_coord_sentinel.add_argument("--loop", action="store_true", default=False, help="Run continuous monitoring loop")
    p_coord_sentinel.add_argument("--interval", type=int, default=30, help="Loop interval in seconds (default: 30)")
    p_coord_sentinel.add_argument("--write-brief", action="store_true", default=False, help="Write .coord/codex_brief.md")
    p_coord_sentinel.add_argument("--recipient", default="codex", help="P1 alert recipient (default: codex)")
    p_coord_sentinel.add_argument("--log", default=None,
                                  help="Append each cycle's JSON line to this file (a resident loop has no console)")
    p_coord_sentinel.add_argument("--ring", action="store_true", default=False,
                                  help="Ring Codex (codex queue) for waiting P1 wakes while Codex has a fresh ACTIVE heartbeat")
    p_coord_sentinel.set_defaults(func=cmd_coord_sentinel)

    p_coord_presence = p_coord_subs.add_parser("presence")
    p_coord_presence.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_presence.add_argument("--tool", choices=["codex", "claude", "antigravity"], default=None)
    p_coord_presence.add_argument("--state", choices=["ACTIVE", "LIMITED", "ABSENT"], default=None)
    p_coord_presence.add_argument("--ttl", type=int, default=3600, help="Seconds until the heartbeat reads UNKNOWN")
    p_coord_presence.add_argument("--if-uaos", action="store_true", default=False,
                                  help="Do nothing unless the project has .coord/PLAN.md (for global session hooks)")
    p_coord_presence.add_argument("--from-hook", action="store_true", default=False,
                                  help="Find the project from the hook payload on stdin (cwd, workspacePaths), "
                                       "CLAUDE_PROJECT_DIR or --project, walking up to .coord/PLAN.md; never fails the hook")
    p_coord_presence.add_argument("--say", choices=["json", "brief", "none", "empty-json", "p1"], default="json",
                                  help="What to print: presence JSON (default), one context line, nothing, {}, or "
                                       "p1 = one line only when a P1 wake waits and Codex is not ACTIVE (U38)")
    # U57-D: the acting conductor had to write a Codex quota lease through Python (2026-09-27); the lease itself
    # (U47-A1b) already existed in presence.mark, only the flag was missing.
    p_coord_presence.add_argument("--lease", action="store_true", default=False,
                                  help="Record a capability lease that ordinary heartbeats cannot overwrite until --ttl")
    p_coord_presence.set_defaults(func=cmd_coord_presence)

    p_coord_watch = p_coord_subs.add_parser("watch", help="Block until a new mailbox letter for a target arrives")
    p_coord_watch.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_watch.add_argument("--target", action="append", required=True, choices=["codex", "claude", "antigravity"])
    p_coord_watch.add_argument("--timeout", type=float, default=4 * 3600.0, help="Seconds before exit 3 (default: 4 h)")
    p_coord_watch.add_argument("--interval", type=float, default=30.0, help="Seconds between inbox scans (default: 30)")
    p_coord_watch.set_defaults(func=cmd_coord_watch)

    p_coord_route = p_coord_subs.add_parser("route", help="Choose the sole authority from fresh presence states")
    p_coord_route.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_route.set_defaults(func=cmd_coord_route)
    p_coord_collect = p_coord_subs.add_parser(
        "usage-collect", help="Find usage rows left only in linked worktrees; --apply appends them to the desk ledger")
    p_coord_collect.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_collect.add_argument("--apply", action="store_true", help="Append the orphan rows (default: dry run)")
    p_coord_collect.set_defaults(func=cmd_coord_usage_collect)

    p_coord_thrift = p_coord_subs.add_parser("thrift", help="Prepare a deterministic local budget handoff packet")
    p_coord_thrift.add_argument("--project", default=".")
    p_coord_thrift.add_argument("--tool", required=True, choices=["codex", "claude", "antigravity"])
    p_coord_thrift.add_argument("--remaining-percent", required=True, type=float)
    p_coord_thrift.add_argument("--reset-at", default=None)
    p_coord_thrift.add_argument("--thrift-at", type=float, default=20)
    p_coord_thrift.add_argument("--handoff-at", type=float, default=7)
    p_coord_thrift.add_argument("--current-card", default="")
    p_coord_thrift.add_argument("--next-action", default="")
    p_coord_thrift.add_argument("--acceptance", default="")
    p_coord_thrift.add_argument("--stop-condition", default="")
    p_coord_thrift.set_defaults(func=cmd_coord_thrift)

    p_coord_init = p_coord_subs.add_parser("init")
    p_coord_init.add_argument("--project", default=".", help="Project to prepare for UAOS (default: .)")
    p_coord_init.set_defaults(func=cmd_coord_init)

    p_coord_inbox = p_coord_subs.add_parser("inbox")
    p_coord_inbox.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_inbox.set_defaults(func=cmd_coord_inbox)

    p_coord_ack = p_coord_subs.add_parser("ack")
    p_coord_ack.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_ack.add_argument("--id", dest="message_id", required=True, help="Mailbox message id to mark handled")
    p_coord_ack.add_argument("--consumer", default="commander", help="Who handled it (default: commander)")
    p_coord_ack.set_defaults(func=cmd_coord_ack)

    p_coord_pub = p_coord_subs.add_parser("publish-thread")
    p_coord_pub.add_argument("--actor", required=True, choices=["agy", "claude", "antigravity"])
    p_coord_pub.add_argument("--task", required=True, help="Task name (e.g. 'MIA 전략 레드팀')")
    p_coord_pub.add_argument("--prompt", default="", help="User prompt text (optional if --transcript is given)")
    p_coord_pub.add_argument("--response", default=None, help="Assistant response text")
    p_coord_pub.add_argument("--response-file", default=None, help="File containing assistant response text")
    p_coord_pub.add_argument("--transcript", default=None, help="Path to transcript.jsonl for full session import")
    p_coord_pub.add_argument("--thread-id", default=None, help="Optional thread UUID")
    p_coord_pub.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_pub.set_defaults(func=cmd_coord_publish_thread)

    # rsi: evidence-gated self-improvement (docs/38). observe → propose → try → gate → judge → rollback.
    p_rsi = subparsers.add_parser("rsi", help="Evidence-gated self-improvement: report, propose, gate, adopt, rollback")
    p_rsi_subs = p_rsi.add_subparsers(dest="rsi_subcommand", required=True)
    p_rsi_report = p_rsi_subs.add_parser("report", help="Per-worker pass/rework/blocked rates and recurring causes")
    p_rsi_report.add_argument("--project", default=".")
    p_rsi_report.set_defaults(func=cmd_rsi_report)
    p_rsi_propose = p_rsi_subs.add_parser("propose", help="Deterministic remedies for the causes in the ledger")
    p_rsi_propose.add_argument("--project", default=".")
    p_rsi_propose.add_argument("--candidate-for", default=None, metavar="PROPOSAL_ID",
                               help="Print a candidate file to fill after the trial runs")
    p_rsi_propose.add_argument("--author", default=None, help="Author of the candidate (default: detected tool)")
    p_rsi_propose.set_defaults(func=cmd_rsi_propose)
    p_rsi_gate = p_rsi_subs.add_parser("gate", help="Judge a tried candidate on ledger evidence (read only)")
    p_rsi_gate.add_argument("--project", default=".")
    p_rsi_gate.add_argument("--candidate", required=True, help="Candidate JSON file")
    p_rsi_gate.set_defaults(func=cmd_rsi_gate)
    p_rsi_adopt = p_rsi_subs.add_parser("adopt", help="Refused by design (B83): prints the gate evidence and the proposed file for a PLAN card")
    p_rsi_adopt.add_argument("--project", default=".")
    p_rsi_adopt.add_argument("--candidate", required=True)
    p_rsi_adopt.add_argument("--judge", required=True, choices=["codex", "claude", "user"],
                             help="Codex, Claude while Codex is absent, or the user (docs/31 §3)")
    p_rsi_adopt.set_defaults(func=cmd_rsi_adopt)
    p_rsi_rollback = p_rsi_subs.add_parser("rollback", help="Refused by design (B83): prints the previous policy as a proposed file")
    p_rsi_rollback.add_argument("--project", default=".")
    p_rsi_rollback.add_argument("--judge", required=True, choices=["codex", "claude", "user"])
    p_rsi_rollback.add_argument("--reason", required=True)
    p_rsi_rollback.set_defaults(func=cmd_rsi_rollback)

    p_rsi_watch = p_rsi_subs.add_parser("watch", help="Deterministic change detection cycle (U42)")
    p_rsi_watch.add_argument("--project", default=".")
    p_rsi_watch.add_argument("--config", default=None, help="Watcher config JSON path")
    p_rsi_watch.set_defaults(func=cmd_rsi_watch)

    p_rsi_prepare = p_rsi_subs.add_parser("prepare", help="Prepare a release packet (dry-run by default, --apply to write)")
    p_rsi_prepare.add_argument("--project", default=".")
    p_rsi_prepare.add_argument("--packet", required=True, help="Release packet JSON file")
    p_rsi_prepare.add_argument("--apply", action="store_true", help="Write version and update documents")
    p_rsi_prepare.add_argument("--date", default="2026-09-25", help="Release date string")
    p_rsi_prepare.set_defaults(func=cmd_rsi_prepare)

    p_rsi_ship = p_rsi_subs.add_parser("ship", help="Ship an approved release (dry-run by default, --execute to push & pr)")
    p_rsi_ship.add_argument("--project", default=".")
    p_rsi_ship.add_argument("--packet", required=True, help="Release packet JSON file")
    p_rsi_ship.add_argument("--approval", required=True, help="Approval receipt JSON file")
    p_rsi_ship.add_argument("--execute", action="store_true", help="Execute git commit, push, and gh pr create")
    p_rsi_ship.set_defaults(func=cmd_rsi_ship)

    p_rsi_schedule = p_rsi_subs.add_parser("schedule", help="Manage Windows Task Scheduler for RSI watch")
    p_rsi_schedule.add_argument("--project", default=".")
    p_rsi_schedule.add_argument("--action", choices=["install", "status", "remove", "manual-now"], default="status")
    p_rsi_schedule.add_argument("--apply", action="store_true", help="Apply schtasks command / run manual-now")
    p_rsi_schedule.add_argument("--python-bin", default=None, help="Python executable path")
    p_rsi_schedule.set_defaults(func=cmd_rsi_schedule)

    p_rsi_retention = p_rsi_subs.add_parser("retention", help="Deletion-free retention plan (dry-run manifest, U42-R1)")
    p_rsi_retention.add_argument("--project", default=".")
    p_rsi_retention.add_argument("--archive", action="store_true", help="Archive candidate files into a verified zip")
    p_rsi_retention.add_argument("--rollup-olla", action="store_true", help="Roll up olla usage ledger")
    p_rsi_retention.add_argument("--purge", default=None, metavar="ZIP",
                                 help="Validate an archive then return the fail-closed deletion boundary")
    p_rsi_retention.add_argument("--approval", default=None, metavar="FILE",
                                 help="Compatibility only; file labels are never treated as authentication")
    p_rsi_retention.set_defaults(func=cmd_rsi_retention)

    return parser


def detect_actor() -> Optional[str]:
    """Which of the three tools is running this command, from its shell environment. None for a plain terminal."""
    from .olla import _caller

    caller = _caller()
    return caller if caller in ("codex", "claude", "antigravity") else None


def record_pilot_in_stream(project: Path, summary: dict, *, actor: str = "claude", task: Optional[str] = None) -> Optional[str]:
    """파일럿 결과를 조율 스트림에 한 줄로 남긴다.

    사람이 기억해서 적으면 빠뜨린다. 실행이 끝나는 자리에서 바로 남겨야 지휘자가
    무엇을 판정해야 하는지 알 수 있다. 기록이 실패해도 파일럿 결과 보고는 막지 않는다.
    """
    from .coord.stream import StreamRejected, append_event

    verdict = str(summary.get("verdict_hint") or "UNKNOWN")
    state = str(summary.get("state") or "UNKNOWN")
    # run_pilot's summary has no task_id on a normal run, so every event used to read "pilot".
    task = str(task or summary.get("task_id") or "pilot")
    changed = summary.get("changed_files") or []
    bundle = summary.get("bundle_id") or ""
    promotion = summary.get("promotion") or ""
    kind = "RUN" if state == "SUCCEEDED" else "BLOCKED"
    detail = f"{state}/{verdict}"
    if promotion:
        detail += f"/{promotion}"
    summary_line = f"파일럿 {task}: {detail}, 변경 {len(changed)}개"
    if summary.get("error_class") not in (None, "", "NONE"):
        summary_line += f", {summary['error_class']}"

    evidence = {"cmd": f"pilot run --task {task}", "exit": 0 if state == "SUCCEEDED" else 1}
    if bundle:
        evidence["bundle"] = bundle
    refs = []
    if summary.get("summary_path"):
        # The stream refuses absolute refs, which silently dropped the whole event when --work-dir was absolute.
        ref = Path(str(summary["summary_path"]).replace("\\", "/"))
        if ref.is_absolute():
            try:
                ref = ref.resolve().relative_to(Path(project).resolve())
            except ValueError:
                ref = None
        if ref is not None:
            refs = [ref.as_posix()]
    try:
        event = append_event(
            project,
            actor=actor,
            kind=kind,
            step=task,
            summary=summary_line[:200],
            refs=refs,
            evidence=evidence,
        )
        return event.id
    except (StreamRejected, OSError, RuntimeError):
        # 기록 실패가 실행 보고를 덮지 않게 한다. 다음 브리핑에서 빈자리로 드러난다.
        return None


def cmd_pilot_review(args: argparse.Namespace) -> int:
    from .review import ReviewRefused, run_review

    try:
        manual_text = Path(args.manual).read_text(encoding="utf-8")
        record = run_review(task_id=args.task, work_dir=Path(args.work_dir), source=Path(args.source),
                            manual_text=manual_text, reviewer=args.reviewer, budget=args.budget,
                            budget_usd=args.budget_usd, model=args.model,
                            timeout_s=args.timeout)
    except (ReviewRefused, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)[:400]}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, **record}, ensure_ascii=False, indent=2))
    return 0


def cmd_pilot_judge(args: argparse.Namespace) -> int:
    from .judge import JudgeRefused, run_judge

    try:
        record = run_judge(task_id=args.task, work_dir=Path(args.work_dir), source=Path(args.source),
                           manual_path=Path(args.manual), project=Path(args.project) if args.project else None,
                           judge=args.judge, budget=args.budget, timeout_s=args.timeout, apply=not args.no_apply)
    except (JudgeRefused, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)[:400]}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, **record}, ensure_ascii=False, indent=2))
    return 0 if record["verdict"] in ("APPROVE", "REJECT") else 3


def resolve_worker_command(worker: str, explicit: Optional[Sequence[str]]) -> list[str]:
    """어느 작업자에게 맡길지 정한다.

    `agy`는 계정 할당량을 쓰는 원격 작업자, `local`은 이 PC의 Ollama 모델이다.
    할당량이 소진돼도 진행이 멈추지 않도록 두 번째 손을 둔다. 판정은 어느 쪽이든
    파일럿의 인수 검사와 게이트가 하므로, 작업자가 약해도 거짓 성공은 통과하지 못한다.
    """
    if explicit:
        return list(explicit)
    if worker in ("local", "cascade"):  # cascade starts on local; cmd_pilot_run switches to lane on REWORK
        return [sys.executable, str(Path(__file__).resolve().parent / "adapters" / "ollama_worker.py")]
    if worker == "lane":  # Claude Code's tool loop on the local model; kept beside "local" for the A/B
        return [sys.executable, str(Path(__file__).resolve().parent / "adapters" / "lane_worker.py")]
    if worker == "apply":  # U34: the commander already wrote the code; apply it without a model
        return [sys.executable, str(Path(__file__).resolve().parent / "adapters" / "apply_worker.py")]
    if worker == "claude":  # U38: Claude Code on the paid account, budget-gated (docs/40)
        return [sys.executable, str(Path(__file__).resolve().parent / "adapters" / "claude_worker.py")]
    return ["agy"]


def cmd_coord_log(args: argparse.Namespace) -> int:
    """U15: 조율 사건 한 줄을 스트림에 남긴다. 세 도구가 같은 입구를 쓴다."""
    from .coord.stream import StreamRejected, append_event

    evidence: dict[str, object] = {}
    if args.cmd:
        evidence["cmd"] = args.cmd
    if args.exit_code is not None:
        evidence["exit"] = args.exit_code
    if args.bundle:
        evidence["bundle"] = args.bundle
    try:
        event = append_event(
            Path(args.project),
            actor=args.actor,
            kind=args.kind,
            step=args.step,
            summary=args.summary,
            refs=args.ref,
            evidence=evidence or None,
        )
    except StreamRejected as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "id": event.id, "ts": event.ts}, ensure_ascii=False))
    return 0


def cmd_coord_status(args: argparse.Namespace) -> int:
    """Report coordinator and harness health status."""
    project = Path(args.project)
    lock_file = project / ".work" / "QUIET_LOCK"
    lock_status = "LOCKED" if lock_file.is_file() else "CLEAN"

    mailbox_dir = project / ".coord" / "mailbox" / "inbox"
    mailbox_count = len(list(mailbox_dir.glob("*.json"))) if mailbox_dir.is_dir() else 0

    from .coord.stream import StreamRejected, read_events

    try:
        stream_count = len(read_events(project))
    except StreamRejected as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    usage_file = project / ".coord" / "usage" / "runs.jsonl"
    usage_count = len(usage_file.read_text(encoding="utf-8").splitlines()) if usage_file.is_file() else 0

    out = {
        "ok": True,
        "lock": lock_status,
        "mailbox_pending": mailbox_count,
        "stream_events": stream_count,
        "ledger_entries": usage_count,
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


def cmd_coord_brief(args: argparse.Namespace) -> int:
    """U15: 스트림을 접어 Codex 브리핑을 만든다. 같은 입력이면 같은 결과다."""
    from .coord.brief import brief_hash, pending_from_plan, render_brief, write_brief

    project = Path(args.project)
    # 판정 대기를 손으로 넘기지 않으면 PLAN 상태 칸에서 읽는다. 사람이 넘기면 빠뜨린다.
    pending = list(args.pending) or pending_from_plan(project)
    text = render_brief(
        project,
        owner=args.owner,
        lock=args.lock,
        pending=pending,
        next_candidates=args.next,
    )
    if args.write:
        path = write_brief(project, text)
        print(json.dumps({"ok": True, "path": str(path), "hash": brief_hash(text)[:12], "lines": len(text.splitlines())}, ensure_ascii=False))
    else:
        print(text, end="")
    return 0


def cmd_coord_notify(args: argparse.Namespace) -> int:
    """U15: 브리핑이 바뀌었을 때만 Codex 대화창으로 한 건 보낸다. 기본은 드라이런이다."""
    from .coord.brief import pending_from_plan
    from .coord.notify import NotifyRefused, notify, resolve_thread

    project = Path(args.project)
    brief_file = project / ".coord" / "codex_brief.md"
    if not brief_file.is_file():
        print(json.dumps({"ok": False, "error": "BRIEF_MISSING"}, ensure_ascii=False))
        return 1

    thread = args.thread or resolve_thread(project)
    if not thread:
        # 스레드를 못 고르면 보내지 않는다. 엉뚱한 작업 창에 배달하는 것보다 안 보내는 편이 낫다.
        print(json.dumps({"ok": False, "error": "THREAD_UNRESOLVED"}, ensure_ascii=False))
        return 1

    vr_arg = getattr(args, "verdict_requested", "auto")
    vr_val = True if vr_arg == "yes" else (False if vr_arg == "no" else None)

    try:
        result = notify(
            project,
            thread=thread,
            actor=args.actor,
            brief_text=brief_file.read_text(encoding="utf-8"),
            headline=args.headline,
            pending=list(args.pending) or pending_from_plan(project),
            verdict_requested=vr_val,
            dry_run=not args.send,
        )
    except NotifyRefused as exc:
        print(json.dumps({"ok": False, "error": str(exc), "thread": thread}, ensure_ascii=False))
        return 1

    print(json.dumps({"ok": True, "sent": result.sent, "reason": result.reason, "thread": thread, "message": result.message}, ensure_ascii=False))
    return 0


def cmd_coord_archive(args: argparse.Namespace) -> int:
    """U15: 판정이 끝난 사건을 보관함으로 옮겨 현역 스트림을 짧게 유지한다."""
    from .coord.stream import archive_settled

    report = archive_settled(Path(args.project))
    print(json.dumps({"ok": True, **report}, ensure_ascii=False))
    return 0


def cmd_coord_deliver(args: argparse.Namespace) -> int:
    from .coord.deliver import deliver

    result = deliver(Path(args.project), message=args.message, actor=args.actor,
                     target=args.target, thread=args.thread)
    # U57-C: QUEUED_INTERACTIVE means a live `coord watch` holds the letter for the interactive session; not a failure.
    ok = result.reason in ("PUBLISHED", "DISPATCHED", "ACKED", "QUEUED_INTERACTIVE")
    print(json.dumps({"ok": ok, "target": result.target, "reason": result.reason,
                      "message_id": result.message_id, "digest": result.digest,
                      "receipt": result.receipt, "output": result.output[:500]}, ensure_ascii=False))
    return 0 if ok else 1


def cmd_coord_publish_thread(args: argparse.Namespace) -> int:
    """U24 / docs/24: 도구의 프로세스 대화를 Codex 데스크톱 프로젝트 대화로 편입·발행한다."""
    from .coord.codex_session_bridge import parse_transcript_to_turns, publish_codex_thread

    if args.transcript:
        turns = parse_transcript_to_turns(Path(args.transcript))
        if not turns:
            print(json.dumps({"ok": False, "error": "EMPTY_OR_INVALID_TRANSCRIPT"}, ensure_ascii=False))
            return 1
    else:
        resp_text = args.response or ""
        if args.response_file:
            resp_text = Path(args.response_file).read_text(encoding="utf-8")
        if not resp_text:
            print(json.dumps({"ok": False, "error": "MISSING_RESPONSE"}, ensure_ascii=False))
            return 1
        turns = [(args.prompt, resp_text)]

    result = publish_codex_thread(
        actor=args.actor,
        task_name=args.task,
        turns=turns,
        project_dir=Path(args.project),
        thread_id=args.thread_id,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


def cmd_coord_sentinel(args: argparse.Namespace) -> int:
    """U23 S4 / U32b: 0-token sentinel (deterministic rules, no model call) — one cycle or a resident loop."""
    import time
    from .coord.mailbox import Mailbox
    from .coord.sentinel import generate_briefing, run_sentinel_cycle

    project = Path(args.project)
    mailbox_dir = project / ".coord" / "mailbox"
    mailbox_dir.mkdir(parents=True, exist_ok=True)
    box = Mailbox(mailbox_dir)

    def _execute_once() -> dict[str, Any]:
        cycle_res = run_sentinel_cycle(project, box, recipient=args.recipient, ring=getattr(args, "ring", False))
        if args.write_brief:
            brief_text = generate_briefing(project, box=box)
            brief_file = project / ".coord" / "codex_brief.md"
            brief_file.parent.mkdir(parents=True, exist_ok=True)
            brief_file.write_text(brief_text, encoding="utf-8")
        return cycle_res

    log_path = Path(args.log) if getattr(args, "log", None) else None

    def _report(res: dict[str, Any]) -> None:
        line = json.dumps(res, ensure_ascii=False)
        print(line, flush=True)  # a no-op under pythonw, where stdout is None
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            # One line a minute is ~0.4 MB a day; keep one previous file instead of growing forever.
            if log_path.is_file() and log_path.stat().st_size > SENTINEL_LOG_MAX_BYTES:
                os.replace(log_path, log_path.with_name(log_path.name + ".1"))
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    if args.loop:
        # A logon task and a manual start must not run two operators on one project.
        from .coord.sentinel import _is_pid_alive

        pid_file = project / ".work" / "sentinel" / "loop.pid"
        try:
            running = int(pid_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            running = 0
        if running and running != os.getpid() and _is_pid_alive(running):
            _report({"ok": True, "skipped": "ALREADY_RUNNING", "pid": running})
            return 0
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(os.getpid()), encoding="utf-8")
        while True:
            # A resident operator must outlive one bad cycle (locked file, corrupt line); it reports and goes on.
            try:
                res = _execute_once()
            except Exception as exc:  # noqa: BLE001
                res = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
            _report(res)
            time.sleep(args.interval)
        return 0

    _report(_execute_once())
    return 0


def cmd_coord_presence(args: argparse.Namespace) -> int:
    """U32b: record one tool's heartbeat, or show all three. Called from each tool's session hooks."""
    from .coord.presence import conductor, mark, read_all

    say = getattr(args, "say", "json")

    def _emit(data: dict[str, Any], line: str = "") -> None:
        if say == "json":
            print(json.dumps(data, ensure_ascii=False))
        elif say in ("brief", "p1") and line:
            print(line)
        elif say == "empty-json":
            print("{}")

    if getattr(args, "from_hook", False):
        from .coord.hook_context import (
            brief_line,
            hook_project,
            hook_session,
            p1_is_new,
            p1_line,
            read_stdin,
            retention_alert,
            retention_alert_is_new,
        )

        # A pilot worker (U38) runs inside a staged copy that holds .coord/PLAN.md; a hook there must write nothing.
        if os.environ.get("UAOS_WORKER"):
            _emit({"ok": True, "skipped": "UAOS_WORKER"})
            return 0
        # A session hook must never break the session: every failure is reported and the exit code stays 0.
        try:
            stdin_text = read_stdin()
            project = hook_project(stdin_text, args.project)
            if project is None:
                _emit({"ok": True, "skipped": "NOT_A_UAOS_PROJECT"})
                return 0
            if args.tool and args.state:
                # U58: the hook payload names its session, so one session ending leaves the others at the desk.
                mark(project, args.tool, args.state, ttl_s=args.ttl, session=hook_session(stdin_text))
            presence = read_all(project)
            line = p1_line(project, presence) if say == "p1" else brief_line(project, presence)
            if say == "brief":
                alert = retention_alert(project)
                if retention_alert_is_new(project, alert):
                    line = line + " " + alert
            elif say == "p1" and not p1_is_new(project, line):
                line = ""  # U46-P1: an unchanged P1 set is ACK_ONLY; it was repeated on every prompt
            _emit({"ok": True, "project": str(project), "presence": presence, "conductor": conductor(presence)}, line)
        except Exception as exc:  # noqa: BLE001
            _emit({"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]})
        return 0

    project = Path(args.project)
    if getattr(args, "if_uaos", False) and not (project / ".coord" / "PLAN.md").is_file():
        # Global hooks fire in every project; only UAOS projects get a presence file.
        _emit({"ok": True, "skipped": "NOT_A_UAOS_PROJECT"})
        return 0
    if args.tool or args.state:
        if not (args.tool and args.state):
            print(json.dumps({"ok": False, "error": "--tool and --state go together"}, ensure_ascii=False))
            return 2
        mark(project, args.tool, args.state, ttl_s=args.ttl, lease=getattr(args, "lease", False))
    presence = read_all(project)
    _emit({"ok": True, "presence": presence, "conductor": conductor(presence)})
    return 0


def cmd_coord_watch(args: argparse.Namespace) -> int:
    """U57-B: wait at zero model tokens until a new letter for one of the targets lands; exit 3 on timeout."""
    from .coord.watch import watch

    found = watch(Path(args.project), tuple(args.target), timeout_s=args.timeout, interval_s=args.interval)
    if found is None:
        print(json.dumps({"ok": False, "reason": "TIMEOUT", "targets": args.target}, ensure_ascii=False))
        return 3
    print(json.dumps({"ok": True, "reason": "NEW_LETTER", **found}, ensure_ascii=False))
    return 0


def cmd_coord_usage_collect(args: argparse.Namespace) -> int:
    """U72-L: recover ledger rows written into worktree copies before the desk routing existed. Append-only."""
    from .coord.usage_ledger import UsageRejected, collect

    try:
        result = collect(Path(args.project), apply=args.apply)
    except UsageRejected as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


def cmd_coord_route(args: argparse.Namespace) -> int:
    """Choose authority from provider states; percentages and reset windows are never token balances."""
    from .budget_route import route_authority
    from .coord.presence import read_all

    presence = read_all(Path(args.project))
    states = {tool: (presence.get(tool) or {}).get("state", "UNKNOWN")
              for tool in ("codex", "claude", "antigravity")}
    authority = route_authority(states["codex"], states["claude"], states["antigravity"])
    print(json.dumps({"ok": not authority.startswith("BLOCKED_"), "authority": authority,
                      "states": states, "quota_conversion": "FORBIDDEN"}, ensure_ascii=False))
    return 0 if not authority.startswith("BLOCKED_") else 1


def cmd_coord_thrift(args: argparse.Namespace) -> int:
    from .coord.thrift import ThriftRejected, apply
    try:
        result = apply(Path(args.project), tool=args.tool, remaining_percent=args.remaining_percent,
                       current_card=args.current_card, next_action=args.next_action, acceptance=args.acceptance,
                       stop_condition=args.stop_condition, reset_at=args.reset_at,
                       thrift_at=args.thrift_at, handoff_at=args.handoff_at)
    except ThriftRejected as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


SENTINEL_LOG_MAX_BYTES = 5 * 1024 * 1024

UAOS_GITIGNORE_LINES = (
    ".work/",
    ".coord/pilot/",
    ".coord/stream/",
    ".coord/codex_brief.md",
    ".coord/mailbox/",
    ".coord/presence/",
    ".coord/usage/runs.jsonl",
)

PLAN_TEMPLATE = """# 통합 실행 계획 (UAOS)

상태 기준: `READY → ACTIVE → REVIEW → DONE`. 한 번에 활성 단계 하나, 단계마다 소유자 한 명.

| ID | 상태 | 소유자 | 산출물/판정 |
|---|---|---|---|
| S01 | READY | (지휘자) | 첫 단계: 인수 명령을 먼저 정한다 |

도구 상태(시각이 지나면 UNKNOWN): `python -m v7_harness.cli coord presence`로 확인한다.
"""

PROJECT_MANUAL_TEMPLATE = """# 프로젝트 총괄 매뉴얼 (UAOS Project Manual)

- work_id: PROJECT
- 프로젝트 목표: 프로젝트 전체 목적과 해결 과제를 정의한다.
- 승인 경계: 데이터 삭제, push·배포, 결제, 권한 변경은 사용자 승인 필수.
- 권한 상태기계: Codex ACTIVE → Claude ACTIVE → 둘 다 LIMITED/ABSENT일 때 Antigravity ACTIVE. UNKNOWN은 fail-closed.
- 예산: 잔여율·리셋 창을 토큰으로 환산하지 않고, 호출별 token/USD/time 상한을 각각 집행한다.
- 위임: 계약 파일을 먼저 발행·lint하고 그 내용 전체를 호출에 포함한다.
- 단일 원장: `.coord/PLAN.md`; 작성자와 최종 판정자는 분리한다.
- 보존: archive candidate와 복구 manifest만 만들고 실제 삭제는 별도 최신 승인을 요구한다.

## Goal
One sentence: what is done when this project is done.

## Scope
Files and folders the tools may change.

## Forbidden
Actions that always need the user: deletion, push/deploy/publish, payment, account/permission/credential changes.

## Gates
The commands that decide done (tests, checks). A step without a gate is unmeasured.

## Workers
Who does what: apply (0 tokens) when the code is known, Ollama for narrow mechanical work, Antigravity or `worker: claude` with a token and dollar cap for judgment work.

## Judge
The tool that approves, never the author of the same change.
"""

CONTRACT_MANUAL_TEMPLATE = "Generated per project by cmd_coord_init with a pinned .coord/PLAN.md hash."


def cmd_coord_init(args: argparse.Namespace) -> int:
    """Prepare any project for UAOS. Idempotent: existing files are never overwritten, only missing lines are added."""
    project = Path(args.project)
    if not project.is_dir():
        print(json.dumps({"ok": False, "error": f"not a directory: {project}"}, ensure_ascii=False))
        return 1
    created: list[str] = []
    plan = project / ".coord" / "PLAN.md"
    if not plan.is_file():
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text(PLAN_TEMPLATE, encoding="utf-8")
        created.append(".coord/PLAN.md")
    project_manual = project / ".coord" / "PROJECT_MANUAL.md"
    if not project_manual.is_file():
        project_manual.write_text(PROJECT_MANUAL_TEMPLATE, encoding="utf-8")
        created.append(".coord/PROJECT_MANUAL.md")
    for folder in (".coord/tasks", ".coord/mailbox", ".work"):
        if not (project / folder).is_dir():
            (project / folder).mkdir(parents=True)
            created.append(folder + "/")
    task_tpl = project / ".coord" / "tasks" / "contract_template.md"
    if not task_tpl.is_file():
        from .manual import new_manual

        task_tpl.parent.mkdir(parents=True, exist_ok=True)
        task_tpl.write_text(new_manual(
            project,
            work_id="T01_EXTRACT_READY_ID",
            worker="local",
            goal="Extract the first exact READY work item ID from `.coord/PLAN.md` into `.work/T01-result.txt`.",
            inputs=[".coord/PLAN.md"],
            allow=[".work/T01-result.txt"],
            acceptance='python -c "from pathlib import Path; assert Path(\'.work/T01-result.txt\').is_file()"',
            judge="codex",
            timeout_s=300,
        ), encoding="utf-8")
        created.append(".coord/tasks/contract_template.md")
    gitignore = project / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.is_file() else []
    missing = [line for line in UAOS_GITIGNORE_LINES if line not in existing]
    if missing:
        prefix = "" if not existing or existing[-1] == "" else "\n"
        with gitignore.open("a", encoding="utf-8") as handle:
            handle.write(prefix + "# UAOS runtime state (coord init)\n" + "\n".join(missing) + "\n")
    print(json.dumps({"ok": True, "created": created, "gitignore_added": missing,
                      "contract_manuals": ".coord/tasks/<work_id>-manual.md",
                      "next": ["coord presence --tool <codex|claude|antigravity> --state ACTIVE",
                               "fill .coord/PROJECT_MANUAL.md (big picture) before the first delegation",
                               "pilot manual new ... then pilot manual lint ... then pilot run --manual ..."]},
                     ensure_ascii=False))
    return 0


def cmd_coord_inbox(args: argparse.Namespace) -> int:
    """U32b: list what waits in the voicemail without claiming it."""
    from .coord.mailbox import Mailbox

    mailbox_dir = Path(args.project) / ".coord" / "mailbox"
    if not mailbox_dir.is_dir():
        print(json.dumps({"ok": True, "messages": [], "bad": []}, ensure_ascii=False))
        return 0
    box = Mailbox(mailbox_dir)
    messages = []
    for message_id, payload in box.peek():
        data = payload if isinstance(payload, dict) else {}
        messages.append({
            "id": message_id,
            "kind": data.get("kind") or ("P1" if data.get("p1_alert") else None),
            "step": data.get("step"),
            "summary": data.get("summary") or data.get("wake_reason"),
        })
    print(json.dumps({"ok": True, "messages": messages, "bad": box.list_bad()}, ensure_ascii=False))
    return 0


def cmd_coord_ack(args: argparse.Namespace) -> int:
    """U32b: mark one voicemail message as handled so it stops showing up in briefs and bells."""
    from .coord.mailbox import Mailbox, MailboxRejected

    box = Mailbox(Path(args.project) / ".coord" / "mailbox")
    claim = box.claim(args.message_id, consumer_id=args.consumer)
    if claim is None:
        already = (box.ack_dir / f"{args.message_id}.json").is_file()
        print(json.dumps({"ok": already, "id": args.message_id,
                          "error": None if already else "NOT_IN_INBOX"}, ensure_ascii=False))
        return 0 if already else 1
    try:
        box.ack(claim)
    except (MailboxRejected, OSError) as exc:
        box.nack(claim)
        print(json.dumps({"ok": False, "id": args.message_id, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "id": args.message_id}, ensure_ascii=False))
    return 0


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_rsi_report(args: argparse.Namespace) -> int:
    from .olla import USAGE_LOG
    from .rsi import analyze, load_policy, load_rows, local_usage, open_trials, read_decisions

    project = Path(args.project)
    policy = load_policy(project)
    rows = load_rows(project)
    report = analyze(rows, policy)
    # U47-D1: the local model's real work (fake 1/1 rows excluded), joined to the pilot ledger by work_id.
    report["local"] = local_usage(USAGE_LOG, rows)
    report["policy"] = policy
    report["decisions"] = len(read_decisions(project))
    # An adopted change whose window is complete is due for its re-check: keep it or `rsi rollback`.
    report["trials"] = open_trials(project, rows)
    _print_json(report)
    return 0


def cmd_rsi_propose(args: argparse.Namespace) -> int:
    from .rsi import analyze, candidate_template, load_policy, load_rows, propose

    project = Path(args.project)
    policy = load_policy(project)
    proposals = propose(analyze(load_rows(project), policy), policy)
    if args.candidate_for:
        match = [proposal for proposal in proposals if proposal["id"] == args.candidate_for]
        if not match:
            _print_json({"ok": False, "error": f"unknown proposal id: {args.candidate_for}"})
            return 1
        _print_json(candidate_template(match[0], args.author or detect_actor() or "unknown"))
        return 0
    _print_json({"proposals": proposals,
                 "next": "try one proposal on a trial manual, then `rsi gate --candidate FILE` and hand it to the judge"})
    return 0


def _read_candidate(path: str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("the candidate file must hold a JSON object")
    return data


def cmd_rsi_gate(args: argparse.Namespace) -> int:
    from .rsi import gate_from_ledger

    try:
        candidate = _read_candidate(args.candidate)
    except (OSError, ValueError) as exc:
        _print_json({"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]})
        return 1
    verdict = gate_from_ledger(Path(args.project), candidate)
    _print_json(verdict)
    return 0 if verdict["decision"] == "ADOPT_CANDIDATE" else 2


def cmd_rsi_adopt(args: argparse.Namespace) -> int:
    from .rsi import RsiRefused, adopt

    try:
        result = adopt(Path(args.project), _read_candidate(args.candidate), args.judge)
    except RsiRefused as exc:
        # B83: always refused; the evidence and the proposed file go into a PLAN card instead.
        _print_json({"ok": False, "error": str(exc)[:500], "evidence": exc.evidence,
                     "proposed_policy_json": exc.proposed_policy})
        return 2
    except (OSError, ValueError) as exc:
        _print_json({"ok": False, "error": str(exc)[:500]})
        return 2
    _print_json({"ok": True, **result})
    return 0


def cmd_rsi_rollback(args: argparse.Namespace) -> int:
    from .rsi import RsiRefused, rollback

    try:
        result = rollback(Path(args.project), args.judge, args.reason)
    except RsiRefused as exc:
        _print_json({"ok": False, "error": str(exc), "proposed_policy_json": exc.proposed_policy})
        return 2
    _print_json({"ok": True, **result})
    return 0


def cmd_rsi_watch(args: argparse.Namespace) -> int:
    import time
    from .rsi_release import run_scheduler_cycle

    project = Path(args.project)
    config_path = Path(args.config) if args.config else project / ".coord" / "rsi" / "watcher.json"
    if not config_path.is_file():
        config = {
            "interval_seconds": 86400,
            "timeout_seconds": 15,
            "max_retries": 3,
            "backoff_base_seconds": 60,
            "lock_ttl_seconds": 3600,
            "sources": [],
        }
    else:
        config = json.loads(config_path.read_text(encoding="utf-8"))

    def _record(event: dict[str, Any]) -> None:
        # A quiet local scheduler still leaves one line when it recovers a dead/stale lock.
        print(json.dumps({"scheduler_event": event}, ensure_ascii=False))

    res = run_scheduler_cycle(project, config, now=time.time(), sleeper=time.sleep, record=_record)
    _print_json(res)
    return 0 if res.get("status") in ("ACK_ONLY", "ACTIONABLE_DELTA") else 1


def cmd_rsi_retention(args: argparse.Namespace) -> int:
    import time

    from . import olla
    from .retention import (
        RetentionRefused,
        apply_retention,
        archive_candidates,
        default_policy,
        plan_retention,
        purge_archived,
        rollup_jsonl,
        work_dir_report,
    )

    now = time.time()
    project = Path(args.project)
    policy = default_policy()
    plan = plan_retention(project, policy, now=now)
    result = apply_retention(project, plan)
    out: dict = {"ok": True, **result}

    if getattr(args, "archive", False):
        out["archive"] = archive_candidates(project, plan, now=now)

    if getattr(args, "rollup_olla", False):
        out["rollup"] = rollup_jsonl(olla.USAGE_LOG, olla.USAGE_LOG.parent / "archive")

    if getattr(args, "purge", None):
        approval_path = Path(args.approval) if getattr(args, "approval", None) else project / "unused_approval.json"
        try:
            purge_archived(project, Path(args.purge), approval_path)
        except RetentionRefused as exc:
            _print_json({
                "ok": False,
                "status": "FRESH_DELETE_APPROVAL_REQUIRED",
                "error": str(exc),
                "purge": {"status": "REFUSED", "deleted": 0},
            })
            return 2
        raise AssertionError("purge_archived must always fail closed")

    out["work_report"] = work_dir_report(project, now=now)
    _print_json(out)
    return 0


def cmd_rsi_prepare(args: argparse.Namespace) -> int:
    from .rsi_release import ReleaseRefused, prepare_release

    project = Path(args.project)
    packet = json.loads(Path(args.packet).read_text(encoding="utf-8"))
    try:
        plan = prepare_release(project, packet, apply=args.apply, date=args.date)
    except (ReleaseRefused, ValueError) as exc:
        _print_json({"ok": False, "error": str(exc)})
        return 1
    _print_json({"ok": True, **plan})
    return 0


def cmd_rsi_ship(args: argparse.Namespace) -> int:
    from .rsi_release import ReleaseRefused, ship_release

    project = Path(args.project)
    packet = json.loads(Path(args.packet).read_text(encoding="utf-8"))
    approval = json.loads(Path(args.approval).read_text(encoding="utf-8"))
    try:
        res = ship_release(project, packet, approval, execute=args.execute)
    except (ReleaseRefused, ValueError) as exc:
        _print_json({"ok": False, "error": str(exc)})
        return 1
    _print_json({"ok": True, **res})
    return 0


def cmd_rsi_schedule(args: argparse.Namespace) -> int:
    from .rsi_release import windows_schedule

    project = Path(args.project)
    python_bin = args.python_bin or sys.executable
    res = windows_schedule(project, python_bin, action=args.action, apply=args.apply)
    _print_json(res)
    return 0 if res.get("status") == "DRY_RUN" or res.get("ok") else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    # Windows 콘솔 기본(cp949)에서는 `coord brief` 등의 한국어가 깨진다. olla.main 과 같은 처리.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "coord_subcommand", None) in _DESK_COMMANDS and getattr(args, "project", None):
        from .coord.hook_context import shared_desk

        desk = shared_desk(args.project)
        if desk != Path(args.project):  # unchanged paths keep the caller's spelling
            args.project = str(desk)
    return args.func(args)


# U59: commands that read or write gitignored desk state (presence, mail, watch files) run against the main checkout
# when called from a linked worktree, so every session of a repository shares one desk. PLAN readers (log, status,
# brief) keep the worktree's own branch copy.
_DESK_COMMANDS = frozenset({"presence", "watch", "route", "sentinel", "inbox", "ack", "archive"})


if __name__ == "__main__":
    sys.exit(main())
===FILE: tests/test_u72l_desk_ledger.py===
"""U72-L: a run inside a linked worktree lands in the desk ledger, and rows stranded in worktree copies come back.

Seen 2026-09-28: U68-U71 ran their pilots in `.work/<id>` worktrees. Each appended to that worktree's copy of the
tracked `runs.jsonl`, which is never committed, so the desk ledger that admission (U69) and RSI read stopped at
U44-FIX6B. The U72 gate "no ledger omission" could not pass.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from v7_harness.admission import ledger_rows
from v7_harness.coord.usage_ledger import collect, linked_worktrees, record_usage

REPO = Path(__file__).resolve().parents[1]


def _entry(work_id: str) -> dict:
    return {"schema": "uaos-usage-v2", "work_id": work_id, "actor": "coordinator", "model": "deterministic",
            "kind": "pilot", "collection_mode": "automatic", "input_tokens": 0, "output_tokens": 0,
            "wall_time_s": 1.5, "outcome": "PASS", "receipt": "r.json", "independent_verifier": None,
            "rsi_eligible": False, "exclusion_reason": "PENDING_INDEPENDENT_VERIFICATION", "ts": 1.0}


def _line(work_id: str) -> str:
    return json.dumps(_entry(work_id), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _ledger(root: Path) -> Path:
    return root / ".coord" / "usage" / "runs.jsonl"


def _write(root: Path, *work_ids: str, crlf: bool = False) -> None:
    path = _ledger(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    end = "\r\n" if crlf else "\n"
    path.write_bytes("".join(_line(w) + end for w in work_ids).encode("utf-8"))


def _ids(root: Path) -> list[str]:
    return [json.loads(line)["work_id"] for line in _ledger(root).read_text(encoding="utf-8").splitlines() if line]


class DeskFixture(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.desk = base / "main"
        (self.desk / ".coord").mkdir(parents=True)
        (self.desk / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        self.trees = []
        for name in ("w1", "w2"):
            (self.desk / ".git" / "worktrees" / name).mkdir(parents=True)
            tree = base / name
            (tree / ".coord").mkdir(parents=True)
            (tree / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
            (tree / ".git").write_text(f"gitdir: {(self.desk / '.git' / 'worktrees' / name).as_posix()}\n",
                                       encoding="utf-8")
            # Git's own back-pointer: the linked worktree's `.git` file path.
            (self.desk / ".git" / "worktrees" / name / "gitdir").write_text(f"{(tree / '.git').as_posix()}\n",
                                                                           encoding="utf-8")
            self.trees.append(tree)

    def tearDown(self) -> None:
        self._tmp.cleanup()


class DeskRoutingTests(DeskFixture):
    def test_a_worktree_run_is_recorded_and_read_on_the_desk(self) -> None:
        written = record_usage(self.trees[0], _entry("U72L-A"))
        self.assertEqual(_ledger(self.desk).resolve(), written.resolve())
        self.assertFalse(_ledger(self.trees[0]).exists())
        # Admission inside the worktree sees the desk floor it just added to.
        self.assertEqual(["U72L-A"], [r["work_id"] for r in ledger_rows(self.trees[1])])

    def test_a_plain_folder_keeps_its_own_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(_ledger(Path(d)).resolve(), record_usage(Path(d), _entry("U72L-P")).resolve())


class CollectTests(DeskFixture):
    def test_stranded_rows_come_back_once_and_only_with_apply(self) -> None:
        _write(self.desk, "BASE1", "BASE2", crlf=True)  # a CRLF checkout of the same rows is not a new row
        _write(self.trees[0], "BASE1", "BASE2", "U68", "U70")
        _write(self.trees[1], "BASE1", "U70", "U71")
        dry = collect(self.desk, trees=self.trees)
        self.assertEqual((3, 0, "DRY_RUN"), (dry["orphans"], dry["appended"], dry["mode"]))
        self.assertEqual(["BASE1", "BASE2"], _ids(self.desk))
        done = collect(self.desk, trees=self.trees, apply=True)
        self.assertEqual(3, done["appended"])
        self.assertEqual(["BASE1", "BASE2", "U68", "U70", "U71"], _ids(self.desk))
        # The appended bytes are the worktree's own line, not a re-stamped record.
        self.assertIn(_line("U68"), _ledger(self.desk).read_text(encoding="utf-8").splitlines())
        self.assertEqual(0, collect(self.desk, trees=self.trees, apply=True)["appended"])

    def test_worktrees_are_found_from_git_records_without_a_subprocess(self) -> None:
        (self.desk / ".git" / "worktrees" / "gone").mkdir()
        (self.desk / ".git" / "worktrees" / "gone" / "gitdir").write_text("/nowhere/.git\n", encoding="utf-8")
        self.assertEqual([t.resolve() for t in self.trees], [t.resolve() for t in linked_worktrees(self.desk)])
        _write(self.desk, "BASE1")
        _write(self.trees[1], "BASE1", "U71")
        self.assertEqual(1, collect(self.trees[0], apply=True)["appended"])  # from inside a worktree, too
        self.assertEqual(["BASE1", "U71"], _ids(self.desk))

    def test_parallel_collectors_append_each_row_once(self) -> None:
        _write(self.desk, "BASE1")
        for i, tree in enumerate(self.trees):
            _write(tree, "BASE1", *[f"T{i}-{n}" for n in range(20)])
        code = ("import sys; from pathlib import Path; from v7_harness.coord.usage_ledger import collect; "
                "collect(Path(sys.argv[1]), trees=[Path(p) for p in sys.argv[2:]], apply=True)")
        argv = [sys.executable, "-c", code, str(self.desk), *map(str, self.trees)]
        env = {**os.environ, "PYTHONPATH": str(REPO)}
        procs = [subprocess.Popen(argv, cwd=REPO, env=env, stderr=subprocess.PIPE, text=True) for _ in range(6)]
        for proc in procs:
            _, err = proc.communicate(timeout=120)
            self.assertEqual(0, proc.returncode, err)
        ids = _ids(self.desk)
        self.assertEqual(41, len(ids))
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
===FILE: docs/59_u72l-desk-ledger.md===
# U72-L 저장소 하나에 장부 하나

## 왜 필요한가

U72의 완료 관문에는 "사용량 장부 누락 0"이 있다. 그런데 2026-09-28에 데스크 장부(`.coord/usage/runs.jsonl`)를 확인해 보니 마지막 행이 U44-FIX6B였다. U68~U71의 pilot 실행 기록이 하나도 없었다.

원인은 다음과 같다.

- 작업은 `.work/<id>` 같은 연결 작업트리(linked worktree)에서 돈다.
- pilot, 리뷰, 판정은 실행한 폴더(`source`)의 `.coord/usage/runs.jsonl`에 행을 추가했다.
- 그 파일은 git이 추적하는 파일의 작업트리 사본이다. 커밋하지 않는 것이 규칙이라 기록이 그 사본 안에 갇혔다.
- 입장 관문(U69)과 RSI는 데스크 장부만 읽는다. 그래서 새 기록을 보지 못했다.

presence, 우편함, 감시 파일은 이미 U59에서 "작업트리도 본 체크아웃의 데스크를 쓴다"로 고쳤다. 장부만 빠져 있었다.

## 무엇을 바꿨나

1. **쓰기** — `record_usage`는 `ledger_file(project)`에 쓴다. `ledger_file`은 U59의 `shared_desk`로 본 체크아웃을 찾는다.
   - 연결 작업트리의 기록은 본 체크아웃 장부로 간다.
   - 일반 폴더나 임시 폴더는 전처럼 자기 장부를 쓴다.
   - 이 경로 하나로 pilot, judge, review 세 곳의 기록 경로가 함께 바뀐다.
2. **읽기** — 입장 관문 `admission.ledger_rows`와 RSI `load_rows`도 같은 `ledger_file`을 읽는다. 작업트리 안에서 판정해도 저장소 전체 바닥(floor)을 본다.
3. **회수** — `coord usage-collect [--apply]`는 작업트리 사본에만 남은 행을 찾아 데스크 장부 끝에 덧붙인다.
   - 작업트리 목록은 git이 남긴 `<desk>/.git/worktrees/<이름>/gitdir` 파일에서 읽는다. 하위 프로세스를 띄우지 않으므로 U54 방화벽 감사(firewall audit)에 새 실행 지점이 생기지 않는다.
   - 행의 동일성은 JSON을 정규형(키 정렬)으로 바꿔 비교한다. 줄바꿈(CRLF)이나 키 순서가 달라도 같은 행은 한 번만 센다.
   - 덧붙이는 내용은 작업트리가 쓴 줄 그대로다. 재검증하거나 시각을 다시 찍지 않는다. 장부는 추가 전용(append-only) 기록이기 때문이다.
   - 읽기, 비교, 추가가 모두 장부 잠금 안에서 일어난다. 그래서 수집기 여러 개가 동시에 돌아도 행마다 한 번만 추가된다. 프로세스 6개로 확인했다.
   - 기본은 드라이런(dry-run)이다. 삭제는 하지 않는다.

## 실측(2026-09-28, 드라이런)

- 연결 작업트리 35개에서 데스크에 없는 행 142개를 찾았다.
- 예: Codex `relay-nonstop` 55행, `.work/u45_claude` 30행, 이 Claude 세션 작업트리 14행, U68~U71 작업트리 각 1~3행.
- 일부는 데스크 체크아웃보다 새 커밋에 이미 있는 행일 수 있다. 어느 쪽이든 실제로 일어난 실행 기록이므로 덧붙이는 것이 맞다.
- 이 PR이 병합되면 `--apply`로 회수한 뒤 U72 표본을 센다.

## 고정 인수

`tests/test_u72l_desk_ledger.py`가 확인하는 것:

- 작업트리에서 쓴 기록이 데스크로 간다. 수정 전(58ba50b)에는 작업트리 쪽에 써서 이 시험이 실패한다(red).
- 일반 폴더는 바뀌지 않는다.
- 회수는 드라이런과 적용이 구분되고, 같은 행은 한 번만 추가된다. 두 번째 실행은 0행을 추가한다.
- CRLF로 저장된 같은 행은 새 행으로 보지 않는다.
- 작업트리 목록을 git 기록에서 찾는다. 사라진 작업트리는 건너뛴다.
- 수집기 6개를 동시에 돌려도 41행이 모두 한 번씩만 들어간다.
===END===

## Output

- Reply with ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.
