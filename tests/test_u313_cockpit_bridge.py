import hashlib, json, tempfile, unittest
from pathlib import Path
from v7_harness.coord.native_meter import MeterStore
from v7_harness.coord.cockpit_meter import ingest_cache

class BridgeEvidence(unittest.TestCase):
    def test_fresh_pair_and_stale_or_ambiguous_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); account=hashlib.sha256(b'a@example.invalid').hexdigest()
            path=root/'cache/quota_api_v1_plugin/authorized'/f'{account}.json'; path.parent.mkdir(parents=True)
            store=MeterStore(root/'meter.db')
            data={'version':1,'source':'authorized','email':'a@example.invalid','updatedAt':1000000,
                  'payload':{'groups':[{'buckets':[{'bucketId':key,'remainingFraction':.1,'resetTime':2000}
                                                  for key in ('gemini-5h','gemini-weekly')]}]}}
            path.write_text(json.dumps(data)); result=ingest_cache(path,store,now=1001,max_age_s=10)
            self.assertEqual(2,result['inserted']); self.assertEqual(1000,result['source_observed_at'])
            with self.assertRaisesRegex(ValueError,'STALE_OR_FUTURE_SOURCE'):
                ingest_cache(path,store,now=1100,max_age_s=10)
            data['payload']={'models':{'x':{'quotaInfo':{'remainingFraction':1,'resetTime':2000}}}}
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'EXPLICIT_WINDOW_BINDING_REQUIRED'):
                ingest_cache(path,store,now=1001,max_age_s=10)
            self.assertEqual(2,len(store.observations()))
            data['email']='other@example.invalid'; path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'CACHE_ACCOUNT_BINDING_MISMATCH'):
                ingest_cache(path,store,now=1001,max_age_s=10)

if __name__=='__main__': unittest.main()
