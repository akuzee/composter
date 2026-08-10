"""status — recompute and rewrite zCompost/_status.md, print JSON.

Tier 1 of failure surfacing (plan §13): a boring file that is right there
when Obsidian is open. Rewritten only when its content actually changed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .config import Config
from .db import DB
from .vault import VaultWriter


def _now() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def build_payload(cfg: Config, db: DB, now: datetime | None = None) -> dict:
    now = now or _now()
    last = db.last_successful_run()
    per_source = {}
    for name in cfg.sources:
        r = db.last_successful_run(name)
        per_source[name] = dict(r) if r else None
    day_ago = (now - timedelta(hours=24)).isoformat(timespec="seconds")
    recent = [dict(r) for r in db.recent_runs(day_ago)]
    conflicts = [
        {"composter_id": i.composter_id, "title": i.title, "path": i.path}
        for i in db.items_in_state("conflict")
    ]
    return {
        "generated_note": "elapsed times are computed at read time by `status`, not stored",
        "now": now.isoformat(timespec="seconds"),
        "last_successful_run": dict(last) if last else None,
        "elapsed_since_success_seconds": (
            (now - datetime.fromisoformat(last["finished_at"])).total_seconds()
            if last and last["finished_at"] else None
        ),
        "per_source": per_source,
        "counts_by_state": db.counts_by_state(),
        "runs_last_24h": recent,
        "conflicts": conflicts,
    }


def render_status_md(payload: dict) -> str:
    lines = ["# Composter status", ""]
    last = payload["last_successful_run"]
    if last:
        lines.append(f"Last successful run: **{last['finished_at']}** (source: {last['source'] or 'all'})")
    else:
        lines.append("Last successful run: **never**")
    lines.append("")

    lines.append("## Items")
    counts = payload["counts_by_state"]
    if counts:
        for state in ("managed", "conflict", "graduated", "dismissed", "skipped", "error"):
            if counts.get(state):
                lines.append(f"- {state}: {counts[state]}")
    else:
        lines.append("- nothing captured yet")
    lines.append("")

    runs = payload["runs_last_24h"]
    lines.append("## Last 24h")
    if runs:
        for r in runs[:10]:
            lines.append(
                f"- {r['started_at']} `{r['source'] or 'all'}` "
                f"{'ok' if r['ok'] else 'FAILED'} — "
                f"+{r['created']} new, {r['updated']} updated, {r['unchanged']} unchanged"
                + (f", {r['conflicts']} conflicts" if r["conflicts"] else "")
            )
    else:
        lines.append("- no runs")
    lines.append("")

    conflicts = payload["conflicts"]
    if conflicts:
        lines.append("## Waiting on you")
        for c in conflicts:
            link = c["path"].removesuffix(".md") if c["path"] else c["composter_id"]
            lines.append(
                f"- [[{link}]] — edited locally while upstream changed. "
                f"`resolve --id \"{c['composter_id']}\" --take-upstream | --keep-mine`"
            )
        lines.append("")

    return "\n".join(lines) + "\n"


def write_status(cfg: Config, db: DB, now: datetime | None = None) -> dict:
    payload = build_payload(cfg, db, now)
    writer = VaultWriter(cfg.vault_root, cfg.managed_dir, cfg.vault_id)
    payload["status_file_rewritten"] = writer.write_status(render_status_md(payload))
    return payload
