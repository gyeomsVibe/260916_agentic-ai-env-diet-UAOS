"""Installed template: pin reviewed query bytes before executing that buffer."""
import sys
if not sys.flags.isolated: raise SystemExit('HELPER_ISOLATED_MODE_REQUIRED')
import hashlib
import pathlib
bundle = pathlib.Path(__file__).resolve().parent/'helper-runtime'/'__BUNDLE_ID__'
router = bundle/'router.py'
data = router.read_bytes()
if hashlib.sha256(data).hexdigest() != '__ROUTER_SHA256__': raise SystemExit('HELPER_LAUNCHER_BYTES_MISMATCH')
exec(compile(data, str(router), 'exec'), {'__name__':'__main__','__file__':str(router)})
