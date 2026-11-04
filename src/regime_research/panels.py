"""Optional point-in-time breadth and fixed-classification industry-index proxies."""
import numpy as np
import pandas as pd
from .features import make_features, PAPER_FEATURES


def _wide(frame, identifier, value):
    required = {"date", identifier, value}
    if not required <= set(frame):
        raise ValueError(f"Panel requires columns {sorted(required)}")
    x = frame.copy()
    x["date"] = pd.to_datetime(x.date)
    if x.duplicated(["date", identifier]).any():
        raise ValueError("Duplicate date/instrument in panel")
    return x.pivot(index="date", columns=identifier, values=value).sort_index()


def breadth_features(stock_panel: pd.DataFrame, membership: pd.DataFrame) -> pd.DataFrame:
    """Membership is a daily historical snapshot, not today's survivor list.

    close must be a consistently adjusted close/total-return price per instrument;
    eligible denotes tradable, established (>=60 observations) securities at t.
    An unavailable membership value is an error, never inferred as True.
    """
    close = _wide(stock_panel, "order_book_id", "close")
    if (close <= 0).any().any():
        raise ValueError("Stock closes must be positive where observed")
    member = _wide(membership, "order_book_id", "eligible").reindex(index=close.index, columns=close.columns)
    if not member.isin([True, False, 0, 1]).all().all():
        raise ValueError("Membership requires explicit 0/1 for each panel date/instrument")
    observed = close.rolling(60).count().eq(60)
    valid = member.astype(bool) & observed & close.notna()
    denom = valid.sum(axis=1).replace(0, np.nan)
    above = close > close.rolling(20).mean()
    advance = close > close.shift()
    # A strict new high relative to the PREVIOUS 20 sessions, not an inclusive maximum.
    new_high = close > close.shift().rolling(20).max()
    return pd.DataFrame({"breadth_above_ma20": (above & valid).sum(axis=1) / denom,
                         "breadth_advancing": (advance & valid).sum(axis=1) / denom,
                         "breadth_new_high20": (new_high & valid).sum(axis=1) / denom,
                         "breadth_eligible_count": valid.sum(axis=1)})


def industry_features(panel: pd.DataFrame, top_n: int = 3, window: int = 20) -> pd.DataFrame:
    """Equal-weight sector-index return proxies, NOT actual market contributions.

    Fixed classification/constituent methodology must be recorded by the caller.
    All-negative positive contribution shares remain NaN in the raw diagnostics.
    Selected model proxy uses zero plus an explicit no-positive flag.
    """
    close = _wide(panel, "industry_id", "close")
    turnover = _wide(panel, "industry_id", "total_turnover").reindex_like(close)
    if close.shape[1] <= top_n:
        raise ValueError("Industry panel must contain more industries than top_n")
    if close.isna().any().any() or turnover.isna().any().any():
        raise ValueError("Industry index panel must be complete; no classification-gap interpolation")
    if (close <= 0).any().any() or (turnover < 0).any().any():
        raise ValueError("Invalid industry price/turnover")
    returns = close.pct_change(fill_method=None)
    momentum = close.pct_change(window, fill_method=None)
    result = pd.DataFrame(index=close.index)
    result["industry_breadth_20"] = momentum.gt(0).mean(axis=1).where(momentum.notna().all(axis=1))
    result["industry_dispersion_20"] = momentum.std(axis=1, ddof=0)
    positive = momentum.clip(lower=0)
    negative = -momentum.clip(upper=0)
    pos_share = positive.div(positive.sum(axis=1).replace(0, np.nan), axis=0)
    neg_share = negative.div(negative.sum(axis=1).replace(0, np.nan), axis=0)
    n = close.shape[1]
    result["industry_positive_hhi_proxy"] = ((pos_share.pow(2).sum(axis=1, min_count=n) - 1/n) / (1-1/n))
    result["industry_negative_hhi_proxy"] = ((neg_share.pow(2).sum(axis=1, min_count=n) - 1/n) / (1-1/n))
    top = pos_share.apply(lambda row: row.nlargest(top_n).sum(min_count=top_n), axis=1)
    result["industry_positive_top3_raw"] = top
    no_positive = positive.sum(axis=1).eq(0) & momentum.notna().all(axis=1)
    result["industry_no_positive"] = no_positive.astype(float).where(momentum.notna().all(axis=1))
    result["industry_positive_top3_proxy"] = top.mask(no_positive, 0.0)
    shares = turnover.div(turnover.sum(axis=1).replace(0, np.nan), axis=0)
    result["industry_turnover_hhi"] = (shares.pow(2).sum(axis=1, min_count=n) - 1/n) / (1-1/n)
    # Lag by L to compare non-overlapping momentum windows.
    old = momentum.shift(window)
    stability, churn, correlation, com = [], [], [], []
    for i in range(len(close)):
        now, previous = momentum.iloc[i], old.iloc[i]
        if now.notna().all() and previous.notna().all():
            stability.append(now.corr(previous, method="spearman"))
            churn.append(1 - len(set(now.nlargest(top_n).index) & set(previous.nlargest(top_n).index)) / top_n)
        else:
            stability.append(np.nan); churn.append(np.nan)
        sample = returns.iloc[max(0, i-59):i+1]
        if len(sample) == 60 and sample.notna().all().all():
            corr = sample.corr().to_numpy()
            if np.isfinite(corr).all():
                correlation.append(corr[np.triu_indices(n, 1)].mean())
                com.append(np.linalg.eigvalsh(corr)[-1] / n)
                continue
        correlation.append(np.nan); com.append(np.nan)
    result["industry_rank_persistence"] = stability
    result["industry_top3_turnover"] = churn
    result["industry_correlation_60"] = correlation
    result["industry_commonality_60"] = com
    return result


def combined_features(prices, industry_panel, stock_panel, membership, styles):
    out = make_features(prices)
    # Retain momentum_60 as a model label-alignment anchor; omit from GMM input later.
    out = out.join(industry_features(industry_panel)).join(breadth_features(stock_panel, membership))
    required = {"small_close", "large_close"}
    if not required <= set(styles) or styles.index.has_duplicates:
        raise ValueError("Styles require unique date index and small_close/large_close")
    if (styles[list(required)] <= 0).any().any():
        raise ValueError("Style index prices must be positive")
    relative = styles.small_close / styles.large_close
    out["size_spread_20"] = np.log(relative / relative.shift(20))
    return out[PAPER_FEATURES + ["momentum_60"]]
