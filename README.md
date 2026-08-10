# Composter

A personal capture-and-retrieval system built alongside an existing Obsidian
vault. Design and rationale live in [IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md)
— that document is authoritative; this file is just the operating manual.

**Explicitly out of scope for the capture layer:** no embeddings, no LLM
calls, no vector store, no UI, no tags beyond provenance.

**Isolation is the top priority.** The system's entire vault footprint is
`zCompost/`. Zero writes outside it, enforced four independent ways
(containment assertions, the sentinel file, no delete path in the codebase,
and the standing isolation baseline test).

## Setup

```sh
python3 -m venv .venv
./.venv/bin/pip install -r requirements-dev.txt
./.venv/bin/python -m pytest tests/        # 26 tests, all against temp vaults
```

## Before pointing at the real vault (Phase 0)

1. Confirm which local folder Obsidian Sync is actually bound to
   (Settings → Sync). Two vaults are registered on this machine.
2. `python -m src.main doctor` — fix any ✗.
3. `python -m src.main init` — creates `zCompost/` + sentinel, captures the
   isolation baseline **while the vault is pristine**.
4. Create the kitchen-sink note in Apple Notes (every construct, including a
   checklist with one item checked), snapshot its HTML into
   `tests/fixtures/notes_kitchen_sink.html` — the snapshot test in
   `tests/test_htmlmd.py` activates automatically once the file exists.

## Sources

- **apple-notes** (Phase 2, built): JXA two-phase fetch — 5-event index of the
  whole library (~6 s for 3,073 notes), then bodies only for notes whose
  modification date moved. Locked notes -> `skipped`; Recently Deleted never
  imported; notes modified in the last `quiet_seconds` deferred; title-only
  one-line jots import with an empty body (the title is the thought).
  Change detection hashes upstream HTML, so converter tweaks never look like
  edits. `--limit N` imports the N newest not-yet-imported notes, so repeated
  limited pulls walk backward through the library in slices.
- **voice / ios**: Phases 4–5, blocked on Full Disk Access.

## Triage — deciding what is compost and what is trash

**Parked, and deliberately so.** Nothing about triage blocks capture: unfiltered
notes import fine, and whether junk actually hurts is a *retrieval* question
(plan Principle 9, "embed on capture, reason on retrieval") that cannot be
answered until Phase 7 has a real corpus to test against. Pick this back up
then. The one piece that is not deferrable is credentials, which is a security
matter rather than a triage one — see below.

Everything is hand-invoked, local-only, and never part of a scheduled run.
Nothing is ever deleted: tossed notes stay in Apple Notes and composter simply
stops importing them.

```sh
.venv/bin/python triage/dump_candidates.py    # read-only dump of the Notes folder
.venv/bin/python triage/obvious.py            # print every form-rule match, to check precision
.venv/bin/python triage/build_review.py       # build the local review page
open state/triage_review.html                 # decide (decisions persist in localStorage)
.venv/bin/python triage/apply_decisions.py    # apply the downloaded JSON
```

Verdicts land in `state/triage_exclusions.json`, which the Apple Notes source
reads on every run. Folder-level exclusions go in `sources.notes.exclude_folders`
— coarser and cheaper than per-note decisions. `Recently Deleted` is always
excluded.

### What was learned building this

The first attempt classified notes by *value* using keyword rules and was bad
enough to be unusable: a regex for password-shaped strings matched `goggles!!!`,
so a packing list was filed as a credential, and a catch-all fallback swept
doctor's notes into "reflection". **Do not resurrect `categorize.py`'s
approach.**

What replaced it splits the problem in two:

- `triage/obvious.py` — judges **form, not meaning**: no text at all, digits
  outnumbering letters, a string matching a real vendor key format. Each is
  checkable at a glance. Run it directly to eyeball every match. A "scratch
  calculation" rule was written and deleted after scoring 1-in-4 precision on
  the real library; the comment where it used to be explains why.
- `triage/CLASSIFY-BRIEF.md` — the brief for model-read, per-note judgements
  (`state/verdicts/shard-*.jsonl`). These are surfaced as opt-in *suggestions*
  that pre-decide nothing, because no classifier is trustworthy enough to
  delete on.

Precision beats recall here in a way that is not a preference: an unexcluded
grocery list costs a vector that never matches anything, while a wrongly
excluded thought is gone.

## Verbs

```
doctor      preflight checklist
init        create zCompost/ skeleton + sentinel + DB + isolation baseline
reindex     reconcile ledger with vault reality (graduation / dismissal)
pull        [--source fixture|notes|voice|ios] [--limit N] [--max-new N] [--dry-run]
status      rewrite zCompost/_status.md, print JSON
resolve     --id <composter_id> --take-upstream | --keep-mine
relocate    [--dry-run] --yes   move managed files into mirrored source folders
isolation   --capture [--force] | --check
all         reindex + pull all enabled sources + status + alarm   ← what launchd calls
backfill    Phase 6 only — currently refuses by design
```

Always `pull --limit 5 --dry-run` before the first real pull of any source.

## The scheduler

```sh
.venv/bin/python scripts/agent.py install --interval 3600   # hourly
.venv/bin/python scripts/agent.py status
.venv/bin/python scripts/agent.py uninstall
```

Hourly rather than every 15 minutes: a run costs ~6 seconds of CPU, but each one
wakes Notes.app in the background, and the quiet period already refuses anything
edited in the last two minutes. Hourly buys same-day capture for a quarter of the
wakeups. The interval is one number.

`all` takes an exclusive `flock` and exits 0 if another run holds it, so a long
run can never overlap the next tick.

**Failure surfacing, in three tiers:**

1. `zCompost/_status.md` — rewritten after each run *only when its content
   changed*, so it generates no needless sync traffic. Boring when all is well.
2. `zCompost/!! needs attention.md` — appears only after 3 consecutive failures
   or 26 hours with no success, carries the real error and the exact command to
   run, fires **one** macOS notification, and **deletes itself** on the next
   success. This is the only unlink of a content file in the codebase; see the
   docstring on `VaultWriter.clear_alarm` for why it is safe.
3. `state/logs/`, the `runs` table, and `status` — for debugging, not noticing.

`doctor` checks that the agent is actually loaded, which is the one gap the
scheme otherwise has: no run means no status update means no alarm.

## Layout in the vault

`zCompost/` splits by **source**, never by topic — topic folders are the
taxonomy Principle 8 forbids:

```
zCompost/
  Notes/        Apple Notes, mirroring the upstream folder tree
    Notebook/   thoughts/   big stuff/   …
    *.md        ← iCloud's default "Notes" folder collapses to the root
  Voice/        voice memo transcripts        (Phase 4)
  Inbox/        things shared from the phone  (Phase 5)
  Media/        audio and images
  Queue/        read-later                    (Phase 8)
  Digests/      interpretation layer          (Phase 7)
  _superseded/  never-lose-data holding pen
```

Mirroring is deliberate: a quotes list and a personal notebook are different
enough that flattening them loses real information. It is applied at creation
only — the writer never moves a file afterwards, because a script rename
silently breaks `[[wikilinks]]` that Obsidian would repair for its own renames.
Reorganizing in Apple Notes therefore causes drift, which is accepted; run
`relocate` by hand if it ever matters.

## Circuit breaker

`writer.max_new_per_run: 50` caps new files per run. Apple Notes IDs are tied to
the local Notes database, so rebuilding it — new Mac, re-adding the iCloud
account, a corruption repair — reissues **every** ID, and composter would see
thousands of unrecognized notes and duplicate the whole library. The cap turns
that into an alarm instead. It binds only during the initial backfill, where
`pull --max-new N` raises it for one run, by hand, never in the agent.
