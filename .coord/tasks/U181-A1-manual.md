```contract
work_id: U181-A1
worker: apply
apply_after: U181-L1
goal: U181 boot task definition, plan and launcher for the sentinel (registers nothing)
inputs:
- v7_harness/cli.py sha256=ba6a3660e735f412c9e98acf91a72f6ea81c83c80d700294b1123dd9d1b5af12
allow:
- v7_harness/coord/boot_task.py
- v7_harness/cli.py
context_allow:
- v7_harness/cli.py
acceptance: python -m unittest tests.test_u181_boot_task tests.test_u180s_pid_reuse tests.test_u180s_lifetime_lease tests.test_u180s_cli_lease tests.test_u37_install_everywhere
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push; running schtasks
stop: two failures with the same cause; input hash mismatch; no output
judge: antigravity
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Card U181 (master schedule phase U180S-BOOT). The Ollama run U181-L1 failed with PROVIDER_ERROR. Dictation: write the
one new file and copy the two edit blocks below exactly. Change nothing else.

Design (Antigravity frame .work/cards/U181_frame.md: BootTrigger + S4U + LeastPrivilege), with two corrections by the
acting conductor: (1) the module lives in v7_harness because the installed runtime ships only v7_harness, so a task
that runs ~/.uaos/uaos.py can reach nothing in uaos_everywhere; (2) one action, not one per project: Task Scheduler
runs actions one after another and a `--loop` never returns, so a second project would never start.

===FILE: v7_harness/coord/boot_task.py===
"""U181: boot-time sentinel supervision — a Task Scheduler definition and the launcher it starts.

Nothing here registers, elevates or deletes. `plan` writes one XML file under ~/.uaos/boot and returns the commands
the user runs once from an elevated prompt (a BootTrigger needs an administrator token). The task runs `launch`,
which starts one sentinel loop per project; each loop takes the U180S lifetime lease, so the boot task and the logon
launcher can both fire and only one loop per project runs.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape

NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
TASK_NAME = "UAOS\\Sentinel-Boot"
BOOT_DELAY = "PT30S"  # the profile volume and the scheduler service settle before the first cycle
RESTART_INTERVAL = "PT1M"  # the shortest restart interval Task Scheduler accepts
RESTART_COUNT = 3  # a broken runtime must not restart for ever
INTERVAL_S = 60  # the interval the logon launcher (global_install sentinel_*.cmd) already uses
LEASE_BUSY = 3  # cmd_coord_sentinel: another launcher already supervises this project
ORDER = ("RegistrationInfo", "Triggers", "Principals", "Settings", "Actions")  # the schema's required sequence
PROJECT = re.compile(r'--project "([^"]+)"')


def task_xml(user: str, python: str, launcher: str) -> str:
    """One action only: Task Scheduler runs actions in sequence and a loop never returns."""
    arguments = escape(f'"{launcher}" coord boot --launch')
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="{NS}">
  <RegistrationInfo>
    <Description>UAOS sentinel supervision from system boot. Local checks only, no model calls.</Description>
  </RegistrationInfo>
  <Triggers>
    <BootTrigger>
      <Enabled>true</Enabled>
      <Delay>{BOOT_DELAY}</Delay>
    </BootTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user)}</UserId>
      <LogonType>S4U</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure>
      <Interval>{RESTART_INTERVAL}</Interval>
      <Count>{RESTART_COUNT}</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(python)}</Command>
      <Arguments>{arguments}</Arguments>
    </Exec>
  </Actions>
</Task>
"""


def validate(text: str) -> list[str]:
    """Problems that make the definition unsafe to register; empty when it is safe."""
    body = text.split("?>", 1)[1] if text.lstrip().startswith("<?xml") and "?>" in text else text
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        return [f"NOT_XML:{exc}"]
    tag = "{" + NS + "}"
    if root.tag != tag + "Task":
        return ["NOT_A_TASK"]
    problems = []
    if tuple(child.tag.removeprefix(tag) for child in root) != ORDER:
        problems.append("ELEMENT_ORDER")
    if len(root.findall(f".//{tag}Triggers/*")) != 1 or len(root.findall(f".//{tag}BootTrigger")) != 1:
        problems.append("NOT_ONE_BOOT_TRIGGER")
    for name, wanted in (("LogonType", "S4U"), ("RunLevel", "LeastPrivilege"), ("MultipleInstancesPolicy", "IgnoreNew")):
        if [node.text for node in root.findall(f".//{tag}{name}")] != [wanted]:
            problems.append(f"{name.upper()}_NOT_{wanted.upper()}")
    actions = root.findall(f".//{tag}Actions/*")
    if len(actions) != 1 or actions[0].tag != tag + "Exec":
        problems.append("NOT_ONE_EXEC")
    if any("--ring" in (node.text or "") for node in root.findall(f".//{tag}Arguments")):
        problems.append("RING_BEFORE_LOGON")
    return problems


def projects(home) -> list[str]:
    """Projects that already have a logon launcher: global_install wrote one sentinel_*.cmd for each."""
    seen, kept = set(), []
    for cmd in sorted((Path(home) / ".uaos").glob("sentinel_*.cmd")):
        found = PROJECT.search(cmd.read_text(encoding="utf-8", errors="replace"))
        if not found or not Path(found.group(1)).is_dir():
            continue
        key = os.path.normcase(os.path.abspath(found.group(1)))
        if key not in seen:
            seen.add(key)
            kept.append(str(Path(found.group(1))))
    return kept


def plan(home, user: str | None = None, python: str | None = None) -> dict:
    """Write the definition and return the commands for the user; registers nothing."""
    home = Path(home)
    user = user or f"{os.environ.get('USERDOMAIN', '.')}\\{os.environ.get('USERNAME', '')}"
    python = python or str(Path(sys.executable).with_name("pythonw.exe"))
    text = task_xml(user, python, str(home / ".uaos" / "uaos.py"))
    problems = validate(text)
    path = home / ".uaos" / "boot" / "UAOS-Sentinel-Boot.xml"
    if not problems:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-16")
    return {"ok": not problems, "problems": problems, "registered": False, "xml": str(path),
            "projects": projects(home),
            "register": f'schtasks /Create /TN "{TASK_NAME}" /XML "{path}"',
            "uninstall": f'schtasks /Delete /TN "{TASK_NAME}" /F',
            "needs": "an elevated prompt (administrator token); the user runs it once"}


def launch(home, python: str | None = None) -> int:
    """Start one sentinel loop per project and wait: 0 when every loop ended cleanly or was already supervised."""
    home = Path(home)
    children = []
    for root in projects(home):
        log = Path(root) / ".work" / "sentinel" / "sentinel.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        children.append(subprocess.Popen(
            [python or sys.executable, str(home / ".uaos" / "uaos.py"), "coord", "sentinel", "--project", root,
             "--loop", "--interval", str(INTERVAL_S), "--write-brief", "--log", str(log)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    if sys.stdout is not None:  # pythonw has no console
        print(json.dumps({"ok": True, "children": [child.pid for child in children]}), flush=True)
    codes = [child.wait() for child in children]
    return 0 if all(code in (0, LEASE_BUSY) for code in codes) else 1

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
def cmd_coord_sentinel(args: argparse.Namespace) -> int:
    """U180S: every launcher kind holds one OS lease for the whole synchronous command."""
=======
def cmd_coord_boot(args: argparse.Namespace) -> int:
    """U181: print the boot task plan (registers nothing) or run the launcher the task starts."""
    from .coord import boot_task
    home = Path(args.home) if args.home else Path.home()
    if args.launch:
        return boot_task.launch(home)
    result = boot_task.plan(home)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


def cmd_coord_sentinel(args: argparse.Namespace) -> int:
    """U180S: every launcher kind holds one OS lease for the whole synchronous command."""
>>>>>>> REPLACE

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
    p_coord_sentinel.set_defaults(func=cmd_coord_sentinel)
=======
    p_coord_sentinel.set_defaults(func=cmd_coord_sentinel)
    p_coord_boot = p_coord_subs.add_parser("boot", help="U181: boot task plan (registers nothing) or its launcher")
    p_coord_boot.add_argument("--home", default=None, help="Home that holds .uaos (default: the user's)")
    p_coord_boot.add_argument("--launch", action="store_true", help="Start one sentinel loop per project and wait")
    p_coord_boot.set_defaults(func=cmd_coord_boot)
>>>>>>> REPLACE

## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
