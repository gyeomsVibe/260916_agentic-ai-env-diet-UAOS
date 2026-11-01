"""Black-box runtime gates: shipped model selector and tamper refusal."""
import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

class HelperRuntimeAcceptance(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        repo=pathlib.Path(__file__).resolve().parents[1]
        files={'router.py':(repo/'scripts/helper_router.py').read_bytes(),
               'worker_routing.py':(repo/'v7_harness/worker_routing.py').read_bytes()}
        manifest={'source_commit':'fixture-reviewed-commit','files':{k:hashlib.sha256(v).hexdigest() for k,v in files.items()}}
        key=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
        self.root=pathlib.Path(self.tmp.name)/key
        self.root.mkdir()
        for name,data in files.items(): (self.root/name).write_bytes(data)
        (self.root/'MANIFEST.json').write_text(json.dumps(manifest),encoding='utf-8')
        self.request={'task':dict(caller='codex',kind='transform',input_tokens=100,output_tokens=40,changed_lines=0,local_qualified=False,local_failures=0,allow_remote=True,budget_tokens=1000,budget_usd=.02,timeout_s=60,remote_model='gpt-6-luna'),'availability':{'codex':True,'agy':False}}

    def run_query(self):
        return subprocess.run([sys.executable,'-I','-B',str(self.root/'router.py')],input=json.dumps(self.request),capture_output=True,text=True,timeout=10)

    def test_real_catalog_selects_luna_without_execution(self):
        result=self.run_query()
        self.assertEqual(result.returncode,0,result.stderr)
        plan=json.loads(result.stdout)
        self.assertEqual(plan['model'],'gpt-6-luna')
        self.assertFalse(plan['execution_authorized'])

    def test_unavailable_flash_is_blocked(self):
        self.request['task']['remote_model']='gemini-3.8-flash-low'
        result=self.run_query()
        self.assertEqual(result.returncode,1)
        self.assertEqual(json.loads(result.stdout)['status'],'BLOCKED')

    def test_invalid_requests_are_cleanly_blocked(self):
        for payload in ('{', '{}', '[]', 'null', '{"task": {}}', '['*20000+'0'+']'*20000):
            with self.subTest(payload_bytes=len(payload)):
                result=subprocess.run([sys.executable,'-I','-B',str(self.root/'router.py')],input=payload,capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,1)
                self.assertEqual(json.loads(result.stdout),{'status':'BLOCKED','reason':'HELPER_REQUEST_INVALID'})
                self.assertNotIn('Traceback',result.stderr)

    def test_legacy_short_bundle_identity_is_rejected(self):
        shortened=self.root.with_name(self.root.name[:12])
        self.root.rename(shortened)
        self.root=shortened
        result=self.run_query()
        self.assertNotEqual(result.returncode,0)
        self.assertIn('HELPER_MANIFEST_ID_MISMATCH',result.stderr)

    def test_tampered_module_is_rejected_before_execution(self):
        (self.root/'worker_routing.py').write_text("raise RuntimeError('MUST_NOT_EXECUTE')")
        result=self.run_query()
        self.assertNotEqual(result.returncode,0)
        self.assertIn('HELPER_BYTES_MISMATCH',result.stderr)
        self.assertNotIn('MUST_NOT_EXECUTE',result.stderr)

    def test_tampered_manifest_identity_is_rejected(self):
        manifest=json.loads((self.root/'MANIFEST.json').read_text())
        manifest['source_commit']='unreviewed'
        (self.root/'MANIFEST.json').write_text(json.dumps(manifest))
        result=self.run_query()
        self.assertNotEqual(result.returncode,0)
        self.assertIn('HELPER_MANIFEST_ID_MISMATCH',result.stderr)

    def test_extra_json_cannot_shadow_standard_library(self):
        (self.root/'json.py').write_text("raise RuntimeError('SHADOW_EXECUTED')")
        result=self.run_query()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn('SHADOW_EXECUTED',result.stderr)

    def test_nonisolated_invocation_refuses_before_shadow_import(self):
        (self.root/'json.py').write_text("raise RuntimeError('SHADOW_EXECUTED')")
        result=subprocess.run([sys.executable,'-B',str(self.root/'router.py')],input=json.dumps(self.request),capture_output=True,text=True,timeout=10)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('HELPER_ISOLATED_MODE_REQUIRED',result.stderr)
        self.assertNotIn('SHADOW_EXECUTED',result.stderr)

    def launcher(self):
        target=self.root.parent/'helper-runtime'/self.root.name
        target.mkdir(parents=True)
        for name in ('router.py','worker_routing.py','MANIFEST.json'):
            (target/name).write_bytes((self.root/name).read_bytes())
        template=(pathlib.Path(__file__).resolve().parents[1]/'scripts/helper_launcher.py').read_text()
        text=template.replace('__BUNDLE_ID__',self.root.name).replace('__ROUTER_SHA256__',hashlib.sha256((self.root/'router.py').read_bytes()).hexdigest())
        launcher=self.root.parent/'helper_router.py'
        launcher.write_text(text,encoding='utf-8')
        return launcher,target

    def test_launcher_runs_pinned_catalog(self):
        launcher,_=self.launcher()
        result=subprocess.run([sys.executable,'-I','-B',str(launcher)],input=json.dumps(self.request),capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['model'],'gpt-6-luna')

    def test_launcher_rejects_consistent_worker_and_manifest_swap(self):
        launcher,target=self.launcher()
        malicious=b"raise RuntimeError('WORKER_EXECUTED')"
        (target/'worker_routing.py').write_bytes(malicious)
        manifest=json.loads((target/'MANIFEST.json').read_text())
        manifest['files']['worker_routing.py']=hashlib.sha256(malicious).hexdigest()
        (target/'MANIFEST.json').write_text(json.dumps(manifest))
        result=subprocess.run([sys.executable,'-I','-B',str(launcher)],input=json.dumps(self.request),capture_output=True,text=True,timeout=10)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('HELPER_MANIFEST_ID_MISMATCH',result.stderr)
        self.assertNotIn('WORKER_EXECUTED',result.stderr)

    def test_launcher_refuses_replaced_query_before_execution(self):
        launcher,target=self.launcher()
        (target/'router.py').write_text("raise RuntimeError('ROUTER_EXECUTED')")
        result=subprocess.run([sys.executable,'-I','-B',str(launcher)],input=json.dumps(self.request),capture_output=True,text=True,timeout=10)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('HELPER_LAUNCHER_BYTES_MISMATCH',result.stderr)
        self.assertNotIn('ROUTER_EXECUTED',result.stderr)
