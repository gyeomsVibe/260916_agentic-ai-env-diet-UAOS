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


# U113: these workers never touch the file system; the harness writes their stage. Watching home and temp for them
# only caught other apps rewriting their own config (Codex config.toml in U113-D a001, Claude settings in U106-A2-agy).
HARNESS_ONLY_WORKERS = ("local", "apply")


def mandatory_watch_roots(work_dir: Path, source_dir: Path, worker: str = "agy") -> list[Path]:
    """Shallow roots a worker must not write into during a run.

    U45-F5: the work dir's parent used to be watched always. When that parent is a shared `.work/` folder, the
    conductor keeps writing its own notes there during a paid run (U45-G7 a001: two conductor files flagged, run
    abandoned, $0.319 lost). A shared `.work/` is therefore not watched; home, temp, the source's parent and the stage
    stay watched. A worker writing a sibling file inside `.work/` goes unseen, and `.work/` is never committed.
    """
    work = work_dir.resolve()
    if worker in HARNESS_ONLY_WORKERS:
        return [(work_dir / "stage").resolve()]
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
    # U98-D-F1: without a manual lint never ran, so apply took any amount of dictated code (U98-D-R P1).
    if chosen == "apply" and contract is None:
        from .delegation import delegate_first_errors

        refusal = delegate_first_errors(prompt or "", {"worker": "apply"}, source_dir)
        if refusal:
            print(json.dumps({"task_id": task_id, "state": "REFUSED", "error_class": "DELEGATE_FIRST",
                              "verdict_hint": "BLOCKED", "manual_errors": refusal}, indent=2, ensure_ascii=False))
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
    mandatory_roots = mandatory_watch_roots(work_dir, source_dir, chosen)
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
            escalate_to = getattr(args, "escalate_to", None)
            escalation = (_admission(source_dir, escalate_to, contract)
                          if escalate_to in REMOTE_WORKERS and remote_budget else None)
            if escalate_to is None and remote_budget:
                # U110: paying is the judge's call on each run (--escalate-to); auto-escalation spent ~7.6M Antigravity
                # tokens on 9 runs (2026-09-30..10-01), most of them FAILED or blocked.
                summary["escalation"] = "HELD:FAILED_LOCAL_GOES_TO_THE_JUDGE"
                trace.append("held")
            elif escalate_to in REMOTE_WORKERS + (None,) and not remote_budget:
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
        paid_after=args.paid_after,
        paid_reason=args.paid_reason,
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
    p_pilot_run.add_argument("--worker", choices=["agy", "local", "lane", "cascade", "auto", "apply", "claude"], default="auto", help="auto (default) = the router picks: dictated code -> apply, a specific task -> cascade (Ollama first), else agy; claude = Claude Code on the paid account (needs a manual with remote_budget_tokens; judge codex or user); agy = remote worker (uses account quota); local = this machine's Ollama model, one-shot; lane = Claude Code tool loop on the local model; apply = apply the ===FILE/===EDIT blocks written in the prompt, no model (0 tokens)")
    p_pilot_run.add_argument("--manual", default=None,
                             help="Work manual with a ```contract block: linted first, then its worker, acceptance, allow list and timeout drive the run")
    p_pilot_run.add_argument("--allow", action="append", default=[],
                             help="Path or glob the worker may change (repeatable); anything else is rejected as SCOPE_VIOLATION")
    # cascade 승격 대상 작업자(lane의 e2e 실패 빈발로 기본값은 agy)
    p_pilot_run.add_argument("--escalate-to", choices=["agy", "lane", "claude"], default=None, help="Worker for the cascade's second stage when local gets REWORK; omitted: hold for the judge (U110)")
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
    p_manual_new.add_argument("--paid-after", default="", help="U106: work_id of a failed local run of this card")
    p_manual_new.add_argument("--paid-reason", default="", help="U106: why this card needs the paid worker (3+ words)")
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
    # U95-A: antigravity has no CLI to wake; its letter waits in the inbox and its PreInvocation hook names it.
    p_coord_deliver.add_argument("--target", default=None, choices=["codex", "claude", "antigravity"])
    p_coord_deliver.add_argument("--message", required=True)
    p_coord_deliver.add_argument("--thread", default="")
    # U115: a card id routes the letter into that card's window (`.coord/windows/<card>.json`, U114).
    p_coord_deliver.add_argument("--card", default="")
    # U141-A: structured wake fields. Only these decide a paid wake; the message text is never read for it.
    p_coord_deliver.add_argument("--wake-class", default=None, choices=["ACTIONABLE", "NOTICE"])
    p_coord_deliver.add_argument("--verdict-requested", action="store_true", default=None)
    p_coord_deliver.add_argument("--verdict", default=None,
                                 choices=["PASS", "REVISE", "FAIL", "APPROVE", "PIVOT", "REWORK"])
    p_coord_deliver.add_argument("--delta", default=None, help="U141-A: what changed; an ACTIONABLE letter needs one")
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
    p_coord_presence.add_argument("--say", choices=["json", "brief", "none", "empty-json", "p1", "agy"], default="json",
                                  help="What to print: presence JSON (default), one context line, nothing, {}, "
                                       "p1 = one line only when a P1 wake waits and Codex is not ACTIVE (U38), or "
                                       "agy = Antigravity injectSteps JSON on a turn's first call when its line "
                                       "changed, else {} (U95-A)")
    # U103: the delta hook ran only for Claude and only in one project; each tool's hook now asks for its own.
    p_coord_presence.add_argument("--delta", action="store_true", default=False,
                                  help="With --from-hook: add what the other tools changed since this tool last looked")
    # U105: Claude and Codex mid-turn hooks pass --post-tool to print PostToolUse JSON context.
    p_coord_presence.add_argument("--post-tool", action="store_true", default=False,
                                  help="With --from-hook: print the line as PostToolUse JSON "
                                       "hookSpecificOutput.additionalContext (Claude, Codex mid-turn), "
                                       "nothing when there is no news (U105)")
    # U57-D: the acting conductor had to write a Codex quota lease through Python (2026-09-27); the lease itself
    # (U47-A1b) already existed in presence.mark, only the flag was missing.
    p_coord_presence.add_argument("--lease", action="store_true", default=False,
                                  help="Record a capability lease that ordinary heartbeats cannot overwrite until --ttl")
    # U148: a hook never moves an OK Antigravity desk (Codex review); this explicit registration does.
    p_coord_presence.add_argument("--desk-thread", default=None,
                                  help="U148: record this Antigravity desktop conversation id as the user's desk")
    p_coord_presence.set_defaults(func=cmd_coord_presence)

    p_coord_watch = p_coord_subs.add_parser("watch", help="Block until a new mailbox letter for a target arrives")
    p_coord_watch.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_watch.add_argument("--target", action="append", required=True, choices=["codex", "claude", "antigravity"])
    p_coord_watch.add_argument("--timeout", type=float, default=4 * 3600.0, help="Seconds before exit 3 (default: 4 h)")
    p_coord_watch.add_argument("--interval", type=float, default=30.0, help="Seconds between inbox scans (default: 30)")
    p_coord_watch.add_argument("--wakes-session", action="store_true",
                               help="U117: this watch runs as a background task whose exit wakes its session")
    # U141-A: structured (default) wakes only on an ACTIONABLE letter, once per letter, one watcher per target.
    p_coord_watch.add_argument("--policy", default="structured", choices=["structured", "legacy"])
    p_coord_watch.set_defaults(func=cmd_coord_watch)

    # U146-A: the nonstop chain. `next` names the tool's next card, `stop-gate` is the Claude Stop hook, and
    # `push-check` reads the user's standing push grant.
    p_coord_next = p_coord_subs.add_parser("next", help="Print the next card for a tool from the master schedule")
    p_coord_next.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_next.add_argument("--tool", required=True, choices=["codex", "claude", "antigravity"])
    p_coord_next.add_argument("--claim", action="store_true", help="Claim the own NEXT card so no other session runs it")
    p_coord_next.add_argument("--session", default=None, help="Session id that owns the claim (U146a-R: required to claim)")
    p_coord_next.set_defaults(func=cmd_coord_next)
    p_coord_stop = p_coord_subs.add_parser("stop-gate", help="Stop hook: block a turn end while an own NEXT card is ready")
    p_coord_stop.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_stop.add_argument("--tool", required=True, choices=["codex", "claude", "antigravity"])
    p_coord_stop.set_defaults(func=cmd_coord_stop_gate)
    p_coord_push = p_coord_subs.add_parser("push-check", help="ALLOW or DENY a push under .coord/grants/push.json")
    p_coord_push.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_push.add_argument("--branch", required=True)
    p_coord_push.add_argument("--force", action="store_true", help="The push would be forced (always DENY)")
    p_coord_push.set_defaults(func=cmd_coord_push_check)

    p_coord_route = p_coord_subs.add_parser("route", help="Choose the sole authority from fresh presence states")
    p_coord_route.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_route.set_defaults(func=cmd_coord_route)
    p_coord_collect = p_coord_subs.add_parser(
        "usage-collect", help="Find usage rows left only in linked worktrees; --apply appends them to the desk ledger")
    p_coord_collect.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_collect.add_argument("--apply", action="store_true", help="Append the orphan rows (default: dry run)")
    p_coord_collect.set_defaults(func=cmd_coord_usage_collect)
    p_coord_session = p_coord_subs.add_parser(
        "usage-session", help="Record a Claude Code transcript's or Codex rollout's tokens since its last recorded window (U73, U74)")
    p_coord_session.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_session.add_argument("--transcript", required=True, help="The Claude Code transcript .jsonl or Codex rollout-*.jsonl; the actor is read from its format")
    p_coord_session.add_argument("--work-id", required=True, help="Card the recorded window is attributed to")
    p_coord_session.add_argument("--apply", action="store_true", help="Append the row (default: dry run)")
    p_coord_session.set_defaults(func=cmd_coord_usage_session)

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
    p_coord_inbox.add_argument("--all", action="store_true",
                               help="List routine RUN notices too, with full summaries (U97-I)")
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
    # U114: one process (card) = one named window per tool; the manual's content is the window's first prompt.
    p_coord_win = p_coord_subs.add_parser("window", help="Open (or reuse) the card's dedicated window in one tool")
    p_coord_win.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_win.add_argument("--card", required=True, help="Card id, e.g. U114")
    p_coord_win.add_argument("--tool", required=True, choices=["codex", "claude", "antigravity", "auto"],
                             help="auto (U129): the clickless route, Codex (ACTIVE) -> idle Claude session -> agy -p")
    p_coord_win.add_argument("--title", required=True, help="Window title after [card]")
    p_coord_win.add_argument("--prompt-file", required=False, default=None,
                             help="Manual whose content opens the window (codex, antigravity)")
    p_coord_win.add_argument("--session-id", default=None,
                             help="U129: id of a visible Claude desktop session to record (claude only)")
    p_coord_win.add_argument("--release", action="store_true",
                             help="U129: mark the card's window done so its Claude session can take the next card")
    p_coord_win.set_defaults(func=cmd_coord_window)

    # U130: one card template (four stage slots with default workers) and an audit of the card's Ollama/Antigravity use.
    p_card = subparsers.add_parser("card", help="U130 default card pipeline: new, claim, skip, audit")
    p_card_subs = p_card.add_subparsers(dest="card_subcommand", required=True)
    p_card_new = p_card_subs.add_parser(
        "new", help="Write the card manual from the four-stage template (never overwrites)")
    p_card_new.add_argument("--title", required=True)
    p_card_new.set_defaults(func=cmd_card_new)
    p_card_claim = p_card_subs.add_parser(
        "claim", help="Copy this session's real Ollama MCP calls since the card opened into the ledger")
    p_card_claim.add_argument("--session", required=True, help="Session id in the Ollama usage log")
    p_card_claim.add_argument("--olla-log", default=None, help="Ollama MCP usage log (default ~/.cache/olla/usage.jsonl)")
    p_card_claim.set_defaults(func=cmd_card_claim)
    p_card_skip = p_card_subs.add_parser(
        "skip", help="Record a skipped ollama/agy slot with its checked reason and evidence")
    p_card_skip.add_argument("--slot", required=True, choices=["ollama", "agy"])
    p_card_skip.add_argument("--reason", required=True, choices=["OLLAMA_DOWN", "AGY_LIMITED", "TASK_CLASS"])
    p_card_skip.add_argument("--evidence", required=True)
    p_card_skip.set_defaults(func=cmd_card_skip)
    p_card_audit = p_card_subs.add_parser("audit", help="Exit 1 unless the card shows Ollama and Antigravity evidence")
    p_card_audit.add_argument("--code-path", action="append", default=None,
                              help="Changed file; a .py path voids a TASK_CLASS skip of the ollama slot")
    p_card_audit.set_defaults(func=cmd_card_audit)
    for p_card_cmd in (p_card_new, p_card_claim, p_card_skip, p_card_audit):
        p_card_cmd.add_argument("--project", default=".", help="Project root (default: .)")
        p_card_cmd.add_argument("--card", required=True, help="Card id, e.g. U130")
    # U135: the card's last step writes its RESULT line in its own checkout; the user window collects them all.
    p_card_result = p_card_subs.add_parser(
        "result", help="Write .coord/results/<card>.md in this checkout and print the RESULT line for the user window")
    p_card_result.add_argument("--project", default=".", help="This card's checkout (a worktree too; default: .)")
    p_card_result.add_argument("--card", required=True, help="Card id, e.g. U135")
    p_card_result.add_argument("--pr", required=True, help="Pull request URL")
    p_card_result.add_argument("--mergeable", required=True, choices=["yes", "no"])
    p_card_result.add_argument("--tests", required=True, help="<run>/<fail>, e.g. 1590/0")
    p_card_result.add_argument("--blocker", default="none", help="none, or one line naming the blocker")
    p_card_result.set_defaults(func=cmd_card_result)
    p_card_results = p_card_subs.add_parser(
        "results", help="List the RESULT lines of the main checkout and every worktree (newest per card)")
    p_card_results.add_argument("--project", default=".", help="Any checkout of the project (default: .)")
    p_card_results.set_defaults(func=cmd_card_results)

    # rsi: evidence-gated self-improvement (docs/38). observe → propose → try → gate → judge → rollback.
    p_rsi = subparsers.add_parser("rsi", help="Evidence-gated self-improvement: report, propose, gate, adopt, rollback")
    p_rsi_subs = p_rsi.add_subparsers(dest="rsi_subcommand", required=True)
    p_rsi_report = p_rsi_subs.add_parser("report", help="Per-worker pass/rework/blocked rates and recurring causes")
    p_rsi_report.add_argument("--project", default=".")
    p_rsi_report.set_defaults(func=cmd_rsi_report)
    p_rsi_savings = p_rsi_subs.add_parser(
        "savings", help="Paid-token savings from matched controlled pairs only; UNMEASURED below 10 (U76-A, read only)")
    p_rsi_savings.add_argument("--project", default=".")
    p_rsi_savings.set_defaults(func=cmd_rsi_savings)
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
                     target=args.target, thread=args.thread, card=args.card,
                     wake_class=getattr(args, "wake_class", None),
                     verdict_requested=getattr(args, "verdict_requested", None),
                     verdict=getattr(args, "verdict", None), delta=getattr(args, "delta", None))
    # U57-C: QUEUED_INTERACTIVE means a live `coord watch` holds the letter for the interactive session; not a failure.
    # U74-D: QUEUED_ACK_ONLY is an ACK_ONLY letter left in the inbox without a paid turn; also not a failure.
    # U134-C: QUEUED_UNTIL_ACTIVE waits for the target's next ACTIVE turn; also not a failure.
    ok = result.reason in ("PUBLISHED", "DISPATCHED", "ACKED", "QUEUED_INTERACTIVE", "QUEUED_ACK_ONLY",
                           "QUEUED_UNTIL_ACTIVE")
    print(json.dumps({"ok": ok, "target": result.target, "reason": result.reason,
                      "message_id": result.message_id, "digest": result.digest,
                      "receipt": result.receipt, "output": result.output[:500]}, ensure_ascii=False))
    return 0 if ok else 1


def cmd_coord_window(args: argparse.Namespace) -> int:
    """U114: exit 0 with the window id, 2 when the tool is LIMITED/ABSENT or, U129, Claude has no idle visible session.

    U129 (2026-10-02): `--tool auto` takes the clickless route (Codex ACTIVE -> idle visible Claude session -> Antigravity
    headless); `--release` frees a card's window so its Claude desktop session can take the next card.
    """
    from .coord import windows

    project = Path(args.project)
    if args.release:
        if args.tool == "auto":
            print(json.dumps({"error": "--release needs --tool codex, claude or antigravity"}, ensure_ascii=False))
            return 2
        result = windows.release_window(project, args.card, args.tool)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["released"] else 2
    route = windows.route_window(project, args.card, session_id=args.session_id) if args.tool == "auto" else None
    tool = route["route"] if route else args.tool
    if tool != "claude" and not args.prompt_file:
        print(json.dumps({"error": f"--prompt-file is required for {tool}"}, ensure_ascii=False))
        return 2
    prompt = Path(args.prompt_file).read_text(encoding="utf-8") if args.prompt_file else ""
    if args.prompt_file:
        from .card_pipeline import missing_slots

        gaps = missing_slots(prompt)
        if gaps:  # U130: a free-form manual skips the research/MIA/execute/verify slots and their default workers
            print(json.dumps({"error": "MANUAL_MISSING_SLOTS", "missing_slots": gaps,
                              "fix": f"uaos card new --card {args.card} --title <title>"}, ensure_ascii=False))
            return 2
    # U129: a Claude window is a visible desktop session the caller names; nothing is launched for it.
    passes_session = args.session_id is not None and (route is None or tool == "claude")
    extra = {"session_id": args.session_id} if passes_session else {}
    result = windows.open_window(project, args.card, tool, args.title, prompt, **extra)
    if route:
        result = {**result, "route": tool, "step": route["step"]}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("id") else 2


def _card_desk(args: argparse.Namespace) -> Path:
    """U130: card records and the ledger live on the shared desk (the main checkout), like `coord presence`."""
    from .coord.hook_context import shared_desk

    return Path(shared_desk(args.project))


def cmd_card_new(args: argparse.Namespace) -> int:
    from . import card_pipeline

    try:
        result = card_pipeline.new_manual(_card_desk(args), args.card, args.title)
    except ValueError as exc:
        _print_json({"ok": False, "error": str(exc)})
        return 2
    _print_json({"ok": True, **result})
    return 0


def cmd_card_claim(args: argparse.Namespace) -> int:
    from . import card_pipeline

    olla_log = Path(args.olla_log) if args.olla_log else Path.home() / ".cache" / "olla" / "usage.jsonl"
    try:
        result = card_pipeline.claim(_card_desk(args), args.card, args.session, olla_log)
    except ValueError as exc:
        _print_json({"ok": False, "error": str(exc)})
        return 2
    _print_json(result)
    return 0 if result.get("ok") else 1


def cmd_card_skip(args: argparse.Namespace) -> int:
    from . import card_pipeline

    try:
        result = card_pipeline.skip(_card_desk(args), args.card, args.slot, args.reason, args.evidence)
    except ValueError as exc:
        _print_json({"ok": False, "error": str(exc)})
        return 2
    _print_json(result)
    return 0 if result.get("ok") else 1


def cmd_card_audit(args: argparse.Namespace) -> int:
    from . import card_pipeline
    from .pilot_dirs import discover

    try:
        result = card_pipeline.audit(_card_desk(args), args.card, code_paths=args.code_path or (),
                                     run_dirs=discover(Path(args.project)))
    except ValueError as exc:
        _print_json({"ok": False, "error": str(exc)})
        return 2
    _print_json(result)
    return 0 if result["ok"] else 1


def cmd_card_result(args: argparse.Namespace) -> int:
    """U135: written in this checkout, never the shared desk, because a card worktree may not write the base."""
    from . import card_pipeline

    try:
        result = card_pipeline.write_result(Path(args.project), args.card, args.pr, args.mergeable, args.tests,
                                            args.blocker)
    except ValueError as exc:
        _print_json({"ok": False, "error": str(exc)})
        return 2
    _print_json(result)
    return 0


def cmd_card_results(args: argparse.Namespace) -> int:
    from . import card_pipeline

    _print_json({"ok": True, "results": card_pipeline.collect_results(Path(args.project))})
    return 0


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


def _sentinel_loop_owner(pid_file: Path, interval: float) -> int:
    """Pid of a live sentinel loop holding pid_file, else 0. U122: Windows reuses pids, so only a file the loop
    rewrote within three cycles (floor 180 s; one tick took up to 8 s) counts; an older one is stale."""
    from .coord.sentinel import _is_pid_alive
    import time
    try:
        running = int(pid_file.read_text(encoding="utf-8").strip())
        age = time.time() - pid_file.stat().st_mtime
    except (OSError, ValueError):
        return 0
    return running if age < max(180.0, 3 * interval) and running != os.getpid() and _is_pid_alive(running) else 0


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
        pid_file = project / ".work" / "sentinel" / "loop.pid"
        running = _sentinel_loop_owner(pid_file, args.interval)
        if running:
            _report({"ok": True, "skipped": "ALREADY_RUNNING", "pid": running})
            return 0
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        while True:
            # A resident operator must outlive one bad cycle (locked file, corrupt line); it reports and goes on.
            try:
                pid_file.write_text(str(os.getpid()), encoding="utf-8")  # U122: each cycle refreshes the heartbeat
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
    from .coord.presence import conductor, hook_turn_start, mark, read_all

    say = getattr(args, "say", "json")

    shown = {"user": "", "event": ""}  # U147: the in-app line for 윤겸스 and the hook event that carries it

    def _emit(data: dict[str, Any], line: str = "") -> None:
        user = shown["user"]
        if getattr(args, "post_tool", False):
            # U105: plain stdout on PostToolUse never reaches the model; only this JSON does
            out: dict[str, Any] = {"systemMessage": user} if user else {}
            if line:
                out["hookSpecificOutput"] = {"hookEventName": "PostToolUse", "additionalContext": line}
            if out:
                print(json.dumps(out, ensure_ascii=False))
            return
        if user and say in ("brief", "p1", "none"):
            # U147: Claude Code and Codex show `systemMessage` to the user, not the model (0 tokens); the model's
            # line moves into additionalContext, which these hooks read like plain stdout.
            out = {"systemMessage": user}
            if line:
                out["hookSpecificOutput"] = {"hookEventName": shown["event"] or "UserPromptSubmit",
                                             "additionalContext": line}
            print(json.dumps(out, ensure_ascii=False))
        elif say == "json":
            print(json.dumps(data, ensure_ascii=False))
        elif say in ("brief", "p1", "none") and line:
            print(line)
        elif say == "empty-json":
            print("{}")
        elif say == "agy":
            # Antigravity reads one JSON object on stdout; a skip, an error or an unchanged line prints {}.
            print(json.dumps({"injectSteps": [{"ephemeralMessage": line}]}, ensure_ascii=False) if line else "{}")

    if getattr(args, "desk_thread", None) is not None:
        from .coord import desk_sync
        from .coord.deliver import agy_desktop_conversation

        # Only a conversation of the Antigravity desktop app can be the user's Antigravity desk. U163: the peers hear
        # it. This explicit command alone repairs an unreadable record (U148); the bytes are kept as `.corrupt`.
        try:
            ok = args.tool == "antigravity" and agy_desktop_conversation(args.desk_thread) \
                and desk_sync.designate(Path(args.project), "antigravity", args.desk_thread, source="explicit",
                                        repair=True)
        except (OSError, ValueError):
            ok = False
        print(json.dumps({"ok": bool(ok), "tool": args.tool, "desk_thread": args.desk_thread}))
        return 0 if ok else 2
    if getattr(args, "from_hook", False):
        from .coord.hook_context import (
            agy_line,
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
            if args.tool:
                # U147-D: the user's desk is set before mark(dispatch=True), so letters queued for the old desk go to the
                # new one (Codex relay_48fb8d38). U163: only a fresh explicit declaration designates (relay_69611232);
                # the peers see the change in their own desk delta.
                try:
                    from .coord import desk_sync
                    from .coord.deliver import agy_desktop_conversation

                    event = json.loads(stdin_text) if stdin_text.strip() else {}
                    if isinstance(event, dict):
                        desk_sync.on_hook(project, args.tool, event, hook_session(stdin_text) or "")
                    if args.tool == "antigravity" and isinstance(event, dict) \
                            and event.get("invocationNum", 0) == 0 \
                            and agy_desktop_conversation(event.get("conversationId")):
                        # U148: Antigravity has no UserPromptSubmit, and nothing in its PreInvocation payload proves
                        # a human turn (Codex review: subagents, restarts and continuations look the same), so the
                        # hook never writes the desk; coord presence --desk-thread does (U148-C2). The key names
                        # (never values) are the evidence a future human-origin field would need.
                        keys = project / ".coord" / "presence" / "agy_hook_keys.json"
                        keys.parent.mkdir(parents=True, exist_ok=True)
                        keys.write_text(json.dumps(sorted(event)), encoding="utf-8")
                except Exception:  # noqa: BLE001 - a hook never fails the session
                    pass
            window_line = ""
            # U154: only the per-prompt hook global_install writes (`--delta`, all 3 tools) runs U150. Claude's project
            # hook has no --delta and got byte-identical stdin, so it recorded every prompt a second time.
            if args.tool and args.delta:
                # U150-C: a declared user window gets `[사용자 대화창구-YYMMDD-N]` in its own tool's UI. Claude and
                # Codex hand the typed prompt; Antigravity's first invocation names its transcript instead.
                try:
                    from .coord.user_window import on_prompt

                    event = json.loads(stdin_text) if stdin_text.strip() else {}
                    event = event if isinstance(event, dict) else {}
                    prompt = event.get("prompt") if event.get("hook_event_name") == "UserPromptSubmit" else None
                    thread = hook_session(stdin_text) or ""
                    if args.tool == "antigravity" and event.get("invocationNum", 0) == 0 \
                            and event.get("transcriptPath"):
                        from .coord.codex_session_bridge import parse_transcript_to_turns

                        turns = parse_transcript_to_turns(Path(str(event["transcriptPath"])))
                        prompt = turns[-1][0] if turns else None
                        thread = str(event.get("conversationId") or "")
                    window_line = on_prompt(project, args.tool, thread, prompt)
                    # U150-B: an error report reaches the other two tools; a repeat of it becomes P1.
                    from .coord.repeat_error import on_prompt as error_lines

                    window_line = "\n".join(p for p in (window_line, error_lines(project, args.tool, prompt)) if p)
                except Exception:  # noqa: BLE001 - a hook never fails the session
                    window_line = ""
            if args.tool and args.state:
                # U58: the hook payload names its session, so one session ending leaves the others at the desk.
                # U134: a turn start clears a stale LIMITED/ABSENT lease; an ACTIVE beat sends queued letters.
                mark(project, args.tool, args.state, ttl_s=args.ttl, session=hook_session(stdin_text),
                     turn_start=hook_turn_start(stdin_text) and not getattr(args, "post_tool", False), dispatch=True)
            presence = read_all(project)
            if say == "agy":
                line = agy_line(project, presence, stdin_text)
            else:
                line = p1_line(project, presence) if say == "p1" else brief_line(project, presence)
            if say == "brief":
                alert = retention_alert(project)
                if retention_alert_is_new(project, alert):
                    line = line + " " + alert
            elif say == "p1" and not p1_is_new(project, line):
                line = ""  # U46-P1: an unchanged P1 set is ACK_ONLY; it was repeated on every prompt
            if say == "none":
                line = ""  # `none` prints nothing of its own; only a U103 desk delta may speak
            ack = None
            if getattr(args, "delta", False) and args.tool:
                from .coord.desk_delta import prepare_delta

                event = json.loads(stdin_text) if stdin_text.strip() else {}
                event = event if isinstance(event, dict) else {}
                # U105: removed first-call limit (invocationNum 0) so a letter arriving mid-turn is heard at next call
                session = hook_session(stdin_text) or str(event.get("conversationId") or "") or None
                # U141-A: the cursor and the wake receipts advance only after the output below was written.
                text, ack = prepare_delta(project, args.tool, session)
                line = "\n".join(part for part in (line, text) if part)
                if say != "agy":  # Antigravity's user-visible hook field is UNKNOWN; its line stays model-facing
                    from .coord.board import letters_in, line_is_new, status_line

                    try:  # the in-app line must never cost the model its desk delta
                        user = status_line(project, args.tool, letters_in(text))
                        if line_is_new(project, args.tool, user):
                            shown["user"], shown["event"] = user, str(event.get("hook_event_name") or "")
                    except Exception:  # noqa: BLE001
                        pass
            line = "\n".join(part for part in (window_line, line) if part)
            _emit({"ok": True, "project": str(project), "presence": presence, "conductor": conductor(presence)}, line)
            if ack is not None:
                try:
                    ack()
                except Exception:  # noqa: BLE001 - a failed ack shows the same letters again next time; never a crash
                    pass
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
        # U134-R F3: a hand-written lease is `manual`, so the tool's next real turn start may clear it.
        lease = getattr(args, "lease", False)
        mark(project, args.tool, args.state, ttl_s=args.ttl, lease=lease, lease_source="manual" if lease else "")
    presence = read_all(project)
    _emit({"ok": True, "presence": presence, "conductor": conductor(presence)})
    return 0


def cmd_coord_watch(args: argparse.Namespace) -> int:
    """U57-B: wait at zero model tokens until a new letter for one of the targets lands; exit 3 on timeout."""
    from .coord.watch import watch

    found = watch(Path(args.project), tuple(args.target), timeout_s=args.timeout, interval_s=args.interval,
                  wakes_session=args.wakes_session, policy=getattr(args, "policy", "structured"))
    if found is not None and found.get("state") == "ALREADY_WATCHING":
        # U141-A: one watcher per target; a second one exits instead of waking the session a second time.
        print(json.dumps({"ok": False, "reason": "ALREADY_WATCHING", **found}, ensure_ascii=False))
        return 4
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


def cmd_coord_usage_session(args: argparse.Namespace) -> int:
    """U73: one ledger row for the session tokens spent since the last recording. Transcript-only, no model call."""
    from .coord.session_usage import record_session
    from .coord.usage_ledger import UsageRejected

    try:
        result = record_session(Path(args.project), Path(args.transcript), work_id=args.work_id, apply=args.apply)
    except (UsageRejected, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


def cmd_coord_next(args: argparse.Namespace) -> int:
    """U146-A: print the next card for a tool from the master schedule (read-only unless --claim)."""
    from .coord.next_card import next_step
    print(json.dumps(next_step(Path(args.project), args.tool, claim=args.claim, session=args.session),
                     ensure_ascii=False))
    return 0


def cmd_coord_stop_gate(args: argparse.Namespace) -> int:
    """U146-A: the Claude Stop hook. A broken gate never breaks the session, so every failure exits 0 silently."""
    try:
        try:
            hook = json.loads(sys.stdin.read() or "{}")
        except ValueError:
            hook = {}
        # U146a-R: the hook input's session_id owns the claim; without one the gate claims nothing and allows the stop.
        session = hook.get("session_id") if isinstance(hook, dict) else None
        from .coord.stop_gate import gate
        result = gate(Path(args.project), args.tool, session=session if isinstance(session, str) else None)
        if isinstance(result, dict):
            print(json.dumps(result, ensure_ascii=False))
    except Exception:  # noqa: BLE001 - fail open: the stop is allowed
        pass
    return 0


def cmd_coord_push_check(args: argparse.Namespace) -> int:
    """U146-A R2: deny-by-default push grant check."""
    from .coord.stop_gate import push_check
    result = push_check(Path(args.project), args.branch, force=args.force)
    print(json.dumps(result, ensure_ascii=False))
    # Exit 3 on DENY: a non-zero exit stops a shell `&&` chain before `git push`.
    return 0 if result.get("decision") == "ALLOW" else 3


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


# U97-I: pilot RUN notices go to the tool that ran the pilot, and the prompt hook already relays them; listing them
# made the start-of-session inbox 80,966 bytes (298 of 480 letters). They are counted, never acked or moved.
INBOX_ROUTINE_KINDS = frozenset({"RUN"})
# 200 characters keep a letter's who/what/verdict; the full text stays in the letter and under `--all`.
INBOX_SUMMARY_LIMIT = 200


def cmd_coord_inbox(args: argparse.Namespace) -> int:
    """U32b: list what waits in the voicemail without claiming it (U97-I: routine RUN notices only counted)."""
    from .coord.mailbox import Mailbox

    mailbox_dir = Path(args.project) / ".coord" / "mailbox"
    if not mailbox_dir.is_dir():
        print(json.dumps({"ok": True, "messages": [], "bad": []}, ensure_ascii=False))
        return 0
    box = Mailbox(mailbox_dir)
    show_all = bool(getattr(args, "all", False))
    messages = []
    routine: dict[str, int] = {}
    for message_id, payload in box.peek():
        data = payload if isinstance(payload, dict) else {}
        kind = data.get("kind") or ("P1" if data.get("p1_alert") else None)
        if kind in INBOX_ROUTINE_KINDS and not show_all:
            routine[kind] = routine.get(kind, 0) + 1
            continue
        summary = data.get("summary") or data.get("wake_reason")
        if not show_all and isinstance(summary, str) and len(summary) > INBOX_SUMMARY_LIMIT:
            summary = summary[:INBOX_SUMMARY_LIMIT] + "…"
        messages.append({"id": message_id, "kind": kind, "step": data.get("step"), "summary": summary})
    result: dict[str, Any] = {"ok": True, "messages": messages, "bad": box.list_bad()}
    if routine:
        result["routine_counted"] = routine  # listed in full with --all
    print(json.dumps(result, ensure_ascii=False))
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


def cmd_rsi_savings(args: argparse.Namespace) -> int:
    from .coord.token_savings import report

    _print_json(report(Path(args.project)))
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
    # U130: a release ships only for a card whose `card audit` shows Ollama and Antigravity evidence.
    from . import card_pipeline
    from .coord.hook_context import shared_desk
    from .pilot_dirs import discover

    card = str(packet.get("card") or str(packet.get("work_id", "")).split("-")[0])
    if not card_pipeline.CARD_RE.fullmatch(card):
        _print_json({"ok": False, "error": 'CARD_AUDIT: name the card in the packet ("card": "U##")'})
        return 1
    audit = card_pipeline.audit(Path(shared_desk(project)), card, code_paths=packet.get("changed_files", []),
                                run_dirs=discover(project))
    if not audit["ok"]:
        _print_json({"ok": False, "error": f"CARD_AUDIT: {card} has no {', '.join(audit['missing'])} evidence",
                     "audit": audit})
        return 1
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
