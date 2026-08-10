// Cheap index of the entire Notes library. The plural-specifier form returns
// an entire property column in ONE Apple Event, so this is five events total
// regardless of library size (plan §8.1). JXA not AppleScript: JSON out,
// ISO dates, no locale-dependent parsing.
function run() {
  const notes = Application('Notes').notes;
  const ids = notes.id();
  const names = notes.name();
  const mods = notes.modificationDate();
  const crts = notes.creationDate();
  const locks = notes.passwordProtected();
  const out = ids.map((id, i) => ({
    id: id,
    name: names[i],
    locked: locks[i],
    modified: mods[i] ? mods[i].toISOString() : null,
    created: crts[i] ? crts[i].toISOString() : null,
  }));
  return JSON.stringify(out);
}
