"""The most important test in the suite (plan §12): after any full run,
every file outside zCompost/ is byte-identical to the baseline.
"""

from __future__ import annotations

import shutil

from src.main import run_resolve
from src.vault import check_baseline
from tests.conftest import DECOYS, ENTRY


def _assert_pristine(env):
    problems = check_baseline(env.vault, "zCompost", env.cfg.isolation_baseline_path)
    assert problems == [], problems


def test_full_lifecycle_never_touches_the_vault(env):
    """Exercise every write path the system has, then hash-check the vault."""
    env.set_fixture([dict(ENTRY, id=f"fx-{i:03d}", title=f"note {i}") for i in range(10)])
    env.pull()
    _assert_pristine(env)

    # Updates.
    env.set_fixture([dict(ENTRY, id=f"fx-{i:03d}", title=f"note {i}",
                          body=f"rewritten body {i}") for i in range(10)])
    env.pull(minutes=15)
    _assert_pristine(env)

    # Conflict + both resolutions.
    f = env.managed_files()[0]
    f.write_text(f.read_text().replace("rewritten", "hand-mangled"))
    env.set_fixture([dict(ENTRY, id=f"fx-{i:03d}", title=f"note {i}",
                          body=f"third body {i}") for i in range(10)])
    env.pull(minutes=30)
    item = next(i for i in env.db.items_in_state("conflict"))
    run_resolve(env.cfg, env.db, item.composter_id, take_upstream=True, now=env.t0)
    _assert_pristine(env)

    # Dismissal.
    env.managed_files()[1].unlink()
    for m in (45, 75, 110):
        env.reindex(minutes=m)
    _assert_pristine(env)

    # Status file.
    from src.status import write_status
    write_status(env.cfg, env.db)
    _assert_pristine(env)


def test_graduated_files_are_expected_baseline_changes(env):
    """Graduation is the owner moving a file out — the baseline check is run
    against composter's writes, so the test verifies the decoys specifically."""
    env.set_fixture([dict(ENTRY)])
    env.pull()
    path = env.managed_files()[0]
    shutil.move(path, env.vault / "Main" / path.name)  # owner's move
    env.pull(minutes=15)
    # Composter itself still changed nothing it shouldn't: decoys intact.
    for rel, text in DECOYS.items():
        assert (env.vault / rel).read_text() == text


def test_baseline_check_actually_detects_damage(env):
    """The alarm itself must work: corrupt, add, and remove decoys and
    confirm each is reported."""
    (env.vault / "a poem 3-9-26.md").write_text("corrupted!")
    (env.vault / "sneaky new file.md").write_text("should not be here")
    (env.vault / "Main" / "Zettlekasken" / "idea.md").unlink()
    problems = check_baseline(env.vault, "zCompost", env.cfg.isolation_baseline_path)
    kinds = {p.split(":")[0] for p in problems}
    assert kinds == {"CHANGED", "NEW FILE", "MISSING"}
