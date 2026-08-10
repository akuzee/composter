"""Apple Notes via JXA (plan §8.1): needs Automation consent only, not Full
Disk Access. Two-phase fetch — a cheap five-event index of the whole library,
then bodies only for notes whose modification date moved, in batches.

This module knows nothing about vaults, conflicts, or graduation. It shells
out to osascript, converts HTML to markdown, and yields Captures.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..htmlmd import html_to_markdown
from .base import Capture, Source

JXA_DIR = Path(__file__).resolve().parents[1] / "jxa"

CONSENT_HINT = (
    " — this looks like missing Automation consent. Run any composter pull once "
    "from Terminal and click Allow, or check System Settings → Privacy & Security "
    "→ Automation → (your terminal) → Notes."
)


class JXAError(RuntimeError):
    pass


def _meaningful(title: str) -> bool:
    return bool(title.strip()) and title.strip().lower() not in ("untitled", "new note")


def run_jxa(script: str, args: list[str] | None = None, timeout: int = 600) -> str:
    cmd = ["osascript", "-l", "JavaScript", str(JXA_DIR / script), *(args or [])]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise JXAError(f"{script} timed out after {timeout}s"
                       " (a consent dialog may be waiting on screen)") from e
    if proc.returncode != 0:
        err = proc.stderr.strip()
        hint = CONSENT_HINT if ("-1743" in err or "authorized" in err.lower()) else ""
        raise JXAError(f"{script} failed: {err}{hint}")
    return proc.stdout


def _to_local_iso(iso_utc: str | None) -> str | None:
    """JXA emits UTC (toISOString). Store local-offset ISO so timelines and
    filename dates reflect when the thought actually happened here."""
    if not iso_utc:
        return None
    dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    return dt.astimezone().isoformat(timespec="seconds")


class AppleNotesSource(Source):
    name = "apple-notes"
    subfolder = "Notes"

    def __init__(self, quiet_seconds: int = 120, batch_size: int = 50,
                 max_fetch_per_run: int = 200,
                 exclude_folders: tuple[str, ...] = ("Quick Notes",),
                 exclude_ids: frozenset[str] = frozenset(),
                 runner=None, now=None):
        self.quiet_seconds = int(quiet_seconds)
        self.batch_size = int(batch_size)
        # Folders that never enter the compost. "Recently Deleted" is always
        # excluded; "Quick Notes" is the owner's designated trash-not-compost
        # channel (Control Center jots that shouldn't be archived).
        self.exclude_folders = frozenset(exclude_folders) | {"Recently Deleted"}
        # Per-note trash verdicts from the hand-run triage review.
        self.exclude_ids = frozenset(exclude_ids)
        # Hard cap on bodies fetched in one run: on first contact with a
        # large library every note is "changed", and an uncapped run would
        # fetch thousands of bodies before writing anything. The backlog
        # drains across runs instead; steady-state runs never hit this.
        self.max_fetch_per_run = int(max_fetch_per_run)
        self.runner = runner or run_jxa       # injectable for tests
        self.now = now or (lambda: datetime.now(timezone.utc))

    def captures(self, limit: int | None = None,
                 known_mods: dict[str, str] | None = None) -> list[Capture]:
        known = known_mods or {}
        index = json.loads(self.runner("dump_index.js", []))
        try:
            folders = json.loads(self.runner("dump_folders.js", []))
        except JXAError:
            folders = {}  # folder info is nice-to-have, never blocking
        folder_of = {nid: fname for fname, ids in folders.items() for nid in ids}

        now = self.now()
        out: list[Capture] = []
        to_fetch: list[dict] = []
        # Newest first: --limit N grabs the most recent thinking, deterministically.
        index.sort(key=lambda e: (e.get("modified") or "", e["id"]), reverse=True)

        for e in index:
            if e["id"] in self.exclude_ids:
                continue  # triaged as trash-not-compost by the owner
            folder = folder_of.get(e["id"], "")
            if self.exclude_folders & set(folder.split("/")):
                continue  # excluded channel: deleted notes, Quick Notes, etc.
            if known.get(e["id"]) == e.get("modified"):
                continue  # prefilter: fetch bodies only for what actually moved
            if e.get("locked"):
                out.append(self._skip(e, "locked", folder_of))
                continue
            if self._in_quiet_period(e.get("modified"), now):
                continue  # never import a note modified in the last two minutes
            to_fetch.append(e)
            cap = self.max_fetch_per_run if limit is None else min(limit, self.max_fetch_per_run)
            if len(to_fetch) >= cap:
                break

        bodies: dict[str, dict] = {}
        for i in range(0, len(to_fetch), self.batch_size):
            batch = [e["id"] for e in to_fetch[i:i + self.batch_size]]
            for b in json.loads(self.runner("dump_bodies.js", batch)):
                bodies[b["id"]] = b

        for e in to_fetch:
            b = bodies.get(e["id"])
            if b is None:
                continue  # vanished between index and body fetch; next run gets it
            title = b.get("name") or "untitled"
            html = b.get("body") or ""
            atts = [str(a) for a in (b.get("attachments") or []) if a]
            md = html_to_markdown(html, title=title)
            # Normalized attachments may not appear in body HTML at all;
            # surface every attachment the note knows about, no silent loss.
            for att in atts:
                if att not in md:
                    md = (md + f"\n\n> [!info] Attachment not yet imported: {att}").strip()
            out.append(Capture(
                source=self.name,
                source_id=e["id"],
                title=title,
                body=md,
                created=_to_local_iso(e.get("created")),
                kind="note",
                source_ref=folder_of.get(e["id"]),
                modified=e.get("modified"),
                # Change detection hashes the upstream HTML (+ attachment
                # names), not our rendering, so a converter tweak never
                # dirties every file (plan §7.1).
                payload_hash=hashlib.sha256(
                    "\x00".join([title, html, *atts]).encode("utf-8")).hexdigest(),
                # Title-only one-line jots are real captures — the title IS
                # the thought. Skip only when there is no content anywhere.
                skip_reason=None if (md.strip() or _meaningful(title)) else "empty",
            ))
        return out

    def _skip(self, e: dict, reason: str, folder_of: dict) -> Capture:
        return Capture(
            source=self.name, source_id=e["id"],
            title=e.get("name") or "untitled", body="",
            created=_to_local_iso(e.get("created")),
            source_ref=folder_of.get(e["id"]),
            modified=e.get("modified"), skip_reason=reason,
        )

    def _in_quiet_period(self, modified_iso: str | None, now: datetime) -> bool:
        if not modified_iso:
            return False
        mod = datetime.fromisoformat(modified_iso.replace("Z", "+00:00"))
        return now - mod < timedelta(seconds=self.quiet_seconds)
