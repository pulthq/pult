"""Pult: what depends on the operating system, in one place. Standard library only.

Today Pult runs on macOS; Linux and Windows are being ported (stage K). Each function answers for the system it runs
on and says "don't know" (None) rather than fail, so the rest of Pult keeps working where an answer is missing.
"""
import re
import subprocess
import sys

KIND = "mac" if sys.platform == "darwin" else "windows" if sys.platform == "win32" else "linux"


def input_idle():
    """Seconds since the last keyboard or mouse input on this computer, or None when the system can't tell
    (not supported here yet, a server without a screen, a remote session)."""
    if KIND != "mac":
        return None
    try:
        out = subprocess.run(["ioreg", "-c", "IOHIDSystem", "-d", "4", "-r", "-k", "HIDIdleTime"],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', out)
    return int(m.group(1)) / 1e9 if m else None
