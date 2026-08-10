"""Load and validate config/composter.yaml into a plain object.

Everything downstream takes a Config instance; nothing else reads the
YAML file, and nothing reads environment variables.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "composter.yaml"

VALID_ON_LOCAL_EDIT = ("conflict", "graduate")


class ConfigError(RuntimeError):
    pass


@dataclass
class SourceConfig:
    name: str
    enabled: bool = False
    options: dict = field(default_factory=dict)


@dataclass
class Config:
    vault_root: Path
    managed_dir: str
    vault_id: str
    state_dir: Path
    media_dir: Path
    max_new_per_run: int
    on_local_edit: str
    dismiss_after_runs: int
    dismiss_after_seconds: int
    max_inline_mb: int
    isolation_exclude: list[str]
    sources: dict[str, SourceConfig]

    @property
    def managed_root(self) -> Path:
        return self.vault_root / self.managed_dir

    @property
    def db_path(self) -> Path:
        return self.state_dir / "composter.sqlite"

    @property
    def pending_dir(self) -> Path:
        return self.state_dir / "pending"

    @property
    def transcripts_dir(self) -> Path:
        return self.state_dir / "transcripts"

    @property
    def logs_dir(self) -> Path:
        return self.state_dir / "logs"

    @property
    def isolation_baseline_path(self) -> Path:
        return self.state_dir / "isolation_baseline.json"

    def ensure_state_dirs(self) -> None:
        for d in (self.state_dir, self.pending_dir, self.transcripts_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)


def _as_path(value: str, base: Path) -> Path:
    p = Path(value).expanduser()
    if not p.is_absolute():
        p = base / p
    return p


def load_config(path: Path | str | None = None) -> Config:
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ConfigError(f"config is not a mapping: {path}")
    return parse_config(raw, base=path.resolve().parents[0].parent)


def parse_config(raw: dict, base: Path) -> Config:
    """base is the directory relative paths (state_dir) resolve against."""
    try:
        vault = raw["vault"]
        vault_root = Path(str(vault["root"])).expanduser()
        managed_dir = str(vault["managed_dir"])
        vault_id = vault.get("vault_id")
    except KeyError as e:
        raise ConfigError(f"config missing required key: vault.{e.args[0]}") from e

    if not vault_id or not str(vault_id).strip():
        raise ConfigError("vault.vault_id must be a non-empty string")
    if "/" in managed_dir or managed_dir in ("", ".", ".."):
        raise ConfigError(f"vault.managed_dir must be a single folder name, got {managed_dir!r}")

    writer = raw.get("writer", {}) or {}
    on_local_edit = str(writer.get("on_local_edit", "conflict"))
    if on_local_edit not in VALID_ON_LOCAL_EDIT:
        raise ConfigError(
            f"writer.on_local_edit must be one of {VALID_ON_LOCAL_EDIT}, got {on_local_edit!r}"
        )

    sources = {}
    for name, sraw in (raw.get("sources", {}) or {}).items():
        sraw = sraw or {}
        opts = {k: v for k, v in sraw.items() if k != "enabled"}
        sources[name] = SourceConfig(name=name, enabled=bool(sraw.get("enabled", False)), options=opts)

    isolation = raw.get("isolation", {}) or {}

    return Config(
        vault_root=vault_root,
        managed_dir=managed_dir,
        vault_id=str(vault_id).strip(),
        state_dir=_as_path(str(raw.get("state_dir", "state")), base),
        media_dir=Path(str(raw.get("media_dir", "~/Media/composter"))).expanduser(),
        max_new_per_run=int(writer.get("max_new_per_run", 50)),
        on_local_edit=on_local_edit,
        dismiss_after_runs=int(writer.get("dismiss_after_runs", 3)),
        dismiss_after_seconds=int(writer.get("dismiss_after_seconds", 3600)),
        max_inline_mb=int(writer.get("max_inline_mb", 25)),
        isolation_exclude=list(isolation.get("exclude", []) or []),
        sources=sources,
    )
