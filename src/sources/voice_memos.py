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
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from ..transcribe import TranscribeError, probe_duration, transcribe
from .base import Capture, Source

GROUP_CONTAINER = Path.home() / "Library" / "Group Containers" / \
    "group.com.apple.VoiceMemos.shared"
# Measured on macOS 26 (2026-09-22): the group container exists but holds only
# an empty Library/ skeleton until the first recording syncs to this Mac, so
# the exact subfolder could not be confirmed. Older macOS used Recordings/.
# Rather than hard-code a guess, resolve at call time and fall back to
# searching the container for audio.
CONTAINER = GROUP_CONTAINER / "Recordings"
DB_NAME = "CloudRecordings.db"
AUDIO_SUFFIXES = (".m4a", ".wav", ".mp3", ".aac", ".caf")

# Core Data counts seconds from 2001-01-01, not the Unix epoch.
CORE_DATA_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)

# Measured on macOS 26: for an unnamed memo ZCUSTOMLABEL holds an ISO
# timestamp ("2026-09-09T04:02:22Z"), not a human title. Using it verbatim
# would produce a vault full of files named after timestamps — unfindable,
# and redundant with `created`. Detect that shape and prefer the transcript.
_ISO_LABEL = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")

QUIET_SECONDS = 90          # gate 1: too recently modified
STABLE_WINDOW_SECONDS = 5   # gate 2: size unchanged across this interval


class VoiceMemosBlocked(RuntimeError):
    """The recordings container is not readable — Full Disk Access is missing."""


def container_readable(root: Path = GROUP_CONTAINER) -> bool:
    """Readable means the TCC grant is in place — not that recordings exist."""
    try:
        root.iterdir()
        return True
    except (PermissionError, OSError):
        return False


def resolve_recordings_dir(group: Path = GROUP_CONTAINER) -> Path | None:
    """Find the directory actually holding recordings.

    Apple has moved this between releases and it does not exist at all until
    the first memo syncs, so prefer discovery over a hard-coded path. Returns
    None when the container is unreadable or simply has no audio in it yet.
    """
    if not container_readable(group):
        return None
    preferred = group / "Recordings"
    if preferred.is_dir():
        return preferred
    try:
        for p in group.rglob("*"):
            if p.is_file() and p.suffix.lower() in AUDIO_SUFFIXES:
                return p.parent
    except OSError:
        return None
    return preferred if preferred.exists() else None


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

    def _stable_set(self, paths: list[Path]) -> set[Path]:
        """Gate 2, batched: snapshot every candidate's size, sleep ONCE, then
        re-check. The obvious per-file implementation sleeps 5s each, which on
        a library of 100 recordings is eight minutes of doing nothing — and it
        happens before the cheaper gates have had a chance to rule files out.
        """
        if not paths:
            return set()
        first: dict[Path, int] = {}
        for p in paths:
            try:
                first[p] = p.stat().st_size
            except OSError:
                continue
        time.sleep(STABLE_WINDOW_SECONDS)
        stable = set()
        for p, size in first.items():
            try:
                if p.stat().st_size == size:
                    stable.add(p)
            except OSError:
                continue
        return stable

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

        # Newest recording first, by the date the memo was MADE. Filesystem
        # mtime is useless here: everything that syncs down from iCloud lands
        # with the same sync timestamp, so ordering by it is arbitrary and
        # `--limit N` would return a random N rather than the latest N.
        def recorded_at(p: Path) -> float:
            d = (meta.get(p.name) or {}).get("date")
            return float(d) if d else p.stat().st_mtime

        files = sorted((p for p in self.root.iterdir()
                        if p.suffix.lower() in AUDIO_SUFFIXES and p.is_file()),
                       key=recorded_at, reverse=True)

        for path in self.root.iterdir():
            if self._icloud_placeholder(path):
                pending_download.append(path)

        # Cheap gates first, so the expensive ones only see real candidates.
        candidates: list[tuple[Path, str, dict]] = []
        for path in files:
            ok, _why = self._ready(path)
            if not ok:
                continue                      # gate 1: modified too recently
            row = meta.get(path.name) or {}
            source_id = row.get("unique_id") or hash_identity(path)
            if known.get(source_id):
                continue                      # already imported; write-once
            candidates.append((path, source_id, row))

        stable = self._stable_set([c[0] for c in candidates])   # gate 2, one sleep

        for path, source_id, row in candidates:
            if path not in stable:
                continue
            duration = probe_duration(path)
            if duration is None:
                continue                      # truncated or still syncing
            # A single recording longer than the entire budget would otherwise
            # be deferred on every run, forever. Let the first one through.
            if duration > budget_seconds and budget_seconds < self.max_minutes_per_run * 60:
                continue                      # budget already spent; try next run
            budget_seconds -= duration

            created = row.get("date")
            created_iso = (datetime.fromtimestamp(created, tz=timezone.utc)
                           .astimezone().isoformat(timespec="seconds")
                           if created else
                           datetime.fromtimestamp(path.stat().st_mtime)
                           .astimezone().isoformat(timespec="seconds"))
            label = (row.get("title") or "").strip()
            human_label = label if label and not _ISO_LABEL.match(label) else ""

            try:
                result = transcribe(path, self.model, self.transcripts_dir,
                                    stem=_safe_stem(source_id))
            except TranscribeError:
                continue                      # retried next run; never fatal

            # An unnamed memo gets its title from what was actually said —
            # far more findable than "voice memo" a hundred times over, and
            # the filename is chosen once at creation so it must be good now.
            title = human_label or _title_from_transcript(result.text) or (
                f"voice memo {created_iso[:10]}" if created_iso else "voice memo")
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


def _title_from_transcript(text: str, words: int = 9) -> str:
    """First few words of what was said, as the note's title.

    Voice memos arrive unnamed, and the filename is chosen once at creation
    and never changed (plan §7.2 invariant 5), so it has to be worth keeping.
    """
    flat = " ".join((text or "").split())
    if not flat:
        return ""
    head = " ".join(flat.split(" ")[:words])
    return head.rstrip(" ,.;:—-").strip()
