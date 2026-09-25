"""Phase 6: frontmatter for pre-existing notes — the one write outside the
managed folder."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from src.backfill import (
    Proposal,
    apply_one,
    candidates,
    infer_date,
    infer_kind_and_authorship,
    propose,
    read_proposal,
    verify_snapshot,
)
from src.vault import parse_note


def note(env, rel: str, text: str = "some prose\n") -> Path:
    p = env.vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# -- inference ------------------------------------------------------------------

def test_unambiguous_filename_date_is_high_confidence(env):
    p = note(env, "notes 8-30-25.md")
    iso, ev, conf = infer_date(p, p.stem)
    assert iso.startswith("2025-08-30") and conf == "high"


def test_ambiguous_date_is_flagged_not_guessed_silently(env):
    """3-9-26 could be March 9th or September 3rd. Read as M-D-Y, but say so."""
    p = note(env, "research 3-9-26.md")
    iso, ev, conf = infer_date(p, p.stem)
    assert iso.startswith("2026-03-09")
    assert conf == "medium" and "M-D-Y" in ev


def test_missing_year_is_low_confidence(env):
    p = note(env, "interests dump 12-4.md")
    _, ev, conf = infer_date(p, p.stem)
    assert conf == "low" and "year from birthtime" in ev


def test_leading_date_is_found(env):
    p = note(env, "9-22 crumb about workflows.md")
    iso, ev, conf = infer_date(p, p.stem)
    assert iso[5:10] == "09-22" and "filename head" in ev


def test_no_date_falls_back_to_birthtime(env):
    p = note(env, "harrison notes.md")
    iso, ev, conf = infer_date(p, p.stem)
    assert ev == "filesystem birthtime" and iso


def test_clippings_are_marked_as_someone_elses_writing(env):
    """Without this, 'what was I thinking about' returns other people's essays
    — a correctness bug no amount of embedding quality fixes."""
    kind, who = infer_kind_and_authorship(Path("zClippings/essay.md"), "text")
    assert (kind, who) == ("clipping", "theirs")
    kind, who = infer_kind_and_authorship(Path("Main/idea.md"), "text")
    assert (kind, who) == ("note", "mine")


def test_web_clipper_frontmatter_implies_theirs(env):
    kind, who = infer_kind_and_authorship(
        Path("Misc/x.md"), "---\nsource: https://example.com\nauthor: Someone\n---\n")
    assert who == "theirs"


# -- the prose is never touched ---------------------------------------------------

def test_apply_prepends_and_leaves_prose_byte_identical(env):
    p = note(env, "Main/a note.md", "# Heading\n\nbody text\n\n- a list\n")
    before, after = apply_one(p, Proposal("Main/a note.md", "2026-01-01T12:00:00-05:00",
                                          "note", "mine", "", "high", ""), "NOW")
    assert after.endswith(before), "prose must survive byte for byte"
    fm = parse_note(after).frontmatter
    assert fm["created"] == "2026-01-01T12:00:00-05:00"
    assert fm["composter_managed"] is False, "backfilled notes are not managed"


def test_empty_created_writes_no_key_at_all(env):
    """An absent field is honest; a wrong one silently corrupts the timeline."""
    p = note(env, "Main/undated.md")
    _, after = apply_one(p, Proposal("Main/undated.md", "", "note", "mine",
                                     "", "low", ""), "NOW")
    fm = parse_note(after).frontmatter
    assert "created" not in fm
    assert fm["kind"] == "note"


def test_refuses_a_file_that_already_has_frontmatter(env):
    p = note(env, "Main/clipped.md", "---\ntitle: x\n---\n\nbody\n")
    with pytest.raises(ValueError, match="already has frontmatter"):
        apply_one(p, Proposal("Main/clipped.md", "", "note", "mine", "", "", ""), "NOW")


# -- scope ------------------------------------------------------------------------

def test_managed_folder_is_never_a_candidate(env):
    """Backfill touches the curated tree, never composter's own output."""
    note(env, "Main/plain.md")
    note(env, "zCompost/Notes/managed.md", "---\ncomposter_id: x\n---\n\nbody\n")
    rels = {str(p.relative_to(env.vault)) for p in candidates(env.cfg)}
    assert "Main/plain.md" in rels
    assert not any(r.startswith("zCompost/") for r in rels)


def test_notes_that_already_have_a_date_are_left_alone(env):
    note(env, "Main/dated.md", "---\ncreated: 2020-01-01\n---\n\nbody\n")
    rels = {str(p.relative_to(env.vault)) for p in candidates(env.cfg)}
    assert "Main/dated.md" not in rels


def test_proposal_round_trips(env, tmp_path):
    note(env, "Main/one 8-30-25.md")
    note(env, "zClippings/two.md")
    tsv = tmp_path / "p.tsv"
    rows = propose(env.cfg, tsv)
    back = read_proposal(tsv)
    assert {r.relpath for r in back} == {r.relpath for r in rows}
    rels = {r.relpath for r in back}
    assert {"Main/one 8-30-25.md", "zClippings/two.md"} <= rels
    by = {r.relpath: r for r in back}
    assert by["zClippings/two.md"].authorship == "theirs"
    assert by["Main/one 8-30-25.md"].created.startswith("2025-08-30")


def test_snapshot_verification_catches_a_missing_file(env, tmp_path):
    note(env, "Main/only here.md")
    snap = tmp_path / "snap"
    (snap / "Main").mkdir(parents=True)
    problems = verify_snapshot(env.cfg, snap)
    assert any("MISSING FROM SNAPSHOT" in p for p in problems)
