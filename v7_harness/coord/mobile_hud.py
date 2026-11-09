"""U306: Mobile HUD Widget Status Exporter and Lightweight Server.

Generates clean, standardized JSON for mobile widgets (iOS Scriptable, Android KWGT, PWA)
and serves a responsive, real-time Mobile Web Cockpit at http://localhost:8765/.
Zero external dependencies, zero paid tokens.
"""

from __future__ import annotations

import datetime
import http.server
import json
import socketserver
import sys
import threading
import time
from pathlib import Path
from typing import Any

from v7_harness.coord.capacity_planner import collect_capacity_snapshot


def _fuel_color(pct: float | None) -> str:
    """Return hex color matching the HUD cockpit fuel theme."""
    if pct is None:
        return "#888888"
    if pct > 60:
        return "#10b981"  # green
    if pct > 25:
        return "#f59e0b"  # amber
    return "#ef4444"      # red


def _progress_bar(pct: float | None, length: int = 8) -> str:
    """Return Unicode progress bar for iOS Scriptable / text widgets."""
    if pct is None:
        return "░" * length
    filled = max(0, min(length, int(round((pct / 100.0) * length))))
    return "█" * filled + "░" * (length - filled)


def build_mobile_status(project: Path) -> dict[str, Any]:
    """Extract clean, deterministic status payload optimized for mobile widgets."""
    project = Path(project).resolve()
    snap = collect_capacity_snapshot(project, persist=False)
    engines = snap.get("engines", {})

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    tools_out: dict[str, Any] = {}

    for tool_name in ("codex", "claude", "antigravity", "haiku", "ollama"):
        eng = engines.get(tool_name, {})
        sub = eng.get("subscription_plan", {})
        pres = str(eng.get("presence_state") or "ACTIVE")
        tier = str(eng.get("status_tier") or "UNKNOWN")

        # Quotas and fuel
        rem_5h = sub.get("quota_5h_ui_pct")
        rem_7d = sub.get("quota_7d_ui_pct")

        rem_pct: float | None = None
        if rem_5h is not None:
            rem_pct = float(rem_5h)
        elif rem_7d is not None:
            rem_pct = float(rem_7d)

        helper_info = sub.get("helper_quota")
        helper_pct = (
            float(helper_info.get("remaining_pct"))
            if helper_info and helper_info.get("remaining_pct") is not None
            else None
        )

        tools_out[tool_name] = {
            "name": tool_name.capitalize(),
            "presence": pres,
            "tier": tier,
            "short_plan": sub.get("short_plan") or tool_name,
            "remaining_pct": rem_pct,
            "helper_remaining_pct": helper_pct,
            "fuel_color": _fuel_color(rem_pct),
            "progress_bar": _progress_bar(rem_pct),
            "resets_at_5h": sub.get("resets_at_5h"),
            "resets_at_7d": sub.get("resets_at_7d"),
            "usable_tokens": eng.get("usable_remaining_5h_tokens") or sub.get("remaining_5h_tokens"),
        }

    active_phase_id = "IDLE"
    active_phase_title = "대기 중"
    sched_file = project / ".coord" / "master_schedule.json"
    if sched_file.is_file():
        try:
            sched_data = json.loads(sched_file.read_text(encoding="utf-8"))
            active_phase_id = str(sched_data.get("current_phase_id") or "IDLE")
            for ph in sched_data.get("phases", []):
                if ph.get("phase_id") == active_phase_id:
                    active_phase_title = str(ph.get("title") or active_phase_id)
                    break
        except (OSError, ValueError):
            pass

    return {
        "ok": True,
        "updated_at": now_iso,
        "tools": tools_out,
        "active_phase": {
            "id": active_phase_id,
            "title": active_phase_title,
        },
    }


def export_mobile_status(project: Path, out_path: Path | None = None) -> Path:
    """Save mobile status JSON atomically."""
    project = Path(project).resolve()
    if out_path is None:
        out_path = project / ".work" / "hud_live" / "mobile_status.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    data = build_mobile_status(project)
    tmp_path = out_path.with_suffix(".tmp_json")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(out_path)
    return out_path


def render_mobile_html(status_data: dict[str, Any]) -> str:
    initial_json = json.dumps(status_data, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#0b0f19">
<title>UAOS Mobile HUD</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
body {{ background: #0b0f19; color: #f1f5f9; padding: 16px; display: flex; flex-direction: column; gap: 14px; min-height: 100vh; }}
.header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #1e293b; padding-bottom: 10px; }}
.header h1 {{ font-size: 1.15rem; font-weight: 700; color: #38bdf8; letter-spacing: -0.5px; }}
.badge {{ font-size: 0.72rem; padding: 3px 8px; border-radius: 9999px; background: #064e3b; color: #34d399; font-weight: 600; }}
.phase-card {{ background: #131b2e; border: 1px solid #1e293b; border-radius: 12px; padding: 12px 14px; }}
.phase-title {{ font-size: 0.8rem; color: #94a3b8; margin-bottom: 4px; }}
.phase-name {{ font-size: 0.95rem; font-weight: 600; color: #e2e8f0; }}
.tools-grid {{ display: flex; flex-direction: column; gap: 10px; }}
.tool-card {{ background: #131b2e; border: 1px solid #1e293b; border-radius: 12px; padding: 12px 14px; display: flex; flex-direction: column; gap: 6px; }}
.tool-header {{ display: flex; justify-content: space-between; align-items: center; }}
.tool-name {{ font-size: 0.92rem; font-weight: 700; color: #f8fafc; }}
.tool-val {{ font-size: 0.92rem; font-weight: 700; }}
.fuel-track {{ width: 100%; height: 7px; background: #1e293b; border-radius: 4px; overflow: hidden; }}
.fuel-fill {{ height: 100%; border-radius: 4px; transition: width 0.3s ease; }}
.tool-meta {{ display: flex; justify-content: space-between; font-size: 0.72rem; color: #64748b; }}
.footer {{ text-align: center; font-size: 0.7rem; color: #475569; margin-top: auto; padding-top: 10px; }}
.guide-box {{ background: #1e293b; border-radius: 10px; padding: 12px 14px; font-size: 0.78rem; color: #cbd5e1; line-height: 1.5; }}
.guide-box b {{ color: #38bdf8; }}
</style>
</head>
<body>
<div class="header">
  <h1>⚡ UAOS COCKPIT</h1>
  <span class="badge" id="status-badge">실시간 연동됨</span>
</div>

<div class="phase-card">
  <div class="phase-title">📌 활성 작업 (Active Phase)</div>
  <div class="phase-name" id="phase-name">로딩 중...</div>
</div>

<div class="tools-grid" id="tools-container"></div>

<div class="guide-box">
  📱 <b>바탕화면 위젯 설치 방법</b><br>
  하단 우측 점 3개(<b>︙</b>) ➔ <b>'현재 페이지 추가'</b> ➔ <b>'홈 화면'</b>을 누르면 스마트폰 바탕화면에 즉시 위젯 아이콘이 생성됩니다.
</div>

<div class="footer" id="last-updated">실시간 동기화 중...</div>

<script>
let lastData = {initial_json};

function renderData(data) {{
  if (!data || !data.ok) return;
  document.getElementById('phase-name').innerText = data.active_phase.id + ': ' + data.active_phase.title;

  const container = document.getElementById('tools-container');
  container.innerHTML = '';

  const order = ['codex', 'claude', 'antigravity', 'haiku', 'ollama'];
  for (const k of order) {{
    const t = data.tools[k];
    if (!t) continue;

    const card = document.createElement('div');
    card.className = 'tool-card';

    const pct = t.remaining_pct;
    const displayVal = pct != null ? Math.round(pct) + '%' : (t.presence === 'LIMITED' ? '0% (소진)' : '정상');
    const barWidth = pct != null ? Math.max(0, Math.min(100, pct)) : (t.presence === 'LIMITED' ? 0 : 100);

    card.innerHTML = `
      <div class="tool-header">
        <span class="tool-name">${{t.name}} <span style="font-weight:400;font-size:0.75rem;color:#64748b">(${{t.short_plan}})</span></span>
        <span class="tool-val" style="color:${{t.fuel_color}}">${{displayVal}}</span>
      </div>
      <div class="fuel-track">
        <div class="fuel-fill" style="width:${{barWidth}}%; background:${{t.fuel_color}}"></div>
      </div>
      <div class="tool-meta">
        <span>상태: ${{t.presence}} · ${{t.tier}}</span>
        <span>${{t.usable_tokens ? Number(t.usable_tokens).toLocaleString() + ' tok' : (t.helper_remaining_pct ? '보조 ' + Math.round(t.helper_remaining_pct) + '%' : '')}}</span>
      </div>
    `;
    container.appendChild(card);
  }}

  const d = new Date(data.updated_at);
  document.getElementById('last-updated').innerText = '실시간 동기화됨: ' + d.toLocaleTimeString('ko-KR');
}}

renderData(lastData);

async function refreshHUD() {{
  try {{
    const res = await fetch('/api/status.json?t=' + Date.now());
    const data = await res.json();
    if (data && data.ok) {{
      renderData(data);
      document.getElementById('status-badge').innerText = '실시간 연동됨';
      document.getElementById('status-badge').style.background = '#064e3b';
      document.getElementById('status-badge').style.color = '#34d399';
    }}
  }} catch (err) {{
    // keep rendering lastData
  }}
}}
setInterval(refreshHUD, 2000);
</script>
</body>
</html>
"""


import threading

# --- Cached status layer: background thread refreshes, HTTP serves instantly ---
_cached_status: dict[str, Any] = {}
_cached_html: bytes = b""
_cached_json: bytes = b""
_cache_lock = threading.Lock()


def _refresh_cache(project: Path) -> None:
    """Rebuild cached status data. Called from background thread."""
    global _cached_status, _cached_html, _cached_json
    try:
        data = build_mobile_status(project)
        html = render_mobile_html(data).encode("utf-8")
        jdata = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        with _cache_lock:
            _cached_status = data
            _cached_html = html
            _cached_json = jdata
    except Exception:
        pass  # keep serving stale data on error


def _cache_refresh_loop(project: Path, interval: float = 15.0) -> None:
    """Background loop that refreshes cache every `interval` seconds."""
    while True:
        _refresh_cache(project)
        time.sleep(interval)


_ALLOWED_LOCAL_ORIGINS = frozenset({
    "http://127.0.0.1:8765",
    "http://localhost:8765",
    "http://127.0.0.1",
    "http://localhost",
})


class MobileStatusHandler(http.server.BaseHTTPRequestHandler):
    project_dir: Path = Path(".")

    def _cors_origin(self) -> str:
        req_origin = (self.headers.get("Origin") or "").strip()
        if req_origin in _ALLOWED_LOCAL_ORIGINS:
            return req_origin
        return "http://127.0.0.1:8765"

    def do_GET(self) -> None:
        try:
            path = self.path.split("?")[0]  # strip query params
            if path in ("/status.json", "/api/status.json", "/api/hud.json"):
                with _cache_lock:
                    body = _cached_json
                if not body:
                    body = b'{"ok": false, "error": "cache warming up"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", self._cors_origin())
                self.send_header("Vary", "Origin")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path in ("/", "/index.html", "/mobile.html"):
                with _cache_lock:
                    body = _cached_html
                if not body:
                    body = b"<html><body>Cache warming up...</body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            pass

    def log_message(self, format: str, *args: Any) -> None:
        pass


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve_mobile_api(project: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    project = Path(project).resolve()
    export_mobile_status(project)

    # Warm cache before starting server
    _refresh_cache(project)

    # Start background refresh thread (15s interval)
    t = threading.Thread(target=_cache_refresh_loop, args=(project,), daemon=True)
    t.start()

    class CustomHandler(MobileStatusHandler):
        project_dir = project

    with ThreadedTCPServer((host, port), CustomHandler) as httpd:
        print(f"Mobile HUD Web & API listening on http://{host}:{port}/")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    serve_mobile_api(Path("."))
