"""Phase 4: the Voice Memos source, against a fake recordings directory.

Full Disk Access is not needed to test any of this — the source takes its root
as a parameter, so a tmp_path stands in for the real container.
"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.sources.voice_memos import (
    CORE_DATA_EPOCH,
    VoiceMemosBlocked,
    VoiceMemosSource,
    container_readable,
    hash_identity,
    read_cloud_recordings,
)

MODEL = Path.home() / ".cache/whisper-models/ggml-base.en.bin"
HAVE_TOOLS = all(shutil.which(t) for t in ("ffmpeg", "ffprobe", "say")) and (
    shutil.which("whisper-cli") or shutil.which("whisper-cpp"))
needs_tools = pytest.mark.skipif(not (HAVE_TOOLS and MODEL.is_file()),
                                 reason="audio tooling unavailable")


def make_recording(root: Path, name: str, words: str) -> Path:
    dest = root / name
    subprocess.run(["say", "-o", str(dest.with_suffix(".aiff")), words],
                   check=True, capture_output=True, timeout=120)
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y",
                    "-i", str(dest.with_suffix(".aiff")), str(dest)],
                   check=True, capture_output=True, timeout=300)
    dest.with_suffix(".aiff").unlink()
    return dest


@pytest.fixture
def recordings(tmp_path):
    d = tmp_path / "Recordings"
    d.mkdir()
    return d


def source(recordings, tmp_path, **kw):
    kw.setdefault("now", lambda: 1e12)   # everything is old enough
    return VoiceMemosSource(root=recordings, model=MODEL,
                            transcripts_dir=tmp_path / "transcripts", **kw)


# -- access ---------------------------------------------------------------------

def test_blocked_container_raises_a_clear_error(tmp_path):
    src = VoiceMemosSource(root=tmp_path / "does-not-exist")
    assert container_readable(tmp_path / "does-not-exist") is False
    with pytest.raises(VoiceMemosBlocked, match="Full Disk Access"):
        src.captures()


# -- identity -------------------------------------------------------------------

def test_hash_identity_is_stable_across_renames(tmp_path):
    a = tmp_path / "one.m4a"
    a.write_bytes(b"audio bytes here" * 100)
    before = hash_identity(a)
    b = tmp_path / "renamed.m4a"
    a.rename(b)
    assert hash_identity(b) == before, "filenames are not identity"


def test_hash_identity_differs_by_content(tmp_path):
    a = tmp_path / "a.m4a"; a.write_bytes(b"x" * 5000)
    b = tmp_path / "b.m4a"; b.write_bytes(b"y" * 5000)
    assert hash_identity(a) != hash_identity(b)


# -- CloudRecordings.db ---------------------------------------------------------

def make_db(root: Path, rows: list[tuple], columns: str) -> None:
    conn = sqlite3.connect(root / "CloudRecordings.db")
    conn.execute(f"CREATE TABLE ZCLOUDRECORDING ({columns})")
    marks = ", ".join("?" * len(rows[0]))
    conn.executemany(f"INSERT INTO ZCLOUDRECORDING VALUES ({marks})", rows)
    conn.commit()
    conn.close()


def test_reads_expected_schema(recordings):
    when = (datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
            - CORE_DATA_EPOCH).total_seconds()
    make_db(recordings, [("ABC-123", "/x/memo.m4a", when, "walk thoughts", 42.5)],
            "ZUNIQUEID TEXT, ZPATH TEXT, ZDATE REAL, ZCUSTOMLABEL TEXT, ZDURATION REAL")
    meta = read_cloud_recordings(recordings)
    assert meta["memo.m4a"]["unique_id"] == "ABC-123"
    assert meta["memo.m4a"]["title"] == "walk thoughts"
    got = datetime.fromtimestamp(meta["memo.m4a"]["date"], tz=timezone.utc)
    assert got.year == 2026 and got.month == 8   # Core Data epoch, not Unix

def test_unrecognised_schema_degrades_instead_of_raising(recordings):
    """macOS 26's schema is unaudited. An unknown shape must fall back to hash
    identity, not break the importer."""
    make_db(recordings, [("something",)], "ZWHATEVER TEXT")
    assert read_cloud_recordings(recordings) == {}


def test_absent_db_is_fine(recordings):
    assert read_cloud_recordings(recordings) == {}


# -- gates ----------------------------------------------------------------------

def test_recent_file_is_deferred(recordings, tmp_path):
    f = recordings / "new.m4a"
    f.write_bytes(b"\x00" * 1000)
    import time
    src = source(recordings, tmp_path, now=time.time)   # file is brand new
    assert src.captures() == []


def test_unreadable_audio_is_skipped_not_errored(recordings, tmp_path):
    (recordings / "junk.m4a").write_bytes(b"not audio at all")
    assert source(recordings, tmp_path, quiet_seconds=0).captures() == []


# -- end to end -----------------------------------------------------------------

@needs_tools
def test_transcribes_a_recording(recordings, tmp_path):
    make_recording(recordings, "memo.m4a",
                   "The unit of work is the smallest complete thing.")
    caps = source(recordings, tmp_path, quiet_seconds=0).captures()
    assert len(caps) == 1
    c = caps[0]
    assert c.source == "voice-memo" and c.kind == "transcript"
    assert "smallest complete thing" in c.body.lower()
    assert c.source_id.startswith("sha256:")     # no db -> documented fallback
    assert c.media == (str(recordings / "memo.m4a"),)
    assert c.created is not None


@needs_tools
def test_uses_unique_id_when_the_db_is_readable(recordings, tmp_path):
    make_recording(recordings, "memo.m4a", "Good scraps, not completeness.")
    make_db(recordings, [("UNIQ-9", "/x/memo.m4a", 0.0, "a title", 3.0)],
            "ZUNIQUEID TEXT, ZPATH TEXT, ZDATE REAL, ZCUSTOMLABEL TEXT, ZDURATION REAL")
    caps = source(recordings, tmp_path, quiet_seconds=0).captures()
    assert caps[0].source_id == "UNIQ-9"
    assert caps[0].title == "a title"


@needs_tools
def test_already_imported_memo_is_not_retranscribed(recordings, tmp_path):
    """Voice memos are write-once: upstream never changes."""
    path = make_recording(recordings, "memo.m4a", "Only once, please.")
    src = source(recordings, tmp_path, quiet_seconds=0)
    first = src.captures()
    assert len(first) == 1
    again = src.captures(known_mods={first[0].source_id: "seen"})
    assert again == [], "must not burn whisper time on an unchanged memo"


@needs_tools
def test_long_recording_deferred_by_minute_budget(recordings, tmp_path):
    make_recording(recordings, "memo.m4a", "A short one.")
    src = source(recordings, tmp_path, quiet_seconds=0, max_minutes_per_run=0)
    assert src.captures() == [], "one long recording must not blow a run"


# -- through the engine, into a temp vault --------------------------------------

@needs_tools
def test_voice_capture_lands_in_the_vault_with_playable_audio(env, tmp_path):
    """Plan §12 Phase 4: a note appears with a readable transcript and an
    embedded audio player, and re-running writes zero bytes."""
    from src.main import run_pull

    recordings = tmp_path / "Recordings"
    recordings.mkdir()
    make_recording(recordings, "memo.m4a",
                   "Good scraps, not completeness.")
    src = VoiceMemosSource(root=recordings, model=MODEL,
                           transcripts_dir=env.cfg.transcripts_dir,
                           quiet_seconds=0, now=lambda: 1e12)

    result = run_pull(env.cfg, env.db, "voice", now=env.t0, source=src)
    assert result["created"] == 1, result

    notes = sorted((env.vault / "zCompost" / "Voice").rglob("*.md"))
    assert len(notes) == 1
    text = notes[0].read_text()
    assert "![[zCompost/Media/Voice/memo.m4a]]" in text   # inline player
    assert "scraps" in text.lower()
    assert (env.vault / "zCompost" / "Media" / "Voice" / "memo.m4a").is_file()
    assert (recordings / "memo.m4a").is_file(), "the original is never touched"

    before = notes[0].read_bytes(), notes[0].stat().st_mtime_ns
    again = run_pull(env.cfg, env.db, "voice", now=env.t0, source=src)
    assert again["created"] == 0
    assert (notes[0].read_bytes(), notes[0].stat().st_mtime_ns) == before
