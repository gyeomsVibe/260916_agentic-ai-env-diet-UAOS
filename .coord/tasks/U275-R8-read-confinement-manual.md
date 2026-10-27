# U275-R8 — PR244 opened-object read contract (author: antigravity; judges: claude gate + codex)

Receipt: Codex `PR244-R7-6436-REVIEW` = REVISE_READ_CONFINEMENT_NOT_ESTABLISHED on head 6436f30.
Finding: `_inspect_binary_static` checks ancestors *after* `bin_path.read_bytes()`; no opened-handle
identity is validated, so bytes may come from an object outside root. Same pattern at the source-file
read (`f.read_bytes()`) and the SQLite copy (`shutil.copy2(db_path, ...)`, WAL/SHM copies).

## Goal
Every byte rea_bridge consumes from the target tree is read from a file descriptor whose identity was
verified to be the in-root regular file. Keep the verified restore/CAS improvement unchanged.

## Contract (one helper, all sites)
Add `_read_confined_bytes(path: Path, root: Path | None) -> bytes` in `v7_harness/rea_bridge.py`:
1. `has_symlink_or_junction_ancestor(path, root)` false, else raise `ConfinementError("SYMLINK_OR_JUNCTION_ESCAPE")`.
2. `pre = os.lstat(path)`; require `stat.S_ISREG(pre.st_mode)` and, on Windows, no
   `FILE_ATTRIBUTE_REPARSE_POINT` in `pre.st_file_attributes`; else `NOT_REGULAR_FILE`.
3. `fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))`.
4. `opened = os.fstat(fd)`; require `(opened.st_dev, opened.st_ino) == (pre.st_dev, pre.st_ino)` and
   `S_ISREG(opened.st_mode)`; else close fd and raise `HANDLE_IDENTITY_MISMATCH`.
5. Re-run step 1 and `post = os.lstat(path)` with the same (dev, ino) check *before* reading; mismatch → raise.
6. Read only via `os.read(fd, ...)` loop (or `os.fdopen(fd, "rb")`), cap at the existing size limit; `finally` close.
Define `class ConfinementError(OSError)` carrying the code string.

Replace: source `f.read_bytes()`, binary `bin_path.read_bytes()`, SQLite `shutil.copy2(db_path/wal/shm, snap)`
→ write `_read_confined_bytes(...)` output into the snapshot files. Error codes surface unchanged in
`failed_files` / `error` fields. No `read_bytes()`/`open(`/`copy2(` on target-tree paths may remain;
reads of the temp snapshot are allowed.

## Tests (ordinary, no directory-race fixture — Codex: do not retry the blocked fixture)
`tests/test_u275_r8_read_confinement.py`, using `unittest.mock.patch`:
- call order: lstat → open → fstat → lstat → read (record calls; assert order).
- fstat returning a different st_ino → `HANDLE_IDENTITY_MISMATCH`, zero bytes returned, fd closed.
- post-open lstat ino change → mismatch, fd closed.
- lstat reports reparse attribute / non-regular → `NOT_REGULAR_FILE`, `os.open` never called.
- happy path: real temp file inside root returns exact bytes; binary + sqlite + .py inspection still pass.

## Allowed files
`v7_harness/rea_bridge.py`, `tests/test_u275_r8_read_confinement.py`, `.coord/results/U275.md`.
Bans: no other source, no test shrink, no edits to existing tests, no runtime install, no merge.

## Pass command (judge reruns)
`python -m unittest tests.test_u275_r8_read_confinement -v` exit 0, plus existing
`python -m unittest discover -s tests -p "test_u275_*.py"` exit 0, plus judge gate
`python .work/u275_r8/judge_gate.py <head>` exit 0 (Claude-owned, not shared with author before verdict).

## Stop / caps
Push one new commit to `agy/u275-auto-rea-reverse-engineering`, reply RESULT (head sha, tests, exit codes).
Cap: one implementation attempt, 60 min wall. On failure reply BLOCKED with the error; do not loop.
