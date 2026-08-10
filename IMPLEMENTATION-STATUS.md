# Composter — implementation status

A living companion to [IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md). The plan
states the intent and the reasoning and does not change; this document records
what has actually been built, what contact with the real system changed, and
what remains. Where the two disagree, this one describes reality.

**Where things stand:** capture works. Apple Notes flows into the vault on an
hourly schedule, with the existing writing untouched. Retrieval does not exist
yet, and that is the next real question.

---

## Build status

| Phase | State | Notes |
|---|---|---|
| 0 — Reconnaissance | **done** | Sync binding confirmed; Automation consent granted; kitchen-sink fixture captured; JXA timing measured |
| 1 — The spine | **done** | `config` `db` `vault` `main` `doctor` `status` + fixture source; full state machine exercised before any real source existed |
| 2 — Apple Notes, text | **done** | JXA two-phase fetch, `htmlmd`, folder mirroring; five-step milestone passed on the real vault |
| 3 — Scheduler + failure surface | **done** | Hourly launchd agent, `flock`, three-tier failure surfacing |
| — Live with it for a week | **pending** | The deliberate pause. Principle 12 names tool-building as the top risk to the enterprise |
| 4 — Voice Memos | not started | Blocked on Full Disk Access |
| 5 — iOS inbox + `Compost` shortcut | not started | Blocked on Full Disk Access |
| 6 — Backfill existing notes | not started | Verb exists and refuses by design |
| 7 — Retrieval | not started | Gated on a populated corpus, which now exists |
| 8 — Read-later queue | not started | Gated on retrieval |

67 tests, all passing. ~3,000 lines across `src/`, `triage/`, `scripts/`.

---

## What Phase 0 actually established

The plan's four open questions, answered against the real machine:

- **Sync binding.** `~/Desktop/main` is the live vault. The second registered
  vault at `~/Documents/Main` is months stale and not sync-connected — a
  non-issue, not the diverging-forks risk the plan feared.
- **JXA timing.** A full index of **3,080 notes takes ~6 seconds**; folder
  membership under one second. Both are O(1) in Apple Events, as designed. No
  watermark needed, and the schedule is unconstrained by fetch cost.
- **Automation consent** was already granted. Full Disk Access still is not,
  which blocks Phases 4–5 only.
- **Notes HTML fidelity**, measured against a real kitchen-sink note, is worse
  than the plan assumed in three places. See below.

---

## Where reality differed from the plan

These are the load-bearing surprises. Each is a case where building against the
real system taught something argument could not.

### Apple Notes' HTML is lossier than expected

The plan anticipated losing checklist checked-state. Measured, the losses are
wider — and all are in Apple's own scripting API, so the sqlite route would not
recover them either:

| Construct | Reality |
|---|---|
| Checklists | Arrive as a plain `<ul>`. No checked flag, and checked items may be dropped entirely |
| Numbered lists | Emitted as bare `<li>`s merged into the preceding `<ul>`; degrade to bullets |
| Blockquotes | Emitted as plain `<div>`s; quoting is lost |
| Links | **No `<a href>` at all** — URLs arrive as underlined text |
| Tables | Survive, but wrapped in `<object>`, which naive parsing drops |
| Headings | Only survive if typed as HTML; UI heading styles arrive as styled spans |

Handled where possible: `<object>` is unwrapped so tables survive, and bare URLs
are unwrapped from `<u>` so Obsidian autolinks them. The rest is documented and
accepted. `tests/fixtures/notes_kitchen_sink.html` is now a snapshot test, so a
macOS update that changes any of this fails a test rather than silently
degrading a year of imports.

### One account enumeration is not enough

`Notes.folders` returns only the default account's folders. Iterating
`Notes.accounts()` first was required — without it, **1,437 of 3,080 notes had
no folder** and two accounts each had a folder called "Notes" that shadowed each
other.

### Recently Deleted is reachable through the API

Notes in Recently Deleted are returned by the index like any other. Importing
them would have resurrected, in the vault, every note the owner had just
deleted. Always excluded now.

### Title-only notes are real captures

A large share of this library is one-line jots where the title *is* the thought
and the body is empty. An early "skip empty notes" rule discarded them. They now
import with an empty body; only genuinely contentless notes are skipped.

### Change detection must hash the upstream payload, not the rendering

Hashing the converted markdown would mean any improvement to the HTML converter
dirties every file at once, triggering rewrites and conflict checks across the
whole library. `source_hash` is taken over the raw HTML plus attachment names.

### The isolation check needed two different meanings

A single baseline captured at `init` cannot distinguish "composter wrote outside
its folder" from "the owner edited their own vault", and the latter happens
constantly. Split in two:

- **The guarantee**: every `pull` snapshots every file outside `zCompost/`
  before and after itself and aborts on any change *it* caused. This is the real
  protection and it runs on every import.
- **A drift report**: `isolation --check` compares against the `init` baseline
  and reports differences as drift, not violations, with a re-baseline hint.

### Folder structure is mirrored, deliberately

Not in the plan, added after seeing 2,000 notes land in one flat folder: the
Apple Notes folder tree is reproduced under `zCompost/Notes/`. A quotes list and
a personal notebook are different enough that flattening loses information.

Mirroring is applied **at creation only**. The writer never moves a file
afterwards, because a script rename silently breaks `[[wikilinks]]` that Obsidian
would repair for its own renames. Reorganizing upstream therefore causes drift,
which is accepted; the hand-invoked `relocate` verb exists if it ever matters.

### Triage was attempted, failed, and was parked

A pass at classifying notes by *value* — worth keeping or not — using keyword
rules produced results bad enough to be unusable: a regex for password-shaped
strings matched `goggles!!!`, filing a packing list under credentials, while a
catch-all fallback swept doctor's notes into "reflection".

Two lessons, both now enforced in the code:

1. **Classifying by form is reliable; classifying by value is not.** What
   survives (`triage/obvious.py`) judges only form — no text at all, digits
   outnumbering letters, a string matching a real vendor key format — and prints
   every match so precision can be checked. A "scratch calculation" rule was
   written and deleted after scoring 1-in-4 on real notes.
2. **Exclusion is a retrieval question, not a capture one** (Principle 9). An
   unexcluded grocery list costs a vector that never matches anything; a wrongly
   excluded thought is gone. Whether junk actually hurts cannot be known until
   retrieval exists.

793 notes were excluded by hand and 94 by folder rule. The tooling is documented
in the README and parked until Phase 7.

### Notes apps accumulate credentials, and it is worth checking

Incidental to the exercise but worth stating as a general finding: a personal
notes library of this size turned out to contain a number of live API keys and
passwords in plaintext, syncing to every device. `triage/obvious.py` matches
real vendor key formats (`sk-`, `AKIA`, `ghp_`, and similar) precisely so this
surfaces. It is a security matter rather than a triage one — the fix is to
rotate and delete, not to exclude.

---

## What the capture layer looks like now

```
~/Desktop/main/zCompost/
  Notes/          Apple Notes, mirroring the upstream folder tree
    Notebook/  thoughts/  quotes/  big stuff/  words/  …
    *.md          ← iCloud's default "Notes" folder collapses to the root
  Voice/  Inbox/  Media/  Queue/  Digests/      (later phases)
  _status.md      heartbeat, rewritten only when its content changes
  _superseded/    never-lose-data holding pen
```

Every file carries the full frontmatter contract: `created` (the note's true
original date, unrecoverable if not captured at import), `captured`, `source`,
`composter_id`, `composter_authorship`, `composter_source_ref`, and the reserved
`zone` / `consumed` keys for the queue that ships later.

**Safety properties, each with tests:**

- Path containment before every write, unlink, or rename.
- A sentinel file the writer refuses to start without — two vaults are
  registered on this machine.
- Atomic writes: temp file → `fsync` → `os.replace`.
- No delete path anywhere, with exactly one documented exception: the escalation
  alarm deletes itself, guarded by both a containment check and an exact
  filename check.
- Graduation and dismissal are terminal, enforced at the database layer.
- Dismissal requires a marker to be absent for 3 consecutive runs spanning an
  hour, so sync lag can never be read as deletion.
- `max_new_per_run: 50` turns a mass ID re-issue into an alarm instead of
  thousands of duplicate files.

---

## What is next, and what it depends on

**Immediately: live with it.** The plan makes the week-long pause a real step,
and it is the step most likely to be skipped. A week of using a Notes-only
composter will teach more about the capture layer than another week of building.

**Then Phase 7 — retrieval, the first genuinely open question.** Everything so
far has been mechanical: identity, atomicity, deletion semantics. Retrieval is
where the project either becomes useful or does not. The plan's instruction is
to install Smart Connections on the now-populated corpus and live with it before
building anything, then decide how much of the structure half (authorship, date,
and zone filtering; digests; the timeline view) is worth building.

Three questions are waiting for that corpus, and none can be answered before it:

- Does junk in the archive actually degrade results, or was the whole triage
  exercise unnecessary? (See [BACKLOG.md](BACKLOG.md).)
- Do "what was I thinking about last spring" and "find me something about the
  feeling of leaving a place" need different retrieval modes, or does one pool
  with date filtering serve both?
- Is a hand-written digest insight, or beautiful-sounding nothing? The plan says
  to write one by hand and read it before building any machinery around it.

**Phases 4 and 5 are blocked only on Full Disk Access**, which is a System
Settings grant, not a build problem.

Deferred ideas with their reasoning live in [BACKLOG.md](BACKLOG.md).
