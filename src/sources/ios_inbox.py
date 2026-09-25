"""The iOS inbox (plan §8.3).

A Shortcut on the phone writes a JSON sidecar plus any attached files into an
iCloud folder; the Mac sweeps that folder. The phone never writes into the
vault, deliberately: the Mac stays the single writer, and two writers into one
synced file tree is how you manufacture exactly the conflicts the fence logic
exists to prevent.

The sidecar carries structured JSON, not rendered markdown, so every
formatting decision stays in vault.py rather than being maintained in
Shortcuts' template editor — which is how you end up with two divergent
renderers.

Consumed sidecars are MOVED to _ingested/<YYYY-MM>/, never deleted, so a bug
cannot destroy a capture and a visibly empty inbox is its own health signal
on the phone.
"""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from ..exifdate import exif_capture_date
from .base import Capture, Source

INBOX = (Path.home() / "Library" / "Mobile Documents" /
         "com~apple~CloudDocs" / "Composter Inbox")
INGESTED = "_ingested"
QUIET_SECONDS = 30
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".heic", ".heif", ".gif", ".webp")


class IosInboxBlocked(RuntimeError):
    """The inbox folder is unreadable — Full Disk Access, or it does not exist."""


def inbox_readable(root: Path = INBOX) -> bool:
    try:
        root.iterdir()
        return True
    except (PermissionError, OSError):
        return False


def is_placeholder(path: Path) -> bool:
    """`.name.icloud` stubs are files iCloud has not downloaded yet. Never
    treat one as an empty capture."""
    return path.name.startswith(".") and path.name.endswith(".icloud")


def request_download(paths: list[Path]) -> None:
    for p in paths[:20]:
        try:
            subprocess.run(["brctl", "download", str(p)],
                           capture_output=True, timeout=30, check=False)
        except (OSError, subprocess.SubprocessError):
            pass


def _kind_for(payload: dict, files: list[Path]) -> str:
    declared = (payload.get("kind") or "").strip().lower()
    if declared in ("note", "link", "photo", "snippet", "clipping"):
        return declared
    if payload.get("source_url"):
        return "link"
    if files and any(f.suffix.lower() in IMAGE_SUFFIXES for f in files):
        return "photo"
    return "note"


def _title_for(payload: dict, kind: str, files: list[Path], created: str) -> str:
    for key in ("title", "name"):
        v = (payload.get(key) or "").strip()
        if v:
            return v[:80]
    text = " ".join((payload.get("text") or "").split())
    if text:
        return " ".join(text.split(" ")[:9]).rstrip(" ,.;:—-")[:80]
    if files:
        return files[0].stem[:80]
    return f"{kind} {created[:10]}"


class IosInboxSource(Source):
    name = "ios-share"
    subfolder = "Inbox"
    mirror_folders = False

    def __init__(self, root: Path = INBOX, quiet_seconds: int = QUIET_SECONDS,
                 now=None):
        self.root = Path(root)
        self.quiet_seconds = int(quiet_seconds)
        self.now = now or time.time

    def captures(self, limit: int | None = None,
                 known_mods: dict[str, str] | None = None) -> list[Capture]:
        if not inbox_readable(self.root):
            raise IosInboxBlocked(
                f"cannot read {self.root}. Grant Full Disk Access to the "
                f"interpreter, and make sure the folder exists in iCloud Drive.")

        known = known_mods or {}
        pending = [p for p in self.root.iterdir() if is_placeholder(p)]
        if pending:
            request_download(pending)

        out: list[Capture] = []
        sidecars = sorted((p for p in self.root.iterdir()
                           if p.suffix.lower() == ".json" and p.is_file()),
                          key=lambda p: p.name)

        for sidecar in sidecars:
            try:
                if self.now() - sidecar.stat().st_mtime < self.quiet_seconds:
                    continue          # still being written, or still syncing
                payload = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue              # malformed or mid-write; try again next run
            if not isinstance(payload, dict):
                continue

            # The sidecar's name is the capture's identity: the Shortcut stamps
            # it with a timestamp to the second, and it never changes.
            source_id = sidecar.stem
            if known.get(source_id):
                continue

            files, missing = [], False
            for rel in (payload.get("files") or []):
                f = self.root / str(rel).lstrip("/")
                if is_placeholder(f) or not f.is_file():
                    # An attachment named but not yet downloaded. Wait rather
                    # than import a capture with a hole in it.
                    missing = True
                    request_download([f])
                    break
                files.append(f)
            if missing:
                continue

            created = (payload.get("captured_at") or "").strip()
            # A photo's EXIF capture date is the truth and is unrecoverable
            # once stripped; the share timestamp is only when it was sent.
            for f in files:
                if f.suffix.lower() in IMAGE_SUFFIXES:
                    exif = exif_capture_date(f)
                    if exif:
                        created = exif
                        break
            if not created:
                created = datetime.fromtimestamp(
                    sidecar.stat().st_mtime, tz=timezone.utc).astimezone().isoformat(
                        timespec="seconds")

            kind = _kind_for(payload, files)
            text = (payload.get("text") or "").strip()
            url = (payload.get("source_url") or "").strip()
            body = "\n\n".join(x for x in (f"<{url}>" if url else "", text) if x)

            out.append(Capture(
                source=self.name,
                source_id=source_id,
                title=_title_for(payload, kind, files, created),
                body=body,
                created=created,
                kind=kind,
                source_ref=sidecar.name,
                media=tuple(str(f) for f in files),
                modified=source_id,       # write-once: identity is the stamp
                payload_hash=source_id,
                skip_reason=None if (body or files) else "empty capture",
            ))
            if limit is not None and len(out) >= limit:
                break
        return out

    def mark_ingested(self, source_ids: set[str]) -> int:
        """Move consumed sidecars and their files out of the inbox.

        Moved, never deleted: a bug must not be able to destroy a capture, and
        an inbox that looks empty on the phone is its own health signal.
        """
        moved = 0
        for sidecar in list(self.root.glob("*.json")):
            if sidecar.stem not in source_ids:
                continue
            try:
                payload = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
            dest = self.root / INGESTED / datetime.now().strftime("%Y-%m")
            dest.mkdir(parents=True, exist_ok=True)
            for rel in (payload.get("files") or []):
                f = self.root / str(rel).lstrip("/")
                if f.is_file():
                    f.replace(dest / f.name)
            sidecar.replace(dest / sidecar.name)
            moved += 1
        return moved
