"""U255: Antigravity Moderator, Mediator, Watchdog, Caretaker, Repairman & Personal Assistant Orchestrator.

Antigravity acts as the continuous UAOS-RSI:
- 사회자 (Moderator): Turn-taking & non-author REVIEW verdict routing (`detect_and_intervene_stalls`)
- 동네 반장 (Neighborhood Chief): Codex/Claude bottleneck & backlog relief + mutual hand-lending (`detect_and_relieve_bottlenecks`)
- 수리공 & 관리인 (Repairman & Caretaker): Reconnecting cut LAN cables (stranded un-ACKed relays), broken dependency bridges, and stale `.work/QUIET_LOCK`s (`repair_broken_bridges_and_lan`)
- 구청공무원 (District Official): 3-tool consensus ledger (`mediate_consensus`) & official audit registry (`.coord/moderator/official_registry.jsonl`)
- 사용자의 비서 (User's Personal Secretary): Utilizing Ollama CLI (`qwen2.5-coder:7b`, 0 paid tokens) and Haiku 5.5 CLI (`claude-haiku-4-5-20251001`, <=12,000 preflight token gate) to auto-draft lint-valid failover/assist contract manuals (`detect_and_handle_quota_limits`, `PersonalAssistantOrchestrator`).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from .mailbox import Mailbox
from .next_card import coord_root
from .presence import TOOLS, read_all
from .stall import CAPABILITY, HUMAN_ONLY_RE
from .stream import _exclusive

TERMINAL = ("DONE", "DONE_SCOPED", "DONE_ELSEWHERE", "RETIRED", "SUPERSEDED")
UNAVAILABLE_STATES = ("LIMITED", "ABSENT", "EXHAUSTED", "QUOTA")
VERDICT_PEERS = ("codex", "claude", "antigravity")

DEFAULT_OLLAMA_MODEL = "qwen2.5-coder:7b"
DEFAULT_HAIKU_MODEL = "claude-haiku-5-5"
MAX_HAIKU_PREFLIGHT_TOKENS = 12000
DEFAULT_STALL_THRESHOLD_S = 60.0
DEFAULT_LAN_CUT_THRESHOLD_S = 30.0
DEFAULT_MAX_LAN_AGE_S = 3600.0
DEFAULT_QUIET_LOCK_MAX_AGE_S = 3600.0
MAX_CONSENSUS_TURNS = 5
UAOS_CORE_FOUNDING_PRINCIPLE = (
    "최대 성과를 목표로 3대 AI 도구 (Antigravity, Claude Code, Codex)의 부족한 토큰예산을 절약하는 "
    "3대 AI도구 '병렬'-협업-운영시스템, 하지만 결과물의 최상의 품질기준이 근본 존재이유이다."
)
UAOS_CORE_FINANCIAL_FRAME = (
    "UAOS의 핵심 목표는 최대성과, 고품질의 결과를 도출하는 것이며, 사용량 제한 및 구독제 업그레이드의 "
    "재정적 부담으로 UAOS-RSI 운영 시스템을 만든 것이다."
)
CODEX_EXCLUSIVE_KEYPOINTS = frozenset(
    {
        "architectural_core",
        "security_boundary",
        "rsi_canon",
        "p1_escalation",
        "final_quality_audit",
        "tie_break",
    }
)
PRIMARY_SOURCES_DEFAULT = (
    "https://zdnet.co.kr/view/?no=20261019165618",
    "https://github.com/langchain-ai/langgraph-supervisor-py",
    "https://github.com/microsoft/autogen",
    "https://github.com/SmartManoj/openrig",
    "https://github.com/Showgn/agentic-ai-orchestration-platform",
    "https://github.com/morluto/rea",
)


def estimate_tokens(text: str) -> int:
    """Conservative UTF-8 token estimate (~3 bytes per token, minimum 1 for non-empty)."""
    if not text:
        return 0
    raw_len = len(text.encode("utf-8"))
    return max(1, (raw_len + 2) // 3)


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2))
        handle.flush()
        os.fsync(handle.fileno())
    for _ in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.01)
    os.replace(tmp, path)


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


KEYPOINT_CANON_PATHS = (
    "uaos_global_rule_block.md",
    "uaos_everywhere/adapters/",
    "firewall_audit.py",
    "calculator_gate.py",
    "binding_gate.py",
    "stop_gate.py",
    "sandbox",
)


def is_codex_exclusive_keypoint(phase: dict[str, Any]) -> bool:
    """Return True if phase requires Codex's core architectural/security/canon judgment ($20 Plus Astra keypoint)."""
    if not isinstance(phase, dict):
        return False
    if phase.get("codex_keypoint") is True:
        return True
    tier = str(phase.get("tier") or "").strip().lower()
    kind = str(phase.get("kind") or "").strip().lower()
    if tier in CODEX_EXCLUSIVE_KEYPOINTS or kind in CODEX_EXCLUSIVE_KEYPOINTS:
        return True
    tags = {str(t).strip().lower() for t in (phase.get("tags") or []) if t}
    if tags & CODEX_EXCLUSIVE_KEYPOINTS:
        return True
    file_fields = (
        list(phase.get("files") or [])
        + list(phase.get("changed_files") or [])
        + list(phase.get("allowed_files") or [])
        + list(phase.get("paths") or [])
    )
    for f in file_fields:
        norm = str(f).replace("\\", "/").lower()
        if any(pat.lower() in norm for pat in KEYPOINT_CANON_PATHS):
            return True
    if phase.get("routine_approval") is True or phase.get("codex_keypoint") is False:
        return False
    blob = f"{phase.get('title', '')} {phase.get('note', '')}".lower()
    return any(kp in blob for kp in CODEX_EXCLUSIVE_KEYPOINTS)


def verify_supreme_quality_gate(phase: dict[str, Any], *, judge_tool: str = "") -> dict[str, Any]:
    """Enforce UAOS-RSI's supreme quality invariant before any peer approval is accepted."""
    excluded = {str(phase.get("author_tool") or ""), str(phase.get("owner_tool") or "")} - {""}
    if judge_tool and judge_tool in excluded:
        return {
            "ok": False,
            "error": "SELF_APPROVAL_FORBIDDEN",
            "founding_principle": UAOS_CORE_FOUNDING_PRINCIPLE,
        }
    if phase.get("require_accept_cmd", False) and not str(phase.get("accept_cmd") or "").strip():
        return {
            "ok": False,
            "error": "MISSING_ACCEPT_CMD",
            "founding_principle": UAOS_CORE_FOUNDING_PRINCIPLE,
        }
    exit_code = phase.get("accept_exit_code")
    if exit_code is not None and int(exit_code) != 0:
        return {
            "ok": False,
            "error": "ACCEPT_GATE_FAILED",
            "founding_principle": UAOS_CORE_FOUNDING_PRINCIPLE,
        }
    if int(phase.get("tests_failed") or 0) > 0:
        return {
            "ok": False,
            "error": "TESTS_FAILED",
            "founding_principle": UAOS_CORE_FOUNDING_PRINCIPLE,
        }
    if phase.get("require_primary_sources", False) and not (phase.get("primary_source_urls") or []):
        return {
            "ok": False,
            "error": "MISSING_PRIMARY_SOURCES",
            "founding_principle": UAOS_CORE_FOUNDING_PRINCIPLE,
        }
    has_evidence = (
        bool(str(phase.get("accept_cmd") or "").strip())
        and phase.get("accept_exit_code") is not None
        and int(phase.get("accept_exit_code")) == 0
    )
    return {
        "ok": True,
        "verdict": "PASS" if has_evidence else "UNKNOWN",
        "founding_principle": UAOS_CORE_FOUNDING_PRINCIPLE,
        "financial_frame": UAOS_CORE_FINANCIAL_FRAME,
        "judge_tool": judge_tool,
    }


class PersonalAssistantOrchestrator:
    """Antigravity's personal secretary router using Ollama CLI (0 paid tokens) and Haiku 5.5 CLI."""

    def __init__(
        self,
        project_root: Path | str,
        *,
        ollama_model: str = DEFAULT_OLLAMA_MODEL,
        haiku_model: str = DEFAULT_HAIKU_MODEL,
        haiku_token_cap: int = MAX_HAIKU_PREFLIGHT_TOKENS,
        runner: Callable[..., Any] | None = None,
    ) -> None:
        self.project_root = coord_root(Path(project_root))
        self.ollama_model = ollama_model
        self.haiku_model = haiku_model
        self.haiku_token_cap = int(haiku_token_cap)
        self.runner = runner or subprocess.run

    def _journal_attempt(
        self,
        *,
        work_id: str,
        worker: str,
        model: str,
        input_hash: str,
        wall_time_s: float,
        input_tokens: int,
        output_tokens: int,
        outcome: str,
        error_class: str | None = None,
    ) -> None:
        usage_dir = self.project_root / ".coord" / "usage"
        usage_dir.mkdir(parents=True, exist_ok=True)
        lock_file = usage_dir / ".runs.lock"
        ledger_file = usage_dir / "runs.jsonl"
        row = {
            "ts": time.time(),
            "caller": "antigravity-moderator",
            "project": self.project_root.name,
            "work_id": work_id,
            "worker": worker,
            "model": model,
            "input_hash": input_hash,
            "wall_time_s": round(wall_time_s, 4),
            "input_tokens": int(input_tokens),
            "output_tokens": int(output_tokens),
            "outcome": outcome,
            "error_class": error_class,
        }
        with _exclusive(lock_file):
            with ledger_file.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())

    def call_ollama_cli(self, *, work_id: str, prompt: str, timeout_s: float = 30.0) -> dict[str, Any]:
        """Run a fixed-input operation on Ollama CLI at 0 paid tokens."""
        t0 = time.time()
        in_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
        in_tokens = estimate_tokens(prompt)
        ollama_bin = shutil.which("ollama") or "ollama"
        argv = [ollama_bin, "run", self.ollama_model, prompt]
        try:
            cp = self.runner(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
            )
        except Exception as exc:
            wall = time.time() - t0
            self._journal_attempt(
                work_id=work_id,
                worker="ollama",
                model=self.ollama_model,
                input_hash=in_hash,
                wall_time_s=wall,
                input_tokens=in_tokens,
                output_tokens=0,
                outcome="FAILED",
                error_class=type(exc).__name__,
            )
            return {"ok": False, "assistant": "ollama", "error": str(exc), "output": ""}

        rc = int(getattr(cp, "returncode", 1))
        out = (getattr(cp, "stdout", "") or "").strip()
        err = (getattr(cp, "stderr", "") or "").strip()
        wall = time.time() - t0
        if rc != 0 or not out:
            self._journal_attempt(
                work_id=work_id,
                worker="ollama",
                model=self.ollama_model,
                input_hash=in_hash,
                wall_time_s=wall,
                input_tokens=in_tokens,
                output_tokens=0,
                outcome="FAILED",
                error_class=f"RC_{rc}" if rc != 0 else "EMPTY_OUTPUT",
            )
            return {"ok": False, "assistant": "ollama", "error": err or f"rc={rc}", "output": ""}

        out_tokens = estimate_tokens(out)
        self._journal_attempt(
            work_id=work_id,
            worker="ollama",
            model=self.ollama_model,
            input_hash=in_hash,
            wall_time_s=wall,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            outcome="PASS",
        )
        return {"ok": True, "assistant": "ollama", "model": self.ollama_model, "output": out}

    def call_haiku_cli(self, *, work_id: str, prompt: str, timeout_s: float = 30.0) -> dict[str, Any]:
        """Run a bounded personal-assistant call on Haiku 5.5 CLI under the 12,000-token preflight gate."""
        t0 = time.time()
        in_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
        in_tokens = estimate_tokens(prompt)
        if in_tokens > self.haiku_token_cap:
            self._journal_attempt(
                work_id=work_id,
                worker="haiku",
                model=self.haiku_model,
                input_hash=in_hash,
                wall_time_s=0.0,
                input_tokens=in_tokens,
                output_tokens=0,
                outcome="BLOCKED",
                error_class="PREFLIGHT_TOKEN_CAP_EXCEEDED",
            )
            return {
                "ok": False,
                "assistant": "haiku",
                "error": "PREFLIGHT_TOKEN_CAP_EXCEEDED",
                "estimated_tokens": in_tokens,
                "cap": self.haiku_token_cap,
                "output": "",
            }

        claude_bin = shutil.which("claude") or "claude"
        argv = [claude_bin, "-p", prompt, "--model", self.haiku_model, "--output-format", "json"]
        try:
            cp = self.runner(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
            )
        except Exception as exc:
            wall = time.time() - t0
            self._journal_attempt(
                work_id=work_id,
                worker="haiku",
                model=self.haiku_model,
                input_hash=in_hash,
                wall_time_s=wall,
                input_tokens=in_tokens,
                output_tokens=0,
                outcome="FAILED",
                error_class=type(exc).__name__,
            )
            return {"ok": False, "assistant": "haiku", "error": str(exc), "output": ""}

        rc = int(getattr(cp, "returncode", 1))
        stdout = (getattr(cp, "stdout", "") or "").strip()
        stderr = (getattr(cp, "stderr", "") or "").strip()
        wall = time.time() - t0
        if rc != 0 or not stdout:
            self._journal_attempt(
                work_id=work_id,
                worker="haiku",
                model=self.haiku_model,
                input_hash=in_hash,
                wall_time_s=wall,
                input_tokens=in_tokens,
                output_tokens=0,
                outcome="FAILED",
                error_class=f"RC_{rc}" if rc != 0 else "EMPTY_OUTPUT",
            )
            return {"ok": False, "assistant": "haiku", "error": stderr or f"rc={rc}", "output": ""}

        parsed = None
        try:
            parsed = json.loads(stdout)
            text = str(parsed.get("result", stdout)) if isinstance(parsed, dict) else stdout
        except ValueError:
            text = stdout

        if isinstance(parsed, dict) and isinstance(parsed.get("usage"), dict):
            u = parsed["usage"]
            reported_total = sum(
                int(u.get(k) or 0)
                for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
            )
            if reported_total > self.haiku_token_cap:
                self._journal_attempt(
                    work_id=work_id,
                    worker="haiku",
                    model=self.haiku_model,
                    input_hash=in_hash,
                    wall_time_s=wall,
                    input_tokens=int(u.get("input_tokens") or in_tokens),
                    output_tokens=int(u.get("output_tokens") or 0),
                    outcome="BLOCKED",
                    error_class="REPORTED_TOKEN_CAP_EXCEEDED",
                )
                return {
                    "ok": False,
                    "assistant": "haiku",
                    "error": "REPORTED_TOKEN_CAP_EXCEEDED",
                    "reported_tokens": reported_total,
                    "cap": self.haiku_token_cap,
                    "output": "",
                }

        out_tokens = estimate_tokens(text)
        self._journal_attempt(
            work_id=work_id,
            worker="haiku",
            model=self.haiku_model,
            input_hash=in_hash,
            wall_time_s=wall,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            outcome="PASS",
        )
        return {"ok": True, "assistant": "haiku", "model": self.haiku_model, "output": text}

    def draft_failover_manual(
        self,
        *,
        phase: dict[str, Any],
        new_owner: str,
        judge_tool: str,
        unavailable_tool: str,
    ) -> dict[str, Any]:
        """Draft a lint-valid failover contract manual via Ollama CLI -> Haiku 5.5 -> deterministic template."""
        phase_id = str(phase.get("phase_id") or "U000")
        allowed = phase.get("allowed_files") or ["v7_harness/coord/agy_moderator.py"]
        accept_cmd = str(phase.get("acceptance_cmd") or "python -m unittest")
        title = str(phase.get("title") or f"{phase_id} failover continuation")
        prompt = (
            f"Draft a concise 2-sentence English execution summary for UAOS card {phase_id} ({title}) "
            f"reassigned from {unavailable_tool} (LIMITED) to {new_owner} with independent judge {judge_tool}."
        )
        res = self.call_ollama_cli(work_id=f"{phase_id}-MOD-OLLAMA", prompt=prompt)
        if not res["ok"]:
            res = self.call_haiku_cli(work_id=f"{phase_id}-MOD-HAIKU", prompt=prompt)
        assistant_used = res["assistant"] if res["ok"] else "deterministic"
        summary_line = (
            res["output"].splitlines()[0].strip()
            if res["ok"] and res["output"].strip()
            else f"Auto-generated failover manual after {unavailable_tool} became unavailable; {new_owner} executes and {judge_tool} judges."
        )

        inputs_lines: list[str] = []
        for f in allowed:
            fp = self.project_root / f
            if fp.is_file():
                digest = hashlib.sha256(fp.read_bytes()).hexdigest()
                inputs_lines.append(f"- {f} sha256={digest}")
            else:
                inputs_lines.append(f"- {f}")
        inputs_block = "\n".join(inputs_lines)
        allow_block = "\n".join(f"- {f}" for f in allowed)
        src_block = "\n".join(f"- {u}" for u in PRIMARY_SOURCES_DEFAULT)
        content = (
            f"# {phase_id}: {title} (Moderator Failover Contract Manual)\n\n"
            f"## Moderator Summary ({assistant_used})\n"
            f"{summary_line}\n\n"
            f"## Primary Sources\n{src_block}\n\n"
            f"```contract\n"
            f"work_id: {phase_id}\n"
            f"worker: local\n"
            f"goal: {title}\n"
            f"inputs:\n{inputs_block}\n"
            f"allow:\n{allow_block}\n"
            f"acceptance: {accept_cmd}\n"
            f"forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push\n"
            f"stop: two failures with the same cause; input hash mismatch; no output\n"
            f"judge: {judge_tool}\n"
            f"timeout_s: 180\n"
            f"remote_budget_tokens: 0\n"
            f"```\n"
        )
        manual_path = self.project_root / ".coord" / "tasks" / f"{phase_id}-failover-manual.md"
        manual_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = manual_path.with_name(f"{manual_path.name}.{os.getpid()}.tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, manual_path)
        return {
            "phase_id": phase_id,
            "manual_path": str(manual_path),
            "assistant_used": assistant_used,
            "new_owner": new_owner,
            "judge": judge_tool,
        }


class AntigravityModerator:
    """Antigravity Moderator, Mediator, Watchdog, Caretaker, Repairman & District Official (`사회자·중재자·감시자·동네 반장·수리공·관리인·구청공무원`)."""

    def __init__(
        self,
        project_root: Path | str = ".",
        *,
        stall_threshold_s: float = DEFAULT_STALL_THRESHOLD_S,
        lan_cut_threshold_s: float = DEFAULT_LAN_CUT_THRESHOLD_S,
        assistant: PersonalAssistantOrchestrator | None = None,
    ) -> None:
        self.project_root = coord_root(Path(project_root))
        self.stall_threshold_s = float(stall_threshold_s)
        self.lan_cut_threshold_s = float(lan_cut_threshold_s)
        self.assistant = assistant or PersonalAssistantOrchestrator(self.project_root)
        self.schedule_path = self.project_root / ".coord" / "master_schedule.json"
        self.moderator_dir = self.project_root / ".coord" / "moderator"
        self.consensus_path = self.moderator_dir / "consensus_ledger.json"
        self.registry_path = self.moderator_dir / "official_registry.jsonl"

    def _schedule_lock(self) -> Path:
        return self.project_root / ".coord" / "stall" / "stall.lock"

    def _record_official_ledger(self, *, role: str, action: str, details: dict[str, Any], now: float | None = None) -> None:
        """District Official (구청공무원) immutable administrative registry entry."""
        self.moderator_dir.mkdir(parents=True, exist_ok=True)
        lock_file = self.moderator_dir / ".registry.lock"
        row = {
            "ts": time.time() if now is None else now,
            "role": role,
            "action": action,
            "details": details,
        }
        with _exclusive(lock_file):
            with self.registry_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())

    def _emit_wake(
        self,
        *,
        target: str,
        card: str,
        delta: str,
        message: str,
        verdict_requested: bool = False,
    ) -> str:
        mb_dir = self.project_root / ".coord" / "mailbox"
        mb_dir.mkdir(parents=True, exist_ok=True)
        box = Mailbox(mb_dir)
        digest = hashlib.sha256(f"mod:{target}:{card}:{delta}:{message}".encode("utf-8")).hexdigest()
        msg_id = f"relay_{digest[:32]}"
        if not box.has_message(msg_id):
            payload: dict[str, Any] = {
                "kind": "HANDOFF",
                "actor": "antigravity",
                "moderator": True,
                "requested_target": target,
                "card": card,
                "wake_class": "ACTIONABLE",
                "delta": delta[:200],
                "message": message,
                "digest": digest,
            }
            if verdict_requested:
                payload["verdict_requested"] = True
            box.publish(msg_id, payload)
        return msg_id

    def detect_and_intervene_stalls(
        self,
        *,
        desk: dict[str, dict[str, Any]] | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Detect stalled READY/ACTIVE phases or unassigned REVIEW phases and immediately intervene."""
        moment = time.time() if now is None else now
        if desk is None:
            desk = read_all(self.project_root, now=moment)
        active_tools = [t for t in ("antigravity", "claude", "codex") if (desk.get(t) or {}).get("state") == "ACTIVE"]

        interventions: list[dict[str, Any]] = []
        wakes_sent: list[dict[str, Any]] = []
        lock_path = self._schedule_lock()
        lock_path.parent.mkdir(parents=True, exist_ok=True)

        with _exclusive(lock_path):
            sched = _read_json(self.schedule_path, {"phases": []})
            phases = sched.get("phases") if isinstance(sched, dict) else None
            if not isinstance(phases, list):
                return {"ok": False, "error": "INVALID_SCHEDULE", "interventions": [], "wakes_sent": []}

            changed = False
            for phase in phases:
                if not isinstance(phase, dict) or not phase.get("phase_id"):
                    continue
                pid = str(phase["phase_id"])
                state = str(phase.get("state") or "")
                if state in TERMINAL:
                    continue
                text_blob = f"{pid} {phase.get('human', '')} {phase.get('note', '')} {phase.get('blocker_reason', '')}"
                if state == "HUMAN" or HUMAN_ONLY_RE.search(text_blob):
                    continue

                author = str(phase.get("author_tool") or phase.get("owner_tool") or "")
                excluded_authors = {str(phase.get("author_tool") or ""), str(phase.get("owner_tool") or "")} - {""}
                # Case 1: REVIEW phase without an active non-author reviewer assigned or waiting
                if state == "REVIEW":
                    if phase.get("release_hold") or phase.get("blocker_kind") == "SAFETY_GATE":
                        continue
                    reviewer = str(phase.get("reviewer") or "")
                    waiting_on = str(phase.get("waiting_on") or "")
                    current_judge = reviewer or (waiting_on.split("-")[0] if waiting_on.endswith("-verdict") else "")
                    valid_judges = [t for t in VERDICT_PEERS if t in active_tools and t not in excluded_authors]
                    if not valid_judges:
                        continue
                    chosen_judge = current_judge if current_judge in valid_judges else valid_judges[0]
                    assignment_changed = reviewer != chosen_judge or waiting_on != f"{chosen_judge}-verdict"
                    last_woken = phase.get("moderator_woken_at")
                    already_woken_recently = (
                        not assignment_changed
                        and isinstance(last_woken, (int, float))
                        and not isinstance(last_woken, bool)
                        and (moment - float(last_woken)) < self.stall_threshold_s
                    )
                    if already_woken_recently:
                        continue
                    if assignment_changed:
                        phase["reviewer"] = chosen_judge
                        phase["waiting_on"] = f"{chosen_judge}-verdict"
                        phase["moderated_at"] = moment
                    phase["moderator_woken_at"] = moment
                    changed = True
                    delta = f"MODERATOR VERDICT ASSIGNED: {pid} -> {chosen_judge} (author={author})"
                    msg = (
                        f"ACTIONABLE_DELTA VERDICT_REQUESTED=YES [Antigravity Moderator] Phase {pid} is in REVIEW "
                        f"(author={author}). Assigned non-author judge={chosen_judge} so next_step returns NEXT/VERDICT immediately."
                    )
                    relay_id = self._emit_wake(
                        target=chosen_judge,
                        card=pid,
                        delta=delta,
                        message=msg,
                        verdict_requested=True,
                    )
                    interventions.append(
                        {"phase_id": pid, "kind": "REVIEW_VERDICT_ASSIGNED", "judge": chosen_judge, "author": author}
                    )
                    wakes_sent.append({"phase_id": pid, "target": chosen_judge, "relay_id": relay_id})
                    continue

                # Case 2: READY or stalled ACTIVE phase whose owner is idle past stall_threshold_s
                if state in ("READY", "ACTIVE"):
                    owner = str(phase.get("owner_tool") or "")
                    owner_state = str((desk.get(owner) or {}).get("state") or "UNKNOWN").upper()
                    # Authority rule: UNKNOWN is no ground for acting/rerouting
                    if owner_state == "UNKNOWN":
                        continue
                    since_raw = phase.get("waiting_since") or phase.get("started_at") or phase.get("updated_at")
                    if not isinstance(since_raw, (int, float)) or isinstance(since_raw, bool):
                        continue
                    age_s = moment - float(since_raw)
                    if age_s < self.stall_threshold_s:
                        continue
                    target = owner if owner in active_tools else (active_tools[0] if (owner_state in UNAVAILABLE_STATES and active_tools) else "")
                    if not target:
                        continue
                    if target != owner:
                        phase["rerouted_from"] = {"owner_tool": owner, "state": state}
                        phase["owner_tool"] = target
                        phase["state"] = "READY"
                        phase["moderated_at"] = moment
                        changed = True
                    delta = f"MODERATOR STALL PROD: {pid} -> {target} (idle {int(age_s)}s)"
                    msg = (
                        f"ACTIONABLE_DELTA [Antigravity Moderator] Phase {pid} was idle for {int(age_s)}s "
                        f"(>{int(self.stall_threshold_s)}s). Immediate execution required by {target}."
                    )
                    relay_id = self._emit_wake(target=target, card=pid, delta=delta, message=msg)
                    interventions.append(
                        {"phase_id": pid, "kind": "STALL_PRODDED", "owner": target, "age_s": round(age_s, 1)}
                    )
                    wakes_sent.append({"phase_id": pid, "target": target, "relay_id": relay_id})

            if changed:
                _atomic_write_json(self.schedule_path, sched)

        return {
            "ok": True,
            "active_tools": active_tools,
            "interventions": interventions,
            "wakes_sent": wakes_sent,
        }

    def _unacked_actionable_counts(self) -> dict[str, int]:
        counts = {t: 0 for t in TOOLS}
        inbox_dir = self.project_root / ".coord" / "mailbox" / "inbox"
        ack_dir = self.project_root / ".coord" / "mailbox" / "ack"
        if not inbox_dir.is_dir():
            return counts
        for p in inbox_dir.glob("*.json"):
            mid = p.stem
            if (ack_dir / f"{mid}.json").is_file():
                continue
            doc = _read_json(p, {})
            payload = doc.get("payload") if isinstance(doc, dict) else {}
            if not isinstance(payload, dict):
                continue
            if payload.get("wake_class") != "ACTIONABLE":
                continue
            target = str(payload.get("requested_target") or "")
            if target in counts:
                counts[target] += 1
        return counts

    def detect_and_relieve_bottlenecks(
        self,
        *,
        desk: dict[str, dict[str, Any]] | None = None,
        review_bottleneck_threshold: int = 1,
        backlog_threshold: int = 2,
        now: float | None = None,
    ) -> dict[str, Any]:
        """동네 반장 (Neighborhood Chief): Relieve Codex/Claude bottlenecks & lend a hand when one tool is overloaded.

        1. REVIEW Bottleneck Relief: When a judge (e.g. `codex`) has > `review_bottleneck_threshold` REVIEW cards
           queued (or un-ACKed letter backlog >= `backlog_threshold` or an ACTIVE card in flight), offload excess
           REVIEW verdicts to an unsaturated ACTIVE non-author peer (`author != judge`).
        2. READY Workload Assist (일손 돕기): When a tool (`codex`, `claude`, or `antigravity`) is busy on an ACTIVE
           phase or has > 1 READY/ACTIVE phases or letter backlog >= `backlog_threshold`, dispatch an unsaturated
           ACTIVE helper tool to take ready-to-run disjoint phases (`assisted_by`, `owner_tool = helper`).
        """
        moment = time.time() if now is None else now
        if desk is None:
            desk = read_all(self.project_root, now=moment)
        active_tools = [t for t in ("antigravity", "claude", "codex") if (desk.get(t) or {}).get("state") == "ACTIVE"]
        letter_counts = self._unacked_actionable_counts()

        relieved: list[dict[str, Any]] = []
        wakes_sent: list[dict[str, Any]] = []
        lock_path = self._schedule_lock()
        lock_path.parent.mkdir(parents=True, exist_ok=True)

        with _exclusive(lock_path):
            sched = _read_json(self.schedule_path, {"phases": []})
            phases = sched.get("phases") if isinstance(sched, dict) else None
            if not isinstance(phases, list):
                return {"ok": False, "error": "INVALID_SCHEDULE", "relieved": [], "wakes_sent": []}

            done_ids = {
                str(p.get("phase_id"))
                for p in phases
                if isinstance(p, dict) and str(p.get("state") or "") in TERMINAL
            }
            active_load: dict[str, int] = {t: 0 for t in TOOLS}
            review_load: dict[str, int] = {t: 0 for t in TOOLS}
            claimed_resources: set[str] = set()

            for p in phases:
                if not isinstance(p, dict):
                    continue
                st = str(p.get("state") or "")
                own = str(p.get("owner_tool") or "")
                if st == "ACTIVE" and own in active_load:
                    active_load[own] += 1
                    for res in p.get("allowed_files") or []:
                        claimed_resources.add(str(res))
                elif st == "REVIEW":
                    rev = str(p.get("reviewer") or "")
                    if not rev:
                        wo = str(p.get("waiting_on") or "")
                        if wo.endswith("-verdict"):
                            rev = wo.split("-")[0]
                    if rev in review_load:
                        review_load[rev] += 1

            changed = False
            seen_reviews_per_judge: dict[str, int] = {t: 0 for t in TOOLS}
            seen_work_per_owner: dict[str, int] = {t: active_load.get(t, 0) for t in TOOLS}

            for phase in phases:
                if not isinstance(phase, dict) or not phase.get("phase_id"):
                    continue
                pid = str(phase["phase_id"])
                state = str(phase.get("state") or "")
                if state in TERMINAL:
                    continue
                text_blob = f"{pid} {phase.get('human', '')} {phase.get('note', '')} {phase.get('blocker_reason', '')}"
                if state == "HUMAN" or HUMAN_ONLY_RE.search(text_blob):
                    continue
                if phase.get("release_hold") or phase.get("blocker_kind") == "SAFETY_GATE":
                    continue

                # 1. REVIEW bottleneck offload (especially Codex review queue backup)
                if state == "REVIEW":
                    if phase.get("bottleneck_relieved_from"):
                        continue
                    if is_codex_exclusive_keypoint(phase) and "codex" in active_tools:
                        phase["codex_keypoint_preserved"] = True
                        continue
                    author = str(phase.get("author_tool") or phase.get("owner_tool") or "")
                    excluded_authors = {str(phase.get("author_tool") or ""), str(phase.get("owner_tool") or "")} - {""}
                    wo = str(phase.get("waiting_on") or "")
                    judge = str(phase.get("reviewer") or (wo.split("-")[0] if wo.endswith("-verdict") else ""))
                    if not judge:
                        continue
                    seen_reviews_per_judge[judge] = seen_reviews_per_judge.get(judge, 0) + 1
                    judge_overloaded = (
                        seen_reviews_per_judge[judge] > review_bottleneck_threshold
                        or active_load.get(judge, 0) >= 1
                        or letter_counts.get(judge, 0) >= backlog_threshold
                    )
                    if not judge_overloaded:
                        continue
                    candidates = [
                        t
                        for t in VERDICT_PEERS
                        if t in active_tools
                        and t not in excluded_authors
                        and t != judge
                        and active_load.get(t, 0) == 0
                        and letter_counts.get(t, 0) < backlog_threshold
                    ]
                    if not candidates:
                        continue
                    candidates.sort(key=lambda t: (review_load.get(t, 0) + active_load.get(t, 0) + letter_counts.get(t, 0)))
                    helper_judge = candidates[0]
                    phase["reviewer"] = helper_judge
                    phase["waiting_on"] = f"{helper_judge}-verdict"
                    phase["bottleneck_relieved_from"] = judge
                    phase["moderated_at"] = moment
                    review_load[judge] = max(0, review_load.get(judge, 1) - 1)
                    review_load[helper_judge] = review_load.get(helper_judge, 0) + 1
                    changed = True

                    delta = f"BOTTLENECK VERDICT OFFLOAD: {pid} ({judge}->{helper_judge}, author={author})"
                    msg = (
                        f"ACTIONABLE_DELTA VERDICT_REQUESTED=YES [동네 반장 Bottleneck Relief] Judge {judge} is bottlenecked "
                        f"(active={active_load.get(judge, 0)}, letters={letter_counts.get(judge, 0)}). "
                        f"Offloaded REVIEW verdict for {pid} (author={author}) to {helper_judge}."
                    )
                    relay_id = self._emit_wake(
                        target=helper_judge,
                        card=pid,
                        delta=delta,
                        message=msg,
                        verdict_requested=True,
                    )
                    relieved.append(
                        {
                            "phase_id": pid,
                            "kind": "REVIEW_BOTTLENECK_RELIEVED",
                            "from_tool": judge,
                            "to_tool": helper_judge,
                            "author": author,
                        }
                    )
                    wakes_sent.append({"phase_id": pid, "target": helper_judge, "relay_id": relay_id})
                    continue

                # 2. READY workload assist (한놈의 일손이 모자라면 가서 도와준다)
                if state == "READY" and phase.get("assist") is not False and not phase.get("worktree"):
                    owner = str(phase.get("owner_tool") or "")
                    if not owner:
                        continue
                    deps = [str(d) for d in (phase.get("depends_on") or [])]
                    if any(d not in done_ids for d in deps):
                        continue
                    p_resources = {str(r) for r in (phase.get("allowed_files") or [])}
                    if p_resources & claimed_resources:
                        continue

                    seen_work_per_owner[owner] = seen_work_per_owner.get(owner, 0) + 1
                    owner_saturated = (
                        active_load.get(owner, 0) >= 1
                        and (seen_work_per_owner[owner] > 1 or letter_counts.get(owner, 0) >= backlog_threshold)
                    )
                    if not owner_saturated:
                        continue

                    helpers = [
                        t
                        for t in active_tools
                        if t != owner and seen_work_per_owner.get(t, 0) == 0 and letter_counts.get(t, 0) < backlog_threshold
                    ]
                    if not helpers:
                        helpers = [t for t in active_tools if t != owner]
                    if not helpers:
                        continue
                    helpers.sort(key=lambda t: (seen_work_per_owner.get(t, 0), letter_counts.get(t, 0)))
                    helper = helpers[0]

                    phase["assisted_from"] = owner
                    phase["assisted_by"] = helper
                    phase["owner_tool"] = helper
                    phase["moderated_at"] = moment
                    seen_work_per_owner[helper] = seen_work_per_owner.get(helper, 0) + 1
                    claimed_resources.update(p_resources)
                    changed = True

                    delta = f"WORKLOAD ASSIST DISPATCHED: {pid} ({owner}->{helper})"
                    msg = (
                        f"ACTIONABLE_DELTA [동네 반장 Mutual Assist] Tool {owner} is bottlenecked/busy. "
                        f"Dispatched {helper} to lend a hand on READY phase {pid} immediately."
                    )
                    relay_id = self._emit_wake(target=helper, card=pid, delta=delta, message=msg)
                    relieved.append(
                        {
                            "phase_id": pid,
                            "kind": "WORKLOAD_ASSIST_DISPATCHED",
                            "from_tool": owner,
                            "to_tool": helper,
                        }
                    )
                    wakes_sent.append({"phase_id": pid, "target": helper, "relay_id": relay_id})

            if changed:
                _atomic_write_json(self.schedule_path, sched)

        if relieved:
            self._record_official_ledger(
                role="동네반장/사회자",
                action="BOTTLENECK_AND_ASSIST_RELIEF",
                details={"relieved": relieved},
                now=moment,
            )
        return {
            "ok": True,
            "active_tools": active_tools,
            "letter_counts": letter_counts,
            "relieved": relieved,
            "wakes_sent": wakes_sent,
        }

    def repair_broken_bridges_and_lan(
        self,
        *,
        desk: dict[str, dict[str, Any]] | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """수리공 & 관리인 (Repairman & Caretaker): Reconnect cut LAN cables, broken dependency bridges, and stale QUIET_LOCKs."""
        moment = time.time() if now is None else now
        if desk is None:
            desk = read_all(self.project_root, now=moment)
        active_tools = [t for t in ("antigravity", "claude", "codex") if (desk.get(t) or {}).get("state") == "ACTIVE"]

        repairs: list[dict[str, Any]] = []
        wakes_sent: list[dict[str, Any]] = []

        # 1. 관리인 (Caretaker): Clear stale .work/QUIET_LOCK with dead PID or age > 3600s; respect live foreign QUIET_LOCK
        quiet_lock = self.project_root / ".work" / "QUIET_LOCK"
        if quiet_lock.is_file():
            lock_doc = _read_json(quiet_lock, {})
            pid = int(lock_doc.get("pid") or 0) if isinstance(lock_doc, dict) else 0
            raw_started = lock_doc.get("started_at") if isinstance(lock_doc, dict) else None
            started = 0.0
            if isinstance(raw_started, (int, float)) and not isinstance(raw_started, bool):
                started = float(raw_started)
            elif isinstance(raw_started, str) and raw_started.strip():
                try:
                    started = float(raw_started)
                except ValueError:
                    from datetime import datetime
                    try:
                        started = datetime.fromisoformat(raw_started.replace("Z", "+00:00")).timestamp()
                    except ValueError:
                        started = moment
            age = (moment - started) if started > 0 else (DEFAULT_QUIET_LOCK_MAX_AGE_S + 1.0)
            if (pid > 0 and not _pid_alive(pid)) or age > DEFAULT_QUIET_LOCK_MAX_AGE_S:
                try:
                    quiet_lock.unlink()
                    repairs.append({"kind": "STALE_QUIET_LOCK_CLEARED", "pid": pid, "age_s": round(age, 1)})
                except OSError:
                    pass
            else:
                return {"ok": True, "quiet_lock_held": True, "repairs": repairs, "wakes_sent": wakes_sent}

        # 2. 수리공 (Repairman): Reconnect broken dependency bridges in master_schedule.json
        lock_path = self._schedule_lock()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with _exclusive(lock_path):
            sched = _read_json(self.schedule_path, {"phases": []})
            phases = sched.get("phases") if isinstance(sched, dict) else None
            if isinstance(phases, list):
                done_ids = {
                    str(p.get("phase_id"))
                    for p in phases
                    if isinstance(p, dict) and str(p.get("state") or "") in TERMINAL
                }
                changed = False
                for phase in phases:
                    if not isinstance(phase, dict) or not phase.get("phase_id"):
                        continue
                    pid = str(phase["phase_id"])
                    state = str(phase.get("state") or "")
                    text_blob = f"{pid} {phase.get('human', '')} {phase.get('note', '')} {phase.get('blocker_reason', '')}"
                    if state == "HUMAN" or HUMAN_ONLY_RE.search(text_blob):
                        continue
                    if phase.get("release_hold") or phase.get("blocker_kind") == "SAFETY_GATE":
                        continue
                    deps = [str(d) for d in (phase.get("depends_on") or [])]
                    if (
                        state == "BLOCKED"
                        and str(phase.get("blocker_kind") or "") in ("DEPENDENCY", "BRIDGE_CUT", "")
                        and deps
                        and all(d in done_ids for d in deps)
                    ):
                        owner = str(phase.get("owner_tool") or "")
                        target = owner if owner in active_tools else (active_tools[0] if active_tools else owner)
                        phase["state"] = "READY"
                        phase["owner_tool"] = target
                        phase["waiting_since"] = moment
                        phase.pop("blocker_kind", None)
                        phase.pop("blocker_reason", None)
                        phase["bridge_repaired_at"] = moment
                        changed = True
                        relay_id = self._emit_wake(
                            target=target,
                            card=pid,
                            delta=f"BROKEN BRIDGE RECONNECTED: {pid} -> {target} (dependencies {deps} DONE)",
                            message=f"ACTIONABLE_DELTA [수리공 Bridge Repair] Dependencies {deps} are DONE; reconnected {pid} to READY for {target}.",
                        )
                        repairs.append({"kind": "BROKEN_BRIDGE_RECONNECTED", "phase_id": pid, "owner": target})
                        wakes_sent.append({"phase_id": pid, "target": target, "relay_id": relay_id})
                if changed:
                    _atomic_write_json(self.schedule_path, sched)

        # 3. 수리공 (Repairman): Reconnect cut LAN cables (stranded un-ACKed ACTIONABLE letters with no delivery receipt or dead session)
        inbox_dir = self.project_root / ".coord" / "mailbox" / "inbox"
        ack_dir = self.project_root / ".coord" / "mailbox" / "ack"
        accepted_dir = self.project_root / ".coord" / "mailbox" / "delivery" / "accepted"
        reconnected_dir = self.moderator_dir / "reconnected_lan"
        if inbox_dir.is_dir():
            for msg_file in sorted(inbox_dir.glob("*.json")):
                mid = msg_file.stem
                if (ack_dir / f"{mid}.json").is_file() or (reconnected_dir / f"{mid}.json").is_file():
                    continue
                doc = _read_json(msg_file, {})
                payload = doc.get("payload") if isinstance(doc, dict) else {}
                if not isinstance(payload, dict) or payload.get("wake_class") != "ACTIONABLE":
                    continue
                if payload.get("lan_reconnected") or payload.get("moderator") or payload.get("verdict"):
                    continue
                target = str(payload.get("requested_target") or "")
                if not target or target not in active_tools:
                    continue
                created = float(doc.get("created_at") or payload.get("ts") or 0.0)
                if created <= 0.0:
                    try:
                        created = msg_file.stat().st_mtime
                    except OSError:
                        created = moment
                age_s = moment - created
                if age_s > DEFAULT_MAX_LAN_AGE_S:
                    continue
                has_receipt = (accepted_dir / f"{mid}.json").is_file()
                if age_s < self.lan_cut_threshold_s:
                    continue
                reroute_target = target
                card = str(payload.get("card") or "LAN-RECONNECT")
                reconnected_dir.mkdir(parents=True, exist_ok=True)
                _atomic_write_json(
                    reconnected_dir / f"{mid}.json",
                    {"original_id": mid, "reconnected_at": moment, "from_target": target, "to_target": reroute_target},
                )
                relay_id = self._emit_wake(
                    target=reroute_target,
                    card=card,
                    delta=f"LAN CABLE RECONNECTED: {mid} -> {reroute_target}",
                    message=(
                        f"ACTIONABLE_DELTA [수리공 LAN Reconnect] Un-ACKed ACTIONABLE relay {mid} for {card} "
                        f"was stranded ({int(age_s)}s, receipt={has_receipt}). Re-spliced line to {reroute_target}."
                    ),
                    verdict_requested=bool(payload.get("verdict_requested")),
                )
                repairs.append(
                    {
                        "kind": "LAN_CABLE_RECONNECTED",
                        "original_message_id": mid,
                        "card": card,
                        "from_target": target,
                        "to_target": reroute_target,
                    }
                )
                wakes_sent.append({"phase_id": card, "target": reroute_target, "relay_id": relay_id})

        if repairs:
            self._record_official_ledger(
                role="수리공/관리인/구청공무원",
                action="BRIDGE_AND_LAN_REPAIR",
                details={"repairs": repairs},
                now=moment,
            )
        return {"ok": True, "repairs": repairs, "wakes_sent": wakes_sent}

    def _replan_quota_locked(self, desk: dict[str, dict[str, Any]], moment: float) -> dict[str, Any]:
        """Self-contained atomic quota failover replanner (no external untracked module dependency required)."""
        active_tools = [t for t in ("antigravity", "claude", "codex") if (desk.get(t) or {}).get("state") == "ACTIVE"]
        unavailable_tools = [
            t
            for t in ("antigravity", "claude", "codex")
            if str((desk.get(t) or {}).get("state") or "").upper() in UNAVAILABLE_STATES
        ]
        mode = f"{len(active_tools)}_TOOL_FAILOVER" if unavailable_tools else "3_TOOL_NORMAL"
        if not unavailable_tools or not active_tools:
            return {
                "ok": True,
                "mode": mode,
                "active_tools": active_tools,
                "unavailable_tools": unavailable_tools,
                "replanned": [],
            }

        lock_path = self._schedule_lock()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        replanned: list[dict[str, Any]] = []
        with _exclusive(lock_path):
            sched = _read_json(self.schedule_path, {"phases": []})
            phases = sched.get("phases") if isinstance(sched, dict) else None
            if not isinstance(phases, list):
                return {
                    "ok": False,
                    "mode": mode,
                    "active_tools": active_tools,
                    "unavailable_tools": unavailable_tools,
                    "replanned": [],
                }
            changed = False
            idx = 0
            for phase in phases:
                if not isinstance(phase, dict) or not phase.get("phase_id"):
                    continue
                pid = str(phase["phase_id"])
                state = str(phase.get("state") or "")
                if state in TERMINAL or state == "REVIEW":
                    continue
                text_blob = f"{pid} {phase.get('human', '')} {phase.get('note', '')} {phase.get('blocker_reason', '')}"
                if state == "HUMAN" or HUMAN_ONLY_RE.search(text_blob):
                    continue
                owner = str(phase.get("owner_tool") or "")
                if owner not in unavailable_tools:
                    continue
                if state not in ("READY", "BLOCKED"):
                    continue
                new_owner = active_tools[idx % len(active_tools)]
                idx += 1
                phase["failover_from"] = owner
                phase["owner_tool"] = new_owner
                phase["state"] = "READY"
                phase["moderated_at"] = moment
                changed = True
                replanned.append({"phase_id": pid, "from": owner, "to": new_owner})
            if changed:
                _atomic_write_json(self.schedule_path, sched)
        return {
            "ok": True,
            "mode": mode,
            "active_tools": active_tools,
            "unavailable_tools": unavailable_tools,
            "replanned": replanned,
        }

    def detect_and_handle_quota_limits(
        self,
        *,
        desk: dict[str, dict[str, Any]] | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Detect LIMITED/ABSENT tools, replan their phases, and generate failover contract manuals via assistant."""
        moment = time.time() if now is None else now
        if desk is None:
            desk = read_all(self.project_root, now=moment)

        replan_res = self._replan_quota_locked(desk, moment)
        active_tools = replan_res.get("active_tools") or []
        unavailable_tools = replan_res.get("unavailable_tools") or []
        manuals_generated: list[dict[str, Any]] = []
        wakes_sent: list[dict[str, Any]] = []

        if not replan_res.get("replanned"):
            return {
                "ok": True,
                "mode": replan_res.get("mode"),
                "active_tools": active_tools,
                "unavailable_tools": unavailable_tools,
                "replanned": [],
                "manuals_generated": [],
                "wakes_sent": [],
            }

        sched = _read_json(self.schedule_path, {"phases": []})
        by_id = {str(p.get("phase_id")): p for p in (sched.get("phases") or []) if isinstance(p, dict)}

        for item in replan_res["replanned"]:
            pid = str(item["phase_id"])
            new_owner = str(item.get("to") or item.get("to_tool"))
            from_tool = str(item.get("from") or item.get("from_tool"))
            phase_obj = by_id.get(pid, {"phase_id": pid, "title": pid})
            non_author_judges = [t for t in ("codex", "claude", "antigravity") if t != new_owner and t in active_tools]
            judge_tool = non_author_judges[0] if non_author_judges else ("codex" if new_owner != "codex" else "antigravity")
            manual_info = self.assistant.draft_failover_manual(
                phase=phase_obj,
                new_owner=new_owner,
                judge_tool=judge_tool,
                unavailable_tool=from_tool,
            )
            manuals_generated.append(manual_info)
            delta = f"MODERATOR QUOTA FAILOVER MANUAL: {pid} ({from_tool}->{new_owner}, manual={Path(manual_info['manual_path']).name})"
            msg = (
                f"ACTIONABLE_DELTA [Antigravity Moderator] Tool {from_tool} is LIMITED/ABSENT. "
                f"Phase {pid} is reassigned to {new_owner} with auto-generated contract manual {manual_info['manual_path']} "
                f"(assistant={manual_info['assistant_used']}, judge={judge_tool}). Execute nonstop."
            )
            relay_id = self._emit_wake(target=new_owner, card=pid, delta=delta, message=msg)
            wakes_sent.append({"phase_id": pid, "target": new_owner, "relay_id": relay_id})

        self._record_official_ledger(
            role="사용자의비서/사회자",
            action="QUOTA_FAILOVER_MANUAL_ISSUED",
            details={"replanned": replan_res["replanned"], "manuals": manuals_generated},
            now=moment,
        )
        return {
            "ok": True,
            "mode": replan_res.get("mode"),
            "active_tools": active_tools,
            "unavailable_tools": unavailable_tools,
            "replanned": replan_res["replanned"],
            "manuals_generated": manuals_generated,
            "wakes_sent": wakes_sent,
        }

    def mediate_consensus(
        self,
        *,
        proposal_id: str,
        author_tool: str,
        voter_tool: str,
        vote: str,
        evidence_summary: str = "",
        desk: dict[str, dict[str, Any]] | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Record and mediate 3-tool tiki-taka consensus under an OS byte-range lock (`author != judge`, <=5 turns)."""
        moment = time.time() if now is None else now
        if desk is None:
            desk = read_all(self.project_root, now=moment)
        vote_norm = (vote or "").strip().upper()
        if vote_norm not in ("AGREE", "PASS", "APPROVE", "REWORK", "PIVOT", "REJECT"):
            return {"ok": False, "error": f"INVALID_VOTE:{vote}"}
        if voter_tool == author_tool and vote_norm in ("AGREE", "PASS", "APPROVE"):
            return {"ok": False, "error": "SELF_APPROVAL_FORBIDDEN", "proposal_id": proposal_id}

        self.moderator_dir.mkdir(parents=True, exist_ok=True)
        lock_file = self.moderator_dir / ".consensus.lock"
        with _exclusive(lock_file):
            ledger = _read_json(self.consensus_path, {"proposals": {}})
            proposals = ledger.setdefault("proposals", {})
            entry = proposals.get(proposal_id) or {
                "proposal_id": proposal_id,
                "author_tool": author_tool,
                "state": "OPEN",
                "turns": 0,
                "votes": {},
                "history": [],
                "created_at": moment,
            }
            if int(entry.get("turns", 0)) >= MAX_CONSENSUS_TURNS and entry.get("state") == "OPEN":
                entry["state"] = "ESCALATED_ROUTE_CHANGE"
                proposals[proposal_id] = entry
                _atomic_write_json(self.consensus_path, ledger)
                return {"ok": False, "error": "MAX_TURNS_EXCEEDED", "proposal": entry}

            entry["turns"] = int(entry.get("turns", 0)) + 1
            entry.setdefault("votes", {})[voter_tool] = {
                "vote": vote_norm,
                "evidence": evidence_summary[:300],
                "at": moment,
            }
            entry.setdefault("history", []).append(
                {"turn": entry["turns"], "voter": voter_tool, "vote": vote_norm, "at": moment}
            )

            active_non_authors = [
                t
                for t in TOOLS
                if t != author_tool and (desk.get(t) or {}).get("state") == "ACTIVE"
            ]
            votes_map = entry["votes"]
            if vote_norm in ("REWORK", "PIVOT", "REJECT"):
                entry["state"] = "REWORK_REQUIRED"
            elif active_non_authors and all(
                (votes_map.get(peer) or {}).get("vote") in ("AGREE", "PASS", "APPROVE")
                for peer in active_non_authors
            ):
                entry["state"] = "ADOPTED"
                entry["adopted_at"] = moment
                entry["agreed_by"] = sorted([author_tool, *active_non_authors])

            proposals[proposal_id] = entry
            _atomic_write_json(self.consensus_path, ledger)
            return {"ok": True, "proposal": entry}

    def route_codex_keypoint_and_routine_approvals(
        self,
        *,
        desk: dict[str, dict[str, Any]] | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """U257: Preserve Codex $20 Plus Astra quota for core keypoints while offloading routine approvals to Claude/Antigravity under the Supreme Quality gate."""
        moment = time.time() if now is None else now
        if desk is None:
            desk = read_all(self.project_root, now=moment)
        active_tools = [t for t in TOOLS if (desk.get(t) or {}).get("state") == "ACTIVE"]

        preserved_keypoints: list[str] = []
        offloaded_routine: list[dict[str, Any]] = []
        rejected_quality: list[dict[str, Any]] = []
        wakes_sent: list[dict[str, Any]] = []

        self.moderator_dir.mkdir(parents=True, exist_ok=True)
        lock_file = self.moderator_dir / ".schedule.lock"
        with _exclusive(lock_file):
            sched = _read_json(self.schedule_path, {})
            phases = sched.get("phases") if isinstance(sched, dict) else None
            if not isinstance(phases, list):
                return {
                    "ok": True,
                    "founding_principle": UAOS_CORE_FOUNDING_PRINCIPLE,
                    "financial_frame": UAOS_CORE_FINANCIAL_FRAME,
                    "preserved_keypoints": [],
                    "offloaded_routine": [],
                    "rejected_quality": [],
                }

            active_load: dict[str, int] = {t: 0 for t in TOOLS}
            review_load: dict[str, int] = {t: 0 for t in TOOLS}
            for phase in phases:
                if not isinstance(phase, dict):
                    continue
                st = str(phase.get("state") or "")
                ow = str(phase.get("owner_tool") or "")
                if st == "ACTIVE" and ow in active_load:
                    active_load[ow] += 1
                if st == "REVIEW":
                    rv = str(phase.get("reviewer") or "")
                    if rv in review_load:
                        review_load[rv] += 1

            changed = False
            for phase in phases:
                if not isinstance(phase, dict) or not phase.get("phase_id"):
                    continue
                pid = str(phase["phase_id"])
                state = str(phase.get("state") or "")
                if state != "REVIEW":
                    continue
                wo = str(phase.get("waiting_on") or "")
                judge = str(phase.get("reviewer") or (wo.split("-")[0] if wo.endswith("-verdict") else ""))
                if judge != "codex":
                    continue

                is_kp = is_codex_exclusive_keypoint(phase)
                if is_kp:
                    if "codex" in active_tools:
                        phase["codex_keypoint_preserved"] = True
                        phase["quality_frame"] = UAOS_CORE_FOUNDING_PRINCIPLE
                        preserved_keypoints.append(pid)
                        changed = True
                        continue
                    phase["codex_rereview_required"] = True

                author = str(phase.get("author_tool") or phase.get("owner_tool") or "")
                excluded_authors = {str(phase.get("author_tool") or ""), str(phase.get("owner_tool") or "")} - {""}
                candidates = [
                    t
                    for t in ("claude", "antigravity")
                    if t in active_tools and t not in excluded_authors
                ]
                if not candidates:
                    continue
                candidates.sort(key=lambda t: (active_load.get(t, 0), review_load.get(t, 0)))
                helper_judge = candidates[0]

                q_gate = verify_supreme_quality_gate(phase, judge_tool=helper_judge)
                if not q_gate["ok"]:
                    rejected_quality.append({"phase_id": pid, "error": q_gate["error"]})
                    continue

                phase["reviewer"] = helper_judge
                phase["waiting_on"] = f"{helper_judge}-verdict"
                phase["bottleneck_relieved_from"] = "codex"
                phase["codex_astra_quota_saved"] = True
                phase["quality_frame"] = UAOS_CORE_FOUNDING_PRINCIPLE
                phase["moderated_at"] = moment
                review_load["codex"] = max(0, review_load.get("codex", 1) - 1)
                review_load[helper_judge] = review_load.get(helper_judge, 0) + 1
                changed = True

                delta = f"CODEX ASTRA QUOTA SAVED (ROUTINE APPROVAL OFFLOAD): {pid} (codex->{helper_judge}, author={author})"
                msg = (
                    f"ACTIONABLE_DELTA VERDICT_REQUESTED=YES [U257 Codex Astra Quota Preservation] "
                    f"Routine non-keypoint approval for {pid} (author={author}) delegated to {helper_judge} "
                    f"under Supreme Quality Gate ({UAOS_CORE_FOUNDING_PRINCIPLE})."
                )
                relay_id = self._emit_wake(
                    target=helper_judge,
                    card=pid,
                    delta=delta,
                    message=msg,
                    verdict_requested=True,
                )
                offloaded_routine.append(
                    {
                        "phase_id": pid,
                        "from_tool": "codex",
                        "to_tool": helper_judge,
                        "author": author,
                        "quality_gate": "PENDING_JUDGE",
                    }
                )
                wakes_sent.append({"phase_id": pid, "target": helper_judge, "relay_id": relay_id})

            if changed:
                _atomic_write_json(self.schedule_path, sched)

        if preserved_keypoints or offloaded_routine or rejected_quality:
            self._record_official_ledger(
                role="구청공무원/사회자",
                action="U257_CODEX_KEYPOINT_AND_QUALITY_ROUTE",
                details={
                    "preserved_keypoints": preserved_keypoints,
                    "offloaded_routine": offloaded_routine,
                    "rejected_quality": rejected_quality,
                },
                now=moment,
            )
        return {
            "ok": True,
            "founding_principle": UAOS_CORE_FOUNDING_PRINCIPLE,
            "financial_frame": UAOS_CORE_FINANCIAL_FRAME,
            "preserved_keypoints": preserved_keypoints,
            "offloaded_routine": offloaded_routine,
            "rejected_quality": rejected_quality,
            "wakes_sent": wakes_sent,
        }

    def run_all_roles_cycle(
        self,
        *,
        desk: dict[str, dict[str, Any]] | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Run a full 6-persona cycle: Caretaker/Repairman -> Quota Secretary -> Bottleneck Chief -> Stall Moderator."""
        moment = time.time() if now is None else now
        if desk is None:
            desk = read_all(self.project_root, now=moment)
        repairs = self.repair_broken_bridges_and_lan(desk=desk, now=moment)
        quota = self.detect_and_handle_quota_limits(desk=desk, now=moment)
        bottlenecks = self.detect_and_relieve_bottlenecks(desk=desk, now=moment)
        stalls = self.detect_and_intervene_stalls(desk=desk, now=moment)
        return {
            "ok": True,
            "repairs": repairs,
            "quota": quota,
            "bottlenecks": bottlenecks,
            "stalls": stalls,
        }
