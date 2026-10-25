"""UAOS Documentation Manager (docs_manager.py).

Provides automatic docs/ folder scaffolding, default 00_DOCUMENT_INDEX.md generation,
and chronological auto-numbering logic that inspects preceding and succeeding documents.
"""

from __future__ import annotations

import os
import re
import threading
from functools import wraps
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

KST = timezone(timedelta(hours=9))
_DOC_LOCKS = threading.local()

INDEX_FILENAME = "00_DOCUMENT_INDEX.md"
INDEX_HEADER_TEMPLATE = """# UAOS-RSI 프로젝트 공식 문서 전체 색인 (Document Master Index)

> **프로젝트**: {project_name}  
> **자동 생성 일시**: {created_at_kst}  
> **정렬 원칙**: 실제 문서 작성 및 등록 일시(KST) 기준 완전 엄격 연대기 정렬 (Chronological Ordering), 번호 중복·누락 방지 단일 순번 부여

---

## 전체 문서 전수 매핑 테이블 (Master Document Table)

| 번호 | 새 파일명 (링크) | 작성일시 (KST) | 문서 제목 / 핵심 주제 |
|:---:|:---|:---:|:---|
"""


@dataclass
class DocEntry:
    path: Path
    filename: str
    number: Optional[int]
    prefix: str
    base_name: str
    title: str
    created_at_kst: datetime
    is_index: bool = False


def _serialized_doc_write(operation):
    @wraps(operation)
    def locked(project_root, *args, **kwargs):
        key = str(Path(project_root).resolve())
        owned = getattr(_DOC_LOCKS, "owned", set())
        if key in owned:
            return operation(project_root, *args, **kwargs)
        from .coord.stream import _exclusive
        lock = Path(project_root) / ".work" / "docs_manager.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        with _exclusive(lock):
            _DOC_LOCKS.owned = owned | {key}
            try:
                return operation(project_root, *args, **kwargs)
            finally:
                _DOC_LOCKS.owned = owned
    return locked


def ensure_docs_dir(project_root: Path) -> Path:
    """Ensure the docs/ directory exists under project_root."""
    docs_dir = Path(project_root) / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    return docs_dir


@_serialized_doc_write
def ensure_doc_index(project_root: Path) -> Path:
    """Ensure docs/00_DOCUMENT_INDEX.md exists with standard header and table."""
    docs_dir = ensure_docs_dir(project_root)
    index_path = docs_dir / INDEX_FILENAME
    if not index_path.is_file():
        now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        content = INDEX_HEADER_TEMPLATE.format(
            project_name=project_root.resolve().name,
            created_at_kst=now_kst
        )
        index_path.write_text(content, encoding="utf-8")
    return index_path


def parse_doc_filename(filename: str) -> tuple[Optional[int], str, str]:
    """Extract (number, prefix, base_name) from filename.
    
    Examples:
        '01_foo.md' -> (1, '01_', 'foo.md')
        '84_auto_init.md' -> (84, '84_', 'auto_init.md')
        'note.md' -> (None, '', 'note.md')
    """
    m = re.match(r"^(\d{2,})_(.*)$", filename)
    if m:
        num = int(m.group(1))
        prefix = f"{m.group(1)}_"
        base_name = m.group(2)
        return num, prefix, base_name
    return None, "", filename


def extract_doc_title(file_path: Path) -> str:
    """Extract the first H1 title from markdown or <title>/<h1> from HTML, or default to filename."""
    if not file_path.is_file():
        return file_path.name
    try:
        text = file_path.read_text(encoding="utf-8", errors="ignore")[:8192]
        if file_path.suffix.lower() in (".html", ".htm"):
            m = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
            if not m:
                m = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.IGNORECASE | re.DOTALL)
            if m:
                clean = re.sub(r"<[^>]+>", "", m.group(1)).strip()
                if clean:
                    return clean.replace("|", "/")
        for line in text.splitlines()[:30]:
            s = line.strip()
            if s.startswith("# "):
                return s[2:].strip().replace("|", "/")
    except Exception:
        pass
    _, _, base = parse_doc_filename(file_path.name)
    return re.sub(r"\.(md|html?)$", "", base, flags=re.IGNORECASE).replace("_", " ")


def scan_docs(project_root: Path) -> list[DocEntry]:
    """Scan docs/ directory and return list of DocEntry sorted chronologically and numerically."""
    docs_dir = ensure_docs_dir(project_root)
    entries: list[DocEntry] = []

    for entry in docs_dir.iterdir():
        if entry.is_dir():
            continue
        fname = entry.name
        is_idx = fname in (INDEX_FILENAME, "00_DOCUMENT_HUB.html")
        num, prefix, base = parse_doc_filename(fname)
        stat = entry.stat()
        mtime_kst = datetime.fromtimestamp(stat.st_mtime, tz=KST)
        m_date = re.search(r"(\d{4}-\d{2}-\d{2})", fname)
        if m_date:
            try:
                fn_dt = datetime.strptime(m_date.group(1), "%Y-%m-%d").replace(tzinfo=KST)
                if mtime_kst.strftime("%Y-%m-%d") != m_date.group(1):
                    mtime_kst = fn_dt
            except Exception:
                pass
        title = extract_doc_title(entry)
        entries.append(DocEntry(
            path=entry,
            filename=fname,
            number=num,
            prefix=prefix,
            base_name=base,
            title=title,
            created_at_kst=mtime_kst,
            is_index=is_idx
        ))

    def sort_key(e: DocEntry):
        if e.is_index:
            return (-1, datetime.min.replace(tzinfo=KST), e.filename)
        n = e.number if e.number is not None else 9999
        return (n, e.created_at_kst, e.filename)

    entries.sort(key=sort_key)
    return entries


def allocate_next_doc_number(project_root: Path, target_date: Optional[datetime] = None) -> tuple[int, str]:
    """Inspect preceding and succeeding documents and allocate the next sequential number.
    
    Returns (next_num, next_prefix), e.g. (84, '84_').
    """
    entries = scan_docs(project_root)
    valid_numbers = [e.number for e in entries if e.number is not None and not e.is_index]
    
    if not valid_numbers:
        return 1, "01_"
        
    max_num = max(valid_numbers)
    next_num = max_num + 1
    
    # 2-digit padding up to 99, 3-digit for 100+
    padding = 2 if next_num < 100 else 3
    prefix = f"{next_num:0{padding}d}_"
    return next_num, prefix


@_serialized_doc_write
def register_new_doc(
    project_root: Path,
    title: str,
    slug: Optional[str] = None,
    category: str = "",
    author_tool: str = "",
    content: str = "",
    target_date: Optional[datetime] = None,
    ext: str = "md",
    source_file: Optional[Path] = None,
) -> Path:
    """Create a new numbered document, write content, and register in 00_DOCUMENT_INDEX.md and 00_DOCUMENT_HUB.html."""
    docs_dir = ensure_docs_dir(project_root)
    ensure_doc_index(project_root)

    next_num, prefix = allocate_next_doc_number(project_root, target_date)
    clean_ext = ext.lstrip(".").lower() or "md"
    if clean_ext not in ("md", "html"):
        raise ValueError("ext must be md or html")

    if not slug:
        safe_slug = re.sub(r"[^\w\-\uac00-\ud7a3]", "_", title).strip("_")
        safe_slug = re.sub(r"_+", "_", safe_slug)
        if not safe_slug:
            safe_slug = "document"
    else:
        safe_slug = slug.strip().replace(" ", "_")
        if re.search(r'[<>:"/\\|?*\x00-\x1f]', safe_slug):
            raise ValueError("slug must be a single safe filename component")

    filename = f"{prefix}{safe_slug}.{clean_ext}"
    doc_path = docs_dir / filename

    now = target_date or datetime.now(KST)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    if source_file is not None:
        content = Path(source_file).read_text(encoding="utf-8")
    elif not content:
        content = f"""# {title}

- 작성일시: {now_str} (KST)
- 카테고리: {category or '일반'}
- 작성도구: {author_tool or 'UAOS-RSI'}

## 1. 개요

## 2. 주요 내용

## 3. 검증 및 결과
"""

    with doc_path.open("x", encoding="utf-8") as handle:
        handle.write(content)

    append_to_doc_index(project_root, next_num, filename, now_str[:16], title)
    sync_doc_index(project_root)
    return doc_path


@_serialized_doc_write
def append_to_doc_index(project_root: Path, doc_num: int, filename: str, date_str: str, title: str) -> None:
    """Append a new row to docs/00_DOCUMENT_INDEX.md."""
    index_path = ensure_doc_index(project_root)
    clean_title = title.replace("|", "/").strip()
    current_text = index_path.read_text(encoding="utf-8")
    
    if "| 기존 파일명 |" in current_text:
        row = f"| {doc_num:02d} | [{filename}]({filename}) | - | {date_str} | {clean_title} |\n"
    else:
        row = f"| {doc_num:02d} | [{filename}]({filename}) | {date_str} | {clean_title} |\n"
    
    if filename not in current_text:
        # Check if table exists
        if "| 번호 | 새 파일명 (링크) |" in current_text:
            # Append before any trailing section (e.g. ## 3. 서브 디렉터리)
            sub_marker = "\n---\n\n## 3. 서브 디렉터리"
            if sub_marker in current_text:
                parts = current_text.split(sub_marker, 1)
                new_text = parts[0].rstrip() + "\n" + row + sub_marker + parts[1]
            else:
                new_text = current_text.rstrip() + "\n" + row
            index_path.write_text(new_text, encoding="utf-8")
        else:
            with index_path.open("a", encoding="utf-8") as f:
                f.write(row)


@_serialized_doc_write
def sync_doc_index(project_root: Path) -> int:
    """Audit docs/ directory and synchronize 00_DOCUMENT_INDEX.md and 00_DOCUMENT_HUB.html."""
    docs_dir = ensure_docs_dir(project_root)
    index_path = ensure_doc_index(project_root)
    entries = scan_docs(project_root)

    non_index = [e for e in entries if not e.is_index]
    non_index.sort(key=lambda x: (x.number if x.number is not None else 9999, x.created_at_kst))

    now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    header = INDEX_HEADER_TEMPLATE.format(
        project_name=project_root.resolve().name,
        created_at_kst=now_kst
    )

    rows = []
    html_rows = []
    for e in non_index:
        num_str = f"{e.number:02d}" if e.number is not None else "--"
        dt_str = e.created_at_kst.strftime("%Y-%m-%d %H:%M")
        rows.append(f"| {num_str} | [{e.filename}]({e.filename}) | {dt_str} | {e.title} |")
        html_rows.append(f"<tr><td>{num_str}</td><td><a href='{e.filename}'>{e.filename}</a></td><td>{dt_str}</td><td>{e.title}</td></tr>")

    full_content = header + "\n".join(rows) + "\n"
    index_path.write_text(full_content, encoding="utf-8")
    hub_path = docs_dir / "00_DOCUMENT_HUB.html"
    hub_html = (
        f"<!DOCTYPE html><html lang='ko'><head><meta charset='utf-8'><title>UAOS Document Hub - {project_root.resolve().name}</title></head>"
        f"<body><h1>UAOS-RSI Unified Document Hub ({len(rows)})</h1><table>"
        + "".join(html_rows)
        + "</table></body></html>\n"
    )
    hub_path.write_text(hub_html, encoding="utf-8")
    return len(rows)
