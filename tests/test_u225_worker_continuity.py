"""Worker supplemental counterexamples; fixed judge acceptance remains unchanged."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from v7_harness.coord import continuity, watch
from v7_harness import global_install

class ContinuityCounterexamples(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / '.coord/presence').mkdir(parents=True)
        (self.root / '.coord/PLAN.md').write_text('# temp')
        self.payload = {'session_id':'desk', 'cwd':str(self.root), 'hook_event_name':'Stop'}
        (self.root / '.coord/presence/user_desk_claude.json').write_text(json.dumps({'thread':'desk','at':time.time()-5}))
        (self.root / '.coord/mailbox').mkdir()
        from v7_harness.coord.mailbox import Mailbox
        self.box = Mailbox(self.root / '.coord/mailbox')

    def letter(self, name='letter', **extra):
        body = {'actor':'codex','requested_target':'claude','wake_class':'ACTIONABLE','delta':'new artifact', **extra}
        (self.root / '.coord/mailbox/inbox' / (name+'.json')).write_text(json.dumps({'payload':body}))
        return body

    def listen(self):
        return continuity.run_hook(self.payload,'claude',timeout_s=.05,interval_s=.01)

    def test_session_start_bootstrap_never_enters_blocking_watcher(self):
        from unittest.mock import Mock
        watcher=Mock()
        result=continuity.run_hook({**self.payload,'hook_event_name':'SessionStart'},'claude',watch_fn=watcher)
        self.assertEqual(result,(0,None))
        watcher.assert_not_called()
        states=list((self.root/'.coord/presence/continuity').glob('*.json'))
        self.assertEqual(len(states),1)
        self.assertEqual(json.loads(states[0].read_text())['state'],'BOOTSTRAP_COMPLETE')

    def test_inert_claim_cannot_starve_native_and_native_deduplicates(self):
        body=self.letter()
        self.assertEqual(watch.claim_wake(self.root,'claude','letter',watch.letter_digest('letter',body)),'CLAIMED')
        self.assertEqual(self.listen()[0],2)
        self.assertEqual(self.listen()[0],0)

    def test_foreign_stale_ack_notice_do_not_consume_native_claim(self):
        self.letter('foreign',native_receiver='other')
        self.letter('ack',delta='ACK_ONLY')
        self.letter('notice',wake_class='NOTICE')
        self.letter('stale')
        path=self.root / '.coord/mailbox/inbox/stale.json'
        os.utime(path,(0,0))
        self.assertEqual(self.listen()[0],0)
        self.assertFalse((self.root/'.coord/presence/pending_wake/claude').exists())

    def test_desk_switch_while_waiting_stops_listener(self):
        def change(*args,**kwargs):
            (self.root/'.coord/presence/user_desk_claude.json').write_text(json.dumps({'thread':'other'}))
            return {'id':'late','wake_class':'ACTIONABLE','requested_target':'claude'}
        self.assertEqual(continuity.run_hook(self.payload,'claude',watch_fn=change)[0],0)

    def test_late_letter_after_scan_window_wakes_without_a_new_turn(self):
        import threading
        from unittest.mock import patch
        writer=threading.Thread(target=lambda: (time.sleep(.16), self.letter()))
        writer.start()
        try:
            with patch.object(continuity, 'SCAN_WINDOW_S', .04):
                result=continuity.run_hook(self.payload,'claude',timeout_s=1,interval_s=.01)
            self.assertEqual(result[0],2)
        finally:
            writer.join(timeout=2)

    def test_kernel_lifetime_lock_rejects_real_overlapping_process(self):
        script = '''import json,sys,time
from pathlib import Path
from v7_harness.coord.continuity import run_hook
p=json.loads(sys.argv[1])
marker=Path(sys.argv[2])
def wait(*a,**k):
    marker.write_text("ready")
    time.sleep(.6)
    return {"id":"one","wake_class":"ACTIONABLE","requested_target":"claude"}
print(run_hook(p,"claude",watch_fn=wait)[0])
'''
        marker=self.root/'ready'
        first=subprocess.Popen([sys.executable,'-c',script,json.dumps(self.payload),str(marker)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        deadline=time.monotonic()+5
        while not marker.exists() and first.poll() is None and time.monotonic()<deadline:
            time.sleep(.01)
        if not marker.exists():
            stdout, stderr = first.communicate(timeout=5)
            self.fail(f'child did not acquire lease: {first.returncode}, {stdout}, {stderr}')
        second=self.listen()
        self.assertEqual(second[0],0)
        stdout,stderr=first.communicate(timeout=5)
        self.assertEqual((first.returncode,stdout.strip(),stderr),(0,'2',''))

    def test_installer_idempotent_and_uninstall_preserves_unrelated(self):
        home=self.root/'home'
        (home/'.claude').mkdir(parents=True)
        path=home/'.claude/settings.json'
        path.write_text(json.dumps({'hooks':{'Stop':[{'hooks':[{'type':'command','command':'echo keep'}]}]}}))
        def planned(uninstall=False):
            return next(x for x in global_install.plan(home,'python',rules=False,enable_codex_hooks=False,uninstall=uninstall) if x.path==path)
        applied=planned(); path.write_text(applied.new_text)
        self.assertEqual(planned().action,'UNCHANGED')
        removed=json.loads(planned(True).new_text)
        commands=[h['command'] for groups in removed['hooks'].values() for group in groups for h in group['hooks']]
        self.assertEqual(commands,['echo keep'])

    def test_new_desk_waits_for_old_native_listener_to_retire(self):
        script = 'import json,sys; from v7_harness.coord.continuity import run_hook; print(run_hook(json.loads(sys.argv[1]),"claude",timeout_s=2,interval_s=.25)[0])'
        first=subprocess.Popen([sys.executable,'-c',script,json.dumps(self.payload)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        owner=self.root/'.coord/presence/continuity/claude.native.owner.json'
        deadline=time.monotonic()+5
        while not owner.exists() and first.poll() is None and time.monotonic()<deadline:
            time.sleep(.01)
        self.assertTrue(owner.exists())
        (self.root/'.coord/presence/user_desk_claude.json').write_text(json.dumps({'thread':'new-desk'}))
        self.letter(native_receiver='new-desk')
        payload={**self.payload,'session_id':'new-desk'}
        result=continuity.run_hook(payload,'claude',timeout_s=1,interval_s=.01)
        self.assertEqual(result[0],2)
        stdout,stderr=first.communicate(timeout=5)
        self.assertEqual((first.returncode,stdout.strip(),stderr),(0,'0',''))
