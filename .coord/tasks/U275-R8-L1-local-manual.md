```contract
work_id: U275-R8-L1
worker: local
goal: Add ConfinementError and _read_confined_bytes helper to rea_bridge.py
inputs:
- v7_harness/rea_bridge.py sha256=d5c764952cbe87f45607f063a3f6d137591ba930a7d36fdb7e90dfa56a7b4118
allow:
- v7_harness/rea_bridge.py
acceptance: python .work/u275_r8/judge_helper_test.py
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Edit only `v7_harness/rea_bridge.py`. Add two new top-level definitions directly after the function
`is_symlink_or_junction` (do not change any existing line). Add `import stat` next to the existing imports if absent.

```python
class ConfinementError(OSError):
    """Raised when a target-tree read cannot be bound to the verified in-root regular file."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _read_confined_bytes(path: Path, root: Path | None = None, limit: int | None = None) -> bytes:
    """Read bytes only through a descriptor whose identity matches the in-root regular file."""
    if has_symlink_or_junction_ancestor(path, root):
        raise ConfinementError("SYMLINK_OR_JUNCTION_ESCAPE")
    pre = os.lstat(path)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if not stat.S_ISREG(pre.st_mode) or (getattr(pre, "st_file_attributes", 0) & reparse):
        raise ConfinementError("NOT_REGULAR_FILE")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (pre.st_dev, pre.st_ino):
            raise ConfinementError("HANDLE_IDENTITY_MISMATCH")
        if has_symlink_or_junction_ancestor(path, root):
            raise ConfinementError("SYMLINK_OR_JUNCTION_ESCAPE")
        post = os.lstat(path)
        if (post.st_dev, post.st_ino) != (pre.st_dev, pre.st_ino):
            raise ConfinementError("HANDLE_IDENTITY_MISMATCH")
        chunks = []
        total = 0
        while True:
            block = os.read(fd, 1 << 20)
            if not block:
                break
            chunks.append(block)
            total += len(block)
            if limit is not None and total > limit:
                raise ConfinementError("READ_LIMIT_EXCEEDED")
        return b"".join(chunks)
    finally:
        os.close(fd)
```

Make sure `import os` exists at the top. Output the full edited file.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
