```contract
work_id: U95-A
worker: apply
goal: Make Antigravity addressable by UAOS letters and tell it, once per change, what waits for it and what its role is, so it follows UAOS work orders without the user relaying them.
inputs:
- .coord/PLAN.md sha256=0606bf49f8a9beafc366417455de6a17a6564b6271a21506094b3a4db60b35eb
- v7_harness/cli.py sha256=b86bd7658e674ae4e646bc1d620432bc305c9511875043a9773bbe8d678cb87d
- v7_harness/coord/hook_context.py sha256=09059a3e8286b098363664157e6bed879423ff74e58321c644e5583c93c95aa4
- v7_harness/coord/deliver.py sha256=8002270c56511b244f6e924d47656d0fa5b98eaf6b5b92c22721995fc83eb81e
- v7_harness/global_install.py sha256=f6e85160cb911d6ef03f3df36b6b3e7a7c5ade474dddf1a944ea3c0272a7efa3
- tests/test_u37_install_everywhere.py sha256=c4596292e05327d3b1e2f2c591c70c46f3a6a2207cc6617efb500ef7f0dd25f7
allow:
- v7_harness/cli.py
- v7_harness/coord/hook_context.py
- v7_harness/coord/deliver.py
- v7_harness/global_install.py
- tests/test_u37_install_everywhere.py
- tests/test_u95a_antigravity_briefing.py
- .coord/PLAN.md
acceptance: python -m unittest tests.test_u95a_antigravity_briefing tests.test_u37_install_everywhere tests.test_u57_desk_signals tests.test_u94r1_watch_scan_cost
forbidden: design changes; edits outside allow; weakening or deleting existing tests (the one test_u37 line changes the expected installer flag from empty-json to agy, the behavior this card changes; the empty-json CLI test stays); writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the EDIT and FILE blocks exactly.

Receipt (2026-09-30, Claude audit for the token-thrift project U95): Antigravity's UAOS presence hook prints `{}` (`--say empty-json`), and `coord deliver --target` accepts only codex and claude. Antigravity therefore never learns from UAOS what waits for it; its only UAOS knowledge is GEMINI.md, and every work order so far reached it through the user. In the same period its olla hook injected a plan hint on 202 turns. Antigravity's PreInvocation hook accepts `{"injectSteps": [{"ephemeralMessage": ...}]}` (used by `olla hook-agy`, `v7_harness/olla.py`), so the same channel can carry the UAOS line.

===EDIT: v7_harness/coord/hook_context.py===
<<<<<<< SEARCH
RETENTION_SEEN = Path(".coord") / "presence" / "retention_seen.txt"
=======
# U95-A: Antigravity's dedupe record, beside p1_hook_seen.txt (.coord/presence/ is git-ignored).
AGY_SEEN = Path(".coord") / "presence" / "agy_hook_seen.txt"
AGY_TARGET = "antigravity"
# Five ids (38 characters each) keep the line near 200 tokens; `coord inbox` lists the rest.
AGY_SHOWN = 5


def agy_letters(project: Path) -> list[str]:
    """Ids of inbox letters addressed to Antigravity (requested_target or to), in name order."""
    box_dir = Path(project) / ".coord" / "mailbox" / "inbox"
    found: list[str] = []
    if not box_dir.is_dir():
        return found
    for path in sorted(box_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue  # claimed or mid-write: the next turn looks again
        payload = data.get("payload") if isinstance(data, dict) else None
        if isinstance(payload, dict) and AGY_TARGET in (payload.get("requested_target"), payload.get("to")):
            found.append(path.stem)
    return found


def agy_line(project: Path, presence: dict[str, Any], stdin_text: str) -> str:
    """U95-A: what Antigravity learns about UAOS on the first model call of a turn, said only when it changed.

    Seen 2026-09-30: Antigravity's presence hook printed only {} and `coord deliver` could not address it, so its only
    UAOS knowledge was GEMINI.md and every work order reached it through the user. The line names Antigravity's role
    and the letters addressed to it. It repeats only when the conversation, the desk or those letters change, so an
    unchanged desk costs no tokens; later calls of the same turn read nothing from disk.
    """
    try:
        event = json.loads(stdin_text) if stdin_text.strip() else {}
    except json.JSONDecodeError:
        event = {}
    if not isinstance(event, dict):
        event = {}
    if event.get("invocationNum", 0) != 0:
        return ""
    letters = agy_letters(project)
    desk = ", ".join(f"{tool}={info.get('state')}" for tool, info in presence.items())
    conversation = str(event.get("conversationId") or "")
    fingerprint = hashlib.sha256("\n".join([conversation, desk, *letters]).encode("utf-8")).hexdigest()
    seen = Path(project) / AGY_SEEN
    try:
        if seen.read_text(encoding="utf-8").strip() == fingerprint:
            return ""
    except OSError:
        pass
    try:
        seen.parent.mkdir(parents=True, exist_ok=True)
        seen.write_text(fingerprint, encoding="utf-8")
    except OSError:
        pass  # a hook never fails the session; the line is said again next time
    line = (f"UAOS project {Path(project).name}: desk {desk}. Antigravity conducts only while codex and claude are "
            "both LIMITED/ABSENT; otherwise it does only work orders addressed to antigravity and never judges its "
            "own work. ")
    if letters:
        line += (f"{len(letters)} letter(s) for antigravity in .coord/mailbox/inbox: {', '.join(letters[:AGY_SHOWN])}. "
                 "Each names a work manual: keep to its allow, acceptance, forbidden and stop lines, then report with "
                 "`uaos coord deliver --actor antigravity --target claude --message ...`.")
    else:
        line += "No letter waits for antigravity; .coord/PLAN.md lists the cards."
    return line[:900]


RETENTION_SEEN = Path(".coord") / "presence" / "retention_seen.txt"
>>>>>>> REPLACE
===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
    p_coord_deliver.add_argument("--target", default=None, choices=["codex", "claude"])
=======
    # U95-A: antigravity has no CLI to wake; its letter waits in the inbox and its PreInvocation hook names it.
    p_coord_deliver.add_argument("--target", default=None, choices=["codex", "claude", "antigravity"])
>>>>>>> REPLACE
===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
    p_coord_presence.add_argument("--say", choices=["json", "brief", "none", "empty-json", "p1"], default="json",
                                  help="What to print: presence JSON (default), one context line, nothing, {}, or "
                                       "p1 = one line only when a P1 wake waits and Codex is not ACTIVE (U38)")
=======
    p_coord_presence.add_argument("--say", choices=["json", "brief", "none", "empty-json", "p1", "agy"], default="json",
                                  help="What to print: presence JSON (default), one context line, nothing, {}, "
                                       "p1 = one line only when a P1 wake waits and Codex is not ACTIVE (U38), or "
                                       "agy = Antigravity injectSteps JSON on a turn's first call when its line "
                                       "changed, else {} (U95-A)")
>>>>>>> REPLACE
===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
        elif say == "empty-json":
            print("{}")

    if getattr(args, "from_hook", False):
        from .coord.hook_context import (
            brief_line,
=======
        elif say == "empty-json":
            print("{}")
        elif say == "agy":
            # Antigravity reads one JSON object on stdout; a skip, an error or an unchanged line prints {}.
            print(json.dumps({"injectSteps": [{"ephemeralMessage": line}]}, ensure_ascii=False) if line else "{}")

    if getattr(args, "from_hook", False):
        from .coord.hook_context import (
            agy_line,
            brief_line,
>>>>>>> REPLACE
===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
            line = p1_line(project, presence) if say == "p1" else brief_line(project, presence)
=======
            if say == "agy":
                line = agy_line(project, presence, stdin_text)
            else:
                line = p1_line(project, presence) if say == "p1" else brief_line(project, presence)
>>>>>>> REPLACE
===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
    box.publish(message_id, _payload(actor, message, digest, requested_target))
    if target is None:
=======
    box.publish(message_id, _payload(actor, message, digest, requested_target))
    if target == "antigravity":
        # U95-A: no CLI wakes Antigravity; its PreInvocation hook names the letter on its next turn (agy_line).
        return DeliverResult(False, "antigravity", "PUBLISHED", (), "", message_id, digest)
    if target is None:
>>>>>>> REPLACE
===EDIT: v7_harness/global_install.py===
<<<<<<< SEARCH
                    # Antigravity runs hooks inside ~/.gemini/config (antigravity-cli#1005); --from-hook reads
                    # workspacePaths from stdin instead. It reads a JSON result on stdout, so the hook prints {}.
                    after[AGY_GROUP] = {"enabled": True, "PreInvocation": [{"type": "command", "command": presence_command(
                        python, launcher, "antigravity", "ACTIVE", 3600, "empty-json")}]}
=======
                    # Antigravity runs hooks inside ~/.gemini/config (antigravity-cli#1005); --from-hook reads
                    # workspacePaths from stdin instead. It reads a JSON result on stdout: {} or, when its UAOS line
                    # changed, injectSteps with that line (U95-A; before, it always printed {} and learned nothing).
                    after[AGY_GROUP] = {"enabled": True, "PreInvocation": [{"type": "command", "command": presence_command(
                        python, launcher, "antigravity", "ACTIVE", 3600, "agy")}]}
>>>>>>> REPLACE
===EDIT: tests/test_u37_install_everywhere.py===
<<<<<<< SEARCH
        self.assertIn("--say empty-json", agy["uaos-presence"]["PreInvocation"][0]["command"])
=======
        self.assertIn("--say agy", agy["uaos-presence"]["PreInvocation"][0]["command"])
>>>>>>> REPLACE
===EDIT: .coord/PLAN.md===
<<<<<<< SEARCH
`tests/test_u94r1_watch_scan_cost.py` |
=======
`tests/test_u94r1_watch_scan_cost.py` |
| U95-A | REVIEW (Claude 설계, Codex 복귀 시 재검토) | claude(설계) · apply(0토큰) | 영수증: Antigravity의 UAOS 출석 훅은 `{}`만 출력했고 `coord deliver --target`은 codex·claude만 받아, Antigravity는 UAOS에서 자기 일을 알 수 없었음(작업 지시는 모두 사용자 전달). 같은 기간 olla 훅은 202턴에 계획 안내를 주입. 조치: `deliver --target antigravity`(우편함 게시만), 출석 훅 `--say agy`가 턴 첫 호출에서 역할과 Antigravity 앞 편지를 바뀐 때만 injectSteps로 알림. — `v7_harness/coord/hook_context.py`, `v7_harness/cli.py`, `v7_harness/coord/deliver.py`, `v7_harness/global_install.py`, `tests/test_u95a_antigravity_briefing.py` |
>>>>>>> REPLACE
===FILE: tests/test_u95a_antigravity_briefing.py===
"""U95-A: Antigravity can be addressed by a UAOS letter, and its presence hook tells it once per change.

Seen 2026-09-30: the Antigravity presence hook printed only {} and `coord deliver --target` accepted only codex and
claude, so Antigravity never learned from UAOS what waited for it; every work order reached it through the user.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from v7_harness.cli import main
from v7_harness.coord.deliver import deliver
from v7_harness.coord.hook_context import agy_letters, agy_line
from v7_harness.coord.mailbox import Mailbox

DESK = {"codex": {"state": "ABSENT"}, "claude": {"state": "ACTIVE"}, "antigravity": {"state": "ACTIVE"}}


def _event(conversation: str, invocation: int = 0) -> str:
    return json.dumps({"conversationId": conversation, "invocationNum": invocation})


class AntigravityBriefingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        (self.project / ".coord").mkdir()
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _order(self, text: str = "work order: read .coord/tasks/U95-R-manual.md") -> str:
        runner = mock.Mock(side_effect=AssertionError("antigravity has no CLI to dispatch to"))
        result = deliver(self.project, message=text, actor="claude", target="antigravity", runner=runner)
        self.assertEqual(("antigravity", "PUBLISHED"), (result.target, result.reason))
        return result.message_id

    def test_deliver_publishes_a_letter_addressed_to_antigravity_without_dispatch(self) -> None:
        message_id = self._order()
        self.assertEqual([message_id], agy_letters(self.project))

    def test_cli_accepts_antigravity_as_a_deliver_target(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["coord", "deliver", "--project", str(self.project), "--actor", "claude",
                         "--target", "antigravity", "--message", "work order: U95-R"])
        self.assertEqual(0, code)
        self.assertEqual("PUBLISHED", json.loads(out.getvalue())["reason"])

    def test_line_names_the_letter_once_per_conversation_and_again_when_letters_change(self) -> None:
        first_id = self._order()
        first = agy_line(self.project, DESK, _event("c1"))
        self.assertIn(first_id, first)
        self.assertIn("never judges its own work", first)
        self.assertEqual("", agy_line(self.project, DESK, _event("c1")))
        self.assertEqual("", agy_line(self.project, DESK, _event("c1", invocation=3)))
        second_id = self._order("work order: read .coord/tasks/U95-X-manual.md")
        again = agy_line(self.project, DESK, _event("c1"))
        self.assertIn(second_id, again)
        self.assertIn("2 letter(s)", again)
        self.assertIn(first_id, agy_line(self.project, DESK, _event("c2")))

    def test_letters_for_other_tools_are_not_named(self) -> None:
        (self.project / ".coord" / "mailbox").mkdir(exist_ok=True)
        Mailbox(self.project / ".coord" / "mailbox").publish(
            "relay_for_claude", {"kind": "HANDOFF", "actor": "codex", "message": "x", "requested_target": "claude"})
        self.assertEqual([], agy_letters(self.project))
        self.assertIn("No letter waits for antigravity", agy_line(self.project, DESK, _event("c1")))

    def test_presence_hook_prints_inject_steps_then_empty_json(self) -> None:
        self._order()
        payload = json.dumps({"conversationId": "c9", "invocationNum": 0, "workspacePaths": [str(self.project)]})

        def run() -> str:
            out = io.StringIO()
            # CLAUDE_PROJECT_DIR is emptied so a run inside a Claude Code session never finds the real desk.
            with redirect_stdout(out), mock.patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": ""}), \
                    mock.patch("v7_harness.coord.hook_context.read_stdin", return_value=payload):
                self.assertEqual(0, main(["coord", "presence", "--tool", "antigravity", "--state", "ACTIVE",
                                          "--from-hook", "--project", str(self.project), "--say", "agy"]))
            return out.getvalue()

        first = json.loads(run())
        self.assertIn("letter(s) for antigravity", first["injectSteps"][0]["ephemeralMessage"])
        self.assertEqual({}, json.loads(run()))


if __name__ == "__main__":
    unittest.main()
===END===

## Output

- Reply with ===EDIT and ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.
