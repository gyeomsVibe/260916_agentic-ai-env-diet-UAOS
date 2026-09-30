```contract
work_id: U102-N
worker: apply
goal: Hide Claude's own mailbox letters (evt -claude- names and actor=claude relays) from the prompt hook.
inputs:
- tests/test_u102n_own_letters.py sha256=663a029c15912e668b6da91db40d239faac3c4c0951f4b81b2cd0e4649eef1e6
allow:
- uaos_everywhere/hooks/codex_delta.py
context_allow:
- tests/test_u102n_own_letters.py
acceptance: python -m unittest tests.test_u102n_own_letters tests.test_u99m_mailbox_delta tests.test_u101_absence_brief
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the blocks below exactly (judge-dictated, 12 lines, U98-D apply limit is 20).

The prompt hook showed Claude its own letters: `evt_<stamp>-claude-0001.json` passed the old filter, which looked only at the text before the first `-`, and a relay Claude sent says who wrote it only in `payload.actor`.

===EDIT: uaos_everywhere/hooks/codex_delta.py===
<<<<<<< SEARCH
def plan_rows(path: Path) -> dict[str, str]:
=======
def actor_of(path: Path) -> str:
    """Who wrote a JSON letter (`payload.actor`), or "" when the file says nothing readable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return str(data.get("payload", data).get("actor") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def plan_rows(path: Path) -> dict[str, str]:
>>>>>>> REPLACE
===END===

===EDIT: uaos_everywhere/hooks/codex_delta.py===
<<<<<<< SEARCH
                if name.startswith("claude_to_") or "claude" in name.split("-")[0]:
                    continue  # Claude's own letters are not news to Claude
=======
                # U102-N: 240 of Claude's own evt letters carry "-claude-" mid-name; its relays say so only in actor.
                own = name.startswith("claude_to_") or "claude" in name.split("-")[0] or "claude" in name.split("-")
                if own or (path.suffix == ".json" and actor_of(path) == "claude"):
                    continue  # Claude's own letters are not news to Claude
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
