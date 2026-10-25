# U241C-L1 Contract Manual — Ultra-Minimal `<details>` Zero-Scroll/Zero-JS `render_control_ux_html`

```contract
work_id: U241C-L1
worker: local
goal: Replace render_control_ux_html in v7_harness/control_ux.py with an ultra-minimal zero-JS <details> accordion HTML layout
inputs:
  - v7_harness/control_ux.py sha256=d2f5f505e66e7128e84bf2675829a917c439a90c187789a26bcee417001f1d3c
  - tests/test_u241_control_ux.py sha256=51422341b054c79587d867317167635b9bf71c948d6e973da287a12d516862fb
allow:
  - v7_harness/control_ux.py
context_allow:
  - tests/test_u241_control_ux.py
acceptance: C:\Python314\python.exe -m unittest tests.test_u241_control_ux.U241ControlUxTests.test_render_control_ux_html_renders_canonical_owner_tool_and_minimal_details_accordion
forbidden: editing or deleting tests; edits outside allow; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 300 seconds
judge: claude
timeout_s: 300
remote_budget_tokens: 0
```

## Task Specification (Replace `def render_control_ux_html`)

Replace `def render_control_ux_html(snapshot: dict, output_path: Path | str | None = None) -> str:` in `v7_harness/control_ux.py` with:

```python
def render_control_ux_html(snapshot: dict, output_path: Path | str | None = None) -> str:
    tools = snapshot.get("tools") or {}
    boxes = "".join(
        f"<div class='box'><b>{html.escape(t.upper())}</b>{html.escape(str((tools.get(t) or {}).get('state') or 'UNKNOWN'))}</div>"
        for t in TOOLS
    )
    rows = "".join(
        f"<tr><td>{html.escape(str(p.get('phase_id', '')))}</td>"
        f"<td>{html.escape(str(p.get('title', '')))}</td>"
        f"<td>{html.escape(str(p.get('owner_tool') or p.get('owner') or ''))}</td>"
        f"<td>{html.escape(str(p.get('state', '')))}</td></tr>"
        for p in snapshot.get("phases", [])
    )
    bgs = "".join(
        f"<li>{html.escape(str(b.get('kind', '')))}: {html.escape(str(b.get('target', '')))} ({html.escape(str(b.get('id', '')))})</li>"
        for b in snapshot.get("background_tasks", [])
    )
    doc = (
        f"<!DOCTYPE html><html lang='ko'><head><meta charset='UTF-8'><title>{SCHEMA}</title>"
        "<style>body{margin:0;padding:10px 12px;background:#0b1020;color:#e2e8f0;font:12px/1.4 sans-serif}"
        ".banner{border-left:4px solid #38bdf8;padding-left:8px;margin-bottom:8px;font-weight:700}"
        ".row{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:8px}"
        ".box{background:#131c31;border:1px solid #263554;border-radius:6px;padding:6px 8px}.box b{color:#38bdf8;display:block}"
        "details{background:#131c31;border:1px solid #263554;border-radius:6px;padding:5px 8px}summary{cursor:pointer;font-weight:600;color:#bae6fd}"
        "table{width:100%;border-collapse:collapse;margin-top:6px}th,td{border:1px solid #334155;padding:4px 6px;text-align:left}</style></head>"
        f"<body><div class='banner'><strong>ANTIGRAVITY = 사용자와의 메인 대화창구 ({SCHEMA})</strong></div>"
        f"<div class='row'>{boxes}</div>"
        "<details><summary>Master Schedule &amp; Background Tasks (Click to expand)</summary>"
        f"<table><thead><tr><th>ID</th><th>Title</th><th>Owner</th><th>State</th></tr></thead><tbody>{rows}</tbody></table>"
        f"<ul>{bgs}</ul></details></body></html>"
    )
    if output_path is not None:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(doc, encoding="utf-8")
    return doc
```
