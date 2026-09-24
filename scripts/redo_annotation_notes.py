"""One-off: re-import voice notes whose title came from a whisper annotation.

Nine notes were written during the first backfill, before two fixes landed:
parenthesised annotations were not yet stripped, and the owner's recording
names were being read from the wrong database column. They ended up titled
"(upbeat music)" when the recording has a real name in Voice Memos.

Filenames are chosen once at creation and never changed (plan §7.2 invariant
5), so the only way to correct one is to supersede it and let it be imported
again. The file is MOVED to _superseded/, never deleted, and the ledger row
is dropped so the next pull treats the recording as new.

    .venv/bin/python scripts/redo_annotation_notes.py [--apply]
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import load_config                        # noqa: E402
from src.db import DB                                     # noqa: E402
from src.transcribe import strip_non_speech               # noqa: E402
from src.vault import VaultWriter, parse_note             # noqa: E402


def annotation_only(body: str) -> bool:
    """Body has text, but none of it is speech — only sound descriptions."""
    prose = "\n".join(l for l in body.splitlines()
                      if not l.startswith("![[") and not l.startswith("> [!"))
    return bool(prose.strip()) and not strip_non_speech(prose).strip()


def main() -> int:
    apply = "--apply" in sys.argv
    cfg = load_config(None)
    db = DB(cfg.db_path)
    writer = VaultWriter(cfg.vault_root, cfg.managed_dir, cfg.vault_id,
                         dry_run=not apply)
    today = date.today().isoformat()
    n = 0
    for item in db.items_in_state("managed"):
        if item.source != "voice-memo" or not item.path:
            continue
        path = cfg.vault_root / item.path
        if not path.is_file():
            continue
        parsed = parse_note(path.read_text(encoding="utf-8"))
        body = parsed.body or ""
        title = str(parsed.frontmatter.get("title") or "")
        # Stale either way: a body that is only annotations, or a title built
        # from one before annotations were being stripped.
        # Compare on collapsed whitespace: strip_non_speech normalises runs of
        # spaces, and a title that merely had a double space in it is not stale.
        def norm(s: str) -> str:
            return re.sub(r"\s+", " ", s).strip()
        title_stale = bool(title.strip()) and norm(strip_non_speech(title)) != norm(title)
        if not (annotation_only(body) or title_stale):
            continue
        print(f"  {item.path}")
        if apply:
            moved = writer.supersede(item.path, today)
            # Drop the ledger row so the next pull imports it afresh with the
            # correct name. The content is preserved in _superseded/.
            with db.conn:
                db.conn.execute("DELETE FROM items WHERE id=?", (item.id,))
            print(f"    -> {moved}  (ledger row dropped; will re-import)")
        n += 1
    print(f"\n{'superseded' if apply else 'would supersede'}: {n}")
    if not apply:
        print("dry run — re-run with --apply")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
