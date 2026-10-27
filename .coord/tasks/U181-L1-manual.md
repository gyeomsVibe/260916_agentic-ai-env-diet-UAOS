```contract
work_id: U181-L1
worker: local
goal: U181 boot task definition, plan and launcher for the sentinel (registers nothing)
inputs:
- tests/test_u181_boot_task.py sha256=4a4874da95f07f66987d3f1338e6cda0fedbe65b79c69a25e5d50e5b68a72366
allow:
- v7_harness/coord/boot_task.py
context_allow:
- tests/test_u181_boot_task.py
acceptance: python -m unittest tests.test_u181_boot_task.TaskXml tests.test_u181_boot_task.Plan.test_projects_come_from_installed_launchers_once_and_existing_only tests.test_u181_boot_task.Plan.test_plan_writes_one_file_and_registers_nothing
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push; running schtasks
stop: two failures with the same cause; input hash mismatch; no output
judge: antigravity
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Card U181. Write one new Python module, v7_harness/coord/boot_task.py, that the test file in your context imports as
`from v7_harness.coord import boot_task`. Standard library only. No function may start a process except `launch`.

Module constants: NS = "http://schemas.microsoft.com/windows/2004/02/mit/task", TASK_NAME = "UAOS\\Sentinel-Boot".

Functions:

1. task_xml(user, python, launcher) returns a Task Scheduler XML string, version 1.2, namespace NS, first line
   `<?xml version="1.0" encoding="UTF-16"?>`. Children of Task in this order: RegistrationInfo, Triggers, Principals,
   Settings, Actions. Triggers holds one BootTrigger with Enabled true and Delay PT30S. Principals holds one Principal
   id="Author" with UserId (the escaped user), LogonType S4U, RunLevel LeastPrivilege. Settings holds
   MultipleInstancesPolicy IgnoreNew, DisallowStartIfOnBatteries false, StopIfGoingOnBatteries false,
   ExecutionTimeLimit PT0S, and RestartOnFailure with Interval PT1M and Count 3. Actions Context="Author" holds exactly
   one Exec with Command (the escaped python) and Arguments `"<launcher>" coord boot --launch` (escaped). Escape text
   with xml.sax.saxutils.escape.
2. validate(text) returns a list of problem strings, empty when the definition is safe. Problems: not parseable XML;
   root is not {NS}Task; child order differs from the five names above; not exactly one BootTrigger; LogonType is not
   S4U; RunLevel is not LeastPrivilege; MultipleInstancesPolicy is not IgnoreNew; not exactly one Exec; Arguments
   contains --ring. Parse the text after the `?>` of the XML declaration when it has one.
3. projects(home) returns a list of project root strings: for every file matching sentinel_*.cmd in Path(home)/".uaos"
   (sorted by name) take the text after `--project "` up to the next `"`; keep only existing directories; drop
   duplicates (compare with os.path.normcase(os.path.abspath(root))); return str(Path(root)) values in first-seen
   order. A missing .uaos folder gives [].
4. plan(home, user=None, python=None) builds the XML with launcher str(Path(home)/".uaos"/"uaos.py"), validates it,
   and when there are no problems writes it to Path(home)/".uaos"/"boot"/"UAOS-Sentinel-Boot.xml" with
   encoding="utf-16". It returns a dict: ok (no problems), problems, registered False, xml (the path string),
   projects (projects(home)), register `schtasks /Create /TN "<TASK_NAME>" /XML "<xml path>"`, uninstall
   `schtasks /Delete /TN "<TASK_NAME>" /F`. Default user is USERDOMAIN\USERNAME from the environment; default python is
   pythonw.exe beside sys.executable.

## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
