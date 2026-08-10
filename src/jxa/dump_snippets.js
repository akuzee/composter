// Triage support: plaintext snippets (first ~280 chars) for explicit ids.
// Read-only; used by the hand-invoked triage tool, never by scheduled pulls.
function run(argv) {
  const app = Application('Notes');
  const out = [];
  for (const id of argv) {
    let txt = '';
    try {
      txt = app.notes.byId(id).plaintext() || '';
    } catch (e) {
      txt = '';
    }
    out.push({ id: id, snippet: txt.slice(0, 280) });
  }
  return JSON.stringify(out);
}
