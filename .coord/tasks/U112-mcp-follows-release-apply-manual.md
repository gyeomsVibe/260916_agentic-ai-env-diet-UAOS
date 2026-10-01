```contract
work_id: U112
worker: apply
goal: The olla MCP entry of Claude, Codex and Antigravity loads the olla release the installer keeps current
inputs:
- v7_harness/global_install.py sha256=e5463397ba552fd630b63ab7b24531ad461dea0bf371bdbe816767b53217660d
- tests/test_u112_mcp_follows_release.py sha256=76b89876d5e2d9dac0a93cc43960f0e58fb44d655a5cc9d0e1db6edbee21a954
allow:
- v7_harness/global_install.py
acceptance: python -m unittest tests.test_u112_mcp_follows_release tests.test_u111_olla_release_sync tests.test_u37_install_everywhere
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the block below exactly.

===EDIT: v7_harness/global_install.py===
<<<<<<< SEARCH
            if change.action != "UNCHANGED":
                changes.append(change)
    return changes
=======
            if change.action != "UNCHANGED":
                changes.append(change)
        # U112: all three tools' olla MCP servers ran a runtime pinned by hand on 09-27 (U48-M1) while the hooks moved
        # on; existing entries now load the same release. Forward slashes: valid in TOML literals, JSON and PYTHONPATH.
        for target, path, pattern in MCP_ENTRIES:
            earlier = next((c for c in changes if c.path == home / path and c.new_text is not None), None)
            before = earlier.new_text if earlier else _read(home / path)
            after = re.sub(pattern, lambda m: m.group(1) + Path(olla_release).as_posix() + m.group(2), before or "",
                           count=1)
            if before and after != before:
                if earlier is not None:  # one file, one write: e.g. config.toml also gets the hooks feature line
                    earlier.new_text = after
                else:
                    changes.append(_text_change(target, home / path, before, after))
    return changes


MCP_ENTRIES = (
    ("claude mcp", ".claude.json", r'("olla"\s*:\s*\{[^{}]*"env"\s*:\s*\{[^{}]*?"PYTHONPATH"\s*:\s*")[^"]*(")'),
    ("codex mcp", ".codex/config.toml", r"(\[mcp_servers\.olla\.env\][^\[]*?PYTHONPATH\s*=\s*')[^'\n]*(')"),
    ("antigravity mcp", ".gemini/antigravity/mcp_config.json",
     r'("olla"\s*:\s*\{[^{}]*"env"\s*:\s*\{[^{}]*?"PYTHONPATH"\s*:\s*")[^"]*(")'))
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
