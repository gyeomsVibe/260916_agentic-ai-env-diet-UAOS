```contract
work_id: U277-A9-R2
worker: local
goal: Make deliver._repo_url return a credential-free host/path repository identity or empty UNKNOWN, per the instructions file
inputs:
- v7_harness/coord/deliver.py sha256=89b040e387ca3b87cc575ac944f10c25bcee7d0ecbbab4132a310ca71ebe2a0a
- tests/test_u277_repo_identity.py sha256=b3661b65e9d9f18049ecc21c3a0d5c3ee3e1d329fea9057fdb44278efaafe531
allow:
- v7_harness/coord/deliver.py
context_allow:
- v7_harness/coord/deliver.py
- tests/test_u277_repo_identity.py
acceptance: python -m pytest -q -p no:cacheprovider tests/test_u277_repo_identity.py
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

# U277-A9 source-only contract: credential-free repository identity

Why: Codex A8 REVISE (relay_f6ab3525, `.work/desk_261028_2/U277_A8_VERDICT.md`). `deliver._repo_url` returns
`git config --get remote.origin.url` verbatim and `requests.register` persists it, so HTTPS userinfo, query and
fragment authentication material lands in `.coord/requests/*.json`. Python's own docs warn that URL splitting does
not validate input (https://docs.python.org/3/library/urllib.parse.html#url-parsing-security), so the fix is an
allow-list normaliser that fails to UNKNOWN, not a strip of known-bad parts.

## Allowed change

Only `v7_harness/coord/deliver.py`, only the body of `_repo_url` plus at most one private helper next to it.
No other file, no evaluator, no test, no cap or budget change. Keep the git call exactly as it is (argv, 5 s timeout,
no shell). Callers and the binding fields (project, head, requester_session) stay untouched.

## Required behaviour of `_repo_url(root) -> str`

Return `"<host>/<path>"` or `""` (explicit UNKNOWN, the existing unavailable value). Never return any other text.

1. git failure, non-zero return code, or empty/whitespace output → `""`.
2. URL form `scheme://...` with scheme in {https, http, ssh, git}: take `hostname` (lower-case) and `path` from
   `urllib.parse.urlsplit`; discard username, password, port, query and fragment entirely. Read `parts.port`
   inside the same `try/except ValueError` (urllib validates the port lazily), so a non-numeric or out-of-range
   port such as `:notaport` or `:99999` returns `""` (Codex A9 port gate). Any other scheme
   (file, ext, …) → `""`.
3. scp form `[user@]host:path` (no `://`, exactly one `:` before the path, host has no `/`, `\` or whitespace):
   host is the part after the last `@` and before `:`; path is after `:`. The user part is discarded.
4. Anything else (Windows or POSIX local path, bare words) → `""`.
5. Validate before returning: host must match `^[a-z0-9.-]+$` and contain at least one `.` or be `localhost`;
   path stripped of leading/trailing `/` and one trailing `.git` must be non-empty and match `^[A-Za-z0-9._/-]+$`.
   Either check failing → `""`.
6. Result is `host + "/" + path`, so `https://h/t/r.git`, `git@h:t/r.git`, `ssh://git@h/t/r` all give `h/t/r`.

## Acceptance (judge runs; author must not edit)

- `python -m pytest -q -p no:cacheprovider tests/test_u277_repo_identity.py` exit 0 (fixtures only, 4 tests).
- Codex frozen gates on the stage: `.work/desk_261028_1/u277_repo_identity_gate.py` and `u277_session_gate.py` exit 0.
- Full suite exit 0.

## Stop

Stop and report on any need to touch another file or function, or on a second failure of the same cause.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
