"""U245: Evidence Citation Invariant Gate & REA 4-Tier Epistemic Provenance Ledger.

Enforces the permanent UAOS-RSI rule (2026-10-20 / U245):
1. Every planning, analysis, or proposal report must include primary source links
   (news article URL and/or official GitHub repository URL). Reports without
   primary source URLs are automatically rejected as FAILED (MISSING_PRIMARY_SOURCE).
2. Preserves REA epistemic provenance tiers (OBSERVED, DERIVED, INFERRED, UNKNOWN)
   with content-addressed evidence_id and revision-checked unknown tracking.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

EPISTEMIC_TIERS = ("OBSERVED", "DERIVED", "INFERRED", "UNKNOWN")
VERIFYING_TIERS = ("OBSERVED", "DERIVED")
URL_RE = re.compile(r"https?://[^\s)>\]\"']+", re.IGNORECASE)
GITHUB_URL_RE = re.compile(r"https?://(?:www\.)?github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", re.IGNORECASE)


def extract_urls(text: str) -> list[str]:
    """Return unique HTTP(S) URLs found in text in order of appearance."""
    seen: set[str] = set()
    out: list[str] = []
    for match in URL_RE.findall(text or ""):
        cleaned = match.rstrip(".,;:!?")
        if cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)
    return out


def verify_report_citations(
    report_text: str,
    *,
    require_github: bool = True,
    require_article_or_doc: bool = True,
) -> dict[str, Any]:
    """Gate planning/analysis reports on mandatory primary source URLs (U245).

    Returns verdict="PASS" when required primary source links are present,
    or verdict="FAILED" with error="MISSING_PRIMARY_SOURCE" otherwise.
    """
    urls = extract_urls(report_text or "")
    github_urls = [u for u in urls if GITHUB_URL_RE.match(u)]
    external_doc_urls = [u for u in urls if not GITHUB_URL_RE.match(u)]
    missing: list[str] = []
    if not urls:
        missing.append("primary_source_url")
    if require_github and not github_urls:
        missing.append("github_repository_url")
    if require_article_or_doc and not external_doc_urls:
        missing.append("article_or_official_doc_url")
    if missing:
        return {
            "verdict": "FAILED",
            "error": "MISSING_PRIMARY_SOURCE",
            "missing": missing,
            "urls_found": urls,
        }
    return {
        "verdict": "PASS",
        "error": None,
        "missing": [],
        "urls_found": urls,
        "github_urls": github_urls,
        "article_urls": external_doc_urls,
    }


class EvidenceLedger:
    """REA-inspired epistemic provenance and unknown registry stored on disk."""

    def __init__(self, ledger_dir: Path | str) -> None:
        self.ledger_dir = Path(ledger_dir)
        self.evidence_path = self.ledger_dir / "evidence_records.json"
        self.unknowns_path = self.ledger_dir / "unknown_records.json"

    def _read_json(self, path: Path, default: Any) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def record_evidence(
        self,
        *,
        kind: str,
        claim: str,
        tier: str,
        source_url: str,
        digest: str = "",
        limitations: str = "",
        now: float | None = None,
    ) -> dict[str, Any]:
        """Record an epistemic finding and return its stable evidence_id."""
        tier_norm = (tier or "").upper()
        if tier_norm not in EPISTEMIC_TIERS:
            raise ValueError(f"Unsupported epistemic tier: {tier!r}")
        if not URL_RE.match(source_url or ""):
            raise ValueError(f"Primary source_url required: {source_url!r}")
        raw_key = f"{kind}|{claim}|{tier_norm}|{source_url}|{digest}"
        evidence_id = "ev_" + hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:12]
        records = self._read_json(self.evidence_path, {})
        entry = {
            "evidence_id": evidence_id,
            "kind": kind,
            "claim": claim,
            "tier": tier_norm,
            "source_url": source_url,
            "digest": digest,
            "limitations": limitations,
            "recorded_at": time.time() if now is None else now,
        }
        records[evidence_id] = entry
        self._write_json(self.evidence_path, records)
        return entry

    def record_unknown(
        self,
        *,
        question: str,
        authority_needed: str,
        supporting_ids: list[str] | None = None,
        contradicting_ids: list[str] | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Track an unresolved question in the session registry (REA record_unknown)."""
        unknown_id = "unk_" + hashlib.sha256(question.encode("utf-8")).hexdigest()[:12]
        unknowns = self._read_json(self.unknowns_path, {})
        existing = unknowns.get(unknown_id)
        revision = int(existing.get("revision", 0)) + 1 if isinstance(existing, dict) else 1
        entry = {
            "unknown_id": unknown_id,
            "question": question,
            "authority_needed": authority_needed,
            "supporting_ids": list(supporting_ids or []),
            "contradicting_ids": list(contradicting_ids or []),
            "state": "OPEN",
            "revision": revision,
            "resolved_by": None,
            "updated_at": time.time() if now is None else now,
        }
        unknowns[unknown_id] = entry
        self._write_json(self.unknowns_path, unknowns)
        return entry

    def update_unknown(
        self,
        *,
        unknown_id: str,
        expected_revision: int,
        resolved_by_evidence_id: str,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Resolve an unknown only when revision matches and evidence is OBSERVED/DERIVED."""
        unknowns = self._read_json(self.unknowns_path, {})
        target = unknowns.get(unknown_id)
        if not isinstance(target, dict):
            return {"ok": False, "error": "UNKNOWN_NOT_FOUND"}
        if int(target.get("revision", 0)) != int(expected_revision):
            return {
                "ok": False,
                "error": "STALE_REVISION",
                "current_revision": target.get("revision"),
            }
        records = self._read_json(self.evidence_path, {})
        ev = records.get(resolved_by_evidence_id)
        if not isinstance(ev, dict):
            return {"ok": False, "error": "EVIDENCE_NOT_FOUND"}
        if ev.get("tier") not in VERIFYING_TIERS:
            return {
                "ok": False,
                "error": "UNVERIFIED_RESOLUTION",
                "reason": f"Tier {ev.get('tier')} cannot resolve an unknown; OBSERVED or DERIVED required",
            }
        target["state"] = "RESOLVED"
        target["resolved_by"] = resolved_by_evidence_id
        target["revision"] = int(target["revision"]) + 1
        target["updated_at"] = time.time() if now is None else now
        unknowns[unknown_id] = target
        self._write_json(self.unknowns_path, unknowns)
        return {"ok": True, "unknown": target}
