"""Npcap detection and best-effort in-app installer.

Per-device hotspot usage capture needs the Npcap driver. Because Npcap's free
licence restricts *redistributing* the installer, we don't bundle it — we
download the official installer from npcap.com at runtime (exactly what a user
would do by hand) and run it.

The install is silent and deliberately passes ``/dot11_support=no`` so it can't
enable the "raw 802.11 / monitor mode" option, which is known to break the
Windows Mobile Hotspot.
"""
from __future__ import annotations

import ctypes
import os
import shutil
import tempfile
import urllib.request
from ctypes import wintypes
from pathlib import Path
from typing import Callable

# Pinned official installer. If this URL ever 404s, the UI falls back to opening
# the download page in the browser.
NPCAP_VERSION = "1.79"
NPCAP_URL = f"https://npcap.com/dist/npcap-{NPCAP_VERSION}.exe"
NPCAP_PAGE = "https://npcap.com/#download"

# Silent-install flags: no WinPcap-compat, keep loopback, and crucially NO raw
# 802.11 support (that option breaks Mobile Hotspot).
_INSTALL_ARGS = "/S /loopback_support=yes /dot11_support=no /winpcap_mode=no"


def npcap_installed() -> bool:
    """True if Npcap's driver DLLs are present on this system."""
    root = os.environ.get("SystemRoot", r"C:\Windows")
    sys32 = Path(root) / "System32"
    return (sys32 / "Npcap" / "wpcap.dll").exists() or (sys32 / "wpcap.dll").exists()


def _run_elevated_wait(exe: str, params: str) -> int | None:
    """Launch `exe` elevated (triggers UAC if needed) and wait for it.

    Returns the process exit code, or None if the elevation was cancelled/failed.
    """
    SEE_MASK_NOCLOSEPROCESS = 0x00000040
    SW_HIDE = 0

    class SHELLEXECUTEINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", ctypes.c_ulong),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIcon", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    sei = SHELLEXECUTEINFO()
    sei.cbSize = ctypes.sizeof(sei)
    sei.fMask = SEE_MASK_NOCLOSEPROCESS
    sei.lpVerb = "runas"
    sei.lpFile = exe
    sei.lpParameters = params
    sei.nShow = SW_HIDE
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)):
        return None
    handle = sei.hProcess
    if not handle:
        return None
    ctypes.windll.kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
    code = wintypes.DWORD()
    ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(handle)
    return code.value


def install(status: Callable[[str], None]) -> tuple[bool, str]:
    """Download and silently install Npcap. Returns (ok, user-facing message).

    `status` is called with short progress strings; run this off the UI thread.
    """
    try:
        status("Downloading Npcap from npcap.com …")
        dest = Path(tempfile.gettempdir()) / f"npcap-{NPCAP_VERSION}.exe"
        req = urllib.request.Request(NPCAP_URL, headers={"User-Agent": "Kresge"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as fh:
            shutil.copyfileobj(resp, fh)
    except Exception as exc:
        return False, f"Couldn't download Npcap ({exc}). Opening the download page instead."

    status("Installing Npcap — approve the Windows security prompt if it appears …")
    code = _run_elevated_wait(str(dest), _INSTALL_ARGS)
    if code is None:
        return False, "Npcap installation was cancelled or blocked by Windows."
    if code != 0:
        return False, f"The Npcap installer exited with code {code}."
    if not npcap_installed():
        return False, "Npcap did not install correctly. Try installing it manually."
    return True, "Npcap installed. Restart Kresge to enable per-device usage capture."
