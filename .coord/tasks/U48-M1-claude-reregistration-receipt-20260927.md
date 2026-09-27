# U48-M1 — Claude re-registration receipt (2026-09-27 16:22–16:25)

Actor: Claude (acting conductor while Codex is LIMITED; manual `U48_CLAUDE_ACTING_COMPLETION_MANUAL_20260927.md`).
This receipt is evidence for Codex's re-review, not a verdict.

## What changed

- **Backups first:** `~/.uaos-backups/m1_20260927_162231/`
  - `codex_config.toml` (8707 B)
  - `claude.json` (128561 B)
  - `antigravity_mcp_config.json` (26 B)
- **Target runtime:** `C:\Users\Kimyoongyeom\.uaos\runtime\0.3.2-ad721a2fc713`, the verified immutable runtime; `current.json` names it.
- **Codex:** in `~/.codex/config.toml`, `[mcp_servers.olla.env] PYTHONPATH` changed from `runtime\0.3.2` to `runtime\0.3.2-ad721a2fc713`.
  - Nothing else in the file changed.
  - `tomllib` parse confirms the new value.
  - `codex mcp get olla` reports enabled, stdio.
- **Claude:** ran `claude mcp remove olla -s user`, then `claude mcp add olla -s user -e PYTHONPATH=… -e PYTHONIOENCODING=utf-8 -- C:\Python314\python.exe -m v7_harness.olla_mcp`.
  - `claude mcp get olla` reports Connected with the new PYTHONPATH.
  - **Incident:** the first `add-json` attempt was rejected ("Invalid input"), so Claude had no `olla` registration for about 1 minute until the `add` command succeeded.
- **Antigravity:** `~/.gemini/antigravity/mcp_config.json` held `{"mcpServers": {}}` with no `olla` entry.
  - Claude added `olla` with the same command, PYTHONPATH and UTF-8 settings.
  - `agy mcp list` reports `olla stdio enabled`.
  - Earlier PLAN text said "Agy list enabled", but this file had no entry. Where that listing came from is UNKNOWN.

## Evidence

- **Handshake:** `C:/Python314/python.exe .work/u48m1/handshake.py <runtime>` sends `initialize` then `tools/list` over stdio, with PYTHONPATH set to the runtime only.
  - Result: exit 0.
  - Tools: `local_read_map`, `local_draft`, `local_search`.
  - Module loaded from `…\runtime\0.3.2-ad721a2fc713\v7_harness\olla_mcp.py`.
  - stderr was empty.
- **Fresh-session canaries** (a new Claude, Codex or Antigravity session listing and calling an `olla` tool): UNKNOWN.
  - No session has opened naturally since the change.
  - Per the manual, no paid call is made only to produce this evidence.

## Rollback

Copy the three backup files back to their original paths.
