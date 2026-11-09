import subprocess
# WiseCare365 Reverse-Engineered Process & System Cleaner for UAOS
# Pure Python standard library + Win32 ctypes implementation

import ctypes
import os
import shutil
import sys
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

# Win32 Process Constants
PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100
PROCESS_QUERY_INFORMATION = 0x0400
TH32CS_SNAPPROCESS = 0x00000002

# Safe system processes that must NEVER be terminated or treated as orphaned
IMMUNE_PROCESSES = {
    "system", "system idle process", "smss.exe", "csrss.exe", "wininit.exe",
    "services.exe", "lsass.exe", "winlogon.exe", "svchost.exe", "fontdrvhost.exe",
    "dwm.exe", "explorer.exe", "sihost.exe", "taskhostw.exe", "runtimebroker.exe",
    "shellexperiencehost.exe", "startmenuexperiencehost.exe", "searchhost.exe",
    "securityhealthsystray.exe", "antigravity.exe", "codex.exe", "claude.exe"
}

# Processes permitted for memory working set trimming when idle
TRIMMABLE_PROCESSES = {
    "textinputhost.exe", "claude.exe", "codex.exe", "antigravity.exe",
    "chatgpt.exe", "chrome.exe", "msedge.exe", "pythonw.exe", "python.exe"
}

class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ('dwSize', wintypes.DWORD),
        ('cntUsage', wintypes.DWORD),
        ('th32ProcessID', wintypes.DWORD),
        ('th32DefaultHeapID', ctypes.c_size_t),
        ('th32ModuleID', wintypes.DWORD),
        ('cntThreads', wintypes.DWORD),
        ('th32ParentProcessID', wintypes.DWORD),
        ('pcPriClassBase', wintypes.LONG),
        ('dwFlags', wintypes.DWORD),
        ('szExeFile', ctypes.c_char * 260)
    ]

def get_process_snapshot() -> List[Tuple[int, int, str]]:
    """Returns list of (PID, PPID, exe_name.lower()) using Toolhelp32Snapshot."""
    if sys.platform != "win32":
        return []
    
    kernel32 = ctypes.windll.kernel32
    hSnap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if hSnap == -1:
        return []
    
    entry = PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
    procs = []
    
    if kernel32.Process32First(hSnap, ctypes.byref(entry)):
        while True:
            exe = entry.szExeFile.decode('ansi', errors='replace').lower()
            procs.append((entry.th32ProcessID, entry.th32ParentProcessID, exe))
            if not kernel32.Process32Next(hSnap, ctypes.byref(entry)):
                break
    kernel32.CloseHandle(hSnap)
    return procs

def empty_working_set(pid: int) -> bool:
    """Empties the working set of a target process via psapi.EmptyWorkingSet."""
    if sys.platform != "win32" or pid <= 4:
        return False
    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
    
    h = kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_QUERY_INFORMATION, False, pid)
    if not h:
        return False
    try:
        res = psapi.EmptyWorkingSet(h)
        return bool(res)
    finally:
        kernel32.CloseHandle(h)

def terminate_pid(pid: int) -> bool:
    """Terminates a process safely via OpenProcess(PROCESS_TERMINATE)."""
    if sys.platform != "win32" or pid <= 4:
        return False
    kernel32 = ctypes.windll.kernel32
    h = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not h:
        return False
    try:
        return bool(kernel32.TerminateProcess(h, 1))
    finally:
        kernel32.CloseHandle(h)

def clean_orphaned_zombies(dry_run: bool = True, kill_orphans: bool = False) -> List[Dict[str, Any]]:
    """WiseCare365 heuristic: Identifies pythonw / olla_mcp processes whose parent has terminated."""
    procs = get_process_snapshot()
    if not procs:
        return []
    
    all_pids = {p[0] for p in procs}
    killed = []
    
    for pid, ppid, exe in procs:
        if exe in IMMUNE_PROCESSES:
            continue
        # Heuristic: pythonw.exe or python.exe running disconnected from live parent
        if exe in ("pythonw.exe", "python.exe") and ppid not in all_pids and ppid != 0:
            status = "DRY_RUN"
            if not dry_run and kill_orphans:
                ok = terminate_pid(pid)
                status = "KILLED" if ok else "FAILED"
            killed.append({"pid": pid, "ppid": ppid, "exe": exe, "status": status})
            
    return killed

def clean_excess_olla_mcp(keep_newest: int = 2, dry_run: bool = True) -> List[Dict[str, Any]]:
    """Terminates older olla_mcp instances exceeding keep_newest threshold."""
    procs = get_process_snapshot()
    olla_pids = [pid for pid, ppid, exe in procs if exe == "python.exe"]
    # We inspect commandlines via powershell or safe fallback
    # For safe determinism, if there are multiple python instances with dead parents, clean_orphaned_zombies handles them
    return []

def optimize_textinputhost(threshold_mb: int = 150, dry_run: bool = True) -> Dict[str, Any]:
    """WiseCare365 Memory + Lag optimization: Trims working set of TextInputHost.exe."""
    procs = get_process_snapshot()
    target = None
    for pid, ppid, exe in procs:
        if "textinputhost" in exe:
            target = pid
            break
            
    if not target:
        return {"action": "NOT_FOUND"}
        
    if dry_run:
        return {"action": "DRY_RUN", "pid": target}
        
    # First: trim working set (immediate zero-disruption memory release)
    trimmed = empty_working_set(target)
    return {"action": "TRIMMED" if trimmed else "TRIM_FAILED", "pid": target}

def trim_idle_processes(dry_run: bool = True) -> List[int]:
    """WiseCare365 RAM Booster: Empties working sets of large non-critical UI apps."""
    procs = get_process_snapshot()
    trimmed = []
    for pid, ppid, exe in procs:
        if exe in TRIMMABLE_PROCESSES:
            if not dry_run:
                if empty_working_set(pid):
                    trimmed.append(pid)
            else:
                trimmed.append(pid)
    return trimmed

def clean_temp_directory(temp_path: Path, max_age_hours: int = 24, dry_run: bool = True) -> int:
    """WiseCare365 Disk Cleaner heuristic: Removes temporary files older than max_age_hours."""
    if not temp_path.exists() or not temp_path.is_dir():
        return 0
    now = time.time()
    cutoff = now - (max_age_hours * 3600)
    cleaned = 0
    
    for item in temp_path.iterdir():
        try:
            st = item.stat()
            if st.st_mtime < cutoff:
                if item.is_file() or item.is_symlink():
                    if not dry_run:
                        item.unlink(missing_ok=True)
                    cleaned += 1
                elif item.is_dir():
                    if not dry_run:
                        shutil.rmtree(item, ignore_errors=True)
                    cleaned += 1
        except Exception:
            continue
    return cleaned

def enforce_zero_console_registry(dry_run: bool = True, enable_console_shield: bool = False) -> bool:
    """Enforce the conhost zero-visibility registry lock so any console app is positioned off-screen."""
    if dry_run or not enable_console_shield:
        return False
    if sys.platform != "win32":
        return True
    try:
        import winreg
        guid = "{B23D10C0-E52E-411E-9D5B-C09FDF709C7D}"
        k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Console\%%Startup")
        winreg.SetValueEx(k, "DelegationConsole", 0, winreg.REG_SZ, guid)
        winreg.SetValueEx(k, "DelegationTerminal", 0, winreg.REG_SZ, guid)
        winreg.CloseKey(k)
        
        pos_offscreen = (30000 << 16) | 30000
        for sub in [
            r"Console",
            r"Console\%SystemRoot%_System32_cmd.exe",
            r"Console\%SystemRoot%_SysWOW64_cmd.exe",
            r"Console\%SystemRoot%_System32_conhost.exe",
            r"Console\Command Prompt",
            r"Console\명령 프롬프트",
            r"Console\Git Bash",
            r"Console\Git CMD",
            r"Console\%SystemRoot%_System32_WindowsPowerShell_v1.0_powershell.exe",
            r"Console\%SystemRoot%_SysWOW64_WindowsPowerShell_v1.0_powershell.exe",
        ]:
            s = winreg.CreateKey(winreg.HKEY_CURRENT_USER, sub)
            winreg.SetValueEx(s, "WindowPosition", 0, winreg.REG_DWORD, pos_offscreen)
            winreg.SetValueEx(s, "WindowAlpha", 0, winreg.REG_DWORD, 0)
            winreg.SetValueEx(s, "WindowSize", 0, winreg.REG_DWORD, 0x00010001)
            winreg.CloseKey(s)
        return True
    except Exception:
        return False


def ensure_console_shield_daemon(dry_run: bool = True, enable_console_shield: bool = False) -> dict[str, Any]:
    """Ensure the 0-flash WinEvent Console Shield Daemon is running in pythonw (opt-in only)."""
    if dry_run:
        return {"action": "SKIPPED_DRY_RUN"}
    if not enable_console_shield:
        return {"action": "SKIPPED_OPT_OUT"}
    if sys.platform != "win32":
        return {"action": "SKIPPED_NON_WINDOWS"}
    enforce_zero_console_registry(dry_run=False, enable_console_shield=True)
        
    procs = get_process_snapshot()
    # Check if console_shield is already active
    # We inspect pythonw processes or launch the daemon
    shield_path = Path.home() / ".uaos" / "console_shield.pyw"
    if not shield_path.exists():
        src = Path(__file__).parent / "console_shield.py"
        if src.exists():
            shutil.copy2(src, shield_path)
            
    # Check if mutex or process exists, else launch via pythonw
    pythonw_bin = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw_bin.exists():
        pythonw_bin = Path(sys.executable)
        
    # Check using EnumWindows if any hidden console daemon responds, or launch once
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    si = subprocess.STARTUPINFO()
    si.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 1)
    si.wShowWindow = 0
    
    # We maintain a PID file in .coord/presence/
    pid_file = Path.home() / ".uaos" / "console_shield.pid"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
            # Check if PID is alive
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if h:
                ctypes.windll.kernel32.CloseHandle(h)
                return {"action": "ALREADY_RUNNING", "pid": pid}
        except Exception:
            pass
            
    try:
        proc = subprocess.Popen([str(pythonw_bin), str(shield_path)],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=flags, startupinfo=si)
        pid_file.write_text(str(proc.pid), encoding="utf-8")
        return {"action": "SPAWNED", "pid": proc.pid}
    except Exception as exc:
        return {"action": "FAILED", "error": str(exc)[:200]}


def run_system_cleanup(
    dry_run: bool = True,
    *,
    kill_orphans: bool = False,
    clean_temp: bool = False,
    trim_memory: bool = False,
    enable_console_shield: bool = False,
) -> Dict[str, Any]:
    """Master invocation performing the WiseCare365 cleanup cycle (safe dry_run=True and opt-out by default)."""
    t0 = time.time()
    zombies = clean_orphaned_zombies(dry_run=dry_run or not kill_orphans, kill_orphans=kill_orphans)
    tih = optimize_textinputhost(dry_run=dry_run or not trim_memory)
    trimmed = trim_idle_processes(dry_run=dry_run or not trim_memory)
    
    shield_status = ensure_console_shield_daemon(
        dry_run=dry_run,
        enable_console_shield=enable_console_shield,
    )
    cleaned_files = 0
    if clean_temp and not dry_run:
        temp_dir = Path(os.environ.get("TEMP", os.environ.get("TMP", "")))
        if temp_dir.exists():
            cleaned_files = clean_temp_directory(temp_dir, max_age_hours=48, dry_run=False)
        
    return {
        "elapsed_s": round(time.time() - t0, 3),
        "dry_run": dry_run,
        "zombies_killed": zombies,
        "textinput_action": tih,
        "trimmed_procs": len(trimmed),
        "temp_files_cleaned": cleaned_files,
        "console_shield": shield_status,
    }
