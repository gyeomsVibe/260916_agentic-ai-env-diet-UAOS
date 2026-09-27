```contract
work_id: U47-A1
worker: apply
goal: When the agy judge answers with a quota error, keep agy's own error text in the judge record and mark Antigravity LIMITED on the presence desk until the reset it names; add the frozen test.
inputs:
- v7_harness/judge.py sha256=c79793c1dc69d3c5143026b3fb8ef853ae1a0c05f25624e66c83610edde9103c
allow:
- v7_harness/judge.py
- tests/test_u47_a1_agy_quota_presence.py
acceptance: python tests/u47_a1_check.py
forbidden: design changes; edits outside allow; editing or deleting other tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

===FILE: tests/test_u47_a1_agy_quota_presence.py===
"""U47-A1 frozen acceptance (written by Claude): an agy quota answer marks Antigravity LIMITED on the desk.

2026-09-27 01:5x: the desk read antigravity=ACTIVE (a session heartbeat), so the conductor mailed Antigravity a
verdict request and asked the user to relay it. The real call answered "RESOURCE_EXHAUSTED ... Resets in 162h49m0s",
but `pilot judge` kept only "JUDGE_FAILED:agy QUOTA" and left the desk ACTIVE. The provider's message must be kept
and the desk must read LIMITED until the reset, so routing stops sending work to a tool that cannot answer.
"""

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness import judge
from v7_harness.coord.presence import read

MANUAL = """```contract
work_id: T1
worker: apply
goal: g
allow:
- a.py
acceptance: python -c "pass"
judge: antigravity
remote_budget_tokens: 0
```
"""
QUOTA_MSG = ("API error (attempt 6): RESOURCE_EXHAUSTED (code 429): Individual quota reached. Please upgrade your "
             "subscription to increase your limits. Resets in 162h49m0s.")


class Done:
    def __init__(self, stdout=b"", returncode=0):
        self.stdout = stdout
        self.stderr = b""
        self.returncode = returncode


class AgyQuotaPresenceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.work, self.source, stage = root / "work", root / "src", root / "stage"
        self.project = root / "project"
        self.runs = self.work / "runs" / "T1"
        for folder in (self.runs, self.source, stage, self.project):
            folder.mkdir(parents=True)
        (self.source / "a.py").write_text("X = 1\n", encoding="utf-8")
        (stage / "a.py").write_text("X = 2\n", encoding="utf-8")
        (self.runs / "worker").write_text("apply", encoding="utf-8")
        (self.runs / "summary.json").write_text(json.dumps(
            {"agy_workspace": str(stage), "changed_files": ["a.py"], "bundle_id": "b1",
             "promotion": "DRY_RUN_PASSED", "acceptance_exit": 0}), encoding="utf-8")
        self.manual = root / "m.md"
        self.manual.write_text(MANUAL, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def run_with(self, error_text, status="ERROR"):
        envelope = {"conversation_id": "c1", "status": status, "response": "", "error": error_text}

        def runner(argv, **kwargs):
            return Done(json.dumps(envelope).encode("utf-8"))
        return judge.run_judge(task_id="T1", work_dir=self.work, source=self.source, manual_path=self.manual,
                               project=self.project, budget=10_000, runner=runner,
                               approver=lambda *a, **k: Done(), desk={"codex": {"state": "LIMITED"}})

    def test_quota_keeps_message_and_marks_limited_until_reset(self):
        record = self.run_with(QUOTA_MSG)
        self.assertEqual("UNUSABLE", record["verdict"])
        self.assertIn("Resets in 162h49m0s", record["provider_message"])
        self.assertEqual("LIMITED", record["presence_marked"])
        desk = read(self.project, "antigravity")
        self.assertEqual("LIMITED", desk["state"])
        ttl = desk["expires_at"] - json.loads((self.runs / "judge_agy.json").read_text(encoding="utf-8"))["marked_at"]
        self.assertAlmostEqual(162 * 3600 + 49 * 60, ttl, delta=5)

    def test_quota_without_reset_time_uses_one_hour(self):
        self.assertEqual(3600, judge.quota_ttl("429 RESOURCE_EXHAUSTED"))
        self.assertEqual(2 * 3600 + 5 * 60, judge.quota_ttl("Resets in 2h5m0s."))
        self.assertEqual(90, judge.quota_ttl("resets in 1m30s"))

    def test_other_failures_leave_the_desk_alone(self):
        record = self.run_with("503 no capacity")
        self.assertEqual("", record["presence_marked"])
        self.assertIn("no capacity", record["provider_message"])
        self.assertEqual("UNKNOWN", read(self.project, "antigravity")["state"])


if __name__ == "__main__":
    unittest.main()
===END===

===EDIT: v7_harness/judge.py===
<<<<<<< SEARCH
# Enough of the acceptance log to show the failing or passing summary without flooding the judge prompt.
ACCEPTANCE_TAIL_CHARS = 4_000
=======
# Enough of the acceptance log to show the failing or passing summary without flooding the judge prompt.
ACCEPTANCE_TAIL_CHARS = 4_000
# U47-A1: agy's quota answer names the wait ("Resets in 162h49m0s", 2026-09-27). The desk then reads LIMITED until the
# reset instead of a session heartbeat's ACTIVE, which had routed a verdict request to a tool that could not answer.
QUOTA_RESET_RE = re.compile(r"resets in\s*(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:(\d+)s)?", re.I)
# No reset time in the message: re-probe after an hour rather than guess a long outage.
QUOTA_FALLBACK_TTL_S = 3_600
# agy's error is one line (~170 chars with the reset time); 300 keeps it whole without storing a transcript.
PROVIDER_MESSAGE_CHARS = 300


def quota_ttl(message: str) -> int:
    """Seconds until agy's quota resets, read from its error text; one hour when the text names no time."""
    match = QUOTA_RESET_RE.search(message or "")
    if not match or not any(match.groups()):
        return QUOTA_FALLBACK_TTL_S
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return max(1, hours * 3600 + minutes * 60 + seconds)


def _provider_message(stdout: bytes) -> str:
    """agy's own error text from its JSON envelope, so a failed judgement says why (quota, auth, capacity)."""
    text = stdout.decode("utf-8", errors="replace")
    try:
        envelope = json.loads(text)
    except ValueError:
        return text[:PROVIDER_MESSAGE_CHARS]
    return str(envelope.get("error") or "")[:PROVIDER_MESSAGE_CHARS] if isinstance(envelope, dict) else ""
>>>>>>> REPLACE

===EDIT: v7_harness/judge.py===
<<<<<<< SEARCH
    error = ""
    envelope_sha = ""
=======
    error = ""
    envelope_sha = ""
    provider_message = ""
    presence_marked = ""
    marked_at = None
>>>>>>> REPLACE

===EDIT: v7_harness/judge.py===
<<<<<<< SEARCH
        else:
            error = f"JUDGE_FAILED:agy {outcome.error_class}"
=======
        else:
            error = f"JUDGE_FAILED:agy {outcome.error_class}"
            provider_message = _provider_message(stdout)
            if outcome.error_class == "QUOTA":
                from .coord.presence import mark

                marked_at = time.time()
                mark(Path(project or source).resolve(), JUDGE_TOOL[judge], "LIMITED",
                     ttl_s=quota_ttl(provider_message), now=marked_at)
                presence_marked = "LIMITED"
>>>>>>> REPLACE

===EDIT: v7_harness/judge.py===
<<<<<<< SEARCH
        "applied": False,
    }
=======
        "applied": False,
        "provider_message": provider_message, "presence_marked": presence_marked, "marked_at": marked_at,
    }
>>>>>>> REPLACE


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
