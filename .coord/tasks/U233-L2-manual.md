# U233-L2: Single-function slice on `extract_doc_title` in `v7_harness/docs_manager.py`

```contract
work_id: U233-L2
worker: local
goal: Extract HTML title in extract_doc_title in v7_harness/docs_manager.py
inputs:
- v7_harness/docs_manager.py sha256=e66e4d4d0bbabe4687824d97b06e209fb2f6a5d15f716d73348eb1c7eae4df5a
- tests/test_u233_unified_doc_hub.py sha256=e79b05ccfb2f6ef29077ac15ae0dc55e2b3f34ee3891e92a95a5e00ad8abf7a7
allow:
- v7_harness/docs_manager.py
context_allow:
- tests/test_u233_unified_doc_hub.py
acceptance: C:\Python314\python.exe -m unittest tests.test_u233_unified_doc_hub tests.test_docs_manager tests.test_u113_docs_manager tests.test_u222_docs_concurrency tests.test_docs_manager_concurrency
forbidden: editing or deleting tests; edits outside allow; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 300 seconds
judge: claude
timeout_s: 300
remote_budget_tokens: 0
```

## Exact edit in `v7_harness/docs_manager.py`

Replace `extract_doc_title`:
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
