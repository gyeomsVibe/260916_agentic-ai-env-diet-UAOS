"""Read-only, content-addressed helper catalog; never dispatches a provider."""
import sys
if not sys.flags.isolated: raise SystemExit('HELPER_ISOLATED_MODE_REQUIRED')
import hashlib
import json
import pathlib
import types
base = pathlib.Path(__file__).resolve().parent
manifest = json.loads((base/'MANIFEST.json').read_text(encoding='utf-8'))
identity = json.dumps({'files': manifest['files'], 'source_commit': manifest['source_commit']}, sort_keys=True).encode()
if base.name != hashlib.sha256(identity).hexdigest(): raise SystemExit('HELPER_MANIFEST_ID_MISMATCH')
data = {name: (base/name).read_bytes() for name in ('router.py', 'worker_routing.py')}
if any(hashlib.sha256(value).hexdigest() != manifest['files'].get(name) for name,value in data.items()): raise SystemExit('HELPER_BYTES_MISMATCH')
module = types.ModuleType('verified_worker_routing')
exec(compile(data['worker_routing.py'], str(base/'worker_routing.py'), 'exec'), module.__dict__)
try: request = json.load(sys.stdin); result = module.select_pool_worker(request['task'], request['availability'])
except (KeyError, TypeError, ValueError, RecursionError): print(json.dumps({'status': 'BLOCKED', 'reason': 'HELPER_REQUEST_INVALID'})); raise SystemExit(1)
print(json.dumps(result, ensure_ascii=False, allow_nan=False))
raise SystemExit(0 if result['status'] == 'READY' else 1)
