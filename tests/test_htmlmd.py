"""htmlmd unit tests against synthetic Notes-shaped HTML.

NOTE: this fixture is a best guess at Notes' output shape. Phase 0 item 2
captures the REAL kitchen-sink HTML into tests/fixtures/notes_kitchen_sink.html,
which then becomes the authoritative snapshot test (see
test_real_kitchen_sink_snapshot below — it activates once the file exists).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.htmlmd import html_to_markdown

KITCHEN_SINK = Path(__file__).parent / "fixtures" / "notes_kitchen_sink.html"

NOTES_STYLE_HTML = """<html><head></head><body>
<div><h1>Kitchen sink</h1></div>
<div>First paragraph with <b>bold</b> and <i>italic</i> and <u>underline</u> and <s>struck</s>.</div>
<div><br></div>
<div>Second paragraph with a <a href="https://example.com">link</a>.</div>
<div><br></div>
<ul><li>one</li><li>two<ul><li>nested</li></ul></li></ul>
<ol><li>first</li><li>second</li></ol>
<blockquote>quoted line</blockquote>
<table><tbody><tr><td>a</td><td>b</td></tr><tr><td>c</td><td>d</td></tr></tbody></table>
<div><img src="cid:abc-123" alt="photo.jpg"></div>
<div>Last paragraph.</div>
</body></html>"""


@pytest.fixture(scope="module")
def md():
    return html_to_markdown(NOTES_STYLE_HTML, title="Kitchen sink")


def test_title_not_duplicated(md):
    assert "Kitchen sink" not in md  # Notes puts the title in the first line


def test_paragraph_structure_preserved(md):
    assert "First paragraph" in md and "Second paragraph" in md
    para_gap = md.index("Second paragraph") - md.index("First paragraph")
    assert "\n\n" in md[md.index("First paragraph"):md.index("Second paragraph")]
    assert "\n\n\n" not in md  # 3+ blank lines collapsed


def test_inline_formatting(md):
    assert "**bold**" in md
    assert "*italic*" in md
    assert "<u>underline</u>" in md   # kept raw; Obsidian renders it
    assert "<s>struck</s>" in md
    assert "[link](https://example.com)" in md


def test_lists(md):
    assert "- one" in md
    assert "- nested" in md
    assert "1. first" in md and "2. second" in md


def test_blockquote(md):
    assert "> quoted line" in md


def test_table_passes_through_as_raw_html(md):
    assert "<table>" in md and "<td>a</td>" in md  # no GFM serializer, by design


def test_attachment_becomes_callout_not_silence(md):
    assert "> [!info] Attachment not yet imported: photo.jpg" in md
    assert "cid:abc-123" not in md


def test_nbsp_normalized(md):
    assert "Last paragraph." in md


def test_no_divs_survive(md):
    assert "<div" not in md


def test_empty_body():
    assert html_to_markdown("", title="x") == ""
    assert html_to_markdown("<div><h1>x</h1></div>", title="x") == ""


@pytest.mark.skipif(not KITCHEN_SINK.exists(),
                    reason="Phase 0 item 2: real kitchen-sink HTML not captured yet")
def test_real_kitchen_sink_snapshot():
    """Once the real note's HTML is snapshotted, a macOS update that changes
    Notes' HTML shape fails THIS test instead of silently degrading imports."""
    html = KITCHEN_SINK.read_text(encoding="utf-8")
    md = html_to_markdown(html, title="composter kitchen sink")
    golden = KITCHEN_SINK.with_suffix(".golden.md")
    if not golden.exists():
        golden.write_text(md, encoding="utf-8")  # first run records the golden
    assert md == golden.read_text(encoding="utf-8")
