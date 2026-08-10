"""High-precision detectors for mechanically-obvious junk.

These judge FORM, not value. "Is this mostly digits" is checkable; "is this
thought worth keeping" is not, and the earlier attempt to do the latter with
keyword rules failed badly. Every rule here must be tight enough that a human
skimming its matches agrees with essentially all of them — precision over
recall, always. Anything not matched simply imports.

Each rule returns a reason string or None. Run `python triage/obvious.py` to
print every rule's matches so precision can be eyeballed before trusting it.
"""

from __future__ import annotations

import re
import unicodedata

OBJ = "￼"  # object-replacement char: Notes' inline attachment marker

PLACEHOLDER_TITLES = {
    "new note", "untitled", "note", "asdf", "asdfasdf", "test", "temp", "tmp",
    "aaa", "aa", "xxx", "blah", "bosquejo", "-", "--", "/", "\\", ".", "..",
}

# Real key formats only. Nothing heuristic: each of these is a vendor-defined
# shape, so a match is a fact rather than a guess.
KEY_PATTERNS = [
    ("OpenAI API key", re.compile(r"\bsk-[A-Za-z0-9_\-]{32,}")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("Stripe key", re.compile(r"\b[sr]k_(live|test)_[A-Za-z0-9]{20,}")),
]


def _body(title: str, snippet: str) -> str:
    s = (snippet or "").strip()
    t = (title or "").strip()
    return s[len(t):].strip() if s.startswith(t) else s


def rule_empty(title: str, body: str) -> str | None:
    """Nothing there: no body text, and a title that carries no meaning."""
    stripped = body.replace(OBJ, "").strip()
    if stripped:
        return None
    t = title.strip()
    tl = t.lower()
    # Say so when an image is attached — "empty" must never read as "nothing
    # here" when there is a photo the text importer simply cannot hold.
    extra = ", but has an attachment" if OBJ in body else ""
    if tl in PLACEHOLDER_TITLES:
        return f"placeholder title, no text{extra}"
    if len(t) <= 2:
        return f"title is one or two characters, no text{extra}"
    # A title of only punctuation/symbols/emoji carries no retrievable text.
    if t and all(unicodedata.category(c)[0] in "PSZC" for c in t):
        return f"title is punctuation or symbols only, no text{extra}"
    return None


def rule_attachment_only(title: str, body: str) -> str | None:
    """An image/PDF with no words. The file is still in Apple Notes; there is
    simply no text for a text archive to hold."""
    if OBJ not in body:
        return None
    if body.replace(OBJ, "").strip():
        return None
    words = [w for w in re.findall(r"[A-Za-z']{2,}", title)]
    if len(words) <= 2:
        return "attachment with no text and no descriptive title"
    return None


def rule_numeric(title: str, body: str) -> str | None:
    """Bare figures: scores, amounts, codes, tallies. No prose."""
    text = body.replace(OBJ, " ").strip()
    if not text or len(text) > 400:
        return None
    letters = sum(c.isalpha() for c in text)
    digits = sum(c.isdigit() for c in text)
    if digits < 4:
        return None
    words = re.findall(r"[A-Za-z']{3,}", text)
    if digits > letters and len(words) <= 4:
        return "almost entirely digits"
    return None


# A "scratch calculation" rule was written and then deleted: on the real
# library it matched a work note, study notes, and a weight log — because any
# note containing "100-150" or "14-17" looks like arithmetic. 1-in-4 precision
# is not worth the recall. Numbers alone are covered by rule_numeric, which
# requires digits to dominate the note rather than merely appear in it.


def rule_live_key(title: str, body: str) -> str | None:
    """A credential in a real vendor key format. Not a judgment call."""
    text = f"{title}\n{body}"
    for label, pat in KEY_PATTERNS:
        if pat.search(text):
            return f"contains what looks like a live {label}"
    return None


# Order matters: the first match wins, and live-key must outrank everything
# so a credential is never filed as "just numbers".
RULES = [
    ("live-key", rule_live_key),
    ("empty", rule_empty),
    ("numeric", rule_numeric),
    ("attachment-only", rule_attachment_only),
]

# attachment-only is NOT junk — it is media a text importer cannot hold. It is
# surfaced separately so the owner decides, and never defaulted to trash.
NOT_JUNK = {"attachment-only"}


def detect(title: str, snippet: str) -> tuple[str, str] | None:
    """-> (rule_name, reason) for the first matching rule, else None."""
    body = _body(title, snippet)
    for name, fn in RULES:
        reason = fn(title or "", body)
        if reason:
            return name, reason
    return None


def _main() -> None:
    import json
    from collections import defaultdict
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "state" / "triage_candidates.jsonl"
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").split("\n") if l.strip()]
    hits = defaultdict(list)
    for r in rows:
        got = detect(r["title"], r["snippet"])
        if got:
            hits[got[0]].append(r)

    total = 0
    for name, _ in RULES:
        rs = hits[name]
        total += len(rs)
        print(f"\n{'=' * 62}\n{name}: {len(rs)} of {len(rows)}\n{'=' * 62}")
        for r in rs[:25]:
            b = _body(r["title"], r["snippet"]).replace(OBJ, "[attachment]")
            b = " ".join(b.split())
            print(f"  {r['title'][:44]!r:48} | {b[:52]}")
        if len(rs) > 25:
            print(f"  … and {len(rs) - 25} more")
    print(f"\nTOTAL flagged: {total} of {len(rows)} "
          f"({100 * total / len(rows):.0f}%) — everything else imports.")


if __name__ == "__main__":
    _main()
