ACTIONABLE_DELTA verdict_requested=yes
WORK MANUAL U122-AR (Antigravity independent counterexample audit; author Claude, acting conductor)
goal: find defects in the merged U122 change below (sentinel single-instance check). You are the independent reviewer; Claude wrote it and may not judge it.
input: the unified diff below (v7_harness/cli.py, commit 251f556, merged as PR #94). Context: Windows reuses pids; the old check trusted any live pid in .work/sentinel/loop.pid; one sentinel tick measured 0.5-8 s; default --interval 60.
check: (1) can two sentinel loops now run at once for one project (race at start, slow tick > 180 s, interval < 60)? (2) can a stale file still block start? (3) any crash path (mtime on missing file, clock change, write failure mid-loop)?
allowed output: one JSON object only, no file links or paths: {"verdict":"PASS|FAIL","findings":[{"severity":"P1|P2|P3","scenario":"concrete inputs -> wrong result","fix":"one line"}]}. Max 1200 chars.
forbidden: editing, creating or deleting any file; running commands; network; secrets.
cost cap: one turn, 35,000 tokens. judge: Claude checks each finding against the code before acting.
DIFF:
@@ -1277,4 +1277,17 @@ def cmd_coord_publish_thread(args: argparse.Namespace) -> int:
 
 
+def _sentinel_loop_owner(pid_file: Path, interval: float) -> int:
+    """Pid of a live sentinel loop holding pid_file, else 0. U122: Windows reuses pids, so only a file the loop
+    rewrote within three cycles (floor 180 s; one tick took up to 8 s) counts; an older one is stale."""
+    from .coord.sentinel import _is_pid_alive
+    import time
+    try:
+        running = int(pid_file.read_text(encoding="utf-8").strip())
+        age = time.time() - pid_file.stat().st_mtime
+    except (OSError, ValueError):
+        return 0
+    return running if age < max(180.0, 3 * interval) and running != os.getpid() and _is_pid_alive(running) else 0
+
+
 def cmd_coord_sentinel(args: argparse.Namespace) -> int:
     """U23 S4 / U32b: 0-token sentinel (deterministic rules, no model call) — one cycle or a resident loop."""
@@ -1312,17 +1325,12 @@ def cmd_coord_sentinel(args: argparse.Namespace) -> int:
     if args.loop:
         # A logon task and a manual start must not run two operators on one project.
-        from .coord.sentinel import _is_pid_alive
-
         pid_file = project / ".work" / "sentinel" / "loop.pid"
-        try:
-            running = int(pid_file.read_text(encoding="utf-8").strip())
-        except (OSError, ValueError):
-            running = 0
-        if running and running != os.getpid() and _is_pid_alive(running):
+        running = _sentinel_loop_owner(pid_file, args.interval)
+        if running:
             _report({"ok": True, "skipped": "ALREADY_RUNNING", "pid": running})
             return 0
         pid_file.parent.mkdir(parents=True, exist_ok=True)
-        pid_file.write_text(str(os.getpid()), encoding="utf-8")
         while True:
+            pid_file.write_text(str(os.getpid()), encoding="utf-8")  # U122: each cycle refreshes the heartbeat
             # A resident operator must outlive one bad cycle (locked file, corrupt line); it reports and goes on.
             try:
