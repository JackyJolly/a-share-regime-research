from dataclasses import replace
import numpy as np
import pandas as pd
import pytest
from regime_research.features import make_features
from regime_research.model import walk_forward
from regime_research.similarity import historical_analogs


def test_features_unchanged_when_future_prices_change(prices):
    modified = prices.copy()
    modified.iloc[650:, :4] *= 5
    pd.testing.assert_frame_equal(make_features(prices).iloc[:650], make_features(modified).iloc[:650])


@pytest.mark.parametrize("kind", ["gmm", "hmm"])
def test_predictions_prefix_invariant(features, model_config, kind):
    cfg = replace(model_config, model_type=kind, refit_every=126)
    a = walk_forward(features.iloc[:650], cfg)
    b = walk_forward(features.iloc[:700], cfg)
    pd.testing.assert_frame_equal(a.predictions, b.predictions.loc[a.predictions.index])
    assert (pd.to_datetime(a.fits.train_end) < pd.to_datetime(a.fits.prediction_start)).all()
    p = b.predictions.filter(regex="^p_state_")
    np.testing.assert_allclose(p.sum(axis=1), 1, atol=1e-10)
    assert b.predictions.entropy.between(-1e-10, 1+1e-10).all()
    assert np.isfinite(b.predictions.oos_log_likelihood).all()


def test_interior_missing_features_rejected(features, model_config):
    x = features.copy(); x.iloc[500, 0] = np.nan
    with pytest.raises(ValueError, match="after warmup"):
        walk_forward(x, model_config)


def test_historical_analog_cutoff_spacing_and_future_invariance(features, prices, model_config):
    query = features.index[700]
    a = historical_analogs(features, prices, model_config, query, horizon=20, limit=7)
    assert (a.outcome_end <= query).all()
    positions = sorted(prices.index.get_indexer(a.date))
    assert min(np.diff(positions)) >= 20
    modified = prices.copy(); modified.loc[modified.index > query, "close"] *= 3
    changed_features = features.copy(); changed_features.loc[changed_features.index > query] *= 5
    b = historical_analogs(changed_features, modified, model_config, query, horizon=20, limit=7)
    pd.testing.assert_frame_equal(a, b)
