from pathlib import Path
import sqlite3

from fdp.extract import fetch_synthetic, save_raw
from fdp.transform import transform_prices
from fdp.load import load_to_sql

def test_end_to_end():
    # Use synthetic to avoid network in CI
    df = fetch_synthetic(days=5)
    out_raw = save_raw(df)
    assert out_raw.exists()

    out_clean = transform_prices()
    assert out_clean.exists()

    url, table = load_to_sql()
    assert Path("warehouse.db").exists()
    conn = sqlite3.connect("warehouse.db")
    cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
    n = cur.fetchone()[0]
    assert n > 0
    conn.close()
