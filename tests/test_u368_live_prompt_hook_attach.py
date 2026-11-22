"""U368: the live prompt hook (desk_sync.on_hook) feeds auto_attach.hook_on_prompt for all three tools.

Receipt: U337 shipped the auto-attach queue and hook_on_prompt, but no live hook called it, so a human work prompt in
any tool's window never became a card. Each test maps one row of the U368 contract section 5 failure-mode table. All
fixtures live in a temporary project and a temporary Antigravity app home; no model, network or subprocess is used.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v7_harness.coord import auto_attach, deliver, desk_sync  # noqa: E402

DECLARE = "이제부터 여기 사용자 대화창구이다"
WORK = "Fix pkg/mod.py"


class TestU368LivePromptHookAttach(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        base = Path(self._tmp.name)
        self.project = base / "proj"
        (self.project / ".coord").mkdir(parents=True, exist_ok=True)
        self.app = base / "agy-app"
        (self.app / "conversations").mkdir(parents=True)
        self.conversation = str(uuid.uuid4())
        (self.app / "conversations" / f"{self.conversation}.db").write_bytes(b"")
        self.transcript = base / "transcript.jsonl"
        self._env = mock.patch.dict(os.environ, {deliver.AGY_APP_HOME_ENV: str(self.app)})
        self._env.start()
        for name in ("UAOS_WORKER", "UAOS_AUTO_ATTACH"):
            os.environ.pop(name, None)

    def tearDown(self) -> None:
        self._env.stop()
        self._tmp.cleanup()

    def _prompt_event(self, prompt: object, event_id: str = "") -> dict:
        event = {"hook_event_name": "UserPromptSubmit", "prompt": prompt}
        if event_id:
            event["event_id"] = event_id
        return event

    def _agy_event(self, prompts: list[str], invocation: int = 0) -> dict:
        lines = [json.dumps({"type": "USER_INPUT", "content": p}, ensure_ascii=False) for p in prompts]
        self.transcript.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {"invocationNum": invocation, "transcriptPath": str(self.transcript),
                "conversationId": self.conversation}

    def _presence(self, states: dict[str, str]) -> None:
        folder = self.project / ".coord" / "presence"
        folder.mkdir(parents=True, exist_ok=True)
        for tool, state in states.items():
            (folder / f"{tool}.json").write_text(json.dumps({"tool": tool, "state": state}), encoding="utf-8")

    @contextmanager
    def _spy(self):
        with mock.patch.object(auto_attach, "hook_on_prompt", wraps=auto_attach.hook_on_prompt) as spy:
            yield spy

    def test_peer_silent_zero_tokens_local(self) -> None:
        self._presence({"codex": "LIMITED", "antigravity": "ABSENT", "claude": "ACTIVE"})
        session = str(uuid.uuid4())
        with self._spy() as spy, mock.patch("subprocess.Popen", side_effect=AssertionError("no launch")), \
                mock.patch("subprocess.run", side_effect=AssertionError("no launch")):
            self.assertFalse(desk_sync.on_hook(self.project, "claude", self._prompt_event(WORK, "e1"), session))
        spy.assert_called_once_with(self.project, "claude", WORK, session=session, event_id="e1")
        queue = auto_attach.read_queue(self.project)
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["owner"], "claude")
        self.assertEqual(queue[0]["session"], session)
        self.assertEqual(queue[0]["event_id"], "e1")
        self.assertEqual(queue[0]["peers"], ["codex", "antigravity"])

    def test_message_flood_deduplicated(self) -> None:
        session = str(uuid.uuid4())
        for i in range(20):
            self.assertFalse(desk_sync.on_hook(self.project, "codex",
                                               self._prompt_event(f"Fix pkg/mod_{i}.py", f"e{i}"), session))
        queue = auto_attach.read_queue(self.project)
        self.assertEqual(len(queue), 1)
        card = auto_attach.read_card(self.project, queue[0]["card_id"])
        self.assertEqual(card["files"], [f"pkg/mod_{i}.py" for i in range(20)])
        replay = desk_sync.on_hook(self.project, "codex", self._prompt_event("Fix pkg/mod_0.py", "e0"), session)
        self.assertFalse(replay)
        self.assertEqual(len(auto_attach.read_queue(self.project)), 1)

    def test_lock_timeout_fails_safe(self) -> None:
        session = str(uuid.uuid4())
        prompt = f"{DECLARE}. pkg/mod.py 수정해줘"

        @contextmanager
        def busy(_project):
            raise TimeoutError("auto_attach lock busy")
            yield  # pragma: no cover

        with self._spy() as spy:
            if sys.platform == "win32":  # the real lock, held by another handle, with a short bounded wait
                with auto_attach._lock(self.project), mock.patch.object(auto_attach, "LOCK_TIMEOUT_S", 0.05):
                    result = desk_sync.on_hook(self.project, "claude", self._prompt_event(prompt), session)
            else:  # fcntl.flock has no timeout; simulate the bounded wait's TimeoutError
                with mock.patch.object(auto_attach, "_lock", busy):
                    result = desk_sync.on_hook(self.project, "claude", self._prompt_event(prompt), session)
        self.assertTrue(result)
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(auto_attach.read_queue(self.project), [])
        desk = json.loads((self.project / ".coord" / "presence" / "user_desk_claude.json").read_text(encoding="utf-8"))
        self.assertEqual(desk["thread"], session)

    def test_crash_mid_hook_fails_safe_preserves_bool(self) -> None:
        session = str(uuid.uuid4())
        with mock.patch.object(auto_attach, "hook_on_prompt", side_effect=RuntimeError("torn")) as boom:
            self.assertTrue(desk_sync.on_hook(self.project, "codex", self._prompt_event(DECLARE), session))
            self.assertFalse(desk_sync.on_hook(self.project, "codex", self._prompt_event(WORK), str(uuid.uuid4())))
            self.assertTrue(desk_sync.on_hook(self.project, "antigravity", self._agy_event([DECLARE]), ""))
        self.assertEqual(boom.call_count, 3)
        with mock.patch.object(auto_attach, "hook_on_prompt", side_effect=KeyError("x")):
            self.assertFalse(desk_sync.on_hook(self.project, "claude", self._prompt_event(WORK), ""))
        self.assertEqual(auto_attach.read_queue(self.project), [])

    def test_antigravity_duplicate_turn_idempotent(self) -> None:
        event = self._agy_event([WORK])
        det = hashlib.sha256(f"{self.conversation}\0{1}".encode("utf-8")).hexdigest()
        with self._spy() as spy:
            self.assertFalse(desk_sync.on_hook(self.project, "antigravity", event, ""))
            self.assertFalse(desk_sync.on_hook(self.project, "antigravity", event, ""))
            self.assertFalse(desk_sync.on_hook(self.project, "antigravity", dict(event, invocationNum=1), ""))
        self.assertEqual(spy.call_count, 2)
        for call in spy.call_args_list:
            self.assertEqual(call.args, (self.project, "antigravity", WORK))
            self.assertEqual(call.kwargs, {"session": self.conversation, "event_id": det})
        queue = auto_attach.read_queue(self.project)
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["event_id"], det)
        index = json.loads((self.project / ".coord" / "auto_attach" / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["events"], {f"antigravity:{det}": queue[0]["card_id"]})
        self.assertEqual(auto_attach.enqueue_from_prompt(self.project, "antigravity", WORK, session=self.conversation,
                                                         event_id=det)["action"], "DUPLICATE")
        nxt = self._agy_event([WORK, "Fix pkg/other.py"])
        self.assertFalse(desk_sync.on_hook(self.project, "antigravity", nxt, ""))
        queue = auto_attach.read_queue(self.project)
        self.assertEqual(len(queue), 1)
        self.assertEqual(auto_attach.read_card(self.project, queue[0]["card_id"])["files"],
                         ["pkg/mod.py", "pkg/other.py"])

    def test_worker_and_disabled_env_skipped(self) -> None:
        with mock.patch.dict(os.environ, {"UAOS_WORKER": "1"}):
            self.assertFalse(desk_sync.on_hook(self.project, "codex", self._prompt_event(WORK), str(uuid.uuid4())))
            with self._spy() as spy:
                self.assertFalse(desk_sync.on_hook(self.project, "antigravity", self._agy_event([WORK]), ""))
            spy.assert_not_called()
        self.assertFalse((self.project / ".coord" / "auto_attach" / "queue.json").exists())
        session = str(uuid.uuid4())
        with mock.patch.dict(os.environ, {"UAOS_AUTO_ATTACH": "0"}):
            self.assertTrue(desk_sync.on_hook(self.project, "claude",
                                              self._prompt_event(f"{DECLARE}. pkg/mod.py 수정해줘"), session))
            self.assertFalse(desk_sync.on_hook(self.project, "antigravity", self._agy_event([WORK]), ""))
        self.assertEqual(auto_attach.read_queue(self.project), [])

    def test_conductor_down_enqueued_in_fifo(self) -> None:
        self._presence({"codex": "ABSENT", "claude": "ACTIVE", "antigravity": "ACTIVE"})
        self.assertFalse(desk_sync.on_hook(self.project, "claude", self._prompt_event("Fix pkg/a.py"),
                                           str(uuid.uuid4())))
        self.assertFalse(desk_sync.on_hook(self.project, "antigravity", self._agy_event(["Fix pkg/b.py"]), ""))
        self.assertFalse(desk_sync.on_hook(self.project, "codex", self._prompt_event("Fix pkg/c.py"),
                                           str(uuid.uuid4())))
        queue = auto_attach.read_queue(self.project)
        self.assertEqual([i["owner"] for i in queue], ["claude", "antigravity", "codex"])
        self.assertEqual([i["files"] for i in queue], [["pkg/a.py"], ["pkg/b.py"], ["pkg/c.py"]])
        for item in queue:
            self.assertNotIn(item["owner"], item["peers"])
            self.assertEqual(item["state"], "PENDING")

    def test_user_absent_empty_or_system_prompt_skipped(self) -> None:
        session = str(uuid.uuid4())
        with self._spy() as spy:
            for prompt in ("", "   ", "<system-reminder>Fix pkg/mod.py</system-reminder>", "ACK_ONLY fix it",
                           "hello there"):
                self.assertFalse(desk_sync.on_hook(self.project, "claude", self._prompt_event(prompt), session))
            for prompt in (None, 42, {"text": WORK}):
                self.assertFalse(desk_sync.on_hook(self.project, "codex", self._prompt_event(prompt), session))
            self.assertFalse(desk_sync.on_hook(self.project, "antigravity", self._agy_event(["   "]), ""))
            self.transcript.write_text("", encoding="utf-8")
            self.assertFalse(desk_sync.on_hook(self.project, "antigravity",
                                               {"invocationNum": 0, "transcriptPath": str(self.transcript),
                                                "conversationId": self.conversation}, ""))
        self.assertEqual(spy.call_count, 5)
        self.assertEqual(auto_attach.read_queue(self.project), [])


if __name__ == "__main__":
    unittest.main()
