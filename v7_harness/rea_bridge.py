"""U247 / U275: On-Demand Static REA Bridge, PE/Binary String Extractor & Contract Spec / Obligation Ledger Generator.

Provides a strictly read-only (`STATIC_ONLY`) analysis adapter inspired by
`morluto/rea` that extracts symbols, PE/ELF/WASM binary URLs/strings, SQLite schema
metadata, and module boundaries without executing untrusted target binaries or
scripts, and converts findings into a finite Reconstruction Obligation Ledger and
UAOS-RSI Contract Manual.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

PY_EXPORT_RE = re.compile(r"^(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)\b", re.MULTILINE)
TS_EXPORT_RE = re.compile(
    r"^export\s+(?:async\s+)?(?:function|class|const|interface|type|enum)\s+([A-Za-z0-9_]+)",
    re.MULTILINE,
)
RS_EXPORT_RE = re.compile(r"^pub(?:\([^)]+\))?\s+(?:async\s+)?(?:fn|struct|enum|trait)\s+([A-Za-z0-9_]+)", re.MULTILINE)

def has_symlink_or_junction_ancestor(path: Path, root: Path | None = None) -> bool:
    """True if path or ANY ancestor up to filesystem root (or root) is a symlink,
    Windows junction, or reparse point, or if path resolves outside root.
    """
    try:
        if root is not None:
            try:
                if not path.resolve().is_relative_to(root.resolve()):
                    return True
            except OSError:
                return True
        check_p = path.absolute()
        while check_p and check_p != check_p.parent:
            if is_symlink_or_junction(check_p):
                return True
            if root is not None and check_p.resolve() == root.resolve():
                break
            check_p = check_p.parent
    except OSError:
        return True
    return False


def is_symlink_or_junction(path: Path) -> bool:
    """True if path is a POSIX symlink, Windows junction, or reparse point."""
    import os
    try:
        if path.is_symlink():
            return True
        if hasattr(path, "is_junction") and path.is_junction():
            return True
        if hasattr(os.path, "isjunction") and os.path.isjunction(path):
            return True
        st = path.lstat()
        attrs = getattr(st, "st_file_attributes", 0)
        if attrs and (attrs & 0x0400):
            return True
    except OSError:
        return True
    return False


FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
READ_CHUNK = 1 << 20  # 1 MiB per os.read call; bounds one syscall, not the file size (no size cap existed before R8).


class ConfinementError(OSError):
    """A refused confined read; `code` is the stable error string surfaced in failed_files / error."""

    def __init__(self, code: str, path: Path | str = "") -> None:
        super().__init__(f"{code}: {path}")
        self.code = code


def _require_regular(st: os.stat_result, path: Path) -> None:
    if not stat.S_ISREG(st.st_mode) or (getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT):
        raise ConfinementError("NOT_REGULAR_FILE", path)


def _opened_final_path(fd: int) -> str:
    """Path of the object behind an open fd, from the OS (not from the name we opened).

    Windows: GetFinalPathNameByHandleW on the CRT handle (Microsoft: returns the final, fully resolved path for a
    file handle). Linux: /proc/self/fd. macOS: fcntl F_GETPATH. Anything else, or an API failure, raises
    HANDLE_PATH_UNKNOWN so the caller reads nothing (fail closed).
    """
    import sys

    if sys.platform == "win32":
        import ctypes
        import msvcrt
        from ctypes import wintypes

        handle = msvcrt.get_osfhandle(fd)
        fn = ctypes.windll.kernel32.GetFinalPathNameByHandleW
        fn.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
        fn.restype = wintypes.DWORD
        size = 1024
        while True:
            buf = ctypes.create_unicode_buffer(size)
            n = fn(handle, buf, size, 0)  # 0 = FILE_NAME_NORMALIZED | VOLUME_NAME_DOS
            if n == 0:
                raise ConfinementError("HANDLE_PATH_UNKNOWN", f"fd {fd}")
            if n < size:
                break
            size = n + 1
        final = buf.value
        if final.startswith("\\\\?\\UNC\\"):
            final = "\\\\" + final[8:]
        elif final.startswith("\\\\?\\"):
            final = final[4:]
        return final
    if sys.platform.startswith("linux"):
        try:
            return os.readlink(f"/proc/self/fd/{fd}")
        except OSError as exc:
            raise ConfinementError("HANDLE_PATH_UNKNOWN", f"fd {fd}") from exc
    if sys.platform == "darwin":
        try:
            import fcntl

            out = fcntl.fcntl(fd, 50, b"\0" * 1024)  # F_GETPATH
            return out.split(b"\0", 1)[0].decode("utf-8", "surrogateescape")
        except OSError as exc:
            raise ConfinementError("HANDLE_PATH_UNKNOWN", f"fd {fd}") from exc
    raise ConfinementError("HANDLE_PATH_UNKNOWN", f"fd {fd}")


def _within(child: str, root: Path) -> bool:
    base = os.path.normcase(os.path.realpath(str(root)))
    c = os.path.normcase(child)
    return c == base or c.startswith(base.rstrip("\\/") + os.sep)


def _read_confined_bytes(path: Path, root: Path | None) -> bytes:
    """U275-R8: read `path` only through a descriptor whose identity was verified to be the in-root regular file.

    Order: ancestor check -> lstat -> open -> fstat identity -> opened-handle final path in root ->
    ancestor check + lstat identity -> read via fd.
    Any mismatch raises ConfinementError before a single content byte is consumed; the fd is closed on all branches.
    """
    path = Path(path)
    # Trusted context: the caller's analysis root; a standalone file call trusts only its own directory.
    trusted_root = Path(root) if root is not None else path.absolute().parent
    if has_symlink_or_junction_ancestor(path, root):
        raise ConfinementError("SYMLINK_OR_JUNCTION_ESCAPE", path)
    pre = os.lstat(path)
    _require_regular(pre, path)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (pre.st_dev, pre.st_ino) or not stat.S_ISREG(opened.st_mode):
            raise ConfinementError("HANDLE_IDENTITY_MISMATCH", path)
        # rev2 (Claude review P2): name-based checks can be raced by swapping an ancestor to a junction and back.
        # The OS-reported path of the opened object itself must lie inside the trusted root.
        if not _within(_opened_final_path(fd), trusted_root):
            raise ConfinementError("HANDLE_PATH_OUTSIDE_ROOT", path)
        if has_symlink_or_junction_ancestor(path, root):
            raise ConfinementError("SYMLINK_OR_JUNCTION_ESCAPE", path)
        post = os.lstat(path)
        if (post.st_dev, post.st_ino) != (pre.st_dev, pre.st_ino):
            raise ConfinementError("HANDLE_IDENTITY_MISMATCH", path)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, READ_CHUNK)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


BIN_URL_RE = re.compile(rb"https?://[A-Za-z0-9._/\-:?=&%]+")
BIN_IDENT_RE = re.compile(rb"(?:src-tauri/[A-Za-z0-9._/\-]+|[a-z_]+::[a-z0-9_:]{4,64})")

BINARY_EXTS = frozenset({".exe", ".dll", ".so", ".dylib", ".apk", ".dex", ".asar", ".wasm"})
SQLITE_EXTS = frozenset({".db", ".sqlite", ".sqlite3", ".vscdb"})


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

    if target.is_file() and target.suffix.lower() in SQLITE_EXTS:
        return _inspect_sqlite_static(target)

    if target.is_file() and target.suffix.lower() in BINARY_EXTS:
        return _inspect_binary_static(target)

    root_resolved = target.resolve()
    files: list[Path] = []
    failed_files: list[dict[str, str]] = []
    if target.is_file():
        files = [target]
    else:
        for p in sorted(target.rglob("*")):
            if ".git" in p.parts:
                continue
            is_esc = False
            if is_symlink_or_junction(p):
                is_esc = True
            else:
                try:
                    if not p.resolve().is_relative_to(root_resolved):
                        is_esc = True
                except OSError:
                    is_esc = True
            if is_esc:
                failed_files.append({"file": p.relative_to(target).as_posix() if p != target else p.name, "error": "SYMLINK_OR_JUNCTION_ESCAPE"})
                continue
            if p.is_file():
                files.append(p)

    symbols: list[dict[str, Any]] = []
    sqlite_dbs: list[dict[str, Any]] = []
    binaries: list[dict[str, Any]] = []

    for f in files:
        ext = f.suffix.lower()
        rel_str = str(f.relative_to(target.parent if target.is_file() else target)).replace("\\", "/")
        if has_symlink_or_junction_ancestor(f, root_resolved):
            failed_files.append({"file": rel_str, "error": "SYMLINK_OR_JUNCTION_ESCAPE"})
            continue
        if ext in SQLITE_EXTS:
            db_res = _inspect_sqlite_static(f, root_resolved)
            db_res["file"] = rel_str
            if not db_res.get("ok"):
                failed_files.append({"file": rel_str, "error": str(db_res.get("error") or "SQLITE_INVALID")})
                continue
            sqlite_dbs.append(db_res)
            for tbl in db_res.get("tables", []):
                symbols.append({
                    "name": f"sqlite_table:{tbl['name']}",
                    "file": rel_str,
                    "sha256": db_res["sha256"],
                    "tier": "OBSERVED",
                })
            continue
        if ext in BINARY_EXTS:
            try:
                bin_res = _inspect_binary_static(f, root_resolved)
                bin_res["file"] = rel_str
                if not bin_res.get("ok"):
                    failed_files.append({"file": rel_str, "error": str(bin_res.get("error") or "BINARY_READ_FAILED")})
                    continue
                binaries.append(bin_res)
                for s_item in bin_res.get("symbols", [])[:50]:
                    symbols.append({
                        "name": s_item["name"],
                        "file": rel_str,
                        "sha256": bin_res["sha256"],
                        "tier": "OBSERVED",
                    })
            except Exception as exc:
                failed_files.append({"file": rel_str, "error": f"{type(exc).__name__}: {exc}"})
            continue
        if ext not in (".py", ".ts", ".tsx", ".js", ".rs"):
            continue
        try:
            raw = _read_confined_bytes(f, root_resolved)
            text = raw.decode("utf-8", errors="replace")
        except ConfinementError as exc:
            failed_files.append({"file": rel_str, "error": exc.code})
            continue
        except OSError as exc:
            failed_files.append({"file": rel_str, "error": f"OS_READ_ERROR: {exc}"})
            continue
        digest = hashlib.sha256(raw).hexdigest()
        regex = PY_EXPORT_RE if ext == ".py" else (RS_EXPORT_RE if ext == ".rs" else TS_EXPORT_RE)
        for m in regex.findall(text):
            symbols.append({
                "name": m,
                "file": rel_str,
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
        "sqlite_databases": sqlite_dbs,
        "binaries": binaries,
        "failed_files": failed_files,
        "source_complete": len(failed_files) == 0,
    }


def _inspect_binary_static(bin_path: Path, root: Path | None = None) -> dict[str, Any]:
    """Extract deterministic static metadata, URLs, and module identifiers from a PE/ELF/WASM binary without executing it.
    Guarantees handle-bound confinement: before and after reading, verifies that bin_path and all ancestors
    are not symlinks/junctions and remain contained in root.
    """
    try:
        raw = _read_confined_bytes(bin_path, root)
    except ConfinementError as exc:
        return {"ok": False, "mode": "STATIC_ONLY_BINARY", "target": str(bin_path), "error": exc.code}
    except OSError as exc:
        return {
            "ok": False,
            "mode": "STATIC_ONLY_BINARY",
            "target": str(bin_path),
            "error": f"READ_ERROR: {exc}",
        }
    digest = hashlib.sha256(raw).hexdigest()
    urls = sorted({m.decode("ascii", errors="ignore") for m in BIN_URL_RE.findall(raw)})[:100]
    idents = sorted({m.decode("ascii", errors="ignore") for m in BIN_IDENT_RE.findall(raw)})[:100]
    symbols: list[dict[str, Any]] = []
    for u in urls:
        symbols.append({"name": f"url:{u}", "file": bin_path.name, "sha256": digest, "tier": "OBSERVED"})
    for ident in idents:
        symbols.append({"name": f"ident:{ident}", "file": bin_path.name, "sha256": digest, "tier": "OBSERVED"})
    return {
        "ok": True,
        "mode": "STATIC_ONLY_BINARY",
        "target": str(bin_path),
        "size_bytes": len(raw),
        "sha256": digest,
        "urls": urls,
        "identifiers": idents,
        "symbol_count": len(symbols),
        "symbols": symbols,
    }


def _inspect_sqlite_static(db_path: Path, root: Path | None = None) -> dict[str, Any]:
    """Inspect a SQLite DB using a disposable temporary snapshot so:
    1. Filenames with `#` or `?` never break URI parsing or create stray files.
    2. WAL-mode databases never have `-shm` sidecars created in the source directory.
    3. WAL file is copied to temp snapshot BEFORE hashing to eliminate hash/copy races.
    """
    wal_path = Path(str(db_path) + "-wal")
    shm_path = Path(str(db_path) + "-shm")

    tables: list[dict[str, Any]] = []
    try:
        with tempfile.TemporaryDirectory(prefix="uaos_rea_sqlite_") as tmp_dir:
            snap_db = Path(tmp_dir) / "snapshot.sqlite"
            snap_wal = Path(str(snap_db) + "-wal")
            snap_shm = Path(str(snap_db) + "-shm")

            try:
                main_bytes = _read_confined_bytes(db_path, root)
            except ConfinementError as exc:
                return {"ok": False, "mode": "STATIC_ONLY_SQLITE", "target": str(db_path), "error": exc.code}
            except OSError as exc:
                return {"ok": False, "mode": "STATIC_ONLY_SQLITE", "target": str(db_path), "error": f"READ_ERROR: {exc}"}
            snap_db.write_bytes(main_bytes)
            if main_bytes and len(main_bytes) >= 16 and not main_bytes.startswith(b"SQLite format 3\x00"):
                return {
                    "ok": False,
                    "mode": "STATIC_ONLY_SQLITE",
                    "target": str(db_path),
                    "error": "INVALID_SQLITE_HEADER",
                }

            # Sidecars: a missing/unreadable WAL or SHM keeps the old best-effort behaviour, but a confinement
            # refusal is an error, never silently skipped (bytes from outside root must not enter the snapshot).
            wal_bytes = b""
            for side, snap_side in ((wal_path, snap_wal), (shm_path, snap_shm)):
                if not os.path.lexists(side):
                    continue
                try:
                    data = _read_confined_bytes(side, root)
                except ConfinementError as exc:
                    return {"ok": False, "mode": "STATIC_ONLY_SQLITE", "target": str(db_path), "error": exc.code}
                except OSError:
                    continue
                snap_side.write_bytes(data)
                if side is wal_path:
                    wal_bytes = data

            h = hashlib.sha256(main_bytes)
            if wal_bytes:
                h.update(b"|WAL|")
                h.update(wal_bytes)
            digest = h.hexdigest()

            uri = snap_db.resolve().as_uri() + "?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=3)
            try:
                cur = conn.execute(
                    "SELECT name, type, sql FROM sqlite_master WHERE type IN ('table', 'view') ORDER BY name"
                )
                for name, kind, sql in cur.fetchall():
                    tables.append({"name": name, "type": kind, "sql": sql or ""})
            finally:
                conn.close()
    except sqlite3.Error as exc:
        return {
            "ok": False,
            "mode": "STATIC_ONLY_SQLITE",
            "target": str(db_path),
            "sha256": digest if "digest" in locals() else "",
            "error": f"SQLITE_ERROR: {exc}",
        }
    except OSError as exc:
        return {
            "ok": False,
            "mode": "STATIC_ONLY_SQLITE",
            "target": str(db_path),
            "error": f"SNAPSHOT_IO_ERROR: {exc}",
        }

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
    files_lines = "\n".join(f"  - {f}" for f in allowed_files)
    return (
        f"# Contract Manual: {work_id}\n\n"
        f"```contract\n"
        f"id: {work_id}\n"
        f"worker: local\n"
        f"judge: codex\n"
        f"allow:\n"
        f"{files_lines}\n"
        f"accept: {accept_cmd}\n"
        f"```\n\n"
        f"## Primary Sources (Stage 0 Mandatory)\n"
        f"{src_lines}\n\n"
        f"## REA Reconstruction Obligations (Finite Typed Scope)\n"
        f"{obl_lines}\n"
    )


def execute_auto_reverse_engineering_pipeline(
    project_root: Path | str,
    target_path: Path | str,
    *,
    primary_sources: list[str] | None = None,
    page_limit: int = 20,
) -> dict[str, Any]:
    """U275: Automatically run the full REA reverse-engineering pipeline on a binary, SQLite DB, or external repo."""
    from v7_harness.analysis_view import inspect_analysis_view, retain_analysis_bundle
    from v7_harness.evidence_ledger import EvidenceLedger
    from v7_harness.library_store import CANONICAL_LIBRARY_ROOT, inspect_library_repo, register_library_entry

    desk = Path(project_root)
    target = Path(target_path)
    if not target.is_absolute():
        candidate = desk / target
        if candidate.exists():
            target = candidate

    static_res = inspect_static_target(target)
    if not static_res.get("ok"):
        return {
            "ok": False,
            "error": static_res.get("error", "INSPECTION_FAILED"),
            "target": str(target),
            "static_inspection": static_res,
        }

    items: list[dict[str, Any]] = []
    if static_res.get("mode") == "STATIC_ONLY_SQLITE":
        for tbl in static_res.get("tables", []):
            items.append({"name": tbl["name"], "type": tbl["type"], "sql": tbl["sql"], "sha256": static_res["sha256"]})
    elif static_res.get("mode") == "STATIC_ONLY_BINARY":
        items = list(static_res.get("symbols", []))
    else:
        items = list(static_res.get("symbols", []))

    failed_list = list(static_res.get("failed_files") or [])
    is_complete = bool(static_res.get("source_complete", True)) and len(failed_list) == 0
    limitations = [f"{item['file']}: {item['error']}" for item in failed_list]

    store_dir = desk / ".work" / "rea_bundles"
    bundle_meta = retain_analysis_bundle(
        store_dir,
        kind=str(static_res.get("mode", "STATIC_ONLY")).lower(),
        target_path=str(target),
        items=items,
        source_complete=is_complete,
        limitations=limitations,
    )
    first_page = inspect_analysis_view(
        store_dir,
        parent_evidence_id=bundle_meta["parent_evidence_id"],
        offset=0,
        limit=page_limit,
        fields=["name", "file", "type"],
    )

    ev_ledger = EvidenceLedger(desk / ".work" / "rea_ledger")
    sources = list(primary_sources or ["https://github.com/morluto/rea"])
    ev_rec = ev_ledger.record_evidence(
        kind=str(static_res.get("mode", "STATIC_ONLY")).lower(),
        claim=(
            f"Auto-REA {static_res.get('mode')} inspection of {target.name}: "
            f"{len(items)} items extracted (bundle={bundle_meta['parent_evidence_id']})"
        ),
        tier="OBSERVED" if is_complete else "DERIVED",
        source_url=sources[0],
        digest=str(static_res.get("sha256") or bundle_meta["parent_evidence_id"]),
        limitations="; ".join(limitations),
    )

    top_claims = [
        {
            "symbol": str(it.get("name", f"item_{i}")),
            "expected_behavior": f"Clean-room behavioral parity for {it.get('name', 'symbol')} ({it.get('file', target.name)})",
            "oracle_cases": 2,
        }
        for i, it in enumerate(items[:10])
    ]
    if not top_claims:
        top_claims = [{"symbol": target.name, "expected_behavior": "Static artifact structure verified", "oracle_cases": 1}]
    obligation_ledger = build_reconstruction_obligation_ledger(
        target_id=target.stem.upper() or "REA_TARGET",
        claims=top_claims,
    )

    library_registration: dict[str, Any] | None = None
    try:
        resolved_target = target.resolve()
        lib_root = CANONICAL_LIBRARY_ROOT.resolve()
        if resolved_target == lib_root or lib_root in resolved_target.parents:
            repo_dir = resolved_target if resolved_target.parent == lib_root else next(
                p for p in resolved_target.parents if p.parent == lib_root
            )
            info = inspect_library_repo(repo_dir)
            if info.get("ok"):
                readme_path = register_library_entry(
                    library_root=lib_root,
                    folder_name=repo_dir.name,
                    source_url=info.get("origin_url") or f"https://github.com/unknown/{repo_dir.name}",
                    license_id="Open Source",
                    commit_sha=info.get("commit_sha", "UNKNOWN"),
                    file_count=int(info.get("file_count", 0)),
                    description="Auto-registered by U275 REA reverse-engineering pipeline",
                )
                library_registration = {"registered": True, "repo": repo_dir.name, "readme": str(readme_path)}
    except Exception:
        library_registration = None

    return {
        "ok": True,
        "auto_triggered": True,
        "target": str(target),
        "mode": static_res.get("mode"),
        "file_count": static_res.get("file_count", 1),
        "total_extracted_items": len(items),
        "source_complete": is_complete,
        "failed_files": failed_list,
        "bundle_summary": bundle_meta,
        "first_page_preview": first_page,
        "epistemic_evidence": ev_rec,
        "obligation_ledger": obligation_ledger,
        "library_registration": library_registration,
    }
