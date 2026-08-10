"""Audio -> transcript, via ffmpeg and whisper.cpp (plan §8.2).

Nothing here knows what a vault is. It takes an audio file, returns prose and
a duration, and writes the raw whisper JSON to state/transcripts/ so a better
model can be re-run later without re-reading the original audio.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

# Whisper.cpp requires 16 kHz mono PCM; anything else silently degrades.
FFMPEG_ARGS = ["-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le"]

# A pause longer than this starts a new paragraph. Speech has no other
# structure to grip, and a downstream chunker needs paragraphs.
PARAGRAPH_GAP_MS = 1500


class TranscribeError(RuntimeError):
    pass


@dataclass
class Transcript:
    text: str
    duration_seconds: float
    model: str
    json_path: Path | None = None


def _tool(name: str, alternatives: tuple[str, ...] = ()) -> str:
    for candidate in (name, *alternatives):
        found = shutil.which(candidate)
        if found:
            return found
    raise TranscribeError(f"{name} not found on PATH")


def probe_duration(path: Path) -> float | None:
    """Seconds, or None if ffprobe cannot make sense of the file.

    This is the strongest of the three partial-file gates: a truncated or
    still-syncing .m4a fails it, and ffmpeg is already installed so it is free.
    """
    try:
        proc = subprocess.run(
            [_tool("ffprobe"), "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=60)
    except (TranscribeError, OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        seconds = float(proc.stdout.strip())
    except ValueError:
        return None
    return seconds if seconds > 0 else None


def to_wav(src: Path, dest: Path) -> None:
    proc = subprocess.run(
        [_tool("ffmpeg"), "-nostdin", "-loglevel", "error", "-y",
         "-i", str(src), *FFMPEG_ARGS, str(dest)],
        capture_output=True, text=True, timeout=1800)
    if proc.returncode != 0 or not dest.is_file():
        raise TranscribeError(f"ffmpeg failed on {src.name}: {proc.stderr.strip()[:300]}")


def assemble(segments: list[dict]) -> str:
    """Join whisper segments into readable prose.

    Punctuation is preserved exactly as whisper emits it — stripping it would
    leave a downstream chunker with nothing to split on.
    """
    paragraphs: list[list[str]] = []
    current: list[str] = []
    prev_end: int | None = None

    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        offsets = seg.get("offsets") or {}
        start, end = offsets.get("from"), offsets.get("to")
        if (prev_end is not None and start is not None
                and start - prev_end >= PARAGRAPH_GAP_MS and current):
            paragraphs.append(current)
            current = []
        current.append(text)
        if end is not None:
            prev_end = end

    if current:
        paragraphs.append(current)
    return "\n\n".join(" ".join(p) for p in paragraphs).strip()


def transcribe(src: Path, model: Path, transcripts_dir: Path,
               stem: str) -> Transcript:
    """Convert and transcribe. `stem` names the retained JSON."""
    model = Path(model).expanduser()
    if not model.is_file():
        raise TranscribeError(f"whisper model not found: {model}")
    whisper = _tool("whisper-cli", ("whisper-cpp", "main"))

    duration = probe_duration(src)
    if duration is None:
        raise TranscribeError(f"ffprobe could not read {src.name} — "
                              f"truncated, still syncing, or not audio")

    transcripts_dir.mkdir(parents=True, exist_ok=True)
    out_stem = transcripts_dir / stem
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "audio.wav"
        to_wav(src, wav)
        proc = subprocess.run(
            [whisper, "-m", str(model), "-oj", "-of", str(out_stem), str(wav)],
            capture_output=True, text=True, timeout=7200)
    json_path = out_stem.with_suffix(".json")
    if proc.returncode != 0 or not json_path.is_file():
        raise TranscribeError(
            f"whisper failed on {src.name}: {proc.stderr.strip()[-300:]}")

    data = json.loads(json_path.read_text(encoding="utf-8"))
    return Transcript(
        text=assemble(data.get("transcription") or []),
        duration_seconds=duration,
        model=model.name,
        json_path=json_path,
    )
