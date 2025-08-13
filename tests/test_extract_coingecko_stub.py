import pandas as pd
from fdp.extract import fetch_coingecko_prices

class DummyResp:
    status_code = 200
    def __init__(self, data):
        self._data = data
    def json(self):
        return self._data

def test_coingecko_parser(monkeypatch):
    # Stub requests.get to avoid network
    def fake_get(url, params=None, timeout=10):
        data = {
            "prices": [
                [1704067200000, 42000.0],
                [1704153600000, 43000.0],
                [1704240000000, 41000.0],
            ]
        }
        return DummyResp(data)
    import fdp.extract as ex
    monkeypatch.setattr(ex.requests, "get", fake_get)

    df = fetch_coingecko_prices("bitcoin", "usd", days=3)
    assert set(df.columns) == {"date","open","close"}
    assert len(df) == 3
