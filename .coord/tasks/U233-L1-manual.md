# U233-L1: Unified Document Hub (`docs_manager.py` HTML title, `00_DOCUMENT_HUB.html`, `--ext`/`--from-file`)

```contract
work_id: U233-L1
worker: local
goal: docs_manager extracts HTML titles, supports ext and source_file in register_new_doc, and writes 00_DOCUMENT_HUB.html in sync_doc_index
inputs:
- v7_harness/docs_manager.py sha256=e66e4d4d0bbabe4687824d97b06e209fb2f6a5d15f716d73348eb1c7eae4df5a
- tests/test_u233_unified_doc_hub.py sha256=e79b05ccfb2f6ef29077ac15ae0dc55e2b3f34ee3891e92a95a5e00ad8abf7a7
allow:
- v7_harness/docs_manager.py
context_allow:
- tests/test_u233_unified_doc_hub.py
acceptance: python -m unittest tests.test_docs_manager tests.test_u222_docs_concurrency
forbidden: editing or deleting tests; edits outside allow; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 900 seconds
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Exact edits: four whole top-level functions in `v7_harness/docs_manager.py`

1. Replace `extract_doc_title`:
```python
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
```

2. Replace `scan_docs`:
```python
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
```

3. Replace `register_new_doc`:
```python
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
```

4. Replace `sync_doc_index`:
```python
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
```

## Output

- Reply with one ===EDIT: v7_harness/docs_manager.py=== block holding the four whole top-level functions above in a ```python fence, copied character for character. No explanations. Do not claim success; the acceptance command decides.
