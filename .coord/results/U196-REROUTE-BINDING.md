# U196-REROUTE-BINDING — result
- Change: next_card._bound_here; a claim returns WAIT/WORKTREE_MISMATCH unless phase.worktree is the claimant's existing checkout (samefile); the claim lock also re-checks `worktree` (atomic reassignment refused). Phases without `worktree` unchanged.
- Bundle 38ccf4d0 (Codex apply4, APPLIED); staged next_card.py sha256 2e56491c… equals the bundle stage byte-for-byte (CR stripped).
- Verdicts: Codex judge 01a14388 APPROVE; Antigravity 5eaff82f PASS; combined audit relay_c34b1088 PASS; card audit U196 ok, missing [].
- Tests: Codex full pytest 2283 passed / 6 skipped exit 0; author focused set 89 passed exit 0 (.work/u196/accept_final.log).
- Receipt: .coord/reviews/U196-reviewed-release-policy-block-20261016.json. Scope: worktree substep only; native-identity scope not DONE.
