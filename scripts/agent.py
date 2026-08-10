"""Install, remove, and inspect the launchd agent.

    .venv/bin/python scripts/agent.py install [--interval 3600]
    .venv/bin/python scripts/agent.py status
    .venv/bin/python scripts/agent.py uninstall

Interpreter choice matters (plan §13): TCC identity is inherited from the binary
named in ProgramArguments, and Homebrew's python3 symlinks into a version-stamped
Cellar path that changes on every patch bump, silently invalidating Full Disk
Access. This installs against the python.org framework build. A venv's bin/python
resolves to the base interpreter anyway.
"""

from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path

LABEL = "com.adamkuzee.composter"
PROJECT = Path(__file__).resolve().parents[1]
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOGDIR = Path.home() / "Library" / "Logs" / "composter"
FRAMEWORK_PY = Path("/Library/Frameworks/Python.framework/Versions/3.13/bin/python3")


def interpreter() -> Path:
    venv = PROJECT / ".venv" / "bin" / "python3"
    real = Path(os.path.realpath(venv)) if venv.exists() else None
    if real and "Frameworks/Python.framework" in str(real):
        return venv          # venv resolves to the framework build: fine
    if FRAMEWORK_PY.exists():
        return FRAMEWORK_PY
    print(f"WARNING: {FRAMEWORK_PY} not found; falling back to {sys.executable}.\n"
          "         A Homebrew interpreter will lose its Full Disk Access grant\n"
          "         on the next patch bump (plan §13, risk 5).", file=sys.stderr)
    return Path(sys.executable)


def build_plist(interval: int) -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": [str(interpreter()), "-m", "src.main", "all"],
        "WorkingDirectory": str(PROJECT),
        "EnvironmentVariables": {"PYTHONPATH": str(PROJECT)},
        "StartInterval": interval,
        "ThrottleInterval": 300,
        "RunAtLoad": True,
        "ProcessType": "Background",
        "LowPriorityIO": True,
        "Nice": 5,
        "StandardOutPath": str(LOGDIR / "composter.out.log"),
        "StandardErrorPath": str(LOGDIR / "composter.err.log"),
    }


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def is_loaded() -> bool:
    return _launchctl("print", f"gui/{os.getuid()}/{LABEL}").returncode == 0


def install(interval: int) -> int:
    LOGDIR.mkdir(parents=True, exist_ok=True)
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    if is_loaded():
        _launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")
    with open(PLIST, "wb") as f:
        plistlib.dump(build_plist(interval), f)
    proc = _launchctl("bootstrap", f"gui/{os.getuid()}", str(PLIST))
    if proc.returncode != 0:
        print(f"bootstrap failed: {proc.stderr.strip()}", file=sys.stderr)
        return 1
    mins = interval // 60
    print(f"installed {LABEL}: every {mins} minute{'' if mins == 1 else 's'}")
    print(f"  interpreter: {interpreter()}")
    print(f"  plist:       {PLIST}")
    print(f"  logs:        {LOGDIR}")
    return 0


def uninstall() -> int:
    if is_loaded():
        _launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")
    if PLIST.exists():
        PLIST.unlink()
    print(f"removed {LABEL}")
    return 0


def status() -> int:
    loaded = is_loaded()
    print(f"{LABEL}: {'loaded' if loaded else 'NOT loaded'}")
    if PLIST.exists():
        with open(PLIST, "rb") as f:
            p = plistlib.load(f)
        print(f"  interval:    {p.get('StartInterval')}s")
        print(f"  interpreter: {p['ProgramArguments'][0]}")
    else:
        print(f"  no plist at {PLIST}")
    return 0 if loaded else 1


def main() -> int:
    ap = argparse.ArgumentParser(prog="agent")
    sub = ap.add_subparsers(dest="verb", required=True)
    p = sub.add_parser("install")
    p.add_argument("--interval", type=int, default=3600,
                   help="seconds between runs (default 3600 = hourly)")
    sub.add_parser("uninstall")
    sub.add_parser("status")
    args = ap.parse_args()
    if args.verb == "install":
        return install(args.interval)
    if args.verb == "uninstall":
        return uninstall()
    return status()


if __name__ == "__main__":
    raise SystemExit(main())
