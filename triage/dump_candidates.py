"""Triage dump: id/title/created/snippet for every note in the iCloud "Notes"
folder, as JSONL. Hand-invoked, read-only, not part of the capture pipeline.

    .venv/bin/python triage/dump_candidates.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.sources.apple_notes import run_jxa  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "state" / "triage_candidates.jsonl"
FOLDER = "iCloud/Notes"
BATCH = 50


def main() -> None:
    index = {e["id"]: e for e in json.loads(run_jxa("dump_index.js", []))}
    folders = json.loads(run_jxa("dump_folders.js", []))
    ids = [i for i in folders.get(FOLDER, []) if i in index and not index[i]["locked"]]
    print(f"{len(ids)} unlocked notes in {FOLDER}", flush=True)

    rows = []
    for i in range(0, len(ids), BATCH):
        batch = ids[i:i + BATCH]
        for s in json.loads(run_jxa("dump_snippets.js", batch, timeout=600)):
            e = index[s["id"]]
            rows.append({
                "id": s["id"],
                "title": e["name"],
                "created": e["created"],
                "modified": e["modified"],
                "snippet": " ".join(s["snippet"].split()),  # squash whitespace
            })
        print(f"  {min(i + BATCH, len(ids))}/{len(ids)}", flush=True)

    rows.sort(key=lambda r: r["modified"] or "", reverse=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        for n, r in enumerate(rows):
            r["n"] = n
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} rows to {OUT}")


if __name__ == "__main__":
    main()
