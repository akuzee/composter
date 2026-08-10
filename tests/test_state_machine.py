"""The seven Phase-1 transitions (plan §12) plus the writer's invariants."""

from __future__ import annotations

import json
import shutil

import pytest

from src.db import TransitionError
from src.main import run_resolve
from src.vault import (
    ContainmentError,
    SentinelError,
    VaultWriter,
    parse_note,
)
from tests.conftest import ENTRY, VAULT_ID


# -- 1. create -> unchanged (zero bytes written) ------------------------------

def test_create_writes_expected_file(seeded):
    files = seeded.managed_files()
    assert len(files) == 1
    assert files[0].name == "composting metaphor 8-9-26.md"  # owner's convention
    text = files[0].read_text()
    parsed = parse_note(text)
    fm = parsed.frontmatter
    assert fm["composter_id"] == "fixture:fx-001"
    assert fm["source"] == "fixture"
    assert fm["created"] == "2026-08-09T14:32:11-04:00"
    assert fm["captured"] is not None and fm["captured"] != fm["created"]
    assert fm["composter_authorship"] == "mine"
    assert fm["composter_rev"] == 1
    assert fm["composter_managed"] is True
    assert fm["zone"] == "produced"
    assert fm["tags"] == ["compost/fixture"]
    assert parsed.body == ENTRY["body"]
    assert seeded.item().state == "managed"


def test_rerun_is_byte_identical(seeded):
    path = seeded.managed_files()[0]
    before_bytes = path.read_bytes()
    before_mtime = path.stat().st_mtime_ns
    result = seeded.pull(minutes=15)
    assert result["unchanged"] == 1 and result["created"] == 0 and result["updated"] == 0
    assert path.read_bytes() == before_bytes
    assert path.stat().st_mtime_ns == before_mtime  # file was never opened for write


# -- 2. update ---------------------------------------------------------------

def test_upstream_change_updates_file(seeded):
    entry = dict(ENTRY, body=ENTRY["body"] + "\n\nA new third paragraph.")
    seeded.set_fixture([entry])
    result = seeded.pull(minutes=15)
    assert result["updated"] == 1
    parsed = parse_note(seeded.managed_files()[0].read_text())
    assert "A new third paragraph." in parsed.body
    assert parsed.frontmatter["composter_rev"] == 2
    assert seeded.item().rev == 2


# -- 3. annotate below fence, then update: annotation survives ----------------

def test_annotation_below_fence_survives_update(seeded):
    path = seeded.managed_files()[0]
    annotation = "\nMy own thought, added by hand.\n\n[[a poem 3-9-26]]\n"
    path.write_text(path.read_text() + annotation)

    entry = dict(ENTRY, body="Rewritten upstream body.")
    seeded.set_fixture([entry])
    result = seeded.pull(minutes=15)
    assert result["updated"] == 1

    text = path.read_text()
    parsed = parse_note(text)
    assert parsed.body == "Rewritten upstream body."
    assert text.endswith(annotation)  # byte-for-byte, per plan §7.3 layer 2


def test_hand_added_frontmatter_survives_update(seeded):
    path = seeded.managed_files()[0]
    text = path.read_text()
    # Owner marks it consumed and adds a personal key.
    text = text.replace("consumed: null", "consumed: 2026-08-10")
    text = text.replace("---\n\n<!--", "must-read: true\n---\n\n<!--")
    path.write_text(text)

    seeded.set_fixture([dict(ENTRY, body="changed upstream")])
    assert seeded.pull(minutes=15)["updated"] == 1
    fm = parse_note(path.read_text()).frontmatter
    assert str(fm["consumed"]) == "2026-08-10"
    assert fm["must-read"] is True


# -- 4. edit inside fence + upstream edit -> conflict, file untouched ----------

def test_local_edit_plus_upstream_edit_is_conflict(seeded):
    path = seeded.managed_files()[0]
    tampered = path.read_text().replace("Tracking my inner life", "I rewrote this by hand")
    path.write_text(tampered)
    before = path.read_bytes()

    seeded.set_fixture([dict(ENTRY, body="upstream moved on")])
    result = seeded.pull(minutes=15)
    assert result["conflict"] == 1
    assert path.read_bytes() == before  # write nothing
    assert seeded.item().state == "conflict"

    pending = list((seeded.cfg.pending_dir).glob("*.json"))
    assert len(pending) == 1
    payload = json.loads(pending[0].read_text())
    assert payload["body"] == "upstream moved on"

    # Re-running while conflicted stays parked and still writes nothing.
    result = seeded.pull(minutes=30)
    assert result["conflict"] == 1
    assert path.read_bytes() == before


def test_resolve_take_upstream(seeded):
    path = seeded.managed_files()[0]
    path.write_text(path.read_text().replace("Tracking", "Hand-edited"))
    seeded.set_fixture([dict(ENTRY, body="upstream moved on")])
    seeded.pull(minutes=15)

    outcome = run_resolve(seeded.cfg, seeded.db, "fixture:fx-001", take_upstream=True,
                          now=seeded.t0)
    assert "superseded" in outcome or "_superseded" in outcome
    item = seeded.item()
    assert item.state == "managed"
    assert parse_note(path.read_text()).body == "upstream moved on"
    superseded = list((seeded.vault / "zCompost" / "_superseded").rglob("*.md"))
    assert len(superseded) == 1  # local edits preserved, never destroyed
    assert "Hand-edited" in superseded[0].read_text()
    # Conflict resolved: next pull is quiet.
    assert seeded.pull(minutes=30)["unchanged"] == 1


def test_resolve_keep_mine_graduates(seeded):
    path = seeded.managed_files()[0]
    path.write_text(path.read_text().replace("Tracking", "Hand-edited"))
    seeded.set_fixture([dict(ENTRY, body="upstream moved on")])
    seeded.pull(minutes=15)

    run_resolve(seeded.cfg, seeded.db, "fixture:fx-001", take_upstream=False, now=seeded.t0)
    assert seeded.item().state == "graduated"
    before = path.read_bytes()
    seeded.pull(minutes=30)
    assert path.read_bytes() == before  # never written again


def test_on_local_edit_graduate_config(seeded):
    seeded.cfg.on_local_edit = "graduate"
    path = seeded.managed_files()[0]
    path.write_text(path.read_text().replace("Tracking", "Hand-edited"))
    seeded.set_fixture([dict(ENTRY, body="upstream moved on")])
    result = seeded.pull(minutes=15)
    assert result["graduated"] == 1 and result["conflict"] == 0
    assert seeded.item().state == "graduated"


# -- 5. move out of zCompost/ -> graduated -------------------------------------

def test_graduation_by_moving_out(seeded):
    path = seeded.managed_files()[0]
    dest = seeded.vault / "Main" / "Areas" / "Art" / path.name
    shutil.move(path, dest)
    dest.write_text(dest.read_text() + "\nMy own addition after graduating.\n")

    result = seeded.pull(minutes=15)
    assert result["graduated"] == 1
    item = seeded.item()
    assert item.state == "graduated"

    # Upstream keeps changing; the graduated file is never touched again.
    before = dest.read_bytes()
    seeded.set_fixture([dict(ENTRY, body="upstream changed after graduation")])
    seeded.pull(minutes=30)
    assert dest.read_bytes() == before

    # Terminal means terminal: dragging it back in does not resume management.
    shutil.move(dest, seeded.vault / "zCompost" / "Notes" / path.name)
    seeded.pull(minutes=45)
    assert seeded.item().state == "graduated"


def test_opt_out_flag_graduates_in_place(seeded):
    path = seeded.managed_files()[0]
    path.write_text(path.read_text().replace("composter_managed: true",
                                             "composter_managed: false"))
    seeded.reindex(minutes=15)
    assert seeded.item().state == "graduated"


def test_move_within_zcompost_keeps_managing(seeded):
    path = seeded.managed_files()[0]
    dest = seeded.vault / "zCompost" / "Inbox" / path.name
    shutil.move(path, dest)
    seeded.reindex(minutes=15)
    item = seeded.item()
    assert item.state == "managed"
    assert item.path == f"zCompost/Inbox/{path.name}"
    # And updates follow it to the new location.
    seeded.set_fixture([dict(ENTRY, body="updated after reorganizing the heap")])
    assert seeded.pull(minutes=30)["updated"] == 1
    assert "reorganizing the heap" in dest.read_text()


# -- 6 & 7. delete -> dismissed (with grace), stays dismissed -------------------

def test_dismissal_requires_grace_period(seeded):
    path = seeded.managed_files()[0]
    path.unlink()  # owner deletes the note (test simulates the owner)

    seeded.reindex(minutes=0)
    assert seeded.item().state == "managed"  # missing once: not dismissed
    assert seeded.item().missing_runs == 1

    seeded.reindex(minutes=30)
    assert seeded.item().state == "managed"  # 2 runs but < 1 hour

    seeded.reindex(minutes=45)
    assert seeded.item().state == "managed"  # 3 runs but only 45 min

    seeded.reindex(minutes=61)
    assert seeded.item().state == "dismissed"  # >= 3 runs AND >= 1 hour


def test_deleted_note_edited_upstream_does_not_error_or_resurrect(seeded):
    """The nastiest ordering: delete the file, then edit it in Apple Notes.
    Must not recreate it, and must not fail the run (a failed run three times
    over raises the escalation alarm)."""
    seeded.managed_files()[0].unlink()
    seeded.set_fixture([dict(ENTRY, body="upstream changed after I deleted it")])

    result = seeded.pull(minutes=15)
    assert result["error"] == 0 and result["ok"] is True
    assert seeded.managed_files() == [], "must not resurrect a deleted note"

    for m in (45, 75):
        seeded.pull(minutes=m)
    assert seeded.item().state == "dismissed"
    assert seeded.managed_files() == []


def test_dismissed_is_never_recreated(seeded):
    seeded.managed_files()[0].unlink()
    for m in (0, 30, 61):
        seeded.reindex(minutes=m)
    assert seeded.item().state == "dismissed"

    result = seeded.pull(minutes=90)
    assert result["created"] == 0
    assert seeded.managed_files() == []  # the single most infuriating bug, absent
    assert seeded.item().state == "dismissed"


def test_sync_lag_is_not_a_deletion(seeded):
    path = seeded.managed_files()[0]
    content = path.read_bytes()
    path.unlink()

    seeded.reindex(minutes=0)
    seeded.reindex(minutes=30)
    assert seeded.item().missing_runs == 2

    path.write_bytes(content)  # sync catches up
    seeded.reindex(minutes=61)
    item = seeded.item()
    assert item.state == "managed"
    assert item.missing_runs == 0  # counter fully reset


# -- terminal states are enforced at the ledger, not by convention -------------

def test_terminal_transitions_raise(seeded):
    seeded.managed_files()[0].unlink()
    for m in (0, 30, 61):
        seeded.reindex(minutes=m)
    item = seeded.item()
    assert item.state == "dismissed"
    with pytest.raises(TransitionError):
        seeded.db.set_state(item, "managed", "2026-08-10T12:00:00+00:00")


# -- writer invariants ----------------------------------------------------------

def test_source_folder_is_mirrored_on_create(env):
    from src.vault import subfolder_for
    assert subfolder_for("Notes", "iCloud/Notebook") == "Notes/Notebook"
    assert subfolder_for("Notes", "iCloud/Notebook/drafts") == "Notes/Notebook/drafts"
    assert subfolder_for("Notes", "iCloud/Notes") == "Notes"   # no Notes/Notes
    assert subfolder_for("Notes", "Google/Notes") == "Notes"
    assert subfolder_for("Notes", None) == "Notes"
    assert subfolder_for("Notes", "iCloud/../escape") == "Notes/escape"

    env.set_fixture([dict(ENTRY, source_ref="iCloud/thoughts")])
    env.pull()
    p = env.vault / "zCompost" / "Notes" / "thoughts" / "composting metaphor 8-9-26.md"
    assert p.is_file()
    assert env.item().path == "zCompost/Notes/thoughts/composting metaphor 8-9-26.md"


def test_relocate_moves_into_mirrored_folders(env):
    from src.main import run_relocate
    env.set_fixture([dict(ENTRY)])                       # no source_ref -> flat
    env.pull()
    flat = env.vault / "zCompost" / "Notes" / "composting metaphor 8-9-26.md"
    assert flat.is_file()

    env.set_fixture([dict(ENTRY, source_ref="iCloud/quotes")])
    env.pull(minutes=15)                                 # updates in place, no move
    assert flat.is_file()

    preview = run_relocate(env.cfg, env.db, dry_run=True)
    assert preview["moved"] == 1 and flat.is_file(), "dry run must move nothing"

    result = run_relocate(env.cfg, env.db)
    assert result["moved"] == 1
    moved = env.vault / "zCompost" / "Notes" / "quotes" / "composting metaphor 8-9-26.md"
    assert moved.is_file() and not flat.exists()
    assert env.item().path == "zCompost/Notes/quotes/composting metaphor 8-9-26.md"
    # Idempotent, and the ledger followed the file.
    assert run_relocate(env.cfg, env.db)["moved"] == 0
    assert env.pull(minutes=30)["unchanged"] == 1


def test_relocate_never_leaves_the_managed_root(env):
    writer = VaultWriter(env.vault, "zCompost", VAULT_ID)
    with pytest.raises(ContainmentError):
        writer.relocate("Main/Areas/Art/essay.md", "Notes")
    with pytest.raises(ContainmentError):
        writer.relocate("zCompost/Notes/x.md", "../../Main")


def test_containment_blocks_writes_outside_managed_root(env):
    writer = VaultWriter(env.vault, "zCompost", VAULT_ID)
    with pytest.raises(ContainmentError):
        writer._write_bytes(env.vault / "Main" / "evil.md", b"nope")
    with pytest.raises(ContainmentError):
        writer._write_bytes(env.vault / "zCompost" / ".." / "evil.md", b"nope")
    with pytest.raises(ContainmentError):
        writer.supersede("Main/Areas/Art/essay.md", "2026-08-10")


def test_writer_refuses_without_sentinel(tmp_path):
    (tmp_path / "notavault").mkdir()
    with pytest.raises(SentinelError):
        VaultWriter(tmp_path / "notavault", "zCompost", VAULT_ID)


def test_writer_refuses_wrong_vault_id(env):
    with pytest.raises(SentinelError):
        VaultWriter(env.vault, "zCompost", "some-other-vault")


def test_dry_run_writes_nothing(env):
    env.set_fixture([dict(ENTRY)])
    result = env.pull(dry_run=True)
    assert result["created"] == 1 and result["dry_run"] is True
    assert env.managed_files() == []
    assert env.item() is None  # ledger untouched too


def test_circuit_breaker_caps_new_files(env):
    env.cfg.max_new_per_run = 2
    entries = [dict(ENTRY, id=f"fx-{i:03d}", title=f"note {i}") for i in range(5)]
    env.set_fixture(entries)
    result = env.pull()
    assert result["created"] == 2
    assert result["ok"] is False  # a tripped breaker is an alarm, not a success
    assert len(env.managed_files()) == 2


def test_skipped_capture_recorded_and_recheckable(env):
    env.set_fixture([dict(ENTRY, skip="locked")])
    result = env.pull()
    assert result["skipped"] == 1
    assert env.item().state == "skipped"
    assert env.managed_files() == []
    # Note gets unlocked upstream -> imported on the next run.
    env.set_fixture([dict(ENTRY)])
    result = env.pull(minutes=15)
    assert result["created"] == 1
    assert env.item().state == "managed"


def test_fingerprint_rematch_survives_id_reissue(seeded):
    # Upstream re-issues the ID (plan risk 1): same created + same body.
    seeded.set_fixture([dict(ENTRY, id="fx-reissued")])
    result = seeded.pull(minutes=15)
    assert result["created"] == 0  # no duplicate file
    assert len(seeded.managed_files()) == 1
    item = seeded.db.get_item("fixture", "fx-reissued")
    assert item is not None and item.state == "managed"
    # The file's marker followed the re-key, so reindex won't see it missing.
    fm = parse_note(seeded.managed_files()[0].read_text()).frontmatter
    assert fm["composter_id"] == "fixture:fx-reissued"
    seeded.reindex(minutes=30)
    assert seeded.db.get_item("fixture", "fx-reissued").missing_runs == 0
