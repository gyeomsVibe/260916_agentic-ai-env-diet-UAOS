```contract
work_id: U134-F1
worker: apply
apply_after: U134-L6
goal: thread identity and canonical project workspace verification for Codex rollout discovery (U134-R F1)
inputs:
- tests/test_u134_thread_fallback.py sha256=a272923674c458ba9e06fc364f3c69b0276c5415006d931ddab2f005e597d944
- tests/test_u134_judge_counterexamples.py sha256=019608228ca494af4c798d735c066bf6a182401ef5b338d8f7f3dbf265d52ad3
allow:
- v7_harness/coord/deliver.py
acceptance: python -m unittest tests.test_u134_thread_fallback tests.test_u134_judge_counterexamples
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 900
remote_budget_tokens: 0
```

## Work Order: U134-R F1 Thread Identity & Project Verification

Approved spec: U134-R_F1_spec.md (SHA256 285a2bd72ed4f55a745245ea75dd0a6fd7c33676ec5f91eaf7946baf1fa5235c).
Scope: v7_harness/coord/deliver.py only (_codex_thread and call sites). notify.py is untouched.
Frozen acceptance: tests/test_u134_thread_fallback.py (SHA256 a272923674c458ba9e06fc364f3c69b0276c5415006d931ddab2f005e597d944).
Supplemental judge gate: tests/test_u134_judge_counterexamples.py (SHA256 019608228ca494af4c798d735c066bf6a182401ef5b338d8f7f3dbf265d52ad3).

===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
def _codex_thread(desk: Path, thread: str) -> tuple[str, dict[str, str]]:
    """U134-D (2026-10-03): `--thread handoff-20261003`, a free-text name, failed `No active session found`.

    A thread is live when a Codex rollout file carries its id; otherwise the newest rollout of this project is used
    and the fallback is returned for the receipt. With no project thread the given value is kept (no worse than
    before). An empty thread resolves exactly as before, now from the same sessions folder.
    """
    from v7_harness.coord.notify import resolve_thread
    root = _codex_sessions()
    # Codex thread ids are UUIDs; the bound keeps any other text out of the glob pattern.
    if thread and re.fullmatch(r"[0-9A-Za-z-]{8,64}", thread) and any(root.glob(f"*/*/*/rollout-*-{thread}.jsonl")):
        return thread, {}
    newest = resolve_thread(desk, sessions_dir=root)
    if not thread:
        return newest, {}
    if newest and newest != thread:
        return newest, {"given": thread, "used": newest}
    return thread, {}
=======
META_LINE_MAX = 256 * 1024
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _read_rollout_meta(path: Path) -> tuple[str, Path | None, str]:
    """Read session_id and canonical cwd from rollout file metadata.

    U134-R F1:
    - Bounded read (max 256 KiB bytes).
    - Requires type == 'session_meta' (rejects event_msg).
    - Every present id key (id, session_id) must be a non-empty string; at least one present; all equal.
    - Strict UUID format check and filename suffix check.
    - Returns (chosen_id, canonical_cwd, status).
    """
    try:
        with path.open("rb") as handle:
            raw_line = handle.readline(META_LINE_MAX + 1)
            if not raw_line or len(raw_line) > META_LINE_MAX:
                return "", None, "THREAD_UNVERIFIED"
            line = raw_line.decode("utf-8", errors="replace")
            data = json.loads(line)
    except (OSError, json.JSONDecodeError):
        return "", None, "THREAD_UNVERIFIED"
    if not isinstance(data, dict) or data.get("type") != "session_meta":
        return "", None, "THREAD_UNVERIFIED"
    payload = data.get("payload")
    if not isinstance(payload, dict):
        return "", None, "THREAD_UNVERIFIED"

    present_ids: list[str] = []
    for key in ("id", "session_id"):
        if key in payload:
            val = payload[key]
            if not isinstance(val, str) or not val.strip():
                return "", None, "THREAD_UNVERIFIED"
            present_ids.append(val.strip())

    if not present_ids:
        return "", None, "THREAD_UNVERIFIED"

    first = present_ids[0]
    if any(pid.lower() != first.lower() for pid in present_ids):
        return "", None, "THREAD_UNVERIFIED"

    chosen_id = first
    if not UUID_RE.fullmatch(chosen_id):
        return "", None, "THREAD_UNVERIFIED"
    if not path.name.lower().endswith(f"-{chosen_id.lower()}.jsonl"):
        return "", None, "THREAD_UNVERIFIED"
    cwd_str = payload.get("cwd")
    cwd = Path(cwd_str).resolve() if cwd_str else None
    return chosen_id, cwd, "OK"


def _registered_roots(project: Path) -> set[str]:
    """Return canonical checkouts belonging to this repository, including git worktrees.

    U134-R F1:
    - Resolves linked worktree back to main repository without subprocess.
    - Resolves <main>/.git/worktrees/*/gitdir and verifies back-pointers.
    - Normalizes paths with os.path.normcase(str(p)).
    """
    project_res = project.resolve()
    main_repo = project_res
    git_entry = project_res / ".git"

    if git_entry.is_file():
        try:
            content = git_entry.read_text(encoding="utf-8").strip()
            if content.startswith("gitdir:"):
                raw_target = content[7:].strip()
                gitdir_path = Path(raw_target)
                if not gitdir_path.is_absolute():
                    gitdir_path = (project_res / gitdir_path).resolve()
                else:
                    gitdir_path = gitdir_path.resolve()
                if "worktrees" in gitdir_path.parts:
                    p = gitdir_path
                    while p.name != ".git" and p.parent != p:
                        p = p.parent
                    if p.name == ".git":
                        main_repo = p.parent.resolve()
        except OSError:
            pass

    roots = {os.path.normcase(str(project_res)), os.path.normcase(str(main_repo))}
    worktrees_dir = main_repo / ".git" / "worktrees"
    if worktrees_dir.is_dir():
        try:
            for entry in worktrees_dir.iterdir():
                if entry.is_dir():
                    gitdir_file = entry / "gitdir"
                    if gitdir_file.is_file():
                        try:
                            target = gitdir_file.read_text(encoding="utf-8").strip()
                            tpath = Path(target)
                            if not tpath.is_absolute():
                                tpath = (entry / tpath).resolve()
                            else:
                                tpath = tpath.resolve()
                            wt_dir = tpath.parent if tpath.name == ".git" else tpath
                            wt_git = wt_dir / ".git"
                            if wt_git.is_file():
                                back_content = wt_git.read_text(encoding="utf-8").strip()
                                if back_content.startswith("gitdir:"):
                                    bpath = Path(back_content[7:].strip())
                                    if not bpath.is_absolute():
                                        bpath = (wt_dir / bpath).resolve()
                                    else:
                                        bpath = bpath.resolve()
                                    if os.path.normcase(str(bpath)) == os.path.normcase(str(entry.resolve())):
                                        roots.add(os.path.normcase(str(wt_dir.resolve())))
                            elif wt_dir.resolve() == main_repo.resolve():
                                roots.add(os.path.normcase(str(wt_dir.resolve())))
                        except OSError:
                            pass
        except OSError:
            pass

    return roots


def _newest_verified_thread(desk: Path, sessions_dir: Path, exclude_threads: set[str] = ()) -> str:
    """Discover the newest verified thread for this project from up to 12 recent rollouts."""
    if not sessions_dir.is_dir():
        return ""
    reg_roots = _registered_roots(desk)
    candidates = sorted(sessions_dir.glob("*/*/*/rollout-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates[:12]:
        chosen_id, cwd, status = _read_rollout_meta(path)
        if status == "OK" and chosen_id not in exclude_threads:
            if cwd and os.path.normcase(str(cwd.resolve())) in reg_roots:
                return chosen_id
    return ""


def _codex_thread(desk: Path, thread: str) -> tuple[str, dict[str, str], str]:
    """U134-D / U134-R F1: Resolve Codex thread with strict identity and workspace verification.

    Returns (chosen_thread, fallback_dict, status).
    Status is 'DISPATCH' on success, or 'THREAD_UNVERIFIED', 'THREAD_PROJECT_MISMATCH', 'NO_VERIFIED_THREAD'.
    """
    root = _codex_sessions()
    if not thread:
        newest = _newest_verified_thread(desk, root)
        if newest:
            return newest, {}, "DISPATCH"
        return "", {}, "NO_VERIFIED_THREAD"

    if not UUID_RE.fullmatch(thread):
        newest = _newest_verified_thread(desk, root)
        if newest:
            return newest, {"given": thread, "used": newest, "why": "not_uuid"}, "DISPATCH"
        return "", {}, "NO_VERIFIED_THREAD"

    matched = list(root.glob(f"*/*/*/rollout-*-{thread}.jsonl"))
    if not matched:
        newest = _newest_verified_thread(desk, root)
        if newest:
            return newest, {"given": thread, "used": newest, "why": "no_rollout"}, "DISPATCH"
        return "", {}, "NO_VERIFIED_THREAD"

    reg_roots = _registered_roots(desk)
    for mf in matched:
        cid, cwd, status = _read_rollout_meta(mf)
        if status != "OK":
            return "", {}, "THREAD_UNVERIFIED"
        if not cwd or os.path.normcase(str(cwd.resolve())) not in reg_roots:
            return "", {}, "THREAD_PROJECT_MISMATCH"
        return thread, {}, "DISPATCH"

    return "", {}, "THREAD_UNVERIFIED"
>>>>>>> REPLACE

===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
        if target == "codex":
            if window:  # U115: the card's own Codex thread replaces the default thread
                thread = window
            thread, fallback = _codex_thread(desk, thread)  # U134-D: a dead or free-text thread falls back
            result = (_deliver_to_codex(envelope, thread, runner=runner) if thread else
                      DeliverResult(False, "codex", "NO_THREAD", (), ""))
=======
        if target == "codex":
            if window:  # U115: the card's own Codex thread replaces the default thread
                thread = window
            chosen_thread, fallback, status = _codex_thread(desk, thread)
            if status != "DISPATCH":
                result = DeliverResult(False, "codex", status, (), "")
            else:
                result = _deliver_to_codex(envelope, chosen_thread, runner=runner)
                # Rule 6: retry once on rc != 0 with newest verified thread other than failed one
                if not result.delivered and result.reason.startswith("DELIVERY_FAILED:rc="):
                    alt_thread = _newest_verified_thread(desk, _codex_sessions(), exclude_threads={chosen_thread})
                    if alt_thread:
                        fallback = {"given": chosen_thread, "used": alt_thread, "why": "send_failed"}
                        result = _deliver_to_codex(envelope, alt_thread, runner=runner)
>>>>>>> REPLACE

