"""Installed command-line interface for the offline correctness baseline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from . import __version__
from .config import ConfigurationError, load_yaml_config
from .load import AtomicReplaceError
from .oracle import OracleError
from .pipeline import run_synthetic_baseline
from .validation import ValidationError


def _integer_setting(
    name: str, cli_value: int | None, config: dict[str, Any], default: int, *, minimum: int
) -> int:
    value = cli_value if cli_value is not None else config.get(name, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ConfigurationError(f"{name} must be an integer >= {minimum}")
    return value


@click.group()
@click.version_option(version=__version__)
def cli() -> None:
    """Finance Data Pipelines correctness-first CLI."""


@cli.command("run-all")
@click.option(
    "--source",
    type=click.Choice(["synthetic"], case_sensitive=False),
    default=None,
    help="Offline source. Phase 3D supports synthetic only.",
)
@click.option("--seed", type=int, default=None, help="Nonnegative deterministic seed.")
@click.option("--rows", type=int, default=None, help="Exact number of rows to generate.")
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path, file_okay=False),
    required=True,
    help="Directory that will contain every generated artifact.",
)
@click.option(
    "--db-path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="Optional SQLite path; defaults to OUTPUT_DIR/warehouse.db.",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=None,
    help="Optional YAML file with source, seed, and rows.",
)
def run_all(
    source: str | None,
    seed: int | None,
    rows: int | None,
    output_dir: Path,
    db_path: Path | None,
    config_path: Path | None,
) -> None:
    """Generate, normalize, atomically load, and verify an offline snapshot."""

    try:
        config = load_yaml_config(config_path)
        resolved_source = (source or config.get("source", "synthetic")).lower()
        if resolved_source != "synthetic":
            raise ConfigurationError("source must be 'synthetic' in Phase 3D")
        resolved_seed = _integer_setting("seed", seed, config, 20270916, minimum=0)
        resolved_rows = _integer_setting("rows", rows, config, 1000, minimum=1)
        result = run_synthetic_baseline(
            seed=resolved_seed,
            rows=resolved_rows,
            output_dir=output_dir,
            database_path=db_path,
        )
    except (
        AtomicReplaceError,
        ConfigurationError,
        ValidationError,
        OracleError,
        OSError,
        ValueError,
    ) as exc:
        raise click.ClickException(str(exc)) from exc

    output = {
        "output_dir": str(result.artifacts.output_dir),
        "database": str(result.artifacts.database),
        "manifest": str(result.artifacts.manifest),
        "correctness": str(result.artifacts.correctness),
        **result.correctness,
    }
    click.echo(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    cli()
