"""Apple Notes HTML -> markdown (plan §8.1).

Notes' body HTML uses one <div> per paragraph and <div><br></div> for blank
lines; naive markdownify collapses those and destroys paragraph structure.
So: normalize structure with bs4 first, then markdownify, then tidy.

Fidelity table (measured against the real kitchen-sink fixture on macOS 26,
tests/fixtures/notes_kitchen_sink.html — the snapshot test guards all of it):
  paragraphs/bold/italic/links/bullet lists   clean
  underline / strikethrough    kept as raw <u>/<s> — Obsidian renders them
  tables                       Notes wraps them in <object>; unwrapped, then
                               passed through as raw HTML — Obsidian renders them
  attachments / inline photos  photos arrive as base64 data-URIs; replaced with
                               a callout placeholder, so nothing is silently lost
  checklists                   LOSSY IN NOTES' OWN API: items arrive as a plain
                               <ul> (no class, no checked flag), and checked
                               items may be dropped entirely. Accepted per plan
                               §8.1 — do not chase the sqlite route for this.
  numbered lists               LOSSY: Notes emits bare <li>s merged into the
                               preceding <ul>; they degrade to bullets.
  blockquotes                  LOSSY: Notes emits plain <div>s; quoting is lost.
  headings typed as HTML h1/h2 survive; heading STYLE applied in the Notes UI
                               arrives as styled spans and degrades to text.
  links                        Notes emits NO <a href> in body HTML — URLs
                               arrive as underlined text. The URL text is
                               unwrapped so Obsidian's autolinking picks it up;
                               link TITLES over other text are unrecoverable.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup
from markdownify import MarkdownConverter

_BLOCK_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "blockquote",
               "pre", "table", "p", "div", "hr"}
_ATTACHMENT_TAGS = ("img", "object", "video", "audio", "embed")

_TABLE_TOKEN = "@@COMPOSTER-TABLE-{n}@@"
_ATT_TOKEN = "@@COMPOSTER-ATT-{n}@@"


class _Converter(MarkdownConverter):
    # Keep as raw HTML — markdown has no underline, and Obsidian renders these.
    def convert_u(self, el, text, *args, **kwargs):
        if not text:
            return ""
        # Notes has no <a href> in body HTML; URLs arrive as <u>https://…</u>.
        # Unwrap those so Obsidian's bare-URL autolinking works.
        if re.fullmatch(r"https?://\S+", text.strip()):
            return text.strip()
        return f"<u>{text}</u>"

    def convert_s(self, el, text, *args, **kwargs):
        return f"<s>{text}</s>" if text else ""

    convert_strike = convert_s
    convert_del = convert_s


def _describe_src(tag) -> str | None:
    """Notes embeds photos as base64 data-URIs — never use src verbatim as a
    display name (it would dump kilobytes of base64 into the note)."""
    src = tag.get("src")
    if not src:
        return None
    if src.startswith("data:"):
        mime = src[5:].split(";", 1)[0].split(",", 1)[0] or "unknown type"
        return f"embedded {mime}"
    return src


def _is_blank_div(div) -> bool:
    kids = [c for c in div.contents if getattr(c, "name", None) or str(c).strip()]
    return not kids or all(getattr(c, "name", None) == "br" for c in kids)


def _normalize_divs(soup: BeautifulSoup) -> None:
    """<div>text</div> -> <p>text</p>; <div><br></div> -> gone (paragraph
    spacing already yields the blank line); divs wrapping block elements
    unwrap. Innermost first, so nesting resolves cleanly."""
    while True:
        div = next((d for d in soup.find_all("div") if not d.find("div")), None)
        if div is None:
            break
        if _is_blank_div(div):
            div.decompose()
        elif any(getattr(c, "name", None) in _BLOCK_TAGS for c in div.contents):
            div.unwrap()
        else:
            div.name = "p"


def _drop_duplicate_title(soup: BeautifulSoup, title: str) -> None:
    """Notes uses the first line as the note's name, so every body would
    otherwise contain its own title twice."""
    first = soup.find(lambda t: t.name in ("h1", "h2", "h3", "div", "p"))
    if first is not None and first.get_text().strip() == title.strip():
        first.decompose()


def html_to_markdown(html: str, title: str = "") -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup.find_all(("html", "head", "body")):
        tag.unwrap()

    if title:
        _drop_duplicate_title(soup, title)

    # Notes wraps tables in <object>; unwrap those first so the table
    # extraction below sees them (measured in the real kitchen-sink fixture).
    for obj in soup.find_all("object"):
        if obj.find("table"):
            obj.unwrap()

    # Notes emits nested lists as SIBLINGS of the parent <li> (invalid HTML,
    # measured in the fixture). Fold each such list into the preceding <li>
    # so markdownify indents it.
    for sublist in soup.find_all(("ul", "ol")):
        prev = sublist.find_previous_sibling()
        if getattr(prev, "name", None) == "li":
            prev.append(sublist.extract())

    # Extract tables and attachments before conversion; reinsert after.
    tables: list[str] = []
    for t in soup.find_all("table"):
        token = _TABLE_TOKEN.format(n=len(tables))
        tables.append(str(t))
        t.replace_with(soup.new_string(token))

    attachments: list[str] = []
    for tag in soup.find_all(_ATTACHMENT_TAGS):
        name = tag.get("alt") or tag.get("title") or _describe_src(tag) or tag.name
        token = _ATT_TOKEN.format(n=len(attachments))
        attachments.append(str(name))
        tag.replace_with(soup.new_string(token))

    _normalize_divs(soup)

    md = _Converter(heading_style="ATX", bullets="-").convert_soup(soup)

    for n, raw in enumerate(tables):
        md = md.replace(_TABLE_TOKEN.format(n=n), f"\n\n{raw}\n\n")
    for n, name in enumerate(attachments):
        md = md.replace(_ATT_TOKEN.format(n=n),
                        f"\n\n> [!info] Attachment not yet imported: {name}\n\n")

    md = md.replace("\u00a0", " ")  # Notes salts its HTML with nbsp
    md = "\n".join(line.rstrip() for line in md.split("\n"))
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()
