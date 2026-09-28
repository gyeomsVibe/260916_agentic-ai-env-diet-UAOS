```contract
work_id: U82
worker: apply
goal: Remove the timing race in test_timeout_kills_worker_process_tree so the kill lands after the child exists.
inputs:
- .coord/PLAN.md sha256=efb91a4ff9f2b27a67d78c73c77fe64b74eaa0c5d8aa064f3d2ce0238236b561
- tests/test_u12_execution.py sha256=eacb0bad91f961bbcbf007348cca666c00f3bd6360c18e67b0411f80d8db9e7e
allow:
- tests/test_u12_execution.py
- .coord/PLAN.md
acceptance: python -m unittest tests.test_u12_execution
forbidden: design changes; edits outside allow; weakening or deleting existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the EDIT blocks exactly. The test is made stricter (explicit premise check), not weaker.

===EDIT: tests/test_u12_execution.py===
<<<<<<< SEARCH
        decision = MockSubprocessLauncher(default_timeout_sec=0.3).launch(
            attempt_id="tree-timeout",
            acceptance_hash=H,
            custom_script=parent_script,
            worker_capability="read_only",
        )
        self.assertEqual(decision.error_class, "TIMEOUT")
        child_pid = int(pid_file.read_text())

=======
        # U82: the kill must land after the child exists. Measured 2026-09-29 on 12 busy cores, the parent needs up to
        # 0.44 s (median 0.34) to start, spawn the child and write its pid; the old 0.3 s killed it first in 2 of 15
        # loaded runs (FileNotFoundError on child.pid). 3.0 s is about 7x that worst case; the parent then sleeps 30 s,
        # so the timeout still fires.
        decision = MockSubprocessLauncher(default_timeout_sec=3.0).launch(
            attempt_id="tree-timeout",
            acceptance_hash=H,
            custom_script=parent_script,
            worker_capability="read_only",
        )
        self.assertEqual(decision.error_class, "TIMEOUT")
        self.assertTrue(pid_file.is_file(), "the parent was killed before it spawned the child: premise not met")
        child_pid = int(pid_file.read_text())

>>>>>>> REPLACE
===EDIT: .coord/PLAN.md===
<<<<<<< SEARCH
| U81 | DONE-DELEGATED (Codex LIMITED 중 Claude 권한대행 2026-09-28 — Codex 복귀 시 재검토) | claude(대행 설계·판정) · apply(0토큰) | U80 반례 수정: apply 작업자의 결정적 거부(UNREQUESTED_DELETION)가 엔진에서 UNKNOWN_EFFECT_NEEDS_RECONCILIATION → 장부 PROVIDER_ERROR로 바뀌어 `rsi propose`가 Ollama 점검을 권했다. pilot은 작업자 봉투의 `error`를 error_detail에 보존하고, rsi는 일반 분류(PROVIDER_ERROR·EXECUTION_ERROR)일 때만 detail의 구체 원인을 택한다. — `tests/test_u81_apply_cause.py` |

=======
| U81 | DONE-DELEGATED (Codex LIMITED 중 Claude 권한대행 2026-09-28 — Codex 복귀 시 재검토) | claude(대행 설계·판정) · apply(0토큰) | U80 반례 수정: apply 작업자의 결정적 거부(UNREQUESTED_DELETION)가 엔진에서 UNKNOWN_EFFECT_NEEDS_RECONCILIATION → 장부 PROVIDER_ERROR로 바뀌어 `rsi propose`가 Ollama 점검을 권했다. pilot은 작업자 봉투의 `error`를 error_detail에 보존하고, rsi는 일반 분류(PROVIDER_ERROR·EXECUTION_ERROR)일 때만 detail의 구체 원인을 택한다. — `tests/test_u81_apply_cause.py` |
| U82 | DONE-DELEGATED (Codex LIMITED 중 Claude 권한대행 2026-09-29 — Codex 복귀 시 재검토) | claude(대행 설계·판정) · apply(0토큰) | 불안정 테스트 근본 수정: `test_timeout_kills_worker_process_tree`의 0.3초 제한이 부모 프로세스의 자식 생성·pid 기록(부하 시 최대 0.44초, 중앙 0.34초)보다 짧아, 자식이 생기기 전에 종료되어 child.pid가 없었다(12코어 부하 15회 중 2회 재현). 제한을 3.0초(최악의 약 7배)로 올리고 전제 미충족을 명시적으로 실패시킨다. — `tests/test_u12_execution.py` |

>>>>>>> REPLACE
===END===

## Output

- Reply with ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.
