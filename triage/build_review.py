"""Generate the local triage review page.

    .venv/bin/python triage/build_review.py && open state/triage_review.html

Every note lands in exactly one section. Sections come in two kinds, and the
distinction is the whole point:

  FACT     — matched on form: no text at all, digits outnumbering letters, a
             string in a real vendor key format. Checkable at a glance.
  JUDGEMENT— a model read the note and guessed. Useful for grouping, never
             authoritative. An earlier version of this tool treated guesses as
             facts and was unusable; see README.

Workflow the sections are built for: scroll a section, pick off the individual
notes you care about, then bulk the remainder. Bulk never overwrites a note you
decided yourself.

Local file, opened from disk. No note text leaves the machine.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from triage.obvious import OBJ, _body, detect  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "state" / "triage_candidates.jsonl"
VERDICT_DIR = ROOT / "state" / "verdicts"
OUT = ROOT / "state" / "triage_review.html"

FOLDERS = ["Notebook", "thoughts", "words", "lists", "misc", "exercises",
           "quotes", "big stuff", "do lists", "dreams", "prompts", "crumbs"]

# key: (label, lean, kind, blurb).  lean drives only the dot colour and the
# section order — nothing is ever pre-decided.
SECTIONS = [
    ("live-key", ("Live credentials", "trash", "fact",
     "Strings in real vendor key formats (sk-, AKIA, ghp_). Rotate these and delete "
     "the notes — they are plaintext in Apple Notes and sync to every device.")),
    ("empty", ("No text at all", "trash", "fact",
     "Placeholder titles, single characters, empty bodies. Nothing for a text archive to hold.")),
    ("numeric", ("Bare numbers", "trash", "fact",
     "Digits outnumber letters with no prose — scores, tallies, codes, amounts.")),
    ("credential", ("Passwords and account details", "trash", "judgement",
     "Read as logins, PINs, or account numbers that did not match a strict key format. "
     "Skim before bulking: this is the category the old rules got most wrong.")),
    ("stub", ("Fragments", "trash", "judgement",
     "Read as too little to be a thought. Some one-liners are real captures, so skim.")),
    ("errand", ("Errands and shopping", "trash", "judgement",
     "Groceries, packing lists, chores, gift lists.")),
    ("logistics", ("Logistics and admin", "trash", "judgement",
     "Appointments, housing, paperwork, bills, schedules.")),
    ("roster", ("Names and numbers", "trash", "judgement",
     "Bare lists of people or phone numbers with no context.")),
    ("attachment-only", ("Media, no text", "ask", "fact",
     "A photo or PDF with no words. Not junk — the text importer just has nothing to "
     "take, and media import is a later phase. The files stay in Apple Notes regardless.")),
    ("draft-msg", ("Messages to people", "ask", "judgement",
     "Drafted texts. Some are pure logistics; some are the most honest thing written "
     "that month. Worth scrolling rather than bulking.")),
    ("work-note", ("Work and research notes", "ask", "judgement",
     "Analysis plans, findings, meeting notes, questions for people. Tied to tasks that "
     "may be long finished, but often carrying real thinking.")),
    ("reference", ("Reference", "ask", "judgement",
     "Durable information looked up once and possibly wanted again: routines, recipes, "
     "book lists, people-and-context notes.")),
    ("writing", ("Writing", "keep", "judgement",
     "Lyrics, poems, wordplay, deliberate prose fragments.")),
    ("idea", ("Ideas", "keep", "judgement",
     "Research ideas, project seeds, arguments, observations, aphorisms.")),
    ("reflection", ("Reflection", "keep", "judgement",
     "Thinking about yourself, your life, other people, how to live. The core of what "
     "the archive is for.")),
]
SECTION_KEYS = [k for k, _ in SECTIONS]


def load_llm_verdicts() -> dict[int, dict]:
    out: dict[int, dict] = {}
    if not VERDICT_DIR.is_dir():
        return out
    for shard in sorted(VERDICT_DIR.glob("shard-*.jsonl")):
        for line in shard.read_text(encoding="utf-8").split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                v = json.loads(line)
                out[int(v["n"])] = v
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
    return out


def build() -> tuple[dict, int, int]:
    text = CANDIDATES.read_text(encoding="utf-8")
    rows = [json.loads(l) for l in text.split("\n") if l.strip()]
    llm = load_llm_verdicts()
    groups: dict[str, list] = defaultdict(list)
    unplaced = 0

    for r in rows:
        note = {"id": r["id"], "title": r["title"],
                "body": _body(r["title"], r["snippet"]).replace(OBJ, "🖼"),
                "created": r["created"]}
        got = detect(r["title"], r["snippet"])       # facts win over judgement
        if got:
            rule, reason = got
            note["why"] = reason
            groups[rule].append(note)
            continue
        v = llm.get(r["n"])
        cat = (v or {}).get("category")
        if cat in SECTION_KEYS:
            note["why"] = (v.get("why") or "").strip()
            groups[cat].append(note)
        else:
            unplaced += 1
    return groups, len(rows), unplaced


HTML = r"""<title>Composter — note triage</title>
<style>
  :root {
    --paper:#f5f5f1; --card:#fff; --ink:#1f231d; --muted:#6a7066; --line:#dfe0d8;
    --keep:#47673a; --keep-bg:#e9efe3; --toss:#9a5330; --toss-bg:#f7ece4;
    --warn:#8c3f2a; --warn-bg:#f8e8e2; --rail:#bfc4b9;
    --shadow:0 1px 2px rgba(31,35,29,.05), 0 8px 24px rgba(31,35,29,.06);
    --sans:ui-sans-serif,system-ui,-apple-system,"Helvetica Neue",sans-serif;
    --serif:ui-serif,"Iowan Old Style",Georgia,serif;
    --mono:ui-monospace,SFMono-Regular,Menlo,monospace;
  }
  @media (prefers-color-scheme: dark) { :root {
    --paper:#13150f; --card:#1c1f18; --ink:#e5e7de; --muted:#979d8f; --line:#2f332b;
    --keep:#93bb7a; --keep-bg:#212f1b; --toss:#d38d61; --toss-bg:#32211a;
    --warn:#e09277; --warn-bg:#37201a; --rail:#40453a;
    --shadow:0 1px 2px rgba(0,0,0,.5), 0 8px 24px rgba(0,0,0,.32); } }
  :root[data-theme="dark"] {
    --paper:#13150f; --card:#1c1f18; --ink:#e5e7de; --muted:#979d8f; --line:#2f332b;
    --keep:#93bb7a; --keep-bg:#212f1b; --toss:#d38d61; --toss-bg:#32211a;
    --warn:#e09277; --warn-bg:#37201a; --rail:#40453a;
    --shadow:0 1px 2px rgba(0,0,0,.5), 0 8px 24px rgba(0,0,0,.32); }
  :root[data-theme="light"] {
    --paper:#f5f5f1; --card:#fff; --ink:#1f231d; --muted:#6a7066; --line:#dfe0d8;
    --keep:#47673a; --keep-bg:#e9efe3; --toss:#9a5330; --toss-bg:#f7ece4;
    --warn:#8c3f2a; --warn-bg:#f8e8e2; --rail:#bfc4b9;
    --shadow:0 1px 2px rgba(31,35,29,.05), 0 8px 24px rgba(31,35,29,.06); }

  * { box-sizing:border-box }
  body { margin:0; background:var(--paper); color:var(--ink);
         font-family:var(--sans); font-size:15px; line-height:1.5 }
  .wrap { width:min(880px,94vw); margin:0 auto; padding:32px 0 80px;
          display:flex; flex-direction:column; gap:22px }
  h1 { font-family:var(--serif); font-size:24px; font-weight:500; margin:0 }
  .lede { color:var(--muted); max-width:72ch; margin:0 }
  .lede b { color:var(--ink); font-weight:600 }
  .tally { font-family:var(--mono); font-size:12px; color:var(--muted);
           display:flex; gap:16px; font-variant-numeric:tabular-nums; margin-top:8px }
  .tally .t b{color:var(--toss)} .tally .k b{color:var(--keep)}
  .warn { background:var(--warn-bg); border-left:3px solid var(--warn);
          padding:13px 16px; border-radius:0 7px 7px 0 }
  .warn b { color:var(--warn) }

  section { border:1px solid var(--line); border-radius:10px; background:var(--card);
            box-shadow:var(--shadow); overflow:hidden }
  .head { padding:16px 19px; display:grid; grid-template-columns:1fr auto;
          gap:5px 16px; align-items:center; border-bottom:1px solid var(--line) }
  .head h2 { margin:0; font-size:16px; font-weight:600; display:flex; gap:9px;
             align-items:center; flex-wrap:wrap }
  .dot { width:8px; height:8px; border-radius:50%; flex:none }
  .dot.trash{background:var(--toss)} .dot.keep{background:var(--keep)}
  .dot.ask{background:var(--rail)}
  .kind { font-family:var(--mono); font-size:10px; text-transform:uppercase;
          letter-spacing:.06em; padding:2px 6px; border-radius:3px;
          border:1px solid var(--line); color:var(--muted); font-weight:400 }
  .kind.fact { color:var(--ink); border-color:var(--muted) }
  .n { font-family:var(--mono); font-size:11.5px; color:var(--muted);
       font-variant-numeric:tabular-nums; font-weight:400 }
  .head p { margin:0; grid-column:1; color:var(--muted); font-size:13.5px; max-width:66ch }
  .head .acts { grid-row:1 / span 2; grid-column:2; display:flex; gap:6px;
                align-items:center }

  ul.notes { list-style:none; margin:0; padding:0; max-height:400px; overflow-y:auto }
  ul.notes li { padding:11px 19px; border-bottom:1px solid var(--line);
                display:grid; grid-template-columns:1fr auto; gap:2px 14px;
                align-items:start }
  ul.notes li:last-child { border-bottom:0 }
  ul.notes li.tossed { opacity:.4 }
  ul.notes li.kept { background:var(--keep-bg) }
  .nt { font-family:var(--serif); font-size:15.5px; margin:0; overflow-wrap:anywhere }
  .nb { grid-column:1; font-family:var(--mono); font-size:12px; color:var(--muted);
        margin:0; white-space:pre-wrap; overflow-wrap:anywhere;
        max-height:4.2em; overflow:hidden }
  .nb:empty::before { content:"— no body —"; font-style:italic }
  .nw { grid-column:1; font-size:11.5px; color:var(--muted); margin:0; font-style:italic }
  .row-acts { grid-row:1 / span 3; grid-column:2; display:flex; gap:5px; align-items:center }

  button { font:inherit; font-size:13px; padding:6px 11px; border-radius:6px;
           border:1px solid var(--line); background:var(--card); color:var(--ink);
           cursor:pointer; white-space:nowrap }
  button:hover:not(:disabled) { border-color:var(--muted) }
  button:disabled { opacity:.4; cursor:default }
  button:focus-visible { outline:2px solid var(--ink); outline-offset:2px }
  button.toss { color:var(--toss) } button.keep { color:var(--keep) }
  button.primary { background:var(--ink); color:var(--paper); border-color:var(--ink) }
  button.mini { padding:3px 9px; font-size:12px }
  button.link { border:0; background:none; color:var(--muted); padding:6px 4px;
                text-decoration:underline }
  .bar { display:flex; gap:9px; flex-wrap:wrap; align-items:center;
         position:sticky; bottom:0; background:var(--paper);
         padding:14px 0; border-top:1px solid var(--line) }
  details > summary { cursor:pointer; color:var(--muted); font-size:13.5px }
  .folders { display:grid; grid-template-columns:repeat(auto-fill,minmax(160px,1fr));
             gap:7px; margin-top:13px }
  .folders label { display:flex; gap:8px; align-items:center; font-size:13.5px;
                   padding:8px 10px; border:1px solid var(--line); border-radius:6px;
                   cursor:pointer }
  .folders input:checked + span { color:var(--toss); font-weight:500 }
</style>

<div class="wrap">
  <div>
    <h1>Note triage</h1>
    <div class="tally">
      <span class="t">tossed <b id="nT">0</b></span>
      <span class="k">kept <b id="nK">0</b></span>
      <span>undecided <b id="nU">0</b></span>
      <span>of <b>__TOTAL__</b></span>
    </div>
  </div>

  <p class="lede">Scroll a section, pick off the ones you care about, then bulk the rest.
    <b>Bulk only touches notes you haven't decided</b> — your own choices always win.
    Sections marked <span class="kind fact">fact</span> are matched on form and are safe to
    trust; <span class="kind">judgement</span> means a model guessed and you should skim.
    Nothing is deleted either way: tossing only stops composter importing it.</p>

  <div id="warnbox"></div>
  <div id="groups"></div>

  <div class="bar">
    <button class="primary" onclick="download()">Download decisions</button>
    <button onclick="reset()">Clear all decisions</button>
    <span style="flex:1"></span>
    <details><summary>Exclude whole folders</summary>
      <div class="folders" id="folders"></div></details>
  </div>
</div>

<script>
const GROUPS = __GROUPS__, META = __META__, ORDER = __ORDER__, TOTAL = __TOTAL__;
const KEY = "composter-triage-v2";          // unchanged: earlier work carries over
let S = JSON.parse(localStorage.getItem(KEY) || '{"d":{},"folders":[]}');
if (!S.d) S.d = {}; if (!S.folders) S.folders = [];

const $ = id => document.getElementById(id);
const esc = s => (s||"").replace(/[&<>]/g, m => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[m]));
const save = () => localStorage.setItem(KEY, JSON.stringify(S));

function tally() {
  let t=0,k=0;
  for (const v of Object.values(S.d)) { if (v==="trash") t++; else if (v==="keep") k++; }
  $("nT").textContent=t; $("nK").textContent=k; $("nU").textContent=TOTAL-t-k;
}

function noteLI(n) {
  const v = S.d[n.id] || "";
  return `<li class="${v==="trash"?"tossed":v==="keep"?"kept":""}" data-id="${esc(n.id)}">
    <p class="nt">${esc(n.title) || "<em>untitled</em>"}</p>
    <p class="nb">${esc(n.body)}</p>
    <p class="nw">${esc(n.why||"")}${n.created?` · ${n.created.slice(0,10)}`:""}</p>
    <span class="row-acts">
      <button class="mini toss" onclick="one(this,'trash')">toss</button>
      <button class="mini keep" onclick="one(this,'keep')">keep</button>
    </span></li>`;
}

function section(key) {
  const m = META[key], notes = GROUPS[key];
  return `<section data-key="${esc(key)}">
    <div class="head">
      <h2><span class="dot ${m.lean}"></span>${esc(m.label)}
        <span class="kind ${m.kind==="fact"?"fact":""}">${m.kind}</span>
        <span class="n" data-count></span></h2>
      <p>${esc(m.blurb)}</p>
      <span class="acts">
        <button class="toss" data-bulk="trash" onclick="bulk('${key}','trash')"></button>
        <button class="keep" data-bulk="keep" onclick="bulk('${key}','keep')"></button>
        <button class="link" data-clear onclick="clearSection('${key}')">clear</button>
      </span>
    </div>
    <ul class="notes">${notes.map(noteLI).join("")}</ul>
  </section>`;
}

// Repaint only what changed: a full re-render would throw away the scroll
// position of the list being worked down.
function paintLI(li) {
  const v = S.d[li.dataset.id];
  li.classList.toggle("tossed", v === "trash");
  li.classList.toggle("kept", v === "keep");
}
function paintCount(sec) {
  const notes = GROUPS[sec.dataset.key] || [];
  const left = notes.filter(n => !S.d[n.id]).length;
  const done = notes.length - left;
  sec.querySelector("[data-count]").textContent =
    `${notes.length}` + (done ? ` · ${done} decided` : "");
  for (const b of sec.querySelectorAll("[data-bulk]")) {
    const verb = b.dataset.bulk === "trash" ? "Toss" : "Keep";
    b.textContent = `${verb} remaining${left ? ` (${left})` : ""}`;
    b.disabled = left === 0;
  }
  sec.querySelector("[data-clear]").disabled = done === 0;
}
function repaint(sec) { sec.querySelectorAll("li").forEach(paintLI); paintCount(sec); tally(); }

function one(btn, v) {
  const li = btn.closest("li"), id = li.dataset.id;
  if (S.d[id] === v) delete S.d[id]; else S.d[id] = v;
  save(); paintLI(li); paintCount(li.closest("section")); tally();
}
function bulk(key, v) {
  for (const n of GROUPS[key]) if (!S.d[n.id]) S.d[n.id] = v;   // never overwrite
  save(); repaint(document.querySelector(`section[data-key="${key}"]`));
}
function clearSection(key) {
  for (const n of GROUPS[key]) delete S.d[n.id];
  save(); repaint(document.querySelector(`section[data-key="${key}"]`));
}
function reset() {
  if (!confirm("Discard every decision on every section?")) return;
  S.d = {}; save();
  document.querySelectorAll("section[data-key]").forEach(repaint);
}
function download() {
  const trash=[], kept=[];
  for (const [id,v] of Object.entries(S.d)) (v==="trash"?trash:kept).push(id);
  const blob = new Blob([JSON.stringify(
    {trash_ids:trash, kept_ids:kept, excluded_folders:S.folders}, null, 1)],
    {type:"application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "composter-triage-decisions.json";
  a.click();
}

const creds = (GROUPS["live-key"]||[]).length;
$("warnbox").innerHTML = creds ? `<div class="warn"><b>${creds} notes contain what look
  like live API keys.</b> Rotate them, then delete the notes — they are plaintext in
  Apple Notes and sync to every device.</div>` : "";
$("groups").innerHTML = ORDER.filter(k => (GROUPS[k]||[]).length).map(section).join("");
document.querySelectorAll("section[data-key]").forEach(paintCount);
tally();

$("folders").innerHTML = __FOLDERS__.map(f =>
  `<label><input type="checkbox" value="${esc(f)}" ${S.folders.includes(f)?"checked":""}
     onchange="toggleFolder(this)"><span>${esc(f)}</span></label>`).join("");
function toggleFolder(el) {
  S.folders = el.checked ? [...new Set([...S.folders, el.value])]
                         : S.folders.filter(f => f!==el.value);
  save();
}
</script>
"""


def main() -> None:
    groups, total, unplaced = build()
    meta = {k: {"label": v[0], "lean": v[1], "kind": v[2], "blurb": v[3]}
            for k, v in SECTIONS}
    html = (HTML
            .replace("__GROUPS__", json.dumps(groups, ensure_ascii=False))
            .replace("__META__", json.dumps(meta, ensure_ascii=False))
            .replace("__ORDER__", json.dumps(SECTION_KEYS))
            .replace("__FOLDERS__", json.dumps(FOLDERS))
            .replace("__TOTAL__", str(total)))
    OUT.write_text(html, encoding="utf-8")

    print(f"{total} notes -> {OUT}")
    placed = 0
    for key, (label, lean, kind, _) in SECTIONS:
        n = len(groups.get(key, []))
        placed += n
        if n:
            print(f"  {label:32} {n:5}  {lean:5} {kind}")
    print(f"  {'(unclassified, not shown)':32} {unplaced:5}")
    assert placed + unplaced == total, f"{placed} + {unplaced} != {total}"


if __name__ == "__main__":
    main()
