"""Same Windows 16-thread workload before/after; fail on first exception or duplicate."""
from pathlib import Path
import json
import sys
import tempfile
import threading
import traceback

source = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(source))
from v7_harness.coord import user_window as uw

errors = []
for round_no in range(60):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / '.coord').mkdir()
        titles = []
        def run(i):
            try:
                titles.append(uw.claim(root, 'claude', f's{i}')['title'])
            except Exception:
                errors.append(traceback.format_exc())
        workers = [threading.Thread(target=run, args=(i,)) for i in range(16)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        if len(set(titles)) != 16:
            errors.append('missing or duplicate title: ' + repr(titles))
    if errors:
        break
print(json.dumps({'rounds': round_no + 1, 'errors': len(errors)}))
for error in errors[:2]:
    print(error)
sys.exit(1 if errors else 0)
