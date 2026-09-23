"""One-off: turn bare filesystem paths for out-of-vault audio into clickable
file:// links.

Voice memos are write-once, so the importer will never rewrite these notes on
its own — their upstream payload has not changed. Only the fenced region is
touched; frontmatter and anything below the end fence stay byte-identical.

    .venv/bin/python scripts/fix_external_media_links.py [--apply]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import load_config                                  # noqa: E402
from src.db import DB                                               # noqa: E402
from src.vault import FENCE_BEGIN, FENCE_END, VaultWriter, sha256_text  # noqa: E402

OLD = re.compile(
    r"> \[!info\] Media kept outside the vault \(over (\d+) MB\): `([^`]+)`")


def main() -> int:
    apply = "--apply" in sys.argv
    cfg = load_config(None)
    db = DB(cfg.db_path)
    writer = VaultWriter(cfg.vault_root, cfg.managed_dir, cfg.vault_id,
                         dry_run=not apply)
    fixed = 0
    for item in db.items_in_state("managed", "conflict"):
        if not item.path:
            continue
        path = cfg.vault_root / item.path
        if not path.is_file():
            continue
        raw = path.read_text(encoding="utf-8")
        m = OLD.search(raw)
        if not m:
            continue
        mb, target = m.group(1), m.group(2)
        link = (f"> [!info] Audio kept outside the vault (over {mb} MB) — "
                f"[open {Path(target).name}](file://{quote(target)})")
        new = raw[:m.start()] + link + raw[m.end():]
        print(f"  {item.path}\n    -> {link[:100]}")
        if apply:
            writer._write_bytes(path, new.encode("utf-8"))
            i = new.index(FENCE_BEGIN) + len(FENCE_BEGIN)
            j = new.index(FENCE_END)
            body = new[i:j].strip("\n")
            db.update_item(item.id, written_hash=sha256_text(new),
                           managed_body_hash=sha256_text(body))
        fixed += 1
    print(f"\n{'rewrote' if apply else 'would rewrite'}: {fixed}")
    if not apply:
        print("dry run — re-run with --apply")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
