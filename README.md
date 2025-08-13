# Finance Data Pipelines (Starter)

Python + SQL starter for building ETL pipelines on financial datasets (stocks/indices).

## Quickstart
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q
python -m src.etl.extract
python -m src.etl.transform
python -m src.etl.load
