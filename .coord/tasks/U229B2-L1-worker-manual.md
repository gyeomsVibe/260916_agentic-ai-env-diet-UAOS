# U229B2-L1 (judge claude, deputy for LIMITED codex; Codex re-review owed): invocation journal skeleton

Card manual: `.coord/tasks/U229B2-card-manual.md`. Slice 1 of `v7_harness/invocation.py` (new file): module
docstring, imports, constants, `InvocationError` and the `__main__` guard. Functions follow in L2 and L3 as whole
top-level definitions spliced by name. The main guard calls `main`, which L3 adds; nothing runs the module before.

```contract
work_id: U229B2-L1
worker: local
goal: create the v7_harness/invocation.py skeleton (imports, constants, InvocationError) for the U229 B2 journal
inputs:
- tests/test_u229_independent_invocation.py sha256=e755fafb36ca36a071835f67ab52e259eaf40563d8ad38e84cfdf2f8f7e1201c
allow:
- v7_harness/invocation.py
context_allow:
- tests/test_u229_independent_invocation.py
acceptance: python -c "import v7_harness.invocation as i; assert issubclass(i.InvocationError, ValueError) and i.CALLERS == ('codex', 'claude', 'antigravity')"
forbidden: editing or deleting tests; edits outside allow; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 900 seconds
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Exact file, verbatim

===FILE: v7_harness/invocation.py===
"""U229: durable metadata-only invocation receipts and evidence-only review.

The journal grants no approval and stores no prompts or raw provider diagnostics.
Provider execution is parked: atomic process-tree containment was not proven.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time
import uuid

CALLERS = ("codex", "claude", "antigravity")
HAIKU = "claude-haiku-5-5"
LOCAL_MODEL = "qwen2.5-coder:7b"
DEFAULT_DB = Path.home() / ".uaos" / "usage" / "invocations.sqlite3"
SECRET = re.compile(r"(?:sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|Bearer\s+\S{20,})")
SCHEMA = """CREATE TABLE IF NOT EXISTS attempts (
 id TEXT PRIMARY KEY, caller TEXT NOT NULL, project TEXT NOT NULL,
 work_id TEXT NOT NULL, purpose TEXT NOT NULL, model TEXT NOT NULL,
 input_sha256 TEXT NOT NULL, started_at REAL NOT NULL, finished_at REAL,
 wall_time_s REAL, outcome TEXT NOT NULL, error_class TEXT,
 input_tokens INTEGER, output_tokens INTEGER, acceptance TEXT NOT NULL,
 metadata TEXT NOT NULL DEFAULT '{}')"""


class InvocationError(ValueError):
    """Invalid/unbounded request or an unavailable durable receipt."""


if __name__ == "__main__":
    raise SystemExit(main())
===END===

## Output

- Reply with the one ===FILE block above, copied character for character. No explanations. Do not claim success;
  the acceptance command decides.
