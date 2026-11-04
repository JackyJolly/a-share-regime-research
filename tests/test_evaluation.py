import numpy as np
import pandas as pd
import pytest
from regime_research.evaluation import forward_outcomes, hac_weighted_mean, performance
from regime_research.strategies import simulate_close_execution, equal_risk_weights


def test_execution_lag_cost_date_and_weight_drift():
    dates = pd.bdate_range("2020-01-01", periods=5)
    returns = pd.DataFrame({"asset": [.5, .4, .1, -.1, .05]}, index=dates)
    targets = pd.DataFrame({"asset": [.5, np.nan, np.nan, np.nan, np.nan]}, index=dates)
    result = simulate_close_execution(returns, targets, cost_bps=10)
    assert result.gross_return.iloc[0] == result.gross_return.iloc[1] == 0
    assert result.cost.iloc[1] == .0005
    assert result.gross_return.iloc[2] == pytest.approx(.05)
    assert result.exposure.iloc[3] == pytest.approx(.5*1.1/1.05)
    assert result.turnover.iloc[2:].eq(0).all()


def test_mdd_and_forward_return_include_current_origin():
    dates = pd.bdate_range("2020-01-01", periods=4)
    data = pd.DataFrame({"close": [100, 110, 88, 105]}, index=dates)
    out = forward_outcomes(data, [2])
    assert out.return_2.iloc[0] == pytest.approx(-.12)
    assert out.mdd_2.iloc[0] == pytest.approx(-.2)
    assert out.return_2.iloc[-2:].isna().all()


def test_hac_mean_zero_weights_and_standard_error():
    y = np.array([1., 2., 3., 4.]); w = np.ones(4)
    result = hac_weighted_mean(y, w, 0)
    assert result["mean"] == 2.5
    assert result["hac_se"] == pytest.approx(np.sqrt(5)/4)
    assert hac_weighted_mean(y, np.zeros(4), 2)["mean"] is None


def test_drawdown_includes_initial_equity():
    assert performance([-.1])["max_drawdown"] == pytest.approx(-.1)


def test_risk_parity_equalizes_risk_contributions():
    cov = np.diag([.01, .04, .09, .16])
    w = equal_risk_weights(cov)
    rc = w*(cov@w)
    np.testing.assert_allclose(rc/rc.sum(), .25, atol=1e-5)
