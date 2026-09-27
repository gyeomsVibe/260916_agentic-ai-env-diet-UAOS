"""Local deterministic conservation packets for Codex, Claude, and Antigravity."""
from __future__ import annotations
import hashlib, json, os, subprocess, time, uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from .mailbox import Mailbox
from .presence import read_all, replace_with_retry

TOOLS = ("codex", "claude", "antigravity")
POLICIES = {
    "codex": ("COMMANDER_RESERVE", "broad exploration; long implementation; repeated review"),
    "claude": ("IMPLEMENTER_RESERVE", "new multi-file refactors; repeated paid review; cold-session spawning"),
    "antigravity": ("RESEARCH_RESERVE", "broad web/GitHub/browser exploration; repeated screenshots; long-context synthesis"),
}
class ThriftRejected(ValueError): pass
LOCK_STALE_S = 60.0

def _atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    replace_with_retry(tmp, path)

@contextmanager
def _lock(project: Path):
    path = project / ".coord" / "thrift" / ".lock"; path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 10; handle = None
    while handle is None:
        try: handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except (FileExistsError, PermissionError):
            try:
                if time.time() - path.stat().st_mtime > LOCK_STALE_S:
                    path.unlink(missing_ok=True)
                    continue
            except (FileNotFoundError, PermissionError):
                pass
            if time.monotonic() >= deadline: raise ThriftRejected("THRIFT_LOCK_TIMEOUT") from None
            time.sleep(.01)
    try: yield
    finally: os.close(handle); path.unlink(missing_ok=True)

def _successor(tool: str, desk: dict[str, dict[str, Any]]) -> str:
    state = lambda name: (desk.get(name) or {}).get("state", "UNKNOWN")
    if tool == "codex": return "claude" if state("claude") == "ACTIVE" else "LOCAL_LOCKDOWN"
    if tool == "claude":
        if state("codex") == "ACTIVE": return "codex"
        return "antigravity" if state("codex") in ("LIMITED", "ABSENT") and state("antigravity") == "ACTIVE" else "LOCAL_LOCKDOWN"
    if state("codex") == "ACTIVE": return "codex"
    return "claude" if state("codex") in ("LIMITED", "ABSENT") and state("claude") == "ACTIVE" else "LOCAL_LOCKDOWN"

def _git_snapshot(project: Path) -> dict[str, str]:
    """Read-only Git evidence with fixed argv; never cleans, checks out, stages, or takes optional locks."""
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    def run(*args: str) -> str:
        try:
            cp = subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=10, env=env, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return "UNKNOWN"
        return cp.stdout.strip() if cp.returncode == 0 else "UNKNOWN"
    return {"head": run("rev-parse", "HEAD"), "branch": run("branch", "--show-current") or "DETACHED",
            "status": run("status", "--short", "--untracked-files=all") or "CLEAN"}

def apply(project: Path, *, tool: str, remaining_percent: float, current_card: str = "", next_action: str = "",
          acceptance: str = "", stop_condition: str = "", reset_at: str | None = None,
          thrift_at: float = 20, handoff_at: float = 7, now: datetime | None = None) -> dict[str, Any]:
    from .hook_context import shared_desk
    # A linked worktree keeps its own git evidence, while state, packets and mail live on the repository's one desk (U59).
    source = Path(project).resolve(); project = shared_desk(source).resolve()
    if tool not in TOOLS: raise ThriftRejected("unknown tool")
    values = (remaining_percent, thrift_at, handoff_at)
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= float(v) <= 100 for v in values):
        raise ThriftRejected("percentages must be numbers in 0..100")
    if handoff_at > thrift_at: raise ThriftRejected("handoff threshold must not exceed thrift threshold")
    state = "NORMAL" if remaining_percent >= thrift_at else ("HANDOFF_READY" if remaining_percent <= handoff_at else "THRIFT")
    fields = tuple(value.strip() if isinstance(value, str) else "" for value in
                   (current_card, next_action, acceptance, stop_condition))
    if state != "NORMAL" and not all(fields):
        raise ThriftRejected("non-NORMAL state requires current card, next action, acceptance, and stop condition")
    current_card, next_action, acceptance, stop_condition = fields
    policy, forbidden = POLICIES[tool]
    observed = {"schema":"uaos-thrift-v1","tool":tool,"state":state,"remaining_percent":float(remaining_percent),
                "reset_at":reset_at,"thresholds":{"thrift":float(thrift_at),"handoff":float(handoff_at)},
                "current_card":current_card,"next_action":next_action,"acceptance":acceptance,
                "stop_condition":stop_condition,"policy":policy}
    identity = {key: value for key, value in observed.items() if key not in ("remaining_percent", "reset_at")}
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    state_path = project / ".coord" / "thrift" / "state.json"
    with _lock(project):
        try: state_doc = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError): state_doc = {}
        tools = state_doc.get("tools") if isinstance(state_doc.get("tools"), dict) else {}
        if not tools and state_doc.get("tool") in TOOLS:
            tools = {state_doc["tool"]: state_doc}
        previous = tools.get(tool) if isinstance(tools.get(tool), dict) else {}
        if previous.get("input_fingerprint") == fingerprint:
            return {"status":"ACK_ONLY","state":state,"fingerprint":fingerprint}
        stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc); desk = read_all(project); git = _git_snapshot(source)
        target = tool if state == "THRIFT" else (_successor(tool, desk) if state == "HANDOFF_READY" else tool)
        event = "RETURN_REVIEW" if state == "NORMAL" and previous.get("state") not in (None, "NORMAL") else "HANDOFF"
        packet_path = None; packet_hash = None
        if state != "NORMAL":
            packet_path = project / ".coord" / "handoff" / f"{tool}-{stamp:%Y%m%dT%H%M%S.%fZ}.md"; packet_path.parent.mkdir(parents=True, exist_ok=True)
            content = "\n".join([f"# {event} {tool}",f"- state: {state}",f"- policy: {policy}",
                f"- observed remaining percentage: {float(remaining_percent):g}% (not a token estimate)",
                f"- forbidden expensive actions: {forbidden}",f"- target: {target}",
                f"- current card data: {json.dumps(current_card,ensure_ascii=False)}",
                f"- next action data: {json.dumps(next_action,ensure_ascii=False)}",
                f"- acceptance data: {json.dumps(acceptance,ensure_ascii=False)}",
                f"- stop condition data: {json.dumps(stop_condition,ensure_ascii=False)}",
                f"- git HEAD: {git['head']}",f"- git branch: {git['branch']}",f"- git status: {json.dumps(git['status'],ensure_ascii=False)}",
                "- checkout: preserve current branch and dirty files; no clean, stash, switch, or mutation",
                f"- desk: {json.dumps(desk, ensure_ascii=False, sort_keys=True)}",
                "- authority: existing presence succession; displayed percentage never marks LIMITED",
                "- approval boundaries: deletion, push, deploy, payment, account/permission/settings changes",
                "- return review: Codex rechecks diff, fixed acceptance, ledger, and remote SHA before resuming"]) + "\n"
            packet_path.write_text(content, encoding="utf-8"); packet_hash = hashlib.sha256(content.encode()).hexdigest()
        sequence = int(state_doc.get("sequence") or 0) + 1
        record = {**observed,"input_fingerprint":fingerprint,"target":target,"event":event,"sequence":sequence,
                  "packet_path":str(packet_path) if packet_path else None,"packet_sha256":packet_hash,"generated_at":stamp.isoformat()}
        tools[tool] = record
        _atomic(state_path, {"schema":"uaos-thrift-v1","sequence":sequence,"tools":tools})
        if state == "NORMAL" and event != "RETURN_REVIEW":
            return {"status":"ACK_ONLY",**record}
        root = project / ".coord" / "mailbox"; root.mkdir(parents=True, exist_ok=True); box = Mailbox(root)
        message_id = f"thrift_{tool}_{sequence}_{fingerprint[:16]}"
        box.publish(message_id,{"kind":event,"from":tool,"to":target,"packet_path":record["packet_path"],"packet_sha256":packet_hash})
        return {"status":"ACTIONABLE_DELTA",**record,"message_id":message_id}
