"""Destination identity regression tests; processes synchronize before delivering."""
import hashlib
import json
import multiprocessing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from v7_harness.coord.deliver import deliver, _project_mailbox, dispatch_queued, _digest
from v7_harness.coord import presence

MESSAGE = "ACK_ONLY MSGID fixed reproduction"

def _send(root, target, start, results):
    try:
        start.wait(20)
        result = deliver(Path(root), actor="codex", message=MESSAGE, target=target)
        results.put((target, result.message_id, result.digest, ""))
    except Exception as exc:
        results.put((target, "", "", repr(exc)))

class MessageIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".coord" / "PLAN.md").parent.mkdir()
        (self.root / ".coord" / "PLAN.md").write_text("# fixed test")
        presence.mark(self.root, "claude", "LIMITED")
        presence.mark(self.root, "codex", "ABSENT")

    def test_destination_idempotency_and_ack_isolation(self):
        first = deliver(self.root, actor="codex", message=MESSAGE, target="antigravity")
        again = deliver(self.root, actor="codex", message=MESSAGE, target="antigravity")
        self.assertEqual(first.message_id, again.message_id)
        box = _project_mailbox(self.root)
        claim = box.claim(first.message_id, "fixed-test")
        self.assertIsNotNone(claim)
        box.ack(claim)
        second = deliver(self.root, actor="codex", message=MESSAGE, target="claude")
        self.assertNotEqual(first.message_id, second.message_id)
        self.assertNotEqual(second.reason, "ACKED")
        auto = deliver(self.root, actor="codex", message=MESSAGE)
        self.assertNotEqual(auto.message_id, second.message_id)
        for result in (second, auto):
            payload = json.loads((box.inbox_dir / (result.message_id + ".json")).read_text())["payload"]
            self.assertEqual(payload["digest"], result.digest)
            self.assertEqual(result.message_id, "relay_" + result.digest[:32])

    def test_parallel_destinations_preserve_both_letters(self):
        ctx = multiprocessing.get_context("spawn")
        start, results = ctx.Barrier(2), ctx.Queue()
        children = [ctx.Process(target=_send, args=(str(self.root), target, start, results))
                    for target in ("antigravity", "claude")]
        for child in children:
            child.start()
        rows = [results.get(timeout=40) for _ in children]
        for child in children:
            child.join(40)
            self.assertEqual(child.exitcode, 0)
        self.assertEqual([row[3] for row in rows], ["", ""])
        self.assertEqual(len({row[1] for row in rows}), 2)
        box = _project_mailbox(self.root)
        self.assertEqual(len(list(box.inbox_dir.glob("relay_*.json"))), 2)

    def test_queued_and_legacy_identity_survives_drain(self):
        root = self.root
        (root/'.coord'/'PLAN.md').write_text('# fixed')
        presence.mark(root,'claude','LIMITED')
        new = deliver(root,actor='codex',message='MSGID real drain',target='claude')
        box = _project_mailbox(root)
        legacy_message='MSGID legacy real drain'
        legacy_digest=hashlib.sha256(('codex\0'+legacy_message).encode()).hexdigest()
        legacy_id='relay_'+legacy_digest[:32]
        box.publish(legacy_id,dict(kind='HANDOFF',actor='codex',message=legacy_message,digest=legacy_digest,requested_target='claude'))
        folder=box.root/'delivery'/'queued'/'claude'
        (folder/(legacy_id+'.json')).write_text(json.dumps(dict(message_id=legacy_id,actor='codex',message=legacy_message,card='',thread='',attempts=0)))
        calls=[]
        def runner(argv,**kw):
            calls.append(str(argv))
            return SimpleNamespace(returncode=0,stdout=json.dumps(dict(type='result',result='accepted')),stderr='')
        presence.mark(root,'claude','ACTIVE')
        with patch('v7_harness.coord.deliver.shutil.which',return_value='claude'):
            rows=dispatch_queued(root,'claude',runner=runner)
        assert len(calls)==2,(rows,calls)
        for identity,digest in ((new.message_id,new.digest),(legacy_id,legacy_digest)):
            receipt=json.loads((box.root/'delivery'/'accepted'/(identity+'.json')).read_text())
            assert receipt['message_id']==identity and receipt['digest']==digest, receipt
            assert any(identity in call and digest in call for call in calls), calls

    def test_explicit_identity_has_unambiguous_framing(self):
        # A literal NUL in message bytes cannot impersonate destination framing.
        self.assertNotEqual(_digest("codex", "text\0claude"),
                            _digest("codex", "text", target="claude"))
        self.assertNotEqual(_digest("codex", "text\0card", target="claude"),
                            _digest("codex", "text", card="card", target="claude"))
        self.assertNotEqual(_digest("codex", "text\0a", card="b", target="claude"),
                            _digest("codex", "text", card="a\0b", target="claude"))
