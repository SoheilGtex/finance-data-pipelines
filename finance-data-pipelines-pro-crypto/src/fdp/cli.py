from __future__ import annotations

import click
from rich.console import Console

from .config import load_yaml_config, Settings, ROOT
from .utils.io import ensure_dirs
from .utils.logging import setup_logging
from .extract import fetch_synthetic, fetch_coingecko_prices, save_raw
from .transform import transform_prices
from .load import load_to_sql

console = Console()

@click.group()
def cli():
    "Finance Data Pipelines CLI"
    pass

@cli.command(help="Run extract step")
@click.option("--source", type=click.Choice(["coingecko", "synthetic"]), default=None)
@click.option("--coin-id", type=str, default=None, help="CoinGecko coin id (e.g., bitcoin)")
@click.option("--vs", type=str, default=None, help="vs_currency (e.g., usd, eur)")
@click.option("--days", type=int, default=None, help="number of days to fetch/generate")
def extract(source: str | None, coin_id: str | None, vs: str | None, days: int | None):
    log = setup_logging()
    ensure_dirs()
    cfg = load_yaml_config(ROOT / "config.yaml")
    src = source or cfg.get("source", "coingecko")
    if src == "coingecko":
        c = cfg.get("coingecko", {})
        coin = coin_id or c.get("coin_id", "bitcoin")
        cur = vs or c.get("vs_currency", "usd")
        d = int(days or c.get("days", 30))
        console.print(f"[bold]CoinGecko[/]: coin_id={coin}, vs={cur}, days={d}")
        df = fetch_coingecko_prices(coin_id=coin, vs_currency=cur, days=d)
    else:
        d = int(days or cfg.get("coingecko", {}).get("days", 30))
        console.print(f"[bold]Synthetic[/]: days={d}")
        df = fetch_synthetic(days=d)

    out = save_raw(df)
    console.print(f"[bold green]Extract OK[/] → {out}")

@cli.command(help="Run transform step")
def transform():
    ensure_dirs()
    out = transform_prices()
    console.print(f"[bold green]Transform OK[/] → {out}")

@cli.command(help="Run load step")
@click.option("--table", type=str, default=None, help="Override table name (else from config.yaml)")
def load(table: str | None):
    cfg = load_yaml_config(ROOT / "config.yaml")
    tbl = table or cfg.get("table", {}).get("name", "prices")
    url, tbl = load_to_sql(table=tbl)
    console.print(f"[bold green]Load OK[/] → {url}.{tbl}")

@cli.command(help="Run all steps: extract → transform → load")
def run_all():
    extract.main(standalone_mode=False)  # type: ignore
    transform.main(standalone_mode=False)  # type: ignore
    load.main(standalone_mode=False)  # type: ignore

if __name__ == "__main__":
    cli()
