from __future__ import annotations

from pathlib import Path
import pandas as pd
from sqlalchemy import create_engine, text

from .config import Settings, CLEAN_DIR

def load_to_sql(in_name: str = "prices_clean.parquet", db_url: str | None = None, table: str = "prices"):
    settings = Settings()
    url = db_url or settings.APP_DB_URL
    df = pd.read_parquet(CLEAN_DIR / in_name)
    engine = create_engine(url, future=True)
    with engine.begin() as conn:
        df.to_sql(table, conn, if_exists="replace", index=False)
        try:
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_{table}_date ON {table}(date)"))
        except Exception:
            pass
    return url, table
