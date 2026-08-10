"""Phase 4: the audio pipeline.

Paragraph assembly is tested on synthetic segment data. The end-to-end test
generates real speech with macOS `say`, runs it through ffmpeg and whisper,
and is skipped when those tools are absent.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.transcribe import (
    PARAGRAPH_GAP_MS,
    TranscribeError,
    Transcript,
    assemble,
    probe_duration,
    transcribe,
)

HAVE_TOOLS = all(shutil.which(t) for t in ("ffmpeg", "ffprobe", "say")) and (
    shutil.which("whisper-cli") or shutil.which("whisper-cpp"))
MODEL = Path.home() / ".cache/whisper-models/ggml-base.en.bin"
needs_tools = pytest.mark.skipif(
    not (HAVE_TOOLS and MODEL.is_file()),
    reason="ffmpeg/say/whisper-cli or the whisper model are unavailable")


def seg(text, start, end):
    return {"text": text, "offsets": {"from": start, "to": end}}


# -- paragraph assembly --------------------------------------------------------

def test_short_gaps_stay_in_one_paragraph():
    out = assemble([seg(" One.", 0, 1000), seg(" Two.", 1200, 2000)])
    assert out == "One. Two."


def test_long_gap_starts_a_paragraph():
    out = assemble([seg(" Before the pause.", 0, 1000),
                    seg(" After the pause.", 1000 + PARAGRAPH_GAP_MS, 4000)])
    assert out == "Before the pause.\n\nAfter the pause."


def test_punctuation_is_preserved():
    """A downstream chunker has nothing to grip without sentence punctuation."""
    out = assemble([seg(" Is this it? Maybe.", 0, 2000)])
    assert "?" in out and out.endswith(".")


def test_empty_and_blank_segments():
    assert assemble([]) == ""
    assert assemble([seg("   ", 0, 500)]) == ""


def test_segments_without_offsets_do_not_crash():
    out = assemble([{"text": " No offsets here."}, seg(" Then this.", 0, 100)])
    assert "No offsets here." in out and "Then this." in out


# -- real audio ---------------------------------------------------------------

@needs_tools
def test_end_to_end_transcription(tmp_path):
    aiff = tmp_path / "spoken.aiff"
    subprocess.run(
        ["say", "-o", str(aiff),
         "Good scraps, not completeness. The unit of work is the smallest "
         "complete thing."],
        check=True, capture_output=True, timeout=120)

    duration = probe_duration(aiff)
    assert duration and duration > 1

    result = transcribe(aiff, MODEL, tmp_path / "transcripts", stem="probe")
    assert isinstance(result, Transcript)
    lowered = result.text.lower()
    assert "scraps" in lowered and "completeness" in lowered
    assert result.duration_seconds == pytest.approx(duration, abs=0.5)
    # Raw whisper JSON is retained so a better model can be re-run later
    # without going back to the original audio.
    assert result.json_path and result.json_path.is_file()


@needs_tools
def test_truncated_file_is_rejected_not_transcribed(tmp_path):
    """The strongest of the three partial-file gates: ffprobe must refuse a
    file that is still being written."""
    bad = tmp_path / "half.m4a"
    bad.write_bytes(b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 200)
    assert probe_duration(bad) is None
    with pytest.raises(TranscribeError):
        transcribe(bad, MODEL, tmp_path / "transcripts", stem="bad")


def test_missing_model_is_a_clear_error(tmp_path):
    with pytest.raises(TranscribeError, match="model not found"):
        transcribe(tmp_path / "x.m4a", tmp_path / "nope.bin",
                   tmp_path / "transcripts", stem="x")
