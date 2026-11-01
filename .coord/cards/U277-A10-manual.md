```contract
work_id: U277-A10
worker: local
goal: Apply the dictated U277-A10 edits to deliver._repo_url/_repo_identity and requests.claim_wake per the instructions file
inputs:
- v7_harness/coord/deliver.py sha256=89b040e387ca3b87cc575ac944f10c25bcee7d0ecbbab4132a310ca71ebe2a0a
- v7_harness/coord/requests.py sha256=331b555079239a6d7e448abcf9397286cecd202171bb672f0a3a42ede204145f
- tests/test_u277_repo_identity.py sha256=80d36adc29a5a573c5a9038f59a8ba117970dda76f4a5bb59b55705b37ee36ed
- tests/test_u277_request_wake.py sha256=43759e386c743579d44961fdb9fbf3394dd5cebf6c710f2d9895dbbaea252569
allow:
- v7_harness/coord/deliver.py
- v7_harness/coord/requests.py
context_allow:
- v7_harness/coord/deliver.py
- v7_harness/coord/requests.py
acceptance: python -m unittest tests.test_u277_repo_identity tests.test_u277_request_wake
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: antigravity
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

# U277-A10 dictation contract: repository identity + bound-session wake (PR #250 rework)

Why: Claude REVISE on PR #250 head 417031d. Two Codex judge gates fail there: the A9 port gate
(`.work/desk_261028_3/u277_malformed_port_gate.py`, expects "UNKNOWN" for `:notaport` / `:99999`) and the A8 session
gate (a blank-session watcher may claim a bound request's wake). The fix is fixed below; copy the blocks exactly.

## Allowed change

Only `v7_harness/coord/deliver.py` and `v7_harness/coord/requests.py`, only the five blocks below. No other edit.

## Output

Reply with exactly these ===EDIT blocks, unchanged.

===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
import time
import uuid
=======
import time
import urllib.parse
import uuid
>>>>>>> REPLACE

===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
def _repo_url(root: Path) -> str:
    """The remote a request was made in (a binding field, U277). "" when git is unavailable."""
=======
# The Codex A9 judge gate (desk_261028_3/u277_malformed_port_gate.py) names an unusable remote "UNKNOWN".
REPO_UNKNOWN = "UNKNOWN"


def _repo_identity(raw: str) -> str:
    """U277-A9: "<host>/<path>" or REPO_UNKNOWN; allow-list only, so userinfo, port, query and fragment never persist."""
    raw = raw.strip()
    if not raw:
        return REPO_UNKNOWN
    if "://" in raw:
        try:
            parts = urllib.parse.urlsplit(raw)
            host = (parts.hostname or "").lower()
            parts.port  # urllib validates the port lazily; a malformed one raises here (Codex A9 port gate)
        except ValueError:
            return REPO_UNKNOWN
        if parts.scheme.lower() not in ("https", "http", "ssh", "git"):
            return REPO_UNKNOWN
        path = parts.path
    else:
        m = re.fullmatch(r"(?:[^@/\s]+@)?([^@:/\s]+):([^:\s].*)", raw)
        if not m:
            return REPO_UNKNOWN
        host, path = m.group(1).lower(), m.group(2)
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    path = path.strip("/")
    if not re.fullmatch(r"[a-z0-9.-]+", host) or ("." not in host and host != "localhost"):
        return REPO_UNKNOWN
    if not path or not re.fullmatch(r"[A-Za-z0-9._/-]+", path):
        return REPO_UNKNOWN
    return f"{host}/{path}"


def _repo_url(root: Path) -> str:
    """The remote a request was made in (a binding field, U277). "" (the binding's unavailable value) when git is
    unavailable or the remote has no safe identity."""
>>>>>>> REPLACE

===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
    return done.stdout.strip() if done.returncode == 0 else ""
=======
    if done.returncode != 0:
        return ""
    identity = _repo_identity(done.stdout)
    return "" if identity == REPO_UNKNOWN else identity
>>>>>>> REPLACE

===EDIT: v7_harness/coord/requests.py===
<<<<<<< SEARCH
        if wanted and session and session != wanted:
=======
        # A bound request wakes only its requester session; a blank or passive watcher may not claim it (Codex A8).
        if wanted and session != wanted:
>>>>>>> REPLACE

## Acceptance (judge runs; author must not edit)

- `python -m unittest tests.test_u277_repo_identity tests.test_u277_request_wake` exit 0.
- Codex frozen gate `.work/desk_261028_3/u277_malformed_port_gate.py` (project root) exit 0.
- Full suite exit 0 (run without `-X utf8`).

## Stop

Two failures with the same cause; input hash mismatch; any SEARCH block not found exactly once.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
