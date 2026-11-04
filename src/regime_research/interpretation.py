"""Candidate economic descriptions, never mandatory four-way labels."""
import numpy as np


def candidate_labels(centers, columns, scaler):
    required = {"breadth_above_ma20", "industry_positive_top3_proxy", "industry_correlation_60"}
    if len(centers) != 4 or not required <= set(columns):
        return [{"candidate_label": "unresolved", "label_score": None, "label_margin": None}
                for _ in centers]
    # Compare conditional profiles against the TRAINING sample's robust location/scale.
    z = scaler.transform(centers)
    def get(name):
        return z[:, columns.get_loc(name)]
    risk = get("volatility_20")
    breadth = get("breadth_above_ma20")
    concentration = get("industry_positive_top3_proxy")
    scores = np.column_stack([
        (-risk + breadth - get("industry_dispersion_20")) / 3,
        (get("efficiency_20") + np.abs(get("momentum_20"))) / 2,
        (concentration - breadth + np.abs(get("size_spread_20"))) / 3,
        (get("downside_20") - get("momentum_20") - breadth + get("industry_correlation_60")) / 4,
    ])
    names = ["stable_candidate", "trending_candidate", "fragile_candidate", "crisis_candidate"]
    result = []
    for score in scores:
        order = np.argsort(score)
        margin = float(score[order[-1]] - score[order[-2]])
        result.append({"candidate_label": names[order[-1]] if margin >= .25 and score[order[-1]] > 0 else "unresolved",
                       "label_score": float(score[order[-1]]), "label_margin": margin})
    return result
