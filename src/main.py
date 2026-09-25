"""CLI entry point and the pull/reindex engine.

    python -m src.main doctor | init | reindex | pull | status | resolve |
                       isolation | backfill | all
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import sys
import shutil
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from . import alarm
from . import doctor as doctor_mod
from . import status as status_mod
from .config import Config, load_config
from .db import DB
from .sources.base import Capture, Source
from .sources.fixture import FixtureSource
from .vault import (
    ContainmentError,
    SentinelError,
    VaultWriter,
    capture_baseline,
    check_baseline,
    diff_file_maps,
    init_managed_root,
    scan_markers,
    subfolder_for,
    walk_outside,
)


def default_now() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


# The correct amount of pluggability is a dict literal (plan §7.4).
def build_sources(cfg: Config) -> dict[str, Source]:
    out: dict[str, Source] = {}
    fx = cfg.sources.get("fixture")
    if fx and fx.enabled:
        p = Path(str(fx.options.get("path", "tests/fixtures/fixture_captures.yaml")))
        if not p.is_absolute():
            p = Path(__file__).resolve().parents[1] / p
        out["fixture"] = FixtureSource(p)
    notes = cfg.sources.get("notes")
    if notes and notes.enabled:
        from .sources.apple_notes import AppleNotesSource
        exclusions = cfg.state_dir / "triage_exclusions.json"
        exclude_ids: frozenset[str] = frozenset()
        if exclusions.is_file():
            with open(exclusions, "r", encoding="utf-8") as f:
                exclude_ids = frozenset(json.load(f).get("trash_ids", []))
        out["notes"] = AppleNotesSource(
            quiet_seconds=int(notes.options.get("quiet_seconds", 120)),
            batch_size=int(notes.options.get("batch_size", 50)),
            max_fetch_per_run=int(notes.options.get("max_fetch_per_run", 200)),
            exclude_folders=tuple(notes.options.get("exclude_folders", ["Quick Notes"])),
            exclude_ids=exclude_ids,
        )
    voice = cfg.sources.get("voice")
    if voice and voice.enabled:
        from .sources.voice_memos import VoiceMemosSource
        kw = {}
        if voice.options.get("recordings_dir"):
            kw["root"] = Path(str(voice.options["recordings_dir"])).expanduser()
        if voice.options.get("model"):
            kw["model"] = Path(str(voice.options["model"])).expanduser()
        out["voice"] = VoiceMemosSource(
            transcripts_dir=cfg.transcripts_dir,
            max_minutes_per_run=int(voice.options.get("max_minutes_per_run", 30)),
            **kw)
    ios = cfg.sources.get("ios")
    if ios and ios.enabled:
        from .sources.ios_inbox import IosInboxSource
        kw = {}
        if ios.options.get("inbox_dir"):
            kw["root"] = Path(str(ios.options["inbox_dir"])).expanduser()
        out["ios"] = IosInboxSource(
            quiet_seconds=int(ios.options.get("quiet_seconds", 30)), **kw)
    return out


def pending_path(cfg: Config, composter_id: str) -> Path:
    key = hashlib.sha256(composter_id.encode("utf-8")).hexdigest()[:16]
    return cfg.pending_dir / f"{key}.json"


# ---------------------------------------------------------------------------
# reindex — layer 4: reconcile the ledger with vault reality
# ---------------------------------------------------------------------------

def run_reindex(cfg: Config, db: DB, now: datetime | None = None) -> dict:
    now = now or default_now()
    scan = scan_markers(cfg.vault_root)
    report = {"scanned": len(scan), "graduated": 0, "dismissed": 0, "moved": 0, "missing": 0}

    for item in db.active_items():
        entry = scan.get(item.composter_id)

        if entry is None:
            # Marker gone. A sync lag is indistinguishable from a deletion,
            # so absence must persist across dismiss_after_runs consecutive
            # runs spanning dismiss_after_seconds before it means anything.
            missing_runs = item.missing_runs + 1
            missing_since = item.missing_since or iso(now)
            elapsed = (now - datetime.fromisoformat(missing_since)).total_seconds()
            if missing_runs >= cfg.dismiss_after_runs and elapsed >= cfg.dismiss_after_seconds:
                db.set_state(item, "dismissed", iso(now),
                             missing_runs=missing_runs, missing_since=missing_since)
                report["dismissed"] += 1
            else:
                db.update_item(item.id, missing_runs=missing_runs, missing_since=missing_since)
                report["missing"] += 1
            continue

        clear = {"missing_runs": 0, "missing_since": None}
        inside = Path(entry.relpath).parts[:1] == (cfg.managed_dir,)

        if not inside:
            db.set_state(item, "graduated", iso(now), path=entry.relpath, **clear)
            report["graduated"] += 1
        elif not entry.managed:
            # composter_managed: false — explicit opt-out in place.
            db.set_state(item, "graduated", iso(now), path=entry.relpath, **clear)
            report["graduated"] += 1
        elif entry.relpath != item.path:
            # Heap reorganized by the owner; keep managing at the new path.
            db.update_item(item.id, path=entry.relpath, **clear)
            report["moved"] += 1
        elif item.missing_runs:
            db.update_item(item.id, **clear)

    return report


# ---------------------------------------------------------------------------
# pull — the state machine, one capture at a time
# ---------------------------------------------------------------------------

def _park_conflict(cfg: Config, cap: Capture, now: datetime, dry_run: bool) -> Path:
    p = pending_path(cfg, cap.composter_id)
    if not dry_run:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "composter_id": cap.composter_id,
            "title": cap.title,
            "created": cap.created,
            "source_hash": cap.source_hash,
            "parked_at": iso(now),
            "body": cap.body,
        }, indent=1), encoding="utf-8")
    return p


def _materialize_media(cfg: Config, writer: VaultWriter, source: Source,
                       cap: Capture) -> Capture:
    """Copy a capture's media into the vault and embed it in the body.

    Sources hand over absolute paths to files they found; only the writer may
    put anything in the vault. Files over `max_inline_mb` are left out of the
    vault entirely and referenced from `media_dir`, so sync weight stays sane.
    """
    if not cap.media:
        return cap
    limit = cfg.max_inline_mb * 1024 * 1024
    vault_paths, external = [], []
    for raw in cap.media:
        p = Path(raw)
        if not p.is_file():
            continue
        if p.stat().st_size > limit:
            external.append(str(p))
            continue
        vault_paths.append(writer.attach_media(p, source.subfolder))

    embeds = "\n".join(f"![[{v}]]" for v in vault_paths)
    # A bare filesystem path is not reachable from Obsidian. A file:// link is
    # clickable and opens the original, which is the point of referencing at
    # all — the note should get you to the audio even when the audio is too
    # large to live in the vault.
    notes = "\n".join(
        f"> [!info] Audio kept outside the vault (over {cfg.max_inline_mb} MB) — "
        f"[open {Path(e).name}](file://{quote(e)})"
        for e in external)
    header = "\n\n".join(x for x in (embeds, notes) if x)
    body = f"{header}\n\n{cap.body}".strip() if header else cap.body
    return replace(cap, body=body, media=tuple(vault_paths))


def _apply_capture(cfg: Config, db: DB, writer: VaultWriter, source: Source,
                   cap: Capture, now: datetime, counts: dict, dry_run: bool,
                   upstream_ids: set[str]) -> str:
    """Returns the WriteResult action for reporting."""
    item = db.get_item(cap.source, cap.source_id)

    rematched = False
    if item is None:
        # Risk 1: upstream may have re-issued IDs. Before creating, try to
        # rematch by fingerprint against an active item of the same source —
        # but only one whose old ID is genuinely gone from upstream, so a
        # new capture that merely shares a timestamp + opening lines with a
        # live item cannot steal it.
        # A rematch must force one file rewrite even if the body is
        # unchanged, so the composter_id in the file's frontmatter follows
        # the re-key — otherwise the next reindex reads the stale marker as
        # missing and starts the dismissal clock on a file that exists.
        orphan = db.find_by_fingerprint(cap.source, cap.fingerprint)
        if orphan is not None and orphan.source_id in upstream_ids:
            orphan = None
        if orphan is not None:
            rematched = True
            if not dry_run:
                db.update_item(orphan.id, source_id=cap.source_id,
                               composter_id=cap.composter_id)
                item = db.get_item(cap.source, cap.source_id)
            else:
                item = orphan

    # -- skipped upstream (locked / empty) — recorded, re-checked each run --
    if cap.skip_reason:
        if item is None and not dry_run:
            db.insert_item(source=cap.source, source_id=cap.source_id,
                           composter_id=cap.composter_id, state="skipped", now=iso(now),
                           title=cap.title, kind=cap.kind, skip_reason=cap.skip_reason,
                           source_ref=cap.source_ref, created_at=cap.created,
                           fingerprint=cap.fingerprint)
        elif item is not None and item.state == "skipped" and not dry_run:
            db.update_item(item.id, skip_reason=cap.skip_reason)
        return "skipped"

    # -- brand new -----------------------------------------------------------
    if item is None or item.state == "skipped":
        if counts["created"] >= cfg.max_new_per_run:
            counts["circuit_breaker"] = counts.get("circuit_breaker", 0) + 1
            return "circuit_breaker"
        captured_iso = iso(now)
        cap = _materialize_media(cfg, writer, source, cap)
        result = writer.create(cap, captured_iso, source.subfolder,
                               mirror_folders=getattr(source, "mirror_folders", False))
        if not dry_run:
            if item is None:
                item = db.insert_item(
                    source=cap.source, source_id=cap.source_id,
                    composter_id=cap.composter_id, state="managed", now=iso(now),
                    title=cap.title, kind=cap.kind, zone=cap.zone,
                    authorship=cap.authorship, created_at=cap.created,
                    captured_at=captured_iso, source_ref=cap.source_ref,
                    path=result.relpath, source_hash=cap.source_hash,
                    source_modified_at=cap.modified,
                    written_hash=result.written_hash,
                    managed_body_hash=result.managed_body_hash,
                    fingerprint=cap.fingerprint, rev=result.rev,
                )
            else:
                db.set_state(item, "managed", iso(now),
                             title=cap.title, kind=cap.kind, created_at=cap.created,
                             captured_at=captured_iso, path=result.relpath,
                             source_hash=cap.source_hash,
                             source_modified_at=cap.modified,
                             written_hash=result.written_hash,
                             managed_body_hash=result.managed_body_hash,
                             fingerprint=cap.fingerprint, rev=result.rev, skip_reason=None)
        return "created"

    # -- terminal: never write again ------------------------------------------
    if item.state in ("graduated", "dismissed"):
        # Record the mod stamp so the source's prefilter stops re-fetching
        # bodies for a note whose vault file we will never touch anyway.
        if not dry_run and cap.modified and cap.modified != item.source_modified_at:
            db.update_item(item.id, source_modified_at=cap.modified)
        return "unchanged"

    # -- conflict already open: keep the parked payload fresh, write nothing --
    if item.state == "conflict":
        if cap.source_hash != item.source_hash:
            _park_conflict(cfg, cap, now, dry_run)
        return "conflict"

    # -- managed: layer 1 — don't write unless upstream actually changed ------
    if cap.source_hash == item.source_hash and not rematched:
        # Content is identical, so no file is touched. Cheap out-of-band
        # metadata is still worth recording: moving a note between folders in
        # Apple Notes does not change its text, and the ledger has to know
        # about it for `relocate` to have anything to act on.
        drift = {}
        if cap.source_ref != item.source_ref:
            drift["source_ref"] = cap.source_ref
        if cap.modified and cap.modified != item.source_modified_at:
            drift["source_modified_at"] = cap.modified
        if drift and not dry_run:
            db.update_item(item.id, **drift)
        return "unchanged"

    # -- managed, upstream changed: layers 2–3 --------------------------------
    result = writer.update(cap, item, item.captured_at or iso(now))

    if result.action == "missing":
        # Do not recreate and do not error. reindex is already counting this
        # toward dismissal; recreating it here would resurrect a note the
        # owner deleted, which is the single most infuriating bug in this
        # category of tool.
        return "unchanged"

    if result.action == "conflict":
        if cfg.on_local_edit == "graduate":
            if not dry_run:
                db.set_state(item, "graduated", iso(now))
            return "graduated"
        _park_conflict(cfg, cap, now, dry_run)
        if not dry_run:
            db.set_state(item, "conflict", iso(now))
        return "conflict"

    if result.action in ("updated", "unchanged") and not dry_run:
        db.update_item(item.id, title=cap.title, kind=cap.kind, created_at=cap.created,
                       source_hash=cap.source_hash, fingerprint=cap.fingerprint,
                       source_modified_at=cap.modified, source_ref=cap.source_ref,
                       written_hash=result.written_hash or item.written_hash,
                       managed_body_hash=result.managed_body_hash or item.managed_body_hash,
                       rev=result.rev or item.rev)
    return result.action


def run_pull(cfg: Config, db: DB, source_name: str, limit: int | None = None,
             dry_run: bool = False, now: datetime | None = None,
             source: Source | None = None) -> dict:
    now = now or default_now()
    if source is None:
        sources = build_sources(cfg)
        if source_name not in sources:
            raise SystemExit(f"source {source_name!r} is not enabled/known "
                             f"(enabled: {sorted(sources) or 'none'})")
        source = sources[source_name]
    writer = VaultWriter(cfg.vault_root, cfg.managed_dir, cfg.vault_id, dry_run=dry_run)

    run_id = None if dry_run else db.start_run(source_name, iso(now))
    counts = {k: 0 for k in ("created", "updated", "unchanged", "conflict",
                             "skipped", "error", "graduated", "dismissed")}
    notes = []
    ok = True
    try:
        reindex_report = run_reindex(cfg, db, now) if not dry_run else {"skipped_in_dry_run": True}
        counts["graduated"] = reindex_report.get("graduated", 0)
        counts["dismissed"] = reindex_report.get("dismissed", 0)

        # Keyed by the source's own identity (e.g. "apple-notes"), not the CLI
        # alias ("notes") — items are stored under the former.
        captures = source.captures(limit, db.mods_for_source(source.name))
        upstream_ids = {c.source_id for c in captures}
        for cap in captures:
            try:
                action = _apply_capture(cfg, db, writer, source, cap, now, counts,
                                        dry_run, upstream_ids)
            except (ContainmentError, SentinelError):
                raise  # isolation failures abort the run, never get counted past
            except Exception as e:
                counts["error"] += 1
                ok = False
                notes.append(f"{cap.composter_id}: {e}")
                if not dry_run:
                    item = db.get_item(cap.source, cap.source_id)
                    if item:
                        db.update_item(item.id, error_count=item.error_count + 1,
                                       last_error=str(e)[:500])
                continue
            if action == "circuit_breaker":
                ok = False
                notes.append(
                    f"circuit breaker: max_new_per_run={cfg.max_new_per_run} reached; "
                    f"further new items NOT created. If upstream re-issued IDs, "
                    f"this is the alarm working."
                )
            elif action in counts:
                counts[action] += 1
            if dry_run and action == "created":
                notes.append(f"would create: {cap.composter_id} ({cap.title!r})")
    finally:
        if run_id is not None:
            db.finish_run(run_id, iso(default_now()), ok, counts, "; ".join(notes) or None)

    # Sweep consumed sidecars out of the inbox so it empties on the phone.
    # Moved, never deleted — a bug must not be able to destroy a capture.
    if ok and not dry_run and hasattr(source, "mark_ingested"):
        done = {c.source_id for c in captures
                if db.get_item(c.source, c.source_id)
                and db.get_item(c.source, c.source_id).state != "error"}
        if done:
            counts["ingested"] = source.mark_ingested(done)

    counts["ok"] = ok
    counts["dry_run"] = dry_run
    counts["notes"] = notes
    return counts


# ---------------------------------------------------------------------------
# resolve
# ---------------------------------------------------------------------------

def run_resolve(cfg: Config, db: DB, composter_id: str, take_upstream: bool,
                now: datetime | None = None) -> str:
    now = now or default_now()
    item = db.get_by_composter_id(composter_id)
    if item is None:
        raise SystemExit(f"no item with composter_id {composter_id!r}")
    if item.state != "conflict":
        raise SystemExit(f"{composter_id} is in state {item.state!r}, not conflict")

    p = pending_path(cfg, composter_id)

    if take_upstream:
        if not p.is_file():
            raise SystemExit(f"no parked payload at {p}")
        payload = json.loads(p.read_text(encoding="utf-8"))
        cap = Capture(source=item.source, source_id=item.source_id,
                      title=payload["title"], body=payload["body"],
                      created=payload.get("created"), kind=item.kind or "note",
                      zone=item.zone, authorship=item.authorship,
                      source_ref=item.source_ref)
        writer = VaultWriter(cfg.vault_root, cfg.managed_dir, cfg.vault_id)
        moved_to = writer.supersede(item.path, now.strftime("%Y-%m-%d"))
        result = writer.rewrite_from_capture(cap, item, item.captured_at or iso(now))
        db.set_state(item, "managed", iso(now),
                     source_hash=payload["source_hash"],
                     written_hash=result.written_hash,
                     managed_body_hash=result.managed_body_hash, rev=result.rev)
        outcome = f"took upstream; local version preserved at {moved_to}"
    else:
        # --keep-mine: graduates in place, severs the link. Nothing written.
        db.set_state(item, "graduated", iso(now))
        outcome = "kept local version; item graduated (never written again)"

    if p.is_file():
        resolved_dir = cfg.pending_dir / "resolved"
        resolved_dir.mkdir(parents=True, exist_ok=True)
        p.replace(resolved_dir / p.name)  # state dir, not vault; moved, not deleted
    return outcome


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _open(args) -> tuple[Config, DB]:
    cfg = load_config(args.config)
    cfg.ensure_state_dirs()
    return cfg, DB(cfg.db_path)


def cmd_doctor(args) -> int:
    cfg = load_config(args.config)
    return doctor_mod.run_doctor(cfg)


def cmd_init(args) -> int:
    cfg, db = _open(args)
    root = init_managed_root(cfg.vault_root, cfg.managed_dir, cfg.vault_id)
    print(f"managed root ready: {root}")
    if not cfg.isolation_baseline_path.is_file():
        n = capture_baseline(cfg.vault_root, cfg.managed_dir, cfg.isolation_exclude,
                             cfg.isolation_baseline_path)
        print(f"isolation baseline captured: {n} files outside {cfg.managed_dir}/")
    else:
        print("isolation baseline already present (not overwritten)")
    db.close()
    return 0


def cmd_reindex(args) -> int:
    cfg, db = _open(args)
    report = run_reindex(cfg, db)
    print(json.dumps(report, indent=1))
    db.close()
    return 0


def _snapshot_outside(cfg: Config) -> dict:
    """The standing isolation check, per-run flavor: snapshot every file
    outside zCompost/ before the run, diff after. Only changes made DURING
    the run can be composter's doing — the owner edits their vault between
    runs all the time, and that is not a violation."""
    return walk_outside(cfg.vault_root, cfg.managed_dir, cfg.isolation_exclude)


def _die_on_violations(pre: dict, post: dict) -> None:
    problems = diff_file_maps(pre, post)
    if problems:
        for p in problems:
            print(f"ISOLATION VIOLATION (file changed during this run): {p}",
                  file=sys.stderr)
        raise SystemExit(2)


def cmd_pull(args) -> int:
    cfg, db = _open(args)
    if getattr(args, "max_new", None):
        print(f"circuit breaker raised for this run only: "
              f"{cfg.max_new_per_run} -> {args.max_new}", file=sys.stderr)
        cfg.max_new_per_run = args.max_new
    if getattr(args, "max_minutes", None):
        voice = cfg.sources.get("voice")
        if voice:
            print(f"voice minute budget raised for this run only: "
                  f"{voice.options.get('max_minutes_per_run', 30)} -> "
                  f"{args.max_minutes}", file=sys.stderr)
            voice.options["max_minutes_per_run"] = args.max_minutes
    pre = _snapshot_outside(cfg)
    result = run_pull(cfg, db, args.source, limit=args.limit, dry_run=args.dry_run)
    print(json.dumps(result, indent=1))
    if not args.dry_run:
        status_mod.write_status(cfg, db)
    _die_on_violations(pre, _snapshot_outside(cfg))
    db.close()
    return 0 if result["ok"] else 1


def cmd_status(args) -> int:
    cfg, db = _open(args)
    payload = status_mod.write_status(cfg, db)
    print(json.dumps(payload, indent=1))
    db.close()
    return 0


def cmd_resolve(args) -> int:
    cfg, db = _open(args)
    outcome = run_resolve(cfg, db, args.id, take_upstream=args.take_upstream)
    print(outcome)
    status_mod.write_status(cfg, db)
    db.close()
    return 0


def cmd_isolation(args) -> int:
    """Standalone drift report against the baseline captured at `init`.

    This is NOT the guarantee. The guarantee is the pre/post snapshot taken
    around every pull, which is the only thing that can attribute a change to
    composter. This command compares against a frozen baseline, so the owner's
    own edits — graduating a file, clipping a page, writing a note — show up
    here too. Differences are reported as drift, not as violations.
    """
    cfg = load_config(args.config)
    cfg.ensure_state_dirs()
    if args.capture:
        if cfg.isolation_baseline_path.is_file() and not args.force:
            print("baseline already exists; --force to recapture (only do this "
                  "deliberately — a baseline taken after damage is worthless)", file=sys.stderr)
            return 1
        n = capture_baseline(cfg.vault_root, cfg.managed_dir, cfg.isolation_exclude,
                             cfg.isolation_baseline_path)
        print(f"baseline captured: {n} files outside {cfg.managed_dir}/")
        return 0
    problems = check_baseline(cfg.vault_root, cfg.managed_dir, cfg.isolation_baseline_path)
    if not problems:
        print("no drift: vault outside the managed dir is byte-identical to baseline")
        return 0
    print(f"{len(problems)} file(s) differ from the baseline captured at init:\n")
    for p in problems:
        print(f"  {p}")
    print("\nThese are almost certainly your own edits — graduating a file out of "
          f"{cfg.managed_dir}/, a web clipping, or ordinary writing. Composter cannot "
          "write here: every pull snapshots this set before and after itself and aborts "
          "on any change it caused.\n"
          "If these are yours, re-baseline with:  isolation --capture --force")
    return 1


def cmd_all(args) -> int:
    """What launchd calls. Never overlaps itself; always leaves the status file
    and the alarm consistent with what actually happened."""
    cfg = load_config(args.config)
    cfg.ensure_state_dirs()
    lock = _acquire_lock(cfg)
    if lock is None:
        print("another run holds the lock; exiting", file=sys.stderr)
        return 0  # not an error: ThrottleInterval is not a lock

    db = DB(cfg.db_path)
    ok = True
    try:
        pre = _snapshot_outside(cfg)
        run_reindex(cfg, db)
        for name, src_cfg in cfg.sources.items():
            if src_cfg.enabled and name in build_sources(cfg):
                result = run_pull(cfg, db, name)
                ok = ok and result["ok"]
        status_mod.write_status(cfg, db)
        _die_on_violations(pre, _snapshot_outside(cfg))
    except Exception as e:
        ok = False
        now = iso(default_now())
        run_id = db.start_run(None, now)
        db.finish_run(run_id, now, False, {}, f"{type(e).__name__}: {e}")
        print(f"run failed: {type(e).__name__}: {e}", file=sys.stderr)
    finally:
        try:
            alarm.update(cfg, db)
        except Exception as e:  # the alarm must never mask the real failure
            print(f"alarm update failed: {e}", file=sys.stderr)
        db.close()
        lock.close()
    return 0 if ok else 1


def _acquire_lock(cfg: Config):
    """flock on state/composter.lock. A long whisper run must never overlap
    the next tick, and ThrottleInterval does not provide mutual exclusion."""
    import fcntl
    path = cfg.state_dir / "composter.lock"
    f = open(path, "w")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def run_relocate(cfg: Config, db: DB, dry_run: bool = False) -> dict:
    """Move managed files into the folder their source now implies.

    Hand-invoked only. Intended for restructuring shortly after an import —
    before anything links to these files — because a script move breaks
    wikilinks that Obsidian would otherwise have repaired itself.
    """
    writer = VaultWriter(cfg.vault_root, cfg.managed_dir, cfg.vault_id, dry_run=dry_run)
    sources = build_sources(cfg)
    base_for = {s.name: s.subfolder for s in sources.values()}
    moved, skipped = [], 0

    for item in db.items_in_state("managed", "conflict"):
        base = base_for.get(item.source)
        if not base or not item.path:
            skipped += 1
            continue
        src_obj = next((s for s in sources.values() if s.name == item.source), None)
        want = (subfolder_for(base, item.source_ref)
                if getattr(src_obj, "mirror_folders", False) else base)
        current = str(Path(item.path).parent.relative_to(cfg.managed_dir))
        if current == want:
            skipped += 1
            continue
        new_rel = writer.relocate(item.path, want)
        if new_rel is None:
            skipped += 1
            continue
        if not dry_run:
            db.update_item(item.id, path=new_rel)
        moved.append((item.path, new_rel))

    # Prune whether or not anything moved this time: a previous relocate (or
    # an interrupted one) can leave husks that no later run would ever clear.
    pruned = 0
    if not dry_run:
        for base in {b for b in base_for.values() if b}:
            pruned += writer.prune_empty_dirs(base)

    return {"moved": len(moved), "unchanged": skipped, "pruned_empty_dirs": pruned,
            "dry_run": dry_run,
            "examples": [f"{a} -> {b}" for a, b in moved[:10]]}


def cmd_relocate(args) -> int:
    cfg, db = _open(args)
    if not args.yes and not args.dry_run:
        print("relocate moves managed files between folders. Obsidian repairs "
              "wikilinks only for renames it performs itself, so any [[link]] "
              "into these files will break. Re-run with --yes once you have "
              "checked --dry-run.", file=sys.stderr)
        return 1
    result = run_relocate(cfg, db, dry_run=args.dry_run)
    print(json.dumps(result, indent=1))
    if not args.dry_run:
        status_mod.write_status(cfg, db)
    db.close()
    return 0


def cmd_backfill(args) -> int:
    """The one operation that writes outside the managed folder (plan §11).

    Hand-invoked only: never scheduled, never a side effect. `all` does not
    call it, and neither does anything else.
    """
    from . import backfill as bf
    cfg = load_config(args.config)
    cfg.ensure_state_dirs()
    tsv = cfg.state_dir / bf.TSV_NAME

    if args.propose:
        rows = bf.propose(cfg, tsv)
        by_conf = {}
        for r in rows:
            by_conf[r.confidence] = by_conf.get(r.confidence, 0) + 1
        print(f"{len(rows)} notes need frontmatter -> {tsv}")
        for c in ("high", "medium", "low"):
            if by_conf.get(c):
                print(f"  {c:6} confidence: {by_conf[c]}")
        print(f"  authorship 'theirs': "
              f"{sum(1 for r in rows if r.authorship == 'theirs')}")
        print("\nNothing was written to the vault. Edit the TSV — clear the "
              "`created` column\nfor any date you do not trust, an absent field "
              "is honest and a wrong one\nis not — then run `backfill --apply "
              "--dry-run`.")
        return 0

    if args.undo:
        snaps = sorted(bf.SNAPSHOT_ROOT.glob("vault-pre-backfill-*"))
        if not snaps:
            print("no snapshot found", file=sys.stderr)
            return 1
        snap = snaps[-1]
        print(f"restoring markdown from {snap}")
        n = 0
        for src_file in snap.rglob("*.md"):
            rel = src_file.relative_to(snap)
            if rel.parts[0] in bf.SKIP_DIRS or rel.parts[0] == cfg.managed_dir:
                continue
            dest = cfg.vault_root / rel
            if dest.is_file() and dest.read_bytes() != src_file.read_bytes():
                if not args.dry_run:
                    shutil.copy2(src_file, dest)
                n += 1
        print(f"{'would restore' if args.dry_run else 'restored'}: {n} files")
        return 0

    if not args.apply:
        print("one of --propose | --apply | --undo is required", file=sys.stderr)
        return 1

    # -- apply ---------------------------------------------------------------
    if not tsv.is_file():
        print(f"no proposal at {tsv}; run `backfill --propose` first", file=sys.stderr)
        return 1
    rows = bf.read_proposal(tsv)

    if not args.dry_run:
        # Safeguard 1: the rollback must exist before a byte is written.
        snap, count, size = bf.snapshot(cfg)
        print(f"snapshot: {snap}  ({count} files, {size/1e6:.1f} MB)")
        problems = bf.verify_snapshot(cfg, snap)
        if problems:
            for p_ in problems[:10]:
                print(f"  {p_}", file=sys.stderr)
            print("snapshot verification FAILED — nothing written", file=sys.stderr)
            return 2

    captured = iso(default_now())
    changed = skipped = failed = 0
    for i, row in enumerate(rows):
        path = cfg.vault_root / row.relpath
        if not path.is_file():
            skipped += 1
            continue
        try:
            before, after = bf.apply_one(path, row, captured)
        except (ValueError, AssertionError) as e:
            print(f"  SKIP {row.relpath}: {e}", file=sys.stderr)
            failed += 1
            continue
        if args.dry_run:
            if changed < args.show:
                diff = difflib.unified_diff(
                    before.splitlines(True)[:3], after.splitlines(True)[:10],
                    fromfile=row.relpath, tofile=row.relpath + " (after)")
                print("".join(diff), end="")
            changed += 1
            continue
        path.write_text(after, encoding="utf-8")
        changed += 1
        # Safeguard 5: batched, so an interrupted run leaves a known state.
        if changed % args.batch == 0:
            print(f"  ... {changed}/{len(rows)}")

    verb = "would change" if args.dry_run else "changed"
    print(f"\n{verb}: {changed}   skipped (missing): {skipped}   refused: {failed}")
    if args.dry_run:
        print("dry run — nothing written. Re-run without --dry-run to apply.")
    else:
        print("Re-baseline the isolation check: `isolation --capture --force`")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="composter")
    ap.add_argument("--config", default=None, help="path to composter.yaml")
    sub = ap.add_subparsers(dest="verb", required=True)

    sub.add_parser("doctor").set_defaults(func=cmd_doctor)
    sub.add_parser("init").set_defaults(func=cmd_init)
    sub.add_parser("reindex").set_defaults(func=cmd_reindex)

    p = sub.add_parser("pull")
    p.add_argument("--source", required=True, choices=["fixture", "notes", "voice", "ios"])
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--max-minutes", type=int, default=None,
                   help="override the voice source's max_minutes_per_run for this "
                        "run only. The config value guards a SCHEDULED run against "
                        "one long recording; raise it by hand for a backfill.")
    p.add_argument("--max-new", type=int, default=None,
                   help="override writer.max_new_per_run for this run only. The config "
                        "value is a circuit breaker against a mass ID re-issue creating "
                        "thousands of duplicates; raise it only for the one-time initial "
                        "backfill, by hand, never in the scheduled agent.")
    p.set_defaults(func=cmd_pull)

    sub.add_parser("status").set_defaults(func=cmd_status)

    p = sub.add_parser("resolve")
    p.add_argument("--id", required=True, help="composter_id")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--take-upstream", action="store_true")
    g.add_argument("--keep-mine", action="store_true")
    p.set_defaults(func=cmd_resolve, take_upstream=False)

    p = sub.add_parser("isolation")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--capture", action="store_true")
    g.add_argument("--check", action="store_true")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_isolation)

    p = sub.add_parser("relocate")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--yes", action="store_true",
                   help="required for a real move; see the warning about wikilinks")
    p.set_defaults(func=cmd_relocate)

    p = sub.add_parser("backfill", help="Phase 6: frontmatter for pre-existing notes. "
                                        "The ONLY command that writes outside the "
                                        "managed folder. Hand-invoked only.")
    p.add_argument("--propose", action="store_true",
                   help="write a TSV of inferred values + evidence; writes nothing else")
    p.add_argument("--apply", action="store_true",
                   help="read the TSV (never re-infers) and write frontmatter")
    p.add_argument("--undo", action="store_true", help="restore markdown from the snapshot")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--batch", type=int, default=20, help="progress every N files")
    p.add_argument("--show", type=int, default=5, help="diffs to print in a dry run")
    p.set_defaults(func=cmd_backfill)

    sub.add_parser("all").set_defaults(func=cmd_all)

    args = ap.parse_args(argv)
    if args.verb == "resolve" and args.keep_mine:
        args.take_upstream = False
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
