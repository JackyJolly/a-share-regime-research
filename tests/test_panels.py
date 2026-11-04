import numpy as np
import pandas as pd
import pytest
from regime_research.panels import industry_features, breadth_features


def test_negative_contributions_not_fabricated():
    dates = pd.bdate_range("2020-01-01", periods=90)
    frame = pd.concat([pd.DataFrame({"date": dates, "industry_id": str(j),
                                    "close": 100*np.exp(-.001*(j+1)*np.arange(90)),
                                    "total_turnover": 1000}) for j in range(5)])
    out = industry_features(frame)
    assert np.isnan(out.industry_positive_top3_raw.iloc[-1])
    assert out.industry_positive_top3_proxy.iloc[-1] == 0
    assert out.industry_no_positive.iloc[-1] == 1
    assert out.industry_breadth_20.iloc[-1] == 0


def test_historical_membership_controls_breadth_denominator():
    dates = pd.bdate_range("2020-01-01", periods=80)
    stocks = pd.concat([pd.DataFrame({"date": dates, "order_book_id": "a", "close": np.arange(80)+100}),
                        pd.DataFrame({"date": dates, "order_book_id": "b", "close": 200-np.arange(80)})])
    member = stocks[["date", "order_book_id"]].copy(); member["eligible"] = 1
    member.loc[(member.date == dates[-1]) & member.order_book_id.eq("b"), "eligible"] = 0
    out = breadth_features(stocks, member)
    assert out.breadth_above_ma20.iloc[-2] == .5
    assert out.breadth_above_ma20.iloc[-1] == 1
    assert out.breadth_eligible_count.iloc[-1] == 1
    with pytest.raises(ValueError, match="explicit"):
        breadth_features(stocks, member.iloc[:-1])
