# Backlog

Ideas worth returning to, parked deliberately. Nothing here blocks the build
order in [IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md); this is the place
things go so they can be dropped from working memory without being lost.

Each entry says what it is, why it is parked, and what would unblock it.

---

## Multimodal image triage, and Apple Photos sorting

**The idea.** Run the same keep/toss review over images that the note triage
does over text: a fast scroll-and-bulk pass that produces a body of **labeled
examples of what is worth keeping and what is not**. Then use those labels,
plus written instructions distilled from them, to run a multimodal classifier
across the Apple Photos library — excluding or sorting rather than deleting.

**Why it is interesting.** The labels are the valuable artifact, not the
session. Doing the exercise once yields training/prompting material reusable
against a corpus far larger than anything reviewable by hand — and a photo
library is exactly that corpus: tens of thousands of items, mostly screenshots,
receipts, and duplicates, with real material buried in it. The text triage
already proved the shape of the problem: *classifying by form is reliable,
classifying by value is not*, so the labels have to come from a human and the
model's job is to generalize them, never to invent the criteria.

**What it needs first.**
- Photos access, which is a separate TCC grant from Full Disk Access.
- A decision about where photo review fits: the plan's Phase 5 imports photos
  via the iOS Shortcut and captures EXIF dates. Library-wide sorting is a much
  larger scope and belongs after that, not folded into it.
- The capture layer's hard line still applies: **no LLM calls in capture**
  (plan §11). This is a retrieval/interpretation-side tool, invoked by hand.

**Carry over from the text version.** Scroll-and-bulk beats card-by-card;
bulk must never overwrite an individual decision; separate *fact* sections from
*judgement* sections and label which is which; show why each item was grouped;
and never delete — exclude.

---

## A second pass over the notes, for insight rather than filtering

**The idea.** Run the corpus through a full read again, but with a completely
different question. The triage pass asked *should this be kept?* — a filtering
question whose output is a verdict per note. This one asks *what is actually in
here?*: recurring preoccupations, how thinking on a subject changed over years,
what gets returned to and never resolved, which ideas were had early and
forgotten, what the writing says about the person writing it.

**Explicitly not for composting.** No exclusion list, no keep/toss, no effect on
what imports. This is its own exercise with its own output — writing, not
configuration — and should not be folded into the capture layer or made to serve
it. Keeping it separate is the point: filtering and understanding pull in
opposite directions, and the triage pass showed how easily a good corpus gets
flattened into a verdict column.

**Why it is worth doing separately.** The classification pass read all 1,439
notes and threw away everything except a category per note. That reading is
where the value was. A pass aimed at insight would keep the observations and
discard the labels — the exact inverse.

**Relationship to the plan.** This is the interpretation layer (plan §10.1)
arriving early and by hand, which the plan actually recommends: *"generate one
digest by hand and read it before building any scheduler around this — it is
the part most likely to produce beautiful-sounding nothing, and one attempt
settles it."* Doing it once, manually, on real material is the cheapest possible
test of whether the whole digest concept is worth building.

**What it needs first.** Nothing technical — the corpus dump already exists at
`state/triage_candidates.jsonl`. What it needs is a decision about what question
to ask, since the question determines everything about whether the output is
insight or horoscope.

---

## Retrieval modes: the same note is signal in one context and noise in another

**The observation** (Adam, after the first triage sweep): some notes are old
*memories* rather than live ideas. They are worth surfacing when deliberately
sitting down to make sense of the past — and not worth surfacing during a normal
creative session, where old ideas genuinely are useful but old memories are
clutter.

**Why this matters more than it looks.** It breaks the keep/toss frame
completely. These notes are not junk and must not be excluded; they are
*context-dependent*. Any capture-time decision — exclude, tag, separate folder —
is the wrong shape, because the same note needs to be present in one query and
absent in another. This is the plan's §1 claim arriving as lived experience:
*"the same material asked different questions — so they are never split into
separate systems."*

**The likely answer, mostly free.** Two retrieval modes over one pool:

- *creative* — no date restriction, favours ideas and fragments, everything in play.
- *memory* — date-scoped, favours reflection and personal material, and is the
  only mode where old memories rank highly.

Most of what separates them is **already in the frontmatter contract**:
`created` makes the temporal scoping possible, and `composter_authorship`
keeps other people's writing out of "who was I" queries. Mode is a query-time
filter, not a property of the note. Nothing needs to be tagged, and nothing
needs deciding at capture time — which is the whole reason the frontmatter
contract was front-loaded.

**The open question.** Whether `kind` (currently a *format* axis:
note/transcript/clipping) also needs a *content* axis to separate "an idea" from
"a memory", or whether date plus embedding similarity already does it. Do not
answer this by adding a field. Answer it in Phase 7 by running both queries
against the real corpus and seeing whether the results are actually wrong —
Principle 8 exists because declared taxonomies rot, and this is exactly the
kind of field that would rot.

---

## Proper onboarding to the process

**The idea.** Right now the system works but there is no path into it for a
person who is not already holding the whole design in their head. Someone
picking this up — including the owner in six months — has to read a 570-line
plan, a status document, and a README to learn what to type first. Build a real
onboarding: what to run, in what order, what each step will do to your vault,
and what "working" looks like when it is working.

**Why it matters more here than for most tools.** The system writes into a
personal archive. The cost of a confused first run is not a stack trace, it is
uncertainty about whether your own writing is safe. Onboarding is therefore part
of the safety story, not documentation polish: the person needs to *understand*
the isolation guarantee, not just be told it exists.

**What it should cover, in rough order.**
- The one-time setup, with the destructive-looking steps explained before they
  run: `doctor` → `init` → `isolation --capture` → a `--dry-run` pull.
- What actually lands in the vault, shown rather than described — a real note
  with its frontmatter, and where it goes.
- The three things the owner does and the system does not: graduate (drag out),
  dismiss (delete), resolve (a conflict). These are the whole interaction model
  and they are currently buried in §7.3 of the plan.
- What failure looks like: the status file when it is boring, and the alarm when
  it is not.
- The escape hatches: every file is plain markdown, the index is disposable,
  nothing is ever deleted.

**Open question worth deciding first.** Whether the audience is *only* the owner
returning later, or genuinely other people. The second is a much larger job — it
implies removing every hard-coded assumption about this machine, this vault, and
this Notes library — and would be a different project than the one the plan
describes. Principle 12 ("build the selfish version") argues for the first.

---

## Deferred from the current build

These came up while building Phases 1–2 and were parked with a reason.

| Item | Why parked | Unblocked by |
|---|---|---|
| **Note triage** (finish or abandon) | Whether junk hurts is a retrieval question, not a capture one — plan Principle 9. Unfiltered notes import fine. | Phase 7, once there is a real corpus to test retrieval against |
| **Attachment import** | Phase 2 is text-only; 19 notes are media with no text, and inline photos arrive as base64. Currently surfaced as a callout so nothing is silently lost. | A media phase; needs the `max_inline_mb` rule and `~/Media/composter/` |
| **`large-v3-turbo` whisper model** | `base.en` ships because it is already on disk, but the plan flags it as a product risk on reflective speech. One config key. | Phase 4, download ~550 MB |
| **App-bundle wrapper for TCC** | Framework interpreter works now; a bundle stops interpreter upgrades from invalidating Full Disk Access. | Phase 3+, when launchd is proven |
| **Checklist checked-state** | Measured as genuinely lost in Notes' own API — items arrive as plain `<ul>`. Accepted per plan §8.1, do not chase the sqlite route. | Nothing; revisit only if Apple changes the API |
| **Second Obsidian vault** (`~/Documents/Main`) | Confirmed stale, months since edited, not sync-bound. Not composter's problem. | Owner deciding whether to merge or delete it |
