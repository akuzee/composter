# Composter — Implementation Plan

A personal capture-and-retrieval system built on an existing Obsidian vault. This document is self-contained: it states the intent, the principles, the verified environment, the architecture, and the build order, and it is the only document needed to implement the system.

---

## 1. What this is

**The problem.** One person with several creative interests running in parallel — writing, photography, video, music — wants to catch and use the things that actually show up: an idea, an urge, a shot, a phrase. Not to schedule creative time, but to keep more fronts alive with less friction.

Capture friction is the obvious half of the problem and the smaller one. The real failure is at the other end: **a note holding a half-formed idea is not an asset sitting in a pile, it is a debt.** A folder of them is a folder of obligations, and accumulating obligations is what makes the whole enterprise feel bad. Two things follow, and they shape every decision below:

- **The unit of work is the smallest complete thing.** Not a song — one finished eight-second loop. Not an essay — one paragraph that stands alone. Satisfaction comes from closing a loop at any scale.
- **A pile is only demoralizing if the pile is the destination.** If it is explicitly a staging area with a mechanism by which good things graduate out of it, it stops being a pile of debts and becomes a compost heap.

**The organizing metaphor is composting**, and it does real work rather than decorating: compost does not require completeness, it requires good scraps. Curation is not a compromise, it is correct — you don't want the noise in there. The design test to apply to any future decision: *does this help good scraps break down and recombine, or does it just make the heap bigger?*

**Two use cases, one store.** The archive serves double duty. Sometimes it is queried for raw material ("find me something about the feeling of leaving a place"); sometimes to remember who you were ("what was I thinking about last spring"). These are the same material asked different questions — the way a person was at the time and the things they were thinking are not separable — so they are never split into separate systems.

**Intended outcome.** Within about a week of working time, material flows from Apple Notes, Voice Memos, and the phone into the vault with near-zero friction and no risk to the writing already there. Within a few weeks after that, the whole archive is semantically searchable.

---

## 2. Principles

These are load-bearing. If a proposed change conflicts with one, the change is wrong unless the principle is explicitly retired.

1. **A net, not a system.** It catches what shows up; it does not schedule creativity.
2. **Composting, not archiving.** Good scraps, not completeness.
3. **One pool.** Reflection and creative material are the same material. Never split them.
4. **The unit is the smallest complete thing.** Closed loops at any scale beat started-and-abandoned at any scale.
5. **The pile is a staging area, never a destination.** Graduation is what makes the pile safe to have.
6. **Capture is non-negotiable; everything else is deferrable.** If capture has friction, nothing else matters.
7. **No batch chores.** Any periodic sort-through-everything ritual will be abandoned. In-the-moment intent beats retrospective sorting on both friction and signal quality.
8. **Never maintain a taxonomy by hand.** Hand-kept tags rot: they get used for a while, then abandoned, and the associations they encode shift underneath them. Meaning is inferred, not declared.
9. **Embed on capture; reason on retrieval.** Do not pre-compute an all-pairs semantic web nobody will look at.
10. **Plain files, always.** Markdown and media on disk, nothing locked in a custom database. The cheapest possible hedge against every future decision.
11. **The vault is the index, not necessarily the container.** Text and light media native; heavy media referenced.
12. **Build the selfish version.** Optimize for one user. Do not let building the tool become the creative project that eats the other creative projects.

Two clarifications that prevent predictable misreadings:

- **Principle 3 is about not splitting reflection from creative material.** It does not forbid the system knowing *whose* words a document contains, or whether an item has been read. Those are mechanical properties, not fuzzy judgments.
- **Principle 10 is a claim about the corpus, not about every byte the system writes.** A search index that can be rebuilt from the markdown at any time locks nothing in.

---

## 3. Constraints and decisions

| Decision | Choice |
|---|---|
| Build order | **Capture first.** Retrieval cannot be evaluated on document types that do not exist in the vault yet |
| Vault location | **`~/Desktop/main`, unmoved** |
| Sync | **Assume Obsidian Sync is active** with the vault present on the phone |
| Backup | Obsidian Sync version history + Time Machine. **No git repo inside the vault** |
| Existing notes | **Untouched for the entire initial buildout.** Backfill is a later, hand-invoked phase with its own safety net |
| Isolation | **Exactly one new folder, `zCompost/`.** Nothing else in the vault is created, modified, moved, renamed, or deleted by any code path during the buildout |
| Retrieval | Start by trialling an existing tool on the full corpus before building one |

### 3.1 Isolation is the top priority

The vault already contains 136 hand-written markdown notes organized into a curated tree. That is the **distillation layer** — writing that has already been thought through. Nothing in the initial buildout may alter it. This is not a preference to be traded against convenience; it is the constraint everything else bends around.

**Regime 1 — the initial buildout (Phases 0–5).** The system's entire footprint is `zCompost/`. Zero writes outside it, by any code path. Enforced four independent ways, because one is not enough for something unrecoverable:

1. A path-containment assertion in `VaultWriter` before every write, unlink, or rename — an `assert`, not a comment.
2. A sentinel file (`zCompost/.composter-vault-id`) the writer refuses to start without, so it can never be pointed at the wrong vault.
3. No delete path anywhere in the codebase. Superseded content moves to `zCompost/_superseded/`.
4. A standing isolation test that hashes every file outside `zCompost/` before and after a run and fails on any difference (see **Verification**).

Consequently, during the buildout: no vault move, no `git init` in the vault (a second folder plus continuous writes), no tidying of stale files, and no frontmatter written into any existing note.

**Regime 2 — backfill, later and deliberately.** Once capture is working and trusted, backfill becomes its own phase, invoked by hand, never on a timer, never as a side effect. Safeguards in **Build order**, Phase 6.

**What waiting costs.** Until backfill runs, the indexer infers dates for pre-existing notes heuristically at index time — parsing filename patterns, falling back to first-line content and mtime — and stores the guess in the index only, never in the file. The existing filenames are genuinely ambiguous (`3-9-26` could be March 9th or September 3rd; `12-4` omits the year), so any timeline view is approximate for older material until backfill fixes it. Search is unaffected, since semantic matching does not depend on dates. Legacy notes are also identified by vault-relative path rather than an embedded ID during this period, so renaming one orphans anything citing it. Both costs are temporary, and both are the right trade for not risking the archive while the code is least proven.

### 3.2 Graduation is already how the owner works

The isolation constraint improves the design rather than fighting it. "Graduation" — the mechanism that makes a staging pile psychologically safe — already exists in this vault as a habit: **`zCompost/` is the raw layer; the existing curated tree is what things graduate *into*.** Dragging a file out of `zCompost/` into `Main/Areas/Art/` is not a metaphor bolted onto the filesystem; it is the move already made when something is worth keeping. The system only has to notice and stop touching it.

**The owner moves files out of `zCompost/`. The system never moves anything.**

---

## 4. Verified environment

Facts established by inspection on the target machine. Not assumptions.

- **macOS 26.5.2, arm64 (M4-family MacBook Pro).**
- **Obsidian 1.9.14**, vault at `~/Desktop/main`: 136 markdown notes, ~1.2 MB, of which only 19 have frontmatter (all web-clipper output). Structure: dated notes at root, plus `Main/{Zettlekasken, Areas/*, Projects/*}`, `Clippings/`, `Misc/`, `zAdmin/`, `zClippings/`. **Zero community plugins installed.**
- The vault uses a **`z` prefix for non-primary folders** (`zAdmin/`, `zClippings/`). The machine's subtree follows that idiom.
- **Full Disk Access is not currently granted.** `NoteStore.sqlite` (39 MB), the Voice Memos group container, `~/Library/Mobile Documents/`, and `~/Documents` all return `Operation not permitted`. `~/Desktop` is readable.
- **The macOS 26 Notes scripting dictionary is sufficient.** `/System/Applications/Notes.app/Contents/Resources/Notes.sdef` exposes, on `note`: `id` (read-only unique identifier), `name`, `body` ("the HTML content of the note"), `plaintext`, `creation date`, `modification date`, `password protected`, `container`. On `attachment`: `id`, `name`, `content identifier` ("the content-id URL in the note's HTML"), `URL`, and a `save` command. **This requires Automation consent only, not Full Disk Access** — so the highest-value source can ship before the TCC blocker is resolved.
- **`VoiceMemos.app` has no `.sdef`.** No scripting surface; it is Full-Disk-Access-or-nothing.
- **Already installed:** whisper-cpp 1.8.4 with a working Metal backend and `~/.cache/whisper-models/ggml-base.en.bin`; ffmpeg 8.1.1; Python 3.13.9; Swift 6.1.2; sqlite3 3.51.0; Homebrew at `/opt/homebrew`. `beautifulsoup4` and `PyYAML` are present. **`pandoc` is not installed**, so HTML→markdown is a Python job. No `uv`, no `pipx`, no `ollama`.
- **A working user-authored launchd agent exists to model** (`StartInterval`-based, currently loaded), so the pattern is proven on this machine.
- **`/usr/bin/shortcuts` works.** 24 shortcuts exist, including one that already writes quick notes to Obsidian — leave it alone and build a new one.

**One open anomaly, worth resolving but not blocking.** Obsidian Sync is believed active with the vault on the phone, but `~/Desktop/main/.obsidian/sync.json` (written when a local folder is bound to a remote vault) is **absent**, there are no sync entries in `obsidian.log`, and the per-vault files in Application Support hold only window geometry. Obsidian also registers a **second vault at `~/Documents/Main`**, which is FDA-blocked and could not be inspected. The likeliest reading is that `~/Documents/Main` is the Sync-connected one and the phone has been showing *that* vault since roughly October 2025, meaning two copies have been diverging. Confirm in Settings → Sync before pointing automation anywhere. (Three `*.sync-conflict-*` files in `.obsidian/` are unrelated — they use Syncthing's naming convention and date to Feb 2025.)

Assuming sync is on has three design consequences, all handled below: the dismissal grace period becomes load-bearing rather than precautionary; in-vault voice audio counts against sync weight (~50 MB/year, comfortably fine); and the iOS holding folder becomes a deliberate choice rather than a forced one.

---

## 5. Architecture

Python 3.13, plain `venv` + `requirements.txt` (no `uv`, no Poetry), SQLite as the only durable state, YAML config, `python -m src.main <verb>` subcommands, idempotent phases, derived outputs treated as disposable and regenerable. No frameworks, no build step, no TypeScript.

```
~/Projects/composter/
  requirements.txt          # pyyaml, beautifulsoup4, markdownify, python-dateutil
  config/composter.yaml     # single config file
  state/
    composter.sqlite        # THE ledger — the only durable state
    pending/                # upstream payloads parked during a conflict
    transcripts/            # raw whisper JSON
    logs/
  src/
    main.py                 # argparse subcommands
    config.py  db.py
    vault.py                # VaultWriter — the ONLY code that touches the vault
    htmlmd.py               # Apple Notes HTML -> markdown
    doctor.py  status.py
    sources/{base,fixture,apple_notes,voice_memos,ios_inbox}.py
    jxa/{dump_index,dump_bodies,dump_folders}.js
  tests/fixtures/
```

Four homes, cleanly separated:

| What | Where | Durable? |
|---|---|---|
| Code + config | `~/Projects/composter/` | version-controlled |
| Ledger, logs, whisper JSON | `~/Projects/composter/state/` | **yes — this is the state** |
| Markdown output | `~/Desktop/main/zCompost/` | regenerable from source + ledger |
| Heavy media (>25 MB) | `~/Media/composter/` | yes — these are originals |

### 5.1 Vault subtree

`zCompost/` is the only writable location and the only new top-level folder.

```
~/Desktop/main/
  Main/ Clippings/ Misc/ zAdmin/ zClippings/   ← untouched; composter cannot write here, ever
  zCompost/                                     ← the entire machine footprint
    .composter-vault-id      ← sentinel; writer refuses to construct without it
    _status.md               ← heartbeat + failure surface
    !! needs attention.md    ← escalation alarm; self-deletes on next success
    _superseded/<date>/      ← never-lose-data holding pen
    Notes/ Voice/ Inbox/     ← produced zone, by source
    Queue/                   ← to-consume zone (§9)
    Digests/                 ← interpretation layer, later
    Media/
```

The `z` prefix sorts it to the bottom of the file explorer — the compost heap at the bottom of the garden, out of the way of the distillation layer.

**No exceptions to containment.** It is tempting to put the escalation alarm at the vault root so it sorts above every hand-made note. Don't. The alarm lives inside `zCompost/`, and the visibility it loses is bought back with a macOS notification (`osascript -e 'display notification'`), which is appropriate precisely because escalation is rare.

**`zCompost/` is not a second pool.** Principle 3 forbids splitting personal from creative; this splits by *managed-ness* — machine-owned vs. human-owned, temporary by design, dissolved by graduation. Reflections and lyrics land in the same folder. Do not later add `zCompost/Personal/` and `zCompost/Creative/`.

The one legitimate subdivision is `Queue/`, on an entirely different axis: **produced vs. to-consume** (§9). That distinction is mechanical — a thing is read or it isn't — which is why it does not rot the way a topic axis would.

### 5.2 CLI

```
doctor      preflight: Automation consent? FDA? whisper? ffmpeg? sentinel? config valid?
init        create zCompost/ skeleton + sentinel + DB. idempotent.
reindex     rescan vault for composter_id markers, reconcile ledger with reality
pull        [--source notes|voice|ios] [--limit N] [--dry-run]
status      recompute + rewrite zCompost/_status.md, print JSON
resolve     --id <composter_id> --take-upstream | --keep-mine
backfill    --propose | --apply [--dry-run] | --undo      (Phase 6 only)
all         reindex + pull all enabled sources + status   ← what launchd calls
```

**Write `doctor` first.** Four capability grants (Automation consent, Full Disk Access, the whisper model, the vault sentinel) can each fail silently. A verb whose entire job is printing a green/red checklist pays for itself in the first hour.

---

## 6. The frontmatter contract

Land this before writing any source. It is the capture layer's entire obligation to the retrieval layer, and several fields are **permanently unrecoverable** if not captured at import time.

```yaml
---
title: Composting metaphor
created: 2026-08-09T14:32:11-04:00      # when the thought happened
captured: 2026-08-09T14:40:02-04:00     # when it entered the vault
source: apple-notes                      # apple-notes|voice-memo|ios-share|web-clipper|zotero|manual
kind: note                               # note|transcript|clipping|snippet|photo|link|paper|digest
zone: produced                           # produced|queue
consumed: null                           # null | ISO8601 date  (queue zone only)
tags: [compost/notes]                    # PROVENANCE ONLY, never topic
composter_id: "notes:x-coredata://B1C2…/ICNote/p1234"
composter_authorship: mine               # mine|theirs
composter_hash: 3f1a9c…
composter_rev: 7
composter_managed: true
composter_media: []                      # explicit resolvable paths
composter_source_ref: "Notes/Ideas"
---

<!-- composter:begin -->
Tracking my inner life for the purpose of composting it…
<!-- composter:end -->
```

Un-namespaced keys are the ones a human or Obsidian Bases (already enabled in this vault) would query, and they deliberately reuse the web clipper's existing vocabulary (`title`/`source`/`created`/`tags`) rather than inventing a parallel scheme. `composter_*` is machine internals.

Six requirements that look optional and are not:

- **`composter_id` must be written into the file**, not merely held in the ledger. Citations, feedback, and search results reference items durably; if IDs live only in SQLite, losing that database orphans everything and the vault stops being self-describing. **Filenames are never identity** — the vault already contains files like `title 12-14 (fave so far).md`, which will obviously be renamed.
- **`created` ≠ `captured`.** They diverge sharply for clippings (an existing one has `published: 2024-09-20`, `created: 2026-05-25`) and for anything backfilled. Conflating them wrecks any timeline view. Creation dates are available at import and unrecoverable afterward.
- **`composter_authorship`.** The clippings folders contain *other people's writing*. Without this marker, "what was I thinking about in the spring" returns someone else's essay as though it were the owner's own thought — a wrong answer in the system's primary use case, and one no amount of embedding quality fixes. Path heuristics work today and break the moment files move; write it into frontmatter.
- **`composter_media` as explicit paths.** Following Obsidian's `![[file.png]]` requires reimplementing its basename-search link resolution across the whole vault. An explicit field costs nothing at write time.
- **Photo EXIF capture date → `created`, at import.** Once a photo leaves the camera roll through an iOS Shortcut, EXIF may be stripped. Lose it and that photo has no true date, forever.
- **`zone` and `consumed` are reserved now even though the queue ships later.** Two lines today; a migration across every file later.

**One file per capture, always.** An append-only `Inbox.md` accumulating 200 unrelated snippets is *one item*: one ID, one timestamp, one incoherent embedding averaging everything ever shared. Splitting it later requires an LLM pass and permanently loses per-item timestamps. Every capture gets its own timestamped file.

**Deterministic writes.** Re-running an importer must produce byte-identical files for unchanged sources: stable frontmatter key order, no `updated_at: now()`, no re-serialization churn. Otherwise every run dirties every file, every content hash changes, and sync churns.

---

## 7. The ledger, the state machine, and the writer

### 7.1 Ledger

`state/composter.sqlite`, table `items`, `UNIQUE(source, source_id)`. Also `assets`, `runs`, and a `kv` table for watermarks and schema version.

Four column choices worth defending:

- **`source_hash`** — sha256 of the canonical upstream payload. **This is the change detector.** `source_modified_at` is only a prefilter deciding *which bodies to fetch*, because Apple Notes bumps modification dates on non-substantive events. Triggering rewrites off the date causes needless writes, which trip conflict detection for no reason.
- **`written_hash`** (the whole file last written) **and `managed_body_hash`** (just the fenced region). Both are needed to distinguish "a paragraph was appended below the fence" (fine, preserve it) from "the imported text itself was rewritten" (conflict).
- **`fingerprint`** = `hash(created_at + first 200 chars)`, for disaster recovery when upstream IDs change (Risk 1).
- **`state`** — deletion is a state, not a boolean.

```
new ──► managed ─┬─ moved outside zCompost/ ──────► graduated  (terminal)
                 ├─ marker gone from vault ───────► dismissed  (terminal)
                 ├─ composter_managed: false ─────► graduated
                 └─ local edit + upstream edit ───► conflict ──► managed | graduated
skipped   (locked note, empty, too short — re-checked each run)
error     (transient; error_count increments, retried with backoff)
```

`graduated` and `dismissed` are **terminal**. Moving a graduated file back into `zCompost/` does not resume management: the failure mode of "accidentally resumed and clobbered work" is far worse than "had to re-manage it explicitly."

### 7.2 VaultWriter

`VaultWriter.write(capture) -> WriteResult` is the only function permitted to mutate the vault. Its invariants should be **actual assertions, not comments**:

1. **Path containment** — `assert resolved.is_relative_to(self.managed_root)` before every write, unlink, or rename. No exceptions.
2. **Sentinel check at construction** — refuses to build unless `zCompost/.composter-vault-id` matches config. Obsidian registers two vaults on this machine, so pointing at the wrong one is not a theoretical risk.
3. **Atomic writes** — temp file in the same directory → `fsync` → `os.replace()`. Obsidian's file watcher will index a half-written file given the chance.
4. **Never destroys** — superseded content moves to `zCompost/_superseded/<date>/`.
5. **Never renames an existing managed file.** The vault has `alwaysUpdateLinks: true`, but that only repairs wikilinks when *Obsidian* performs the rename; a script rename silently breaks every `[[link]]`. Filename is chosen once at creation; title drift lives in frontmatter.
6. **`--dry-run` threaded through the writer itself**, not simulated by callers.
7. **Idempotent** — the same capture twice yields `created`, then `unchanged` with zero bytes written.

**Filenames** follow the owner's existing convention: `zCompost/Notes/composting metaphor 8-9-26.md`, matching hand-written notes like `micro-hci durable findings 8-4-26.md`. A graduated file dragged into the curated tree should look native on arrival.

### 7.3 The edit-clobbering rule

Imported files are overwritten in place, but Obsidian invites editing. Four layers, applied in order:

**Layer 1 — Don't write unless upstream actually changed.** If `capture.source_hash == ledger.source_hash`, return `unchanged` and do not open the file. This alone eliminates ~95% of all clobbering and costs one `if`.

**Layer 2 — The fence.** Only the region between `<!-- composter:begin -->` and `<!-- composter:end -->`, plus `composter_*` frontmatter keys, is machine territory. On update, the writer splices in the new managed region and preserves **everything below the end fence byte-for-byte**, plus any non-`composter_*` frontmatter added by hand. Annotations, appended sections, personal tags, and wikilinks into the curated tree all survive indefinitely. This is what makes the compost heap a place you can *work* rather than a read-only dump.

**Layer 3 — Conflict detection for the residual case.** If upstream changed *and* the on-disk fenced region no longer matches `managed_body_hash`: **write nothing**, park the new upstream markdown at `state/pending/<id>.md`, set `state='conflict'`, and surface it in `_status.md` as a wikilink. Resolve on demand — `resolve --take-upstream` (the local version moves to `_superseded/`) or `--keep-mine` (graduates in place, severs the link). Nothing is lost in either branch.

**Layer 4 — Graduation and dismissal via a full-vault marker scan.** Every `pull` begins with `reindex`, which walks the vault building `{composter_id → path}`. At 136 files this is single-digit milliseconds; still trivial at 10,000.

| Marker found | Meaning | Action |
|---|---|---|
| At the recorded path | normal | update per layers 1–3 |
| Elsewhere **inside** `zCompost/` | heap reorganized | update path, keep managing |
| **Outside** `zCompost/` | **graduated** | never write again |
| Nowhere in the vault | **deleted by the owner** | `dismissed` — never recreate |
| Present, `composter_managed: false` | explicit opt-out in place | graduated |

**Dismissal needs a grace period.** "Marker is missing" and "the file hasn't synced down yet" are indistinguishable to a scanner. With sync active this is routine, not hypothetical — it happens whenever the machine wakes before sync settles. A missing marker must therefore persist across **3 consecutive runs spanning at least one hour** before dismissal, with the intermediate state recorded rather than acted on. One counter column, and it removes the only path by which the system could permanently forget material that still exists.

The `dismissed` state matters as much as `graduated`. Without it, every run resurrects notes that were deliberately deleted — the single most infuriating bug in this category of tool, and one that would destroy trust in a week. It is also the other half of composting: some scraps get thrown out.

**Honest tension:** `resolve` is a manual chore and Principle 7 bans chores. The defense is that layers 1–2 should reduce it to a handful of events per year, it appears passively in a status file rather than as a notification, and the alternative to a rare chore is silent data loss. If it fires more than monthly in practice, flip `writer.on_local_edit: graduate` so any local edit auto-graduates the file. It is a config key from day one precisely because usage, not argument, should decide.

### 7.4 Why the spine comes before the sources

**There is exactly one hard problem in the capture layer, and it is not source-specific:** a file in a human's vault has two authors and they will collide. Identity, dedupe, atomic writes, graduation, conflict handling, and deletion-means-deletion are 90% of the risk and 100% of the surface where a day-one mistake poisons the archive. That belongs in one place, written once, tested once.

The sources are thin by comparison. Apple Notes is "shell out to JXA, hash the HTML, convert what changed." Voice is "list a directory, shell out to ffmpeg and whisper." iOS is "list a directory, move files." **No source module should know what a vault is, what a conflict is, or what graduation means.** If a source imports `os.replace` or writes to a vault path, the design has failed.

Build `db.py` + `vault.py` + `main.py` + `doctor.py` plus a ~20-line **fixture source** yielding synthetic captures from a YAML file, and exercise the entire state machine against the fixture before Apple Notes exists. That turns "drag a file out and confirm it's left alone" into a two-second test rather than a manual dance in Notes.app.

**Do not build a plugin loader, entry points, or a registry format.** A dict literal mapping three strings to three classes is the correct amount of pluggability, and over-abstracting here is this project's favorite scope-creep entry point.

---

## 8. Sources

### 8.1 Apple Notes — JXA via `osascript`

**Rejected: reading `NoteStore.sqlite` directly.** The content is gzip-wrapped protobuf with styled text in parallel `AttributeRun` arrays and embedded tables in separate rows. Mature forensics-grade parsers exist, but they are Ruby, they work as a batch export you then diff against your own ledger, and they require Full Disk Access granted to a Ruby interpreter. The schema is undocumented and Apple changes it. The one genuine advantage — recovering checklist checked-state — does not justify trading the architecture for a checkbox.

**Chosen: JXA**, for four reasons in order of weight:

1. **It needs no Full Disk Access** — only Automation consent. The highest-value source ships without waiting on a System Settings dance, which matters given Principle 6.
2. **Identity comes from a documented API.** ID-keyed mapping is the one make-or-break requirement; a slightly weaker ID from a stable documented interface beats a nicer one from a reverse-engineered schema you will depend on for years.
3. **It is incremental by construction** — fetch a cheap index, pull bodies only for what changed. The sqlite route is inherently full-export-and-diff.
4. **Attachments are supported** (`attachment.save` plus `content identifier`), so it does not dead-end at the media phase.

**Use JXA, not AppleScript.** JXA emits `JSON.stringify` directly, so you never parse AppleScript's locale-dependent record syntax or its `date "Sunday, August 9, 2026 at 2:32:11 PM"` strings. Locale-dependent date parsing out of `osascript` is a classic source of silent, seasonal, timezone-shaped bugs.

**Two-phase fetch.** JXA's plural-specifier form returns an entire property column in *one* Apple Event:

```javascript
// src/jxa/dump_index.js
const n = Application('Notes').notes;
const ids = n.id(), names = n.name(), mods = n.modificationDate(),
      crts = n.creationDate(), lock = n.passwordProtected();
JSON.stringify(ids.map((id, i) => ({ id, name: names[i], locked: lock[i],
  modified: mods[i] ? mods[i].toISOString() : null,
  created:  crts[i] ? crts[i].toISOString() : null })));
```

Five Apple Events for the entire library regardless of size. Folder membership comes from a separate script iterating `Notes.folders` and calling `folder.notes.id()` — also O(folders), not O(notes). Then fetch bodies only for notes whose date moved, in batches of 25–50 ids per invocation.

**Avoid `.whose({...})` clauses.** JXA `whose` is inconsistently supported across apps and fails in surprising ways. Fetch all dates (cheap, one event) and filter in Python.

**HTML → markdown** (`htmlmd.py`). Notes' `body` HTML uses one `<div>` per paragraph and `<div><br></div>` for blank lines. Naive `markdownify` collapses those and destroys paragraph structure, so:

1. Parse with `bs4` (`html.parser`; avoid an `lxml` dependency).
2. Strip `<html>/<body>`; **drop the first heading if it duplicates `note.name`** — Notes uses the first line as the title, so otherwise every note contains its title twice.
3. Normalize `<div>` → block paragraph and `<div><br></div>` → blank line, *before* markdownify.
4. `markdownify(..., heading_style="ATX", bullets="-")`.
5. Collapse 3+ blank lines to 2; strip trailing whitespace.

| Construct | Handling |
|---|---|
| Paragraphs, headings, bold/italic, links, lists, nested lists, blockquotes | markdownify handles cleanly |
| Underline / strikethrough | Keep as raw `<u>`/`<s>` — Obsidian renders it |
| Tables | **Pass through as raw HTML.** Obsidian renders them. Do not write a GFM table serializer |
| Checklists | Unknown until measured (**Build order**, Phase 0). If checked-state is lost, render all as `- [ ]` and document it |
| Attachments / inline images | Phase 1: `> [!info] Attachment not yet imported: <name>` so nothing is silently lost |
| Password-protected notes | Filter on `passwordProtected` → `state='skipped'` |

`quiet_seconds: 120` — never import a note modified in the last two minutes, so a scheduled run cannot capture a half-written thought.

### 8.2 Voice Memos

Blocked until Full Disk Access is granted; the schema must be confirmed in Phase 0 before writing code.

- **Identity: `ZUNIQUEID`** from `CloudRecordings.db` — stable across renames and across devices. **Filenames are not stable** (renaming a memo renames the file in some versions). Fallback if the macOS 26 schema is unrecognizable: `sha256(first 1 MiB) + filesize`. Store whichever was not used as `source_alt_id`, so a later fix can re-key without duplicating.
- **Three gates against partial files, all required:** mtime older than 90s; size stable across two `stat`s at least 5s apart; and **`ffprobe` returns a sane duration**. The third is the strongest — a truncated or still-syncing `.m4a` fails it — and ffmpeg is already installed, so it is free. For memos arriving from the phone, detect `.<name>.icloud` placeholders, trigger `brctl download`, and defer to the next run rather than blocking.
- **Pipeline:** `ffmpeg -nostdin -loglevel error -i SRC -ar 16000 -ac 1 -c:a pcm_s16le` (whisper.cpp requires 16 kHz mono) → `whisper-cli -m MODEL -oj -of state/transcripts/<id>`. The note body is clean prose: join segments, start a new paragraph on gaps over 1.5s. **Preserve sentence punctuation** — a downstream chunker has nothing to grip otherwise. Cap `max_minutes_per_run` so one long recording cannot blow a scheduled run.
- **Audio lives in-vault** at `zCompost/Media/Voice/`, embedded with `![[...]]` so Obsidian renders an inline player. Having the audio and a good transcript together is the point. At ~1 MB/minute, an hour a week is ~50 MB/year; the `max_inline_mb: 25` rule handles pathological cases automatically. Originals in Voice Memos are never touched — composter only ever copies.
- **Model:** ship on `ggml-base.en.bin` because it is already present, but **download `ggml-large-v3-turbo-q5_0.bin` (~550 MB) in week two and make it the default.** On reflective, half-mumbled, walking-around speech — the exact use case — `base.en` produces transcripts bad enough to make the feature feel worthless. That is a product risk, not merely an accuracy one. It is a config key, so switching costs nothing.
- Voice memos are **write-once**. Upstream never changes, so the conflict machinery is dormant here; only graduation and dismissal apply.

### 8.3 iOS — holding folder, not direct vault writes

Sync being active makes direct-vault-write from the phone possible. Reject it anyway. The holding folder keeps **the Mac as the single writer**, and two writers into one synced file tree is how you manufacture exactly the conflicts the fence logic exists to prevent. A phone-written file appearing mid-scan is precisely the race the dismissal grace period guards against; adding a second writer widens that window.

**Destination:** `~/Library/Mobile Documents/com~apple~CloudDocs/Composter Inbox/`, swept by the Mac. (Gated on the same Full Disk Access grant as Voice Memos. A no-FDA fallback via Dropbox exists but the only Dropbox account on this machine is institutional, and personal reflections do not belong there.)

**Build one new shortcut named `Compost`.** Share Sheet on, accepting Text, URLs, Images, Files, Media; also on the Action Button. Do not repurpose the existing quick-note shortcut.

1. Receive share-sheet input.
2. If input is empty → `Ask for Input` (this makes the same shortcut a one-tap jot from the Action Button); otherwise take the input.
3. Format date → `yyyy-MM-dd'T'HHmmss` → `TS`.
4. If image or file: `Save File` to `Composter Inbox/<TS>-1.<ext>`, *Ask Where to Save OFF*, *Overwrite OFF*.
5. Save a JSON sidecar `<TS>.json`: `{captured_at, kind, text, source_url, files[]}`.
6. **There is no step 6.** No caption prompt, no folder picker, no confirmation. If captions are wanted, make a *second* shortcut; do not tax the common path for the rare one.

**The Shortcut emits structured JSON, not pre-rendered markdown.** That keeps every formatting decision on the Mac in `vault.py` where the fence and frontmatter logic already lives. Shortcuts is a miserable place to maintain a markdown template, and doing it there produces two divergent renderers.

**The Mac sweeper** handles iCloud placeholders (never treat one as an empty file), applies the same quiet-period and size-stability gates as voice, and **moves** consumed sources to `Composter Inbox/_ingested/<YYYY-MM>/` rather than deleting them — so a bug cannot destroy a capture, and the visibly-empty inbox is its own quiet health signal on the phone.

### 8.4 Web content

**Change nothing.** The Obsidian Web Clipper already writes markdown into the vault with the source URL captured automatically. It is a free win that already works, requires no building, and should simply be leaned on more.

---

## 9. The read-later queue

A second, related problem: interesting things encountered online — articles, threads, papers — where **capture is already solved** (web clipper, Zotero) but the queue is invisible, unprioritized, and effectively lost. There is no way to see what is queued in a form that allows choosing based on present interest, no sense of the "vibe" of what is waiting, and no notion of must-read versus someday-maybe. The cost is real: a great deal of idle browsing, reading things one would not have recommended to oneself, while a deliberately-chosen backlog sits unseen.

**It belongs in this project: same retrieval machinery, different lifecycle.** Produced material has no "consumed, now done" state; a read-later queue drains. But if unread links dump into the same undifferentiated pool, the consumption backlog pollutes the reflection archive with things that are not the owner's and have not been metabolized.

**One system, two zones, one shared index.** The queue is `zCompost/Queue/` with `zone: queue` in frontmatter — inside the single machine folder, so isolation holds, but distinguishable in every query.

Four commitments:

- **The queue lives in the vault as notes, not as an external pointer index.** A clipped article is already markdown; a Zotero paper becomes a stub note carrying title, abstract, authors, and a link back to the Zotero item. The abstract is the thing worth embedding — it is what "vibe" retrieval matches against — and an index that merely points at Zotero has nothing to embed. Optionally, pointing the web clipper at `zCompost/Queue/` makes the existing clipping habit feed the queue for free; existing clippings stay exactly where they are either way.
- **Read state is marked by moving the file**, reusing the graduation mechanism rather than inventing a second one. Dragging a queue item into the produced zone turns it into source material — which is exactly the permeability wanted, and makes "I read this and it gave me a thought" a single drag. Items finished but leading nowhere get `consumed: <date>`.
- **Prioritization stays coarse** — a `must-read: true` flag and nothing else. Fine-grained priority carries the same rot risk as fine-grained tags.
- **Eviction is by decay, not deletion.** An infinitely growing unread list recreates the pile-of-debts problem the entire project exists to solve. So: **never show a count, never show a badge, never present the queue as a list.** It is reachable only by asking it something ("what's queued that fits what I'm thinking about right now"), and retrieval down-weights items older than ~90 days unless flagged must-read. Nothing is deleted; old links simply stop competing. A queue whose size you cannot see cannot become a debt.

**Sequencing:** the queue comes after retrieval exists. It is *entirely* a retrieval problem, and building the storage side first would produce a folder of links exactly as invisible as the current situation. The only thing needed now is the reserved `zone` / `consumed` frontmatter.

---

## 10. Retrieval

**Start by trialling Smart Connections on the full corpus, not by building an indexer.** [Smart Connections](https://smartconnections.app/smart-connections/) is a free, mature Obsidian plugin that runs local on-device embeddings over the vault, stores per-note and per-block vectors, surfaces related notes while writing, and ships an MCP server so an agent can query the vault. Much of what would otherwise be built already exists there.

Evaluate it **after capture has populated the vault**, not before. The question is whether semantic retrieval feels good across the *whole* archive — transcripts, snippets, clippings, and notes together, at volume — and that corpus does not exist until capture has done its work. Testing on the 136 pre-existing notes would not answer it.

**Smart Connections covers the search half and none of the structure half.** What it cannot do, because it only reads prose:

- **Authorship filtering.** It will return a clipped essay by someone else in response to "what was I thinking about in the spring." This is a correctness bug, and better embeddings do not fix it.
- **Temporal queries.** "What was on my mind last spring" is a date-range filter before it is a similarity search. It has no notion of `created`.
- **Zone awareness.** The queue needs produced-vs-queue as a first-class filter.
- **The interpretation layer.** Dated, compounding interpretation is a writing problem, not a retrieval one.
- **The timeline view.** Reflections plus photos assembled into a season is a different artifact entirely.

So: capture → Smart Connections on the real corpus → *then* decide how much of the structure half is worth building, informed by what actually gets reached for. It is plausible that Smart Connections plus the frontmatter contract covers most of it and the only remaining build is the timeline view. It is also plausible its ranking disappoints and a custom index is wanted. **Either way, the frontmatter contract is what keeps that choice open**, which is the argument for landing it before the first importer regardless.

Note before installing: Smart Connections writes vectors to `.smart-env/` in the vault, and installing any community plugin creates `.obsidian/plugins/`. Neither is composter writing outside `zCompost/` — the isolation rule governs this system's code, not the owner's choices about their own vault — but the folders will appear, and this vault currently has none.

### 10.1 If a custom index is built

- **Embeddings: local**, `Qwen3-Embedding-0.6B` via sentence-transformers on Metal. This corpus is the most intimate a person owns, and Whisper already runs locally for exactly that reason; shipping the transcripts to a third party to embed them would be a hole in that posture, not a tradeoff. Cost is a wash either way (the whole corpus is fractions of a cent hosted), so privacy decides. Qwen3's 32K context embeds even the longest existing note (~11,900 words) whole with nothing truncated. Fallback if the install fights: `BAAI/bge-m3`, then ONNX via `fastembed`. Store `model` and `dim` on every vector row and **refuse to mix**. A full re-embed takes under a minute, so the model choice costs 60 seconds to reverse — pick and move on.
- **Index: one SQLite file outside the vault**, float32 blobs, L2-normalized at write time, brute-force cosine in numpy. 5,000 chunks × 1024 dims is 20 MB, loads in ~50 ms, and one query is a matrix-vector product measured in microseconds. **No vector database.** ANN indexes exist to avoid O(n) scans; O(n) is free here until roughly a million vectors, which this corpus will never reach. Sidecar vector files are rejected — they would double the vault's file count and push regenerable binary through sync. The index is a **derived, disposable artifact**, rebuildable from the markdown at any time, which is why it does not compromise Principle 10.
- **Chunking: dual-granularity.** Note-level vectors answer "what was I thinking about in the spring"; paragraph-window chunks (~300 tokens, overlapping, **never split mid-paragraph**) answer "the feeling of leaving a place," which lives in one paragraph buried in a long note that a note-level average dilutes to nothing. Chunk only notes above ~350 tokens — 64 of the 136 existing notes are under 100 words, where chunking is a no-op. At query time, retrieve both levels and score each note as `max(note_score, best_chunk_score × 0.95)`, returning the best-matching chunk as an excerpt. That excerpt is not cosmetic: it is what makes results readable and what makes semantic search stop feeling like a black box.
- **Interface:** a `search` CLI as the substrate; an MCP server only if the filters Smart Connections lacks are actually needed. A single-file HTML timeline (inline CSS/JS, no build step) is the piece most likely worth building regardless, since nothing off the shelf does the "look back at a season" view. **Do not write an Obsidian plugin** — TypeScript, a build step, and it couples the archive to Obsidian, which is what Principle 10 exists to prevent. *Using* someone else's plugin carries none of that cost.
- **The accumulating interpretation layer.** The goal is that interpretation compounds over time rather than being recomputed cold. The design: **immutable, dated, cited digest notes** in `zCompost/Digests/` — first-class corpus items, embedded and retrievable like anything else, so a digest written in March is retrievable in September and September's can cite it. Compounding is automatic; no separate machinery. The insight that makes this work: *a taxonomy rots because it claims to stay true; a dated interpretation is never wrong, it is merely historical.* Never edit a digest — supersede it, with a pointer to what it replaces. Every claim cites source notes via wikilinks, which lights up Obsidian's backlink panel for free and keeps digests from degenerating into vague prose. Weight them below primary material in ranking, or return them in a separate slot, so interpretation appears as context rather than competition. **Generate one digest by hand and read it before building any scheduler around this** — it is the part most likely to produce beautiful-sounding nothing, and one attempt settles it.

---

## 11. Build order

**Phase 0 — Reconnaissance (half a day, no code).**

The vault is not moved and nothing in it is modified. Setup is exactly one action: **create `zCompost/` and drop the sentinel file in it.**

Confirm which local folder Obsidian Sync is bound to (Settings → Sync). If it is `~/Documents/Main` rather than `~/Desktop/main`, resolve that before pointing automation anywhere — two diverging vaults is a problem worth fixing on its own terms. Grant Full Disk Access to the interpreter that will run the pipeline. Then answer the four questions this plan cannot:

1. Enumerate `~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/` and dump `CloudRecordings.db`'s `ZCLOUDRECORDING` schema. Expected: `ZUNIQUEID`, `ZPATH`, `ZDATE` (Core Data epoch, 2001-01-01), `ZDURATION`, `ZCUSTOMLABEL`, `ZFOLDER` — but macOS 26 is unaudited. If the schema differs, only the identity-resolution function changes.
2. Create one Apple Note containing **every construct at once** — heading, bold, italic, underline, bullet list, numbered list, nested list, checklist with one item checked and one not, a 2×2 table, a link, a blockquote, an inline image — then dump its raw HTML with `osascript -l JavaScript -e 'JSON.stringify(Application("Notes").notes[0].body())'`. **Keep that note permanently as the fidelity fixture** and snapshot the HTML into `tests/fixtures/notes_kitchen_sink.html`, so a future macOS update fails a test instead of silently degrading a year of imports.
3. Time `dump_index.js` against the real library. If it takes minutes rather than seconds, drop to an hourly schedule and add a watermark.
4. Determine whether checklist checked-state survives into `body` HTML. If it does not: accept it, render everything as `- [ ]`, and document it. Do not switch to the sqlite route to recover one checkbox.

**Phase 1 — The spine (1 day).** `config.py`, `db.py`, `vault.py`, `main.py`, `doctor.py`, `status.py`, `sources/fixture.py`. Exercise the entire state machine against the fixture source before any real source exists.

**Phase 2 — Apple Notes, text only (1–1.5 days).** JXA scripts, `htmlmd.py` with the fixture test, `sources/apple_notes.py`. Always `--limit 5 --dry-run` first; then import in slices of 50, reading the output between slices.

> **► MILESTONE — "the loop is proved."** All five in one sitting:
> 1. `doctor` is green for Notes.
> 2. `pull --source notes --limit 5 --dry-run` prints five plausible files; the vault is untouched.
> 3. Dropping `--dry-run` writes exactly those five, and they *read well* in Obsidian.
> 4. Edit one note in Apple Notes, re-run → **that one updates, the other four are byte-identical** (verify with `md5`, not by eye).
> 5. Drag one file into the curated tree, add a line to it, re-run → **untouched**, and `status` reports it graduated.
>
> Step 5 is the one that matters. It is the moment the compost metaphor becomes a mechanism rather than a mood.

**Phase 3 — Scheduler and failure surface (half a day).** Test by deliberately breaking it: revoke Automation consent, confirm the alarm appears after three failed runs, restore consent, confirm it disappears.

> **► Then live with it for a week and change nothing.** This is a real step, not filler. Principle 12 names "building the tool becomes the creative project that eats the other creative projects" as the top risk to the whole enterprise. A week of using a Notes-only composter teaches more about what the capture layer should be than another week of building.

**Phase 4 — Voice Memos (1 day).** Unblocked and de-risked by Phase 0.

**Phase 5 — iOS inbox and the `Compost` shortcut (half a day).**

**Phase 6 — Backfill the existing notes (deliberate, hand-invoked, never automatic).**

This is the one time the system writes outside `zCompost/`, and it happens only after capture has been running and trusted for weeks. Six safeguards, all required:

1. **External snapshot first.** Copy the entire vault to `~/Backups/vault-pre-backfill-<date>/`, outside the vault, verified by file count and total size before proceeding. This is the rollback and it must exist before a single byte is written.
2. **Frontmatter-only; prose never touched.** Insert a YAML block at the top and change nothing below it. If a file already has frontmatter, merge keys, never replace. Assert the body is byte-identical before and after.
3. **Proposal, review, apply — three separate commands.** `backfill --propose` writes a TSV of every file with its inferred `created` / `kind` / `authorship` and the evidence for each guess. A human edits that TSV. `backfill --apply` reads only the TSV and never re-infers. Nothing is written during the proposal step.
4. **Dry-run diff.** `backfill --apply --dry-run` prints a unified diff of every file it would change.
5. **Batched, resumable, interruptible.** Apply in slices of 20 with a per-file record, so it can be stopped and inspected without leaving the vault half-converted.
6. **`backfill --undo`** restores from the snapshot, per-file or wholesale.

Files whose date genuinely cannot be inferred get **no `created` key at all** rather than a guess. An absent field is honest; a wrong one silently corrupts the timeline. Flag those in the TSV.

**Phase 7 — Retrieval.** Install Smart Connections on the by-then-populated corpus and live with it. Only then decide what to build: the likely remainder is authorship/date/zone filtering, digests, and the timeline view — not a search engine.

**Phase 8 — The read-later queue.** Zotero stub importer, `zone`-aware retrieval, the decay rule. Requires retrieval to exist first.

**Two weeks of actual use gates each phase from 7 onward.** To the milestone: ~2.5 days. All of capture: ~6 days including the deliberate pause.

**Explicitly out of scope for the capture layer, and worth stating at the top of the README:** no embeddings, no LLM calls, no vector store, no UI, no tags beyond provenance.

---

## 12. Verification

**Per phase, before moving on:**

- **Phase 1 (fixture).** Run seven transitions and assert each: create → unchanged (zero bytes written) → update → annotate-below-fence-then-update (annotation survives byte-for-byte) → edit-inside-fence-then-update (conflict; file untouched; payload parked in `state/pending/`) → move out of `zCompost/` (graduated) → delete (dismissed) → re-run (**stays** dismissed, not recreated).
- **Phase 2 (Notes).** The five-step milestone above, plus asserting `htmlmd.py` output against `tests/fixtures/notes_kitchen_sink.html`.
- **Phase 3 (scheduler).** Confirm the agent is loaded; revoke Automation consent and confirm the alarm appears after 3 failed runs and self-deletes after the next success; confirm `flock` prevents overlap by starting a run manually mid-tick.
- **Phase 4 (voice).** Record a 30-second memo, wait one tick, confirm a note appears with a readable transcript and a *playable* embedded audio player in Obsidian. Re-run and confirm zero bytes written.
- **Phase 5 (iOS).** Share a photo and a text selection from the phone; confirm two separate files land with correct timestamps, and that the photo's EXIF date became `created`.
- **Phase 7 (retrieval).** Write **8 gold queries** against the corpus where the right answers are already known, and score recall@10 by hand. Include a temporal query ("what was I thinking about in the spring") and an associative one ("the feeling of leaving a place").

**The isolation check is the most important test in the suite.** It is what actually protects the existing writing, so it runs after every phase and before every real `pull`, not as a one-time check.

**Do this before any other code runs against the real vault:** walk the whole vault and record `(path, size, sha256)` for every file outside `zCompost/` into `state/isolation_baseline.json`. Capture that baseline while the vault is still pristine — it is worthless taken afterward.

After any run: re-walk and assert the set is **identical**. No changed hashes, no new paths, no missing paths. Fail loudly and non-zero on any difference. Wire it as a test that performs a full `pull` against the fixture source and asserts the baseline holds, so it cannot be forgotten.

The isolation rule is exactly the kind of constraint that erodes through a well-intentioned "it's just one status file at the root." It must be enforced by something other than discipline. The **only** sanctioned exception is Phase 6 backfill, which re-baselines afterward, and which is hand-invoked, snapshotted, and diff-reviewed precisely because it is the exception.

**Standing safety check:** confirm Obsidian Sync's version history is actually retaining versions before the first bulk import, since it is the primary rollback mechanism.

---

## 13. Scheduler and failure surfacing

A user launchd agent: `StartInterval` 900, `ThrottleInterval` 300, `RunAtLoad`, `ProcessType Background`, `LowPriorityIO`, logs to `~/Library/Logs/composter/`. Loaded with `launchctl bootstrap gui/$(id -u) <plist>`.

Three specifics that matter:

- **Which interpreter.** TCC identity is inherited from the binary named in `ProgramArguments`. Use the **python.org framework build** (`/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`), *not* Homebrew's — `/opt/homebrew/bin/python3.13` symlinks into a version-stamped Cellar path that changes on every patch bump, **silently invalidating the Full Disk Access grant every few weeks**. (A venv's `bin/python3` resolves to the base interpreter anyway, so pointing at a venv grants FDA to the base interpreter regardless.) The clean long-term fix is a tiny app bundle whose executable spawns Python, so TCC attributes to the bundle and interpreter upgrades stop breaking the grant. Stage it: broad grant now, bundle later. `doctor` detects the breakage either way.
- **Not `WatchPaths`, at least at first.** Tempting for the recordings directory, but whether launchd's watcher fires reliably on a TCC-protected group container is unverified. Ship on `StartInterval`; add `WatchPaths` as a latency optimization only after confirming it fires.
- **`flock` on `state/composter.lock`** at startup, exiting 0 immediately if held. `ThrottleInterval` is not a lock, and a long whisper run must never overlap the next tick.

**Failure surfacing — passive first, unmissable on escalation, self-clearing.**

- **Tier 1: `zCompost/_status.md`**, rewritten after each run *only if its content actually changed* (so it does not generate needless file events or sync traffic). Shows last successful run, elapsed time since, per-source counts, 24h activity, and a "Waiting on you" section listing conflicts as wikilinks. This works because it exploits an existing behavior: Obsidian gets opened and `zCompost/` is right there. No new habit, no notification, and when nothing is wrong it is a boring file nobody reads — which is correct.
- **Tier 2: `zCompost/!! needs attention.md`** after 3 consecutive failures or 26 hours without success, **plus** a macOS notification. It contains the error, the last-good timestamp, and the exact command to run, and **it deletes itself on the next successful run**, so it can never become stale nagging. A file alone would be more visible at the vault root, but isolation is absolute, so the notification buys the visibility back — acceptable precisely because escalation should happen about twice a year.
- **Tier 3:** `state/logs/`, the `runs` table, and `status`. For debugging, not for noticing.

**The gap this scheme has** is the agent not running at all — no run means no status update means no alarm. Mitigate by having Tier 1 always print elapsed-time-since-last-success computed at read time, and by having `doctor` verify the agent is loaded. Building a watchdog for the watchdog is exactly the scope creep to avoid; a stale timestamp in a file that gets looked at weekly is enough for a personal system.

---

## 14. Risks, ranked by cost

**0. Damaging the existing 136 notes.** The only unrecoverable risk in the project. Everything else costs time; this costs writing. → The four independent isolation mechanisms, the standing baseline test, no delete path anywhere in the codebase, and backfill quarantined behind a snapshot. Treat any proposal that writes outside `zCompost/` during the buildout as a bug, however convenient.

**1. Apple Notes IDs are less stable than the design assumes.** `note.id` is a Core Data URI whose store UUID is local to this machine's Notes database. Rebuilding the store, removing and re-adding the iCloud account, or migrating to a new Mac can re-issue every ID at once. The whole ledger orphans and the next run re-imports the entire library as duplicates. → **(a)** `fingerprint` rematching in `reindex`, matching orphaned rows to unmatched upstream notes before creating anything new; **(b)** `writer.max_new_per_run: 50`, a circuit breaker that turns a mass-orphan event into an alarm instead of 900 duplicate files. **That one config key is the highest-value safety feature in the plan.**

**2. Shipping capture without stable IDs, real timestamps, provenance, or EXIF dates.** Unrecoverable data, plus every future citation broken. → Land the frontmatter contract before the first importer.

**3. Two diverging vaults.** If the Sync-connected vault is `~/Documents/Main`, the phone and the Mac have been editing different copies since roughly October 2025, and automating against the wrong fork compounds it. → Resolve in Phase 0. This risk exists independently of this project.

**4. A sync lag read as a deletion.** The marker scan infers deletion from absence, and an unsynced file is absent. `dismissed` is terminal, so this is silent permanent loss. → The 3-run / 1-hour grace period, and never dismissing on the first run after a long gap.

**5. Full Disk Access fragility under launchd.** Homebrew's versioned Cellar path silently invalidates the grant on patch bumps; voice and iOS then stop, quietly. → Framework interpreter now, app-bundle wrapper later, `doctor` as the detector, Tier 2 alarm as the backstop.

**6. The Voice Memos schema on macOS 26 is genuinely unknown.** → Three commands in Phase 0. Contained: only the identity function depends on it, and there is a hash fallback.

**7. Notes HTML fidelity, especially checklist state.** → Kitchen-sink fixture in Phase 0 and a snapshot test forever after, so a macOS update fails loudly rather than degrading silently.

**8. Clippings indistinguishable from the owner's own writing.** Corrupts the flagship "who was I" query with other people's essays. → `composter_authorship` in frontmatter, not a path heuristic.

**9. `base.en` transcript quality on reflective speech.** A product risk: transcripts bad enough that the conclusion is "the system doesn't work." → Upgrade to `large-v3-turbo` early; it is a config key.

**10. Notes.app side effects.** Every run launches it in the background, and a run landing mid-sentence imports a half-written note. → `quiet_seconds: 120`.

**11. The `resolve` chore violating Principle 7.** → If it fires more than monthly, flip `on_local_edit: graduate`.

**12. Scope creep — the meta-risk.** Every technically interesting thread here (protobuf parsing, digests, a timeline view, a real conflict-merge UI) is a way to spend a month building instead of composting. → The phase gates, the deliberate week-long pause after Phase 3, and treating "no LLM calls in the capture layer" as a hard line rather than a preference.

---

## 15. Critical files

- **`src/vault.py`** — the VaultWriter; the only code permitted to touch the vault, and where the fence, graduation, and conflict logic live.
- **`src/db.py`** — the ledger schema and state machine; the thing that must be right on day one.
- **`src/sources/apple_notes.py`** + **`src/jxa/dump_index.js`** — the highest-value, first-to-build source.
- **`config/composter.yaml`** — vault root, sentinel, and the `max_new_per_run` circuit breaker.
- **`tests/fixtures/notes_kitchen_sink.html`** — the HTML fidelity snapshot that turns a silent macOS regression into a failing test.
- **The launchd plist** — modeled on an existing working user agent on this machine.
