ACTIONABLE_DELTA verdict_requested=yes
WORK MANUAL U124-A (Antigravity design audit before implementation; author Claude, acting conductor)
goal: find loopholes in the design below before Ollama implements it. User complaint (2026-10-02): "Ollama cannot even copy; Antigravity uses Ollama fine." The local worker must stop losing whole runs to one dropped function.
receipts (ledger `.coord/usage/runs.jsonl`): Ollama worker 71 runs, about 15 PASS (21%), 1.47 of 1.8 wall-clock hours spent on failures. U123-L and U123-L2 (input 7,258 and 7,383 tokens) both failed UNREQUESTED_DELETION:v7_harness/calculator_gate.py:_digest,parent_digests. Cause: the file had 140 lines, below EDIT_MODE_MIN_LINES=150, so `v7_harness/adapters/ollama_worker.py` sent FORMAT_RULES (whole-file rewrite) and qwen2.5-coder:7b dropped two untouched helpers. The rest of the reply was usable. The conductor's spec also asked for the whole file (a spec error, fixed by process).
design:
D1 `ollama_worker._apply`: for a `===FILE:` block whose target is an existing .py file, before `_guard`, find the top-level functions and classes of the original file that are missing from the new content and not named for deletion by the task (`_deletion_requested`). Copy each one's exact source (decorators included) from the original and splice it back into the new content with `def_splice.splice_definitions` (appended before an `if __name__ == "__main__":` guard, else at the end). Log `restored_definitions` with the names, so the ledger shows it.
D2 Only top-level definitions are restored. A missing method or nested def, or a restore that fails to splice, keeps the current UNREQUESTED_DELETION failure (fail closed).
D3 `_guard` is unchanged and still runs after D1. Acceptance tests still run, so a restored helper that breaks import order fails the run.
D4 EDIT blocks and fenced blocks are unchanged: they never delete definitions.
non-goals: changing EDIT_MODE_MIN_LINES; changing models; restoring module-level constants or imports (not observed in receipts).
questions for you:
1. Is restoring a silently dropped helper safe, or can it resurrect code the task meant to remove without naming it, for example a function replaced under a new name?
2. Can the restored position (end of file) change behaviour, for example through decorators, registries filled at import, or name shadowing?
3. Is there a cheaper or stronger fix, for example forcing EDIT_RULES for every existing .py file?
reply: verdict PASS (go as designed) / REVISE (list concrete changes) / FAIL (why), each point with a file:line or a concrete counterexample. Read only; change no files.
