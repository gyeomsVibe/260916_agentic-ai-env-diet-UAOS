"""U215: no ingress 10 s after a letter is dispatched -> probe the receiver's usage -> replan if it is limited.

User order (2026-10-18): "메시지를 보냈을 때 10초 이상 회신이 안 온다면, 상대 도구의 사용량을 조사하고 그에 대비해 계획을
수정하는 로직". A paid reply takes 22-24 s (E5), so the deadline is on ingress, the receiver's turn having started
(its presence `observed_at` after the dispatch), never on the reply. The probe is the presence record: it already
turns Codex's rollout usage_limit_exceeded into LIMITED (presence.codex_quota_block), and a quota percentage is never
turned into tokens (docs/27). UNKNOWN is no ground for acting, so only LIMITED shortens the wait; the rest is LAG.
"""

from __future__ import annotations

from typing import Any

from .presence import _epoch

# The user's value (2026-10-18). Below the 22-24 s paid reply time, so it is measured on ingress only.
INGRESS_DEADLINE_S = 10


def decide(wait: dict[str, Any], record: dict[str, Any], moment: float) -> str:
    """WAIT (not due, ingress seen, or not a letter), REROUTE (receiver LIMITED) or LAG (no ingress, not limited)."""
    since = wait.get("since")
    if not str(wait.get("item", "")).startswith("letter:") or not isinstance(since, (int, float)):
        return "WAIT"
    if moment - since < INGRESS_DEADLINE_S:
        return "WAIT"
    seen = _epoch(record.get("observed_at"))
    if seen is not None and seen >= since:
        return "WAIT"
    return "REROUTE" if record.get("state") == "LIMITED" else "LAG"


def limit(wait: dict[str, Any], record: dict[str, Any], moment: float, default: int) -> int:
    """The wait limit scan applies: the ingress deadline once the receiver is limited, else the default."""
    return INGRESS_DEADLINE_S if decide(wait, record, moment) == "REROUTE" else default
