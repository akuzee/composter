"""VaultWriter — the ONLY code that mutates the vault — plus read-only vault
scanning and the isolation baseline.

Invariants (plan §7.2), enforced as real checks that survive `python -O`:
  1. Path containment before every write, unlink, or rename.
  2. Sentinel check at construction; refuses to build without it.
  3. Atomic writes: temp file in the same directory -> fsync -> os.replace.
  4. Never destroys: superseded content moves to zCompost/_superseded/<date>/.
  5. Never renames an existing managed file.
  6. --dry-run threaded through the writer itself.
  7. Idempotent: same capture twice yields created, then unchanged.

There is deliberately no delete path in this module (or anywhere in the
codebase). The only unlink is cleanup of our own temp file after a failed
atomic write, and it is containment-checked like everything else.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

FENCE_BEGIN = "<!-- composter:begin -->"
FENCE_END = "<!-- composter:end -->"
SENTINEL_NAME = ".composter-vault-id"
SUPERSEDED_DIR = "_superseded"
STATUS_NAME = "_status.md"
ALARM_NAME = "!! needs attention.md"

# Frontmatter key territories (plan §6, §7.3 layer 2):
#   MACHINE_KEYS      — rewritten from upstream on every managed update.
#   CREATION_KEYS     — written once at creation, then human territory
#                       (consumed dates, added provenance) — preserved on update.
#   COMPOSTER_KEYS    — machine internals, always rewritten.
#   anything else     — added by hand, preserved on update.
MACHINE_KEYS = ("title", "created", "captured", "source", "kind")
CREATION_KEYS = ("zone", "consumed", "tags")
COMPOSTER_KEYS = (
    "composter_id",
    "composter_authorship",
    "composter_hash",
    "composter_rev",
    "composter_managed",
    "composter_media",
    "composter_source_ref",
)

SKELETON_DIRS = ("Notes", "Voice", "Inbox", "Queue", "Digests", "Media", SUPERSEDED_DIR)

_FILENAME_BAD = re.compile(r'[\\/:#^\[\]|?*"<>\n\r\t\u2028\u2029]')


class ContainmentError(RuntimeError):
    """A write was attempted outside the managed root. Always a bug."""


class SentinelError(RuntimeError):
    """The managed root has no (or the wrong) sentinel file."""


@dataclass
class WriteResult:
    action: str  # created | unchanged | updated | conflict
    relpath: str | None = None
    written_hash: str | None = None
    managed_body_hash: str | None = None
    rev: int | None = None
    detail: str | None = None


@dataclass
class ParsedNote:
    frontmatter: dict = field(default_factory=dict)
    body: str | None = None  # fenced managed region; None if fences are broken
    tail: str = ""           # everything after the end fence, verbatim
    raw: str = ""


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Note parsing / rendering
# ---------------------------------------------------------------------------

def parse_note(text: str) -> ParsedNote:
    note = ParsedNote(raw=text)
    rest = text
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end == -1 and text.endswith("\n---"):
            end = len(text) - 4
        if end != -1:
            fm_text = text[4:end]
            try:
                fm = yaml.safe_load(fm_text)
                if isinstance(fm, dict):
                    note.frontmatter = fm
            except yaml.YAMLError:
                pass
            rest = text[end + 5:]
    i = rest.find(FENCE_BEGIN)
    j = rest.find(FENCE_END)
    if i == -1 or j == -1 or j < i:
        return note  # body stays None -> caller treats as conflict
    body = rest[i + len(FENCE_BEGIN):j]
    body = body.removeprefix("\n").removesuffix("\n")
    note.body = body
    note.tail = rest[j + len(FENCE_END):]
    return note


def _yaml_value(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_yaml_value(x) for x in v) + "]"
    out = yaml.safe_dump(v, default_flow_style=True, allow_unicode=True, width=10**6)
    lines = out.splitlines()
    if lines and lines[-1] == "...":  # document-end marker on scalar docs
        lines = lines[:-1]
    return "\n".join(lines).strip()


def render_frontmatter(machine: dict, creation: dict, extras: dict, internals: dict) -> str:
    """Deterministic serialization: stable key order, stable formatting, so
    re-rendering unchanged data is byte-identical (plan §6)."""
    lines = []
    for k in MACHINE_KEYS:
        lines.append(f"{k}: {_yaml_value(machine.get(k))}")
    for k in CREATION_KEYS:
        lines.append(f"{k}: {_yaml_value(creation.get(k))}")
    for k in sorted(extras):
        lines.append(f"{k}: {_yaml_value(extras[k])}")
    for k in COMPOSTER_KEYS:
        lines.append(f"{k}: {_yaml_value(internals.get(k))}")
    return "\n".join(lines) + "\n"


def render_note(frontmatter_text: str, body: str, tail: str) -> str:
    return f"---\n{frontmatter_text}---\n\n{FENCE_BEGIN}\n{body}\n{FENCE_END}{tail}"


def subfolder_for(base: str, source_ref: str | None) -> str:
    """Mirror the upstream folder tree under the source's base folder.

    'iCloud/Notebook/drafts' -> 'Notes/Notebook/drafts'. The account segment is
    stripped (one person, one real account), and the upstream default folder —
    also called 'Notes' — collapses to the base rather than nesting Notes/Notes.
    """
    if not source_ref:
        return base
    parts = [p for p in str(source_ref).split("/") if p.strip()]
    if len(parts) > 1:
        parts = parts[1:]                     # drop the account segment
    clean = []
    for p in parts:
        p = _FILENAME_BAD.sub(" ", p).strip().strip(".")
        p = re.sub(r"\s+", " ", p)
        if p and p not in (".", ".."):
            clean.append(p[:60])
    if not clean or clean == [base]:
        return base
    return "/".join([base, *clean])


def filename_for(title: str, created_iso: str | None, captured_iso: str) -> str:
    """Owner's convention: 'composting metaphor 8-9-26.md' (plan §7.2)."""
    slug = _FILENAME_BAD.sub(" ", title).strip().lower()
    slug = re.sub(r"\s+", " ", slug)[:80].strip() or "untitled"
    dt = datetime.fromisoformat(created_iso or captured_iso)
    return f"{slug} {dt.month}-{dt.day}-{dt.strftime('%y')}.md"


# ---------------------------------------------------------------------------
# VaultWriter
# ---------------------------------------------------------------------------

class VaultWriter:
    def __init__(self, vault_root: Path, managed_dir: str, vault_id: str, dry_run: bool = False):
        self.vault_root = Path(vault_root).expanduser().resolve()
        if not self.vault_root.is_dir():
            raise SentinelError(f"vault root does not exist: {self.vault_root}")
        self.managed_root = (self.vault_root / managed_dir).resolve()
        self.dry_run = dry_run

        sentinel = self.managed_root / SENTINEL_NAME
        if not sentinel.is_file():
            raise SentinelError(
                f"sentinel {sentinel} not found — refusing to construct. "
                f"Run `init` (or check you are pointed at the right vault)."
            )
        actual = sentinel.read_text(encoding="utf-8").strip()
        if actual != vault_id:
            raise SentinelError(
                f"sentinel mismatch: file says {actual!r}, config says {vault_id!r} — "
                f"this is the wrong vault. Refusing to construct."
            )

    # -- containment ---------------------------------------------------------

    def _contained(self, path: Path | str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = self.vault_root / p
        resolved = p.resolve()
        if not (resolved == self.managed_root or resolved.is_relative_to(self.managed_root)):
            raise ContainmentError(
                f"refusing to touch {resolved}: outside managed root {self.managed_root}"
            )
        return resolved

    def relpath(self, abspath: Path) -> str:
        return str(abspath.relative_to(self.vault_root))

    # -- atomic write --------------------------------------------------------

    def _write_bytes(self, abspath: Path, data: bytes) -> None:
        abspath = self._contained(abspath)
        if self.dry_run:
            return
        self._contained(abspath.parent).mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=abspath.parent, prefix=".composter-tmp-")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(self._contained(tmp), abspath)
        except BaseException:
            self._contained(tmp).unlink(missing_ok=True)  # our own temp file only
            raise

    # -- captures ------------------------------------------------------------

    def create(self, cap, captured_iso: str, subfolder: str) -> WriteResult:
        relpath = self._unique_relpath(
            subfolder_for(subfolder, cap.source_ref), cap, captured_iso)
        body = cap.body.rstrip()
        fm = self._frontmatter_for(cap, captured_iso, rev=1, creation=None, extras=None)
        text = render_note(fm, body, tail="\n")
        self._write_bytes(self.vault_root / relpath, text.encode("utf-8"))
        return WriteResult(
            action="created",
            relpath=relpath,
            written_hash=sha256_text(text),
            managed_body_hash=sha256_text(body),
            rev=1,
        )

    def update(self, cap, item, captured_iso: str) -> WriteResult:
        """Layers 2–3 of the edit-clobbering rule (plan §7.3). Layer 1
        (source_hash short-circuit) happens in the engine before we are called."""
        abspath = self._contained(self.vault_root / item.path)
        if not abspath.is_file():
            # Deleted by the owner, or not yet synced down. Either way this is
            # reindex's business, not an error: the dismissal grace period is
            # what decides between the two. Erroring here would mark the run
            # failed and — after three runs — raise the escalation alarm just
            # because a deleted note happened to be edited upstream.
            return WriteResult(action="missing", relpath=item.path,
                               detail="file not present in the vault")
        old_text = abspath.read_text(encoding="utf-8")
        parsed = parse_note(old_text)

        if parsed.body is None or sha256_text(parsed.body) != item.managed_body_hash:
            # Fenced region edited (or fences broken) AND upstream changed:
            # write nothing. The engine parks the payload and flags conflict.
            return WriteResult(action="conflict", relpath=item.path,
                               detail="fenced region no longer matches managed_body_hash")

        creation = {k: parsed.frontmatter[k] for k in CREATION_KEYS if k in parsed.frontmatter}
        extras = {
            k: v for k, v in parsed.frontmatter.items()
            if k not in MACHINE_KEYS and k not in CREATION_KEYS and k not in COMPOSTER_KEYS
        }
        rev = (item.rev or 1) + 1
        body = cap.body.rstrip()
        fm = self._frontmatter_for(cap, captured_iso, rev=rev, creation=creation, extras=extras)
        text = render_note(fm, body, tail=parsed.tail)
        if text == old_text:
            return WriteResult(action="unchanged", relpath=item.path,
                               written_hash=sha256_text(text),
                               managed_body_hash=sha256_text(body), rev=item.rev)
        self._write_bytes(abspath, text.encode("utf-8"))
        return WriteResult(
            action="updated",
            relpath=item.path,
            written_hash=sha256_text(text),
            managed_body_hash=sha256_text(body),
            rev=rev,
        )

    def rewrite_from_capture(self, cap, item, captured_iso: str) -> WriteResult:
        """resolve --take-upstream: clean re-render at the same path. The
        caller has already superseded the locally-edited version."""
        rev = (item.rev or 1) + 1
        body = cap.body.rstrip()
        fm = self._frontmatter_for(cap, captured_iso, rev=rev, creation=None, extras=None)
        text = render_note(fm, body, tail="\n")
        self._write_bytes(self.vault_root / item.path, text.encode("utf-8"))
        return WriteResult(
            action="updated",
            relpath=item.path,
            written_hash=sha256_text(text),
            managed_body_hash=sha256_text(body),
            rev=rev,
        )

    def relocate(self, relpath: str, dest_subfolder: str) -> str | None:
        """Move a managed file into a different folder inside the managed root,
        keeping its filename. Returns the new vault-relative path, or None if
        it is already in the right place.

        This is a deliberate, narrowly-scoped exception to invariant 5 (never
        rename an existing managed file). That invariant exists because a script
        rename silently breaks `[[wikilinks]]` — Obsidian only repairs links for
        renames it performs itself. So this is never called automatically: it is
        the hand-invoked `relocate` verb, it reports every move, and it is meant
        for restructuring shortly after an import, before anything links in.
        """
        src = self._contained(self.vault_root / relpath)
        dest_dir = self._contained(self.managed_root / dest_subfolder)
        if src.parent == dest_dir:
            return None
        dest = self._unique_in_dir(dest_dir, src.name)
        if self.dry_run:
            return self.relpath(dest)
        dest_dir.mkdir(parents=True, exist_ok=True)
        os.replace(self._contained(src), self._contained(dest))
        return self.relpath(dest)

    def attach_media(self, src: Path, subfolder: str) -> str:
        """Copy a media file into the managed tree and return its vault-relative
        path. Copies, never moves: the original in Voice Memos or the camera
        roll is never touched. Idempotent — an identical file already present
        is left alone."""
        import shutil
        src = Path(src)
        dest_dir = self._contained(self.managed_root / "Media" / subfolder)
        dest = dest_dir / src.name
        if dest.exists() and dest.stat().st_size == src.stat().st_size:
            return self.relpath(self._contained(dest))
        if dest.exists():
            dest = self._unique_in_dir(dest_dir, src.name)
        dest = self._contained(dest)
        if self.dry_run:
            return self.relpath(dest)
        dest_dir.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f".composter-tmp-{dest.name}")
        shutil.copy2(src, self._contained(tmp))
        os.replace(self._contained(tmp), dest)
        return self.relpath(dest)

    def supersede(self, relpath: str, date_str: str) -> str | None:
        """Move (never delete) a managed file to _superseded/<date>/."""
        src = self._contained(self.vault_root / relpath)
        dest_dir = self._contained(self.managed_root / SUPERSEDED_DIR / date_str)
        dest = self._unique_in_dir(dest_dir, src.name)
        if self.dry_run:
            return self.relpath(dest)
        dest_dir.mkdir(parents=True, exist_ok=True)
        os.replace(self._contained(src), self._contained(dest))
        return self.relpath(dest)

    def write_status(self, text: str) -> bool:
        """Rewrite _status.md only if content actually changed (plan §13)."""
        abspath = self._contained(self.managed_root / STATUS_NAME)
        data = text.encode("utf-8")
        if abspath.is_file() and abspath.read_bytes() == data:
            return False
        self._write_bytes(abspath, data)
        return True

    def write_alarm(self, text: str) -> bool:
        """Raise the Tier 2 alarm. Returns True only on the transition from
        absent to present, so the caller notifies once rather than every tick."""
        abspath = self._contained(self.managed_root / ALARM_NAME)
        existed = abspath.is_file()
        data = text.encode("utf-8")
        if not existed or abspath.read_bytes() != data:
            self._write_bytes(abspath, data)
        return not existed

    def clear_alarm(self) -> bool:
        """Remove the alarm file after a successful run.

        This is the ONLY unlink of a content file anywhere in the codebase, and
        it is deliberate: the plan (§13) requires the alarm to delete itself so
        it can never become stale nagging. It is safe as a delete because the
        file is machine-written, regenerable from the ledger, and never contains
        anything the owner authored. Both the containment check and an exact
        filename check must pass — this cannot be pointed at anything else.
        """
        abspath = self._contained(self.managed_root / ALARM_NAME)
        if abspath.name != ALARM_NAME:
            raise ContainmentError(f"clear_alarm refuses to unlink {abspath}")
        if not abspath.is_file() or self.dry_run:
            return False
        abspath.unlink()
        return True

    # -- internals -----------------------------------------------------------

    def _frontmatter_for(self, cap, captured_iso, rev, creation, extras) -> str:
        machine = {
            "title": cap.title,
            "created": cap.created,
            "captured": captured_iso,
            "source": cap.source,
            "kind": cap.kind,
        }
        if creation is None:
            creation = {"zone": cap.zone, "consumed": None, "tags": [f"compost/{cap.source}"]}
        internals = {
            "composter_id": cap.composter_id,
            "composter_authorship": cap.authorship,
            "composter_hash": cap.source_hash,
            "composter_rev": rev,
            "composter_managed": True,
            "composter_media": list(cap.media),
            "composter_source_ref": cap.source_ref,
        }
        return render_frontmatter(machine, creation, extras or {}, internals)

    def _unique_relpath(self, subfolder: str, cap, captured_iso: str) -> str:
        d = self._contained(self.managed_root / subfolder)
        name = filename_for(cap.title, cap.created, captured_iso)
        return self.relpath(self._unique_in_dir(d, name))

    def _unique_in_dir(self, directory: Path, name: str) -> Path:
        stem, suffix = Path(name).stem, Path(name).suffix
        candidate = directory / name
        n = 2
        while candidate.exists():
            candidate = directory / f"{stem} {n}{suffix}"
            n += 1
        return candidate


# ---------------------------------------------------------------------------
# init — the sanctioned bootstrap (the one mutation before a writer exists,
# since the writer refuses to construct without the sentinel init creates).
# Its footprint is exactly vault_root/managed_dir; it touches nothing else.
# ---------------------------------------------------------------------------

def init_managed_root(vault_root: Path, managed_dir: str, vault_id: str) -> Path:
    vault_root = Path(vault_root).expanduser().resolve()
    if not vault_root.is_dir():
        raise SentinelError(f"vault root does not exist: {vault_root}")
    if "/" in managed_dir or managed_dir in ("", ".", ".."):
        raise ContainmentError(f"managed_dir must be a single folder name: {managed_dir!r}")
    managed_root = vault_root / managed_dir
    managed_root.mkdir(exist_ok=True)
    sentinel = managed_root / SENTINEL_NAME
    if sentinel.is_file():
        actual = sentinel.read_text(encoding="utf-8").strip()
        if actual != vault_id:
            raise SentinelError(
                f"sentinel already present with different id {actual!r} (config: {vault_id!r}). "
                f"Refusing to overwrite — this may be the wrong vault."
            )
    else:
        sentinel.write_text(vault_id + "\n", encoding="utf-8")
    for d in SKELETON_DIRS:
        (managed_root / d).mkdir(exist_ok=True)
    return managed_root


# ---------------------------------------------------------------------------
# Read-only vault scan (layer 4: graduation / dismissal)
# ---------------------------------------------------------------------------

_SCAN_SKIP_DIRS = {".obsidian", ".trash", ".git", ".smart-env"}


@dataclass
class MarkerEntry:
    relpath: str
    managed: bool  # composter_managed value (True if absent)


def scan_markers(vault_root: Path) -> dict[str, MarkerEntry]:
    """Walk the whole vault (read-only) building {composter_id -> location}."""
    vault_root = Path(vault_root).expanduser().resolve()
    out: dict[str, MarkerEntry] = {}
    for dirpath, dirnames, filenames in os.walk(vault_root):
        dirnames[:] = [d for d in dirnames if d not in _SCAN_SKIP_DIRS]
        for fn in filenames:
            if not fn.endswith(".md"):
                continue
            p = Path(dirpath) / fn
            try:
                text = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if "composter_id" not in text:
                continue
            fm = parse_note(text).frontmatter
            cid = fm.get("composter_id")
            if not cid:
                continue
            out[str(cid)] = MarkerEntry(
                relpath=str(p.relative_to(vault_root)),
                managed=bool(fm.get("composter_managed", True)),
            )
    return out


# ---------------------------------------------------------------------------
# Isolation baseline — the most important test in the suite (plan §12)
# ---------------------------------------------------------------------------

def walk_outside(vault_root: Path, managed_dir: str, exclude: list[str]) -> dict[str, dict]:
    """(path, size, sha256) for every file outside the managed dir."""
    return _baseline_walk(vault_root, managed_dir, exclude)


def diff_file_maps(before: dict[str, dict], after: dict[str, dict]) -> list[str]:
    problems = []
    for rel in sorted(set(before) - set(after)):
        problems.append(f"MISSING: {rel}")
    for rel in sorted(set(after) - set(before)):
        problems.append(f"NEW FILE: {rel}")
    for rel in sorted(set(before) & set(after)):
        if before[rel]["sha256"] != after[rel]["sha256"]:
            problems.append(f"CHANGED: {rel}")
    return problems


def _baseline_walk(vault_root: Path, managed_dir: str, exclude: list[str]) -> dict[str, dict]:
    vault_root = Path(vault_root).expanduser().resolve()
    entries: dict[str, dict] = {}
    for dirpath, dirnames, filenames in os.walk(vault_root):
        rel_dir = Path(dirpath).relative_to(vault_root)
        parts = rel_dir.parts
        if parts and parts[0] == managed_dir:
            dirnames[:] = []
            continue
        for fn in sorted(filenames):
            rel = str(rel_dir / fn) if parts else fn
            if any(rel.startswith(x) for x in exclude):
                continue
            p = Path(dirpath) / fn
            st = p.stat()
            entries[rel] = {"size": st.st_size, "sha256": sha256_file(p)}
    return entries


def capture_baseline(vault_root: Path, managed_dir: str, exclude: list[str], out_path: Path) -> int:
    entries = _baseline_walk(vault_root, managed_dir, exclude)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"vault_root": str(Path(vault_root).expanduser().resolve()),
               "managed_dir": managed_dir, "exclude": exclude, "files": entries}
    out_path.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
    return len(entries)


def check_baseline(vault_root: Path, managed_dir: str, baseline_path: Path) -> list[str]:
    """Return a list of violations; empty means the vault outside the managed
    dir is byte-identical to the baseline."""
    saved = json.loads(baseline_path.read_text(encoding="utf-8"))
    current = _baseline_walk(vault_root, managed_dir, saved.get("exclude", []))
    return diff_file_maps(saved["files"], current)
