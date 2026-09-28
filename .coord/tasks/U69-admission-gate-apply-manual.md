```contract
work_id: U69
worker: apply
goal: Refuse a paid pilot run, cascade escalation or review before the call when its token, USD or time budget is below the cheapest complete call the project's usage ledger records
inputs:
- v7_harness/cli.py sha256=7664b61b25b7003d0c5ba20b1df573cc3426ec70a3e2959576aa5115a63f0b94
- v7_harness/review.py sha256=7c405909d7f25e7f80d43fbb9bd63b9d5ebfaa2de629364914063253f9f36308
allow:
- v7_harness/admission.py
- v7_harness/cli.py
- v7_harness/review.py
- tests/test_u69_admission_gate.py
- docs/56_u69-paid-call-admission-gate.md
acceptance: python -m unittest tests.test_u69_admission_gate tests.test_u38_cost_gate_and_claude_worker tests.test_u44_claude_contract tests.test_u54_s2_caller_review
forbidden: design changes; edits outside allow; weakening or deleting existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Card U69 (docs/55): U67-C1 spent 485,172 tokens and $0.43 under a 12,000-token contract before the B85 gate discarded it. The new tests fail on origin/main 90df07e (no admission module). Judge claude (ACTING while Codex is LIMITED); Codex re-reviews. Write the five files below exactly.

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
    path = Path(project) / LEDGER
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
===FILE: v7_harness/review.py===
"""U38: an independent, read-only review of a pilot bundle by Claude Code (`pilot review`). docs/40 §2-2.

The review is evidence for the judge, never a verdict. On one OS account every actor name can be forged (B83), so
a reviewer's PASS cannot stand in for Codex's or the user's approval; it is written with "advisory": true. A reviewer
never reviews its own worker's bundle, and it runs under the same budget gate as a paid worker (B85).
"""

from __future__ import annotations

import difflib
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

# U46-J1: agy lets a conductor wake Antigravity through its CLI instead of a mailbox letter a person must relay.
REVIEWERS = ("claude", "agy")
SCHEMA_HINT = ('{"verdict": "PASS" or "REWORK", "counterexamples": ["..."], '
               '"evidence_lines": ["path:line quote", "..."]}')
MAX_DIFF_CHARS = 60_000
FINAL_ANSWER = ("Stop reading. Answer now with the one JSON verdict object from what you have already read: "
                + SCHEMA_HINT)
# Windows caps a whole command line at 32,767 characters (WinError 206 on the U44-FIX4 review). Past
# ARGV_PROMPT_CHARS (adapters/long_prompt.py) the request goes on standard input, which claude -p reads with the short
# argv prompt (live: 46,529 chars).
STDIN_PROMPT = "The full review request (contract and diff) is on standard input. Follow it."


class ReviewRefused(Exception):
    pass


def bundle_diff(source: Path, staging: Path, changed: list[str]) -> str:
    parts = []
    for rel in changed:
        before = (source / rel).read_text(encoding="utf-8", errors="replace").splitlines(True) if (source / rel).is_file() else []
        after = (staging / rel).read_text(encoding="utf-8", errors="replace").splitlines(True) if (staging / rel).is_file() else []
        parts.extend(difflib.unified_diff(before, after, f"a/{rel}", f"b/{rel}"))
    return "".join(parts)


def review_prompt(task_id: str, manual_text: str, diff: str, spill_path: str | Path | None = None) -> str:
    # U52: a plain diff[:MAX] cut the tail silently while the prompt called the diff complete; the gate keeps head and
    # tail, marks the cut, and the prompt says the diff is partial so the reviewer reads the changed files instead.
    from .output_gate import gate_output

    gated = gate_output(diff, MAX_DIFF_CHARS, spill_path)
    scope = ("The diff below is PARTIAL (see the U52 OUTPUT CUT marker): read the changed files in the current "
             "directory for the omitted part before judging it. " if gated.truncated else
             "The diff below is the complete change: judge from it. ")
    return (f"[{task_id}] Review this change against its contract. {scope}"
            "Read a file only to confirm one specific counterexample, and answer within a few turns.\n\n"
            f"## Contract\n{manual_text}\n\n## Diff\n```diff\n{gated.text}\n```\n\n"
            f"Reply with exactly one JSON object: {SCHEMA_HINT}")


def merge_usage(first: dict[str, int], second: dict[str, int]) -> dict[str, int]:
    merged = {key: first.get(key, 0) + second.get(key, 0) for key in set(first) | set(second) if key != "cost_microusd"}
    if "cost_microusd" in first or "cost_microusd" in second:
        # claude reports a resumed session's running total (U44 live: 251,432 then 268,659), so take the larger.
        merged["cost_microusd"] = max(first.get("cost_microusd", 0), second.get("cost_microusd", 0))
    return merged


def parse_verdict(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or data.get("verdict") not in ("PASS", "REWORK"):
        return None
    return {"verdict": data["verdict"],
            "counterexamples": [str(x)[:500] for x in data.get("counterexamples") or []][:20],
            "evidence_lines": [str(x)[:300] for x in data.get("evidence_lines") or []][:40]}


def run_review(*, task_id: str, work_dir: Path, source: Path, manual_text: str, reviewer: str, budget: int,
               budget_usd: float = 0.0, model: str | None = None, timeout_s: int = 600,
               runner: Any = subprocess.run) -> dict[str, Any]:
    from .adapters.claude_worker import DEFAULT_MODEL, review_command, usage_from, worker_env
    from .pilot import evaluate_cost_gate

    if reviewer not in REVIEWERS:
        raise ReviewRefused(f"UNKNOWN_REVIEWER:{reviewer}")
    if budget <= 0:
        raise ReviewRefused("REVIEW_WITHOUT_BUDGET: pass --budget > 0 (a review is a paid call)")
    if reviewer == "claude" and not budget_usd > 0:
        # agy has no dollar cap option; its review is held by the token budget gate alone (B85).
        raise ReviewRefused("REVIEW_WITHOUT_USD_CAP: pass --budget-usd > 0 (claude --max-budget-usd, before spending)")
    runs = Path(work_dir) / "runs" / task_id
    try:
        summary = json.loads((runs / "summary.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewRefused(f"NO_PILOT_SUMMARY:{runs / 'summary.json'} ({type(exc).__name__})") from exc
    try:
        author = (runs / "worker").read_text(encoding="utf-8").strip()
    except OSError:
        author = ""
    if not author:
        # Fail closed: without the author the rule "never review your own worker's bundle" cannot be checked.
        raise ReviewRefused(f"AUTHOR_UNKNOWN: {runs / 'worker'} is missing (bundle built before U38?)")
    if author == reviewer:
        raise ReviewRefused(f"REVIEWER_IS_AUTHOR:{reviewer} wrote this bundle")
    staging = Path(summary.get("agy_workspace") or "")
    changed = [str(x) for x in summary.get("changed_files") or []]
    if not changed or not staging.is_dir():
        raise ReviewRefused("NOTHING_TO_REVIEW: no changed files or no staged copy")
    # U69: U67-C1 was a 12,000-token review that spent 485,172 before the gate discarded it. Refuse before the call
    # when the budget is below the cheapest review this reviewer has recorded in the project's ledger.
    from .admission import admit

    admission = admit(Path(source), worker=reviewer, kind="review", budget_tokens=budget, budget_usd=budget_usd,
                      timeout_s=timeout_s)
    if admission["decision"] == "REFUSE":
        raise ReviewRefused("ADMISSION_REFUSED:" + ";".join(admission["reasons"]))

    # The spill goes in the run folder, never in staging: a file written there would become part of the bundle.
    prompt = review_prompt(task_id, manual_text, bundle_diff(Path(source), staging, changed), runs / "review.diff")
    started = time.monotonic()
    usage: dict[str, int] = {}
    error = ""
    verdict = None
    conversation_id = None
    try:
        if reviewer == "agy":
            usage, verdict, error, conversation_id = _agy_review(task_id, prompt, runs, timeout_s, runner)
            raise _Reviewed
        from .adapters.long_prompt import ARGV_PROMPT_CHARS

        via_stdin = len(prompt) > ARGV_PROMPT_CHARS
        done = runner(review_command(STDIN_PROMPT if via_stdin else prompt, model or DEFAULT_MODEL, budget_usd),
                      cwd=str(staging), env=worker_env(), capture_output=True, timeout=timeout_s,
                      **({"input": prompt.encode("utf-8")} if via_stdin else {}))
        result = json.loads(done.stdout.decode("utf-8", errors="replace"))
        if isinstance(result, dict):
            usage = usage_from(result)
            verdict = parse_verdict(str(result.get("result") or ""))
            left_usd = budget_usd - usage.get("cost_microusd", 0) / 1_000_000
            if (verdict is None and result.get("subtype") == "error_max_turns" and result.get("session_id")
                    and left_usd >= 0.01):
                # Out of turns before answering (U44-FIX3: 6 turns of reading, no verdict). One more turn in the same
                # session answers from what it already read (U44 live: 1 turn, 48k tokens) instead of a fresh review.
                done = runner(review_command(FINAL_ANSWER, model or DEFAULT_MODEL, left_usd,
                                             resume=str(result["session_id"])),
                              cwd=str(staging), env=worker_env(), capture_output=True, timeout=timeout_s)
                final = json.loads(done.stdout.decode("utf-8", errors="replace"))
                if isinstance(final, dict):
                    usage = merge_usage(usage, usage_from(final))
                    verdict = parse_verdict(str(final.get("result") or ""))
                    result = final
            if verdict is None:
                error = f"REVIEW_UNPARSED: the reviewer did not return the JSON verdict ({result.get('subtype')})"
        else:
            error = "REVIEW_NOT_JSON_OBJECT"
    except _Reviewed:
        pass
    except subprocess.TimeoutExpired:
        error = f"REVIEW_TIMEOUT:{timeout_s}s"
    except (OSError, ValueError) as exc:
        error = f"REVIEW_FAILED:{type(exc).__name__}: {exc}"[:300]
    cost_gate = evaluate_cost_gate(usage, budget)
    record = {
        "task_id": task_id, "reviewer": reviewer, "author_worker": author, "bundle_id": summary.get("bundle_id"),
        # Evidence for the judge, not a verdict (B83): the judge still approves or rejects the bundle.
        "advisory": True,
        "verdict": verdict["verdict"] if verdict and cost_gate == "WITHIN" else "UNUSABLE",
        "counterexamples": (verdict or {}).get("counterexamples", []),
        "evidence_lines": (verdict or {}).get("evidence_lines", []),
        "cost_gate": cost_gate, "usage": usage, "elapsed_s": int(time.monotonic() - started), "error": error,
    }
    if reviewer == "agy":
        record["judge_conversation_id"] = conversation_id
    out = runs / f"review_{reviewer}.json"
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    record["review_path"] = str(out)
    _record_usage(Path(source), task_id, reviewer, model or (DEFAULT_MODEL if reviewer == "claude" else "agy-default"),
                  usage, record, out)
    return record


class _Reviewed(Exception):
    """Leaves the claude call path once the agy review has run."""


def _agy_review(task_id: str, prompt: str, runs: Path, timeout_s: int,
                runner: Any) -> tuple[dict[str, int], dict[str, Any] | None, str, str | None]:
    """Antigravity reads the request from a file in the run folder (a diff can pass the 32,767-character Windows
    command line) and answers in JSON. No permission bypass: it can read, and only the pilot applies anything."""
    import os

    from .adapters.agy import AgyRequest, build_agy_command, parse_agy_result

    request = runs / "review_agy_request.md"
    request.write_text(prompt, encoding="utf-8")
    short = (f"Read {request.name} in this folder: a review request with the contract and the complete diff. "
             f"Do not edit any file. Reply with exactly one JSON object: {SCHEMA_HINT}")
    argv = build_agy_command(AgyRequest(task_id=task_id, title="review", prompt=short, workspace=runs,
                                        isolation_mode="staging", print_timeout_s=timeout_s))
    done = runner(argv, cwd=str(runs), env={**os.environ, "UAOS_WORKER": "1"}, capture_output=True,
                  timeout=timeout_s + 60)
    outcome = parse_agy_result(stdout=done.stdout or b"", stderr=done.stderr or b"", exit_code=done.returncode)
    usage = dict(outcome.usage)
    if not outcome.successful:
        return usage, None, f"REVIEW_FAILED:agy {outcome.error_class}", outcome.conversation_id
    envelope = json.loads(done.stdout.decode("utf-8", errors="replace"))
    text = envelope.get("response") if isinstance(envelope.get("response"), str) else json.dumps(
        envelope.get("structured_output"))
    verdict = parse_verdict(text)
    return (usage, verdict, "" if verdict else "REVIEW_UNPARSED: the reviewer did not return the JSON verdict (agy)",
            outcome.conversation_id)


def _record_usage(source: Path, task_id: str, reviewer: str, model: str, usage: dict[str, int], record: dict,
                  receipt: Path) -> None:
    """A review is a paid call; it goes in the ledger as kind "review" (RSI windows read kind "pilot" only)."""
    if not ((source / ".git").is_dir() or (source / ".coord" / "PLAN.md").is_file()):
        return
    from .coord.usage_ledger import record_usage

    entry = {
        "schema": "uaos-usage-v2", "work_id": f"{task_id}-review-{reviewer}", "actor": reviewer, "model": model,
        "kind": "review", "collection_mode": "automatic",
        "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
        # U46-J2: absolute, so the receipt resolves from any cwd (it was stored as ..\..\runs\...).
        "wall_time_s": None, "outcome": record["verdict"], "receipt": str(Path(receipt).resolve()),
        "independent_verifier": None,
        "rsi_eligible": False, "exclusion_reason": "ADVISORY_REVIEW", "worker": reviewer, "cost_gate": record["cost_gate"],
    }
    for extra in ("cache_creation_input_tokens", "cache_read_input_tokens", "cost_microusd"):
        if extra in usage:
            entry[extra] = usage[extra]
    try:
        record_usage(source, entry)
    except Exception as exc:  # noqa: BLE001 - the review file is the receipt; the ledger is best effort
        record["usage_ledger_error"] = f"{type(exc).__name__}: {exc}"[:200]
===FILE: tests/test_u69_admission_gate.py===
"""U69: a paid call whose contract is below the observed floor is refused before it spends.

The numbers are the project's real ledger: the cheapest complete Claude review (U44-FIX5) counted 124,769 tokens and
$0.133923, and U67-C1 ran a review under a 12,000-token contract that then spent 485,172 tokens and $0.43.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from v7_harness.admission import admit, observed_floor
from v7_harness.cli import main
from v7_harness.manual import new_manual
from v7_harness.review import ReviewRefused, run_review

REVIEW_FIX5 = {"worker": "claude", "kind": "review", "input_tokens": 10, "output_tokens": 1897,
               "cache_creation_input_tokens": 23779, "cache_read_input_tokens": 99083, "cost_microusd": 133923}
REVIEW_FIX = {"worker": "claude", "kind": "review", "input_tokens": 20, "output_tokens": 8191,
              "cache_creation_input_tokens": 72346, "cache_read_input_tokens": 497581, "cost_microusd": 470850}
FLOOR_TOKENS = 124769


def _ledger(root: Path, *rows: dict) -> None:
    usage = root / ".coord" / "usage"
    usage.mkdir(parents=True, exist_ok=True)
    (usage / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows) + "{not json\n", encoding="utf-8")


class FloorTests(unittest.TestCase):
    def test_floor_is_the_cheapest_complete_row_of_that_worker_and_kind(self) -> None:
        rows = [REVIEW_FIX, REVIEW_FIX5,
                # Incomplete or foreign rows would pull the floor under any real call; they do not count.
                {**REVIEW_FIX5, "cache_read_input_tokens": None, "input_tokens": 1},
                {k: v for k, v in REVIEW_FIX5.items() if k != "cache_creation_input_tokens"},
                {**REVIEW_FIX5, "output_tokens": True},
                {**REVIEW_FIX5, "kind": "pilot", "cache_read_input_tokens": 0},
                {**REVIEW_FIX5, "worker": "agy", "cache_read_input_tokens": 0}]
        self.assertEqual({"tokens": FLOOR_TOKENS, "microusd": 133923, "samples": 2},
                         observed_floor(rows, "claude", "review"))
        self.assertIsNone(observed_floor(rows, "claude", "judge"))

    def test_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertEqual("ADMIT_UNMEASURED", admit(root, worker="claude", kind="review", budget_tokens=1)["decision"])
            _ledger(root, REVIEW_FIX, {**REVIEW_FIX5, "wall_time_s": 95.4})
            refused = admit(root, worker="claude", kind="review", budget_tokens=12000, budget_usd=0.05, timeout_s=60)
            self.assertEqual("REFUSE", refused["decision"])
            self.assertEqual([f"BUDGET_BELOW_FLOOR:tokens:12000<{FLOOR_TOKENS}", "BUDGET_BELOW_FLOOR:usd:0.05<0.133923",
                              "BUDGET_BELOW_FLOOR:seconds:60<95"], refused["reasons"])
            # Exactly the floor fits: the floor is a call that really happened within that spend.
            self.assertEqual("ADMIT", admit(root, worker="claude", kind="review", budget_tokens=FLOOR_TOKENS,
                                            budget_usd=0.133923, timeout_s=95)["decision"])
            # A zero dollar or time budget means "not set" (agy has no dollar cap), not "below the floor".
            self.assertEqual("ADMIT", admit(root, worker="claude", kind="review", budget_tokens=200000)["decision"])


class PilotRunAdmissionTests(unittest.TestCase):
    def _manual(self, root: Path, budget: int) -> Path:
        (root / "pkg").mkdir(exist_ok=True)
        (root / "pkg" / "config.py").write_text("TIMEOUT = 30\n", encoding="utf-8")
        path = root / "m.md"
        path.write_text(new_manual(root, work_id="U69_T", worker="agy", goal="Set TIMEOUT = 60 in `pkg/config.py`.",
                                   inputs=["pkg/config.py"], allow=["pkg/config.py"],
                                   acceptance="python -c \"import pkg.config\"", judge="codex",
                                   remote_budget_tokens=budget), encoding="utf-8")
        return path

    def _run(self, root: Path, *extra: str) -> tuple[int, str, mock.MagicMock]:
        out = io.StringIO()
        with mock.patch("v7_harness.pilot.run_pilot", return_value={"state": "SUCCEEDED", "verdict_hint": "PASS"}) as run, \
                mock.patch("v7_harness.cli.detect_actor", return_value="codex"), \
                redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = main(["pilot", "run", "--task", "U69_T", "--source", str(root), "--manual", str(self._manual(root, 12000)),
                         *extra])
        return code, out.getvalue(), run

    def test_a_budget_below_the_floor_never_starts_the_worker(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _ledger(root, {**REVIEW_FIX5, "worker": "agy", "kind": "pilot"})
            code, out, run = self._run(root)
            self.assertEqual(2, code)
            run.assert_not_called()
            report = json.loads(out)
            self.assertEqual(("ADMISSION_REFUSED", [f"BUDGET_BELOW_FLOOR:tokens:12000<{FLOOR_TOKENS}"]),
                             (report["error_class"], report["admission"]["reasons"]))

    def test_a_budget_at_or_above_the_floor_and_an_approval_replay_run(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _ledger(root, {**REVIEW_FIX5, "worker": "agy", "kind": "pilot", "cache_read_input_tokens": 0})
            code, _, run = self._run(root)  # floor 25,686 without cache reads, still above 12,000
            self.assertEqual(2, code)
            run.assert_not_called()
            _ledger(root, {"worker": "agy", "kind": "pilot", "input_tokens": 3000, "output_tokens": 500,
                           "cache_creation_input_tokens": 0, "cache_read_input_tokens": 4000})
            code, _, run = self._run(root)
            run.assert_called_once()
            # --approve replays a saved bundle and spends nothing, so it is not admitted again.
            _ledger(root, {**REVIEW_FIX5, "worker": "agy", "kind": "pilot"})
            code, _, run = self._run(root, "--approve", "b" * 64)
            run.assert_called_once()


class ReviewAdmissionTests(unittest.TestCase):
    def test_the_u67_c1_review_is_refused_before_the_call(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source, staging, runs = root / "src", root / "stage", root / "work" / "runs" / "U69_R"
            for folder in (source, staging, runs):
                folder.mkdir(parents=True)
            (source / "a.py").write_text("x = 1\n", encoding="utf-8")
            (staging / "a.py").write_text("x = 2\n", encoding="utf-8")
            (runs / "summary.json").write_text(json.dumps({"agy_workspace": str(staging), "changed_files": ["a.py"]}),
                                               encoding="utf-8")
            (runs / "worker").write_text("agy", encoding="utf-8")
            _ledger(source, REVIEW_FIX5)
            runner = mock.Mock(side_effect=AssertionError("the paid reviewer must not start"))
            with self.assertRaises(ReviewRefused) as caught:
                run_review(task_id="U69_R", work_dir=root / "work", source=source, manual_text="m", reviewer="claude",
                           budget=12000, budget_usd=0.5, runner=runner)
            self.assertEqual(f"ADMISSION_REFUSED:BUDGET_BELOW_FLOOR:tokens:12000<{FLOOR_TOKENS}", str(caught.exception))
            runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
===FILE: docs/56_u69-paid-call-admission-gate.md===
# U69 유료 호출 입장 관문

## 왜 필요한가

B85 비용 관문(cost gate)은 유료 호출이 **끝난 뒤** 쓴 토큰을 계약 상한과 비교한다. 초과한 결과는 승인하지 않지만 돈과 한도는 이미 쓴 뒤다. U67-C1이 그 빈틈을 보여 줬다. 12,000토큰 계약의 Claude 감사가 실제로는 485,172토큰과 $0.43을 쓰고 나서야 폐기됐다.

Claude 호출은 매 턴 시스템 프롬프트·도구 정의·읽은 파일 같은 고정 컨텍스트를 캐시 읽기(cache read)로 다시 센다. 그래서 어떤 계약도 내려갈 수 없는 바닥(floor)이 있다. 바닥보다 작은 상한은 호출 전에 이미 실패가 확정된 계약이다.

## 무엇을 하나

`v7_harness/admission.py`가 호출 **전에** 프로젝트 사용량 장부(`.coord/usage/runs.jsonl`)를 읽어 판정한다.

- 바닥 = 같은 작업자(worker)·같은 호출 종류(kind: `pilot` 또는 `review`)의 기록 중 네 가지 토큰 종류(input, output, cache_creation, cache_read)가 모두 정수로 보고된 행의 **최솟값**. 비용(micro-USD)과 벽시계(`wall_time_s`)는 보고된 행이 있을 때만 바닥을 만든다.
- 캐시 토큰이 빠진 행은 실제보다 싸 보여 바닥을 끌어내리므로 표본에서 뺀다.
- 판정
  - `ADMIT`: 바닥이 있는 모든 차원(토큰·USD·초)에서 상한이 바닥 이상이다.
  - `ADMIT_UNMEASURED`: 표본이 없다. 첫 측정 자체를 막으면 영원히 바닥을 알 수 없으므로 허용하고, 끝난 뒤 B85가 판정한다.
  - `REFUSE`: 어느 한 차원이라도 상한이 바닥보다 작다. 이유는 `BUDGET_BELOW_FLOOR:tokens:12000<124769`처럼 차원과 두 숫자를 남긴다.
- USD·시간 상한이 0이면 "설정 안 함"으로 본다(agy에는 달러 상한 옵션이 없다).

## 어디에 걸려 있나

- `pilot run --worker agy|claude`: 매뉴얼 검사 뒤, 작업자 실행 전. 거부 시 `state: REFUSED`, `error_class: ADMISSION_REFUSED`, 종료 코드 2.
- `pilot run --worker cascade`의 유료 승격: 거부되면 `escalation: REFUSED:ADMISSION:<이유>`로 남기고 로컬 결과를 그대로 답으로 둔다.
- `pilot review --reviewer claude|agy`: 저자·변경 확인 뒤, 리뷰어 호출 전. 거부 시 `ADMISSION_REFUSED:<이유>`.
- `--approve`는 저장된 번들을 재생할 뿐 새로 쓰지 않으므로 다시 판정하지 않는다.

## 왜 최솟값인가

최솟값은 "실제로 일어난 가장 싼 호출"이다. 상한이 그보다 작으면 기록상 한 번도 들어맞은 적이 없는 계약이다. 반대로 최솟값 이상이면 들어맞을 수도 있으므로 막지 않는다. 즉 이 관문은 **확정된 낭비만** 막고, 가능성이 있는 호출은 막지 않는다(거짓 거부 0을 우선).

## 한계와 남은 위험

- 바닥은 과거 표본이다. 프롬프트나 도구가 줄어 실제 바닥이 내려가도, 상한을 한 번 올려 새 표본이 기록되기 전까지는 옛 바닥으로 거부한다. 탈출구는 상한을 바닥 이상으로 올리는 것이다.
- 2026-09-28 이 데스크 장부의 Claude 리뷰 바닥은 124,769토큰(U44-FIX5)이다. U47-C2가 정한 리뷰 기본 상한 120,000은 이 바닥보다 작아 거부된다. 상한 재결정은 Codex 복귀 판정 대상이다.
- 절감량은 통제 비교 전까지 `UNMEASURED`다. 확실한 것은 U67-C1 같은 호출에서 유료 토큰 0으로 거부된다는 점뿐이다.

## 고정 인수

`tests/test_u69_admission_gate.py` — 바닥 계산(불완전·다른 작업자·다른 종류 행 제외), 세 차원 거부와 경계값 허용, `pilot run` 작업자 미실행, 승인 재생 제외, U67-C1 리뷰의 호출 전 거부.
===END===

## Output

- Reply with ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.
