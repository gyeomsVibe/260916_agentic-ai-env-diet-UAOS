"""U293: 3-Tool Standardized Card-by-Card Parallel Session Execution Engine (Card Sessions + 5-Lane Multiplexing).

Synthesizes the best-in-class parallel session architectures across Claude Code Desktop (`mcp__ccd_session__start_session`,
`mcp__ccd_session__mark_chapter`, `SendMessage`, `local_<uuid>` child sessions, `use_worktree=True`), OpenAI Codex
(`codex app-server` JSON-RPC `thread/start`, `turn/start`, `thread/name/set`), Google Antigravity (`invoke_subagent`
with `Workspace="branch"`, `send_message`, `agy -p`), and GitHub/Reddit worktree-per-card patterns (Vibe Kanban,
Crystal/Nimbalyst, Claude Squad, Planner-Builder-Gatekeeper):

1. Guarantees `1 Card = 1 Unique Session UUID = 1 Isolated Git Worktree = 1 Fresh Context Envelope` across all 3 tools
   while binding each card session to its 5-Category Process Classification Lane (`IMPL_CODE`, `VERIFY_AUDIT`,
   `ARCH_DESIGN`, `MERGE_RELEASE`, `RECOVERY_OPS`).
2. Normalizes Claude Desktop child session IDs (`local_<uuid>` <-> canonical `<uuid>`) so `uaos coord window` and
   `SendMessage` work seamlessly without `ValueError`.
3. Automatically discovers and syncs live Claude Desktop child card sessions (`mcp__ccd_session__start_session`) from
   transcript JSONLs into `.coord/windows/<card>.json` (supporting both single-card and multi-card titles such as
   `U276+U284`).
4. Generates deterministic 3-tool native launch specifications (`build_card_parallel_launch_spec`) and orchestrates
   multi-card parallel batches (`orchestrate_card_parallel_batch`).
"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any
import hashlib
import json
import os
import re
import time

from .hook_context import shared_desk
from .process_lanes import (
    TOOLS,
    classify_process_lane,
    open_or_reuse_lane_window,
    select_active_tool_for_lane,
    validate_lane_id,
)

CHAPTER_TITLE_KO = "카드별 병렬 세션 가동"
LOCAL_SESSION_ID_RE = re.compile(
    r"^(?:local_)?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
    re.IGNORECASE,
)
CARD_TOKEN_RE = re.compile(r"\b(U\d{1,5}[A-Z]?)\b", re.IGNORECASE)
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
    allowed_files: Sequence[str] = (),
    accept_cmd: str = "",
    explicit_lane: str = "",
) -> dict[str, Any]:
    """Build a standardized 3-tool card-parallel child session launch specification.

    Combines:
    - Claude Desktop `mcp__ccd_session__mark_chapter` + `mcp__ccd_session__start_session` (`context="fresh"`, `use_worktree=True`)
    - Antigravity `invoke_subagent` (`Workspace="branch"`, `TypeName="self"`) + headless `agy -p`
    - OpenAI Codex `codex app-server` JSON-RPC (`thread/start`, `turn/start`, `thread/name/set`)
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
        "worktree_path": worktree_rel,
        "branch": branch_name,
        "chapter_title": CHAPTER_TITLE_KO,
        "prompt": prompt_text,
        "background": background_text,
        "native_launchers": {
            "claude_desktop": {
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
                ]
            },
        },
    }


def sync_claude_desktop_card_sessions(
    project: Path,
    *,
    transcripts_root: Path | None = None,
    max_files: int = 25,
) -> dict[str, Any]:
    """Scan Claude Code Desktop transcripts (`~/.claude/projects/*/*.jsonl`) for `mcp__ccd_session__start_session`
    calls and automatically bind discovered `local_<uuid>` child card sessions into `.coord/windows/<card>.json`.

    Supports both single-card titles (`"U291 PR #256 비작성자 판정"`) and multi-card titles
    (`"U276+U284 파일럿·작성자 출처 확인"` -> binds both `U276` and `U284`).
    """
    from v7_harness.card_pipeline import clean_core_title
    from .windows import _record_path, record_window

    desk = Path(shared_desk(project)).resolve()
    if transcripts_root is None:
        claude_home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
        transcripts_root = claude_home / "projects"

    if not transcripts_root.is_dir():
        return {"ok": True, "synced_count": 0, "cards": {}, "reason": "NO_TRANSCRIPTS_DIR"}

    candidates = sorted(
        transcripts_root.rglob("*.jsonl"),
        key=lambda p: p.stat().st_mtime if p.is_file() else 0.0,
        reverse=True,
    )[: max(1, max_files)]

    # Process oldest-to-newest among the recent slice so the newest session binding wins
    synced_cards: dict[str, dict[str, Any]] = {}
    for jsonl_path in reversed(candidates):
        parent_session_id = jsonl_path.stem
        try:
            raw_text = jsonl_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "mcp__ccd_session__start_session" not in raw_text and "Started session " not in raw_text:
            continue

        tool_uses: dict[str, dict[str, Any]] = {}
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

                    lane_id = classify_process_lane(
                        {
                            "card": cards[0],
                            "title": title,
                            "message": f"{title} {prompt_str[:240]}",
                            "verdict_requested": ("판정" in title or "review" in slug.lower()),
                        }
                    )
                    for cid in cards:
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
                        )
                        # Ensure top-level card window record carries the human-readable core title
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
                            "session_name": slug,
                            "session_title": title,
                            "parent_session_id": parent_session_id,
                            "lane_id": lane_id,
                            "lane_window_id": str(lane_win["id"]),
                            "opened_at": entry.get("opened_at"),
                        }

    return {
        "ok": True,
        "project": str(desk),
        "synced_count": len(synced_cards),
        "cards": synced_cards,
    }


def orchestrate_card_parallel_batch(
    project: Path,
    cards: Sequence[str | dict[str, Any]],
    *,
    actor: str = "antigravity",
    tools: Sequence[str] = TOOLS,
    parent_session_id: str = "",
    sync_desktop: bool = True,
    transcripts_root: Path | None = None,
) -> dict[str, Any]:
    """One-stop orchestrator for '카드별 병렬 세션 가동':
    1. Syncs any live Claude Desktop child card sessions (`local_<uuid>`) from transcripts.
    2. Provisions unique per-card windows (`.coord/windows/<card>.json`) across all 3 tools and binds each to its
       5-Category Process Classification Lane (`.coord/windows/lanes/<lane>.json`).
    3. Builds standardized 3-tool native launch specifications (`claude_desktop`, `antigravity`, `codex`) for every
       card in the batch.
    """
    from .process_lanes import open_or_reuse_card_parallel_windows

    desk = Path(shared_desk(project)).resolve()
    sync_res = (
        sync_claude_desktop_card_sessions(desk, transcripts_root=transcripts_root)
        if sync_desktop
        else {"ok": True, "synced_count": 0, "cards": {}}
    )

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
        "cards_provisioned": provision_res.get("cards_provisioned", 0),
        "clustered_by_lane": provision_res.get("clustered_by_lane", {}),
        "synced_claude_sessions": sync_res.get("cards", {}),
        "windows": provision_res.get("cards", {}),
        "launch_specs": specs,
    }
