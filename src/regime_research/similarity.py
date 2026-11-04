import numpy as np
import pandas as pd
from scipy.spatial.distance import jensenshannon
from .model import _fit
from .evaluation import forward_outcomes
from dataclasses import replace


def historical_analogs(features, prices, cfg, query_date=None, horizon=20, limit=5, alpha=.5):
    """Re-score all candidates under the QUERY-TIME GMM for comparable coordinates.

    Outcomes must be completely observable by query close. Fixed alpha and uniform
    diagonal feature weights are declared defaults, not hindsight-optimized values.
    Greedy spacing >=h avoids overlapping candidate outcome windows.
    """
    if not 0 <= alpha <= 1 or horizon < 1 or limit < 1:
        raise ValueError("Invalid similarity settings")
    x = features.dropna()
    query = pd.Timestamp(query_date) if query_date else x.index[-1]
    if query not in x.index:
        raise ValueError("Query date has no complete features")
    train = x.loc[x.index < query].iloc[-cfg.train_window:]
    if len(train) < cfg.min_train_size:
        raise ValueError("Insufficient query-time training history")
    model, scaler, lower, upper, _ = _fit(train, replace(cfg, model_type="gmm"))
    past = x.loc[x.index < query]
    pos = prices.index.get_indexer(past.index)
    query_pos = prices.index.get_loc(query)
    eligible = pos + horizon <= query_pos
    past = past.loc[eligible]
    pos = pos[eligible]
    if past.empty:
        return pd.DataFrame(columns=["date", "distance", "outcome_end", "forward_return", "forward_mdd"])
    z = scaler.transform(past.clip(lower, upper, axis="columns"))
    qz = scaler.transform(x.loc[[query]].clip(lower, upper, axis="columns"))
    p, qp = model.predict_proba(z), model.predict_proba(qz)[0]
    js = np.array([jensenshannon(row, qp)**2 for row in p])
    distance = alpha*js + (1-alpha)*np.linalg.norm(z-qz, axis=1)/np.sqrt(x.shape[1])
    outcomes = forward_outcomes(prices, [horizon])
    chosen, rows = [], []
    for j in np.argsort(distance):
        if any(abs(pos[j]-s) < horizon for s in chosen):
            continue
        chosen.append(pos[j])
        date = past.index[j]
        rows.append({"date": date, "query_date": query, "distance": float(distance[j]),
                     "js_divergence": float(js[j]), "outcome_end": prices.index[pos[j]+horizon],
                     "forward_return": outcomes.loc[date, f"return_{horizon}"],
                     "forward_mdd": outcomes.loc[date, f"mdd_{horizon}"]})
        if len(rows) >= limit:
            break
    return pd.DataFrame(rows)
