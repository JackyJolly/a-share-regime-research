"""Predeclared industry/style index proxies; no hindsight winner selection."""
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from .evaluation import performance


def simulate_close_execution(asset_returns, targets, cost_bps):
    """Targets decided at t close execute at t+1 close, cost on execution date.

    Between trades, weights drift with asset returns. Cash earns zero. Fractional
    index positions are research proxies, without instrument lot/limit constraints.
    NaN target rows mean no trade. Net turnover includes both bought/sold amounts.
    """
    if not asset_returns.index.equals(targets.index) or not asset_returns.columns.equals(targets.columns):
        raise ValueError("Return/target axes must match")
    if not np.isfinite(asset_returns.to_numpy()).all() or (asset_returns <= -1).any().any():
        raise ValueError("Invalid asset returns")
    w = np.zeros(asset_returns.shape[1])
    execution = targets.shift(1)
    rows = []
    for date, r in asset_returns.iterrows():
        before = w.copy()
        gross = float(w @ r.to_numpy())
        drift = w * (1+r.to_numpy()) / (1+gross)
        target = execution.loc[date].to_numpy()
        if np.isnan(target).all():
            turnover = 0.0
            w = drift
        elif np.isfinite(target).all() and (target >= 0).all() and target.sum() <= 1+1e-10:
            turnover = float(np.abs(target-drift).sum())
            w = target
        else:
            raise ValueError("Targets must be entirely missing or long-only weights summing to <=1")
        cost = turnover * cost_bps/10000
        rows.append({"date": date, "gross_return": gross, "net_return": (1+gross)*(1-cost)-1,
                     "turnover": turnover, "cost": cost, "exposure": float(before.sum())})
    return pd.DataFrame(rows).set_index("date")


def equal_risk_weights(covariance):
    cov = np.asarray(covariance, dtype=float)
    n = len(cov)
    cov = cov + np.eye(n)*1e-8
    def objective(w):
        rc = w*(cov@w)
        return np.sum((rc / (w@cov@w) - 1/n)**2)
    initial = 1/np.sqrt(np.diag(cov)); initial /= initial.sum()
    result = minimize(objective, initial, method="SLSQP", bounds=[(1e-6, 1)]*n,
                      constraints={"type": "eq", "fun": lambda w: w.sum()-1},
                      options={"ftol": 1e-10, "maxiter": 300})
    if not result.success:
        raise ValueError("Risk parity optimization failed")
    return result.x / result.x.sum()


def industry_strategy_comparison(panel, predictions, cfg, rebalance=21, rule=None):
    from .panels import _wide
    close = _wide(panel, "industry_id", "close")
    r = close.pct_change(fill_method=None).fillna(0)
    momentum = close.pct_change(20, fill_method=None)
    names = ["industry_momentum", "industry_reversal", "industry_risk_parity"]
    results, metrics = {}, {}
    # Each predefined allocation is compared fixed, rule-conditioned, GMM-conditioned.
    for name in names:
        base = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
        for date in predictions.index[::rebalance]:
            i = close.index.get_loc(date)
            sample = r.iloc[max(1, i-59):i+1]
            if len(sample) < 60 or momentum.loc[date].isna().any():
                continue
            if name == "industry_risk_parity":
                weight = equal_risk_weights(sample.cov().to_numpy())
            else:
                rank = momentum.loc[date].sort_values(ascending=name == "industry_reversal")
                weight = close.columns.isin(rank.index[:3]).astype(float)/3
            base.loc[date] = weight
        for mode in ["fixed", "trend_conditioned", "regime_conditioned"]:
            targets = base.copy()
            if mode == "regime_conditioned":
                targets = targets.mul(predictions.exposure_signal.reindex(targets.index), axis=0)
            elif mode == "trend_conditioned":
                if rule is None:
                    raise ValueError("Trend baseline signals required")
                targets = targets.mul(rule.exposure_signal.reindex(targets.index), axis=0)
            realized = simulate_close_execution(r, targets, cfg.transaction_cost_bps).loc[predictions.index]
            key = f"{name}_{mode}"
            results[key] = realized
            metrics[key] = {**performance(realized.net_return, cfg.periods_per_year),
                            "total_turnover": float(realized.turnover.sum())}
    return results, metrics


def style_strategy_comparison(styles, predictions, rule, cfg, rebalance=21):
    close = styles[["small_close", "large_close"]]
    if close.isna().any().any():
        raise ValueError("Incomplete style panel")
    r = close.pct_change(fill_method=None).fillna(0)
    relative = (close.small_close / close.large_close).pct_change(20, fill_method=None)
    base = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    for date in predictions.index[::rebalance]:
        base.loc[date] = [1., 0.] if relative.loc[date] > 0 else [0., 1.]
    results, metrics = {}, {}
    for mode in ["fixed", "trend_conditioned", "regime_conditioned"]:
        targets = base.copy()
        if mode != "fixed":
            signal = rule.exposure_signal if mode == "trend_conditioned" else predictions.exposure_signal
            targets = targets.mul(signal.reindex(targets.index), axis=0)
        frame = simulate_close_execution(r, targets, cfg.transaction_cost_bps).loc[predictions.index]
        key = f"size_rotation_{mode}"
        results[key] = frame
        metrics[key] = {**performance(frame.net_return, cfg.periods_per_year),
                        "total_turnover": float(frame.turnover.sum())}
    return results, metrics
