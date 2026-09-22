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


def test_tools_are_found_without_a_useful_path(monkeypatch):
    """launchd hands a job a minimal PATH with no Homebrew on it. Relying on
    PATH alone made every tool lookup fail under the scheduler while working
    from a shell — and silently, since a missing ffprobe is indistinguishable
    from an unreadable recording."""
    import src.transcribe as tr
    monkeypatch.setattr(tr.shutil, "which", lambda name: None)
    if not Path("/opt/homebrew/bin/ffprobe").exists():
        pytest.skip("Homebrew ffprobe not installed here")
    assert tr._tool("ffprobe") == "/opt/homebrew/bin/ffprobe"


def test_missing_tool_names_where_it_looked(monkeypatch):
    import src.transcribe as tr
    monkeypatch.setattr(tr.shutil, "which", lambda name: None)
    monkeypatch.setattr(tr, "_TOOL_DIRS", ())
    with pytest.raises(TranscribeError, match="Searched PATH"):
        tr._tool("definitely-not-a-real-tool")


def test_non_speech_annotations_are_stripped():
    """whisper describes sound it cannot transcribe: [MUSIC], [SPLAT],
    [BLANK_AUDIO]. Those are descriptions, not words that were said, so they
    must not end up as note titles or body text."""
    from src.transcribe import strip_non_speech
    assert strip_non_speech("[SPLAT]") == ""
    assert strip_non_speech("[BLANK_AUDIO]") == ""
    assert strip_non_speech("[BLANK_AUDIO] Alright so [MUSIC] here we go") == \
        "Alright so here we go"
    assert strip_non_speech("a normal sentence.") == "a normal sentence."
    # whisper uses parentheses for the same purpose
    assert strip_non_speech("(upbeat music)") == ""
    assert strip_non_speech("(soft laughter)") == ""
    # ...but parentheses in real speech must survive
    assert strip_non_speech("I said (quietly) that it matters") == \
        "I said (quietly) that it matters"


def test_annotation_only_recording_yields_nothing():
    assert assemble([seg(" [SPLAT]", 0, 500)]) == ""
    assert assemble([seg(" [BLANK_AUDIO]", 0, 500), seg(" [MUSIC]", 600, 900)]) == ""
