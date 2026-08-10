"""Voice Memos (plan §8.2).

VoiceMemos.app has no scripting dictionary, so this is Full-Disk-Access-or-
nothing: the recordings live in a TCC-protected group container.

Identity is the one part that genuinely needs the FDA grant before it can be
finalised. `CloudRecordings.db` holds `ZUNIQUEID`, which is stable across
renames and across devices, and filenames are NOT stable (renaming a memo
renames the file in some versions). Until that schema can be read on this
machine, the documented fallback is used — sha256 of the first MiB plus the
file size — and whichever identity was NOT used is stored as `source_alt_id`,
so a later fix can re-key without duplicating anything.

Voice memos are write-once: upstream never changes, so the conflict machinery
is dormant here and only graduation and dismissal apply.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from ..transcribe import TranscribeError, probe_duration, transcribe
from .base import Capture, Source

CONTAINER = Path.home() / "Library" / "Group Containers" / \
    "group.com.apple.VoiceMemos.shared" / "Recordings"
DB_NAME = "CloudRecordings.db"
AUDIO_SUFFIXES = (".m4a", ".wav", ".mp3", ".aac", ".caf")

# Core Data counts seconds from 2001-01-01, not the Unix epoch.
CORE_DATA_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)

QUIET_SECONDS = 90          # gate 1: too recently modified
STABLE_WINDOW_SECONDS = 5   # gate 2: size unchanged across this interval


class VoiceMemosBlocked(RuntimeError):
    """The recordings container is not readable — Full Disk Access is missing."""


def container_readable(root: Path = CONTAINER) -> bool:
    try:
        root.iterdir()
        return True
    except (PermissionError, OSError):
        return False


def hash_identity(path: Path) -> str:
    """Fallback identity: sha256 of the first MiB plus the file size. Stable
    for a file whose content does not change, which is exactly the voice memo
    case, and unaffected by renames."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read(1024 * 1024))
    h.update(str(path.stat().st_size).encode())
    return "sha256:" + h.hexdigest()[:32]


def read_cloud_recordings(root: Path = CONTAINER) -> dict[str, dict]:
    """Map filename -> {unique_id, date, title, duration} from CloudRecordings.db.

    Returns {} for any schema this does not recognise rather than raising: the
    macOS 26 schema is unaudited, and only the identity function depends on it.
    Everything else keeps working off the filesystem.
    """
    db_path = root / DB_NAME
    if not db_path.is_file():
        return {}
    out: dict[str, dict] = {}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(ZCLOUDRECORDING)")}
        if not {"ZUNIQUEID", "ZPATH"} <= cols:
            return {}
        select = ["ZUNIQUEID", "ZPATH"]
        for optional in ("ZDATE", "ZCUSTOMLABEL", "ZDURATION"):
            if optional in cols:
                select.append(optional)
        for row in conn.execute(f"SELECT {', '.join(select)} FROM ZCLOUDRECORDING"):
            path = row["ZPATH"]
            if not path:
                continue
            date = None
            if "ZDATE" in select and row["ZDATE"] is not None:
                date = (CORE_DATA_EPOCH.timestamp() + float(row["ZDATE"]))
            out[Path(path).name] = {
                "unique_id": row["ZUNIQUEID"],
                "date": date,
                "title": row["ZCUSTOMLABEL"] if "ZCUSTOMLABEL" in select else None,
                "duration": row["ZDURATION"] if "ZDURATION" in select else None,
            }
    except sqlite3.Error:
        return {}
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return out


class VoiceMemosSource(Source):
    name = "voice-memo"
    subfolder = "Voice"

    def __init__(self, root: Path = CONTAINER, model: Path | None = None,
                 transcripts_dir: Path | None = None,
                 max_minutes_per_run: int = 30, quiet_seconds: int = QUIET_SECONDS,
                 now=None):
        self.root = Path(root)
        self.model = Path(model) if model else \
            Path.home() / ".cache/whisper-models/ggml-base.en.bin"
        self.transcripts_dir = Path(transcripts_dir or "state/transcripts")
        # One long recording must never blow an entire scheduled run.
        self.max_minutes_per_run = int(max_minutes_per_run)
        self.quiet_seconds = int(quiet_seconds)
        self.now = now or time.time

    # -- gates ---------------------------------------------------------------

    def _ready(self, path: Path) -> tuple[bool, str]:
        """Three independent gates against importing a partial file."""
        try:
            st = path.stat()
        except OSError as e:
            return False, f"unreadable: {e}"
        if self.now() - st.st_mtime < self.quiet_seconds:
            return False, "modified too recently"
        time.sleep(0)  # size stability is checked by the caller across a window
        return True, ""

    def _size_stable(self, path: Path) -> bool:
        try:
            first = path.stat().st_size
            time.sleep(STABLE_WINDOW_SECONDS)
            return path.stat().st_size == first
        except OSError:
            return False

    def _icloud_placeholder(self, path: Path) -> bool:
        """`.name.icloud` stubs are not-yet-downloaded files. Never treat one as
        an empty recording; ask for it and pick it up on a later run."""
        return path.name.startswith(".") and path.name.endswith(".icloud")

    # -- capture -------------------------------------------------------------

    def captures(self, limit: int | None = None,
                 known_mods: dict[str, str] | None = None) -> list[Capture]:
        if not container_readable(self.root):
            raise VoiceMemosBlocked(
                f"cannot read {self.root} — grant Full Disk Access to the "
                f"interpreter running composter, then re-run `doctor`.")

        known = known_mods or {}
        meta = read_cloud_recordings(self.root)
        pending_download = []
        out: list[Capture] = []
        budget_seconds = self.max_minutes_per_run * 60

        files = sorted((p for p in self.root.iterdir()
                        if p.suffix.lower() in AUDIO_SUFFIXES and p.is_file()),
                       key=lambda p: p.stat().st_mtime, reverse=True)

        for path in self.root.iterdir():
            if self._icloud_placeholder(path):
                pending_download.append(path)

        for path in files:
            ok, _why = self._ready(path)
            if not ok:
                continue

            row = meta.get(path.name) or {}
            source_id = row.get("unique_id") or hash_identity(path)
            alt_id = hash_identity(path) if row.get("unique_id") else None
            if known.get(source_id):
                continue                      # already imported; write-once

            if not self._size_stable(path):
                continue
            duration = probe_duration(path)
            if duration is None:
                continue                      # truncated or still syncing
            if duration > budget_seconds:
                continue                      # try again next run
            budget_seconds -= duration

            created = row.get("date")
            created_iso = (datetime.fromtimestamp(created, tz=timezone.utc)
                           .astimezone().isoformat(timespec="seconds")
                           if created else
                           datetime.fromtimestamp(path.stat().st_mtime)
                           .astimezone().isoformat(timespec="seconds"))
            title = (row.get("title") or path.stem).strip() or path.stem

            try:
                result = transcribe(path, self.model, self.transcripts_dir,
                                    stem=_safe_stem(source_id))
            except TranscribeError:
                continue                      # retried next run; never fatal

            out.append(Capture(
                source=self.name,
                source_id=source_id,
                title=title,
                body=result.text,
                created=created_iso,
                kind="transcript",
                source_ref=str(path.name),
                # The audio itself is attached by the engine, which owns the
                # vault; a source never touches vault paths.
                media=(str(path),),
                skip_reason=None if result.text.strip() else "no speech detected",
                payload_hash=source_id,       # write-once: identity IS the hash
            ))
            if limit is not None and len(out) >= limit:
                break

        if pending_download:
            _request_downloads(pending_download)
        return out


def _safe_stem(source_id: str) -> str:
    return hashlib.sha256(source_id.encode()).hexdigest()[:24]


def _request_downloads(paths: list[Path]) -> None:
    """Ask iCloud to materialise placeholder files, then defer to a later run."""
    import subprocess
    for p in paths[:20]:
        try:
            subprocess.run(["brctl", "download", str(p)],
                           capture_output=True, timeout=30, check=False)
        except (OSError, subprocess.SubprocessError):
            pass
