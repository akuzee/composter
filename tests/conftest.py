"""Every test runs against a freshly-built throwaway vault under tmp_path.
The real vault is never touched by this suite — that is the point of it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from src.config import Config, parse_config
from src.db import DB
from src.main import run_pull, run_reindex
from src.vault import capture_baseline, init_managed_root

VAULT_ID = "test-vault"

# Decoy files standing in for the 136 hand-written notes: if any byte of
# these ever changes during a test, the isolation machinery must scream.
DECOYS = {
    "a poem 3-9-26.md": "the curated tree\nmust never change\n",
    "Main/Areas/Art/essay.md": "# essay\n\nhand-written words.\n",
    "Main/Zettlekasken/idea.md": "an old idea\n",
    "Clippings/someone elses piece.md": "---\ntitle: theirs\n---\nnot my words\n",
}


class Env:
    def __init__(self, root: Path):
        self.root = root
        self.vault = root / "vault"
        self.state = root / "state"
        self.fixture_path = root / "fixture_captures.yaml"
        self.vault.mkdir()
        for rel, text in DECOYS.items():
            p = self.vault / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        init_managed_root(self.vault, "zCompost", VAULT_ID)

        self.cfg = parse_config(
            {
                "vault": {"root": str(self.vault), "managed_dir": "zCompost", "vault_id": VAULT_ID},
                "state_dir": str(self.state),
                "writer": {"max_new_per_run": 50, "on_local_edit": "conflict",
                           "dismiss_after_runs": 3, "dismiss_after_seconds": 3600},
                "isolation": {"exclude": []},
                "sources": {"fixture": {"enabled": True, "path": str(self.fixture_path)}},
            },
            base=root,
        )
        self.cfg.ensure_state_dirs()
        self.db = DB(self.cfg.db_path)
        capture_baseline(self.vault, "zCompost", [], self.cfg.isolation_baseline_path)
        self.t0 = datetime(2026, 8, 10, 9, 0, 0, tzinfo=timezone.utc).astimezone()

    def set_fixture(self, entries: list[dict]) -> None:
        self.fixture_path.write_text(yaml.safe_dump(entries, sort_keys=False), encoding="utf-8")

    def pull(self, minutes: float = 0, **kw) -> dict:
        return run_pull(self.cfg, self.db, "fixture",
                        now=self.t0 + timedelta(minutes=minutes), **kw)

    def reindex(self, minutes: float = 0) -> dict:
        return run_reindex(self.cfg, self.db, now=self.t0 + timedelta(minutes=minutes))

    def managed_files(self) -> list[Path]:
        notes = self.vault / "zCompost" / "Notes"
        return sorted(p for p in notes.rglob("*.md"))

    def item(self, source_id: str = "fx-001"):
        return self.db.get_item("fixture", source_id)


ENTRY = {
    "id": "fx-001",
    "title": "composting metaphor",
    "created": "2026-08-09T14:32:11-04:00",
    "body": "Tracking my inner life for the purpose of composting it.\n\nSecond paragraph.",
}


@pytest.fixture
def env(tmp_path) -> Env:
    return Env(tmp_path)


@pytest.fixture
def seeded(env) -> Env:
    env.set_fixture([dict(ENTRY)])
    result = env.pull()
    assert result["created"] == 1, result
    return env
