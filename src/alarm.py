"""Tier 2 failure surfacing (plan §13).

Passive first, unmissable on escalation, self-clearing. The alarm file lives
inside zCompost/ because isolation is absolute; the visibility it loses by not
sitting at the vault root is bought back with a macOS notification, which is
appropriate precisely because escalation should be rare.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone

from .config import Config
from .db import DB
from .vault import ALARM_NAME, VaultWriter

FAIL_THRESHOLD = 3          # consecutive failed runs
STALE_AFTER = timedelta(hours=26)   # ...or this long with no success at all


def _consecutive_failures(db: DB) -> tuple[int, str | None]:
    rows = list(db.conn.execute(
        "SELECT ok, finished_at, notes FROM runs WHERE finished_at IS NOT NULL "
        "ORDER BY id DESC LIMIT 20"))
    n, last_error = 0, None
    for r in rows:
        if r["ok"]:
            break
        n += 1
        last_error = last_error or r["notes"]
    return n, last_error


def notify(title: str, message: str) -> None:
    """Best-effort macOS notification. Never raises — a missing notification
    must not fail a run that otherwise worked."""
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification {_esc(message)} with title {_esc(title)}'],
            capture_output=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        pass


def _esc(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"')[:200] + '"'


def render_alarm(failures: int, last_success: str | None, error: str | None,
                 now: datetime) -> str:
    if last_success:
        elapsed = now - datetime.fromisoformat(last_success)
        ago = f"{int(elapsed.total_seconds() // 3600)} hours ago ({last_success})"
    else:
        ago = "never"
    return "\n".join([
        "# Composter needs attention",
        "",
        f"Consecutive failed runs: **{failures}**",
        f"Last successful run: **{ago}**",
        "",
        "## What went wrong",
        "",
        f"```\n{(error or 'no error recorded').strip()[:1500]}\n```",
        "",
        "## What to run",
        "",
        "```sh",
        "cd ~/Projects/composter",
        ".venv/bin/python -m src.main doctor",
        ".venv/bin/python -m src.main all",
        "```",
        "",
        "This file deletes itself after the next successful run.",
        "",
    ])


def update(cfg: Config, db: DB, now: datetime | None = None) -> dict:
    """Raise or clear the alarm. Called after every scheduled run."""
    now = now or datetime.now(timezone.utc).astimezone()
    writer = VaultWriter(cfg.vault_root, cfg.managed_dir, cfg.vault_id)

    failures, error = _consecutive_failures(db)
    last = db.last_successful_run()
    last_success = last["finished_at"] if last and last["finished_at"] else None

    # Staleness is measured from the last success, or — if there has never been
    # one — from the first run ever attempted. Measuring from epoch would make a
    # brand-new install alarm on its very first failure, well before the
    # three-consecutive-failures rule has had a chance to apply.
    first = db.conn.execute(
        "SELECT MIN(started_at) AS t, COUNT(*) AS n FROM runs").fetchone()
    if first["n"] == 0:
        return {"alarm": False, "cleared": False, "failures": 0}  # nothing has run yet
    since = datetime.fromisoformat(last_success or first["t"])
    stale = now - since > STALE_AFTER
    should_alarm = failures >= FAIL_THRESHOLD or stale

    if should_alarm:
        raised = writer.write_alarm(render_alarm(failures, last_success, error, now))
        if raised:  # only notify on the transition, never on every tick
            notify("Composter needs attention",
                   f"{failures} failed runs. See zCompost/{ALARM_NAME}")
        return {"alarm": True, "newly_raised": raised, "failures": failures}

    cleared = writer.clear_alarm()
    return {"alarm": False, "cleared": cleared, "failures": failures}
