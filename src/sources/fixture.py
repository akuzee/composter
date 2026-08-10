"""Synthetic captures from a YAML file, for exercising the state machine
before any real source exists (plan §7.4).

Fixture YAML is a list of entries:

    - id: fx-001
      title: composting metaphor
      created: 2026-08-09T14:32:11-04:00
      body: |
        Tracking my inner life for the purpose of composting it.
      kind: note            # optional
      authorship: mine      # optional
      source_ref: Fixture   # optional
      skip: locked          # optional -> state 'skipped'
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .base import Capture, Source


class FixtureSource(Source):
    name = "fixture"
    subfolder = "Notes"

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def captures(self, limit: int | None = None,
                 known_mods: dict[str, str] | None = None) -> list[Capture]:
        with open(self.path, "r", encoding="utf-8") as f:
            entries = yaml.safe_load(f) or []
        if not isinstance(entries, list):
            raise ValueError(f"fixture file must be a YAML list: {self.path}")
        out = []
        for e in entries:
            created = e.get("created")
            if hasattr(created, "isoformat"):  # yaml parses bare timestamps
                created = created.isoformat()
            out.append(
                Capture(
                    source=self.name,
                    source_id=str(e["id"]),
                    title=str(e.get("title", "untitled")),
                    body=str(e.get("body", "")).rstrip("\n"),
                    created=str(created) if created else None,
                    kind=str(e.get("kind", "note")),
                    zone=str(e.get("zone", "produced")),
                    authorship=str(e.get("authorship", "mine")),
                    source_ref=e.get("source_ref"),
                    skip_reason=e.get("skip"),
                )
            )
            if limit is not None and len(out) >= limit:
                break
        return out
