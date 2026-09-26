"""U42 fixed acceptance: evidence-backed RSI may prepare a release, but cannot self-adopt or ship without proof."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness import rsi_release


APPROVAL_TEXT = (
    "이 요청은 이 U42 범위의 전역 규칙 배포, 브랜치 생성, 커밋, 원격 푸시, PR 생성에 대한 명시적 승인이다. "
    "삭제·결제·계정/자격증명 변경은 금지한다."
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _receipt(name: str, runner: str) -> dict:
    return {
        "name": name,
        "command": f"python -m unittest {name}",
        "exit_code": 0,
        "passed": 3,
        "fixed_sha256": _sha(name),
        "runner": runner,
    }


def _packet() -> dict:
    sources = []
    for kind, url in (
        ("official_docs", "https://learn.chatgpt.com/docs/agent-configuration/agents-md"),
        ("paper", "https://arxiv.org/abs/2609.26457"),
        ("github", "https://github.com/akaszubski/autonomous-dev"),
        ("reddit", "https://www.reddit.com/r/developersIndia/comments/example"),
    ):
        snapshot = f"{kind}:{url}"
        sources.append({
            "kind": kind,
            "url": url,
            "title": kind,
            "published_at": "2026-09-25",
            "fetched_at": "2026-09-25T12:00:00Z",
            "snapshot": snapshot,
            "snapshot_sha256": _sha(snapshot),
            "apply": "Use one bounded property.",
            "do_not_apply": "Do not treat this single source as a verdict.",
        })
    return {
        "schema": "uaos-rsi-release-v1",
        "work_id": "U42",
        "proposal_id": "evidence-to-pr",
        "title": "근거에서 PR까지",
        "summary": "검증된 근거만 버전된 PR 후보로 만든다.",
        "author": "codex",
        "verifier": "antigravity",
        "judge": "user",
        "change_type": "feature",
        "base_branch": "main",
        "branch": "codex/u42-rsi-research-pr",
        "version_file": "uaos_everywhere/VERSION",
        "update_documents": ["README.md", "uaos_everywhere/README.md"],
        "changed_files": ["v7_harness/rsi_release.py", "uaos_everywhere/uaos_global_rule_block.md"],
        "sources": sources,
        "acceptance": _receipt("acceptance", "codex"),
        "holdout": _receipt("holdout", "antigravity"),
        "red_team": _receipt("red_team", "antigravity"),
        "usage": {"remote_budget_tokens": 100000, "actual_tokens": 5000, "wall_seconds": 30, "failures": []},
        "rollback": "Revert the release commit; never use rsi rollback to write policy.",
        "risks": ["External sources can drift after their snapshot."],
    }


def _approval() -> dict:
    return {
        "schema": "uaos-approval-v1",
        "work_id": "U42",
        "approval_text": APPROVAL_TEXT,
        "approval_sha256": _sha(APPROVAL_TEXT),
        "allowed_actions": ["global_rule_deploy", "branch_create", "commit", "push", "pull_request_create"],
        "forbidden_actions": ["delete_data", "spend_money", "change_account", "change_credentials", "auto_merge"],
    }


class EvidenceTests(unittest.TestCase):
    def test_valid_packet_has_stable_fingerprint(self) -> None:
        packet = _packet()
        self.assertEqual([], rsi_release.validate_packet(packet))
        self.assertEqual(rsi_release.packet_fingerprint(packet), rsi_release.packet_fingerprint(json.loads(json.dumps(packet))))

    def test_source_snapshot_hash_and_duplicate_research_fail_closed(self) -> None:
        packet = _packet()
        packet["sources"][0]["snapshot_sha256"] = "0" * 64
        packet["sources"].append(dict(packet["sources"][1]))
        problems = rsi_release.validate_packet(packet)
        self.assertTrue(any(x.startswith("SOURCE_HASH_MISMATCH") for x in problems), problems)
        self.assertTrue(any(x.startswith("DUPLICATE_SOURCE") for x in problems), problems)
        fp = rsi_release.packet_fingerprint(_packet())
        self.assertEqual(["DUPLICATE_PROPOSAL:" + fp], rsi_release.duplicate_problems(_packet(), [{"fingerprint": fp}]))

    def test_acceptance_holdout_red_team_and_independent_roles_are_mandatory(self) -> None:
        packet = _packet()
        packet["holdout"]["exit_code"] = 1
        packet["red_team"].pop("fixed_sha256")
        packet["judge"] = packet["author"]
        problems = rsi_release.validate_packet(packet)
        self.assertIn("HOLDOUT_NOT_PASS", problems)
        self.assertIn("RED_TEAM_FIXED_HASH_MISSING", problems)
        self.assertIn("JUDGE_NOT_INDEPENDENT", problems)

    def test_evaluators_usage_ledger_and_rsi_core_cannot_be_release_targets(self) -> None:
        for path in ("tests/test_u42_rsi_release.py", ".coord/usage/runs.jsonl", "v7_harness/rsi.py"):
            packet = _packet()
            packet["changed_files"].append(path)
            self.assertIn("PROTECTED_PATH:" + path, rsi_release.validate_packet(packet))

    def test_usage_budget_and_failures_are_evidence_not_optional_metadata(self) -> None:
        packet = _packet()
        packet["usage"] = {"remote_budget_tokens": 100, "actual_tokens": 101, "wall_seconds": None, "failures": ["TIMEOUT"]}
        problems = rsi_release.validate_packet(packet)
        self.assertIn("REMOTE_BUDGET_EXCEEDED", problems)
        self.assertIn("WALL_TIME_UNKNOWN", problems)


class VersionAndDocumentTests(unittest.TestCase):
    def test_semver_bump_is_deterministic(self) -> None:
        self.assertEqual("1.2.4", rsi_release.bump_version("1.2.3", "fix"))
        self.assertEqual("1.3.0", rsi_release.bump_version("1.2.3", "feature"))
        self.assertEqual("2.0.0", rsi_release.bump_version("1.2.3", "breaking"))
        with self.assertRaises(ValueError):
            rsi_release.bump_version("1.2", "feature")

    def test_top_update_section_is_idempotent_and_user_visible(self) -> None:
        original = "# Project\n\nIntro.\n"
        once = rsi_release.render_top_update(original, version="1.1.0", date="2026-09-25", summary="Added gates.", fingerprint="abc")
        twice = rsi_release.render_top_update(once, version="1.1.0", date="2026-09-25", summary="Added gates.", fingerprint="abc")
        self.assertEqual(once, twice)
        self.assertLess(once.index("## 업데이트"), once.index("Intro."))
        self.assertEqual(1, once.count("<!-- uaos-update:abc -->"))

    def test_prepare_defaults_to_dry_run_and_writes_only_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "README.md").write_text("# Root\n\nIntro\n", encoding="utf-8")
            (root / "uaos_everywhere").mkdir()
            (root / "uaos_everywhere" / "README.md").write_text("# UAOS\n\nIntro\n", encoding="utf-8")
            packet = _packet()
            plan = rsi_release.prepare_release(root, packet, apply=False, date="2026-09-25")
            self.assertEqual("0.1.0", plan["next_version"])
            self.assertFalse((root / "uaos_everywhere" / "VERSION").exists())
            rsi_release.prepare_release(root, packet, apply=True, date="2026-09-25")
            self.assertEqual("0.1.0\n", (root / "uaos_everywhere" / "VERSION").read_text(encoding="utf-8"))
            self.assertIn("## 업데이트", (root / "README.md").read_text(encoding="utf-8"))


class ApprovalAndShippingTests(unittest.TestCase):
    def test_approval_is_bound_to_text_hash_work_and_exact_actions(self) -> None:
        self.assertEqual([], rsi_release.validate_approval(_approval(), work_id="U42"))
        bad = _approval()
        bad["approval_text"] += " changed"
        bad["allowed_actions"].remove("push")
        problems = rsi_release.validate_approval(bad, work_id="U42")
        self.assertIn("APPROVAL_HASH_MISMATCH", problems)
        self.assertIn("APPROVAL_ACTION_MISSING:push", problems)

    def test_shipping_fetches_before_commit_push_and_pr_but_never_merges(self) -> None:
        packet = _packet()
        calls = []

        def run(command, **kwargs):
            calls.append(list(command))
            if command[:2] == ["git", "status"]:
                return subprocess.CompletedProcess(command, 0, "", "")
            if command[:3] == ["git", "rev-parse", "HEAD"]:
                return subprocess.CompletedProcess(command, 0, "a" * 40 + "\n", "")
            if command[:3] == ["git", "ls-remote", "origin"]:
                return subprocess.CompletedProcess(command, 0, "a" * 40 + "\trefs/heads/codex/u42-rsi-research-pr\n", "")
            if command[:3] == ["gh", "pr", "view"]:
                return subprocess.CompletedProcess(command, 0, '{"url":"https://github.com/o/r/pull/1","state":"OPEN"}', "")
            return subprocess.CompletedProcess(command, 0, "", "")

        result = rsi_release.ship_release(Path("."), packet, _approval(), execute=True, run=run)
        flat = [" ".join(c) for c in calls]
        self.assertLess(flat.index("git fetch origin main"), next(i for i, x in enumerate(flat) if x.startswith("git commit")))
        self.assertLess(next(i for i, x in enumerate(flat) if x.startswith("git commit")), next(i for i, x in enumerate(flat) if x.startswith("git push")))
        self.assertTrue(any(x.startswith("gh pr create") for x in flat), flat)
        self.assertFalse(any(" merge" in " " + x for x in flat), flat)
        self.assertEqual("OPEN", result["pr"]["state"])
        self.assertEqual("a" * 40, result["remote_sha"])

    def test_shipping_is_dry_run_by_default_and_stops_on_dirty_unexpected_path(self) -> None:
        dry = rsi_release.ship_release(Path("."), _packet(), _approval())
        self.assertEqual("DRY_RUN", dry["status"])
        self.assertTrue(all(isinstance(command, list) for command in dry["commands"]))

        def dirty(command, **kwargs):
            if command[:2] == ["git", "status"]:
                return subprocess.CompletedProcess(command, 0, " M secrets.txt\n", "")
            return subprocess.CompletedProcess(command, 0, "", "")

        with self.assertRaisesRegex(rsi_release.ReleaseRefused, "UNEXPECTED_DIRTY_PATH"):
            rsi_release.ship_release(Path("."), _packet(), _approval(), execute=True, run=dirty)


class SchedulerTests(unittest.TestCase):
    def _config(self) -> dict:
        return {
            "interval_seconds": 86400,
            "timeout_seconds": 15,
            "max_retries": 3,
            "backoff_base_seconds": 60,
            "sources": [{"url": "https://example.test/source", "version": "1"}],
        }

    def _observation(self, content: str = "v1", **overrides) -> dict:
        value = {
            "url": "https://example.test/source",
            "version": "1",
            "etag": '"one"',
            "last_modified": "Thu, 25 Sep 2026 00:00:00 GMT",
            "content_sha256": _sha(content),
        }
        value.update(overrides)
        return value

    def test_no_change_is_quiet_and_one_content_change_triggers_once(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            current = self._observation()
            calls = []

            def fetch(source, timeout):
                self.assertEqual(15, timeout)
                return dict(current)

            baseline = rsi_release.run_scheduler_cycle(root, self._config(), fetch=fetch, trigger=calls.append, now=1000)
            self.assertEqual("ACK_ONLY", baseline["status"])
            self.assertEqual([], calls)
            unchanged = rsi_release.run_scheduler_cycle(root, self._config(), fetch=fetch, trigger=calls.append, now=2000)
            self.assertEqual("ACK_ONLY", unchanged["status"])
            self.assertEqual([], calls)
            current.update(self._observation("v2", version="2", etag='"two"'))
            changed = rsi_release.run_scheduler_cycle(root, self._config(), fetch=fetch, trigger=calls.append, now=3000)
            self.assertEqual("ACTIONABLE_DELTA", changed["status"])
            self.assertEqual(1, len(calls))
            repeated = rsi_release.run_scheduler_cycle(root, self._config(), fetch=fetch, trigger=calls.append, now=4000)
            self.assertEqual("ACK_ONLY", repeated["status"])
            self.assertEqual(1, len(calls))

    def test_etag_or_date_only_change_is_not_actionable(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            first = self._observation()
            rsi_release.run_scheduler_cycle(root, self._config(), fetch=lambda *_: dict(first), trigger=lambda _: None, now=1)
            metadata_only = self._observation(etag='"new"', last_modified="Fri, 26 Sep 2026 00:00:00 GMT")
            calls = []
            result = rsi_release.run_scheduler_cycle(root, self._config(), fetch=lambda *_: metadata_only,
                                                     trigger=calls.append, now=2)
            self.assertEqual("ACK_ONLY", result["status"])
            self.assertEqual([], calls)

    def test_existing_lock_allows_one_owner_only(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            lock = root / ".work" / "rsi-scheduler.lock"
            lock.parent.mkdir(parents=True)
            lock.write_text('{"pid": 123, "started_at": 1000}', encoding="utf-8")
            calls = []
            result = rsi_release.run_scheduler_cycle(root, self._config(), fetch=lambda *_: self._observation(),
                                                     trigger=calls.append, now=1001)
            self.assertEqual("LOCKED", result["status"])
            self.assertEqual([], calls)

    def test_network_failure_has_bounded_exponential_backoff_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            attempts = []

            def fail(source, timeout):
                attempts.append((source["url"], timeout))
                raise OSError("offline")

            result = rsi_release.run_scheduler_cycle(Path(d), self._config(), fetch=fail, trigger=lambda _: None,
                                                     now=1000)
            self.assertEqual("FAILED", result["status"])
            self.assertEqual(3, len(attempts))
            self.assertEqual([60, 120, 240], result["backoff_seconds"])
            self.assertEqual(1240, result["next_run_at"])
            self.assertEqual("OSError: offline", result["failure_receipt"]["error"])

    def test_windows_schedule_is_dry_run_by_default_and_supports_install_status_remove(self) -> None:
        calls = []

        def run(command, **kwargs):
            calls.append(list(command))
            return subprocess.CompletedProcess(command, 0, "SUCCESS", "")

        project = Path(r"C:\Work\UAOS")
        preview = rsi_release.windows_schedule(project, "python.exe", action="install", run=run)
        self.assertEqual("DRY_RUN", preview["status"])
        self.assertEqual([], calls)
        installed = rsi_release.windows_schedule(project, "python.exe", action="install", apply=True, run=run)
        status = rsi_release.windows_schedule(project, "python.exe", action="status", apply=True, run=run)
        removed = rsi_release.windows_schedule(project, "python.exe", action="remove", apply=True, run=run)
        self.assertTrue(installed["ok"] and status["ok"] and removed["ok"])
        self.assertEqual(["schtasks", "/Create"], calls[0][:2])
        self.assertEqual(["schtasks", "/Query"], calls[1][:2])
        self.assertEqual(["schtasks", "/Delete"], calls[2][:2])
        self.assertIn("rsi watch", " ".join(calls[0]))


if __name__ == "__main__":
    unittest.main()
