# U245~U253 DESK-261026-3 Independent Counterexample Repair Evidence

- **Worktree**: `.work/wt_u241_control_ux` (branch `agy/u245-rea-failover-closeout`, base `05d4c32`)
- **Reply to**: Codex `relay_a64574ac44175d9b81e7660dbb36165b` (`DESK-261026-3-INDEPENDENT-REWORK.md`) & Claude `relay_f352756c0d5f84eb21be4737391cc8f3`
- **Primary Sources**:
  - https://zdnet.co.kr/view/?no=20261019165618
  - https://github.com/morluto/rea
  - https://github.com/N0zoM1z0/dx-ball
  - https://github.com/SmartManoj/openrig
  - https://github.com/Showgn/agentic-ai-orchestration-platform
  - https://github.com/gyeomsVibe/260916_agentic-ai-env-diet/pull/216

## 1. Counterexample Repairs Applied
1. **U253 (`v7_harness/coord/deliver.py`)**: Restricted `is already in use` ephemeral `--session-id` retry to unbound/general deliveries (`if rc != 0 and resume and not session and ...`). Explicit card receiver (`session='U253-bound'`) fails closed (`delivered=False`, `reason='DELIVERY_FAILED:rc=1'`). Verified by `.work/desk_261026_3/u253_audit/binding_gate.py --source .work/wt_u241_control_ux -v` -> **Ran 1 test in 0.019s, OK (exit 0)**.
2. **U245 (`v7_harness/evidence_ledger.py`)**: Wrapped the on-disk CAS check + write in `update_unknown` under `_exclusive(self.ledger_dir / '.ledger.lock')`, re-reading `unknowns_path` inside the lock so two processes synchronized at `_read_json` yield **exactly 1 `RESOLVED` (rev 2) and 1 `STALE_REVISION`**.
3. **U246 (`v7_harness/analysis_view.py`)**: Tightened `absence_established` to `bool(len(filtered) == 0 and safe_offset == 0 and source_complete)` so an out-of-range `offset=999` on a non-empty source reports `absence_established: false`.
4. **U248 (`v7_harness/process_supervisor.py`)**:
   - `verify_reconstruction`: Requires explicit `obs.get('byte_or_behavior_match') is True` (missing key now returns `verdict='FAILED'`, `reason='ORACLE_MISMATCH'`).
   - `terminate_with_finalization`: Sets `killed = bool(any_delivered and exited)` so denied `SIGTERM`/`SIGKILL` with no observed exit returns `killed: false, exit_code: null`.
5. **U249 (`v7_harness/coord/failover_closeout.py`, `v7_harness/coord/stop_gate.py`)**: Preserved all 5 Claude review fixes (sole-survivor `REVIEW` never self-approves to `DONE`, `_exclusive` lock on `master_schedule.json`, `stop_gate.py` logs `FAILOVER_ERROR`).

## 2. File SHA256 Digests (`.work/wt_u241_control_ux`)
- `v7_harness/coord/deliver.py`: `f7b0bcf98e9c8a654e4dcf4326381f1b926bb5fd16511820bf711c4004406a79`
- `v7_harness/coord/watch.py`: `c1be9282ccaf11c3a1052d70b14685f91d81cfe1f649c22fee414d559e7309ae`
- `v7_harness/coord/stall.py`: `e97fe4ca081f0424643fc992f0bbb8093ff3b01645dede8f6331b04329869170`
- `v7_harness/coord/failover_closeout.py`: `4eb54cc28e48593b4df896c56d5723cac5fd3275987bf5b203e2dbb9da017489`
- `v7_harness/coord/stop_gate.py`: `3b456e7bffbf2e7429c38d0ed4a27d027e126431062d2c98afd2d7da80cffc27`
- `v7_harness/evidence_ledger.py`: `08702c32a33169aa317e4bc8774afcb32963bc91f1765bddb572980b26dac6fa`
- `v7_harness/analysis_view.py`: `c7e345a2b783e07d0bb8181e24ee8cbc033fe39af8ddf66ccbf191323b2cba83`
- `v7_harness/process_supervisor.py`: `4d5df85d73b6d223e5cefdcfd60454c7b17a2059cb70db54d548effbc6aa4dfe`
- `v7_harness/cli.py`: `3915d131e4e1aa37ff301bcecdca7fce59f8f8f58e3bcda7793e515c49b5e23f`
- `tests/test_u253_zero_deadlock_watch_and_deliver.py`: `f57ac2196f61454c2116de90a854018b715ecbb05a4ed5d1629f4a6df5d913eb`
- `tests/test_u249_failover_preemption_closeout.py`: `9e150c12837bf593e57dd6ecf4aebe19dddc8a929ff626a17577403c35aaef78`
- `tests/test_u245_evidence_citation_gate.py`: `6b25db7dca75c05949b0886ae2a94878265e707ad9ad39ba49e899b7c7f8ebb8`
- `tests/test_u246_analysis_view.py`: `2b94590ba4b4d0fe395d567be87899eeec6a24755dd36b55f7f335adc8026fa1`
- `tests/test_u248_process_finalization.py`: `6dcdccac4e9efd5d1e5e88964c10fdbe6e4a5af4bc499aeb59ce35e685dff188`
