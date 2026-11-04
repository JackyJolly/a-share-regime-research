"""Daily index OHLCV data, with an optional authenticated Ricequant adapter."""
from pathlib import Path
import os
import numpy as np
import pandas as pd

FIELDS = ["open", "high", "low", "close", "volume", "total_turnover"]


def validate_prices(frame: pd.DataFrame) -> pd.DataFrame:
    missing = set(FIELDS) - set(frame.columns)
    if missing:
        raise ValueError(f"Missing price columns: {sorted(missing)}")
    out = frame[FIELDS].copy()
    out.index = pd.DatetimeIndex(pd.to_datetime(out.index), name="date")
    if out.empty or out.index.hasnans or out.index.has_duplicates or not out.index.is_monotonic_increasing:
        raise ValueError("Prices must have a nonempty, unique, increasing date index")
    if out.index.tz is not None or (out.index != out.index.normalize()).any():
        raise ValueError("Expected timezone-naive daily session dates")
    out = out.astype(float)
    if not np.isfinite(out.to_numpy()).all():
        raise ValueError("Prices contain missing or nonfinite values; no silent forward fill")
    if (out[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("OHLC prices must be positive")
    if (out[["volume", "total_turnover"]] < 0).any().any():
        raise ValueError("Volume and turnover must be nonnegative")
    if ((out.high < out[["open", "close", "low"]].max(axis=1)) |
            (out.low > out[["open", "close", "high"]].min(axis=1))).any():
        raise ValueError("Inconsistent OHLC price bounds")
    return out


def read_prices(path: Path) -> pd.DataFrame:
    return validate_prices(pd.read_csv(path, index_col="date", parse_dates=True))


def fetch_ricequant(order_book_id: str, start_date: str, end_date: str, client=None) -> pd.DataFrame:
    """Use only public SDK methods. Credentials stay in process environment.

    An injected client is already authenticated (also permits offline contract tests).
    SDK transport is not assumed to be HTTPS; respect the environment's TCP policy.
    """
    if client is None:
        from .datasets import init_ricequant
        client = init_ricequant()
    try:
        raw = client.get_price(order_book_id, start_date=start_date, end_date=end_date,
                               frequency="1d", fields=FIELDS, adjust_type="none", expect_df=True)
        calendar = pd.DatetimeIndex(pd.to_datetime(client.get_trading_dates(start_date, end_date)))
    except Exception:
        raise RuntimeError("Ricequant data request failed; verify entitlement and supported SDK transport") from None
    if raw is None or raw.empty:
        raise ValueError("Ricequant returned no data")
    if isinstance(raw.index, pd.MultiIndex):
        if "order_book_id" not in raw.index.names:
            raise ValueError("Unexpected Ricequant MultiIndex schema")
        raw = raw.xs(order_book_id, level="order_book_id")
    result = validate_prices(raw)
    if not result.index.equals(calendar.rename("date")):
        raise ValueError("Ricequant sessions differ from the requested trading calendar")
    return result


def synthetic_prices(periods: int = 1800, seed: int = 42) -> tuple[pd.DataFrame, pd.Series]:
    """Offline integration fixture, not historical A-share evidence."""
    if periods < 100:
        raise ValueError("Synthetic sample must contain at least 100 sessions")
    rng = np.random.default_rng(seed)
    states = (np.arange(periods) // 150) % 4
    mu = np.array([-0.001, -0.0001, 0.0002, 0.001])
    sigma = np.array([0.022, 0.008, 0.018, 0.009])
    returns = rng.normal(mu[states], sigma[states])
    close = 3000 * np.exp(np.cumsum(returns))
    opening = np.r_[close[0], close[:-1]] * np.exp(rng.normal(0, 0.003, periods))
    spread = rng.uniform(0.001, 0.015, periods)
    volume = rng.lognormal(19, 0.3, periods)
    dates = pd.bdate_range("2015-01-01", periods=periods, name="date")
    data = pd.DataFrame({"open": opening, "high": np.maximum(opening, close) * (1 + spread),
                         "low": np.minimum(opening, close) * (1 - spread), "close": close,
                         "volume": volume, "total_turnover": volume * close}, index=dates)
    return validate_prices(data), pd.Series(states, index=dates, name="synthetic_latent_state")
