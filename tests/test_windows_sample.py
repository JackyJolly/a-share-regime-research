"""Offline tests of the Windows small-download path; no real credentials/data."""
from datetime import date
import json
import sys

import numpy as np
import pandas as pd
import pytest


class FakeSessionClient:
    """A fake exchange calendar intentionally different from weekday counting."""

    def __init__(self, defect=None):
        self.defect = defect
        weekdays = pd.bdate_range("2025-09-01", "2026-11-04")
        excluded = pd.date_range("2026-10-01", "2026-10-07")
        self.sessions = weekdays[~weekdays.isin(excluded)]
        self.calendar_calls = []
        self.price_calls = []

    def get_trading_dates(self, start_date, end_date, market="cn"):
        assert market == "cn"
        start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
        self.calendar_calls.append((start, end))
        return self.sessions[(self.sessions >= start) & (self.sessions <= end)].date.tolist()

    def get_price(self, order_book_id, start_date=None, end_date=None, **kwargs):
        assert order_book_id == "000300.XSHG"
        assert kwargs["frequency"] == "1d"
        assert kwargs["adjust_type"] == "none"
        assert kwargs["expect_df"] is True
        start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
        sessions = self.sessions[(self.sessions >= start) & (self.sessions <= end)]
        self.price_calls.append((start, end))
        close = np.arange(len(sessions), dtype=float)+100.
        data = pd.DataFrame({"open": close, "high": close+1, "low": close-1,
                             "close": close, "volume": np.full(len(sessions), 1000.),
                             "total_turnover": close*1000},
                            index=pd.DatetimeIndex(sessions, name="date"))
        if self.defect == "truncated":
            data = data.iloc[:-1]
        elif self.defect == "duplicate":
            data = pd.concat([data, data.iloc[[-1]]])
        elif self.defect == "nan":
            data.loc[data.index[-2], "close"] = np.nan
        return pd.concat({order_book_id: data}, names=["order_book_id"])


def test_sample_download_uses_exactly_sixty_exchange_sessions(tmp_path, monkeypatch, capsys):
    pytest.importorskip("pyarrow")
    from regime_research.sample import download_sample
    from regime_research.quality import inspect_dataset
    sdk = FakeSessionClient()
    target = tmp_path/"fake_sdk_sample"
    download_sample(target, client=sdk, today=date(2026, 11, 5))
    prices = pd.read_parquet(target/"prices.parquet")
    actual = pd.DatetimeIndex(pd.to_datetime(prices["date"]))
    expected = pd.DatetimeIndex(sdk.sessions[-60:])
    assert actual.equals(expected)
    assert not actual.equals(pd.bdate_range(end="2026-11-04", periods=60))
    assert len(prices) == 60
    assert len(sdk.price_calls) == 1
    assert sdk.price_calls[0] == (expected[0], expected[-1])
    assert sdk.calendar_calls[0][1] == pd.Timestamp("2026-11-04")
    assert (target/"quality_report.json").is_file()
    assert (target/"quality_report.md").is_file()
    report = json.loads((target/"quality_report.json").read_text())
    assert report["checks"]["exact_requested_calendar"] is True
    manifest = json.loads((target/"manifest.json").read_text())
    assert manifest["market_index"] == "000300.XSHG"
    # This is the downloader's source contract tested with a fake SDK, never an
    # acceptance claim about the live provider or an empirical result.
    assert manifest["source"] == "ricequant"
    check = inspect_dataset(target)
    assert check["status"] == "passed"
    assert check["rows"] == 60
    assert check["usable_core_feature_rows"] == 0
    from regime_research import auth, cli, datasets, sample
    for module in [auth, sample]:
        monkeypatch.setattr(module, "initialize", lambda *a, **k: pytest.fail("Local validation must not initialize the SDK"))
    assert cli.main(["validate-data", "--data", str(target)]) == 0
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert not output.err
    assert result["ok"] is True
    assert result["rows"] == 60
    assert result["is_synthetic"] is False
    assert result["hash_verified"] is True
    (target/"quality_report.json").write_text('{"status": "tampered"}', encoding="utf-8")
    with pytest.raises(ValueError, match="hash|Hash|checksum|Checksum"):
        datasets.verify_manifest(target)


@pytest.mark.parametrize("defect", ["truncated", "duplicate", "nan"])
def test_sample_rejects_incomplete_or_invalid_price_sessions(tmp_path, defect):
    pytest.importorskip("pyarrow")
    from regime_research.sample import download_sample
    target = tmp_path/defect
    with pytest.raises((ValueError, RuntimeError)):
        download_sample(target, client=FakeSessionClient(defect), today=date(2026, 11, 5))
    assert not (target/"manifest.json").exists()


def test_sample_future_end_date_fails_before_any_sdk_request(tmp_path):
    from regime_research.sample import download_sample
    sdk = FakeSessionClient()
    with pytest.raises((ValueError, RuntimeError)):
        download_sample(tmp_path/"future", end_date="2026-11-06", client=sdk,
                        today=date(2026, 11, 5))
    assert not sdk.calendar_calls and not sdk.price_calls


@pytest.mark.parametrize("defect", ["duplicate", "insufficient", "future"])
def test_sample_rejects_invalid_calendar_before_requesting_prices(tmp_path, defect):
    from regime_research.sample import download_sample

    class InvalidCalendarClient(FakeSessionClient):
        def get_trading_dates(self, start_date, end_date, market="cn"):
            sessions = super().get_trading_dates(start_date, end_date, market)
            if defect == "duplicate":
                return sessions + [sessions[-1]]
            if defect == "insufficient":
                return sessions[-59:]
            return sessions + [date(2026, 11, 6)]

    sdk = InvalidCalendarClient()
    target = tmp_path/defect
    with pytest.raises(ValueError, match="calendar"):
        download_sample(target, client=sdk, today=date(2026, 11, 5))
    assert len(sdk.calendar_calls) == 1
    assert not sdk.price_calls
    assert not target.exists()


def test_sample_cli_missing_environment_key_does_not_download(monkeypatch, tmp_path, capsys):
    import regime_research.sample as sample
    for key in ["RQDATAC_LICENSE_KEY", "RQDATAC_USERNAME", "RQDATAC_PASSWORD",
                "RQDATAC_CONF", "RQDATAC2_CONF"]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(sample, "initialize", lambda *a, **k: pytest.fail("No SDK call without a configured key"))
    assert sample.main(["--output", str(tmp_path/"unused")]) != 0
    output = capsys.readouterr()
    assert "RQDATAC_LICENSE_KEY" in output.err+output.out
    assert not (tmp_path/"unused").exists()


def test_sample_cli_suppresses_sdk_output_and_exception(monkeypatch, tmp_path, capsys):
    import regime_research.sample as sample
    fake_secret = "TEST_ONLY_SECRET_NEVER_A_REAL_CREDENTIAL"

    class NoisyFailingClient:
        def get_trading_dates(self, *args, **kwargs):
            print(fake_secret)
            print(fake_secret, file=sys.stderr)
            raise RuntimeError(fake_secret)

        def get_price(self, *args, **kwargs):
            pytest.fail("A failed calendar request must not request prices")

    monkeypatch.setenv("RQDATAC_LICENSE_KEY", fake_secret)
    monkeypatch.setattr(sample, "initialize", lambda: NoisyFailingClient())
    target = tmp_path/"failed_sdk_sample"
    assert sample.main(["--output", str(target), "--end-date", "2000-01-01"]) == 1
    output = capsys.readouterr()
    assert fake_secret not in output.out + output.err
    assert not output.out
    assert json.loads(output.err)["ok"] is False
    assert not target.exists()
