from fdp.extract import fetch_synthetic

def test_fetch_synthetic_shape():
    df = fetch_synthetic(days=10)
    assert {"date","open","close"}.issubset(df.columns)
    assert len(df) == 10
