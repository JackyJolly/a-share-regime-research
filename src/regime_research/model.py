from dataclasses import dataclass
import warnings
import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from sklearn.exceptions import ConvergenceWarning
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler
from .config import ModelConfig
from .interpretation import candidate_labels


class MADScaler:
    def fit(self, x):
        a = np.asarray(x)
        self.center_ = np.median(a, axis=0)
        mad = 1.4826 * np.median(np.abs(a - self.center_), axis=0)
        # Fixed fallback for near-constant/discrete columns, with a recorded scale.
        std = np.std(a, axis=0)
        self.scale_ = np.where(mad > 1e-8, mad, np.where(std > 1e-8, std, 1.0))
        return self

    def transform(self, x):
        return (np.asarray(x) - self.center_) / self.scale_

    def inverse_transform(self, z):
        return np.asarray(z) * self.scale_ + self.center_


@dataclass
class WalkForwardResult:
    predictions: pd.DataFrame
    fits: pd.DataFrame
    centroids: pd.DataFrame


def _fit(train: pd.DataFrame, cfg: ModelConfig):
    lower, upper = train.quantile(cfg.clip_quantile), train.quantile(1 - cfg.clip_quantile)
    if "industry_no_positive" in train:
        lower["industry_no_positive"], upper["industry_no_positive"] = 0., 1.
    clipped = train.clip(lower, upper, axis="columns")
    scaler = (MADScaler() if cfg.scaler == "mad" else StandardScaler()).fit(clipped)
    z = scaler.transform(clipped)
    if cfg.model_type == "hmm":
        from .hmm import fit_hmm
        return fit_hmm(z, cfg), scaler, lower, upper, z
    model = GaussianMixture(n_components=cfg.n_states, covariance_type=cfg.covariance_type,
                            n_init=cfg.n_init, max_iter=cfg.max_iter, reg_covar=cfg.reg_covar,
                            random_state=cfg.random_state)
    with warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        model.fit(z)
    return model, scaler, lower, upper, z


def walk_forward(features: pd.DataFrame, cfg: ModelConfig) -> WalkForwardResult:
    """Fit at t using rows strictly before t, then classify close-of-t features.

    Fit-only scaling/clipping, rolling windows and Hungarian label alignment.
    IDs are statistical identities; no claim of economic meaning or accuracy.
    """
    if features.index.has_duplicates or not features.index.is_monotonic_increasing:
        raise ValueError("Features must have a unique chronological index")
    if features.columns.has_duplicates or "momentum_60" not in features:
        raise ValueError("Unique feature columns including momentum_60 required")
    finite = np.isfinite(features.to_numpy(dtype=float)).all(axis=1)
    valid = np.flatnonzero(finite)
    if not len(valid):
        raise ValueError("No finite features")
    # Only leading rolling-window warmup may be omitted; interior gaps must be fixed.
    x = features.iloc[valid[0]:]
    if not np.isfinite(x.to_numpy()).all():
        raise ValueError("Nonfinite features after warmup; do not bridge missing sessions")
    if len(x) <= cfg.min_train_size:
        raise ValueError("Not enough data after feature warmup for out-of-sample predictions")
    rows, fits, centers = [], [], []
    previous_centers = previous_scale = None
    for i in range(cfg.min_train_size, len(x)):
        if (i - cfg.min_train_size) % cfg.refit_every == 0:
            train = x.iloc[max(0, i - cfg.train_window):i]
            model, scaler, lower, upper, z = _fit(train, cfg)
            raw_centers = scaler.inverse_transform(model.means_)
            if previous_centers is None:
                # This orders initial cluster IDs only; these are not semantic labels.
                order = np.argsort(raw_centers[:, x.columns.get_loc("momentum_60")])
                mapping = np.empty(cfg.n_states, dtype=int)
                mapping[order] = np.arange(cfg.n_states)
                alignment_cost = 0.0
            else:
                distance = np.linalg.norm((previous_centers[:, None, :] - raw_centers[None, :, :]) /
                                          previous_scale[None, None, :], axis=2)
                canonical, component = linear_sum_assignment(distance)
                mapping = np.empty(cfg.n_states, dtype=int)
                mapping[component] = canonical
                alignment_cost = float(distance[canonical, component].mean())
            previous_centers = np.empty_like(raw_centers)
            previous_centers[mapping] = raw_centers
            previous_scale = scaler.scale_.copy()
            labels = candidate_labels(previous_centers, x.columns, scaler)
            fit_id = len(fits)
            fits.append({"fit_id": fit_id, "prediction_start": x.index[i],
                         "train_start": train.index[0], "train_end": train.index[-1],
                         "train_n": len(train), "bic": model.bic(z), "aic": model.aic(z),
                         "converged": model.converged_, "iterations": model.n_iter_,
                         "likelihood_delta": getattr(model, "likelihood_delta", None),
                         "alignment_cost": alignment_cost,
                         "minimum_component_weight": float(np.min(model.weights_)),
                         "small_component_warning": bool(np.min(model.weights_) < cfg.min_component_weight)})
            for state in range(cfg.n_states):
                centers.append({"fit_id": fit_id, "state": state,
                                **labels[state], **dict(zip(x.columns, previous_centers[state]))})
            # Past-only baseline exposure: smooth probability-weighted momentum sign.
            risk_on = (previous_centers[:, x.columns.get_loc("momentum_60")] > 0).astype(float)
        current = x.iloc[[i]].clip(lower, upper, axis="columns")
        transformed = scaler.transform(current)
        if cfg.model_type == "hmm":
            component_p, log_likelihood = model.predict_one(transformed[0])
        else:
            component_p = model.predict_proba(transformed)[0]
            log_likelihood = float(model.score_samples(transformed)[0])
        # Change of variables: keep likelihoods in the original feature coordinates.
        # Clipping still means this is a clipped-feature density, not a return forecast.
        log_likelihood -= float(np.log(scaler.scale_).sum())
        probabilities = np.empty(cfg.n_states)
        probabilities[mapping] = component_p
        entropy = -np.sum(probabilities * np.log(np.clip(probabilities, 1e-15, 1))) / np.log(cfg.n_states)
        rows.append({"date": x.index[i], "fit_id": fit_id, "state": int(probabilities.argmax()),
                     "candidate_label": labels[int(probabilities.argmax())]["candidate_label"],
                     "oos_log_likelihood": log_likelihood,
                     "confidence": float(probabilities.max()), "entropy": float(entropy),
                     "exposure_signal": float(probabilities @ risk_on),
                     **{f"p_state_{j}": float(p) for j, p in enumerate(probabilities)}})
    return WalkForwardResult(pd.DataFrame(rows).set_index("date"), pd.DataFrame(fits), pd.DataFrame(centers))


def initial_bic_diagnostic(features: pd.DataFrame, cfg: ModelConfig) -> pd.DataFrame:
    """K=2..6 diagnostic on the FIRST training window only; no OOS tuning."""
    from dataclasses import replace
    x = features.dropna().iloc[:cfg.min_train_size]
    rows = []
    for k in range(2, 7):
        candidate = replace(cfg, n_states=k, model_type="gmm")
        model, _, _, _, z = _fit(x, candidate)
        rows.append({"n_states": k, "bic": model.bic(z), "aic": model.aic(z),
                     "train_start": x.index[0], "train_end": x.index[-1]})
    return pd.DataFrame(rows)
