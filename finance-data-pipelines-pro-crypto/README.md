# Finance Data Pipelines — Pro (with Real Extractor)

A professional, interview-ready Python ETL template for **financial data** (stocks/indices/crypto).  
Includes **real data extraction via CoinGecko** (no API key), CLI, config, tests, CI, and Docker.

## Quickstart

### 1) Setup (Windows)
```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
copy .env.sample .env
python -m fdp.cli run-all
```

### 1) Setup (macOS/Linux)
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.sample .env
python -m fdp.cli run-all
```

### 2) Switch data source
Edit `config.yaml`:
```yaml
source: coingecko   # options: coingecko | synthetic
coingecko:
  coin_id: bitcoin
  vs_currency: usd
  days: 30

table:
  name: prices
```
- `coingecko` uses the public API (no key).  
- `synthetic` generates demo data (offline; always works).

### 3) Outputs
- `data/raw/prices_raw.parquet`
- `data/clean/prices_clean.parquet`
- `warehouse.db` (SQLite) → table: `prices`

## CLI Examples
```bash
python -m fdp.cli extract --source coingecko --coin-id bitcoin --vs usd --days 30
python -m fdp.cli extract --source synthetic --days 60
python -m fdp.cli transform
python -m fdp.cli load --table prices
python -m fdp.cli run-all
```

## Project Layout
```
src/fdp/
  cli.py          # click-based CLI (with flags)
  config.py       # Pydantic settings + YAML config
  extract.py      # real extractor (CoinGecko) + synthetic fallback
  transform.py    # cleaning + returns
  load.py         # SQLAlchemy load into SQLite
  utils/
    io.py
    logging.py
tests/
  test_flow.py
  test_extract_synthetic.py
  test_extract_coingecko_stub.py
.github/workflows/python-ci.yml
.pre-commit-config.yaml
pyproject.toml
requirements.txt
requirements-dev.txt
Makefile
Dockerfile
.env.sample
config.yaml
LICENSE
README.md
docs/DATA_SOURCES.md
```

> Tip: Replace the CoinGecko extractor with your preferred exchange/stock API if needed,  
and keep credentials in `.env` (never commit secrets).
