"""Phase 3: the alarm, the lock, and the status heartbeat (plan §12, §13)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from src import alarm
from src.main import _acquire_lock
from src.status import write_status
from src.vault import ALARM_NAME, ContainmentError, VaultWriter
from tests.conftest import ENTRY, VAULT_ID


def alarm_path(env):
    return env.vault / "zCompost" / ALARM_NAME


def fail_run(env, minutes: float, note: str = "boom"):
    at = (env.t0 + timedelta(minutes=minutes)).isoformat(timespec="seconds")
    rid = env.db.start_run("fixture", at)
    env.db.finish_run(rid, at, False, {}, note)


def ok_run(env, minutes: float):
    at = (env.t0 + timedelta(minutes=minutes)).isoformat(timespec="seconds")
    rid = env.db.start_run("fixture", at)
    env.db.finish_run(rid, at, True, {"created": 1})


# -- alarm raises, self-clears, and does not nag -------------------------------

def test_alarm_raised_after_three_consecutive_failures(env, monkeypatch):
    seen = []
    monkeypatch.setattr(alarm, "notify", lambda t, m: seen.append((t, m)))

    for i, m in enumerate((0, 15, 30)):
        fail_run(env, m)
        r = alarm.update(env.cfg, env.db, now=env.t0 + timedelta(minutes=m))
        if i < 2:
            assert r["alarm"] is False, "must not fire before the third failure"
            assert not alarm_path(env).exists()

    assert r["alarm"] is True and r["newly_raised"] is True
    text = alarm_path(env).read_text()
    assert "Consecutive failed runs: **3**" in text
    assert "boom" in text                      # the actual error, not a generic message
    assert "src.main doctor" in text           # the exact command to run
    assert len(seen) == 1, "notify exactly once, on the transition"


def test_alarm_does_not_renotify_while_still_failing(env, monkeypatch):
    seen = []
    monkeypatch.setattr(alarm, "notify", lambda t, m: seen.append(1))
    for m in (0, 15, 30, 45, 60):
        fail_run(env, m)
        alarm.update(env.cfg, env.db, now=env.t0 + timedelta(minutes=m))
    assert len(seen) == 1, "escalation notifies once, not every tick"


def test_alarm_self_deletes_on_next_success(env, monkeypatch):
    monkeypatch.setattr(alarm, "notify", lambda t, m: None)
    for m in (0, 15, 30):
        fail_run(env, m)
    alarm.update(env.cfg, env.db, now=env.t0 + timedelta(minutes=30))
    assert alarm_path(env).exists()

    ok_run(env, 45)
    r = alarm.update(env.cfg, env.db, now=env.t0 + timedelta(minutes=45))
    assert r["alarm"] is False and r["cleared"] is True
    assert not alarm_path(env).exists(), "must never become stale nagging"


def test_alarm_raised_when_stale_even_without_failures(env, monkeypatch):
    monkeypatch.setattr(alarm, "notify", lambda t, m: None)
    ok_run(env, 0)
    r = alarm.update(env.cfg, env.db, now=env.t0 + timedelta(hours=12))
    assert r["alarm"] is False
    r = alarm.update(env.cfg, env.db, now=env.t0 + timedelta(hours=27))
    assert r["alarm"] is True                  # 26h with no success
    assert "27 hours ago" in alarm_path(env).read_text()


def test_no_alarm_before_any_run_has_happened(env, monkeypatch):
    monkeypatch.setattr(alarm, "notify", lambda t, m: None)
    r = alarm.update(env.cfg, env.db, now=env.t0 + timedelta(days=30))
    assert r["alarm"] is False, "a fresh install with no runs is not a failure"
    assert not alarm_path(env).exists()


def test_alarm_lives_inside_the_managed_dir(env, monkeypatch):
    monkeypatch.setattr(alarm, "notify", lambda t, m: None)
    for m in (0, 15, 30):
        fail_run(env, m)
    alarm.update(env.cfg, env.db, now=env.t0 + timedelta(minutes=30))
    assert alarm_path(env).exists()
    assert not (env.vault / ALARM_NAME).exists(), "isolation has no exceptions"


# -- clear_alarm is the only unlink, and it is narrow --------------------------

def test_clear_alarm_only_touches_the_managed_copy(env):
    """The path is built internally from managed_root, so a same-named file
    anywhere else in the vault is not reachable by this code path."""
    writer = VaultWriter(env.vault, "zCompost", VAULT_ID)
    decoy = env.vault / ALARM_NAME                 # same NAME, outside zCompost/
    decoy.write_text("hand-written, must survive")
    writer.write_alarm("machine-written")
    assert writer.clear_alarm() is True
    assert not (env.vault / "zCompost" / ALARM_NAME).exists()
    assert decoy.read_text() == "hand-written, must survive"


def test_clear_alarm_is_a_noop_when_absent(env):
    writer = VaultWriter(env.vault, "zCompost", VAULT_ID)
    assert writer.clear_alarm() is False


# -- flock prevents overlapping runs -------------------------------------------

def test_lock_is_exclusive(env):
    first = _acquire_lock(env.cfg)
    assert first is not None
    assert _acquire_lock(env.cfg) is None, "a second run must not proceed"
    first.close()
    second = _acquire_lock(env.cfg)
    assert second is not None, "lock is released when the run ends"
    second.close()


# -- the status heartbeat ------------------------------------------------------

def test_status_reports_elapsed_time_at_read_time(env):
    ok_run(env, 0)
    payload = write_status(env.cfg, env.db, now=env.t0 + timedelta(hours=5))
    assert payload["elapsed_since_success_seconds"] == pytest.approx(5 * 3600, abs=2)


def test_status_only_rewritten_when_content_changes(env):
    ok_run(env, 0)
    assert write_status(env.cfg, env.db, now=env.t0)["status_file_rewritten"] is True
    again = write_status(env.cfg, env.db, now=env.t0)
    assert again["status_file_rewritten"] is False, "no needless file events or sync churn"


def test_conflicts_appear_in_status_as_wikilinks(seeded):
    path = seeded.managed_files()[0]
    path.write_text(path.read_text().replace("Tracking", "Hand-edited"))
    seeded.set_fixture([dict(ENTRY, body="upstream moved on")])
    seeded.pull(minutes=15)

    write_status(seeded.cfg, seeded.db)
    text = (seeded.vault / "zCompost" / "_status.md").read_text()
    assert "Waiting on you" in text
    assert "[[zCompost/Notes/composting metaphor 8-9-26]]" in text
    assert "resolve --id" in text
