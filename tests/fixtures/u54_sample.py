"""U54 fixture: three execution sites the audit must classify exactly GUARDED, GAP and FIXED. Never imported."""

import subprocess

ALLOWED = ("git", "python")


def check_allowed(command):
    if command[0] not in ALLOWED:
        raise PermissionError(command[0])


def guarded(tool_calls):
    command = [tool_calls[0]["function"]["name"]]
    check_allowed(command)
    return subprocess.run(command, check=False)


def unguarded(tool_calls):
    command = tool_calls[0]["function"]["arguments"]
    return subprocess.run(command, shell=True, check=False)


def constant():
    return subprocess.run(["git", "status", "--short"], check=False)
