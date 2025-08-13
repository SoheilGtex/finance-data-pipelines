from __future__ import annotations

from pathlib import Path
import pandas as pd

from .config import RAW_DIR, CLEAN_DIR

def transform_prices(in_name: str = "prices_raw.parquet", out_name: str = "prices_clean.parquet") -> Path:
    src = RAW_DIR / in_name
    df = pd.read_parquet(src)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").drop_duplicates(subset=["date"]).reset_index(drop=True)
    df["return"] = df["close"].pct_change().fillna(0.0)
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    dst = CLEAN_DIR / out_name
    df.to_parquet(dst, index=False)
    return dst
