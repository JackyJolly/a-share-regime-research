import numpy as np
import pandas as pd
import pytest
from regime_research.data import validate_prices, fetch_ricequant
from regime_research.datasets import synthetic_bundle, verify_manifest


@pytest.mark.parametrize("case", ["duplicate", "reverse", "nan", "negative", "bounds"])
def test_reject_bad_prices(prices, case):
    p = prices.copy()
    if case == "duplicate": p = pd.concat([p, p.iloc[[-1]]])
    if case == "reverse": p = p.iloc[::-1]
    if case == "nan": p.iloc[10, 0] = np.nan
    if case == "negative": p.iloc[10, 3] = -1
    if case == "bounds": p.iloc[10, 1] = 1
    with pytest.raises(ValueError): validate_prices(p)


def test_ricequant_sdk_contract(prices):
    sample = prices.iloc[:10]
    class Client:
        def get_price(self, instrument, **kwargs):
            assert instrument == "000985.XSHG"
            assert kwargs["frequency"] == "1d" and kwargs["adjust_type"] == "none"
            assert kwargs["expect_df"] is True
            return pd.concat({instrument: sample}, names=["order_book_id"])
        def get_trading_dates(self, start, end): return list(sample.index.date)
    result = fetch_ricequant("000985.XSHG", "2015-01-01", "2015-01-14", Client())
    pd.testing.assert_frame_equal(result, sample, check_freq=False)


def test_calendar_mismatch_rejected(prices):
    class Client:
        def get_price(self, *a, **k): return prices.iloc[:10]
        def get_trading_dates(self, *a): return list(prices.index[:11].date)
    with pytest.raises(ValueError, match="calendar"):
        fetch_ricequant("000985.XSHG", "2015-01-01", "2015-01-14", Client())


def test_manifest_tampering_and_overwrite(tmp_path):
    directory = synthetic_bundle(tmp_path/"data", periods=300)
    assert verify_manifest(directory)["is_synthetic"]
    with pytest.raises(ValueError, match="overwrite"):
        synthetic_bundle(directory, periods=300)
    with open(directory/"prices.csv", "a") as f: f.write("\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_manifest(directory)
