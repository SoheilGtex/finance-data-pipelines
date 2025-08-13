from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from .config import RAW_DIR

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

def _request_json(url: str, params: dict, retries: int = 3, backoff: float = 1.2) -> dict:
    # Simple GET with retries to handle transient errors/rate-limits.
    last_exc: Optional[Exception] = None
    for i in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=20)
            if resp.status_code == 200:
                return resp.json()
            # Backoff on non-200 (e.g., 429/5xx)
            time.sleep(backoff * (i + 1))
        except Exception as e:
            last_exc = e
            time.sleep(backoff * (i + 1))
    if last_exc:
        raise last_exc
    raise RuntimeError(f"Failed to fetch {url} after {retries} retries.")

def fetch_coingecko_prices(coin_id: str, vs_currency: str = "usd", days: int = 30) -> pd.DataFrame:
    """
    Fetch OHLC-like prices from CoinGecko market_chart (prices only).
    Returns a DataFrame with columns: date, open, close
    (approximate open/close derived from available 'prices' series).
    """
    url = f"{COINGECKO_BASE}/coins/{coin_id}/market_chart"
    js = _request_json(url, {"vs_currency": vs_currency, "days": days})
    prices = js.get("prices", [])
    if not prices:
        raise ValueError("Empty prices from CoinGecko.")
    # prices: [[timestamp_ms, price], ...]
    df = pd.DataFrame(prices, columns=["ts", "price"])
    df["date"] = pd.to_datetime(df["ts"], unit="ms").dt.date
    # aggregate to daily open/close
    grp = df.groupby("date")["price"]
    daily = pd.DataFrame({
        "open": grp.first(),
        "close": grp.last()
    }).reset_index()
    return daily

def fetch_synthetic(days: int = 30) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=days, freq="D")
    df = pd.DataFrame({
        "date": idx.date,
        "open": 100 + (pd.Series(range(days)) * 0.5),
        "close": 100 + (pd.Series(range(days)) * 0.5).shift(1).fillna(100)
    })
    return df

def save_raw(df: pd.DataFrame, name: str = "prices_raw.parquet") -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out = RAW_DIR / name
    df.to_parquet(out, index=False)
    return out
