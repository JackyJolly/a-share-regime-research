"""Descriptive OOS outcomes; HAC accounts for overlap, not multiple model search."""
import numpy as np
import pandas as pd
from .config import EvaluationConfig


def forward_outcomes(prices, horizons):
    close = prices.close
    out = pd.DataFrame(index=close.index)
    for h in horizons:
        out[f"return_{h}"] = close.shift(-h) / close - 1
        a = close.to_numpy()
        mdd = np.full(len(a), np.nan)
        for i in range(len(a)-h):
            path = a[i:i+h+1]
            mdd[i] = np.min(path / np.maximum.accumulate(path) - 1)
        out[f"mdd_{h}"] = mdd
    return out


def hac_weighted_mean(y, weights, lags):
    """Ratio-estimator HAC SE on the full time axis, including zero-weight dates."""
    y, w = np.asarray(y, dtype=float), np.asarray(weights, dtype=float)
    mask = np.isfinite(y) & np.isfinite(w)
    y, w = np.where(mask, y, 0), np.where(mask, w, 0)
    if w.sum() <= 0:
        return {"mean": None, "hac_se": None, "ci_low": None, "ci_high": None, "effective_n": 0.0}
    mean = float(w @ y / w.sum())
    psi = w * (y-mean)
    variance = float(psi @ psi)
    lags = min(lags, len(y)-1)
    for lag in range(1, lags+1):
        variance += 2 * (1-lag/(lags+1)) * float(psi[lag:] @ psi[:-lag])
    se = float(np.sqrt(max(0, variance)) / w.sum())
    return {"mean": mean, "hac_se": se, "ci_low": mean-1.96*se, "ci_high": mean+1.96*se,
            "effective_n": float(w.sum()**2 / (w @ w))}


def state_statistics(predictions, outcomes, horizons, n_states):
    aligned = outcomes.reindex(predictions.index)
    rows = []
    for h in horizons:
        y = aligned[f"return_{h}"]
        drawdown = aligned[f"mdd_{h}"]
        for state in range(n_states):
            hard = predictions.state.eq(state)
            values = y[hard].dropna()
            for method in ["hard", "probability"]:
                weights = hard.astype(float) if method == "hard" else predictions[f"p_state_{state}"]
                valid = y.notna()
                w = weights.where(valid, 0)
                weight_sum = w.sum()
                rows.append({"state": state, "horizon": h, "method": method,
                             "observed_outcomes": int((valid & (weights > 0)).sum()),
                             "hard_episodes": int((hard & ~hard.shift(fill_value=False)).sum()),
                             **hac_weighted_mean(y, weights, h-1),
                             "median_hard": float(values.median()) if len(values) else None,
                             "q05_hard": float(values.quantile(.05)) if len(values) else None,
                             "q95_hard": float(values.quantile(.95)) if len(values) else None,
                             "positive_probability": float((w * y.gt(0)).sum()/weight_sum) if weight_sum else None,
                             "tail_loss_probability": float((w * y.lt(-.05)).sum()/weight_sum) if weight_sum else None,
                             "mdd_below_10pct_probability": float((w * drawdown.lt(-.10)).sum()/weight_sum) if weight_sum else None})
    return pd.DataFrame(rows)


def transition_statistics(predictions, n_states):
    counts = np.zeros((n_states, n_states), dtype=int)
    states = predictions.state.to_numpy()
    np.add.at(counts, (states[:-1], states[1:]), 1)
    denom = counts.sum(axis=1, keepdims=True)
    probabilities = np.divide(counts, denom, out=np.full_like(counts, np.nan, dtype=float), where=denom != 0)
    return pd.DataFrame(counts), pd.DataFrame(probabilities)


def performance(returns, annualization=252):
    r = np.asarray(returns, dtype=float)
    if not len(r) or not np.isfinite(r).all() or (r <= -1).any():
        raise ValueError("Invalid strategy return series")
    equity = np.cumprod(1+r)
    volatility = float(np.std(r, ddof=1)*np.sqrt(annualization)) if len(r) > 1 else 0.0
    return {"total_return": float(equity[-1]-1),
            "annualized_return": float(equity[-1]**(annualization/len(r))-1),
            "annualized_volatility": volatility,
            "sharpe_zero_cash": float(r.mean()*annualization/volatility) if volatility > 0 else None,
            "max_drawdown": float(np.min(equity / np.maximum.accumulate(np.r_[1, equity])[1:] - 1))}


def timing_strategy(prices, predictions, cfg: EvaluationConfig):
    """Illustrative index exposure, not a paper industry/style allocation result.

    signal(t close) -> execute at t+1 close -> first earn close(t+1)..close(t+2).
    Index prices are theoretical proxies, not directly tradeable fills.
    """
    from .strategies import simulate_close_execution
    r = prices.close.pct_change(fill_method=None).fillna(0).to_frame("market")
    targets = predictions.exposure_signal.reindex(prices.index).to_frame("market")
    rows = simulate_close_execution(r, targets, cfg.transaction_cost_bps).loc[predictions.index]
    rows["index_return"] = r.market.reindex(rows.index)
    # Same signal availability and entry delay for the passive comparator.
    passive = pd.DataFrame(np.nan, index=prices.index, columns=["market"])
    passive.loc[predictions.index[0], "market"] = 1.0
    benchmark = simulate_close_execution(r, passive, cfg.transaction_cost_bps)
    rows["benchmark_net_return"] = benchmark.net_return.reindex(rows.index)
    rows["strategy_equity"] = (1+rows.net_return).cumprod()
    rows["benchmark_equity"] = (1+rows.benchmark_net_return).cumprod()
    summary = {"strategy": performance(rows.net_return, cfg.periods_per_year),
               "benchmark": performance(rows.benchmark_net_return, cfg.periods_per_year),
               "total_turnover": float(rows.turnover.sum()), "total_cost": float(rows.cost.sum())}
    return rows, summary


def rule_baseline(features, cfg):
    """Five trend classes, with thresholds estimated only before each prediction."""
    x = features.dropna()
    rows = []
    for i in range(cfg.min_train_size, len(x)):
        if (i-cfg.min_train_size) % cfg.refit_every == 0:
            train = x.iloc[max(0, i-cfg.train_window):i]
            neutral = train.momentum_20.abs().quantile(.25)
            directional = train.efficiency_20.median()
        value = x.iloc[i]
        if abs(value.momentum_20) <= neutral:
            state = "sideways"
        elif value.momentum_20 > 0:
            state = "uptrend" if value.efficiency_20 >= directional else "choppy_up"
        else:
            state = "downtrend" if value.efficiency_20 >= directional else "choppy_down"
        rows.append({"date": x.index[i], "trend_state": state,
                     "exposure_signal": float(value.momentum_20 > neutral)})
    return pd.DataFrame(rows).set_index("date")
