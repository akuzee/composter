// Folder membership: O(folders) Apple Events, not O(notes). Walks every
// account and recurses into subfolders, emitting account-prefixed paths
// ("iCloud/Notebook/drafts") — accounts can have same-named folders, so the
// prefix prevents collisions. Best-effort — the importer works without it.
function run() {
  const app = Application('Notes');
  const out = {};
  function walk(folder, prefix) {
    const name = prefix + '/' + folder.name();
    try {
      out[name] = folder.notes.id();
    } catch (e) {
      out[name] = [];
    }
    let subs = [];
    try {
      subs = folder.folders();
    } catch (e) {
      subs = [];
    }
    for (const sub of subs) {
      walk(sub, name);
    }
  }
  for (const account of app.accounts()) {
    for (const f of account.folders()) {
      walk(f, account.name());
    }
  }
  return JSON.stringify(out);
}
