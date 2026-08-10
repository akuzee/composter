# The Composting System — Design Notes & Direction

*A working document capturing a conversation about building a personal capture-and-creativity system. This is not a build spec. It is a record of the reasoning, the constraints discovered, the decisions provisionally made, and the questions deliberately left open. The intent is that a more capable model (or a later version of me, with more time) can pick this up and do the actual technical planning against it.*

---

## 0. How to read this document

The conversation that produced this doc was exploratory. It started as "how do I keep more creative fronts alive with less friction" and ended somewhere much more specific: a single-pool personal archive, Obsidian as the spine, embeddings rather than tags, and a ranked three-layer architecture where only the first layer actually needs to work.

The path mattered as much as the destination, because several of the important decisions were *eliminations* — things that sounded reasonable and got ruled out for reasons that will not be obvious from the final architecture alone. Those eliminations are preserved here on purpose. If a future planner re-proposes them, that's a signal the reasoning was lost.

Sections 1–3 are the *why*. Sections 4–7 are the *what*. Sections 8–10 are the open questions and the parking lot.

---

## 1. The original problem, and the two false diagnoses

### 1.1 Presenting complaint

Many creative interests running in parallel — writing, photography, video, music. The desire is not to schedule creative time. It is to **catch and capitalize on things that actually show up**: an idea, an urge, a shot, a phrase. The stated requirement was minimal friction, and an explicit rejection of the "block out time, make a plan, execute the plan" model.

The framing that stuck early: **not a system, a net.**

### 1.2 First diagnosis, partially right: capture friction

The initial answer to "what kills an idea when it shows up" was *the tool isn't handy*. This is real but turned out to be the smaller half of the problem. It's a genuine bottleneck — it becomes Layer 1 below — but it is not the thing that was actually causing the ideas to die.

### 1.3 Second diagnosis, wrong: starting friction

The other half of the initial answer was "I don't want to put up the upfront investment." Probing this revealed the friction is **not at the start**. Jotting the loose idea is easy and happens already. The friction is at the *other* end.

### 1.4 Actual diagnosis: half-formed things are demoralizing

The real finding, in his words: starting a bad version of something isn't satisfying. A note containing a loosely-jotted idea is not an asset sitting in a pile. It is a **debt**. A folder of them is a folder of obligations, and accumulating obligations is the thing that makes the whole enterprise feel bad.

This is the load-bearing psychological insight in the entire document. Two consequences follow:

**Consequence A — the unit of work should be the smallest complete thing.** Not a song, one finished eight-second loop. Not an essay, one paragraph that stands alone. The satisfaction comes from *closing a loop*, at any scale. He confirmed this lands, and specifically endorsed the "a bunch of MVPs I like and that are good enough" framing.

**Consequence B — the pile is only demoralizing if the pile is the destination.** If the pile is explicitly a *staging area*, and there's a mechanism by which good things graduate out of it, the pile stops being a pile of debts and becomes a compost heap. Which brings us to the metaphor.

### 1.5 The organizing metaphor: composting

He arrived at this himself, and it does real work — it is not decoration:

> Tracking my inner life for the purpose of composting it, sitting with it, making connections over time. Capturing all the good scraps and putting them in one place for later use.

Why it matters operationally: **compost does not require completeness.** It requires *good scraps*. This single reframe dissolved a problem he'd been stuck on (see §6.3 on photos), because he had been implicitly treating total coverage as the goal. Composting says curation is not a compromise — it's correct. You don't want the noise in there.

Design test to apply to any future decision: *does this feature help good scraps break down and recombine, or is it just making the heap bigger?*

---

## 2. The single most important structural decision: one pool, not two

This was reached, then reversed, then re-reversed — the reversal is important.

**First pass (wrong):** Split into a *reflection stream* (writing, personal video, for-me, about watching your own thinking accumulate) and a *creative-output stream* (photos, music, for-others). Different purposes, different homes. This seemed clean, and the reflection stream was clearly where the energy was.

**The correction, in his words:** the reflections *inform* the things he wants to write about or capture in another form. A thought or feeling on a given evening might become an essay, might become a song, and is also simply something to look back on to remember the headspace he was in. His exact point: *the way you were at the time and the things you were thinking are not really separable.*

**Therefore:** one pool. Splitting them would amputate the source material from the output. The cross-pollination *is* the value.

He also connected this to a separate long-standing idea of his: an app for **looking back at a period of your life** and seeing the reflections alongside the photos, the little moments, the multimodal impression of that day or month — like the Journal app's ability to attach places and photos. He noted, correctly, that this idea is not distinct from the creative one. Same inputs, same store, same retrieval machinery. You just ask it different questions.

**The formulation to preserve:** it is not a creativity tool and it is not a journal. It is **one timeline of an inner life**, which serves double duty. Sometimes you query it to remember who you were. Sometimes you query it for raw material. Same pool, different questions.

**Corollary:** classification along a personal/creative axis is not a top-level structural distinction. The line is genuinely blurry and any schema that hard-codes it will be wrong. (This foreshadows §5 on tags.)

---

## 3. Build for self first — and the one hedge

He raised, unprompted, that other creative types would probably benefit from this, and asked how much to make it custom vs. shareable.

**The tension named:** the thing that makes it good for him is that it is *ruthlessly his*. Building for others means owing people polish, onboarding, and flexibility for workflows that aren't his — at which point it's a startup, not a net for his ideas. There's also a specific failure mode worth stating plainly: **building the tool becomes the creative project that eats all the other creative projects.** Given that the whole premise is "I have too many fronts and not enough closure," this is not a hypothetical risk.

**Decision:** build the selfish version. If it changes how he actually creates over a couple of months, that's the proof it's worth generalizing. If it doesn't stick, he's saved himself from shipping a system nobody uses, including him.

**His refinement, which is the mature version of this:** avoid decisions that would be *unscalable* or force a backtrack later. Accept a little more friction now if it avoids a rebuild. But: "mainly focus on what I need." A soft factor, not a design constraint.

**The hedge that satisfies this almost for free:** **plain files.** Everything lives as portable files on disk — markdown, audio, images — rather than locked in a custom database. This buys most of the future-proofing at essentially zero cost, keeps the door open to generalizing later, and independently satisfies his stated desire to be able to export and reuse content in other settings.

**Rule of thumb agreed:** optimize every decision for himself; when two options are roughly equal effort, take the one that keeps data portable and open.

---

## 4. Architecture: three layers, ranked by priority

He laid these out and ranked them himself. The ranking is as important as the layers.

### Layer 1 — Capture (non-negotiable)

Getting material in with as close to zero friction as possible. **If this has friction, the whole thing dies.** Everything else is decoration. This is the only layer that must work on day one.

### Layer 2 — Retrieval & indexing (the real intelligence)

Being able to find things — by theme, by mood, by period, by "pitch" — and to see what he's been producing over time. Also the connective tissue: surfacing that two things relate. Important but deferrable, *provided* Layer 1 stores things in a way that doesn't foreclose it.

### Layer 3 — Output & sharing (explicitly deprioritized)

Getting finished things out: a section of a personal WordPress site, SoundCloud for music, Instagram, a tweet. His own reasoning for deprioritizing: **when you want to share something, you usually want to share it intentionally.** So automating it has low value, and the manual version is fine. Nice-to-have, do later.

There was an earlier articulation of Layer 3 worth keeping: a **two-layer public/private split**, where the vault is the private staging area holding everything regardless of quality, and a curated public layer receives only what graduates. The medium tends to determine the public home (music → SoundCloud, writing/photos → personal site), and *not everything graduates* — some is personal, some is still bad. The "graduation" move is the mechanism from §1.4 that makes the staging pile psychologically safe.

**A note on the aggregation dashboard idea:** at one point he described a custom app that ingests multiple streams, gives a timeline view of what he's been making, and lets him flag things to graduate. This is a coherent product idea and is essentially Layers 1+2+3 fused into one interface. It was set aside not because it's wrong but because (a) building it is the project-eats-projects risk, and (b) the behavior should be proven with existing tools before anything is built. **The timeline view remains a desirable eventual feature and the plain-files decision keeps it buildable later.**

---

## 5. Organization: why tags lose, and embeddings win

This section covers the longest and least-resolved stretch of the conversation. He was explicit that this is something he'll have to **experiment with** rather than settle up front. But the direction is clear and the reasoning should be preserved because it constrains the storage format.

### 5.1 The stated problem with tags

His own account of the failure mode: he'll use a tag for a while, stop using it, and then no connection gets made. Keeping track of which tags exist and what they were for becomes its own burden, and the result isn't useful. **Any hand-maintained taxonomy rots.**

Deeper than that: the *associations themselves are fluid*. The feeling he attaches to a topic at one point will shift; he may stop associating things that way and abandon the term entirely. So it's not just that he's lazy about tagging — the schema has a genuinely moving target underneath it.

### 5.2 The intermediate idea, and why it doesn't fully work

Zettelkasten-flavored: capture raw, then add metadata later through a lightweight UI — *this is just a thought / this is a take / this is the start of an essay / this is a reflection*. The appeal is real: those labels genuinely make things easier to refine and recombine.

But it's caught in a vise. Labeling **at capture time** adds friction at exactly the moment he can least afford it (Layer 1 must be frictionless). Labeling **later** requires him to come back — and he said himself he might not touch the system for months, and that he abandons routines he sets up. Neither end of the tradeoff is safe.

*(One proposal made in conversation: capture with zero required metadata, and have the LLM propose labels at retrieval time, which you confirm or adjust while already browsing. He was lukewarm on this. Recording it as a live option rather than a decision — it does have the property of making labels regenerable under whatever lens he brings later.)*

### 5.3 What he actually converged on

His own framing: each item is essentially **a point in semantic space**, with associations that accrue over time — and he does **not** want to manage that consciously. Hence: **embeddings**, plus LLMs for the interpretive layer.

Why this dissolves the problem rather than mitigating it:

- Meaning is inferred from content. He never names a theme, never keeps a tag alive.
- Associations shift as the corpus grows, without any retroactive work.
- A connection between two notes isn't something he *drew*; it's something that's *findable*.
- The web of connections doesn't need to be stored. It's **computed at query time.**

He also raised the mental model of the data as a **web or tree** where every item has a position in time, in medium, and in purpose, plus connections to other things. Embeddings are compatible with that view; hand-tagging is what fails at it.

### 5.4 The cost question he raised

He flagged that doing intelligence at retrieval time could be wasteful, and wondered about storing the indexing as you go — passively connecting things — but worried about expense if it tried to connect everything to everything.

The resolution that fits both concerns: **embed on capture (cheap, and it's a per-item cost), reason on retrieval (expensive, but only when you actually ask).** Don't pre-compute a giant all-pairs semantic web upfront; most of it would never be looked at.

### 5.5 What this means for Layer 1

Only one requirement propagates down: **store raw material as plain files with vectors attached (or attachable).** Any retrieval scheme becomes buildable later without redoing anything. His own conclusion, which is right: *if we can capture, the indexing and searching will be fine, because we can build on it.*

**Open question flagged by him:** he wants to do more research on the embedding/semantic-association side. Worth treating as a genuine research task, not a solved problem — particularly the question of how to let the *interpretive* layer accumulate over time rather than being recomputed from scratch each time.

---

## 6. Storage: Obsidian as the spine

### 6.1 The decision

Obsidian, as the default, unless something disqualifies it. Reasons:

- It's **plain markdown files in a folder**. No app-imposed storage ceiling — it's however big the drive is. Maximally portable, nothing locked in. Directly satisfies §3's hedge.
- It's **mature and already has a ton of features**, including a lot of flexibility to grow multimodal over time. Don't rebuild what exists.
- Media can live as attachments in the same folder structure.
- Files are easy to export and reuse elsewhere.

### 6.2 The one real caveat: sync weight, not storage

The constraint is **not** total storage — it's **syncing across devices**.

- **Text is featherweight.** Thousands of notes is nothing.
- **Photos are fine.** A phone photo is a few megabytes; thousands still fits comfortably.
- **Voice memos are very light.** An hour of audio is smaller than one short video, and it transcribes into searchable text — the best ratio of reflective value to bytes in the whole system. *If he wants to shift more reflection toward voice, that's cheap and good.*
- **Video is the only real weight.** A few minutes of phone video can be hundreds of megabytes. Sitting on the Mac, a folder of videos is a non-issue. The pain appears only if it's constantly pushed to the phone and back.

**⚠️ Verify:** the exact limits and pricing of Obsidian Sync (per-file size caps, total quota, plan tiers) were not confirmed in conversation. Also worth checking third-party sync alternatives (iCloud Drive-based, Syncthing, git-based) since the choice of sync mechanism is what actually determines whether media can live in-vault.

### 6.3 The resolution for heavy media

He pushed back usefully here — his best reflection material is often video, and he didn't want it exiled. Also relevant: he does **not** keep photos in iCloud Drive (too much data, too expensive), though *everything else*, including voice memos, is in iCloud Drive. This asymmetry drives several capture decisions in §7.

The pattern agreed:

> **Transcript in the vault; heavy file referenced.**

The video (or large media) file lives outside the vault — iCloud or a local media directory — and the vault holds the **transcript plus a link/embed**. He gets the words in the searchable, embeddable index, and the footage is a tap away, without dragging gigabytes through sync.

Reframe he accepted: **the vault is the index of your life.** Text and light media native; heavy media referenced. This preserves the "all in one place" feeling because the *index* is unified even when the bytes aren't.

Suggested split, endorsed: lean harder on **voice for idea capture** (cheap, transcribes well), reserve **video for moments that genuinely need the visual**.

### 6.4 Explicitly ruled out

**Do not build a monthly photo-review UI.** The idea was raised — a nice interface where once a month you sort through everything and pick what to add — and rejected, by his own logic: a periodic sort-through-everything ritual is exactly the kind of chore he abandons. He said as much ("that's annoying") even while proposing it. **Intentional in-the-moment capture beats any batch review**, on both friction and signal quality. Compost wants good scraps, not a monthly audit.

---

## 7. The capture layer, source by source

This is the part with the most concrete detail. Sources are the **Mac** (notes, direct vault editing, local files, occasional music) and the **phone** (notes, voice memos, photos, video, text snippets).

### 7.1 Apple Notes → Obsidian *(highest priority; also the hardest)*

**Why it's hard.** Apple Notes does not store content as files. It lives in a database, and the content is Apple's own rich-text format, not markdown. Unlike voice memos or photos, you cannot just point a folder at it. Something must actively pull notes out and convert them.

**Two routes considered:**

1. **Existing importer tool, re-run periodically.** Tools exist that pull a whole Notes library into a vault as markdown. Downside: it's a batch pull, and re-running creates duplicate-handling problems.
2. **A script on the Mac** that talks to Notes, grabs what's new, converts to markdown, writes into the vault — on a schedule. More upfront effort, but self-running.

**Decision: build the script.** He chose this explicitly, on the grounds that the duplicate problem would be annoying and this is a day-ish of work. It's also the only option consistent with the frictionless mandate.

**The one design decision that makes or breaks it:**

> **Map each note to its vault file by Apple Notes' internal per-note ID — never by title or content hash.**

Editing a note then updates the *same* file rather than creating a second copy. Match on identity, overwrite in place. This single choice eliminates the duplicate problem outright. Getting it wrong on day one poisons the archive in a way that's tedious to unwind later.

**Rough shape:** AppleScript (or a Swift call) to enumerate and pull notes → rich-text-to-markdown conversion → write/update vault files keyed by ID → scheduler on the Mac (launchd, or similar) to run it quietly on a timer, plus a small local record of what's been processed.

**⚠️ Sequencing warning:** attachments and images *inside* notes are the fiddly part. Text extracts cleanly; embedded media needs extra handling. **Get pure text flowing end to end first and prove the loop.** Add media handling second.

**⚠️ Verify:** the current AppleScript surface for Notes (what's exposed, what isn't), and the fidelity of rich-text→markdown conversion for lists, tables, checklists, and inline formatting.

### 7.2 Voice Memos → Obsidian

More pleasant than Notes, because the files aren't locked away. Voice Memos keeps real audio files, and since he's on iCloud Drive, they sync to the Mac where a script can reach them.

**The four beats:**

1. **Watch the folder.** Point at the synced Voice Memos location; find recordings not yet seen. Same identity discipline as Notes — keep a record of what's been processed so it never doubles up.
2. **Handle the audio.** Copy/move the recording to its home (in-vault or referenced media location per §6.3), and pull metadata — date, memo name — so the note can be titled and timestamped sensibly.
3. **Transcribe.** Feed the audio to a transcription step.
4. **Write the note.** Create a markdown file: transcript as body, link or embed to the audio, date at top. Mark the memo as done.

Same scheduler as the Notes script runs this on a timer. Both just happen in the background.

**Transcription choice:** local Whisper on the Mac (free, private, very good) vs. an API (marginally better accuracy, small per-minute cost). **Recommendation: local.** These are personal reflections — keeps it private, and there's no per-minute bill for talking to yourself.

**Desired outcome, stated explicitly by him:** *both the audio and a nice transcript in Obsidian, together.* The transcript is what makes a voice memo first-class material — searchable, embeddable, not a file you have to remember to listen to.

**⚠️ Verify (flagged in conversation, he asked that it be noted):** Apple has changed where Voice Memos stores files across recent macOS versions, and on some setups they're buried in a group container path. **Step one occasionally takes digging to point at the right folder.** Everything after that is smooth. Confirm the current path on his actual machine and OS version before writing the watcher.

### 7.3 Photos → Obsidian *(deliberately manual)*

**Why it can't be automated the way the others can:** he doesn't use iCloud Photos / iCloud Drive for photos (volume, cost), so the Mac can't reach into a synced folder. The photos live on the phone.

**Also, per §1.5, manual is correct here anyway.** The camera roll is mostly noise — screenshots, incidental junk. Composting wants the good scraps. Deliberate selection is a feature, not a compromise.

**The path:** capture happens **on the phone, at the moment of intent**, via the iOS **share sheet**. See the shot that matters → Share → an **iOS Shortcut** that drops it where the vault can get it.

Two destination options:
- Shortcut writes **directly into the Obsidian vault folder** on the phone, if the vault syncs to the phone.
- Shortcut writes into a **small holding folder** that syncs, and the Mac script sweeps it into the vault later. *(Preferable if he doesn't want the whole vault on the phone.)*

Two taps, in the moment, no batch chore. He accepted this: fully automatic would be cooler, but this is "a good compromise" and fine for now.

### 7.4 Web content → Obsidian

Splits into an easy half and a hard half, and the line between them is worth respecting.

**Easy (take the free win): the Obsidian Web Clipper.** On a page, one click, article comes into the vault as markdown **with the source link attached automatically**. It also handles a highlighted selection plus the URL. This is the same low-friction spirit as everything else and requires no building. He already does this occasionally and should simply lean on it more — the overhead he was worried about is mostly imagined here.

**Hard: closed apps.** Twitter, etc., aren't webpages. No clean URL, no selectable DOM. Best available is the share sheet handing over a link or a screenshot, and a screenshot loses the text as searchable words unless run through OCR later. Doable, but a rabbit hole.

**Line drawn:** browser-based → clipper. App-based → share a link or screenshot into the holding folder, don't over-engineer.

### 7.5 Arbitrary selected text → Obsidian

Anywhere the copy/share menu appears — a tweet, an iMessage from a friend, anything selectable — there's a clean path.

**Mechanism:** an **iOS Shortcut that accepts shared text** and appends it to a note in the vault, with a timestamp. Select → Share → Shortcut. Two taps, no typing. Works in iMessage the same as anywhere else.

**The honest limitation:** when you share *plain selected text*, iOS gives the shortcut the words but typically **not the source**. So it's a trade — highlight the exact passage and lose the source, or share the whole item and keep the source but grab more than you wanted.

**His resolution, which closes this cleanly:** for anything on the web, the clipper gets the source for free anyway. For everything else, **capturing the text without the source is fine.** No further engineering needed.

### 7.6 Mac-native

Direct editing in the vault; local files (music, etc.) are easy to drop in since they're already on disk. Low-friction by default, nothing to build.

---

## 8. Capture layer roll call

| Source | Mechanism | Mode | Priority |
|---|---|---|---|
| Apple Notes | Mac script, AppleScript/Swift pull → markdown, **ID-keyed dedupe**, scheduled | Automatic | **First** |
| Voice Memos | Mac script, folder watch → local Whisper → audio + transcript pair, scheduled | Automatic | **Second** |
| Photos | iOS Shortcut via share sheet → vault or holding folder | Deliberate | Third |
| Selected text (apps, iMessage) | iOS Shortcut accepting shared text, timestamped, source optional | Deliberate | Third |
| Web pages / articles | Obsidian Web Clipper (source captured automatically) | Deliberate, zero-build | Free win |
| Mac-local files | Direct into vault | Manual | Free |
| Reaction videos | *Parked — see §9* | — | Later |

Every inflow he named has a path. **Capture and storage are the two layers now closed.**

---

## 9. Parking lot

Things consciously deferred, with reasons — not forgotten, and none of them blocked by decisions made above.

- **Reaction videos.** He frequently records himself reacting to and talking about videos he's taken. These live in their own folder structure. He's fine keeping them separate for now, and expects an easy add later: a script that pulls transcripts from these local video files into the vault. **It's the same pattern as voice memos** — local file plus transcript in, heavy file referenced — so nothing in the current design blocks it.
- **The timeline / dashboard view.** Seeing what he's produced over time, across media, in one interface. Genuinely wanted. Plain files keep it buildable whenever.
- **The "look back at a period of your life" view.** Reflections + photos + moments assembled into a multimodal impression of a day or a season. Same store, different query.
- **Layer 3 output automation.** Staging things for the personal WordPress site, SoundCloud, Instagram, tweets. Low value per §4 because sharing is intentional anyway.
- **Public/private graduation flow.** The mechanism by which staging-area material becomes published work. Conceptually important (§1.4, §4) even if the implementation is trivial.
- **The Apple-level total-life-history version.** Locations visited, contacts met, searches made, app usage — the full passive record of a life. He named this himself as *only Apple could do it* and **explicitly out of scope**. Named, parked, walked away from. Recorded here so it doesn't get re-litigated.
- **Fully automatic photo ingestion.** Would be cool; blocked by not using iCloud Photos; manual is an accepted compromise.
- **Generalizing for other people.** §3. Only after the selfish version demonstrably sticks.

---

## 10. Open questions for the deeper planning pass

Roughly in order of how much they'd change the build:

1. **Sync mechanism.** What actually syncs the vault between Mac and phone, and what does that imply for media weight? This determines whether §6.3's reference-vs-embed line sits where we drew it. *Verify Obsidian Sync limits/pricing; evaluate iCloud Drive, Syncthing, git.*
2. **Voice Memos file location** on his current macOS version. Flagged as a known gotcha (§7.2).
3. **Notes rich-text → markdown fidelity.** How much structure survives? What breaks? Is there a good existing converter to lean on rather than writing one?
4. **Embedding pipeline.** What generates vectors, where do they live (sidecar files? local vector store?), and how does that stay portable given the plain-files commitment? This is the piece he wants to research properly.
5. **How the interpretive layer accumulates.** He explicitly wants associations to *build over time* rather than being recomputed cold. Is that a stored artifact, a periodic re-embedding, an LLM-maintained summary layer? Genuinely unresolved and the most intellectually interesting question in the project.
6. **Scheduler mechanics.** launchd vs. cron vs. something friendlier; how to fail loudly enough that a broken script gets noticed but quietly enough that it isn't nagging.
7. **Metadata, empirically.** He's said this needs experimentation rather than up-front design. Worth deliberately trying: zero metadata + retrieval-time LLM labels vs. a very small fixed set of high-level types. **Keep any scheme high-level and few** — his own diagnosis is that fine-grained tags rot.
8. **Holding folder vs. direct vault writes** from iOS. Affects whether the whole vault needs to be on the phone.

---

## 11. Principles to carry forward

Compressed, for anyone picking this up:

1. **A net, not a system.** It catches what shows up; it doesn't schedule creativity.
2. **Composting, not archiving.** Good scraps, not completeness. Curation is correct.
3. **One pool.** Reflection and creative material are the same material. Never split them.
4. **The unit is the smallest complete thing.** Closed loops at any scale beat started-and-abandoned at any scale.
5. **The pile is a staging area, never a destination.** Graduation is what makes the pile safe to have.
6. **Capture is non-negotiable; everything else is deferrable.** If capture has friction, nothing else matters.
7. **No batch chores.** Any monthly-review ritual will be abandoned. In-the-moment intent beats retrospective sorting on both friction and signal.
8. **Never maintain a taxonomy by hand.** Meaning is inferred, not declared. Embeddings over tags.
9. **Embed on capture; reason on retrieval.** Don't pre-compute a web nobody will look at.
10. **Plain files, always.** The cheapest possible hedge against every future decision.
11. **The vault is the index, not necessarily the container.** Text native, heavy media referenced.
12. **Build the selfish version.** Generalize only if it earns its keep. Don't let building the tool become the creative project that eats the others.

12. Addendum — the read-later queue (inbound consumption)
Added after the main conversation. A related problem raised separately, and the reasoning about whether it belongs in this project.
12.1 The problem
He constantly runs into interesting things online — articles, threads, papers — that he may or may not want to read later. Capture is already solved: the Obsidian Web Clipper handles general web content, and papers go into Zotero.
The failure is entirely downstream of capture. Once saved, the material is effectively lost:
	•	He can’t see what’s in the queue in a way that lets him choose based on what he’s interested in or thinking about at that moment.
	•	He has no sense of the “vibe” of what’s queued — so he can’t pick the thing that matches his current headspace.
	•	Putting links in a note only works if he later remembers that note exists, or independently thinks of the thing he wanted to read. It doesn’t survive across multiple sources and multiple topics.
	•	No way to prioritize — no notion of “this is top of the queue, must-read” vs. “someday, maybe.”
The stated cost: he does far too much idle browsing, reading things he would not have recommended to himself, while a backlog of things he did deliberately choose sits invisible.
His examples: a burst of research on maximizing agent concentration produced more links than he could read at once, some worth returning to, with nowhere useful for them to go. Same shape for a cooking-and-Indian-food browsing session. What he wants is a viewing list he can actually consult, filtered by present interest.
12.2 Does it belong in this project?
Yes — same machine, different mode. But the distinction is load-bearing.
Why it’s not simply the same pool. Everything in §1–§11 is material he produced: notes, voice memos, reflections, footage. This is inbound material he hasn’t consumed yet. The lifecycles differ in a specific way:
His own scraps have no “consumed, now done” state. A read-later queue drains.
If unread links dump into the same undifferentiated pool, the consumption backlog pollutes the reflection archive — the compost heap fills with things that aren’t his and that he hasn’t metabolized yet.
Why it’s not a separate project either. The retrieval machinery is identical to §5. Embeddings over saved links, then exactly the menu he described: show me what’s in my queue that matches what I’m thinking about right now. Cooking mood → the cooking backlog. Agent-concentration mood → those links. Same query engine, pointed at a reading list instead of at memories.
12.3 Provisional shape
One system, two zones, one shared index. A consumed zone (produced material — the compost heap) and a to-consume zone (the inbound queue), both embedded into the same semantic space.
Implications and things to work out later:
	•	Zone is a first-class property, unlike the personal/creative distinction from §2 which was rejected as too blurry to hard-code. Read/unread is a clean, mechanical, non-fuzzy state — the kind of metadata that doesn’t rot (cf. §5.1).
	•	Draining matters. There should be a state transition when something is read, and ideally the possibility that a consumed item graduates into the produced pool — e.g. a read article that generated a thought becomes source material. This is the one place the two zones should be permeable.
	•	Prioritization is wanted but should be coarse — a must-read flag, not a ranked list. Fine-grained priority is the same rot risk as fine-grained tags.
	•	“Vibe” is a retrieval-time question, not a capture-time one. He shouldn’t label the mood of a link when saving it. The embedding plus an LLM pass should be able to surface what kind of thing each queued item is when he goes looking.
	•	Zotero is a second inbound source alongside the Web Clipper. Worth checking whether Zotero’s library can be indexed in place, or whether metadata needs exporting into the vault. Papers and casual links may deserve separate presentation even inside one queue.
12.4 Open questions
	1.	Does the queue live inside the vault as notes, or as an external index that merely points at Zotero and clipper output?
	2.	What marks something as read — manual, or inferred?
	3.	Is there value in surfacing proactively (a “here’s what’s queued that fits your current thinking” prompt) versus purely on-demand querying? Given §11’s no-batch-chores rule, anything resembling a scheduled review ritual should be treated with suspicion.
	4.	Does the queue need a decay or eviction mechanism? An infinitely growing unread list recreates the pile-of-debts problem from §1.4 — which is, notably, the exact failure this whole project was designed around.