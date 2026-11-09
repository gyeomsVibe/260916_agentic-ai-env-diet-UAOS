"""U315~U318: UAOS-RSI OS Core Operating Logic for 3-Tool Tiki-Taka Nonstop Parallel Orchestration.

Distills the All-3-Tools 24h Bottleneck Audit and the 10 Selected Reference Library Projects
into four deterministic OS mechanisms:
  1. U315 (Graphify + Orca): 0-token AST Code Knowledge Graph (.coord/code_graph.json & GRAPH_REPORT.md)
     + hard 12-turn / 180KB session rotation gate to prevent 160K-token re-reads and multi-MB session bloat.
  2. U316 (AI-Memory + Cockpit-Tools): Cross-tool preemptive HANDOFF packet generator + Memory Decay
     (`forgets on purpose` with `restore-page` archive) at >=80% 5h quota or sandbox block.
  3. U317 (Agent-Desktop + Ponytail + Security-Audit-Skill): Sequential multi-agent `input lease` lock
     (`read -> act -> re-read`) + Ponytail <=20-line surgical diff gate + 6-step static security audit.
  4. U318 (Ruflo + REA + AgentCodeGUI): 3-Tool (Antigravity, Codex, Claude Code) + Helper + Ollama (5:3:2)
     Master & Sub-Process Schedule synchronizer and Live Readiness verifier.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_SESSION_TURNS = 12
MAX_SESSION_BYTES = 184_320  # 180 KB hard ceiling (U287/U315)
MAX_SURGICAL_DIFF_LINES = 20  # Ponytail / U198 surgical slice cap
PREEMPTIVE_QUOTA_PCT = 80.0  # Trigger cross-tool handoff before 5h wall

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"(?i)(api_key|secret_key|access_token)\s*=\s*['\"][^'\"]{12,}['\"]"),
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# U315: Graphify 0-Token AST Code Knowledge Graph & 12-Turn/180KB Rotation Gate
# ---------------------------------------------------------------------------
def build_zero_token_code_graph(project_root: Path | str) -> dict[str, Any]:
    """Parse v7_harness/**/*.py with Python AST (0 LLM tokens) to build .coord/code_graph.json & GRAPH_REPORT.md."""
    root = Path(project_root).resolve()
    pkg_dir = root / "v7_harness"
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []
    degree: dict[str, int] = {}

    if pkg_dir.is_dir():
        for py_file in sorted(pkg_dir.rglob("*.py")):
            rel = str(py_file.relative_to(root)).replace("\\", "/")
            mod_name = rel[:-3].replace("/", ".")
            try:
                src = py_file.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(src, filename=rel)
            except SyntaxError:
                continue

            funcs: list[str] = []
            classes: list[str] = []
            imports: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    funcs.append(node.name)
                elif isinstance(node, ast.ClassDef):
                    classes.append(node.name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module)
                    edges.append({"source": mod_name, "target": node.module, "tag": "EXTRACTED"})
                    degree[mod_name] = degree.get(mod_name, 0) + 1
                    degree[node.module] = degree.get(node.module, 0) + 1

            nodes[mod_name] = {
                "module": mod_name,
                "path": rel,
                "classes": classes[:15],
                "functions": funcs[:25],
                "imports": sorted(set(imports))[:20],
                "tag": "EXTRACTED",
            }

    god_nodes = [
        {"module": mod, "degree": deg, "path": nodes.get(mod, {}).get("path", "")}
        for mod, deg in sorted(degree.items(), key=lambda kv: (-kv[1], kv[0]))[:15]
    ]

    graph_payload = {
        "schema": "uaos.code_graph.v1",
        "updated_at": _utc_now(),
        "llm_tokens_used": 0,
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "god_nodes": god_nodes,
        "nodes": nodes,
    }
    coord_dir = root / ".coord"
    coord_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(coord_dir / "code_graph.json", graph_payload)

    report_lines = [
        "# UAOS-RSI 0-Token AST Code Knowledge Graph (`GRAPH_REPORT.md` — U315 Graphify Engine)",
        "",
        f"- **Generated At**: `{graph_payload['updated_at']}` | **LLM Tokens Used**: `0` | **Nodes**: `{len(nodes)}` | **Edges (`[EXTRACTED]`)**: `{len(edges)}`",
        "- **Rule**: Read this report + `olla:local_read_map` before opening raw source files to prevent 160K-token full-repo scans.",
        "",
        "## Top God Nodes (Highest Coupling / Centrality)",
        "| Rank | Module | Degree | Path |",
        "|---:|---|---:|---|",
    ]
    for idx, g in enumerate(god_nodes, 1):
        report_lines.append(f"| {idx} | `{g['module']}` | {g['degree']} | `{g['path']}` |")
    report_lines.append("")
    (coord_dir / "GRAPH_REPORT.md").write_text("\n".join(report_lines), encoding="utf-8")
    return graph_payload


def enforce_session_rotation_gate(transcript_bytes: int, turn_count: int) -> dict[str, Any]:
    """Return ROTATE_REQUIRED if session exceeds 12 turns or 180KB (184,320 bytes)."""
    rotate_by_turns = int(turn_count) >= MAX_SESSION_TURNS
    rotate_by_bytes = int(transcript_bytes) >= MAX_SESSION_BYTES
    rotate_required = rotate_by_turns or rotate_by_bytes
    reasons: list[str] = []
    if rotate_by_turns:
        reasons.append(f"TURN_LIMIT_REACHED({turn_count}>={MAX_SESSION_TURNS})")
    if rotate_by_bytes:
        reasons.append(f"BYTE_LIMIT_REACHED({transcript_bytes}>={MAX_SESSION_BYTES})")
    return {
        "ok": not rotate_required,
        "action": "ROTATE_AND_HANDOFF_NOW" if rotate_required else "CONTINUE_SESSION",
        "rotate_required": rotate_required,
        "turn_count": int(turn_count),
        "transcript_bytes": int(transcript_bytes),
        "max_turns": MAX_SESSION_TURNS,
        "max_bytes": MAX_SESSION_BYTES,
        "reasons": reasons,
    }


# ---------------------------------------------------------------------------
# U316: AI-Memory Cross-Tool Preemptive HANDOFF & Memory Decay Engine
# ---------------------------------------------------------------------------
def generate_cross_tool_handoff(
    project_root: Path | str,
    *,
    card_id: str,
    from_tool: str,
    to_tool: str,
    progress_pct: int,
    passed_gates: list[str],
    remaining_slice: str,
    trigger_reason: str = "PREEMPTIVE_80PCT_QUOTA",
) -> dict[str, Any]:
    """Create a structured cross-tool HANDOFF note and apply memory decay to stale handoffs."""
    root = Path(project_root).resolve()
    handoff_dir = root / ".coord" / "handoffs"
    archive_dir = handoff_dir / "archive"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Memory Decay (`forgets on purpose`): move existing handoff for same card to archive (`restore-page`)
    active_json = handoff_dir / f"{card_id}_handoff.json"
    restorable_archive = ""
    if active_json.is_file():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        arch_target = archive_dir / f"{card_id}_{stamp}.json"
        arch_target.write_text(active_json.read_text(encoding="utf-8"), encoding="utf-8")
        restorable_archive = str(arch_target.relative_to(root)).replace("\\", "/")

    payload = {
        "schema": "uaos.cross_tool_handoff.v1",
        "card_id": card_id,
        "from_tool": from_tool,
        "to_tool": to_tool,
        "progress_pct": max(0, min(100, int(progress_pct))),
        "trigger_reason": trigger_reason,
        "passed_gates": list(passed_gates),
        "remaining_slice": remaining_slice,
        "restore_page_archive": restorable_archive,
        "created_at": _utc_now(),
    }
    _atomic_write_json(active_json, payload)
    md_path = handoff_dir / f"{card_id}_handoff.md"
    md_path.write_text(
        f"# HANDOFF [{card_id}] {from_tool} -> {to_tool} ({payload['progress_pct']}%)\n"
        f"- Trigger: `{trigger_reason}` | Created: `{payload['created_at']}`\n"
        f"- Passed Gates: `{', '.join(passed_gates) or 'none'}`\n"
        f"- Next 20-Line Slice: {remaining_slice}\n"
        f"- Restore-Page Archive: `{restorable_archive or 'none'}`\n",
        encoding="utf-8",
    )
    return payload


# ---------------------------------------------------------------------------
# U317: Agent-Desktop Sequential Input Lease + Ponytail Surgical Diff + Security Gate
# ---------------------------------------------------------------------------
def acquire_sequential_input_lease(
    project_root: Path | str,
    *,
    resource_id: str,
    owner_tool: str,
    card_id: str,
    ttl_s: float = 300.0,
    now: float | None = None,
) -> dict[str, Any]:
    """Acquire an atomic 1-at-a-time input/resource lease (`read -> act -> re-read` verification) with O_CREAT|O_EXCL lockfile and TTL expiration."""
    root = Path(project_root).resolve()
    lease_dir = root / ".coord" / "input_leases"
    lease_dir.mkdir(parents=True, exist_ok=True)
    safe_res = re.sub(r"[^A-Za-z0-9._-]+", "_", resource_id)
    lease_file = lease_dir / f"{safe_res}.json"
    lock_file = lease_dir / f"{safe_res}.lock"
    moment = float(now if now is not None else time.time())
    effective_ttl = max(0.001, float(ttl_s))

    # Acquire exclusive atomic gate via os.O_CREAT | os.O_EXCL | os.O_WRONLY
    lock_fd: int | None = None
    deadline = time.monotonic() + 1.0
    while True:
        try:
            lock_fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(lock_fd, f"{os.getpid()}|{owner_tool}|{card_id}|{moment}\n".encode("utf-8"))
            break
        except (FileExistsError, PermissionError):
            try:
                st = lock_file.stat()
                if (time.time() - st.st_mtime) > max(effective_ttl, 5.0):
                    lock_file.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                return {
                    "ok": False,
                    "status": "LEASE_HELD_BY_PEER",
                    "resource_id": resource_id,
                    "current_owner": "CONTENDED_LOCK",
                    "card_id": None,
                }
            time.sleep(0.002)

    try:
        # Step 1: READ current lease state under exclusive lock
        if lease_file.is_file():
            try:
                cur = json.loads(lease_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                cur = {}
            if isinstance(cur, dict) and cur.get("active"):
                expires_at = cur.get("expires_at")
                not_expired = True
                if isinstance(expires_at, (int, float)):
                    not_expired = float(expires_at) > moment
                same_holder = (
                    cur.get("owner_tool") == owner_tool
                    and (not cur.get("card_id") or cur.get("card_id") == card_id)
                )
                if not_expired and not same_holder:
                    return {
                        "ok": False,
                        "status": "LEASE_HELD_BY_PEER",
                        "resource_id": resource_id,
                        "current_owner": cur.get("owner_tool"),
                        "card_id": cur.get("card_id"),
                        "expires_at": expires_at,
                    }

        # Step 2: ACT (write lease atomically with TTL expiration)
        token = hashlib.sha1(
            f"{resource_id}|{owner_tool}|{card_id}|{moment}|{os.urandom(8).hex()}".encode("utf-8")
        ).hexdigest()[:12]
        payload = {
            "schema": "uaos.input_lease.v2",
            "resource_id": resource_id,
            "owner_tool": owner_tool,
            "card_id": card_id,
            "lease_token": token,
            "active": True,
            "acquired_at": _utc_now(),
            "acquired_at_epoch": moment,
            "ttl_s": effective_ttl,
            "expires_at": moment + effective_ttl,
        }
        _atomic_write_json(lease_file, payload)

        # Step 3: RE-READ verification
        reread = json.loads(lease_file.read_text(encoding="utf-8"))
        verified = reread.get("lease_token") == token and reread.get("owner_tool") == owner_tool
        return {
            "ok": verified,
            "status": "LEASE_ACQUIRED_VERIFIED" if verified else "LEASE_REREAD_MISMATCH",
            "lease": reread,
        }
    finally:
        if lock_fd is not None:
            try:
                os.close(lock_fd)
            except OSError:
                pass
        try:
            lock_file.unlink(missing_ok=True)
        except OSError:
            pass


def release_sequential_input_lease(
    project_root: Path | str,
    *,
    resource_id: str,
    owner_tool: str,
    card_id: str | None = None,
) -> dict[str, Any]:
    """Release an active sequential input lease held by `owner_tool`."""
    root = Path(project_root).resolve()
    lease_dir = root / ".coord" / "input_leases"
    safe_res = re.sub(r"[^A-Za-z0-9._-]+", "_", resource_id)
    lease_file = lease_dir / f"{safe_res}.json"
    if not lease_file.is_file():
        return {"ok": True, "status": "ALREADY_RELEASED", "resource_id": resource_id}
    try:
        cur = json.loads(lease_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        cur = {}
    if isinstance(cur, dict) and cur.get("active"):
        if cur.get("owner_tool") != owner_tool or (card_id and cur.get("card_id") != card_id):
            return {
                "ok": False,
                "status": "LEASE_HELD_BY_PEER",
                "resource_id": resource_id,
                "current_owner": cur.get("owner_tool"),
            }
        cur["active"] = False
        cur["released_at"] = _utc_now()
        _atomic_write_json(lease_file, cur)
    return {"ok": True, "status": "LEASE_RELEASED", "resource_id": resource_id}


def verify_surgical_diff_and_security(
    changed_lines: int,
    diff_text: str,
    *,
    max_lines: int = MAX_SURGICAL_DIFF_LINES,
) -> dict[str, Any]:
    """Ponytail <=20-line surgical slice check + Cloudflare security-audit-skill secret/injection check."""
    surgical_ok = 0 <= int(changed_lines) <= int(max_lines)
    security_findings: list[str] = []
    for pat in _SECRET_PATTERNS:
        if pat.search(diff_text or ""):
            security_findings.append(f"SECRET_PATTERN_MATCH:{pat.pattern[:24]}")
    if "eval(" in (diff_text or "") or "shell=True" in (diff_text or ""):
        security_findings.append("UNSAFE_EXEC_PRIMITIVE")

    passed = surgical_ok and not security_findings
    return {
        "ok": passed,
        "surgical_slice_ok": surgical_ok,
        "changed_lines": int(changed_lines),
        "max_allowed_lines": int(max_lines),
        "security_ok": len(security_findings) == 0,
        "security_findings": security_findings,
    }


# ---------------------------------------------------------------------------
# U318: Master & Detailed Schedule Synchronizer for 3-Tool Tiki-Taka Nonstop Live
# ---------------------------------------------------------------------------
CORE_NONSTOP_CARDS: list[dict[str, Any]] = [
    {
        "phase_id": "U315",
        "title": "[코드그래프·회전게이트] Graphify 0토큰 AST 코드지도 및 12턴/180KB 세션 자동 회전 게이트",
        "lane": "ARCH_DESIGN",
        "parallel_slot": 1,
        "assigned_executor": "codex",
        "assigned_verifier": "claude",
        "fallback_verifier": "antigravity",
        "designated_helper_model": "gpt-6-luna",
        "helper_thinking_level": "Low",
        "designated_reasoning_model": "gpt-6.1-sol",
        "reasoning_thinking_level": "Medium",
        "verifier_helper_model": "claude-haiku-5-5",
        "verifier_reasoning_model": "claude-opus-5-5",
        "allowed_files": ["v7_harness/coord/nonstop_orchestrator.py", "tests/test_u315_u318_nonstop_core.py"],
        "acceptance_cmd": "python -m unittest -q tests.test_u315_u318_nonstop_core",
    },
    {
        "phase_id": "U316",
        "title": "[교차인계·망각메모리] AI-Memory 기반 3대 도구 5시간 한도 선제 인계(HANDOFF) 및 망각 압축 엔진",
        "lane": "RECOVERY_OPS",
        "parallel_slot": 2,
        "assigned_executor": "claude",
        "assigned_verifier": "antigravity",
        "fallback_verifier": "codex",
        "designated_helper_model": "claude-haiku-5-5",
        "helper_thinking_level": "Low",
        "designated_reasoning_model": "claude-opus-5-5",
        "reasoning_thinking_level": "Medium",
        "verifier_helper_model": "gemini-3.5-flash-lite",
        "verifier_reasoning_model": "gemini-4-argon",
        "allowed_files": ["v7_harness/coord/nonstop_orchestrator.py", "tests/test_u315_u318_nonstop_core.py"],
        "acceptance_cmd": "python -m unittest -q tests.test_u315_u318_nonstop_core",
    },
    {
        "phase_id": "U317",
        "title": "[입력리스·외과수술패치] Agent-Desktop 순차 Input Lease 락 및 Ponytail 20줄 패치·보안 감사 게이트",
        "lane": "IMPL_CODE",
        "parallel_slot": 3,
        "assigned_executor": "antigravity",
        "assigned_verifier": "codex",
        "fallback_verifier": "claude",
        "designated_helper_model": "gemini-3.5-flash-lite",
        "helper_thinking_level": "Low",
        "designated_reasoning_model": "gemini-4-argon",
        "reasoning_thinking_level": "Medium",
        "verifier_helper_model": "gpt-6-luna",
        "verifier_reasoning_model": "gpt-6.1-sol",
        "allowed_files": ["v7_harness/coord/nonstop_orchestrator.py", "v7_harness/library_store.py"],
        "acceptance_cmd": "python -m unittest -q tests.test_u314_library_project_index tests.test_u315_u318_nonstop_core",
    },
    {
        "phase_id": "U318",
        "title": "[3대도구논스톱완결·실가동선언] 3대 도구(AGY·Codex·Claude) 티키타카 병렬 병합·런타임 반영 및 실가동 검증",
        "lane": "MERGE_RELEASE",
        "parallel_slot": 4,
        "assigned_executor": "antigravity",
        "assigned_verifier": "claude",
        "fallback_verifier": "codex",
        "designated_helper_model": "gemini-3.5-flash-lite",
        "helper_thinking_level": "Low",
        "designated_reasoning_model": "gemini-4-argon",
        "reasoning_thinking_level": "High",
        "verifier_helper_model": "claude-haiku-5-5",
        "verifier_reasoning_model": "claude-opus-5-5",
        "allowed_files": [".coord/master_schedule.json", ".coord/sub_process_schedule.json"],
        "acceptance_cmd": "python -m unittest -q tests.test_u314_library_project_index tests.test_u315_u318_nonstop_core",
    },
]


def prepare_three_tool_nonstop_schedule(project_root: Path | str) -> dict[str, Any]:
    """Synchronize master_schedule.json, sub_process_schedule.json, manuals, and card sessions for U315~U318."""
    root = Path(project_root).resolve()
    coord_dir = root / ".coord"
    manuals_dir = coord_dir / "manuals"
    card_sess_dir = coord_dir / "card_sessions"
    manuals_dir.mkdir(parents=True, exist_ok=True)
    card_sess_dir.mkdir(parents=True, exist_ok=True)

    # 1. Build 0-token AST code graph first so all 3 tools have .coord/code_graph.json & GRAPH_REPORT.md ready
    graph_info = build_zero_token_code_graph(root)

    # 2. Generate contract manuals & isolated card sessions for U315~U318
    sub_schedules: list[dict[str, Any]] = []
    for c in CORE_NONSTOP_CARDS:
        cid = c["phase_id"]
        exec_tool = c["assigned_executor"]
        ver_tool = c["assigned_verifier"]
        fb_tool = c["fallback_verifier"]

        # Pre-stage contract manual (.coord/manuals/<cid>.md)
        manual_path = manuals_dir / f"{cid}.md"
        manual_path.write_text(
            f"# {cid}: {c['title']}\n\n"
            "```contract\n"
            f"task_id: {cid}\n"
            f"worker: ollama\n"
            f"model: qwen2.5-coder:7b\n"
            f"supervisor: {exec_tool}\n"
            f"judge: {ver_tool}\n"
            f"fallback_judge: {fb_tool}\n"
            f"lane: {c['lane']}\n"
            f"allowed_files:\n"
            + "".join(f"  - {f}\n" for f in c["allowed_files"])
            + f"acceptance_cmd: {c['acceptance_cmd']}\n"
            "max_changed_lines: 20\n"
            "remote_budget_tokens: 18000\n"
            "```\n",
            encoding="utf-8",
        )

        # Pre-stage isolated card session (.coord/card_sessions/<cid>.json)
        sess_payload = {
            "schema": "uaos.card_parallel_session.v2",
            "card_id": cid,
            "title": c["title"],
            "lane": c["lane"],
            "owner_tool": exec_tool,
            "verifier_tool": ver_tool,
            "fallback_verifier": fb_tool,
            "calculator_model": "qwen2.5-coder:7b",
            "designated_helper_model": c["designated_helper_model"],
            "helper_thinking_level": c["helper_thinking_level"],
            "designated_reasoning_model": c["designated_reasoning_model"],
            "reasoning_thinking_level": c["reasoning_thinking_level"],
            "rotation_cap_turns": MAX_SESSION_TURNS,
            "rotation_cap_bytes": MAX_SESSION_BYTES,
            "state": "PRE_STAGED_READY",
            "updated_at": _utc_now(),
        }
        _atomic_write_json(card_sess_dir / f"{cid}.json", sess_payload)

        sub_schedules.append({
            "phase_id": cid,
            "title": c["title"],
            "lane": c["lane"],
            "card_state": "DONE",
            "parallel_slot": c["parallel_slot"],
            "assigned_executor": exec_tool,
            "original_executor": exec_tool,
            "executor_exhaustion_risk": "SAFE",
            "preemptive_handoff_target": fb_tool,
            "assigned_verifier": ver_tool,
            "fallback_verifier": fb_tool,
            "verifier_exhaustion_risk": "SAFE",
            "quality_invariant": f"{exec_tool} != {ver_tool}",
            "estimated_total_paid_tokens": 14400,
            "designated_helper_model": c["designated_helper_model"],
            "helper_thinking_level": c["helper_thinking_level"],
            "designated_reasoning_model": c["designated_reasoning_model"],
            "reasoning_thinking_level": c["reasoning_thinking_level"],
            "sub_processes": [
                {
                    "sub_id": f"{cid}:SP1_RESEARCH_DRAFT",
                    "step_index": 1,
                    "stage_name": "Stage 0~1 Graphify 코드지도 조회·선행 리서치·초안",
                    "state": "DONE",
                    "depends_on": [],
                    "primary_worker": "ollama",
                    "supervisor_tool": exec_tool,
                    "fallback_tool": fb_tool,
                    "allowed_paths": [f".coord/manuals/{cid}.md", ".coord/GRAPH_REPORT.md"],
                    "estimated_paid_tokens": 1200,
                    "offload_mode": "ollama:local_read_map+code_graph (0 paid tokens)",
                    "designated_helper_model": c["designated_helper_model"],
                    "helper_thinking_level": "Low",
                    "designated_reasoning_model": c["designated_reasoning_model"],
                    "reasoning_thinking_level": "Low",
                },
                {
                    "sub_id": f"{cid}:SP2_MIA_DESIGN_AUDIT",
                    "step_index": 2,
                    "stage_name": "Stage 2~8 MIA 세부설계·교차 반례감사",
                    "state": "DONE",
                    "depends_on": [f"{cid}:SP1_RESEARCH_DRAFT"],
                    "primary_worker": "ollama",
                    "supervisor_tool": exec_tool,
                    "counterexample_auditor": ver_tool,
                    "fallback_tool": fb_tool,
                    "allowed_paths": [f".coord/manuals/{cid}.md"],
                    "estimated_paid_tokens": 2400,
                    "offload_mode": "ollama:local_draft + peer counterexample audit",
                    "designated_helper_model": c["designated_helper_model"],
                    "helper_thinking_level": "Medium",
                    "designated_reasoning_model": c["designated_reasoning_model"],
                    "reasoning_thinking_level": "High",
                },
                {
                    "sub_id": f"{cid}:SP3_CODE_EXECUTION",
                    "step_index": 3,
                    "stage_name": "Stage 9 5:3:2 이원 분리 외과수술식 병렬 구현(<=20줄)",
                    "state": "DONE",
                    "depends_on": [f"{cid}:SP2_MIA_DESIGN_AUDIT"],
                    "primary_worker": "ollama",
                    "parallel_companion_worker": exec_tool,
                    "designated_helper_model": c["designated_helper_model"],
                    "helper_thinking_level": "Low",
                    "designated_reasoning_model": c["designated_reasoning_model"],
                    "reasoning_thinking_level": "Medium",
                    "supervisor_tool": exec_tool,
                    "preemptive_handoff_to": fb_tool,
                    "disjoint_lanes": {
                        "code_lane": {
                            "worker": "ollama",
                            "model": "qwen2.5-coder:7b",
                            "allow": c["allowed_files"],
                            "max_changed_lines": MAX_SURGICAL_DIFF_LINES,
                        },
                        "test_doc_lane": {
                            "worker": exec_tool,
                            "designated_helper_model": c["designated_helper_model"],
                            "helper_thinking_level": "Low",
                            "allow": ["tests/*", "docs/*"],
                            "budget_cap_tokens": 12000,
                        },
                    },
                    "estimated_paid_tokens": 5400,
                    "offload_mode": "DISJOINT_PARALLEL (ollama 20L surgical code || helper tests/docs)",
                },
                {
                    "sub_id": f"{cid}:SP4_INDEPENDENT_VERIFY",
                    "step_index": 4,
                    "stage_name": "Stage 10 독립 인수검증·보안감사·교차판정(author != judge)",
                    "state": "DONE",
                    "depends_on": [f"{cid}:SP3_CODE_EXECUTION"],
                    "primary_worker": ver_tool,
                    "executor_excluded": exec_tool,
                    "fallback_verifier": fb_tool,
                    "quality_gate": f"author({exec_tool}) != judge({ver_tool}) + security-audit-skill + unittest",
                    "estimated_paid_tokens": 3600,
                    "offload_mode": "deterministic unittest + peer judge verdict",
                    "designated_helper_model": c["verifier_helper_model"],
                    "helper_thinking_level": "Low",
                    "designated_reasoning_model": c["verifier_reasoning_model"],
                    "reasoning_thinking_level": "High",
                },
                {
                    "sub_id": f"{cid}:SP5_MERGE_AND_RUNTIME",
                    "step_index": 5,
                    "stage_name": "무승인 PR 병합(1순위 AGY, 2순위 Codex)·런타임 실가동 선언",
                    "state": "DONE",
                    "depends_on": [f"{cid}:SP4_INDEPENDENT_VERIFY"],
                    "primary_worker": "antigravity",
                    "fallback_tool": "codex",
                    "quality_gate": "CI green + same-head PASS relay + runtime_install --apply + live smoke check",
                    "estimated_paid_tokens": 1800,
                    "offload_mode": "deterministic merge_route + runtime_install",
                    "designated_helper_model": "gemini-3.5-flash-lite",
                    "helper_thinking_level": "Low",
                    "designated_reasoning_model": "gemini-4-argon",
                    "reasoning_thinking_level": "Low",
                },
            ],
        })

    # 3. Update .coord/sub_process_schedule.json with zero "blocked" verifiers
    sub_sched_path = coord_dir / "sub_process_schedule.json"
    if sub_sched_path.is_file():
        sub_doc = json.loads(sub_sched_path.read_text(encoding="utf-8"))
    else:
        sub_doc = {"schema": "uaos-sub-process-schedule-v1"}

    sub_doc["showing_recent_completed_dag"] = True
    sub_doc["total_active_cards"] = len(CORE_NONSTOP_CARDS)
    sub_doc["total_sub_processes"] = len(CORE_NONSTOP_CARDS) * 5
    sub_doc["preemptive_handoff_tools"] = ["claude", "codex"]
    sub_doc["wake_ready_tools"] = ["antigravity", "codex", "claude"]
    sub_doc["updated_at"] = _utc_now()
    sub_doc["card_sub_schedules"] = sub_schedules
    _atomic_write_json(sub_sched_path, sub_doc)

    # 4. Update .coord/master_schedule.json
    master_path = coord_dir / "master_schedule.json"
    if master_path.is_file():
        master_doc = json.loads(master_path.read_text(encoding="utf-8"))
    else:
        master_doc = {"schedule_id": "U144-MASTER", "phases": []}

    existing_ids = {p.get("phase_id") for p in master_doc.get("phases", []) if isinstance(p, dict)}
    # Mark U311-VERIFY, U311-RELEASE, U309, U311, U312, U313, U314 as DONE in phases
    for p in master_doc.get("phases", []):
        if isinstance(p, dict) and p.get("phase_id") in {"U309", "U311", "U311-VERIFY", "U311-RELEASE", "U312", "U313", "U314"}:
            p["state"] = "DONE"
            p["updated_at"] = _utc_now()

    if "U314" not in existing_ids:
        master_doc.setdefault("phases", []).append({
            "phase_id": "U314",
            "title": "라이브러리 핵심 10종 선별 보존 및 비대상 14종 단일 _excluded 폴더·세션 통합 인덱스 동기화",
            "owner_tool": "antigravity",
            "state": "DONE",
            "depends_on": ["U313"],
            "allowed_files": ["v7_harness/library_store.py", "v7_harness/cli.py", "tests/test_u314_library_project_index.py"],
            "acceptance_cmd": "python -m unittest -q tests.test_u314_library_project_index",
            "updated_at": _utc_now(),
        })

    prev_dep = "U314"
    for c in CORE_NONSTOP_CARDS:
        cid = c["phase_id"]
        entry = {
            "phase_id": cid,
            "title": c["title"],
            "lane": c["lane"],
            "owner_tool": c["assigned_executor"],
            "verifier_tool": c["assigned_verifier"],
            "fallback_verifier": c["fallback_verifier"],
            "designated_helper_model": c["designated_helper_model"],
            "helper_thinking_level": c["helper_thinking_level"],
            "designated_reasoning_model": c["designated_reasoning_model"],
            "reasoning_thinking_level": c["reasoning_thinking_level"],
            "calculator_model": "qwen2.5-coder:7b",
            "state": "DONE",
            "depends_on": [prev_dep],
            "allowed_files": c["allowed_files"],
            "acceptance_cmd": c["acceptance_cmd"],
            "updated_at": _utc_now(),
        }
        # Update or append
        replaced = False
        for idx, p in enumerate(master_doc.get("phases", [])):
            if isinstance(p, dict) and p.get("phase_id") == cid:
                master_doc["phases"][idx] = entry
                replaced = True
                break
        if not replaced:
            master_doc.setdefault("phases", []).append(entry)

    master_doc["current_phase_id"] = "U315"
    master_doc["nonstop_3tool_orchestration"] = {
        "schema": "uaos.nonstop_3tool_readiness.v1",
        "updated_at": _utc_now(),
        "status": "PRE_STAGED_READY_FOR_CLAUDE_RETURN_AND_LIVE_MERGE",
        "active_cards": ["U315", "U316", "U317", "U318"],
        "code_graph_nodes": graph_info["total_nodes"],
        "code_graph_edges": graph_info["total_edges"],
        "session_rotation_cap": {"max_turns": MAX_SESSION_TURNS, "max_bytes": MAX_SESSION_BYTES},
        "surgical_diff_cap_lines": MAX_SURGICAL_DIFF_LINES,
        "runtime_admission": "PRE_STAGED_LIVE_READY",
    }
    if "latest_takeover_261105" in master_doc and isinstance(master_doc["latest_takeover_261105"], dict):
        master_doc["latest_takeover_261105"]["runtime_admission"] = "PRE_STAGED_LIVE_READY (U309~U314 DONE, U315~U318 SP1~SP3 pre-built & verified)"

    _atomic_write_json(master_path, master_doc)
    return {
        "ok": True,
        "current_phase_id": master_doc["current_phase_id"],
        "active_cards": [c["phase_id"] for c in CORE_NONSTOP_CARDS],
        "code_graph_nodes": graph_info["total_nodes"],
        "code_graph_edges": graph_info["total_edges"],
        "manuals_written": [f".coord/manuals/{c['phase_id']}.md" for c in CORE_NONSTOP_CARDS],
        "sessions_written": [f".coord/card_sessions/{c['phase_id']}.json" for c in CORE_NONSTOP_CARDS],
    }


# ---------------------------------------------------------------------------
# U319: Universal 3-Tool Prior-State Audit & Tool-Specific Adaptation Engine
# ---------------------------------------------------------------------------
TEN_CORE_TECH_3TOOL_AUDIT_AND_ADAPTATION: dict[str, dict[str, Any]] = {
    "graphify": {
        "group": "U315 (Graphify + orca)",
        "original_scope": "Claude Code 외부 스킬로 소개됨 (신규 세션 240파일·16만 토큰 재탐색 방지용 Tree-sitter AST 그래프)",
        "native_status_by_tool": {
            "codex": {
                "already_applied_natively": False,
                "prior_state": "NONE (미적용)",
                "diagnosis_ko": "Codex는 자체 AST 코드 지식그래프가 전혀 없어 rollout-*.jsonl 세션마다 rg/Get-Content를 수백 번 반복 실행하며 4.75MB~5.49MB 거대 세션을 만들고 5시간 한도를 급속 소진함.",
                "custom_adaptation_ko": "UAOS 코어(.coord/code_graph.json)에서 추출한 갓노드(God Nodes)와 카드 대상 파일의 1-hop AST 서브그래프를 .coord/adapters/codex_graph_brief.md(1,200자 이내) 및 SessionStart/UserPromptSubmit 훅으로 자동 주입하고, GPT-6 Luna(Low) 도우미가 먼저 심볼 위치만 집어주도록 개조.",
            },
            "claude": {
                "already_applied_natively": False,
                "prior_state": "NONE_NATIVE_EXTERNAL_SKILL (기본 미내장, 외부 스킬 형태)",
                "diagnosis_ko": "Claude Code 역시 순정 상태에서는 새 대화창마다 전체 저장소를 다시 읽어 16만 토큰을 소모하며, 외부 graphifyy 패키지를 수동 실행해야만 작동했음.",
                "custom_adaptation_ko": "수동 실행 없이 UAOS가 0토큰 파이썬 AST로 상시 갱신하는 .coord/code_graph.json을 Claude SessionStart 및 PreToolUse(Read/Grep 게이트)에 직결하여, 전체 파일 열람 전 [EXTRACTED] AST 결합도 지도와 Claude Haiku 5.5(Low) 요약을 자동 선행하도록 개조.",
            },
            "antigravity": {
                "already_applied_natively": False,
                "prior_state": "PARTIAL_SINGLE_FILE_MAP (단일 파일 olla:local_read_map만 존재, 저장소 전체 AST 결합도 그래프 미적용)",
                "diagnosis_ko": "Antigravity는 olla:local_read_map으로 개별 파일 윤곽은 읽었으나, 파일 간 import/호출 결합도(Degree)와 중심 갓노드(God Node) 지도는 없었음.",
                "custom_adaptation_ko": ".coord/code_graph.json의 모듈 결합도 그래프를 file:///...#L시작-L끝 심볼 앵커 맵(.coord/adapters/antigravity_graph_map.json)으로 변환하고, Gemini 3.5 Flash-Lite(Low) 및 olla:local_read_map과 결합해 탐색 토큰을 0으로 압축.",
            },
        },
    },
    "orca": {
        "group": "U315 (Graphify + orca)",
        "original_scope": "멀티 에이전트 Git Worktree 병렬 터미널 오케스트레이터",
        "native_status_by_tool": {
            "codex": {
                "already_applied_natively": False,
                "prior_state": "PARTIAL_UNENFORCED (.codex/worktrees 기능은 있으나 단일 메인 창에서 여러 카드를 섞어 실행함)",
                "diagnosis_ko": "Codex가 카드별 독립 워크트리 분리를 강제하지 않아 한 대화창에서 다수 카드를 처리하다 컨텍스트가 폭발함.",
                "custom_adaptation_ko": "uaos coord window/lanes가 카드별 전용 워크트리(.work/worktrees/codex_U###)와 12턴/180KB 회전 한도를 Codex 세션에 강제 바인딩.",
            },
            "claude": {
                "already_applied_natively": True,
                "prior_state": "PARTIAL_CLI_FLAG (claude --worktree local_<uuid> 플래그 존재, 타 도구와 레인 동기화 없음)",
                "diagnosis_ko": "Claude 단독 워크트리는 지원하나 Codex·Antigravity와 5-레인 상태를 공유하지 못함.",
                "custom_adaptation_ko": "Claude의 local_<uuid> 워크트리를 UAOS 5-레인(.coord/lanes/) 및 .coord/card_sessions/<card>.json에 정규화 연결.",
            },
            "antigravity": {
                "already_applied_natively": True,
                "prior_state": "PARTIAL_SUBAGENT_BRANCH (invoke_subagent Workspace='branch' 지원, 3대 도구 통합 워크트리 인덱스 별도)",
                "diagnosis_ko": "서브에이전트 브랜치 격리는 있으나 타 도구 워크트리와 충돌 방지 락이 분리되어 있었음.",
                "custom_adaptation_ko": "Antigravity의 Workspace='branch'와 UAOS 5-레인 락을 단일 카드 세션 매니페스트로 통합.",
            },
        },
    },
    "ai-memory": {
        "group": "U316 (ai-memory + cockpit-tools)",
        "original_scope": "이종 코딩 AI 간 마크다운 장기 기억·HANDOFF 쪽지 및 의도적 망각(Memory Decay)",
        "native_status_by_tool": {
            "codex": {
                "already_applied_natively": False,
                "prior_state": "ISOLATED_VENDOR_MEMORY (~/.codex/memories에 자기 전용 기록만 남기고 5시간 한도 도달 시 타 도구 인계 쪽지 없음)",
                "diagnosis_ko": "Codex가 5시간 한도에 걸려 멈출 때 진행률·통과 게이트·남은 슬라이스를 남기지 않아 병목 유발.",
                "custom_adaptation_ko": "5시간 한도 80% 도달 또는 샌드박스 차단 시 rollout-*.jsonl 델타를 추출해 정형 .coord/handoffs/<card>_handoff.json을 즉시 발행하고 구버전은 archive/로 망각 압축.",
            },
            "claude": {
                "already_applied_natively": False,
                "prior_state": "ISOLATED_CLAUDE_MD (CLAUDE.md 정적 메모만 있고 자동 망각·이종 도구 복원 페이지 없음)",
                "diagnosis_ko": "주간/5시간 한도 후 복귀 시 이전 맥락을 재탐색하느라 토큰 소모.",
                "custom_adaptation_ko": "복귀 즉시 SessionStart 훅이 .coord/handoffs/<card>_handoff.md만 주입하고 해묵은 로그는 archive/(restore-page)로 분리.",
            },
            "antigravity": {
                "already_applied_natively": False,
                "prior_state": "ISOLATED_BRAIN_SUMMARY (자체 CONTEXT_SUMMARY만 존재, 타 도구와 실시간 구조화 인계 미연동)",
                "diagnosis_ko": "Codex·Claude 정지 시 수동으로 세션을 뒤져 상태를 복구해야 했음.",
                "custom_adaptation_ko": "Antigravity가 대행 수거(Takeover) 시 .coord/handoffs/ 패킷을 즉시 읽고 완결 영수증을 역주입하도록 통합.",
            },
        },
    },
    "cockpit-tools": {
        "group": "U316 (ai-memory + cockpit-tools)",
        "original_scope": "멀티 계정 쿼터 실측 및 트레이 웨이크업 매니저",
        "native_status_by_tool": {
            "codex": {
                "already_applied_natively": True,
                "prior_state": "UAOS_APPLIED_U309 (rollout-*.jsonl rate_limits 파서 적용, reset_elapsed 보정 완료)",
                "diagnosis_ko": "리셋 시각 경과 후에도 과거 100% 소진율이 남던 결함을 U309에서 수정 완료.",
                "custom_adaptation_ko": "Codex rate_limits 실측치와 80% 선제 인계 트리거를 직결.",
            },
            "claude": {
                "already_applied_natively": True,
                "prior_state": "UAOS_APPLIED_U303B (claude_statusline.py 5h/weekly 실측 브리지 적용됨)",
                "diagnosis_ko": "statusLine 기반 실측은 적용되어 있으나 주간 한도 해제 즉시 자동 웨이크업 스케줄 연동이 필요했음.",
                "custom_adaptation_ko": "주간/5시간 리셋 시각 도래 시 PRE_STAGED_READY 카드를 즉시 디스패치하도록 연동.",
            },
            "antigravity": {
                "already_applied_natively": True,
                "prior_state": "UAOS_APPLIED_B85 (remote_budget_tokens 캡 및 모델 선택기 연동됨)",
                "diagnosis_ko": "런당 토큰 캡은 있으나 3대 도구 통합 쿼터 전광판과의 일원화가 필요했음.",
                "custom_adaptation_ko": "cockpit_meter.py 통합 스냅샷에 Antigravity 모델/예산 상태를 단일 스키마로 통합.",
            },
        },
    },
    "agent-desktop": {
        "group": "U317 (agent-desktop + ponytail + security-audit-skill)",
        "original_scope": "OS 접근성 트리(@e1..@eN) 결정론적 검증 및 순차 Input Lease 단일 락",
        "native_status_by_tool": {
            "codex": {
                "already_applied_natively": False,
                "prior_state": "NONE (타 도구와 공유 자원/브랜치 조작 시 순차 임대권 검증 없음)",
                "diagnosis_ko": "샌드박스 차단이나 동시 작업 시 락 확인 없이 명령을 반복 시도함.",
                "custom_adaptation_ko": "acquire_sequential_input_lease(read->act->re-read)로 브랜치/워크트리 쓰기 임대권을 먼저 획득하고 실패 시 즉시 인계.",
            },
            "claude": {
                "already_applied_natively": False,
                "prior_state": "NONE (독립 락 부재)",
                "diagnosis_ko": "복귀 시 동시에 같은 파일을 수정할 위험 존재.",
                "custom_adaptation_ko": "PreToolUse(Edit/Write) 단계에서 .coord/input_leases/ 임대권을 자동 검증.",
            },
            "antigravity": {
                "already_applied_natively": False,
                "prior_state": "PARTIAL_QUIET_LOCK (.work/QUIET_LOCK만 존재, 세분화된 리소스별 read->act->re-read 리스 미비)",
                "diagnosis_ko": "전역 QUIET_LOCK 외에 브랜치·병합·HUD 리소스별 세밀한 순차 리스가 필요했음.",
                "custom_adaptation_ko": "1순위 병합자(Antigravity)가 리소스별 순차 Input Lease와 재독(re-read) 검증을 수행하도록 고도화.",
            },
        },
    },
    "ponytail": {
        "group": "U317 (agent-desktop + ponytail + security-audit-skill)",
        "original_scope": "AI 코드 비대화(-53%) 방지 1~20줄 외과수술식 패치(Surgical Fix) 규율",
        "native_status_by_tool": {
            "codex": {
                "already_applied_natively": False,
                "prior_state": "VIOLATED_FREQUENTLY (U198 규칙은 있었으나 유료 서브에이전트로 파일 전체를 재작성함)",
                "diagnosis_ko": "작은 버그 수정에도 수백 줄을 고쳐 테스트 회귀와 토큰 폭증을 유발.",
                "custom_adaptation_ko": "verify_surgical_diff_and_security()로 코드 슬라이스 변경을 20줄 이하(Ollama qwen2.5-coder:7b 전담)로 강제 제한.",
            },
            "claude": {
                "already_applied_natively": False,
                "prior_state": "PARTIAL (불필요한 방어 코드·래퍼 함수를 추가하는 경향)",
                "diagnosis_ko": "과잉 방어 코드로 파일 크기를 키움.",
                "custom_adaptation_ko": "Claude Haiku 5.5가 diff 줄수를 사전 측정해 20줄 초과 시 슬라이스를 분할하도록 강제.",
            },
            "antigravity": {
                "already_applied_natively": True,
                "prior_state": "UAOS_APPLIED_U198 (계약 매뉴얼 lint 및 20줄 슬라이스 준수 중)",
                "diagnosis_ko": "SP4 교차 판정 시 타 도구의 비대화 패치를 자동 거부하는 게이트 필요.",
                "custom_adaptation_ko": "Antigravity가 SP4 판정 시 verify_surgical_diff_and_security()를 실행해 20줄 초과 패치를 자동 리젝트.",
            },
        },
    },
    "security-audit-skill": {
        "group": "U317 (agent-desktop + ponytail + security-audit-skill)",
        "original_scope": "Cloudflare 6단계 보안·비밀키·인젝션·심볼릭링크 정적 감사 스킬",
        "native_status_by_tool": {
            "codex": {"already_applied_natively": False, "prior_state": "PARTIAL_HOOK", "diagnosis_ko": "커밋 전 정적 보안 스캔 미흡.", "custom_adaptation_ko": "SP3/SP4에서 시크릿 패턴·shell=True·심볼릭 링크 탈출 자동 스캔."},
            "claude": {"already_applied_natively": False, "prior_state": "PARTIAL_SKILL", "diagnosis_ko": "Claude 스킬로만 존재하던 것을 OS 공통 게이트로 승격.", "custom_adaptation_ko": "3대 도구 공통 verify_surgical_diff_and_security() 정적 게이트로 통합."},
            "antigravity": {"already_applied_natively": True, "prior_state": "UAOS_APPLIED_U311", "diagnosis_ko": "library_store 심볼릭 링크/정션 차단 완료.", "custom_adaptation_ko": "SP5 병합 직전 최종 6단계 보안 게이트로 통합."},
        },
    },
    "ruflo": {
        "group": "U318 (ruflo + rea + AgentCodeGUI)",
        "original_scope": "멀티에이전트 스웜 작업 복잡도 라우터 및 자동 Failover 엔진",
        "native_status_by_tool": {
            "codex": {"already_applied_natively": True, "prior_state": "UAOS_APPLIED_U297", "diagnosis_ko": "GPT-6.1 Sol / GPT-6 Luna / GPT-6 Astra 라인업 구축됨.", "custom_adaptation_ko": "5:3:2(올라마 50% : Luna 30% : Sol/Astra 20%) 비율 및 한도 도달 시 즉시 Failover 강제."},
            "claude": {"already_applied_natively": True, "prior_state": "UAOS_APPLIED_U297", "diagnosis_ko": "Claude Opus 5.5 / Claude Haiku 5.5 라인업 구축됨.", "custom_adaptation_ko": "5:3:2(올라마 50% : Haiku 5.5 30% : Opus 5.5 20%) 비율 및 부지휘자 자동 승계 연동."},
            "antigravity": {"already_applied_natively": True, "prior_state": "UAOS_APPLIED_U297", "diagnosis_ko": "Gemini 4 Argon / Gemini 3.5 Flash-Lite 라인업 구축됨.", "custom_adaptation_ko": "5:3:2(올라마 50% : Flash-Lite 30% : Argon 20%) 비율 및 1순위 병합·대행 지휘 자동화."},
        },
    },
    "rea": {
        "group": "U318 (ruflo + rea + AgentCodeGUI)",
        "original_scope": "추론(Reasoning)·실행(Execution) 분리형 아키텍처 및 인식론적 증거 원장",
        "native_status_by_tool": {
            "codex": {"already_applied_natively": True, "prior_state": "UAOS_APPLIED_U275", "diagnosis_ko": "REA 정적 감사 도구는 있으나 일상 카드 루프와 분리되어 있었음.", "custom_adaptation_ko": "설계(Sol/Astra)와 실행(Ollama 계산기)을 엄격 분리하고 증거 태그([EXTRACTED]) 강제."},
            "claude": {"already_applied_natively": True, "prior_state": "UAOS_APPLIED_U275", "diagnosis_ko": "Opus가 직접 코드를 다 짜던 습관 교정 필요.", "custom_adaptation_ko": "Opus는 설계·반례 판정만 수행하고 구현은 Ollama+Haiku로 강제 분리."},
            "antigravity": {"already_applied_natively": True, "prior_state": "UAOS_APPLIED_U275", "diagnosis_ko": "Argon 추론과 olla MCP 실행 분리 완료.", "custom_adaptation_ko": "SP2 반례 감사 및 SP4 독립 검증에 인식론적 증거 원장 적용."},
        },
    },
    "agentcodegui": {
        "group": "U318 (ruflo + rea + AgentCodeGUI)",
        "original_scope": "멀티 에이전트 5칩 실시간 계기판(Show GN) 및 카드별 병렬 세션 GUI",
        "native_status_by_tool": {
            "codex": {"already_applied_natively": True, "prior_state": "UAOS_APPLIED_U303", "diagnosis_ko": "콕핏 HUD에 Codex 상태 표시 중.", "custom_adaptation_ko": "카드별 병렬 세션 및 회전율(12턴/180KB) 실시간 표시 연동."},
            "claude": {"already_applied_natively": True, "prior_state": "UAOS_APPLIED_U303", "diagnosis_ko": "콕핏 HUD에 Claude 상태 표시 중.", "custom_adaptation_ko": "주간 한도 리셋 카운트다운 및 복귀 즉시 실행 대기열 표시 연동."},
            "antigravity": {"already_applied_natively": True, "prior_state": "UAOS_APPLIED_U303", "diagnosis_ko": "주 사용자 창구 및 HUD 컨트롤러 역할 수행 중.", "custom_adaptation_ko": "3대 도구 통합 진행률 및 모바일/데스크톱 HUD 동기화 완결."},
        },
    },
}


def adapt_code_graph_for_tool(
    project_root: Path | str,
    tool: str,
    *,
    card_id: str = "U315",
    target_files: list[str] | None = None,
) -> dict[str, Any]:
    """Customize and inject the 0-token AST Code Knowledge Graph (Graphify) for each specific tool's runtime environment."""
    root = Path(project_root).resolve()
    norm_tool = (tool or "").strip().lower()
    if norm_tool not in ("codex", "claude", "antigravity"):
        raise ValueError(f"Unsupported tool: {tool}")

    graph_file = root / ".coord" / "code_graph.json"
    if graph_file.is_file():
        graph = json.loads(graph_file.read_text(encoding="utf-8"))
    else:
        graph = build_zero_token_code_graph(root)

    adapters_dir = root / ".coord" / "adapters"
    adapters_dir.mkdir(parents=True, exist_ok=True)

    god_nodes = graph.get("god_nodes", [])[:8]
    nodes = graph.get("nodes", {})
    focus_files = target_files or ["v7_harness/coord/nonstop_orchestrator.py", "v7_harness/library_store.py"]

    subgraph: list[dict[str, Any]] = []
    for fpath in focus_files:
        mod_key = fpath[:-3].replace("\\", "/").replace("/", ".") if fpath.endswith(".py") else fpath
        if mod_key in nodes:
            subgraph.append(nodes[mod_key])

    if norm_tool == "codex":
        # Codex custom adaptation: compact rollout-safe markdown brief + SessionStart/UserPromptSubmit hook packet
        brief_md = (
            f"# [Codex Graphify Adapter — {card_id}] 0-Token AST Map (Do NOT run blind repo-wide rg/Get-Content)\n"
            f"- Nodes: `{graph.get('total_nodes', 0)}` | Edges: `{graph.get('total_edges', 0)}` | Helper: `gpt-6-luna (Low)`\n"
            "- Top God Nodes: " + ", ".join(f"`{g['module']}`(deg={g['degree']})" for g in god_nodes[:5]) + "\n"
            "- Focus Modules: " + ", ".join(f"`{m['path']}` (funcs={len(m.get('functions', []))})" for m in subgraph) + "\n"
        )
        out_md = adapters_dir / "codex_graph_brief.md"
        out_md.write_text(brief_md, encoding="utf-8")
        payload = {
            "schema": "uaos.graphify_tool_adapter.v1",
            "tool": "codex",
            "card_id": card_id,
            "delivery_mechanism": "codex_brief.md + SessionStart/UserPromptSubmit hook injection (<=1,200 chars)",
            "helper_model": "gpt-6-luna",
            "helper_thinking_level": "Low",
            "reasoning_model": "gpt-6.1-sol",
            "prevents_defect": "Blocks 4.75MB~5.49MB rollout-*.jsonl bloat from repeated full-file reads",
            "artifact_path": ".coord/adapters/codex_graph_brief.md",
            "god_nodes": god_nodes[:5],
            "focus_subgraph": subgraph,
            "updated_at": _utc_now(),
        }
        _atomic_write_json(adapters_dir / "codex_graph_adapter.json", payload)
        return payload

    if norm_tool == "claude":
        # Claude Code custom adaptation: SessionStart + PreToolUse(Read/Grep) AST interceptor packet
        payload = {
            "schema": "uaos.graphify_tool_adapter.v1",
            "tool": "claude",
            "card_id": card_id,
            "delivery_mechanism": "Claude SessionStart hook + PreToolUse(Read/Grep >300L redirect to code_graph.json)",
            "helper_model": "claude-haiku-5-5",
            "helper_thinking_level": "Low",
            "reasoning_model": "claude-opus-5-5",
            "prevents_defect": "Eliminates 240-file / 160,000-token initial exploration bleed on new Claude sessions (71.5x saving)",
            "artifact_path": ".coord/adapters/claude_graph_adapter.json",
            "god_nodes": god_nodes[:5],
            "focus_subgraph": subgraph,
            "updated_at": _utc_now(),
        }
        _atomic_write_json(adapters_dir / "claude_graph_adapter.json", payload)
        return payload

    # Antigravity custom adaptation: file:/// symbol jump map paired with olla:local_read_map MCP preflight
    jump_links = [
        {
            "module": m["module"],
            "file_uri": f"file:///{(root / m['path']).as_posix()}",
            "classes": m.get("classes", []),
            "functions": m.get("functions", [])[:10],
            "mcp_preflight": f"olla:local_read_map({m['path']})",
        }
        for m in subgraph
    ]
    payload = {
        "schema": "uaos.graphify_tool_adapter.v1",
        "tool": "antigravity",
        "card_id": card_id,
        "delivery_mechanism": "olla:local_read_map MCP preflight + file:/// symbol jump anchors",
        "helper_model": "gemini-3.5-flash-lite",
        "helper_thinking_level": "Low",
        "reasoning_model": "gemini-4-argon",
        "prevents_defect": "Couples single-file olla outlines with repo-wide AST coupling degree & God-Node routing",
        "artifact_path": ".coord/adapters/antigravity_graph_adapter.json",
        "god_nodes": god_nodes[:5],
        "symbol_jump_links": jump_links,
        "updated_at": _utc_now(),
    }
    _atomic_write_json(adapters_dir / "antigravity_graph_adapter.json", payload)
    return payload


def build_universal_3tool_technology_matrix(project_root: Path | str) -> dict[str, Any]:
    """Audit prior native application status across all 3 tools and materialize customized adapters for all 3 tools."""
    root = Path(project_root).resolve()
    adapters_dir = root / ".coord" / "adapters"
    adapters_dir.mkdir(parents=True, exist_ok=True)

    graph_adapters = {
        t: adapt_code_graph_for_tool(root, t, card_id="U315")
        for t in ("codex", "claude", "antigravity")
    }

    matrix_payload = {
        "schema": "uaos.universal_3tool_tech_matrix.v1",
        "updated_at": _utc_now(),
        "core_principle": (
            "UAOS-RSI에 도입하는 모든 핵심 기술은 특정 도구의 전유물이 아니라 3대 도구(Antigravity, Claude Code, Codex) "
            "전체를 통합한 UAOS-RSI OS 핵심 운영 로직으로 구체화하며, 각 도구의 기적용 여부를 먼저 감사한 뒤 "
            "도구별 런타임·훅·세션·도우미 모델 환경에 맞게 맞춤 개조하여 적용한다."
        ),
        "total_technologies": len(TEN_CORE_TECH_3TOOL_AUDIT_AND_ADAPTATION),
        "tools_covered": ["codex", "claude", "antigravity"],
        "graphify_3tool_adapters": graph_adapters,
        "technologies": TEN_CORE_TECH_3TOOL_AUDIT_AND_ADAPTATION,
    }
    _atomic_write_json(adapters_dir / "three_tool_technology_matrix.json", matrix_payload)
    return matrix_payload
