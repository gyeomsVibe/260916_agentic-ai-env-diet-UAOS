```contract
work_id: U148-D1
worker: local
goal: U148 Antigravity user desk registry in deliver.py, written by Ollama from an exact spec
inputs:
- v7_harness/coord/deliver.py sha256=SHA_DELIVER
allow:
- v7_harness/coord/deliver.py
acceptance: python -c "import os,tempfile,pathlib;from v7_harness.coord import deliver as d;h=pathlib.Path(tempfile.mkdtemp());os.environ[d.AGY_APP_HOME_ENV]=str(h);u='2c573cc3-3c50-40a7-a060-738cadce9bc5';v='0199cccc-0000-4000-8000-000000000003';(h/'conversations').mkdir();(h/'conversations'/(u+'.db')).write_bytes(b'');(h/'brain'/v).mkdir(parents=True);assert d.agy_desktop_conversation(u) and d.agy_desktop_conversation(v);assert not any(d.agy_desktop_conversation(x) for x in ['', 'abc', '../'+u, None, 7, '0199cccc-0000-4000-8000-000000000009']);assert 'antigravity' in d.USER_DESK_TOOLS;p=pathlib.Path(tempfile.mkdtemp());assert d.register_user_desk(p,'antigravity',u,source='t');assert d.user_desk_state(p,'antigravity')==('OK',u);assert d.REPLACE_TRIES>=10"
forbidden: edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 900
```

Card U148 (Antigravity gets a user desk). Three edits in v7_harness/coord/deliver.py. Change nothing else. os, time,
Path and UUID_RE already exist in the file.

1. Change the line USER_DESK_TOOLS = ("codex", "claude") to USER_DESK_TOOLS = ("codex", "claude", "antigravity")
   and add above it the comment line:
   # U148: Antigravity's desk is registered by its PreInvocation hook from a desktop-app conversation (cli.py).

2. Directly after the function `user_desk_path` (anchors: `USER_DESK_TOOLS` `register_user_desk`), add:

AGY_APP_HOME_ENV = "UAOS_AGY_APP_HOME"  # tests point this at a fixture; default ~/.gemini/antigravity


def agy_desktop_conversation(conversation: object) -> bool:
    docstring: """U148: True when `conversation` is a desktop-app conversation. The app keeps conversations/<id>.db and
    brain/<id>/ under ~/.gemini/antigravity; the headless CLI keeps its own under ~/.gemini/antigravity-cli, so a
    CLI-only id is False (checked 2026-10-04: 2c573cc3 app, ae1af179 CLI)."""
    - return False unless isinstance(conversation, str) and UUID_RE.fullmatch(conversation);
    - home = Path(os.environ.get(AGY_APP_HOME_ENV) or (Path.home() / ".gemini" / "antigravity"));
    - return (home / "conversations" / f"{conversation}.db").is_file() or (home / "brain" / conversation).is_dir()

3. In `register_user_desk`, replace the single line os.replace(temp, path) and the return True after it with a
   retry loop, and add above the function this constant with its comment:
   REPLACE_TRIES = 20  # Windows refuses os.replace while another process replaces the same file; 20 x 50 ms = 1 s
   The loop:
    for _attempt in range(REPLACE_TRIES):
        try:
            os.replace(temp, path)
            return True
        except PermissionError:
            time.sleep(0.05)
    temp.unlink(missing_ok=True)
    return False
