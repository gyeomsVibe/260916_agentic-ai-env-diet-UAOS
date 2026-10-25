# U237E-L1: strip URLs and paths before the topic sentence split (user_window.py only)

Codex REWORK of U237D (relay_d014d03cc22f56f7f003ccfabeaf3eee, receipt `.coord/results/U237D-CODEX-REVIEW-261026.json`).
`_topic_from_text` split the prompt on dots before it removed URL and path spans, so `https://example.com` left the
topic `com` and `C:/Work/report.md` left `md`. The fix moves the removal in front of the split. The splicer replaces
whole top-level functions, so this manual dictates the whole function.

```contract
work_id: U237E-L1
worker: local
goal: _topic_from_text removes complete URLs and paths before splitting sentences, so no domain suffix or file extension becomes a topic
inputs:
- v7_harness/coord/user_window.py sha256=dd99bfac8fceb04354fcc7bef0cd2ce3e62877dd1922cdd83df72a2811bafcd8
- .coord/tasks/U237E-codex-topic-negative.py sha256=43d2afd05c1f989359957a7f16323c0f76acc97560bb02bbd4e4146f850a77c9
allow:
- v7_harness/coord/user_window.py
acceptance: python -B -m unittest tests.test_u237_desk_titles tests.test_u207_desk_title_handoff tests.test_u229_independent_title tests.test_u229_title_worker tests.test_u234_title_consensus tests.test_u150_user_window -q && python -B .coord/tasks/U237E-codex-topic-negative.py .
forbidden: editing or deleting tests; edits outside _topic_from_text; edits outside allow; network; paid model calls; commit/push; runtime install
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 900 seconds
judge: codex
timeout_s: 900
remote_budget_tokens: 0
```

## Exact edit: replace the whole top-level function `_topic_from_text` with this, verbatim

```python
def _topic_from_text(text) -> str | None:
    """U237: a window's own sidebar topic is the first sentence of its declaration prompt that is not the declaration,
    with URLs, paths and brackets removed, cut at a word to the topic limit. None when nothing valid remains.
    U237E: the removal runs before the sentence split; splitting first left "com" from https://example.com and "md"
    from C:/Work/report.md as topics."""
    from .title_consensus import MAX_TOPIC_CHARS, valid_topic
    text = typed_prompt(text)
    if not isinstance(text, str):
        return None
    text = re.sub(r"https?://\S*|[A-Za-z]:[\\/]\S*|\S*[\\/]\S*|[\[\]]", " ", text)
    for sentence in re.split(r"[\n.!?。]+", text):
        if _DECLARE_RE.search(sentence) and any(word in sentence for word in _DESIGNATION):
            continue
        words = sentence.split()
        topic = ""
        for word in words:
            if len(f"{topic} {word}".strip()) > MAX_TOPIC_CHARS:
                break
            topic = f"{topic} {word}".strip()
        topic = topic or (words[0][:MAX_TOPIC_CHARS] if words else "")
        if len(topic) >= 2 and valid_topic(topic):
            return topic
    return None
```

## Output

- Reply with one ===EDIT block holding the whole function above. No explanations. Do not claim success; the
  acceptance command decides.
