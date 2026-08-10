"""The source contract.

A source's entire job is to yield Captures. No source knows what a vault
is, what a conflict is, or what graduation means — if a source module
imports os.replace or builds a vault path, the design has failed (plan §7.4).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Capture:
    source: str            # apple-notes | voice-memo | ios-share | fixture | ...
    source_id: str         # stable upstream identity, never a filename
    title: str
    body: str              # markdown
    created: str | None    # ISO8601 with offset — when the thought happened
    kind: str = "note"     # note | transcript | clipping | snippet | photo | link | paper
    zone: str = "produced"
    authorship: str = "mine"
    source_ref: str | None = None   # e.g. "Notes/Ideas" folder path upstream
    media: tuple = ()               # vault-relative media paths, explicit
    skip_reason: str | None = None  # locked / empty / too short — re-checked each run
    modified: str | None = None     # raw upstream modification stamp (prefilter only)
    payload_hash: str | None = None  # explicit hash of the raw upstream payload

    @property
    def composter_id(self) -> str:
        return f"{self.source}:{self.source_id}"

    @property
    def source_hash(self) -> str:
        """sha256 of the canonical upstream payload — THE change detector.
        Sources that convert (e.g. HTML -> markdown) set payload_hash over the
        raw upstream form, so converter changes never look like edits."""
        if self.payload_hash:
            return self.payload_hash
        payload = "\x00".join([self.title, self.body, self.created or ""])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def fingerprint(self) -> str:
        """Disaster-recovery identity when upstream IDs change (plan risk 1)."""
        payload = f"{self.created or ''}|{self.body[:200]}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Source:
    """Interface. Concrete sources: fixture, apple_notes, voice_memos, ios_inbox."""

    name: str = "base"
    subfolder: str = "Notes"  # zCompost/<subfolder>/ where captures land

    def captures(self, limit: int | None = None,
                 known_mods: dict[str, str] | None = None) -> list[Capture]:
        """known_mods maps source_id -> last-imported modification stamp; a
        source may use it to skip fetching bodies that haven't moved. Sources
        without cheap modification dates ignore it."""
        raise NotImplementedError
