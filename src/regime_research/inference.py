"""External descriptive HAC regressions, not a fitted trading forecast."""
import numpy as np
import pandas as pd
from scipy.stats import norm


def bh_adjust(p_values):
    p = np.asarray(p_values, dtype=float)
    order = np.argsort(p)
    ranked = p[order]*len(p)/np.arange(1, len(p)+1)
    adjusted = np.empty_like(p)
    adjusted[order] = np.minimum(1, np.minimum.accumulate(ranked[::-1])[::-1])
    return adjusted


def hac_ols(y, x, lags):
    y, x = np.asarray(y, dtype=float), np.asarray(x, dtype=float)
    if len(y) <= x.shape[1]+lags or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("Insufficient or nonfinite regression data")
    rank = np.linalg.matrix_rank(x)
    inverse = np.linalg.pinv(x.T@x)
    beta = np.linalg.lstsq(x, y, rcond=None)[0]
    residual = y-x@beta
    scores = x*residual[:, None]
    meat = scores.T@scores
    for lag in range(1, min(lags, len(y)-1)+1):
        cross = scores[lag:].T@scores[:-lag]
        meat += (1-lag/(lags+1))*(cross+cross.T)
    covariance = inverse@meat@inverse
    se = np.sqrt(np.maximum(0, np.diag(covariance)))
    return beta, se, rank


def incremental_regressions(features, predictions, outcomes, horizons):
    controls = ["momentum_20", "volatility_20"]
    if "size_spread_20" in features:
        controls.append("size_spread_20")
    x = features.loc[predictions.index, controls].copy()
    x.insert(0, "intercept", 1.)
    # K-1 probabilities avoids the sum-to-one dummy trap.
    for name in list(predictions.filter(regex="^p_state_").columns)[1:]:
        x[name] = predictions[name]
    rows = []
    for h in horizons:
        y = outcomes[f"return_{h}"].reindex(x.index)
        valid = y.notna() & x.notna().all(axis=1)
        beta, se, rank = hac_ols(y[valid], x[valid], h-1)
        for j, name in enumerate(x.columns):
            p = float(2*norm.sf(abs(beta[j]/se[j]))) if se[j] > 0 and rank == len(x.columns) else None
            rows.append({"horizon": h, "term": name, "coefficient": float(beta[j]),
                         "hac_se": float(se[j]), "ci_low": float(beta[j]-1.96*se[j]),
                         "ci_high": float(beta[j]+1.96*se[j]), "p_value": p,
                         "observations": int(valid.sum()), "design_rank": rank,
                         "full_rank": rank == len(x.columns)})
    result = pd.DataFrame(rows)
    valid_p = result.p_value.notna()
    result["p_bh_within_report"] = np.nan
    result.loc[valid_p, "p_bh_within_report"] = bh_adjust(result.loc[valid_p, "p_value"])
    return result
