// Fetch bodies for an explicit list of note ids (passed as argv).
// Called in batches of ~50; only for notes whose modification date moved.
// No .whose() clauses — inconsistently supported (plan §8.1).
// Attachment names ride along: normalized attachments (cid-style) may not
// appear in body HTML at all, and "nothing silently lost" requires knowing
// they exist.
function run(argv) {
  const app = Application('Notes');
  const out = [];
  for (const id of argv) {
    const note = app.notes.byId(id);
    let atts = [];
    try {
      atts = note.attachments.name();
    } catch (e) {
      atts = [];
    }
    out.push({ id: id, name: note.name(), body: note.body(), attachments: atts });
  }
  return JSON.stringify(out);
}
