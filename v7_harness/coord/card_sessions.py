"""U293: 3-Tool Standardized Card-by-Card Parallel Session Execution Engine (Card Sessions + 5-Lane Multiplexing).

Synthesizes the best-in-class parallel session architectures across Claude Code Desktop (`mcp__ccd_session__start_session`,
`mcp__ccd_session__mark_chapter`, `SendMessage`, `local_<uuid>` child sessions, `use_worktree=True`), OpenAI Codex
(`codex app-server` JSON-RPC `thread/start`, `turn/start`, `thread/name/set`), Google Antigravity (`invoke_subagent`
with `Workspace="branch"`, `send_message`, `agy -p`), and GitHub/Reddit worktree-per-card patterns (Vibe Kanban,
Crystal/Nimbalyst, Claude Squad, Planner-Builder-Gatekeeper):

1. Guarantees `1 Card = 1 Unique Session UUID = 1 Isolated Git Worktree = 1 Fresh Context Envelope` across all 3 tools
   while binding each card session to its 5-Category Process Classification Lane (`IMPL_CODE`, `VERIFY_AUDIT`,
   `ARCH_DESIGN`, `MERGE_RELEASE`, `RECOVERY_OPS`).
2. Enforces the Topmost Default User-Facing Window Rule (`가장 위에 위치한 대화창 = 기본 사용자 대상 대화창`):
   the root/parent session at the top of the card-parallel hierarchy is by default the user-facing conversation window
   and is automatically claimed and titled via `user_window.claim` + `desk_title` in the canonical format
   `[YYMMDD-N] <대화창 대표 타이틀>` (while child card sessions underneath it keep `[U##] <핵심 제목>` / `U## <핵심 제목>`).
3. Normalizes Claude Desktop child session IDs (`local_<uuid>` <-> canonical `<uuid>`) so `uaos coord window` and
   `SendMessage` work seamlessly without `ValueError`.
4. Automatically discovers and syncs live Claude Desktop child card sessions (`mcp__ccd_session__start_session`) from
   transcript JSONLs into `.coord/windows/<card>.json` (supporting both single-card and multi-card titles such as
   `U276+U284`) and claims their parent session as `[YYMMDD-N] <대화창 대표 타이틀>`.
5. Generates deterministic 3-tool native launch specifications (`build_card_parallel_launch_spec`) and orchestrates
   multi-card parallel batches (`orchestrate_card_parallel_batch`).
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any
import hashlib
import json
import os
import re

from .hook_context import shared_desk
from .process_lanes import (
    TOOLS,
    classify_process_lane,
    open_or_reuse_lane_window,
    select_active_tool_for_lane,
    validate_lane_id,
)

CHAPTER_TITLE_KO = "카드별 병렬 세션 가동"
DEFAULT_TOPMOST_REP_TITLE = "카드별 병렬 세션 총괄"
LOCAL_SESSION_ID_RE = re.compile(
    r"^(?:local_)?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
    re.IGNORECASE,
)
CARD_TOKEN_RE = re.compile(r"\b(U\d{1,5}[A-Z]?)\b", re.IGNORECASE)
CHILD_CARD_TITLE_PREFIX_RE = re.compile(
    r"^\s*(?:\[\s*(?:U\d{1,5}[A-Z]?(?:\+U\d{1,5}[A-Z]?)*|LANE:[A-Z_]+)\s*\]|U\d{1,5}[A-Z]?(?:\+U\d{1,5}[A-Z]?)*\b)",
    re.IGNORECASE,
)
STARTED_SESSION_RE = re.compile(
    r'Started session "(?P<title>[^"]+)"\s*\(session_id:\s*(?P<native_id>local_[0-9a-fA-F-]{36}),\s*name:\s*(?P<slug>[^)]+)\)'
)
SLUG_CLEAN_RE = re.compile(r"[^a-z0-9-]+")


def normalize_claude_session_id(raw_id: str) -> tuple[str, str]:
    """Validate and normalize a Claude session ID (`<uuid>` or `local_<uuid>`).

    Returns `(canonical_uuid, native_local_id)` where:
    - `canonical_uuid` is the lowercase `8-4-4-4-12` hex UUID for `claude --resume` and `.coord/windows/<card>.json`.
    - `native_local_id` is `local_<canonical_uuid>` for Claude Desktop `SendMessage` routing.
    """
    cleaned = str(raw_id or "").strip()
    m = LOCAL_SESSION_ID_RE.fullmatch(cleaned)
    if not m:
        raise ValueError(f"bad claude session id: {raw_id!r}")
    canonical = m.group(1).lower()
    return canonical, f"local_{canonical}"


def deterministic_card_session_uuid(project: Path, card: str, tool: str, generation: int = 0) -> str:
    """Generate a deterministic, unique UUIDv4/v5-compliant session/window ID for `(project, card, tool, generation)`.

    Ensures two different cards in the same process classification lane NEVER share the same card window ID.
    """
    desk = Path(shared_desk(project)).resolve()
    norm_card = str(card or "").strip().upper()
    norm_tool = str(tool or "").strip().lower()
    seed = f"uaos-card-v1:{os.path.normcase(str(desk))}:{norm_card}:{norm_tool}:{int(generation)}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"{digest[:8]}-{digest[8:12]}-4{digest[13:16]}-a{digest[17:20]}-{digest[20:32]}"


def extract_cards_from_text(text: str | None) -> list[str]:
    """Extract ordered, deduplicated canonical card IDs (`U##`) from a title, slug, or prompt string.

    Supports single-card titles (`"U291 PR #256 비작성자 판정"` -> `["U291"]`) and multi-card titles
    (`"U276+U284 파일럿·작성자 출처 확인"` -> `["U276", "U284"]`).
    """
    if not isinstance(text, str) or not text.strip():
        return []
    seen: set[str] = set()
    ordered: list[str] = []
    for match in CARD_TOKEN_RE.finditer(text):
        cid = match.group(1).upper()
        if cid not in seen:
            seen.add(cid)
            ordered.append(cid)
    return ordered


def is_child_card_session(
    project: Path,
    thread: str,
    raw_title: str = "",
    *,
    claude_sessions_root: Path | None = None,
) -> bool:
    """Return True if `thread` or `raw_title` belongs to a child card/lane session rather than a topmost user window."""
    if isinstance(raw_title, str) and CHILD_CARD_TITLE_PREFIX_RE.search(raw_title):
        return True
    norm_thread = str(thread or "").strip()
    if not norm_thread:
        return False
    candidates = {norm_thread.lower()}
    try:
        canonical_uuid, native_id = normalize_claude_session_id(norm_thread)
        candidates.add(canonical_uuid.lower())
        candidates.add(native_id.lower())
    except ValueError:
        pass

    desk = Path(shared_desk(project)).resolve()
    win_dir = desk / ".coord" / "windows"
    if win_dir.is_dir():
        for rec_file in win_dir.glob("*.json"):
            try:
                data = json.loads(rec_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            for tool_name in TOOLS:
                entry = data.get(tool_name)
                if not isinstance(entry, dict):
                    continue
                for key in ("id", "native_id", "cli_session_id"):
                    val = str(entry.get(key) or "").strip().lower()
                    if val and val in candidates:
                        return True

    if claude_sessions_root is not None and Path(claude_sessions_root).is_dir():
        for path in Path(claude_sessions_root).glob("*/*/local_*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            sid = str(data.get("sessionId") or "").strip().lower()
            cid = str(data.get("cliSessionId") or "").strip().lower()
            if (sid in candidates or cid in candidates) and data.get("titleSource") == "tool":
                return True
    return False


def ensure_topmost_user_window(
    project: Path,
    tool: str,
    thread: str,
    *,
    representative_title: str = "",
    now: datetime | None = None,
    claude_sessions_root: Path | None = None,
    sync_native_store: bool = True,
) -> dict[str, Any]:
    """최상위 부모 세션을 기본 사용자 대상 대화창으로 선점하고, 제목을 '[YYMMDD-N] 대화창 대표 타이틀' 형식으로 강제합니다.
    하위 카드 세션은 변경하지 않고 건너뛰며, 네이티브 저장소와 상태를 동기화한 뒤 결과 딕셔너리를 반환합니다.
    """
    from . import desk_title as dt
    from . import user_window as uw

    desk = Path(shared_desk(project)).resolve()
    norm_tool = str(tool or "").strip().lower()
    norm_thread = str(thread or "").strip()
    if norm_tool not in TOOLS or not norm_thread:
        return {"ok": False, "reason": "INVALID_TOOL_OR_THREAD", "tool": norm_tool, "thread": norm_thread}

    if is_child_card_session(desk, norm_thread, representative_title, claude_sessions_root=claude_sessions_root):
        return {
            "ok": False,
            "reason": "CHILD_CARD_SESSION",
            "tool": norm_tool,
            "thread": norm_thread,
            "is_default_user_window": False,
        }

    current_title = (
        uw._claude_title(norm_thread, root=claude_sessions_root)
        if norm_tool == "claude"
        else uw._current_title(norm_tool, norm_thread)
    )
    if is_child_card_session(desk, norm_thread, current_title or "", claude_sessions_root=claude_sessions_root):
        return {
            "ok": False,
            "reason": "CHILD_CARD_SESSION",
            "tool": norm_tool,
            "thread": norm_thread,
            "is_default_user_window": False,
        }

    existing_names = uw._codex_names() if norm_tool == "codex" else []
    claimed = uw.claim(
        desk,
        norm_tool,
        norm_thread,
        now=now,
        existing=existing_names,
        current=current_title or representative_title,
    )
    prefix = str(claimed["title"])
    schedule_topic = dt._schedule_topic(desk) or ""
    rep_title = (
        uw.extract_representative_title(representative_title)
        or uw.extract_representative_title(current_title)
        or uw.extract_representative_title(schedule_topic)
        or DEFAULT_TOPMOST_REP_TITLE
    )
    full_title = f"{prefix} {rep_title}".strip()

    def _update_topmost_entry(entry: dict[str, Any]) -> dict[str, Any]:
        entry["topic"] = rep_title
        entry["shared_topic"] = schedule_topic or rep_title
        entry["desired_title"] = full_title
        entry["adapter_version"] = dt.ADAPTER_VERSION
        entry["role"] = "TOPMOST_USER_WINDOW"
        entry["is_default_topmost"] = True
        entry["converged"] = True
        entry["title_state"] = "CONVERGED"
        return dict(entry)

    uw._entry_change(desk, norm_tool, norm_thread, _update_topmost_entry)

    store_status = "SKIPPED"
    backup_dir = desk / ".work" / f"backup_{(now or datetime.now()).strftime('%Y%m%d')}"
    if sync_native_store:
        if norm_tool == "claude":
            store_status = uw.rename_claude_desktop_session_title(
                norm_thread,
                full_title,
                root=claude_sessions_root,
                backup_dir=backup_dir,
            )
        elif norm_tool == "antigravity":
            store_status = uw.rename_agy_status(
                norm_thread,
                full_title,
                backup_dir=backup_dir,
            )
        elif norm_tool == "codex":
            store_status = "RPC_READY"

    return {
        "ok": True,
        "tool": norm_tool,
        "thread": norm_thread,
        "prefix": prefix,
        "representative_title": rep_title,
        "full_title": full_title,
        "is_default_user_window": True,
        "position": "TOPMOST_ROOT",
        "store_status": store_status,
        "native_title_controls": {
            "claude_desktop": {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "sessionTitle": full_title,
                },
                "set_session_title": {
                    "session_id": "self",
                    "title": full_title,
                },
            },
            "antigravity": {
                "conversation_id": norm_thread,
                "title": full_title,
                "store_status": store_status,
            },
            "codex": {
                "method": "thread/name/set",
                "params": {"threadId": norm_thread, "name": full_title},
            },
        },
    }


def _preview_topmost_user_window_spec(
    project: Path,
    tool: str,
    parent_session_id: str = "",
    parent_title: str = "",
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the topmost user-facing window title specification (`[YYMMDD-N] <대화창 대표 타이틀>`) without mutating
    stores when `parent_session_id` is not yet provided, or claim it when `parent_session_id` is given."""
    from . import desk_title as dt
    from . import user_window as uw

    desk = Path(shared_desk(project)).resolve()
    norm_tool = str(tool or "claude").strip().lower()
    if norm_tool not in TOOLS:
        norm_tool = "claude"
    if parent_session_id.strip():
        claimed_res = ensure_topmost_user_window(
            desk,
            norm_tool,
            parent_session_id.strip(),
            representative_title=parent_title,
            now=now,
            sync_native_store=False,
        )
        if claimed_res.get("ok"):
            return claimed_res

    date_str = (now or datetime.now()).strftime("%y%m%d")
    prefix = f"[{date_str}-1]"
    try:
        rec_path = desk / ".coord" / "presence" / "user_windows.json"
        if rec_path.is_file():
            rec = json.loads(rec_path.read_text(encoding="utf-8"))
            entries = (rec.get(norm_tool) or []) if isinstance(rec, dict) else []
            primary = max(
                (e for e in entries if isinstance(e, dict) and not e.get("pinned")),
                key=lambda e: float(e.get("at") or 0),
                default=None,
            )
            if primary and uw.TITLE_RE.search(str(primary.get("title") or "")):
                prefix = str(primary["title"])
    except (OSError, ValueError):
        pass

    rep_title = (
        uw.extract_representative_title(parent_title)
        or uw.extract_representative_title(dt._schedule_topic(desk) or "")
        or DEFAULT_TOPMOST_REP_TITLE
    )
    full_title = f"{prefix} {rep_title}".strip()
    return {
        "ok": True,
        "tool": norm_tool,
        "thread": parent_session_id.strip() or "<topmost-parent-session>",
        "prefix": prefix,
        "representative_title": rep_title,
        "full_title": full_title,
        "pattern": "[YYMMDD-N] 대화창 대표 타이틀",
        "is_default_user_window": True,
        "position": "TOPMOST_ROOT",
    }


def _infer_role_slug(role: str, title: str, lane_id: str) -> str:
    raw = str(role or "").strip().lower()
    if raw and raw not in ("auto", "default"):
        slug = SLUG_CLEAN_RE.sub("-", raw).strip("-")
        if slug:
            return slug[:24]
    low_title = str(title or "").lower()
    if "판정" in low_title or "검토" in low_title or "review" in low_title or lane_id == "VERIFY_AUDIT":
        return "review"
    if "pr" in low_title or "병합" in low_title or lane_id == "MERGE_RELEASE":
        return "pr"
    if "출처" in low_title or "provenance" in low_title:
        return "provenance"
    if "설계" in low_title or "리서치" in low_title or lane_id == "ARCH_DESIGN":
        return "design"
    if "복구" in low_title or "병목" in low_title or lane_id == "RECOVERY_OPS":
        return "recovery"
    return "impl"


def build_card_parallel_launch_spec(
    project: Path,
    card: str,
    *,
    title: str = "",
    tool: str = "auto",
    role: str = "",
    source_branch: str = "",
    pr_url: str = "",
    parent_session_id: str = "",
    parent_title: str = "",
    allowed_files: Sequence[str] = (),
    accept_cmd: str = "",
    explicit_lane: str = "",
) -> dict[str, Any]:
    """Build a standardized 3-tool card-parallel child session launch specification.

    Enforces the two-tier window hierarchy:
    - Topmost (parent/root) session = Default User-Facing Conversation Window (`[YYMMDD-N] <대화창 대표 타이틀>`)
    - Child card sessions nested underneath = `[U##] <핵심 제목>` / `U## <핵심 제목>`
    """
    from v7_harness.card_pipeline import card_title as resolve_card_title, clean_core_title
    from .windows import window_entry

    desk = Path(shared_desk(project)).resolve()
    cards = extract_cards_from_text(card)
    primary_card = cards[0] if cards else str(card or "U00").strip().upper()
    if not cards:
        cards = [primary_card]
    card_label = "+".join(cards)

    raw_title = title.strip() or resolve_card_title(desk, primary_card) or f"{card_label} 병렬 세션 작업"
    core_title = clean_core_title(raw_title) or raw_title.strip()
    session_title = f"{card_label} {core_title}" if not core_title.upper().startswith(primary_card) else core_title
    sidebar_title = f"[{card_label}] {core_title}"

    lane_payload: dict[str, Any] = {
        "card": primary_card,
        "title": core_title,
        "message": f"{role} {core_title}",
        "pr_url": pr_url,
        "allowed_files": list(allowed_files),
        "verdict_requested": role.lower() in ("review", "audit", "verdict", "judge"),
    }
    lane_id = classify_process_lane(lane_payload, explicit_lane=explicit_lane)
    role_slug = _infer_role_slug(role, core_title, lane_id)
    session_slug = f"{primary_card.lower()}-{role_slug}"

    selected_tool = tool.strip().lower()
    if selected_tool not in TOOLS:
        selected_tool, _reason = select_active_tool_for_lane(desk, lane_id, requested_target=selected_tool)

    topmost_spec = _preview_topmost_user_window_spec(
        desk,
        selected_tool,
        parent_session_id=parent_session_id,
        parent_title=parent_title,
    )

    worktree_rel = f".work/wt_{primary_card.lower()}_{role_slug}"
    branch_name = source_branch.strip() or f"{'agy' if selected_tool == 'antigravity' else selected_tool}/{session_slug}"

    existing = window_entry(desk, primary_card, selected_tool)
    card_uuid = str(existing.get("id") or deterministic_card_session_uuid(desk, primary_card, selected_tool))
    native_claude_id = str(existing.get("native_id") or f"local_{card_uuid}")

    allowed_clause = ", ".join(allowed_files) if allowed_files else f"files scoped to {card_label} contract manual"
    accept_clause = accept_cmd.strip() or "python -m unittest discover -s tests -t ."
    pr_clause = f" Target PR: {pr_url}." if pr_url else ""
    peer_target = "antigravity" if selected_tool == "claude" else "claude"

    prompt_text = (
        f"Card {card_label} ({core_title}) [Lane: {lane_id}].{pr_clause} "
        f"Execute in isolated card worktree (`{worktree_rel}`, branch `{branch_name}`). "
        f"Allowed scope: {allowed_clause}. "
        f"Steps: (1) verify/implement within allowed scope (Ollama-first for mechanical code/summaries); "
        f"(2) run acceptance and regression suite (`{accept_clause}`) keeping logs in `.work/{primary_card.lower()}/`; "
        f"(3) write `.coord/results/{primary_card}.md` via `uaos card result --card {primary_card}`; "
        f"(4) hand off immediately via `python \"$HOME/.uaos/uaos.py\" coord lanes --project \"{desk.as_posix()}\" "
        f"--action handoff --lane {lane_id} --actor {selected_tool} --target {peer_target} --card {primary_card} "
        f"--verdict-requested --message \"{card_label} ready for non-author verdict\"`. "
        f"Never self-approve (`author != judge`) and never `git add -A`."
    )
    background_text = (
        f"Project: UAOS-RSI ({desk.as_posix()}), 3-tool (Codex, Claude Code, Antigravity) parallel operating system. "
        f"Topmost User Window: {topmost_spec['full_title']} (default user-facing conversation window). "
        f"Rule: 1 Card = 1 Fresh Isolated Worktree Session (`context=\"fresh\"`) bound to 5 Process Lanes (`{lane_id}`). "
        f"Ownership guard: one owner per step; never modify files belonging to other active card sessions. "
        f"Report in Korean brief-ko style (<=5 lines, <=600 chars, core title required, no bare IDs)."
    )

    claude_start_input: dict[str, Any] = {
        "initiation": "user_asked",
        "title": session_title,
        "name": session_slug,
        "context": "fresh",
        "use_worktree": True,
        "prompt": prompt_text,
        "background": background_text,
    }
    if source_branch.strip():
        claude_start_input["source_branch"] = source_branch.strip()

    return {
        "ok": True,
        "card": primary_card,
        "cards": cards,
        "card_label": card_label,
        "core_title": core_title,
        "session_title": session_title,
        "sidebar_title": sidebar_title,
        "session_slug": session_slug,
        "lane_id": lane_id,
        "selected_tool": selected_tool,
        "card_window_id": card_uuid,
        "native_claude_id": native_claude_id,
        "parent_session_id": parent_session_id,
        "topmost_user_window": topmost_spec,
        "worktree_path": worktree_rel,
        "branch": branch_name,
        "chapter_title": CHAPTER_TITLE_KO,
        "prompt": prompt_text,
        "background": background_text,
        "native_launchers": {
            "claude_desktop": {
                "topmost_user_window_title": {
                    "session_id": "self",
                    "title": topmost_spec["full_title"],
                },
                "mark_chapter": {
                    "name": "mcp__ccd_session__mark_chapter",
                    "input": {"title": CHAPTER_TITLE_KO},
                },
                "start_session": {
                    "name": "mcp__ccd_session__start_session",
                    "input": claude_start_input,
                },
                "send_message": {
                    "name": "SendMessage",
                    "input": {
                        "to": native_claude_id,
                        "summary": f"{card_label} update",
                        "message": f"[{card_label}] delta update",
                    },
                },
            },
            "antigravity": {
                "topmost_user_window_title": {
                    "conversation_id": parent_session_id or "<topmost-parent-session>",
                    "title": topmost_spec["full_title"],
                },
                "invoke_subagent": {
                    "name": "invoke_subagent",
                    "input": {
                        "TypeName": "self",
                        "Role": sidebar_title,
                        "Prompt": f"{prompt_text}\n\nBackground:\n{background_text}",
                        "Workspace": "branch",
                        "Model": "inherit",
                    },
                },
                "send_message": {
                    "name": "send_message",
                    "input": {
                        "Recipient": card_uuid,
                        "Message": f"[{card_label}] delta update",
                    },
                },
            },
            "codex": {
                "topmost_user_window_rpc": {
                    "method": "thread/name/set",
                    "params": {
                        "threadId": parent_session_id or "<topmost-parent-session>",
                        "name": topmost_spec["full_title"],
                    },
                },
                "app_server_rpc": [
                    {"method": "thread/start", "params": {"cwd": str((desk / worktree_rel).as_posix())}},
                    {
                        "method": "turn/start",
                        "params": {
                            "threadId": card_uuid,
                            "input": [{"type": "text", "text": f"{prompt_text}\n\nBackground:\n{background_text}"}],
                        },
                    },
                    {"method": "thread/name/set", "params": {"threadId": card_uuid, "name": sidebar_title}},
                ],
            },
        },
    }


def _load_claude_desktop_session_index(claude_sessions_root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Index Claude Desktop `local_*.json` metadata by both `sessionId` (`local_<uuid>`) and `cliSessionId` (`<uuid>`)."""
    from . import user_window as uw

    folder = Path(claude_sessions_root) if claude_sessions_root else uw._claude_sessions_root()
    index: dict[str, dict[str, Any]] = {}
    if not folder.is_dir():
        return index
    for path in folder.glob("*/*/local_*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        sid = str(data.get("sessionId") or "").strip()
        cid = str(data.get("cliSessionId") or "").strip()
        if sid:
            index[sid] = data
        if cid:
            index[cid] = data
    return index


def sync_claude_desktop_card_sessions(
    project: Path,
    *,
    transcripts_root: Path | None = None,
    claude_sessions_root: Path | None = None,
    claim_topmost_parent: bool = True,
    now: datetime | None = None,
    max_files: int = 25,
) -> dict[str, Any]:
    """Scan Claude Code Desktop transcripts (`~/.claude/projects/*/*.jsonl`) for `mcp__ccd_session__start_session`
    calls, automatically bind discovered `local_<uuid>` child card sessions into `.coord/windows/<card>.json`,
    and claim each parent session (`parent_session_id`) as the default topmost user-facing window with
    `[YYMMDD-N] <대화창 대표 타이틀>`.
    """
    from v7_harness.card_pipeline import clean_core_title
    from . import user_window as uw
    from .windows import _record_path, record_window

    desk = Path(shared_desk(project)).resolve()
    if transcripts_root is None:
        claude_home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
        transcripts_root = claude_home / "projects"

    if not transcripts_root.is_dir():
        return {
            "ok": True,
            "synced_count": 0,
            "cards": {},
            "topmost_user_windows": {},
            "reason": "NO_TRANSCRIPTS_DIR",
        }

    desktop_index = _load_claude_desktop_session_index(claude_sessions_root)
    candidates = sorted(
        transcripts_root.rglob("*.jsonl"),
        key=lambda p: p.stat().st_mtime if p.is_file() else 0.0,
        reverse=True,
    )[: max(1, max_files)]

    # Process oldest-to-newest among the recent slice so the newest session binding wins
    synced_cards: dict[str, dict[str, Any]] = {}
    topmost_user_windows: dict[str, dict[str, Any]] = {}

    for jsonl_path in reversed(candidates):
        parent_session_id = jsonl_path.stem
        try:
            raw_text = jsonl_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "mcp__ccd_session__start_session" not in raw_text and "Started session " not in raw_text:
            continue

        tool_uses: dict[str, dict[str, Any]] = {}
        parent_spawned_cards: list[str] = []
        for line in raw_text.splitlines():
            if "start_session" not in line and "Started session " not in line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            msg = row.get("message") if isinstance(row, dict) else None
            content = msg.get("content") if isinstance(msg, dict) else None
            if not isinstance(content, list):
                continue

            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "tool_use" and block.get("name") == "mcp__ccd_session__start_session":
                    tuid = str(block.get("id") or "")
                    inp = block.get("input")
                    if tuid and isinstance(inp, dict):
                        tool_uses[tuid] = inp
                elif btype == "tool_result":
                    tuid = str(block.get("tool_use_id") or "")
                    inp = tool_uses.get(tuid, {})
                    raw_res = block.get("content")
                    text_blobs: list[str] = []
                    if isinstance(raw_res, str):
                        text_blobs.append(raw_res)
                    elif isinstance(raw_res, list):
                        for item in raw_res:
                            if isinstance(item, dict) and isinstance(item.get("text"), str):
                                text_blobs.append(item["text"])
                    combined_res = "\n".join(text_blobs)
                    m = STARTED_SESSION_RE.search(combined_res)
                    if not m:
                        continue
                    title = m.group("title").strip()
                    native_id = m.group("native_id").strip()
                    slug = m.group("slug").strip()
                    try:
                        canonical_uuid, norm_native_id = normalize_claude_session_id(native_id)
                    except ValueError:
                        continue

                    prompt_str = str(inp.get("prompt") or "")
                    cards = (
                        extract_cards_from_text(title)
                        or extract_cards_from_text(slug)
                        or extract_cards_from_text(prompt_str[:200])
                    )
                    if not cards:
                        continue

                    child_meta = desktop_index.get(norm_native_id) or desktop_index.get(canonical_uuid) or {}
                    extra_fields: dict[str, Any] = {}
                    if child_meta.get("cliSessionId"):
                        extra_fields["cli_session_id"] = str(child_meta["cliSessionId"])
                    if child_meta.get("worktreePath"):
                        extra_fields["worktree_path"] = str(child_meta["worktreePath"])
                    if child_meta.get("worktreeBranch"):
                        extra_fields["worktree_branch"] = str(child_meta["worktreeBranch"])

                    lane_id = classify_process_lane(
                        {
                            "card": cards[0],
                            "title": title,
                            "message": f"{title} {prompt_str[:240]}",
                            "verdict_requested": ("판정" in title or "review" in slug.lower()),
                        }
                    )
                    for cid in cards:
                        if cid not in parent_spawned_cards:
                            parent_spawned_cards.append(cid)
                        lane_win = open_or_reuse_lane_window(desk, lane_id, "claude", card=cid)
                        entry = record_window(
                            desk,
                            cid,
                            "claude",
                            canonical_uuid,
                            native_id=norm_native_id,
                            session_name=slug,
                            session_title=title,
                            parent_session_id=parent_session_id,
                            lane_id=lane_id,
                            lane_window_id=str(lane_win["id"]),
                            use_worktree=bool(inp.get("use_worktree", True)),
                            context_mode=str(inp.get("context") or "fresh"),
                            source_branch=str(inp.get("source_branch") or ""),
                            parallel_ready=True,
                            **extra_fields,
                        )
                        rec_path = _record_path(desk, cid)
                        try:
                            rec_data = json.loads(rec_path.read_text(encoding="utf-8"))
                            core = clean_core_title(title)
                            if isinstance(rec_data, dict) and core:
                                rec_data["title"] = f"[{cid}] {core}"
                                rec_path.write_text(
                                    json.dumps(rec_data, ensure_ascii=False, indent=2),
                                    encoding="utf-8",
                                )
                        except (OSError, ValueError):
                            pass

                        synced_cards[cid] = {
                            "card": cid,
                            "window_id": canonical_uuid,
                            "native_id": norm_native_id,
                            "cli_session_id": extra_fields.get("cli_session_id", ""),
                            "worktree_path": extra_fields.get("worktree_path", ""),
                            "session_name": slug,
                            "session_title": title,
                            "parent_session_id": parent_session_id,
                            "lane_id": lane_id,
                            "lane_window_id": str(lane_win["id"]),
                            "opened_at": entry.get("opened_at"),
                        }

        if parent_spawned_cards and claim_topmost_parent:
            parent_meta = desktop_index.get(parent_session_id) or {}
            parent_raw_title = (
                str(parent_meta.get("title") or "")
                or uw._claude_title(parent_session_id, root=claude_sessions_root, transcript=jsonl_path)
                or ""
            )
            top_res = ensure_topmost_user_window(
                desk,
                "claude",
                parent_session_id,
                representative_title=parent_raw_title,
                now=now,
                claude_sessions_root=claude_sessions_root,
                sync_native_store=True,
            )
            if top_res.get("ok"):
                top_res["spawned_cards"] = parent_spawned_cards
                topmost_user_windows[parent_session_id] = top_res

    return {
        "ok": True,
        "project": str(desk),
        "synced_count": len(synced_cards),
        "cards": synced_cards,
        "topmost_user_windows": topmost_user_windows,
    }


def orchestrate_card_parallel_batch(
    project: Path,
    cards: Sequence[str | dict[str, Any]],
    *,
    actor: str = "antigravity",
    tools: Sequence[str] = TOOLS,
    parent_session_id: str = "",
    parent_title: str = "",
    sync_desktop: bool = True,
    transcripts_root: Path | None = None,
    claude_sessions_root: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """One-stop orchestrator for '카드별 병렬 세션 가동':
    1. Syncs any live Claude Desktop child card sessions (`local_<uuid>`) from transcripts and automatically claims
       their topmost parent session as `[YYMMDD-N] <대화창 대표 타이틀>`.
    2. If `parent_session_id` is explicitly supplied for `actor`, ensures that topmost session is also claimed and
       titled as `[YYMMDD-N] <대화창 대표 타이틀>`.
    3. Provisions unique per-card windows (`.coord/windows/<card>.json`) across all 3 tools and binds each to its
       5-Category Process Classification Lane (`.coord/windows/lanes/<lane>.json`).
    4. Builds standardized 3-tool native launch specifications (`claude_desktop`, `antigravity`, `codex`) for every
       card in the batch.
    """
    from .process_lanes import open_or_reuse_card_parallel_windows

    desk = Path(shared_desk(project)).resolve()
    sync_res = (
        sync_claude_desktop_card_sessions(
            desk,
            transcripts_root=transcripts_root,
            claude_sessions_root=claude_sessions_root,
            now=now,
        )
        if sync_desktop
        else {"ok": True, "synced_count": 0, "cards": {}, "topmost_user_windows": {}}
    )

    topmost_windows = dict(sync_res.get("topmost_user_windows") or {})
    if parent_session_id.strip():
        explicit_top = ensure_topmost_user_window(
            desk,
            actor,
            parent_session_id.strip(),
            representative_title=parent_title,
            now=now,
            claude_sessions_root=claude_sessions_root,
            sync_native_store=True,
        )
        if explicit_top.get("ok"):
            topmost_windows[parent_session_id.strip()] = explicit_top

    normalized_items: list[dict[str, Any]] = []
    flat_cards: list[str] = []
    lane_map: dict[str, str] = {}

    for raw in cards:
        if isinstance(raw, str):
            item: dict[str, Any] = {"card": raw.strip()}
        elif isinstance(raw, dict):
            item = dict(raw)
        else:
            continue
        card_str = str(item.get("card") or "").strip()
        if not card_str:
            continue
        normalized_items.append(item)
        extracted = extract_cards_from_text(card_str) or [card_str]
        for cid in extracted:
            if cid not in flat_cards:
                flat_cards.append(cid)
            if item.get("lane"):
                lane_map[cid] = validate_lane_id(str(item["lane"]))

    provision_res = open_or_reuse_card_parallel_windows(
        desk,
        flat_cards,
        tools=tools,
        lane_map=lane_map,
    )

    specs: list[dict[str, Any]] = []
    for item in normalized_items:
        card_str = str(item["card"])
        spec = build_card_parallel_launch_spec(
            desk,
            card_str,
            title=str(item.get("title") or ""),
            tool=str(item.get("tool") or "auto"),
            role=str(item.get("role") or ""),
            source_branch=str(item.get("source_branch") or ""),
            pr_url=str(item.get("pr_url") or ""),
            parent_session_id=parent_session_id,
            parent_title=parent_title,
            allowed_files=item.get("allowed_files") or (),
            accept_cmd=str(item.get("accept_cmd") or ""),
            explicit_lane=str(item.get("lane") or ""),
        )
        specs.append(spec)

    return {
        "ok": True,
        "project": str(desk),
        "actor": actor,
        "chapter_title": CHAPTER_TITLE_KO,
        "topmost_user_windows": topmost_windows,
        "cards_provisioned": provision_res.get("cards_provisioned", 0),
        "clustered_by_lane": provision_res.get("clustered_by_lane", {}),
        "synced_claude_sessions": sync_res.get("cards", {}),
        "windows": provision_res.get("cards", {}),
        "launch_specs": specs,
    }
