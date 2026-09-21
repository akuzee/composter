"""doctor — a green/red preflight checklist. Four capability grants can each
fail silently (Automation consent, Full Disk Access, the whisper model, the
vault sentinel); this verb exists so they fail visibly instead (plan §5.2).
"""

from __future__ import annotations

import importlib
import shutil
import sqlite3
from pathlib import Path

from .config import Config
from .vault import SENTINEL_NAME

GREEN, RED, YELLOW = "✓", "✗", "•"


def _check_deps() -> list[tuple[str, bool, str]]:
    out = []
    for mod, needed_for in (("yaml", "config + frontmatter"),
                            ("bs4", "Phase 2: Apple Notes HTML"),
                            ("markdownify", "Phase 2: Apple Notes HTML"),
                            ("dateutil", "date parsing")):
        try:
            importlib.import_module(mod)
            out.append((f"python module {mod}", True, needed_for))
        except ImportError:
            out.append((f"python module {mod}", False, f"pip install -r requirements.txt ({needed_for})"))
    return out


def _automation_consent_check() -> tuple[str, bool | None, str]:
    """A minimal Apple Event to Notes. First run pops the consent dialog —
    that is the point: doctor is where the grant gets made, visibly."""
    import subprocess
    name = "Automation consent (Phase 2: Apple Notes)"
    try:
        proc = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e",
             'JSON.stringify(Application("Notes").notes.length)'],
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        return (name, False, "no response in 30s — a consent dialog is probably "
                             "waiting on screen; click Allow and re-run doctor")
    except FileNotFoundError:
        return (name, False, "osascript not found")
    if proc.returncode == 0:
        return (name, True, f"granted — Notes reports {proc.stdout.strip()} notes")
    err = proc.stderr.strip()
    if "-1743" in err:
        return (name, False, "DENIED — System Settings → Privacy & Security → "
                             "Automation → (your terminal) → enable Notes")
    return (name, False, err[:200])


def _agent_check() -> tuple[str, bool | None, str]:
    import os
    import subprocess
    label = "com.adamkuzee.composter"
    name = "launchd agent loaded"
    try:
        proc = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{label}"],
                              capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as e:
        return (name, None, f"could not query launchctl: {e}")
    if proc.returncode != 0:
        return (name, None,
                "not installed — `python scripts/agent.py install` (Phase 3)")
    return (name, True, f"{label} is loaded")


def collect_checks(cfg: Config) -> list[tuple[str, bool | None, str]]:
    """(name, ok, detail). ok=None means informational (needed by a later phase)."""
    checks: list[tuple[str, bool | None, str]] = []

    checks.append(("vault root exists", cfg.vault_root.is_dir(), str(cfg.vault_root)))

    managed = cfg.managed_root
    sentinel = managed / SENTINEL_NAME
    if not managed.is_dir():
        checks.append(("managed dir + sentinel", False,
                       f"{managed} missing — run `init` (after Phase 0 confirms the right vault)"))
    elif not sentinel.is_file():
        checks.append(("managed dir + sentinel", False, f"{sentinel} missing — run `init`"))
    else:
        actual = sentinel.read_text(encoding="utf-8").strip()
        ok = actual == cfg.vault_id
        checks.append(("managed dir + sentinel", ok,
                       "matches config" if ok else f"sentinel={actual!r} config={cfg.vault_id!r} — WRONG VAULT?"))

    try:
        cfg.ensure_state_dirs()
        conn = sqlite3.connect(cfg.db_path)
        conn.execute("SELECT 1")
        conn.close()
        checks.append(("state dir + ledger writable", True, str(cfg.db_path)))
    except Exception as e:
        checks.append(("state dir + ledger writable", False, str(e)))

    checks.append(("isolation baseline", cfg.isolation_baseline_path.is_file(),
                   str(cfg.isolation_baseline_path)
                   if cfg.isolation_baseline_path.is_file()
                   else "capture it while the vault is pristine: `isolation --capture`"))

    checks.extend(_check_deps())

    # The one gap in the failure-surfacing scheme is the agent not running at
    # all: no run means no status update means no alarm (plan §13).
    checks.append(_agent_check())

    # Later-phase capabilities — informational until their phase arrives.
    checks.append(("osascript (Phase 2: Apple Notes)",
                   None if shutil.which("osascript") else False,
                   shutil.which("osascript") or "not found"))

    notes_cfg = cfg.sources.get("notes")
    if notes_cfg and notes_cfg.enabled:
        checks.append(_automation_consent_check())
    else:
        checks.append(("Automation consent (Phase 2: Apple Notes)", None,
                       "not probed — enable sources.notes first (probing pops "
                       "the consent dialog)"))
    checks.append(("ffmpeg (Phase 4: voice)",
                   None if shutil.which("ffmpeg") else False,
                   shutil.which("ffmpeg") or "not found"))
    whisper = shutil.which("whisper-cli") or shutil.which("whisper-cpp")
    checks.append(("whisper-cpp (Phase 4: voice)", None if whisper else False,
                   whisper or "not found"))
    model = Path.home() / ".cache/whisper-models/ggml-base.en.bin"
    checks.append(("whisper model (Phase 4: voice)", None if model.is_file() else False,
                   str(model) if model.is_file() else f"{model} missing"))
    # Probe what is actually needed — the Voice Memos container — rather than
    # TCC.db, which is protected more strictly than the thing we want and so
    # reports "blocked" even when voice capture would work fine.
    from .sources.voice_memos import CONTAINER, container_readable
    if container_readable():
        checks.append(("Full Disk Access (Phases 4–5)", True,
                       f"granted — {CONTAINER} is readable"))
    else:
        checks.append((
            "Full Disk Access (Phases 4–5)", None,
            "cannot read the Voice Memos container. macOS attributes file "
            "access to the process that was LAUNCHED, so grant Full Disk "
            "Access to whatever you are running this from (Terminal.app, "
            "iTerm, VS Code) for manual runs; for the scheduled agent, drag "
            "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13 "
            "into the Full Disk Access list from Finder (the picker refuses "
            "loose executables, but drag-and-drop works). Running "
            "Composter.app's inner executable from a shell tests the SHELL's "
            "grant, not the app's."))

    return checks


def run_doctor(cfg: Config) -> int:
    checks = collect_checks(cfg)
    hard_fail = False
    for name, ok, detail in checks:
        if ok is True:
            mark = GREEN
        elif ok is None:
            mark = YELLOW
        else:
            mark = RED
            hard_fail = hard_fail or "Phase" not in name
        print(f" {mark} {name}: {detail}")
    print()
    if hard_fail:
        print("doctor: NOT healthy — fix the ✗ items above before pulling")
        return 1
    print("doctor: healthy for the current phase (• items are for later phases)")
    return 0
