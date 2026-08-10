# Classification brief

You are judging notes from one person's Apple Notes library so a personal
archive tool knows what is worth keeping. The owner writes constantly: private
reflections, research thinking (AI/economics/labor), creative fragments,
drafted messages, and a great deal of pure logistics. Your job is to tell
these apart by **reading each note**, not by keyword matching.

## Input

A TSV file, one note per line: `index<TAB>title<TAB>body-snippet`.
The body may be empty — in that case **the title is the entire note**, and a
title like `noticing what's wrong never helps` is a real captured thought,
while a title like `New Note` or `asdf` is nothing.

## Output

Write JSONL to the output path, one object per input line, no other text:

```
{"n": 42, "category": "reflection", "verdict": "keep", "confidence": 0.8, "why": "six words on what he wants from work"}
```

- `n` — the index from column 1. Every input line gets exactly one output line.
- `why` — under 12 words, specific to THIS note, describing what it actually
  is. Never restate the category name. This is shown to the owner.
- `confidence` — 0.0–1.0, your actual certainty.

## Categories

**keep** by default:
- `reflection` — thinking about himself, his life, his patterns, other people,
  how to live. Includes hard emotional material and relationship processing.
- `idea` — research ideas, project seeds, creative concepts, arguments,
  observations about the world, aphorisms worth keeping.
- `writing` — lyrics, poems, wordplay, bits, deliberate prose fragments.

**ask** (genuinely ambiguous — the owner decides):
- `draft-msg` — a message drafted to a specific person. Some are pure logistics
  ("are we still on for tomorrow"), some are the most emotionally honest thing
  he wrote that month. Judge which by content and say so in `why`.
- `work-note` — substantive work/research notes: analysis plans, findings,
  meeting notes, questions for people. Real intellectual content, but tied to a
  task that may be long finished.
- `reference` — durable useful information he looked up and may want again:
  routines, recipes he wrote, book lists, people-and-context notes.

**trash** by default:
- `credential` — ONLY actual secrets: passwords, API keys, PINs, account
  numbers, recovery codes, license keys. **Be strict.** Punctuation like `!!!`
  or `?` does NOT make something a credential. If you are not confident it is a
  real secret, it is not this category. False positives here are worse than
  misses because they hide real writing.
- `stub` — genuinely empty, a single character, `New Note`, `asdf`, or an
  attachment-only note (`￼` with no text). A short but meaningful thought is
  NOT a stub.
- `errand` — groceries, packing lists, shopping, chores, gift lists, to-buy.
- `logistics` — appointments, confirmations, addresses, housing search,
  bills/amounts owed, schedules, one-off scratch calculations.
- `roster` — bare lists of names or phone numbers with no context.

## Judgement notes

- **Length is not value.** A four-word line can be the best note in the file.
- **Lists are not automatically trash.** A grocery list is trash; a list of
  research questions or a list of what he wants from his life is not.
- **Work notes are not automatically trash** — many contain real thinking.
- **Personal/sexual/relationship material is not trash.** It is exactly the
  reflective material the archive exists for. Judge it on substance like
  anything else, and write a neutral, non-judgmental `why`.
- When torn between a keep category and an ask category, choose the ask
  category. When torn between ask and trash, choose ask. Only assign trash
  when you are confident nothing of value is lost.
