"""U246: REA Summary-First Analysis View Projector (inspect_analysis_view).

Retains complete analysis Evidence on disk under a stable parent_evidence_id and
returns compact summaries first, allowing agents to request bounded pages and
selected fields without flooding the LLM context window.
Explicitly separates `source_complete` from `page_exhausted` so an empty page in
a partial source never claims absence.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def retain_analysis_bundle(
    store_dir: Path | str,
    *,
    kind: str,
    target_path: str,
    items: list[dict[str, Any]],
    source_complete: bool = True,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    """Persist full analysis items and return a summary-first descriptor."""
    store = Path(store_dir)
    store.mkdir(parents=True, exist_ok=True)
    indexed_items = []
    for idx, item in enumerate(items):
        row = dict(item)
        row.setdefault("source_index", idx)
        indexed_items.append(row)
    payload_bytes = json.dumps(
        {"kind": kind, "target": target_path, "items": indexed_items, "source_complete": source_complete},
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    parent_id = "ev_bundle_" + hashlib.sha256(payload_bytes).hexdigest()[:12]
    bundle_file = store / f"{parent_id}.json"
    bundle_doc = {
        "parent_evidence_id": parent_id,
        "kind": kind,
        "target_path": target_path,
        "source_complete": bool(source_complete),
        "total_items": len(indexed_items),
        "limitations": list(limitations or []),
        "items": indexed_items,
    }
    tmp = bundle_file.with_name(f"{bundle_file.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(bundle_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, bundle_file)
    return {
        "parent_evidence_id": parent_id,
        "kind": kind,
        "target_path": target_path,
        "detail": "summary",
        "total_items": len(indexed_items),
        "source_complete": bool(source_complete),
        "limitations": list(limitations or []),
    }


def inspect_analysis_view(
    store_dir: Path | str,
    *,
    parent_evidence_id: str,
    offset: int = 0,
    limit: int = 32,
    fields: list[str] | None = None,
    names: list[str] | None = None,
) -> dict[str, Any]:
    """Project a bounded page and field subset from a retained Evidence bundle."""
    bundle_file = Path(store_dir) / f"{parent_evidence_id}.json"
    try:
        doc = json.loads(bundle_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ok": False, "error": "EVIDENCE_BUNDLE_NOT_FOUND", "parent_evidence_id": parent_evidence_id}

    all_items: list[dict[str, Any]] = doc.get("items") or []
    if names is not None:
        name_set = set(names)
        filtered = [it for it in all_items if it.get("name") in name_set or it.get("logical_path") in name_set]
    else:
        filtered = all_items

    safe_offset = max(0, int(offset))
    safe_limit = max(1, int(limit))
    sliced = filtered[safe_offset : safe_offset + safe_limit]
    projected: list[dict[str, Any]] = []
    for row in sliced:
        if fields:
            item_out = {k: row[k] for k in fields if k in row}
            item_out["source_index"] = row.get("source_index")
            if "address" in row:
                item_out["address"] = row["address"]
            projected.append(item_out)
        else:
            projected.append(dict(row))

    next_offset = safe_offset + len(projected)
    page_exhausted = next_offset >= len(filtered)
    source_complete = bool(doc.get("source_complete", False))
    return {
        "ok": True,
        "parent_evidence_id": parent_evidence_id,
        "kind": doc.get("kind"),
        "rows": projected,
        "coverage": {
            "offset": safe_offset,
            "limit": safe_limit,
            "returned_count": len(projected),
            "filtered_total": len(filtered),
            "source_total": len(all_items),
            "next_offset": None if page_exhausted else next_offset,
            "page_exhausted": page_exhausted,
            "source_complete": source_complete,
            "absence_established": bool(len(projected) == 0 and page_exhausted and source_complete),
        },
    }
