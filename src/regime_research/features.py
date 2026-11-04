import numpy as np
import pandas as pd
from .data import validate_prices

FEATURES = ["momentum_20", "momentum_60", "volatility_20", "downside_20",
            "drawdown_60", "turnover_ratio_20_60", "range_20", "volatility_ratio_20_60",
            "efficiency_20", "turnover_percentile_252"]

# Appendix A, with a separate structural-missingness flag for all-negative sectors.
PAPER_FEATURES = ["momentum_20", "efficiency_20", "volatility_20", "downside_20",
                  "breadth_above_ma20", "industry_breadth_20", "industry_dispersion_20",
                  "industry_positive_top3_proxy", "industry_no_positive",
                  "industry_top3_turnover", "industry_correlation_60", "size_spread_20",
                  "turnover_percentile_252"]


def make_features(prices: pd.DataFrame) -> pd.DataFrame:
    """All rows use only information available at that session's close.

    Index turnover is a trading-value ratio, NOT free-float turnover rate.
    No macro revisions, full-sample normalization, or future labels enter features.
    """
    p = validate_prices(prices)
    r = p.close.pct_change(fill_method=None)
    vol20, vol60 = r.rolling(20).std(), r.rolling(60).std()
    out = pd.DataFrame(index=p.index)
    out["momentum_20"] = np.log(p.close / p.close.shift(20))
    out["momentum_60"] = np.log(p.close / p.close.shift(60))
    out["volatility_20"] = vol20 * np.sqrt(252)
    out["downside_20"] = np.sqrt(r.clip(upper=0).pow(2).rolling(20).mean() * 252)
    out["drawdown_60"] = p.close.rolling(60).apply(
        lambda a: np.min(a / np.maximum.accumulate(a) - 1), raw=True)
    turnover60 = p.total_turnover.rolling(60).mean().replace(0, np.nan)
    out["turnover_ratio_20_60"] = p.total_turnover.rolling(20).mean() / turnover60 - 1
    out["range_20"] = ((p.high - p.low) / p.close).rolling(20).mean()
    out["volatility_ratio_20_60"] = vol20 / vol60.replace(0, np.nan)
    out["efficiency_20"] = p.close.diff(20).abs() / p.close.diff().abs().rolling(20).sum().replace(0, np.nan)
    out["turnover_percentile_252"] = p.total_turnover.rolling(252).rank(pct=True)
    return out[FEATURES].replace([np.inf, -np.inf], np.nan)
