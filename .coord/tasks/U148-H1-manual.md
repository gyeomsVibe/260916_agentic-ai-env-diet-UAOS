```contract
work_id: U148-H1
worker: apply
apply_after: U148-H1R2
goal: U148 Antigravity's desk conversation hears its headless answers in its own hook line, written by Ollama from a spec
inputs:
- v7_harness/coord/hook_context.py sha256=SHA_HOOK
- v7_harness/coord/agy_dispatch.py sha256=SHA_AGY2
allow:
- v7_harness/coord/hook_context.py
acceptance: python -c "import os,json,time,tempfile,pathlib;from v7_harness.coord import hook_context as h,deliver as d;p=pathlib.Path(tempfile.mkdtemp());a=pathlib.Path(tempfile.mkdtemp());os.environ[d.AGY_APP_HOME_ENV]=str(a);(a/'conversations').mkdir();(a/'conversations'/'2c573cc3-3c50-40a7-a060-738cadce9bc5.db').write_bytes(b'');(a/'brain'/'0199cccc-0000-4000-8000-000000000003').mkdir(parents=True);(p/'.coord').mkdir();u='2c573cc3-3c50-40a7-a060-738cadce9bc5';v='0199cccc-0000-4000-8000-000000000003';f=d.user_desk_path(p,'antigravity');f.parent.mkdir(parents=True);f.write_text(json.dumps({'thread':u}),encoding='utf-8');l=p/'.coord'/'mailbox'/'delivery'/'agy_auto.jsonl';l.parent.mkdir(parents=True);n=time.time();l.write_text(''.join(json.dumps({'ts':n,'message_id':m,'state':'ANSWERED'})+chr(10) for m in ['relay_a','relay_b']),encoding='utf-8');s=h.agy_line(p,{},json.dumps({'conversationId':u,'invocationNum':0}));assert '2 headless answer(s) today' in s and 'relay_b' in s,s;(p/h.AGY_SEEN).unlink();o=h.agy_line(p,{},json.dumps({'conversationId':v,'invocationNum':0}));assert o and 'headless answer' not in o and '--desk-thread' not in o,o;f.write_text('{',encoding='utf-8');(p/h.AGY_SEEN).unlink();g=h.agy_line(p,{},json.dumps({'conversationId':v,'invocationNum':0}));assert '--desk-thread '+v in g and 'Only if' in g,g"
forbidden: edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 900
```

Card U148 (Antigravity's desktop conversation learns what its headless runs answered). Dictation: copy the four
edit blocks below exactly, in this order, and change nothing else. Do not rewrite the file: attempt U148-H1
re-emitted the whole file, ran out at 4096 output tokens and wrote nothing; attempt U148-H1R2 echoed the contract
and turned these blocks into bare fenced blocks (DICTATION_MISMATCH:hook_context.py:0). Caps were inspected and
left unchanged (input 16133, output 2552 of 4096), so this run applies the blocks exactly.

===EDIT: v7_harness/coord/hook_context.py===
<<<<<<< SEARCH
import threading
from pathlib import Path
=======
import threading
import time
from pathlib import Path
>>>>>>> REPLACE

===EDIT: v7_harness/coord/hook_context.py===
<<<<<<< SEARCH
    conversation = str(event.get("conversationId") or "")
=======
    conversation = str(event.get("conversationId") or "")
    # U148: only the user's Antigravity desk hears what its headless runs answered (agy_dispatch, U120)
    answers = ""
    from .agy_dispatch import answered_today
    from .deliver import read_user_desk

    if conversation and conversation == read_user_desk(project, "antigravity"):
        done = answered_today(project, time.time())
        if done:
            answers = (f"Your headless runs sent {len(done)} headless answer(s) today, newest re {done[0]} "
                       "(.coord/mailbox/delivery/agy_auto.jsonl). This hook text reaches only you, never the user "
                       "(Antigravity review relay_39c3f5be), so begin your next visible reply with one line naming "
                       "these answers. ")
    # U148 REPLAN (Codex codex_u148_c1_human_origin_gate_unmet): the hook never registers a desk, so a desktop
    # conversation with no valid desk learns the explicit registration, to be used only on the user's own turn.
    from .deliver import agy_desktop_conversation, user_desk_state

    if conversation and user_desk_state(project, "antigravity")[0] != "OK" and agy_desktop_conversation(conversation):
        runtime = Path.home() / ".uaos" / "uaos.py"
        answers += (f"No valid Antigravity user desk is registered for this project. Only if 윤겸스 is the one "
                    f"typing to you in this conversation, register it once with: python \"{runtime}\" coord presence "
                    f"--tool antigravity --desk-thread {conversation} --project \"{project}\" ")
>>>>>>> REPLACE

===EDIT: v7_harness/coord/hook_context.py===
<<<<<<< SEARCH
    fingerprint = hashlib.sha256("\n".join([conversation, desk, mode, *letters]).encode("utf-8")).hexdigest()
=======
    fingerprint = hashlib.sha256("\n".join([conversation, desk, mode, answers, *letters]).encode("utf-8")).hexdigest()
>>>>>>> REPLACE

===EDIT: v7_harness/coord/hook_context.py===
<<<<<<< SEARCH
            f"own work. {mode} ")
=======
            f"own work. {mode} {answers}")
>>>>>>> REPLACE
