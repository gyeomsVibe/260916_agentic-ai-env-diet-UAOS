```contract
work_id: U125-L1
worker: local
goal: Each RSI cause names its own runs and a review letter can name its reader (U125 part 1, dictated)
inputs:
- v7_harness/rsi.py sha256=57c185772c514611e2bef3c73c59d9e90202ce2cf69661885f976825d265d1bf
allow:
- v7_harness/rsi.py
acceptance: python -m unittest tests.test_u125_rsi_review_wakes_conductor.EvidencePerCauseTest tests.test_u125_rsi_review_wakes_conductor.ReviewLetterTest tests.test_u36_evidence_gated_rsi tests.test_u73_session_usage tests.test_u74_closure
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

# Work order: each RSI cause names its own runs, and a review letter can name its reader (U125, part 1)

- Target file: `v7_harness/rsi.py`
- Anchors: `analyze`, `propose`, `rsi_review_messages`

Copy the five edit blocks below into the file exactly, in this order, in this same SEARCH/REPLACE format.
Do not rewrite whole functions. Change nothing else.

===EDIT: v7_harness/rsi.py===
<<<<<<< SEARCH
        causes = Counter(cause for cause in (_cause(row) for row in recent) if cause)
=======
        causes = Counter(cause for cause in (_cause(row) for row in recent) if cause)
        # U125: each cause names only the runs that carry it (a PASS run was evidence for UNREQUESTED_DELETION).
        cause_work_ids: dict[str, list[Any]] = {}
        for row in recent:
            cause = _cause(row)
            if cause:
                cause_work_ids.setdefault(cause, []).append(row.get("work_id"))
>>>>>>> REPLACE

===EDIT: v7_harness/rsi.py===
<<<<<<< SEARCH
            "recent_work_ids": [row.get("work_id") for row in recent][-5:],
=======
            "recent_work_ids": [row.get("work_id") for row in recent][-5:],
            "cause_work_ids": {cause: ids[-5:] for cause, ids in cause_work_ids.items()},
>>>>>>> REPLACE

===EDIT: v7_harness/rsi.py===
<<<<<<< SEARCH
                "action": action,
                "evidence": info["recent_work_ids"],
=======
                "action": action,
                "evidence": info["recent_work_ids"],
                # U125: the runs that carry this cause, for the review letter. `evidence` stays the window because
                # candidate_template turns it into the gate's before_work_ids (a failures-only baseline would pass
                # any candidate).
                "cause_evidence": info.get("cause_work_ids", {}).get(cause) or info["recent_work_ids"],
>>>>>>> REPLACE

===EDIT: v7_harness/rsi.py===
<<<<<<< SEARCH
    project: Path, analysis: dict[str, Any], policy: dict[str, Any] | None = None
) -> list[tuple[str, dict[str, Any]]]:
=======
    project: Path, analysis: dict[str, Any], policy: dict[str, Any] | None = None, target: str | None = None
) -> list[tuple[str, dict[str, Any]]]:
>>>>>>> REPLACE

===EDIT: v7_harness/rsi.py===
<<<<<<< SEARCH
        messages.append((message_id, {"kind": "RSI_REVIEW", "step": "RSI", "summary": summary[:200], "actor": "sentinel"}))
=======
        payload: dict[str, Any] = {"kind": "RSI_REVIEW", "step": "RSI", "summary": summary[:200], "actor": "sentinel"}
        if target:
            # U125: addressed to the acting conductor so its `coord watch --wakes-session` wakes and the recurring
            # causes become a card (15 unaddressed letters were never handled).
            payload["requested_target"] = target
            payload["proposals"] = [
                {**{key: proposal[key] for key in ("id", "cause", "target", "action")},
                 "evidence": proposal.get("cause_evidence", proposal["evidence"])}
                for proposal in propose(analysis, policy)
                if proposal["worker"] == worker and proposal["recurring"]
            ][:5]
        messages.append((message_id, payload))
>>>>>>> REPLACE


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
