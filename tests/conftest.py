import pytest
from regime_research.config import ModelConfig
from regime_research.data import synthetic_prices
from regime_research.features import make_features


@pytest.fixture(scope="session")
def prices():
    return synthetic_prices(850, 11)[0]


@pytest.fixture(scope="session")
def features(prices):
    return make_features(prices)


@pytest.fixture
def model_config():
    return ModelConfig(min_train_size=126, train_window=252, refit_every=63, n_init=1, max_iter=300)
