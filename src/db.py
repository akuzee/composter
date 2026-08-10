"""The ledger — state/composter.sqlite, the only durable state (plan §7.1).

State machine:

    new ──► managed ─┬─ moved outside zCompost/ ──────► graduated  (terminal)
                     ├─ marker gone from vault ───────► dismissed  (terminal)
                     ├─ composter_managed: false ─────► graduated
                     └─ local edit + upstream edit ───► conflict ──► managed | graduated
    skipped   (locked, empty, too short — re-checked each run)
    error     (transient; retried)

`graduated` and `dismissed` are terminal. Moving a graduated file back into
zCompost/ does not resume management.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = 1

STATES = ("managed", "conflict", "graduated", "dismissed", "skipped", "error")
TERMINAL_STATES = ("graduated", "dismissed")
ACTIVE_STATES = ("managed", "conflict")

# state -> states it may move to. Terminal states go nowhere, ever.
ALLOWED_TRANSITIONS = {
    "managed": {"managed", "conflict", "graduated", "dismissed", "error"},
    "conflict": {"managed", "conflict", "graduated", "dismissed", "error"},
    "skipped": {"skipped", "managed", "error"},
    "error": {"managed", "conflict", "skipped", "error", "graduated", "dismissed"},
    "graduated": set(),
    "dismissed": set(),
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    composter_id TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL,
    title TEXT,
    kind TEXT,
    zone TEXT NOT NULL DEFAULT 'produced',
    authorship TEXT NOT NULL DEFAULT 'mine',
    created_at TEXT,
    captured_at TEXT,
    source_ref TEXT,
    path TEXT,
    source_hash TEXT,
    source_modified_at TEXT,
    written_hash TEXT,
    managed_body_hash TEXT,
    fingerprint TEXT,
    rev INTEGER NOT NULL DEFAULT 0,
    source_alt_id TEXT,
    skip_reason TEXT,
    error_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    missing_runs INTEGER NOT NULL DEFAULT 0,
    missing_since TEXT,
    first_seen_at TEXT,
    state_changed_at TEXT,
    UNIQUE(source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_items_state ON items(state);
CREATE INDEX IF NOT EXISTS idx_items_fingerprint ON items(fingerprint);

CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES items(id),
    path TEXT NOT NULL,
    sha256 TEXT,
    bytes INTEGER
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    source TEXT,
    ok INTEGER NOT NULL DEFAULT 0,
    created INTEGER NOT NULL DEFAULT 0,
    updated INTEGER NOT NULL DEFAULT 0,
    unchanged INTEGER NOT NULL DEFAULT 0,
    conflicts INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0,
    graduated INTEGER NOT NULL DEFAULT 0,
    dismissed INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


class TransitionError(RuntimeError):
    pass


@dataclass
class Item:
    id: int
    source: str
    source_id: str
    composter_id: str
    state: str
    title: str | None
    kind: str | None
    zone: str
    authorship: str
    created_at: str | None
    captured_at: str | None
    source_ref: str | None
    path: str | None
    source_hash: str | None
    source_modified_at: str | None
    written_hash: str | None
    managed_body_hash: str | None
    fingerprint: str | None
    rev: int
    source_alt_id: str | None
    skip_reason: str | None
    error_count: int
    last_error: str | None
    missing_runs: int
    missing_since: str | None
    first_seen_at: str | None
    state_changed_at: str | None


def _to_item(row: sqlite3.Row) -> Item:
    return Item(**{k: row[k] for k in Item.__dataclass_fields__})


class DB:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(_SCHEMA)
        cur = self.conn.execute("SELECT value FROM kv WHERE key='schema_version'")
        row = cur.fetchone()
        if row is None:
            self.kv_set("schema_version", str(SCHEMA_VERSION))
        elif int(row["value"]) != SCHEMA_VERSION:
            raise RuntimeError(
                f"ledger schema version {row['value']} != code version {SCHEMA_VERSION}"
            )

    def close(self) -> None:
        self.conn.close()

    # -- kv -------------------------------------------------------------

    def kv_get(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def kv_set(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO kv(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    # -- items ------------------------------------------------------------

    def get_item(self, source: str, source_id: str) -> Item | None:
        row = self.conn.execute(
            "SELECT * FROM items WHERE source=? AND source_id=?", (source, source_id)
        ).fetchone()
        return _to_item(row) if row else None

    def get_by_composter_id(self, composter_id: str) -> Item | None:
        row = self.conn.execute(
            "SELECT * FROM items WHERE composter_id=?", (composter_id,)
        ).fetchone()
        return _to_item(row) if row else None

    def find_by_fingerprint(self, source: str, fingerprint: str, states=ACTIVE_STATES) -> Item | None:
        q = f"SELECT * FROM items WHERE source=? AND fingerprint=? AND state IN ({','.join('?' * len(states))})"
        row = self.conn.execute(q, (source, fingerprint, *states)).fetchone()
        return _to_item(row) if row else None

    def mods_for_source(self, source: str) -> dict[str, str]:
        """source_id -> last-imported modification stamp, for the source's
        fetch-bodies prefilter. Conflict/error items are excluded so their
        payloads keep refreshing until resolved."""
        rows = self.conn.execute(
            "SELECT source_id, source_modified_at FROM items "
            "WHERE source=? AND source_modified_at IS NOT NULL "
            "AND state NOT IN ('conflict', 'error')",
            (source,),
        )
        return {r["source_id"]: r["source_modified_at"] for r in rows}

    def items_in_state(self, *states: str) -> list[Item]:
        q = f"SELECT * FROM items WHERE state IN ({','.join('?' * len(states))}) ORDER BY id"
        return [_to_item(r) for r in self.conn.execute(q, states)]

    def active_items(self) -> list[Item]:
        return self.items_in_state(*ACTIVE_STATES)

    def counts_by_state(self) -> dict[str, int]:
        rows = self.conn.execute("SELECT state, COUNT(*) AS n FROM items GROUP BY state")
        return {r["state"]: r["n"] for r in rows}

    def insert_item(self, *, source, source_id, composter_id, state, now, **fields) -> Item:
        if state not in STATES:
            raise TransitionError(f"unknown state {state!r}")
        cols = {
            "source": source, "source_id": source_id, "composter_id": composter_id,
            "state": state, "first_seen_at": now, "state_changed_at": now, **fields,
        }
        keys = ", ".join(cols)
        marks = ", ".join("?" * len(cols))
        with self.conn:
            cur = self.conn.execute(
                f"INSERT INTO items({keys}) VALUES({marks})", tuple(cols.values())
            )
        return self.get_by_composter_id(composter_id) or _to_item(
            self.conn.execute("SELECT * FROM items WHERE id=?", (cur.lastrowid,)).fetchone()
        )

    def update_item(self, item_id: int, **fields) -> None:
        if "state" in fields:
            raise TransitionError("use set_state() to change state")
        sets = ", ".join(f"{k}=?" for k in fields)
        with self.conn:
            self.conn.execute(f"UPDATE items SET {sets} WHERE id=?", (*fields.values(), item_id))

    def set_state(self, item: Item, new_state: str, now: str, **fields) -> None:
        """The only way state changes. Enforces the transition map; terminal
        states (graduated, dismissed) cannot be left, by construction."""
        if new_state not in STATES:
            raise TransitionError(f"unknown state {new_state!r}")
        allowed = ALLOWED_TRANSITIONS.get(item.state, set())
        if new_state != item.state and new_state not in allowed:
            raise TransitionError(
                f"illegal transition {item.state!r} -> {new_state!r} for {item.composter_id}"
            )
        sets = ", ".join(f"{k}=?" for k in fields)
        q = f"UPDATE items SET state=?, state_changed_at=?{', ' + sets if sets else ''} WHERE id=?"
        with self.conn:
            self.conn.execute(q, (new_state, now, *fields.values(), item.id))

    # -- runs -------------------------------------------------------------

    def start_run(self, source: str | None, now: str) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO runs(started_at, source) VALUES(?, ?)", (now, source)
            )
        return cur.lastrowid

    def finish_run(self, run_id: int, now: str, ok: bool, counts: dict, notes: str | None = None) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE runs SET finished_at=?, ok=?, created=?, updated=?, unchanged=?, "
                "conflicts=?, skipped=?, errors=?, graduated=?, dismissed=?, notes=? WHERE id=?",
                (
                    now, int(ok),
                    counts.get("created", 0), counts.get("updated", 0), counts.get("unchanged", 0),
                    counts.get("conflict", 0), counts.get("skipped", 0), counts.get("error", 0),
                    counts.get("graduated", 0), counts.get("dismissed", 0), notes, run_id,
                ),
            )

    def last_successful_run(self, source: str | None = None) -> sqlite3.Row | None:
        if source:
            return self.conn.execute(
                "SELECT * FROM runs WHERE ok=1 AND source=? ORDER BY id DESC LIMIT 1", (source,)
            ).fetchone()
        return self.conn.execute(
            "SELECT * FROM runs WHERE ok=1 ORDER BY id DESC LIMIT 1"
        ).fetchone()

    def recent_runs(self, since_iso: str) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT * FROM runs WHERE started_at >= ? ORDER BY id DESC", (since_iso,)
        ))
