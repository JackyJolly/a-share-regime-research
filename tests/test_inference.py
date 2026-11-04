import numpy as np
from regime_research.inference import hac_ols, bh_adjust


def test_hac_recovers_known_regression():
    rng = np.random.default_rng(42)
    x = np.column_stack([np.ones(500), rng.normal(size=500)])
    y = x@np.array([.2, .7])+rng.normal(0, .01, 500)
    beta, se, rank = hac_ols(y, x, 4)
    np.testing.assert_allclose(beta, [.2, .7], atol=.002)
    assert rank == 2 and (se > 0).all()


def test_bh_adjustment():
    np.testing.assert_allclose(bh_adjust([.01, .04, .03]), [.03, .04, .04])
