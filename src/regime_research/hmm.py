"""Optional HMM estimator with strictly forward-only filtering."""
import numpy as np
from scipy.special import logsumexp
from scipy.stats import multivariate_normal


class FilteredHMM:
    def __init__(self, model, training):
        self.model = model
        self.means_ = model.means_
        self.weights_ = model.predict_proba(training).mean(axis=0)  # TRAINING profiles only
        history = list(model.monitor_.history)
        self.likelihood_delta = float(history[-1]-history[-2]) if len(history) > 1 else None
        # hmmlearn's monitor also treats negative likelihood deltas as converged.
        # Record this explicitly instead of misreporting numerical deterioration.
        self.converged_ = bool(self.likelihood_delta is not None and
                               -1e-5 <= self.likelihood_delta < model.tol)
        self.n_iter_ = model.monitor_.iter
        self.log_alpha = None
        # Never use smoothed state probabilities as out-of-sample signals.
        for row in training:
            self._step(row)

    def _step(self, row):
        emission = np.array([multivariate_normal.logpdf(row, mean=m, cov=c, allow_singular=True)
                             for m, c in zip(self.model.means_, self.model.covars_)])
        if self.log_alpha is None:
            prior = np.log(np.clip(self.model.startprob_, 1e-300, 1))
        else:
            prior = logsumexp(self.log_alpha[:, None] +
                              np.log(np.clip(self.model.transmat_, 1e-300, 1)), axis=0)
        joint = prior + emission
        likelihood = logsumexp(joint)
        self.log_alpha = joint - likelihood
        return np.exp(self.log_alpha), float(likelihood)

    def predict_one(self, row):
        return self._step(row)

    def aic(self, x):
        return self.model.aic(x)

    def bic(self, x):
        return self.model.bic(x)


def fit_hmm(z, cfg):
    try:
        from hmmlearn.hmm import GaussianHMM
    except ImportError:
        raise RuntimeError("Install the hmm optional dependency for HMM comparisons") from None
    best, best_score, best_converged = None, -np.inf, False
    for j in range(cfg.n_init):
        model = GaussianHMM(n_components=cfg.n_states, covariance_type=cfg.covariance_type,
                            n_iter=cfg.max_iter, min_covar=cfg.reg_covar, random_state=cfg.random_state+j)
        model.fit(z)
        score = model.score(z)
        history = list(model.monitor_.history)
        delta = history[-1]-history[-2] if len(history) > 1 else np.inf
        converged = bool(-1e-5 <= delta < model.tol)
        if np.isfinite(score) and ((converged and not best_converged) or
                                   (converged == best_converged and score > best_score)):
            best, best_score, best_converged = model, score, converged
    if best is None:
        raise ValueError("HMM did not produce a finite training likelihood")
    return FilteredHMM(best, z)
