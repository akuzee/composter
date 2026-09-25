"""Read a photo's capture date from EXIF.

Once a photo leaves the camera roll through an iOS Shortcut, EXIF may be
stripped — so this runs at import or not at all (plan §6). A wrong date here
is not a cosmetic problem: it silently corrupts every timeline view, forever.

Deliberately dependency-free. Pillow would work but pulls a large binary
dependency into a capture layer whose whole virtue is being cheap and boring;
DateTimeOriginal lives in a fixed place in the JPEG APP1 segment.
"""

from __future__ import annotations

import struct
from datetime import datetime
from pathlib import Path

_DATETIME_ORIGINAL = 0x9003
_DATETIME_DIGITIZED = 0x9004
_DATETIME = 0x0132
_EXIF_IFD = 0x8769


def _read_ifd(buf: bytes, offset: int, tiff: int, le: bool, want: set[int],
              found: dict[int, str], depth: int = 0) -> None:
    if depth > 2 or offset + 2 > len(buf):
        return
    fmt = "<" if le else ">"
    (count,) = struct.unpack_from(fmt + "H", buf, offset)
    for i in range(count):
        entry = offset + 2 + i * 12
        if entry + 12 > len(buf):
            return
        tag, typ, n = struct.unpack_from(fmt + "HHI", buf, entry)
        if tag == _EXIF_IFD and typ == 4:
            (sub,) = struct.unpack_from(fmt + "I", buf, entry + 8)
            _read_ifd(buf, tiff + sub, tiff, le, want, found, depth + 1)
        elif tag in want and typ == 2:
            if n <= 4:
                raw = buf[entry + 8:entry + 8 + n]
            else:
                (ptr,) = struct.unpack_from(fmt + "I", buf, entry + 8)
                raw = buf[tiff + ptr:tiff + ptr + n]
            found[tag] = raw.split(b"\x00", 1)[0].decode("ascii", "ignore")


def exif_capture_date(path: Path) -> str | None:
    """ISO8601 local-offset string, or None if the photo carries no EXIF date."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    if not data.startswith(b"\xff\xd8"):
        return None                      # not a JPEG; HEIC/PNG carry no APP1 here

    i, found = 2, {}
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            break
        marker = data[i + 1]
        if marker in (0xD8, 0xD9):
            i += 2
            continue
        (seg_len,) = struct.unpack_from(">H", data, i + 2)
        if marker == 0xE1 and data[i + 4:i + 10] == b"Exif\x00\x00":
            tiff = i + 10
            if data[tiff:tiff + 2] in (b"II", b"MM"):
                le = data[tiff:tiff + 2] == b"II"
                fmt = "<" if le else ">"
                (first,) = struct.unpack_from(fmt + "I", data, tiff + 4)
                _read_ifd(data, tiff + first, tiff, le,
                          {_DATETIME_ORIGINAL, _DATETIME_DIGITIZED, _DATETIME}, found)
            break
        if marker == 0xDA:               # start of scan: no metadata past here
            break
        i += 2 + seg_len

    for tag in (_DATETIME_ORIGINAL, _DATETIME_DIGITIZED, _DATETIME):
        raw = found.get(tag)
        if not raw:
            continue
        try:
            dt = datetime.strptime(raw.strip(), "%Y:%m:%d %H:%M:%S")
        except ValueError:
            continue
        return dt.astimezone().isoformat(timespec="seconds")
    return None
