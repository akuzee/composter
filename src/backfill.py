"""Phase 6: add frontmatter to the notes that were here before composter.

**This is the one place the system writes outside the managed folder**, and the
only sanctioned exception to the isolation rule. It is hand-invoked, never
scheduled, and never a side effect of anything else.

Six safeguards, all required (plan §11):

1. An external snapshot before a single byte is written, verified by file count
   and total size. This is the rollback and it must exist first.
2. Frontmatter only. The prose below it is asserted byte-identical before and
   after; any difference aborts that file.
3. Propose, review, apply as three separate commands. `propose` writes a TSV
   with the inferred values and the evidence for each, and writes nothing else.
   A human edits that TSV. `apply` reads only the TSV and never re-infers.
4. `apply --dry-run` prints a unified diff of every file it would change.
5. Batched and resumable, so it can be stopped and inspected without leaving
   the vault half-converted.
6. `undo` restores from the snapshot.

A file whose date cannot be established gets **no `created` key at all**. An
absent field is honest; a wrong one silently corrupts every timeline view.
"""

from __future__ import annotations

import csv
import difflib
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import Config
from .vault import parse_note, sha256_file

SNAPSHOT_ROOT = Path.home() / "Backups"
TSV_NAME = "backfill_proposal.tsv"
SKIP_DIRS = {".obsidian", ".trash", ".smart-env", ".git"}

# "notes 8-4-26", "11-28-25", "9-22 crumb", "interests dump 12-4"
_DATE_TAIL = re.compile(r"(\d{1,2})[-.](\d{1,2})(?:[-.](\d{2,4}))?\s*$")
_DATE_HEAD = re.compile(r"^(\d{1,2})[-.](\d{1,2})(?:[-.](\d{2,4}))?\b")

THEIRS_DIRS = {"Clippings", "zClippings"}


@dataclass
class Proposal:
    relpath: str
    created: str          # "" means: write no created key
    kind: str
    authorship: str
    evidence: str
    confidence: str       # high | medium | low
    note: str


def _norm_year(y: str | None, fallback: int) -> int | None:
    if not y:
        return None
    n = int(y)
    if n < 100:
        n += 2000
    return n if 1990 <= n <= 2100 else None


def infer_date(path: Path, stem: str) -> tuple[str, str, str]:
    """-> (iso_or_empty, evidence, confidence).

    Filename beats the filesystem: the owner wrote the date deliberately. But
    `3-9-26` could be March 9th or September 3rd, and `12-4` omits the year —
    those are flagged rather than guessed at.
    """
    st = path.stat()
    birth = getattr(st, "st_birthtime", None) or st.st_mtime
    bdt = datetime.fromtimestamp(birth).astimezone()

    for pat, where in ((_DATE_TAIL, "filename tail"), (_DATE_HEAD, "filename head")):
        m = pat.search(stem) if pat is _DATE_TAIL else pat.match(stem)
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        year = _norm_year(m.group(3), bdt.year)
        if not (1 <= a <= 12 and 1 <= b <= 31):
            continue
        ambiguous = a <= 12 and b <= 12          # M-D or D-M, unknowable
        if year is None:
            year = bdt.year
            conf, ev = "low", f"{where} {m.group(0).strip()}, year from birthtime"
        elif ambiguous:
            conf, ev = "medium", f"{where} {m.group(0).strip()}, read as M-D-Y"
        else:
            conf, ev = "high", f"{where} {m.group(0).strip()}"
        try:
            dt = datetime(year, a, b, 12, 0).astimezone()
        except ValueError:
            continue
        # A filename date wildly at odds with the file's own birthtime is more
        # likely a misread than a note written years before it existed.
        if abs((dt - bdt).days) > 400:
            return (dt.isoformat(timespec="seconds"), ev + " (DISAGREES with birthtime "
                    f"{bdt:%Y-%m-%d})", "low")
        return dt.isoformat(timespec="seconds"), ev, conf

    return bdt.isoformat(timespec="seconds"), "filesystem birthtime", "medium"


def infer_kind_and_authorship(relpath: Path, text: str) -> tuple[str, str]:
    top = relpath.parts[0] if len(relpath.parts) > 1 else ""
    if top in THEIRS_DIRS or "Clippings" in relpath.parts:
        return "clipping", "theirs"
    if re.search(r"^\s*(source|author|published):", text[:600], re.M | re.I):
        return "clipping", "theirs"
    return "note", "mine"


def candidates(cfg: Config) -> list[Path]:
    out = []
    for p in sorted(cfg.vault_root.rglob("*.md")):
        rel = p.relative_to(cfg.vault_root)
        if rel.parts[0] in SKIP_DIRS or rel.parts[0] == cfg.managed_dir:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if parse_note(text).frontmatter.get("created"):
            continue
        out.append(p)
    return out


def propose(cfg: Config, out_path: Path) -> list[Proposal]:
    rows = []
    for p in candidates(cfg):
        rel = p.relative_to(cfg.vault_root)
        text = p.read_text(encoding="utf-8", errors="replace")
        created, evidence, conf = infer_date(p, p.stem)
        kind, authorship = infer_kind_and_authorship(rel, text)
        rows.append(Proposal(str(rel), created, kind, authorship, evidence, conf, ""))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["relpath", "created", "kind", "authorship",
                    "evidence", "confidence", "note"])
        for r in rows:
            w.writerow([r.relpath, r.created, r.kind, r.authorship,
                        r.evidence, r.confidence, r.note])
    return rows


def read_proposal(path: Path) -> list[Proposal]:
    with open(path, newline="", encoding="utf-8") as f:
        return [Proposal(r["relpath"], r["created"].strip(), r["kind"].strip(),
                         r["authorship"].strip(), r.get("evidence", ""),
                         r.get("confidence", ""), r.get("note", ""))
                for r in csv.DictReader(f, delimiter="\t")]


# -- snapshot ------------------------------------------------------------------

def snapshot(cfg: Config) -> tuple[Path, int, int]:
    """Copy the whole vault outside itself. Verified before anything is written."""
    dest = SNAPSHOT_ROOT / f"vault-pre-backfill-{datetime.now():%Y-%m-%d-%H%M%S}"
    if dest.exists():
        raise RuntimeError(f"snapshot already exists: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(cfg.vault_root, dest, symlinks=True,
                    ignore=shutil.ignore_patterns(".smart-env"))
    files = [p for p in dest.rglob("*") if p.is_file()]
    return dest, len(files), sum(p.stat().st_size for p in files)


def verify_snapshot(cfg: Config, snap: Path) -> list[str]:
    """Every markdown file we might touch must be present and identical."""
    problems = []
    for p in candidates(cfg):
        rel = p.relative_to(cfg.vault_root)
        mirror = snap / rel
        if not mirror.is_file():
            problems.append(f"MISSING FROM SNAPSHOT: {rel}")
        elif sha256_file(mirror) != sha256_file(p):
            problems.append(f"SNAPSHOT DIFFERS: {rel}")
    return problems


# -- apply ---------------------------------------------------------------------

def render_frontmatter(p: Proposal, captured: str) -> str:
    lines = ["---"]
    if p.created:
        lines.append(f"created: '{p.created}'")
    lines += [
        f"kind: {p.kind}",
        f"composter_authorship: {p.authorship}",
        "composter_managed: false",
        f"composter_backfilled: '{captured}'",
        "---",
        "",
    ]
    return "\n".join(lines)


def apply_one(path: Path, p: Proposal, captured: str) -> tuple[str, str]:
    """-> (before, after). Raises if the prose would change."""
    before = path.read_text(encoding="utf-8")
    existing = parse_note(before).frontmatter
    if existing:
        raise ValueError("file already has frontmatter; merging is not implemented")
    after = render_frontmatter(p, captured) + before
    # Safeguard 2: the prose is untouched, byte for byte.
    if not after.endswith(before) or after[len(after) - len(before):] != before:
        raise AssertionError(f"prose would change in {path}")
    return before, after
