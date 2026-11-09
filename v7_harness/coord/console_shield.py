"""UAOS WinEvent Console Shield Daemon (U287-SHIELD)
Intercepts any ConsoleWindowClass window creation and immediately hides it (SW_HIDE)
before it can paint or flash on screen. Consoles retain 100% of their functionality and pipes.
"""

import ctypes
import ctypes.wintypes
import os
import sys
import time

EVENT_OBJECT_SHOW = 0x8002
EVENT_OBJECT_CREATE = 0x8000
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002
SW_HIDE = 0

user32 = ctypes.windll.user32
ole32 = ctypes.windll.ole32

WinEventProcType = ctypes.WINFUNCTYPE(
    None,
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.DWORD,
    ctypes.wintypes.HWND,
    ctypes.wintypes.LONG,
    ctypes.wintypes.LONG,
    ctypes.wintypes.DWORD,
    ctypes.wintypes.DWORD,
)

def is_background_console(hwnd: int) -> bool:
    class_buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, class_buf, 256)
    cls = class_buf.value
    if cls != "ConsoleWindowClass":
        return False
        
    title_buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, title_buf, 512)
    title = title_buf.value.lower()
    
    # Hide any conhost created by cmd.exe, git, python, node, npx, or default path
    auto_patterns = ["cmd.exe", "system32\\cmd.exe", "python", "git", "npx", "node", "ollama", "mcp", "select"]
    if any(p in title for p in auto_patterns) or not title.strip():
        return True
    return False

def win_event_handler(hWinEventHook, event, hwnd, idObject, idChild, dwEventThread, dwmsEventTime):
    if idObject == 0 and hwnd:  # OBJID_WINDOW
        try:
            if is_background_console(hwnd):
                user32.ShowWindow(hwnd, SW_HIDE)
        except Exception:
            pass

def sweep_existing():
    """Hide any background consoles that are already currently visible."""
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and is_background_console(hwnd):
            user32.ShowWindow(hwnd, SW_HIDE)
        return True
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(cb), 0)

def main():
    ole32.CoInitialize(0)
    sweep_existing()
    
    proc_delegate = WinEventProcType(win_event_handler)
    flags = WINEVENT_OUTOFCONTEXT
    
    hook_show = user32.SetWinEventHook(
        EVENT_OBJECT_SHOW, EVENT_OBJECT_SHOW, 0, proc_delegate, 0, 0, flags
    )
    hook_create = user32.SetWinEventHook(
        EVENT_OBJECT_CREATE, EVENT_OBJECT_CREATE, 0, proc_delegate, 0, 0, flags
    )
    
    # Periodic sweep timer via standard Windows message pump
    user32.SetTimer(0, 0, 500, None)
    
    msg = ctypes.wintypes.MSG()
    try:
        while user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) > 0:
            if msg.message == 0x0113:  # WM_TIMER
                sweep_existing()
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
    finally:
        user32.UnhookWinEvent(hook_show)
        user32.UnhookWinEvent(hook_create)
        ole32.CoUninitialize()

if __name__ == "__main__":
    main()
