"""Phase 5: the iOS inbox, against a fake iCloud folder."""

from __future__ import annotations

import json
import struct
import time
from pathlib import Path

import pytest

from src.exifdate import exif_capture_date
from src.main import run_pull
from src.sources.ios_inbox import (
    INGESTED,
    IosInboxBlocked,
    IosInboxSource,
    inbox_readable,
    is_placeholder,
)
from src.vault import parse_note


@pytest.fixture
def inbox(tmp_path):
    d = tmp_path / "Composter Inbox"
    d.mkdir()
    return d


def src(inbox, **kw):
    kw.setdefault("now", lambda: 1e12)     # everything is old enough
    return IosInboxSource(root=inbox, **kw)


def sidecar(inbox: Path, stem: str, **payload) -> Path:
    p = inbox / f"{stem}.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def jpeg_with_date(path: Path, stamp: str = "2024:07:04 18:06:30") -> Path:
    """Minimal JPEG carrying one EXIF DateTimeOriginal tag."""
    date = stamp.encode() + b"\x00"
    ifd = struct.pack("<H", 1) + struct.pack("<HHI", 0x9003, 2, len(date))
    ifd += struct.pack("<I", 8 + 2 + 12 + 4) + struct.pack("<I", 0)
    tiff = b"II" + struct.pack("<H", 42) + struct.pack("<I", 8) + ifd + date
    app1 = b"Exif\x00\x00" + tiff
    out = (b"\xff\xd8" + b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1
           + b"\xff\xd9")
    path.write_bytes(out)
    return path


# -- access ---------------------------------------------------------------------

def test_missing_inbox_raises_clearly(tmp_path):
    s = IosInboxSource(root=tmp_path / "nope")
    assert inbox_readable(tmp_path / "nope") is False
    with pytest.raises(IosInboxBlocked, match="Full Disk Access"):
        s.captures()


def test_icloud_placeholders_are_recognised():
    assert is_placeholder(Path(".IMG_1.jpg.icloud"))
    assert not is_placeholder(Path("IMG_1.jpg"))


# -- shapes of capture ----------------------------------------------------------

def test_typed_thought(inbox):
    sidecar(inbox, "2026-09-25T101500",
            captured_at="2026-09-25T10:15:00-04:00",
            text="the unit of work is the smallest complete thing")
    cap = src(inbox).captures()[0]
    assert cap.source == "ios-share" and cap.kind == "note"
    assert "smallest complete thing" in cap.body
    assert cap.title.startswith("the unit of work")
    assert cap.created == "2026-09-25T10:15:00-04:00"


def test_shared_link_keeps_the_url(inbox):
    sidecar(inbox, "2026-09-25T110000",
            captured_at="2026-09-25T11:00:00-04:00",
            source_url="https://example.com/essay", text="worth reading")
    cap = src(inbox).captures()[0]
    assert cap.kind == "link"
    assert "https://example.com/essay" in cap.body
    assert "worth reading" in cap.body


def test_photo_uses_its_exif_date_not_the_share_time(inbox):
    """EXIF may be stripped once a photo leaves the camera roll, so the capture
    date has to be read at import. A wrong date corrupts the timeline forever."""
    jpeg_with_date(inbox / "2026-09-25T120000-1.jpg", "2024:07:04 18:06:30")
    sidecar(inbox, "2026-09-25T120000",
            captured_at="2026-09-25T12:00:00-04:00",
            files=["2026-09-25T120000-1.jpg"], text="fireworks")
    cap = src(inbox).captures()[0]
    assert cap.kind == "photo"
    assert cap.created.startswith("2024-07-04"), cap.created
    assert cap.media and cap.media[0].endswith("-1.jpg")


def test_photo_without_exif_falls_back_to_the_share_time(inbox):
    (inbox / "2026-09-25T130000-1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    sidecar(inbox, "2026-09-25T130000",
            captured_at="2026-09-25T13:00:00-04:00",
            files=["2026-09-25T130000-1.png"])
    cap = src(inbox).captures()[0]
    assert cap.created == "2026-09-25T13:00:00-04:00"


# -- gates ----------------------------------------------------------------------

def test_recent_sidecar_is_deferred(inbox):
    sidecar(inbox, "now", captured_at="x", text="half-written")
    assert src(inbox, now=time.time).captures() == []


def test_malformed_json_is_skipped_not_fatal(inbox):
    (inbox / "broken.json").write_text("{not json", encoding="utf-8")
    sidecar(inbox, "good", captured_at="2026-01-01T00:00:00-05:00", text="fine")
    caps = src(inbox).captures()
    assert [c.source_id for c in caps] == ["good"]


def test_capture_waits_for_an_undownloaded_attachment(inbox):
    """Importing a capture with a hole in it is worse than waiting."""
    (inbox / ".2026-09-25T140000-1.jpg.icloud").write_bytes(b"")
    sidecar(inbox, "2026-09-25T140000",
            captured_at="2026-09-25T14:00:00-04:00",
            files=["2026-09-25T140000-1.jpg"], text="with a photo")
    assert src(inbox).captures() == []


def test_already_imported_is_not_reoffered(inbox):
    sidecar(inbox, "seen", captured_at="2026-01-01T00:00:00-05:00", text="hello")
    s = src(inbox)
    first = s.captures()
    assert len(first) == 1
    assert s.captures(known_mods={"seen": "yes"}) == []


# -- consumption ----------------------------------------------------------------

def test_consumed_sidecars_are_moved_never_deleted(inbox):
    jpeg_with_date(inbox / "a-1.jpg")
    sidecar(inbox, "a", captured_at="2026-01-01T00:00:00-05:00",
            files=["a-1.jpg"], text="x")
    s = src(inbox)
    assert s.mark_ingested({"a"}) == 1
    assert not (inbox / "a.json").exists()
    assert not (inbox / "a-1.jpg").exists()
    moved = list((inbox / INGESTED).rglob("*"))
    names = {p.name for p in moved}
    assert "a.json" in names and "a-1.jpg" in names


# -- EXIF -----------------------------------------------------------------------

def test_exif_reader(tmp_path):
    p = jpeg_with_date(tmp_path / "x.jpg", "2019:05:22 14:52:43")
    got = exif_capture_date(p)
    assert got and got.startswith("2019-05-22T14:52:43")


def test_exif_reader_tolerates_rubbish(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"\xff\xd8not really a jpeg")
    assert exif_capture_date(tmp_path / "a.jpg") is None


# -- through the engine ---------------------------------------------------------

def test_capture_lands_in_the_vault(env, tmp_path):
    inbox = tmp_path / "Composter Inbox"
    inbox.mkdir()
    jpeg_with_date(inbox / "2026-09-25T150000-1.jpg", "2024:07:04 18:06:30")
    sidecar(inbox, "2026-09-25T150000",
            captured_at="2026-09-25T15:00:00-04:00",
            files=["2026-09-25T150000-1.jpg"], text="fireworks on the roof")
    s = IosInboxSource(root=inbox, now=lambda: 1e12)

    result = run_pull(env.cfg, env.db, "ios", now=env.t0, source=s)
    assert result["created"] == 1

    notes = list((env.vault / "zCompost" / "Inbox").rglob("*.md"))
    assert len(notes) == 1
    parsed = parse_note(notes[0].read_text())
    assert parsed.frontmatter["source"] == "ios-share"
    assert parsed.frontmatter["kind"] == "photo"
    assert str(parsed.frontmatter["created"]).startswith("2024-07-04")
    assert "![[zCompost/Media/Inbox/" in parsed.body
    assert "fireworks on the roof" in parsed.body
    # Consumed sidecars and their files are MOVED out of the inbox, never
    # deleted: the inbox empties on the phone, and a bug cannot destroy a
    # capture.
    assert not (inbox / "2026-09-25T150000.json").exists()
    kept = {p.name for p in (inbox / INGESTED).rglob("*") if p.is_file()}
    assert kept == {"2026-09-25T150000.json", "2026-09-25T150000-1.jpg"}
    assert result.get("ingested") == 1
