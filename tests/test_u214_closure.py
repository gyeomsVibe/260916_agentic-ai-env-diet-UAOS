"""Maintain the four original U214 frozen closure regressions.

Reuse only the existing fixture helpers so this module discovers exactly four tests.
Assertions and queued helper are copied unchanged from the independent frozen gate.
"""
import json
import os
import time
import unittest

from tests import test_u214_dispatched_wait as module


class ClosureGate(unittest.TestCase):
    setUp = module.DispatchedWait.setUp
    _watermark = module.DispatchedWait._watermark
    _letter = module.DispatchedWait._letter
    _receipt = module.DispatchedWait._receipt
    _schedule = module.DispatchedWait._schedule
    _items = module.DispatchedWait._items

    def queued(self):
        path=self.mailbox/'delivery/queued/codex/relay_a.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'actor':'claude','message':'VERDICT_REQUESTED=YES'}),encoding='utf-8')
        old=time.time()-2*module.HOUR
        os.utime(path,(old,old))

    def test_answered_dispatched_request_with_stale_queue_copy_stays_closed(self):
        self._letter('relay_a')
        self.queued()
        self._letter('relay_reply',target='claude',actor='codex',requested=False,in_reply_to='relay_a')
        self.assertEqual([],self._items())

    def test_ack_with_leftover_queue_and_inbox_copy_stays_closed(self):
        self._letter('relay_a')
        self._letter('relay_a',folder='ack')
        self.queued()
        self.assertEqual([],self._items())

    def test_terminal_card_with_stale_queue_copy_stays_closed(self):
        self._letter('relay_a',card='U9')
        self.queued()
        self._schedule([{'phase_id':'U9','state':'DONE'}])
        self.assertEqual([],self._items())

    def test_failed_delivery_receipt_is_not_proof_of_dispatch(self):
        self._letter('relay_a')
        path=self.mailbox/'delivery/accepted/relay_a.json'
        data=json.loads(path.read_text())
        data['state']='FAILED'
        path.write_text(json.dumps(data))
        self.assertEqual([],self._items())

