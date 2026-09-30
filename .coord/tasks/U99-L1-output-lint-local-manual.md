```contract
work_id: U99-L1
worker: local
goal: Add v7_harness/output_lint.py that counts Korean and English prose lines in Claude transcript text, as the S3 baseline metric.
inputs:
- tests/test_u99l_output_lint.py sha256=6d17a2f5a4634dfd9e1b2b2086e7f7b5cef2027f4bfe4ff597906370493cf2a4
allow:
- v7_harness/output_lint.py
context_allow:
- tests/test_u99l_output_lint.py
acceptance: python -m unittest tests.test_u99l_output_lint
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

## Task (U99-L): new file `v7_harness/output_lint.py`

Create the new file `v7_harness/output_lint.py` with one ===FILE block. It counts Korean and English prose lines in text Claude showed the user. Use only the standard library (`json`, `re`, `sys`, `pathlib.Path`). Start the file with `from __future__ import annotations` after a one-line module docstring.

Module constants, each with a comment line above it:

1. `HANGUL = re.compile(r"[가-힣]")` with comment `# One Hangul syllable marks a Korean line, even with English terms in it.`
2. `LATIN_WORD = re.compile(r"[A-Za-z]{2,}")`
3. `ENGLISH_MIN_WORDS = 4` with comment `# Fewer Latin words is a label, path or ID, not English prose.`

Function `lint_text(text: str) -> dict`:

- Start with `counts = {"lines": 0, "korean": 0, "english": 0}` and `in_fence = False`.
- For each `line` in `text.splitlines()`: let `stripped = line.strip()`.
  - If `stripped.startswith("```")`: flip `in_fence` and continue.
  - If `in_fence` or `not stripped`: continue.
  - Add 1 to `counts["lines"]`.
  - If `HANGUL.search(stripped)`: add 1 to `counts["korean"]`.
  - Else if `len(LATIN_WORD.findall(stripped)) >= ENGLISH_MIN_WORDS`: add 1 to `counts["english"]`.
- Return `counts`.

Function `lint_transcript(path: Path) -> dict`:

- Start with `totals = {"messages": 0, "lines": 0, "korean": 0, "english": 0}`.
- If `not Path(path).is_file()`: skip reading.
- Otherwise, for each line of `Path(path).read_text(encoding="utf-8", errors="replace").splitlines()`:
  - `row = json.loads(line)` inside try; on `json.JSONDecodeError` continue. Continue when `row` is not a dict or `row.get("type") != "assistant"`.
  - `content = (row.get("message") or {}).get("content")`. If it is a str, `texts = [content]`. If it is a list, `texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]`. Otherwise `texts = []`.
  - If `texts` is empty: continue. Else add 1 to `totals["messages"]`, and for each text add the `lines`, `korean` and `english` of `lint_text(text)` to `totals`.
- After the loop set `totals["english_share"] = totals["english"] / totals["lines"] if totals["lines"] else 0.0`, and return `totals`.

Function `main(argv: list[str] | None = None) -> int`:

- For each path in `argv if argv is not None else sys.argv[1:]`, print `json.dumps({"path": path, **lint_transcript(Path(path))}, ensure_ascii=False)`. Return 0.

End with:

```
if __name__ == "__main__":
    raise SystemExit(main())
```

Give each function a one-line docstring. Separate top-level definitions by two blank lines. Do not change any other file.

## Output

- Reply with ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
