"""Apple Notes source tests with an injected fake JXA runner — the source's
logic (prefilter, quiet period, locked notes, batching) without touching
Notes.app — plus a full engine integration against a temp vault.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from src.main import run_pull
from src.sources.apple_notes import AppleNotesSource
from src.vault import parse_note

NOW = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)

INDEX = [
    {"id": "n1", "name": "composting metaphor", "locked": False,
     "modified": "2026-08-09T18:32:11.000Z", "created": "2026-08-09T18:32:11.000Z"},
    {"id": "n2", "name": "secret note", "locked": True,
     "modified": "2026-08-08T10:00:00.000Z", "created": "2026-08-08T10:00:00.000Z"},
    {"id": "n3", "name": "half-written thought", "locked": False,
     "modified": "2026-08-10T11:59:30.000Z", "created": "2026-08-10T11:59:00.000Z"},
    {"id": "n4", "name": "older note", "locked": False,
     "modified": "2026-08-01T09:00:00.000Z", "created": "2026-08-01T09:00:00.000Z"},
]

BODIES = {
    "n1": {"id": "n1", "name": "composting metaphor",
           "body": "<div><h1>composting metaphor</h1></div><div>Good scraps, not completeness.</div>"},
    "n4": {"id": "n4", "name": "older note",
           "body": "<div><h1>older note</h1></div><div>An older thought.</div>"},
}

FOLDERS = {"Ideas": ["n1"], "Notes": ["n2", "n3", "n4"]}


class FakeJXA:
    def __init__(self, index=None, bodies=None, folders=None):
        self.index = index if index is not None else [dict(e) for e in INDEX]
        self.bodies = bodies if bodies is not None else dict(BODIES)
        self.folders = folders if folders is not None else dict(FOLDERS)
        self.body_calls: list[list[str]] = []

    def __call__(self, script, args=None, **kw):
        if script == "dump_index.js":
            return json.dumps(self.index)
        if script == "dump_folders.js":
            return json.dumps(self.folders)
        if script == "dump_bodies.js":
            self.body_calls.append(list(args))
            return json.dumps([self.bodies[i] for i in args if i in self.bodies])
        raise AssertionError(script)


def make_source(fake=None, **kw):
    fake = fake or FakeJXA()
    src = AppleNotesSource(runner=fake, now=lambda: NOW, **kw)
    return src, fake


def test_captures_shape():
    src, fake = make_source()
    caps = {c.source_id: c for c in src.captures()}

    assert set(caps) == {"n1", "n2", "n4"}  # n3 is inside the quiet period
    n1 = caps["n1"]
    assert n1.source == "apple-notes"
    assert n1.title == "composting metaphor"
    assert n1.body == "Good scraps, not completeness."  # title dedup + div normalize
    assert n1.created == "2026-08-09T14:32:11-04:00"    # UTC -> local offset
    assert n1.source_ref == "Ideas"
    assert n1.skip_reason is None
    assert caps["n2"].skip_reason == "locked"
    # Locked note's body was never fetched.
    assert all("n2" not in batch for batch in fake.body_calls)


def test_prefilter_skips_unmoved_bodies():
    src, fake = make_source()
    known = {"n1": "2026-08-09T18:32:11.000Z", "n4": "2026-08-01T09:00:00.000Z"}
    caps = src.captures(known_mods=known)
    assert {c.source_id for c in caps} == {"n2"}  # only the locked skip remains
    assert fake.body_calls == []  # zero body fetches when nothing moved


def test_stale_known_mod_refetches():
    src, fake = make_source()
    known = {"n1": "2026-08-01T00:00:00.000Z"}  # n1 moved since
    caps = {c.source_id for c in src.captures(known_mods=known)}
    assert "n1" in caps and "n4" in caps


def test_limit_counts_fetched_notes_newest_first():
    src, fake = make_source()
    caps = [c for c in src.captures(limit=1) if not c.skip_reason]
    assert [c.source_id for c in caps] == ["n1"]  # newest changed note


def test_batching():
    index = [{"id": f"b{i}", "name": f"note {i}", "locked": False,
              "modified": "2026-08-01T09:00:00.000Z",
              "created": "2026-08-01T09:00:00.000Z"} for i in range(120)]
    bodies = {e["id"]: {"id": e["id"], "name": e["name"],
                        "body": f"<div><h1>{e['name']}</h1></div><div>body</div>"}
              for e in index}
    fake = FakeJXA(index=index, bodies=bodies, folders={})
    src, _ = make_source(fake, batch_size=50)
    caps = src.captures()
    assert len(caps) == 120
    assert [len(b) for b in fake.body_calls] == [50, 50, 20]


def test_title_only_note_is_a_capture_not_a_skip():
    """One-line jots are real captures — the title IS the thought."""
    fake = FakeJXA(bodies={**BODIES, "n1": {"id": "n1", "name": "composting metaphor",
                                            "body": "<div><h1>composting metaphor</h1></div>"}})
    src, _ = make_source(fake)
    n1 = next(c for c in src.captures() if c.source_id == "n1")
    assert n1.skip_reason is None
    assert n1.body == ""


def test_truly_empty_note_yields_skip():
    fake = FakeJXA(bodies={**BODIES, "n1": {"id": "n1", "name": "New Note",
                                            "body": "<div><br></div>"}})
    src, _ = make_source(fake)
    n1 = next(c for c in src.captures() if c.source_id == "n1")
    assert n1.skip_reason == "empty"


def test_recently_deleted_notes_are_never_imported():
    folders = {"iCloud/Notes": ["n1", "n4"], "iCloud/Recently Deleted": ["n2"]}
    fake = FakeJXA(folders=folders)
    src, _ = make_source(fake)
    ids = {c.source_id for c in src.captures()}
    assert "n2" not in ids  # deleting a note must not resurrect it via import


def test_excluded_folders_never_enter_the_compost():
    """Quick Notes is the trash-not-compost channel."""
    folders = {"iCloud/Notes": ["n1"], "iCloud/Quick Notes": ["n4"]}
    fake = FakeJXA(folders=folders)
    src, _ = make_source(fake)
    ids = {c.source_id for c in src.captures()}
    assert "n4" not in ids and "n1" in ids


def test_triage_excluded_ids_never_enter_the_compost():
    src, _ = make_source(exclude_ids=frozenset(["n1"]))
    ids = {c.source_id for c in src.captures()}
    assert "n1" not in ids and "n4" in ids


def test_normalized_attachments_are_surfaced():
    """cid-style attachments may not appear in body HTML at all; the
    attachment names from the API must still produce callouts."""
    bodies = dict(BODIES)
    bodies["n1"] = {**BODIES["n1"], "attachments": ["IMG_4242.jpeg"]}
    fake = FakeJXA(bodies=bodies)
    src, _ = make_source(fake)
    n1 = next(c for c in src.captures() if c.source_id == "n1")
    assert "> [!info] Attachment not yet imported: IMG_4242.jpeg" in n1.body


def test_converter_change_does_not_look_like_an_edit():
    """source_hash is over the upstream HTML, not our markdown rendering."""
    src, _ = make_source()
    n1 = next(c for c in src.captures() if c.source_id == "n1")
    assert n1.payload_hash is not None
    assert n1.source_hash == n1.payload_hash


# -- integration through the engine, against a temp vault ---------------------

def test_pull_notes_end_to_end(env):
    fake = FakeJXA()
    src, _ = make_source(fake)

    result = run_pull(env.cfg, env.db, "notes", now=env.t0, source=src)
    assert result["created"] == 2 and result["skipped"] == 1

    notes_dir = env.vault / "zCompost" / "Notes"
    # Upstream folders are mirrored: n1 is in "Ideas", n4 in the default "Notes".
    files = sorted(str(p.relative_to(notes_dir)) for p in notes_dir.rglob("*.md"))
    assert files == ["Ideas/composting metaphor 8-9-26.md", "older note 8-1-26.md"]
    fm = parse_note((notes_dir / "Ideas" / "composting metaphor 8-9-26.md")
                    .read_text()).frontmatter
    assert fm["source"] == "apple-notes"
    assert fm["composter_id"] == "apple-notes:n1"
    assert fm["composter_source_ref"] == "Ideas"

    # Second pull: prefilter means no body fetches, nothing written.
    fake.body_calls.clear()
    result = run_pull(env.cfg, env.db, "notes", now=env.t0, source=src)
    assert result["created"] == 0 and result["updated"] == 0
    assert fake.body_calls == []

    # Upstream edit: only that note is re-fetched and updated.
    fake.index[0]["modified"] = "2026-08-10T11:00:00.000Z"
    fake.bodies["n1"]["body"] = ("<div><h1>composting metaphor</h1></div>"
                                 "<div>Rewritten in Notes.</div>")
    result = run_pull(env.cfg, env.db, "notes", now=env.t0, source=src)
    assert result["updated"] == 1 and result["unchanged"] == 0
    assert fake.body_calls == [["n1"]]
    assert "Rewritten in Notes." in (
        notes_dir / "Ideas" / "composting metaphor 8-9-26.md").read_text()


def test_touched_but_unchanged_note_writes_nothing(env):
    """Apple bumps modification dates on non-substantive events (plan §7.1):
    the body is re-fetched but layer 1 sees the same hash and writes nothing."""
    fake = FakeJXA()
    src, _ = make_source(fake)
    run_pull(env.cfg, env.db, "notes", now=env.t0, source=src)
    path = env.vault / "zCompost" / "Notes" / "Ideas" / "composting metaphor 8-9-26.md"
    before = (path.read_bytes(), path.stat().st_mtime_ns)

    fake.index[0]["modified"] = "2026-08-10T11:30:00.000Z"  # date moved, body identical
    result = run_pull(env.cfg, env.db, "notes", now=env.t0, source=src)
    assert result["unchanged"] == 1
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
