"""Apply the decisions JSON downloaded from the triage review page.

    .venv/bin/python triage/apply_decisions.py [path-to-decisions.json]

Defaults to the newest composter-triage-decisions*.json in ~/Downloads.
Effects (both merging, never overwriting previous decisions):
  - trash ids  -> state/triage_exclusions.json  (source skips them forever)
  - folder exclusions -> printed for config/composter.yaml (shown, not edited,
    so the config file stays hand-owned)
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUSIONS = ROOT / "state" / "triage_exclusions.json"


def find_decisions() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1]).expanduser()
    downloads = sorted(Path.home().glob("Downloads/composter-triage-decisions*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    if not downloads:
        raise SystemExit("no composter-triage-decisions*.json in ~/Downloads; "
                         "click 'Download decisions' on the review page first")
    return downloads[0]


def main() -> None:
    src = find_decisions()
    decisions = json.loads(src.read_text(encoding="utf-8"))
    new_trash = set(decisions.get("trash_ids", []))
    kept = set(decisions.get("kept_ids", []))

    existing = {"trash_ids": []}
    if EXCLUSIONS.is_file():
        existing = json.loads(EXCLUSIONS.read_text(encoding="utf-8"))
    merged = (set(existing.get("trash_ids", [])) | new_trash) - kept  # keep wins on re-review
    EXCLUSIONS.parent.mkdir(parents=True, exist_ok=True)
    EXCLUSIONS.write_text(json.dumps(
        {"trash_ids": sorted(merged)}, indent=1), encoding="utf-8")

    print(f"applied {src.name}:")
    print(f"  trash ids: +{len(new_trash)} (total {len(merged)}) -> {EXCLUSIONS}")
    folders = decisions.get("excluded_folders", [])
    if folders:
        print("  folder exclusions chosen — add to config/composter.yaml under "
              "sources.notes.exclude_folders:")
        for f in folders:
            print(f"    - {f}")


if __name__ == "__main__":
    main()
