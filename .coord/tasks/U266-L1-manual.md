# U266-L1 Contract Manual — Boilerplate-Immune Topic Extraction & Windows MSIX Session Store Discovery in `user_window.py`

```contract
work_id: U266-L1
worker: local
goal: Update _claude_sessions_root and _topic_from_text in v7_harness/coord/user_window.py so Windows MSIX Claude-Data claude-code-sessions is discovered and meta-instruction boilerplate sentences never pollute entry['topic']
inputs:
  - v7_harness/coord/user_window.py sha256=80606265541cba505d4ac535854b6837d2d19b49abb8536a5e950b648ab814b8
  - tests/test_u266_3tool_title_overhaul.py sha256=b37e771eb9440c5a32b3bed65fab31cd7b063d1464ebc94f6e61d841cd2bf7c9
allow:
  - v7_harness/coord/user_window.py
context_allow:
  - tests/test_u266_3tool_title_overhaul.py
acceptance: C:\Python314\python.exe -m unittest tests.test_u266_3tool_title_overhaul.U266ThreeToolTitleOverhaulTests.test_1_meta_boilerplate_prompt_never_pollutes_entry_topic tests.test_u266_3tool_title_overhaul.U266ThreeToolTitleOverhaulTests.test_4_claude_sessions_root_discovers_windows_msix_claude_data_store tests.test_u237_desk_titles
forbidden: editing or deleting tests; edits outside allow; edits to any other function; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 300 seconds
judge: claude
timeout_s: 300
remote_budget_tokens: 0
```

## Task Specification (Replace `def _claude_sessions_root` and `def _topic_from_text` only)

Replace `def _claude_sessions_root` and `def _topic_from_text` in `v7_harness/coord/user_window.py` with:

```python
_META_BOILERPLATE = (
    "대화창 제목", "자동변환", "출석체크", "마스터 계획 스케줄", "무승인 논스톱",
    "승인은 구하지", "올라마 CLI", "Haiku 5.5", "티키타카 무승인",
)


def is_boilerplate_topic(text: str | None) -> bool:
    if not isinstance(text, str):
        return True
    cleaned = re.sub(r"^[\s#*>-]+", "", text).strip()
    return not cleaned or any(w in cleaned for w in _META_BOILERPLATE) or cleaned in ("출석체크하고", "대화창 제목을 이제부터")


def _claude_sessions_root() -> Path:
    appdata = os.environ.get("APPDATA")  # Windows desktop app; macOS keeps the same folder under Application Support
    base = Path(appdata) / "Claude" if appdata else Path.home() / "Library" / "Application Support" / "Claude"
    roaming = base / "claude-code-sessions"
    if roaming.is_dir():
        return roaming
    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        for candidate in sorted((Path(localappdata) / "Claude-Data").glob("claude_*/claude-code-sessions")):
            if candidate.is_dir():
                return candidate
    return roaming


def _topic_from_text(text) -> str | None:
    """U237/U266: a window's own sidebar topic is the first non-boilerplate sentence of its declaration prompt
    that is not the declaration, with URLs, paths and brackets removed, cut at a word to the topic limit."""
    from .title_consensus import MAX_TOPIC_CHARS, valid_topic
    text = typed_prompt(text)
    if not isinstance(text, str):
        return None
    text = re.sub(r"https?://\S*|[A-Za-z]:[\\/]\S*|\S*[\\/]\S*|[\[\]]", " ", text)
    for sentence in re.split(r"[\n.!?。]+", text):
        if (_DECLARE_RE.search(sentence) and any(word in sentence for word in _DESIGNATION)) or is_boilerplate_topic(sentence):
            continue
        sentence = re.sub(r"^[\s#*>-]+", "", sentence)
        words = sentence.split()
        topic = ""
        for word in words:
            if len(f"{topic} {word}".strip()) > MAX_TOPIC_CHARS:
                break
            topic = f"{topic} {word}".strip()
        topic = topic or (words[0][:MAX_TOPIC_CHARS] if words else "")
        if len(topic) >= 2 and valid_topic(topic) and not is_boilerplate_topic(topic):
            return topic
    return None
```

Do not change any other line of the file.
