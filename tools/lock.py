"""Pult's requirements with hashes (review 2026-10-27, Б8; Q91): requirements.txt and relay/requirements.txt are made
from requirements.in and relay/requirements.in — every package pinned, with the hashes of the files PyPI has for it, for
every system and Python Pult runs on (macOS, Linux, Windows; 3.10 and newer): pip installs only those files. The relay's
take the computer's versions for what both use — the tests install both into one environment. Versions already in the
files stay as they are unless --upgrade.

  python3 tools/lock.py [--upgrade]     needs uv (pip install uv) and PyPI; then python3 tools/consistency.py
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLDEST = "3.10"          # the oldest Python Pult runs on (install.sh, install.ps1, deploy/relay/install.sh)


def uv():
    found = shutil.which("uv")
    if found:
        return [found]
    try:
        import uv as _uv  # noqa: F401  (the pip package)
    except ImportError:
        sys.exit("uv is needed: pip install uv")
    return [sys.executable, "-m", "uv"]


def lock(src, out, *extra):
    cmd = uv() + ["pip", "compile", "--universal", "--generate-hashes", "--python-version", OLDEST, "--no-progress",
                  "--custom-compile-command", "python3 tools/lock.py", *extra, src, "-o", out]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr or r.stdout)


if __name__ == "__main__":
    up = ["--upgrade"] if "--upgrade" in sys.argv[1:] else []
    lock("requirements.in", "requirements.txt", *up)
    lock("relay/requirements.in", "relay/requirements.txt", "-c", "requirements.txt", *up)
    print("requirements.txt and relay/requirements.txt are made — check them: python3 tools/consistency.py")
