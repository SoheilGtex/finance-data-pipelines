"""Runtime configuration with no dependency on the source checkout."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigurationError(ValueError):
    """Raised when a configuration file is malformed or unsupported."""


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    """All generated files live below a caller-selected output directory."""

    output_dir: Path
    raw_dir: Path
    normalized_dir: Path
    database_path: Path
    manifest_path: Path
    correctness_path: Path

    @classmethod
    def from_output_dir(
        cls, output_dir: Path | str, database_path: Path | str | None = None
    ) -> RuntimePaths:
        root = Path(output_dir).expanduser().resolve()
        db_path = (
            Path(database_path).expanduser().resolve()
            if database_path is not None
            else root / "warehouse.db"
        )
        return cls(
            output_dir=root,
            raw_dir=root / "raw",
            normalized_dir=root / "normalized",
            database_path=db_path,
            manifest_path=root / "dataset_manifest.json",
            correctness_path=root / "correctness.json",
        )


def load_yaml_config(path: Path | str | None) -> dict[str, Any]:
    """Load an optional YAML mapping without assuming a repository location."""

    if path is None:
        return {}
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise ConfigurationError(f"Configuration file does not exist: {config_path}")
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Invalid YAML in configuration file: {config_path}") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigurationError("Configuration root must be a mapping.")
    allowed = {"source", "seed", "rows"}
    unexpected = sorted(set(loaded) - allowed)
    if unexpected:
        raise ConfigurationError(f"Unsupported configuration keys: {', '.join(unexpected)}")
    return loaded
