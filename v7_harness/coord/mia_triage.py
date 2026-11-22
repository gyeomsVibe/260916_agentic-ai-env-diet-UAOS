"""U354-A: Stage 0-R, the zero-token MIA tier router (MIA-Fast / MIA-Standard / MIA-Full).

Receipt: every 1-3 line idea ran the full 11-stage `mia-strategic` procedure (contract
`.work/notes/command_tower_261122/U354_ZERO_PASTE_UX_CONTRACT_261122.md` section 4). Small edits paid for four
verification rounds; risky ones (kernel, global rules, permissions) still need all eleven. This router only picks the
depth: the invariants below are returned by every tier and no tier may drop them. It reads no file and calls no model.
"""

from __future__ import annotations

import re
from typing import Any, Sequence

# Stage counts come from the contract section 1-1: Fast 0-R/1/2/3, Standard 0..5, Full the 11-stage mia-strategic.
TIERS: dict[str, dict[str, Any]] = {
    "MIA-Fast": {"steps": 4, "thinking_level": "Low", "card_slots": ("MIA", "Execute", "Verify")},
    "MIA-Standard": {"steps": 6, "thinking_level": "Medium", "card_slots": ("Research", "MIA", "Execute", "Verify")},
    "MIA-Full": {"steps": 11, "thinking_level": "High", "card_slots": ("Research", "MIA", "Execute", "Verify")},
}
# Kept by every tier (contract section 1-1, step 3 of the invariant gates); a shortcut never removes one.
INVARIANTS: tuple[str, ...] = ("author!=judge", "fixed_acceptance_exit_0", "backup_before_overwrite",
                               "safety_7_human_only")
EXPLICIT_MIA = ("mia모드 발동", "mia모드발동", "mia 전략")
# U354-A R2 (AGY REVISE C3): English parity with the Korean list (`아키텍처`/`architecture`, `삭제`/`delete`,
# `전역 규칙`/`global rule`), so an English idea is never routed one tier lower than the same idea in Korean.
HIGH_RISK = ("권한", "삭제", "전역", "보안", "규칙", "스키마", "아키텍처", "security", "permission", "schema", "kernel",
             "evaluator", "calculator_gate", "global_install", "architecture", "delete", "global rule")
MEDIUM = ("신규", "설계", "ui", "대시보드", "리팩터", "연동", "feature", "redesign", "refactor")
SENSITIVE_PATHS = ("v7_harness/calculator_gate.py", "v7_harness/rsi.py", "v7_harness/global_install.py",
                   "uaos_everywhere/uaos_global_rule_block.md", ".githooks/")
# Fast covers one or two files (contract: `<=2` files); three or more is Standard, six or more Full.
FAST_MAX_FILES = 2
FULL_MIN_FILES = 6


def _has(text: str, word: str) -> bool:
    """ASCII words match whole words only (`ui` must not match `build`); Korean words match as substrings.

    U354-A R2 (C3): an optional plural `s` matches (`permissions`), and `_` is a word boundary on both sides
    (`auth_permission`), so identifiers that embed a risky word still route to Full.
    """
    if word.isascii():
        return re.search(rf"(?<![a-z0-9]){re.escape(word)}s?(?![a-z0-9])", text) is not None
    return word in text


def _norm_path(path: str) -> str:
    norm = str(path).replace("\\", "/").strip()
    return norm[2:] if norm.startswith("./") else norm


def _sensitive(paths: Sequence[str], text: str) -> list[str]:
    """Sensitive paths named in `paths` or in the idea text; Windows `\\` and case variants match too (R2 C1, C2)."""
    hits = []
    text = text.replace("\\", "/").lower()
    norms = [_norm_path(path).lower() for path in paths]
    for target in SENSITIVE_PATHS:
        target = target.lower()
        for norm in norms:
            if norm == target or norm.endswith("/" + target) or (target.endswith("/") and
                                                                (norm.startswith(target) or "/" + target in norm)):
                hits.append(target)
                break
        else:
            if target in text:
                hits.append(target)
    return hits


def classify_mia_tier(text: str, *, file_count: int | None = None, paths: Sequence[str] = (),
                      explicit_mia: bool = False, prior_failures: int = 0,
                      needs_external_spec: bool = False) -> dict[str, Any]:
    """Pick the MIA tier for an idea; `file_count` defaults to the number of distinct `paths` (None when unknown)."""
    lowered = (text or "").lower()
    # U354-A R2 (C4): blank paths are no scope at all; an all-blank list stays unknown (None), never "1 file".
    paths = tuple(n for p in (paths or ()) if (n := _norm_path(p)))
    count = file_count if file_count is not None else (len({p.lower() for p in paths}) or None)
    failures = max(0, int(prior_failures or 0))
    full: list[str] = []
    if explicit_mia:
        full.append("explicit_mia")
    full += [f"explicit_trigger:{w}" for w in EXPLICIT_MIA if w in lowered]
    if count is not None and count >= FULL_MIN_FILES:
        full.append(f"file_count>={FULL_MIN_FILES}")
    full += [f"high_risk_keyword:{w}" for w in HIGH_RISK if _has(lowered, w)]
    full += [f"sensitive_path:{p}" for p in _sensitive(paths, lowered)]
    if failures >= 2:
        full.append("prior_failures>=2")
    medium = [f"medium_keyword:{w}" for w in MEDIUM if _has(lowered, w)]
    escalation: list[str] = []
    if failures == 1:
        escalation.append("prior_failures==1")
    if count is not None and count > FAST_MAX_FILES:
        escalation.append(f"file_count>={FAST_MAX_FILES + 1}")
    if needs_external_spec:
        escalation.append("needs_external_spec")
    if full:
        tier, reasons = "MIA-Full", full
        escalated = failures >= 2
        escalation_reason = "prior_failures>=2" if escalated else None
    elif count is not None and 1 <= count <= FAST_MAX_FILES and not medium and not escalation:
        tier, reasons, escalated, escalation_reason = "MIA-Fast", [f"file_count={count}", "no_risk_keyword"], False, None
    else:
        tier = "MIA-Standard"
        reasons = medium + escalation or ["default"]
        # Auto-escalation from Fast: the idea was otherwise Fast-sized (no medium keyword) but a trigger fired.
        escalated = bool(escalation) and not medium
        escalation_reason = ",".join(escalation) if escalated else None
    spec = TIERS[tier]
    return {"tier": tier, "steps": spec["steps"], "thinking_level": spec["thinking_level"],
            "card_slots": list(spec["card_slots"]), "escalated": escalated, "escalation_reason": escalation_reason,
            "reasons": reasons, "file_count": count, "invariants": list(INVARIANTS), "token_savings": "UNMEASURED"}
