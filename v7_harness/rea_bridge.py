"""U247: On-Demand Static REA Bridge & Contract Spec / Obligation Ledger Generator.

Provides a strictly read-only (`STATIC_ONLY`) analysis adapter inspired by
`morluto/rea` that extracts symbols, SQLite schema metadata, and module boundaries
without executing untrusted target binaries or scripts, and converts findings
into a finite Reconstruction Obligation Ledger and UAOS-RSI Contract Manual.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path
from typing import Any

PY_EXPORT_RE = re.compile(r"^(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)\b", re.MULTILINE)
TS_EXPORT_RE = re.compile(
    r"^export\s+(?:async\s+)?(?:function|class|const|interface|type|enum)\s+([A-Za-z0-9_]+)",
    re.MULTILINE,
)
RS_EXPORT_RE = re.compile(r"^pub(?:\([^)]+\))?\s+(?:async\s+)?(?:fn|struct|enum|trait)\s+([A-Za-z0-9_]+)", re.MULTILINE)


def inspect_static_target(
    target_path: Path | str,
    *,
    allow_execution: bool = False,
    allow_mutation: bool = False,
) -> dict[str, Any]:
    """Inspect a local file or directory strictly in STATIC_ONLY read-only mode."""
    if allow_execution or allow_mutation:
        return {
            "ok": False,
            "error": "MUTATION_OR_EXECUTION_FORBIDDEN",
            "reason": "UAOS-RSI REA bridge enforces STATIC_ONLY read-only inspection",
        }
    target = Path(target_path)
    if not target.exists():
        return {"ok": False, "error": "TARGET_NOT_FOUND", "target": str(target)}

    if target.is_file() and target.suffix.lower() in (".db", ".sqlite", ".sqlite3", ".vscdb"):
        return _inspect_sqlite_static(target)

    files = [target] if target.is_file() else sorted(p for p in target.rglob("*") if p.is_file())
    symbols: list[dict[str, Any]] = []
    for f in files:
        ext = f.suffix.lower()
        if ext not in (".py", ".ts", ".tsx", ".js", ".rs"):
            continue
        try:
            raw = f.read_bytes()
            text = raw.decode("utf-8", errors="replace")
        except OSError:
            continue
        digest = hashlib.sha256(raw).hexdigest()
        regex = PY_EXPORT_RE if ext == ".py" else (RS_EXPORT_RE if ext == ".rs" else TS_EXPORT_RE)
        for m in regex.findall(text):
            symbols.append({
                "name": m,
                "file": str(f.relative_to(target.parent if target.is_file() else target)).replace("\\", "/"),
                "sha256": digest,
                "tier": "OBSERVED",
            })
    return {
        "ok": True,
        "mode": "STATIC_ONLY",
        "target": str(target),
        "file_count": len(files),
        "symbol_count": len(symbols),
        "symbols": symbols,
    }


def _inspect_sqlite_static(db_path: Path) -> dict[str, Any]:
    digest = hashlib.sha256(db_path.read_bytes()).hexdigest()
    uri = f"file:{db_path.as_posix()}?mode=ro"
    tables: list[dict[str, Any]] = []
    conn = sqlite3.connect(uri, uri=True)
    try:
        cur = conn.execute("SELECT name, type, sql FROM sqlite_master WHERE type IN ('table', 'view') ORDER BY name")
        for name, kind, sql in cur.fetchall():
            tables.append({"name": name, "type": kind, "sql": sql or ""})
    finally:
        conn.close()
    return {
        "ok": True,
        "mode": "STATIC_ONLY_SQLITE",
        "target": str(db_path),
        "sha256": digest,
        "tables": tables,
    }


def build_reconstruction_obligation_ledger(
    *,
    target_id: str,
    claims: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create a finite typed obligation ledger for clean-room reconstruction (REA verify_reconstruction)."""
    obligations = []
    for idx, c in enumerate(claims):
        obligations.append({
            "obligation_id": f"{target_id}-OBL-{idx + 1:03d}",
            "symbol": c.get("symbol", f"item_{idx + 1}"),
            "expected_behavior": c.get("expected_behavior", ""),
            "oracle_cases": int(c.get("oracle_cases", 1)),
            "status": "PENDING",
        })
    return {
        "target_id": target_id,
        "total_obligations": len(obligations),
        "obligations": obligations,
        "global_equivalence_claimed": False,
    }


def generate_contract_manual_from_rea(
    *,
    work_id: str,
    obligation_ledger: dict[str, Any],
    allowed_files: list[str],
    accept_cmd: str,
    primary_sources: list[str],
) -> str:
    """Render a UAOS-RSI contract manual binding REA obligations and primary sources."""
    obl_lines = "\n".join(
        f"- `{o['obligation_id']}` (`{o['symbol']}`): {o['expected_behavior']} (oracle cases: {o['oracle_cases']})"
        for o in obligation_ledger.get("obligations", [])
    )
    src_lines = "\n".join(f"- {u}" for u in primary_sources)
    allow_lines = "\n".join(f"  - {f}" for f in allowed_files)
    return (
        f"# {work_id} REA Reconstruction Contract Manual\n\n"
        f"## Primary Sources\n{src_lines}\n\n"
        f"## Reconstruction Obligations\n{obl_lines}\n\n"
        f"```contract\n"
        f"work_id: {work_id}\n"
        f"worker: local\n"
        f"judge: codex\n"
        f"allow:\n{allow_lines}\n"
        f"accept_cmd: {accept_cmd}\n"
        f"```\n"
    )
