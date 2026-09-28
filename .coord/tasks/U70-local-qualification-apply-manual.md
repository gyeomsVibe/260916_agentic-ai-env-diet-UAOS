```contract
work_id: U70
worker: apply
goal: Refuse a typed local task before any Ollama call unless the exact model digest is QUALIFIED for that task type, count a repeated extraction item as a failure, and add a deterministic AST symbol lister
inputs:
- v7_harness/cli.py sha256=46ec38d7381472793e3621c0592756a89f68b7e88fc43c27cf52da9236c94d4b
- v7_harness/manual.py sha256=0eb8adcf1453576c2c69c478548401025903d0a9e419ecaaef9437e0bc5a6308
- v7_harness/model_qualification.py sha256=09a8e23c1627681be2bac5a39a3d2f7e6067ea4df6e7592120a80f414a5bfa41
allow:
- v7_harness/cli.py
- v7_harness/manual.py
- v7_harness/model_qualification.py
- v7_harness/symbols.py
- tests/test_u70_local_qualification.py
- docs/57_u70-local-task-qualification-gate.md
acceptance: python -m unittest tests.test_u70_local_qualification tests.test_u51_model_qualification tests.test_u69_admission_gate
forbidden: design changes; edits outside allow; weakening or deleting existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Card U70: U67-O1b sent a JSON extraction to an unqualified local model and duplicates scored as passes (94285bd: alpha x4 -> (4, 4)). The new tests fail on 94285bd (no QUALIFICATION_STORE). Judge claude (ACTING while Codex is LIMITED); Codex re-reviews. Write the six files below exactly.

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
===FILE: v7_harness/manual.py===
"""Work manuals as contracts: checked before a delegated run, enforced during it (U34).

A manual is one markdown file. It starts with a fenced ```contract block of `key: value` lines, followed by
free prose instructions for the worker. The pilot sends the whole file as the prompt (the content, never a path),
so the contract the harness enforces and the text the worker reads cannot drift apart.

Why a checker: the four-tool rules require every Ollama/Antigravity call to carry a manual with a work id, one goal,
pinned inputs, allowed files, forbidden actions, limits, an acceptance command, stop conditions and a judge. Those
manuals were prose, so nothing checked them, and the "allowed files" line was never enforced (a worker could change
any file and still pass). Every check here is deterministic and costs no model tokens.

    ```contract
    work_id: U35_EXAMPLE
    worker: local            # local | apply | agy | lane | cascade
    goal: Replace TIMEOUT = 30 with TIMEOUT = 60 in `pkg/config.py`.
    inputs:
    - pkg/config.py sha256=<64 hex>
    allow:
    - pkg/config.py
    acceptance: python -m unittest tests.test_config
    forbidden: design changes, edits outside allow, editing tests
    stop: two failures with the same cause; input hash mismatch
    judge: codex              # codex | claude | antigravity — never the worker's own tool, never ollama
    timeout_s: 180
    remote_budget_tokens: 0   # >0 only when a cascade may escalate to the paid remote worker
    ```
"""

from __future__ import annotations

import hashlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

CONTRACT_RE = re.compile(r"^```contract[ \t]*\r?\n(?P<body>.*?)^```", re.M | re.S)
REQUIRED = ("work_id", "worker", "goal", "inputs", "allow", "acceptance", "forbidden", "stop", "judge", "timeout_s")
# U50: context_allow is optional; without it a list key would swallow its "- " items into the previous list.
LIST_KEYS = ("inputs", "allow", "context_allow")
WORKERS = ("local", "apply", "agy", "lane", "cascade", "claude")
# Workers that spend a paid account (B85). lane runs Claude Code on the local model, so it is not one of them.
REMOTE_WORKERS = ("agy", "claude")
JUDGES = ("codex", "claude", "antigravity", "user")
# Workers that edit files with their own tools. The harness reads the staged files, never their reply text, so
# telling them to reply with blocks makes them change nothing (U44 probe: NO_CHANGES on the first real claude run).
TOOL_WORKERS = ("agy", "lane", "claude")
# The tool that does the work cannot be the one that accepts it.
WORKER_TOOL = {"agy": "antigravity", "lane": "claude", "claude": "claude"}
MAX_TIMEOUT_S = 3600
# docs/24·docs/30: a local model gets a manual that scores at least 80 for concreteness.
LOCAL_MIN_SPECIFICITY = 80
REMOTE_MIN_SPECIFICITY = 60
SHA_RE = re.compile(r"sha256[=:]\s*([0-9a-fA-F]{64})")


@dataclass
class ManualReport:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    contract: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "errors": self.errors, "warnings": self.warnings, "contract": self.contract}


def parse_contract(text: str) -> dict[str, Any] | None:
    match = CONTRACT_RE.search(text)
    if match is None:
        return None
    contract: dict[str, Any] = {}
    current_list: str | None = None
    for raw in match.group("body").splitlines():
        # A comment needs two spaces before "#", so "issue #12" inside a goal survives.
        line = re.sub(r"\s{2,}#.*$", "", raw).rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.startswith("- ") and current_list is not None:
            contract[current_list].append(stripped[2:].strip())
            continue
        key, sep, value = stripped.partition(":")
        if not sep:
            continue
        key = key.strip().lower()
        value = value.strip()
        if key in LIST_KEYS:
            contract[key] = [item.strip() for item in value.split(",") if item.strip()] if value else []
            current_list = key
        else:
            contract[key] = value
            current_list = None
    return contract


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_relative(item: str) -> bool:
    candidate = item.replace("\\", "/")
    return bool(candidate) and not candidate.startswith("/") and ".." not in PurePosixPath(candidate).parts \
        and not re.match(r"^[A-Za-z]:", candidate)


def related_tests(project: Path, allow: list[str]) -> list[str]:
    """Test modules that import an allowed .py file. P08's acceptance ran one new test and missed that
    tests/test_u15_coord_cli.py covered the command the worker deleted."""
    modules = []
    for item in allow:
        path = PurePosixPath(item.replace("\\", "/"))
        if path.suffix == ".py" and not path.name.startswith("test_") and "*" not in item:
            modules.append(".".join(path.with_suffix("").parts))
    tests_dir = Path(project) / "tests"
    if not modules or not tests_dir.is_dir():
        return []
    found = []
    for test in sorted(tests_dir.glob("test_*.py")):
        try:
            text = test.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if any(re.search(rf"\b{re.escape(module)}\b", text) for module in modules):
            found.append(f"tests.{test.stem}")
    return found


def lint(text: str, project: Path) -> ManualReport:
    from v7_harness.adapters.ollama_worker import dictated_paths
    from v7_harness.adapters.worker_advice import VAGUE_TERMS, advise

    project = Path(project)
    report = ManualReport(ok=False)
    contract = parse_contract(text)
    if contract is None:
        report.errors.append("NO_CONTRACT: the manual needs a ```contract block (see v7_harness/manual.py)")
        return report
    report.contract = contract

    for key in REQUIRED:
        value = contract.get(key)
        if value in (None, "", []):
            report.errors.append(f"MISSING:{key}")

    worker = contract.get("worker", "")
    judge = contract.get("judge", "").lower()
    if worker and worker not in WORKERS:
        report.errors.append(f"UNKNOWN_WORKER:{worker}")
    if judge and judge not in JUDGES:
        report.errors.append(f"JUDGE_NOT_ALLOWED:{judge} (Ollama and the worker never judge)")
    if worker in WORKER_TOOL and judge == WORKER_TOOL[worker]:
        report.errors.append(f"SELF_JUDGE:{judge} cannot accept work done by --worker {worker}")

    goal = contract.get("goal", "")
    vague = [term for term in VAGUE_TERMS if term in goal.lower()]
    if vague:
        report.errors.append(f"VAGUE_GOAL:{','.join(vague)}")
    if len(goal) > 400:
        report.errors.append("GOAL_TOO_LONG: one goal, one sentence")

    # U70: a task type names what the local model is asked to do, so the pilot can check its qualification first.
    task_type = contract.get("task_type", "")
    if task_type:
        from v7_harness.model_qualification import TASK_TYPES

        if task_type not in TASK_TYPES:
            report.errors.append(f"UNKNOWN_TASK_TYPE:{task_type} (known: {', '.join(TASK_TYPES)})")

    for item in contract.get("inputs", []):
        rel = item.split()[0] if item.split() else ""
        pinned = SHA_RE.search(item)
        target = project / rel
        if not _safe_relative(rel):
            report.errors.append(f"INPUT_ESCAPE:{rel}")
        elif not target.is_file():
            report.errors.append(f"INPUT_MISSING:{rel}")
        elif pinned is None:
            report.errors.append(f"INPUT_UNPINNED:{rel} (add sha256=<hex>)")
        elif pinned.group(1).lower() != _sha256(target):
            report.errors.append(f"INPUT_HASH_MISMATCH:{rel}")

    allow = contract.get("allow", [])
    for item in allow:
        if not _safe_relative(item) or item.strip() in ("*", "**"):
            report.errors.append(f"ALLOW_TOO_WIDE:{item}")
    # U50: a wildcard list would admit the whole workspace and undo the gate.
    for item in contract.get("context_allow", []):
        if not _safe_relative(item) or item.strip().replace("\\", "/") in ("*", "**", "*/", "**/", "**/*"):
            report.errors.append(f"CONTEXT_ALLOW_TOO_WIDE:{item}")

    try:
        timeout = int(contract.get("timeout_s", ""))
        if not 0 < timeout <= MAX_TIMEOUT_S:
            raise ValueError
    except ValueError:
        if contract.get("timeout_s"):
            report.errors.append(f"TIMEOUT_INVALID:{contract.get('timeout_s')}")
    budget_raw = contract.get("remote_budget_tokens", "0") or "0"
    try:
        budget = int(budget_raw)
        if budget < 0:
            raise ValueError
    except ValueError:
        budget = 0
        report.errors.append(f"BUDGET_INVALID:{budget_raw}")
    if worker == "cascade" and budget <= 0:
        report.errors.append("CASCADE_WITHOUT_BUDGET: set remote_budget_tokens or use worker: local")
    if worker in REMOTE_WORKERS and budget <= 0:
        # B85: an agy run with no budget spent 655,207 tokens and nothing compared it with anything.
        report.errors.append(f"REMOTE_WITHOUT_BUDGET: worker {worker} needs remote_budget_tokens > 0")
    if worker == "claude":
        # Codex audit: a pre-spend cap (`claude --max-budget-usd`). The token gate only acts after the money is spent.
        usd_raw = str(contract.get("remote_budget_usd") or "")
        try:
            usd = float(usd_raw) if usd_raw else 0.0
        except ValueError:
            usd = -1.0
        if usd <= 0 or usd != usd:
            report.errors.append("REMOTE_WITHOUT_USD_CAP: worker claude needs remote_budget_usd > 0")

    blocks = dictated_paths(text)
    if worker == "apply" and not blocks:
        report.errors.append("NO_BLOCKS_FOR_APPLY: worker apply needs ===FILE/===EDIT blocks in the manual")
    if blocks and allow:
        from v7_harness.isolation.errors import ScopeExpansionError
        from v7_harness.isolation.security import check_scope_confinement

        for path in blocks:
            try:
                check_scope_confinement(path, allow)
            except ScopeExpansionError:
                report.errors.append(f"BLOCK_OUTSIDE_ALLOW:{path}")
    if blocks and worker in ("local", "cascade"):
        report.warnings.append("DICTATION: the manual already contains the exact code; worker: apply does it with 0 tokens")

    # A forbidden line such as "no refactoring" names vague words on purpose; it must not lower the score.
    specificity = advise(re.sub(r"(?m)^\s*forbidden:.*$", "", text)).specificity
    # The thresholds can only tighten through an adopted RSI policy (floors 80/60 are enforced in v7_harness.rsi).
    from v7_harness.rsi import load_policy

    policy = load_policy(project)
    local_min = max(LOCAL_MIN_SPECIFICITY, int(policy["local_min_specificity"]))
    remote_min = max(REMOTE_MIN_SPECIFICITY, int(policy["remote_min_specificity"]))
    if worker in ("local", "cascade") and specificity < local_min:
        report.errors.append(f"LOW_SPECIFICITY:{specificity}<{local_min} for a local model")
    elif worker in ("agy", "lane") and specificity < remote_min:
        report.warnings.append(f"LOW_SPECIFICITY:{specificity}<{remote_min}")

    covering = related_tests(project, allow)
    acceptance = contract.get("acceptance", "")
    missing = [module for module in covering if module not in acceptance and "discover" not in acceptance]
    if missing:
        report.warnings.append(f"RELATED_TESTS_NOT_IN_ACCEPTANCE:{' '.join(missing[:6])}")

    report.ok = not report.errors
    return report


def new_manual(
    project: Path,
    *,
    work_id: str,
    worker: str,
    goal: str,
    inputs: list[str],
    allow: list[str],
    acceptance: str,
    judge: str,
    timeout_s: int = 180,
    remote_budget_tokens: int = 0,
    remote_budget_usd: float = 0.0,
    forbidden: str = "design changes; edits outside allow; editing or deleting tests; network; commit/push",
    stop: str = "two failures with the same cause; input hash mismatch; no output",
    instructions: str = "",
    context_allow: list[str] | None = None,
) -> str:
    """A manual skeleton with the input hashes computed now, so the worker is pinned to these exact bytes."""
    project = Path(project)
    pinned = [f"- {rel} sha256={_sha256(project / rel)}" for rel in inputs]
    lines = [
        "```contract",
        f"work_id: {work_id}",
        f"worker: {worker}",
        f"goal: {goal}",
        "inputs:",
        *pinned,
        "allow:",
        *[f"- {item}" for item in allow],
        *(["context_allow:", *[f"- {item}" for item in context_allow]] if context_allow is not None else []),
        f"acceptance: {acceptance}",
        f"forbidden: {forbidden}",
        f"stop: {stop}",
        f"judge: {judge}",
        f"timeout_s: {timeout_s}",
        f"remote_budget_tokens: {remote_budget_tokens}",
        *([f"remote_budget_usd: {remote_budget_usd:g}"] if remote_budget_usd > 0 else []),
        "```",
        "",
        "## Instructions for the worker",
        "",
        instructions or "- Change only the files under `allow`. Keep every other line byte-identical.",
        "",
        "## Output",
        "",
        output_rule(worker),
        "",
    ]
    return "\n".join(lines)


def output_rule(worker: str) -> str:
    if worker in TOOL_WORKERS:
        return ("- Edit the files under `allow` directly with your file tools. Your reply is not applied: ===FILE / "
                "===EDIT blocks in it are ignored. End with one line saying what you changed. Do not claim success; "
                "the acceptance command decides.")
    return "- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides."


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Lint a work manual")
    parser.add_argument("manual")
    parser.add_argument("--source", default=".")
    args = parser.parse_args(argv)
    report = lint(Path(args.manual).read_text(encoding="utf-8"), Path(args.source))
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
===FILE: v7_harness/model_qualification.py===
"""U51: task-specific model qualification gate bound to execution provenance. docs/49 §2·§5 U-MQ-1.

"The model runs in Ollama" is not "the model may do this task". A model is QUALIFIED per task type only when a
deterministic source check passes on outputs that this module itself obtained from the provider, and the verdict is
tied to the digest the provider reports, not to a name somebody typed.

Two commands, two kinds of evidence (Codex U51-R1b verdict: a hand-made output file scored under any typed identity
forged a QUALIFIED record):
- `score`   scores existing output files. Evidence kind SCORER_ONLY: it prints, it never records, and it takes no
            provider, model or digest, so no identity can be attached to outputs it did not see produced.
- `qualify` calls the provider itself for every source, reads the model digest from the provider before and after the
            run, hashes source, prompt and output into one receipt per call, scores those outputs and only then
            records. A typed --expect-digest that differs from the provider's digest is refused (IDENTITY_MISMATCH).
`lookup` accepts only records that carry receipts for the asked digest.

Limit, stated: a record file is still plain JSON in the user's own account; someone who edits it by hand can forge
it (B83: a label in the same account is not authentication). The gate stops the tool path from minting a verdict for
a model that never ran; it does not defend against the account owner.

Usage: python -m v7_harness.model_qualification qualify --model qwen3.5-32k --sources <dir> --record <dir>
       python -m v7_harness.model_qualification score --runs <dir> --sources <dir> [--pattern art*.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

# A task type is QUALIFIED when at least this share of items passes the source check. 0.8 = at most one item in five
# is thrown away by the independent gate; below that the checking and rework cost more than the local call saves.
# Initial value, to be re-tuned after three fixture runs (docs/49 §5 U-MQ-1).
QUALIFY_MIN = 0.8
# Fewer checked items than this cannot qualify: one lucky pass out of two says nothing about the model.
MIN_ITEMS = 20
TASK_TYPES = ("list_extract", "verbatim_quote")
# Another writer holds the target only for the length of its own replace (milliseconds), so 50 tries x 10 ms
# bounds the wait at 0.5 s before the error surfaces.
REPLACE_TRIES = 50
REPLACE_WAIT_S = 0.01
STATUSES = ("QUALIFIED", "REJECTED", "UNQUALIFIED", "UNQUALIFIED_DIGEST_CHANGED")
EVIDENCE = "PROVENANCE_BOUND"
# Each source asks for at most this many items; an output that does not parse counts as this many failed items, so a
# broken answer lowers the share instead of shrinking the denominator.
MAX_CANDIDATES = 6
# The docs/49 extraction contract (.work/article_ollama_20260927/extract.py), reduced to the two scored fields.
EXTRACT_PROMPT = """TASK: extract, do not judge. Output one JSON object only:
{{"candidates": [{{"name": str (the item's name as written in the document), "quote": str (EXACT substring copied from
the document, 10-80 chars)}}] (max {m})}}
Forbidden: inventing text not in the document; paraphrasing inside "quote".
Every name and quote is checked as a literal substring of the document by an independent script.

DOCUMENT (sha256={h}):
{text}"""
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
# One article of ~20 KB Korean took up to 72 s in docs/49; 900 s leaves room for a cold model load.
CALL_TIMEOUT_S = 900


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def candidate_key(name: str) -> str:
    """The item name without the model's appended explanation ("C09 — Firewall" -> "C09", "X :: y" -> "X")."""
    return re.split(r" — | ::", name or "")[0].strip()


def score_extraction(candidates: list[dict[str, Any]], source_text: str) -> dict[str, tuple[int, int]]:
    """Per task type: (items passing the literal source check, items checked)."""
    flat = _norm(source_text)
    names = [candidate_key(str(c.get("name") or "")) for c in candidates]
    quotes = [_norm(str(c.get("quote") or "")) for c in candidates]

    def passed(items: list[str], haystack: str) -> int:
        # U70: a repeated item is a failed item. U67-O1b answered with duplicates, and each copy of a true item used
        # to count as another pass, so repeating one easy line could lift a model over QUALIFY_MIN.
        seen: set[str] = set()
        count = 0
        for item in items:
            if item and item not in seen and item in haystack:
                count += 1
            seen.add(item)
        return count

    return {
        "list_extract": (passed(names, source_text), len(names)),
        "verbatim_quote": (passed(quotes, flat), len(quotes)),
    }


def score_output(output: str, source_text: str) -> dict[str, tuple[int, int]]:
    """Score one raw model answer; an answer without a candidates list fails MAX_CANDIDATES items per task."""
    try:
        data = json.loads(output)
        candidates = data.get("candidates") if isinstance(data, dict) else None
    except json.JSONDecodeError:
        candidates = None
    if not isinstance(candidates, list):
        return {t: (0, MAX_CANDIDATES) for t in TASK_TYPES}
    return score_extraction([c for c in candidates if isinstance(c, dict)], source_text)


def verdict(passed: int, total: int) -> str:
    if total < MIN_ITEMS:
        return "UNQUALIFIED"
    return "QUALIFIED" if passed / total >= QUALIFY_MIN else "REJECTED"


def score_fixture(runs_dir: Path, sources_dir: Path, pattern: str = "art*.json") -> dict[str, Any]:
    """SCORER_ONLY: score saved outputs against their sources. The result names no model and is never recorded."""
    totals = {t: [0, 0] for t in TASK_TYPES}
    files = sorted(Path(runs_dir).glob(pattern))
    if not files:
        raise ValueError(f"NO_FIXTURE: no {pattern} in {runs_dir}")
    for path in files:
        run = json.loads(path.read_text(encoding="utf-8"))
        meta, data = run["meta"], run.get("data") or {}
        # The pin is the sha256 of the text as Python reads it (newlines normalised to \n), the same text the model
        # was given, so a CRLF checkout of an unchanged document still matches.
        text = (Path(sources_dir) / meta["file"]).read_text(encoding="utf-8")
        if _sha(text) != meta["sha256"]:
            raise ValueError(f"SOURCE_HASH_MISMATCH:{meta['file']}")
        candidates = data.get("candidates") if isinstance(data, dict) else None
        for task, (ok, n) in score_extraction(candidates or [], text).items():
            totals[task][0] += ok
            totals[task][1] += n
    return {"evidence": "SCORER_ONLY", "items": len(files),
            "tasks": {t: {"passed": p, "total": n, "verdict": verdict(p, n)} for t, (p, n) in totals.items()}}


class Provider(Protocol):
    name: str

    def digest(self, model: str) -> str | None: ...

    def generate(self, model: str, prompt: str) -> tuple[str, dict[str, int]]: ...


class OllamaProvider:
    """The local Ollama API: the digest comes from /api/tags, the answer from /api/chat (temperature 0, JSON)."""

    name = "ollama"

    def __init__(self, host: str = OLLAMA_HOST) -> None:
        self.host = host

    def digest(self, model: str) -> str | None:
        with urllib.request.urlopen(f"{self.host}/api/tags", timeout=10) as response:
            tags = json.loads(response.read().decode("utf-8"))
        wanted = {model, f"{model}:latest"}
        for row in tags.get("models", []):
            if row.get("name") in wanted or row.get("model") in wanted:
                return str(row.get("digest") or "") or None
        return None

    def generate(self, model: str, prompt: str) -> tuple[str, dict[str, int]]:
        body = json.dumps({"model": model, "stream": False, "format": "json", "think": False,
                           "options": {"temperature": 0, "num_ctx": 32768},
                           "messages": [{"role": "user", "content": prompt}]}).encode("utf-8")
        request = urllib.request.Request(f"{self.host}/api/chat", body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=CALL_TIMEOUT_S) as response:
            raw = json.loads(response.read().decode("utf-8"))
        usage = {"input_tokens": int(raw.get("prompt_eval_count") or 0), "output_tokens": int(raw.get("eval_count") or 0)}
        return str((raw.get("message") or {}).get("content") or ""), usage


@dataclass(frozen=True)
class Receipt:
    """One provider call: who answered (digest read from the provider), on what (source, prompt), with what (output)."""
    provider: str
    model: str
    digest: str
    source_file: str
    source_sha256: str
    prompt_sha256: str
    output_sha256: str
    started_at: float
    elapsed_s: float
    input_tokens: int
    output_tokens: int


def measure(provider: Provider, model: str, sources: list[Path]) -> tuple[list[Receipt], list[str], list[str]]:
    """Run the extraction on every source through the provider. The digest is read before and after; a model that is
    missing or was replaced during the run yields no receipts."""
    before = provider.digest(model)
    if not before:
        raise ValueError(f"MODEL_NOT_INSTALLED:{provider.name}/{model}")
    receipts, outputs, texts = [], [], []
    for path in sources:
        text = Path(path).read_text(encoding="utf-8")
        prompt = EXTRACT_PROMPT.format(m=MAX_CANDIDATES, h=_sha(text), text=text)
        started = time.time()
        output, usage = provider.generate(model, prompt)
        receipts.append(Receipt(provider.name, model, before, Path(path).name, _sha(text), _sha(prompt), _sha(output),
                                round(started, 3), round(time.time() - started, 3),
                                usage.get("input_tokens", 0), usage.get("output_tokens", 0)))
        outputs.append(output)
        texts.append(text)
    after = provider.digest(model)
    if after != before:
        raise ValueError(f"DIGEST_CHANGED_DURING_RUN:{before}->{after}")
    return receipts, outputs, texts


def _key(provider: str, model: str, task_type: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", f"{provider}__{model}__{task_type}")


def _write(store: Path, name: str, entry: dict[str, Any]) -> None:
    """Atomic write (temp file + os.replace): parallel writers never leave a half-written record."""
    store = Path(store)
    store.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=store, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(entry, handle, ensure_ascii=False, indent=1)
    for attempt in range(REPLACE_TRIES):
        try:
            os.replace(tmp, store / f"{name}.json")
            return
        except PermissionError:
            # Windows refuses a replace while another writer's replace holds the target (U51 8-thread test).
            if attempt == REPLACE_TRIES - 1:
                Path(tmp).unlink(missing_ok=True)
                raise
            time.sleep(REPLACE_WAIT_S)


def qualify(store: Path, provider: Provider, model: str, sources: list[Path],
            expect_digest: str | None = None) -> dict[str, Any]:
    """Measure, verify the provenance, score and record one verdict per task type."""
    if not sources:
        raise ValueError("NO_SOURCES")
    if expect_digest:
        actual = provider.digest(model)
        if actual != expect_digest:
            raise ValueError(f"IDENTITY_MISMATCH: expected digest {expect_digest}, provider reports {actual}")
    receipts, outputs, texts = measure(provider, model, sources)
    totals = {t: [0, 0] for t in TASK_TYPES}
    for receipt, output, text in zip(receipts, outputs, texts):
        # Re-check each receipt against the bytes it describes before any of them may count.
        if receipt.output_sha256 != _sha(output) or receipt.source_sha256 != _sha(text):
            raise ValueError(f"RECEIPT_MISMATCH:{receipt.source_file}")
        for task, (ok, n) in score_output(output, text).items():
            totals[task][0] += ok
            totals[task][1] += n
    digest = receipts[0].digest
    result = {"provider": provider.name, "model": model, "digest": digest, "tasks": {}}
    for task, (passed, total) in totals.items():
        entry = {"evidence": EVIDENCE, "provider": provider.name, "model": model, "digest": digest,
                 "task_type": task, "passed": passed, "total": total, "verdict": verdict(passed, total),
                 "qualify_min": QUALIFY_MIN, "receipts": [asdict(r) for r in receipts]}
        _write(store, _key(provider.name, model, task), entry)
        result["tasks"][task] = {"passed": passed, "total": total, "verdict": entry["verdict"]}
    return result


def lookup(store: Path, *, provider: str, model: str, digest: str, task_type: str) -> str:
    """Status of this exact model artifact for this task. A different digest never inherits a verdict, and a record
    without receipts for that digest (hand-made or from the old `score --record`) counts as no record."""
    path = Path(store) / f"{_key(provider, model, task_type)}.json"
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "UNQUALIFIED"
    if entry.get("digest") != digest:
        return "UNQUALIFIED_DIGEST_CHANGED"
    receipts = entry.get("receipts") or []
    if entry.get("evidence") != EVIDENCE or not receipts or any(
            r.get("digest") != digest or r.get("model") != model or r.get("provider") != provider for r in receipts):
        return "UNQUALIFIED"
    return entry.get("verdict") if entry.get("verdict") in ("QUALIFIED", "REJECTED") else "UNQUALIFIED"


PROVIDERS = {"ollama": OllamaProvider}
# U70: where `qualify --record` keeps a project's verdicts, so the pilot's routing gate finds them.
QUALIFICATION_STORE = Path(".coord") / "qualification"


def local_admission(project: Path, *, model: str, task_type: str, provider: Provider | None = None) -> str:
    """U70: may this local model take a task of *task_type* now? Only QUALIFIED admits.

    The digest is read from the provider at call time, so a re-pulled model under the same name starts UNQUALIFIED.
    A provider that cannot be asked counts as MODEL_NOT_INSTALLED: the gate fails closed, it never guesses.
    """
    if task_type not in TASK_TYPES:
        return "UNKNOWN_TASK_TYPE"
    provider = provider or OllamaProvider()
    try:
        digest = provider.digest(model)
    except (OSError, ValueError):
        digest = None
    if not digest:
        return "MODEL_NOT_INSTALLED"
    return lookup(Path(project) / QUALIFICATION_STORE, provider=provider.name, model=model, digest=digest,
                  task_type=task_type)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="model_qualification")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("score", help="SCORER_ONLY: score saved outputs; never records, takes no identity")
    sc.add_argument("--runs", type=Path, required=True)
    sc.add_argument("--sources", type=Path, required=True)
    sc.add_argument("--pattern", default="art*.json", help="Run file glob inside --runs")
    qu = sub.add_parser("qualify", help="Call the provider on every source, then score and record with receipts")
    qu.add_argument("--provider", default="ollama", choices=sorted(PROVIDERS))
    qu.add_argument("--model", required=True)
    qu.add_argument("--sources", type=Path, required=True)
    qu.add_argument("--pattern", default="*.md", help="Source file glob inside --sources")
    qu.add_argument("--record", type=Path, required=True, help="Store dir for the verdict records")
    qu.add_argument("--expect-digest", default=None, help="Refuse to run unless the provider reports this digest")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "score":
            result = score_fixture(args.runs, args.sources, args.pattern)
        else:
            sources = sorted(args.sources.glob(args.pattern))
            result = qualify(args.record, PROVIDERS[args.provider](), args.model, sources, args.expect_digest)
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
===FILE: v7_harness/symbols.py===
"""U70: the deterministic route for "list what this Python file defines".

U67-O1b asked a local model for this list as JSON and got duplicates and an unusable format. The parser answers the
same question exactly, for zero model tokens, so a list of a Python file's symbols never needs a model at all.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path


def symbols(text: str) -> list[dict[str, object]]:
    """Top-level functions, classes (with their methods) and UPPER_CASE constants, in source order."""
    tree = ast.parse(text)
    rows: list[dict[str, object]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            rows.append({"kind": "function", "name": node.name, "line": node.lineno})
        elif isinstance(node, ast.ClassDef):
            rows.append({"kind": "class", "name": node.name, "line": node.lineno})
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    rows.append({"kind": "method", "name": f"{node.name}.{item.name}", "line": item.lineno})
        else:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(
                node, ast.AnnAssign) else []
            for target in targets:
                # Constants by the project's own convention: an UPPER_CASE module name.
                if isinstance(target, ast.Name) and target.id.isupper():
                    rows.append({"kind": "constant", "name": target.id, "line": node.lineno})
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="symbols", description="List a Python file's symbols without a model")
    parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    try:
        rows = symbols(args.path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        return 1
    print(json.dumps({"ok": True, "file": str(args.path), "symbols": rows}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
===FILE: tests/test_u70_local_qualification.py===
"""U70: a local model gets a typed task only when that exact model artifact is QUALIFIED for the type.

U67-O1b sent a JSON symbol extraction to qwen2.5-coder:7b; the answer repeated items and missed the format, and each
repeated true item used to count as another pass. The gate now refuses before any Ollama call, the scorer counts a
repeat as a failure, and the parser lists a Python file's symbols without a model.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from v7_harness.cli import main
from v7_harness.manual import lint, new_manual
from v7_harness.model_qualification import EVIDENCE, QUALIFICATION_STORE, _key, local_admission, score_extraction
from v7_harness.symbols import symbols

MODEL = "qwen2.5-coder:7b"
DIGEST = "d" * 64


class Provider:
    name = "ollama"

    def __init__(self, digest: str | None = DIGEST, error: Exception | None = None) -> None:
        self._digest, self._error = digest, error

    def digest(self, model: str) -> str | None:
        if self._error is not None:
            raise self._error
        return self._digest


def _record(root: Path, task_type: str, verdict: str, digest: str = DIGEST) -> None:
    store = root / QUALIFICATION_STORE
    store.mkdir(parents=True, exist_ok=True)
    receipt = {"provider": "ollama", "model": MODEL, "digest": digest}
    entry = {"evidence": EVIDENCE, "provider": "ollama", "model": MODEL, "digest": digest, "task_type": task_type,
             "verdict": verdict, "receipts": [receipt]}
    (store / f"{_key('ollama', MODEL, task_type)}.json").write_text(json.dumps(entry), encoding="utf-8")


class ScoringTests(unittest.TestCase):
    def test_a_repeated_true_item_is_a_failed_item(self) -> None:
        source = "alpha beta"
        once = score_extraction([{"name": "alpha", "quote": "alpha"}, {"name": "beta", "quote": "beta"}], source)
        self.assertEqual({"list_extract": (2, 2), "verbatim_quote": (2, 2)}, once)
        # Before U70 the four copies of "alpha" scored 4/4 and qualified a model that knew one item.
        repeated = score_extraction([{"name": "alpha", "quote": "alpha"}] * 4, source)
        self.assertEqual({"list_extract": (1, 4), "verbatim_quote": (1, 4)}, repeated)


class AdmissionTests(unittest.TestCase):
    def test_only_the_same_qualified_artifact_is_admitted(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            ask = lambda provider, task="list_extract": local_admission(root, model=MODEL, task_type=task,  # noqa: E731
                                                                         provider=provider)
            self.assertEqual("UNQUALIFIED", ask(Provider()))
            _record(root, "list_extract", "QUALIFIED")
            _record(root, "verbatim_quote", "REJECTED")
            self.assertEqual("QUALIFIED", ask(Provider()))
            self.assertEqual("REJECTED", ask(Provider(), "verbatim_quote"))
            self.assertEqual("UNQUALIFIED_DIGEST_CHANGED", ask(Provider("e" * 64)))
            self.assertEqual("UNKNOWN_TASK_TYPE", ask(Provider(), "summarise"))
            # Ollama down or the model not pulled: fail closed, never admit on a guess.
            self.assertEqual("MODEL_NOT_INSTALLED", ask(Provider(None)))
            self.assertEqual("MODEL_NOT_INSTALLED", ask(Provider(error=urllib.error.URLError("refused"))))


class PilotRunGateTests(unittest.TestCase):
    def _manual(self, root: Path, task_type: str) -> Path:
        (root / "notes.md").write_text("alpha beta\n", encoding="utf-8")
        text = new_manual(root, work_id="U70_T", worker="local", goal="List the items in `notes.md`.",
                          inputs=["notes.md"], allow=["notes.md"], acceptance="python -c 1", judge="codex")
        path = root / "m.md"
        path.write_text(text.replace("worker: local\n", f"worker: local\ntask_type: {task_type}\n"), encoding="utf-8")
        return path

    def _run(self, root: Path, task_type: str, provider: Provider, *extra: str) -> tuple[int, str, mock.MagicMock]:
        out = io.StringIO()
        with mock.patch("v7_harness.pilot.run_pilot", return_value={"state": "SUCCEEDED", "verdict_hint": "PASS"}) as run, \
                mock.patch("v7_harness.model_qualification.OllamaProvider", return_value=provider), \
                mock.patch("v7_harness.cli.detect_actor", return_value="codex"), \
                redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = main(["pilot", "run", "--task", "U70_T", "--source", str(root),
                         "--manual", str(self._manual(root, task_type)), *extra])
        return code, out.getvalue(), run

    def test_an_unqualified_model_never_starts(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _record(root, "list_extract", "REJECTED")
            code, out, run = self._run(root, "list_extract", Provider())
            self.assertEqual(2, code)
            run.assert_not_called()
            report = json.loads(out)
            self.assertEqual(("LOCAL_NOT_QUALIFIED", "REJECTED", MODEL),
                             (report["error_class"], report["qualification"], report["model"]))
            code, out, run = self._run(root, "list_extract", Provider(error=urllib.error.URLError("refused")))
            self.assertEqual((2, "MODEL_NOT_INSTALLED"), (code, json.loads(out)["qualification"]))
            run.assert_not_called()

    def test_a_qualified_model_and_an_approval_replay_run(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _record(root, "list_extract", "QUALIFIED")
            code, _, run = self._run(root, "list_extract", Provider())
            run.assert_called_once()
            # --approve replays a saved bundle; no model is called, so no qualification is asked.
            code, _, run = self._run(root, "verbatim_quote", Provider(None), "--approve", "b" * 64)
            run.assert_called_once()

    def test_a_manual_without_a_task_type_is_not_gated(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            out = io.StringIO()
            (root / "notes.md").write_text("alpha\n", encoding="utf-8")
            path = root / "m.md"
            path.write_text(new_manual(root, work_id="U70_N", worker="local", goal="g", inputs=["notes.md"],
                                       allow=["notes.md"], acceptance="python -c 1", judge="codex"), encoding="utf-8")
            with mock.patch("v7_harness.pilot.run_pilot", return_value={"state": "SUCCEEDED"}) as run, \
                    mock.patch("v7_harness.model_qualification.OllamaProvider",
                               side_effect=AssertionError("no task type, no qualification lookup")), \
                    mock.patch("v7_harness.cli.detect_actor", return_value="codex"), \
                    redirect_stdout(out), redirect_stderr(io.StringIO()):
                main(["pilot", "run", "--task", "U70_N", "--source", str(root), "--manual", str(path)])
            run.assert_called_once()

    def test_lint_rejects_an_unknown_task_type(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            report = lint(self._manual(root, "summarise").read_text(encoding="utf-8"), root)
            self.assertTrue(any(e.startswith("UNKNOWN_TASK_TYPE:summarise") for e in report.errors), report.errors)
            report = lint(self._manual(root, "list_extract").read_text(encoding="utf-8"), root)
            self.assertFalse(any("TASK_TYPE" in e for e in report.errors), report.errors)


class SymbolsTests(unittest.TestCase):
    def test_the_parser_lists_symbols_with_lines(self) -> None:
        text = ("LIMIT = 3\nname = 'x'\nclass Box:\n    def open(self):\n        pass\n\n"
                "async def fetch():\n    pass\nTIMEOUT: int = 5\n")
        self.assertEqual([{"kind": "constant", "name": "LIMIT", "line": 1},
                          {"kind": "class", "name": "Box", "line": 3},
                          {"kind": "method", "name": "Box.open", "line": 4},
                          {"kind": "function", "name": "fetch", "line": 7},
                          {"kind": "constant", "name": "TIMEOUT", "line": 9}], symbols(text))

    def test_the_parser_covers_a_real_module_without_duplicates(self) -> None:
        path = Path(__file__).resolve().parents[1] / "v7_harness" / "model_qualification.py"
        names = [row["name"] for row in symbols(path.read_text(encoding="utf-8"))]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue({"score_extraction", "local_admission", "TASK_TYPES", "OllamaProvider.digest"} <= set(names))


if __name__ == "__main__":
    unittest.main()
===FILE: docs/57_u70-local-task-qualification-gate.md===
# U70 로컬 모델 작업유형 자격 관문

## 왜 필요한가

U51은 로컬 모델(Ollama)의 자격을 **작업유형(task type)별로, 모델 파일의 digest에 묶어** 기록하는 도구(`model_qualification qualify --record`)를 만들었다. 그러나 그 기록을 읽는 곳이 없었다. 그래서 U67-O1b는 기호 목록 JSON 추출을 `qwen2.5-coder:7b`에 그대로 보냈다. 답은 같은 항목을 되풀이했고 형식도 맞지 않았다.

채점기에도 구멍이 있었다. 참인 항목 하나를 네 번 쓰면 4/4로 계산됐다. 쉬운 줄 하나를 반복하는 것만으로 합격선(QUALIFY_MIN)을 넘을 수 있었다.

## 무엇을 바꿨나

1. **중복은 실패로 센다** — `score_extraction`은 같은 항목의 두 번째 사본부터 통과로 치지 않는다. 기준 커밋 94285bd에서 `alpha`×4는 (4, 4)였고, 이제 (1, 4)다.
2. **매뉴얼의 `task_type:`** — 계약에 `task_type: list_extract` 또는 `verbatim_quote`를 쓸 수 있다. 모르는 값은 lint 오류 `UNKNOWN_TASK_TYPE`이다.
3. **pilot run 관문** — 작업자가 `local` 또는 `cascade`이고 계약에 작업유형이 있으면, Ollama를 부르기 **전에** `local_admission`이 판정한다.
   - 기록 위치: `<source>/.coord/qualification`. `qualify --record`에 이 경로를 주면 된다.
   - 모델: `--model` → 계약의 `model` → `ollama_worker`의 기본 모델 순서로 정한다. 실제 작업자에 넘어가는 순서와 같다.
   - digest는 호출 시점에 Ollama `/api/tags`에서 읽는다. 같은 이름으로 다시 받은 모델은 옛 판정을 물려받지 못한다(`UNQUALIFIED_DIGEST_CHANGED`).
   - `QUALIFIED`만 통과한다. `REJECTED`, `UNQUALIFIED`, digest 변경, Ollama 응답 없음(`MODEL_NOT_INSTALLED`)은 모두 거부한다. 결과는 `state: REFUSED`, `error_class: LOCAL_NOT_QUALIFIED`, 종료 코드 2다.
   - `--approve`는 저장된 번들을 재생할 뿐 모델을 부르지 않으므로 다시 판정하지 않는다.
   - 작업유형이 없는 매뉴얼은 전과 같이 동작한다. 관문은 작업유형을 선언한 작업에만 걸린다.
4. **결정적 경로 `v7_harness/symbols.py`** — 파이썬 파일의 함수·클래스·메서드·대문자 상수를 줄 번호와 함께 AST로 뽑는다. 모델 토큰은 0이다. "이 파일이 무엇을 정의하나"는 이제 모델에 묻지 않는다.
   - 실행: `python -m v7_harness.symbols <파일>`

## 왜 이렇게 정했나

- **통과는 QUALIFIED 하나뿐이다.** 자격 기록이 없다는 것은 "모른다"는 뜻이지 "괜찮다"가 아니다. 로컬 호출은 유료 토큰은 0이지만 벽시계와 검증 비용이 든다. 실패가 예상되는 호출을 막는 쪽이 싸다.
- **digest를 매번 읽는다.** 이름은 사람이 붙인 표시일 뿐이고, 같은 이름 아래 모델 파일이 바뀔 수 있다.
- **Ollama가 응답하지 않으면 거부한다.** 추측으로 허용하지 않는다(fail-closed).

## 운영 상태(2026-09-28)

- 이 데스크에는 아직 `.coord/qualification` 기록이 없다. 따라서 작업유형을 선언한 로컬 작업은 지금 모두 `UNQUALIFIED`로 거부된다.
- 로컬 모델을 다시 쓰려면 먼저 이 명령으로 측정·기록해야 한다.
  - `python -m v7_harness.model_qualification qualify --model qwen2.5-coder:7b --sources <문서 폴더> --record .coord/qualification`
- 절감량은 통제 비교 전까지 `UNMEASURED`다.

## 고정 인수

`tests/test_u70_local_qualification.py`가 확인하는 것:

- 중복 채점
- 판정 여섯 가지: QUALIFIED, REJECTED, digest 변경, 모르는 유형, 미설치, 연결 실패
- pilot run에서 작업자가 시작되지 않음
- 승인 재생과 작업유형 없는 매뉴얼은 관문 밖
- lint
- AST 기호 추출
===END===

## Output

- Reply with ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.
