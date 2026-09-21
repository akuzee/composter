"""One-off: put the thought in the body for title-only notes already imported.

Apple Notes uses the first line as the note's name, so a one-line jot arrives
with a meaningful title and an empty body. Those notes render as a blank page
in Obsidian, and an indexer sees nothing but frontmatter boilerplate — which is
near-identical across all of them, so they embed as similar to each other
rather than to what they say.

`sources/apple_notes.py` now writes the title into the body at import. This
fixes the ones imported before that change. It cannot happen automatically:
the upstream payload is unchanged, so the importer's "don't write unless
upstream changed" rule correctly short-circuits.

Only the fenced region is touched. Frontmatter and everything below the end
fence are preserved byte-for-byte.

    .venv/bin/python scripts/fix_empty_bodies.py [--apply]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import load_config                      # noqa: E402
from src.db import DB                                   # noqa: E402
from src.vault import (FENCE_BEGIN, FENCE_END, VaultWriter,  # noqa: E402
                       parse_note, sha256_text)


def main() -> int:
    apply = "--apply" in sys.argv
    cfg = load_config(None)
    db = DB(cfg.db_path)
    writer = VaultWriter(cfg.vault_root, cfg.managed_dir, cfg.vault_id,
                         dry_run=not apply)

    fixed = skipped = 0
    samples = []
    for item in db.items_in_state("managed"):
        if not item.path:
            continue
        path = cfg.vault_root / item.path
        if not path.is_file():
            continue
        raw = path.read_text(encoding="utf-8")
        parsed = parse_note(raw)
        if parsed.body is None or parsed.body.strip():
            continue                     # broken fences, or already has content
        title = str(parsed.frontmatter.get("title") or "").strip()
        if not title or title.lower() in ("untitled", "new note"):
            skipped += 1
            continue
        # Splice the fenced region only; every other byte is preserved.
        i = raw.index(FENCE_BEGIN) + len(FENCE_BEGIN)
        j = raw.index(FENCE_END)
        new = raw[:i] + "\n" + title + "\n" + raw[j:]
        if len(samples) < 5:
            samples.append((item.path, title))
        if apply:
            writer._write_bytes(path, new.encode("utf-8"))
            db.update_item(item.id, written_hash=sha256_text(new),
                           managed_body_hash=sha256_text(title))
        fixed += 1

    print(f"{'rewrote' if apply else 'would rewrite'}: {fixed}")
    print(f"left alone (no meaningful title): {skipped}")
    for p, t in samples:
        print(f"   {p}\n     body <- {t!r}")
    if not apply:
        print("\ndry run — nothing written. re-run with --apply")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
