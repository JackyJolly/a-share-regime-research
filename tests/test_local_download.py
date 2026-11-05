"""Offline contract tests only: fake SDK data must never be used as research evidence."""
from dataclasses import replace
import importlib.util
from pathlib import Path
import json
import os
import numpy as np
import pandas as pd
import pytest

from regime_research.config import DataConfig
from regime_research.datasets import ricequant_bundle, verify_manifest
from regime_research.storage import read_table, resolve_table


class OfflineClient:
    """A deliberately fake SDK; no network or actual environment credentials used."""
    def __init__(self, fail_after_market=False):
        self.dates = pd.bdate_range("2024-01-02", periods=70, name="date")
        self.fail_after_market = fail_after_market

    def get_trading_dates(self, start, end):
        return self.dates.date.tolist()

    def get_price(self, ids, **kwargs):
        close = np.linspace(100, 110, len(self.dates))
        if isinstance(ids, list):
            frame = pd.DataFrame({"close": close, "volume": 1000.}, index=self.dates)
            return pd.concat({i: frame for i in ids}, names=["order_book_id"])
        if self.fail_after_market and ids != "000985.XSHG":
            print("FAKE_SECRET_MUST_NOT_APPEAR")
            raise RuntimeError("SDK exception contains FAKE_SECRET_MUST_NOT_APPEAR")
        frame = pd.DataFrame({"open": close, "high": close*1.01, "low": close*.99,
                              "close": close, "volume": 1000., "total_turnover": close*1000},
                             index=self.dates)
        return pd.concat({ids: frame}, names=["order_book_id"])

    def index_components(self, index, date):
        return ["FAKE_A", "FAKE_B"]


@pytest.mark.parametrize("format", ["csv", "parquet"])
def test_downloaded_tables_and_manifest_published_together(tmp_path, format):
    if format == "parquet":
        pytest.importorskip("pyarrow")
    config = DataConfig(industry_ids=["FAKE_1", "FAKE_2", "FAKE_3", "FAKE_4"],
                        industry_classification="offline_test_only")
    destination = tmp_path/"fixture_only"
    ricequant_bundle(destination, config, with_panels=True, client=OfflineClient(), output_format=format)
    manifest = verify_manifest(destination)
    assert manifest["source"] == "ricequant"  # Adapter contract, NOT real-service acceptance.
    assert manifest["is_synthetic"] is False
    assert set(manifest["logical_tables"]) == {"prices", "styles", "industry_panel", "stock_panel", "membership"}
    for name, filename in manifest["logical_tables"].items():
        assert filename.endswith("."+format)
        assert not read_table(resolve_table(destination, manifest, name)).empty
    assert not list(tmp_path.glob(".fixture_only.download-*"))
    assert not (destination/"INCOMPLETE.json").exists()


def test_failed_download_does_not_publish_dataset_or_echo_sdk_secret(tmp_path, capsys):
    cfg = DataConfig(industry_ids=["FAKE_1", "FAKE_2", "FAKE_3", "FAKE_4"],
                     industry_classification="offline_test_only")
    destination = tmp_path/"fixture_only"
    with pytest.raises(RuntimeError) as error:
        ricequant_bundle(destination, cfg, True, OfflineClient(fail_after_market=True))
    assert "FAKE_SECRET_MUST_NOT_APPEAR" not in str(error.value)
    assert "FAKE_SECRET_MUST_NOT_APPEAR" not in capsys.readouterr().out
    assert not destination.exists()
    staging = list(tmp_path.glob(".fixture_only.download-*"))
    assert len(staging) == 1 and (staging[0]/"prices.csv").exists()
    with pytest.raises(ValueError, match="Incomplete"):
        verify_manifest(staging[0])


def test_existing_data_and_invalid_config_rejected_before_network(tmp_path):
    destination = tmp_path/"existing"
    destination.mkdir(); (destination/"user-file").write_text("keep")
    with pytest.raises(ValueError, match="overwrite"):
        ricequant_bundle(destination, DataConfig(), client=object())
    assert (destination/"user-file").read_text() == "keep"
    with pytest.raises(ValueError, match="industry"):
        ricequant_bundle(tmp_path/"new", DataConfig(), True, object())


def _script_module():
    path = Path(__file__).parents[1]/"scripts/download_ricequant.py"
    spec = importlib.util.spec_from_file_location("local_rq_script", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_hidden_prompt_restores_environment(monkeypatch, capsys):
    script = _script_module()
    monkeypatch.setenv("RQDATAC_LICENSE_KEY", "PREVIOUS_TEST_VALUE")
    monkeypatch.setattr(script.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(script.getpass, "getpass", lambda _: "TEMPORARY_TEST_VALUE")
    calls = []
    def fake_cli(args):
        assert os.environ["RQDATAC_LICENSE_KEY"] == "TEMPORARY_TEST_VALUE"
        calls.append(args)
        return 0
    monkeypatch.setattr(script, "research_cli", fake_cli)
    assert script.main(["--output", "unused", "--format", "parquet", "--prompt-license"]) == 0
    assert calls == [["fetch", "--output", "unused", "--format", "parquet"]]
    assert os.environ["RQDATAC_LICENSE_KEY"] == "PREVIOUS_TEST_VALUE"
    assert "TEST_VALUE" not in capsys.readouterr().out


def test_prompt_refuses_echoing_noninteractive_stdin(monkeypatch):
    script = _script_module()
    monkeypatch.setattr(script.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(script.getpass, "getpass", lambda _: pytest.fail("Must not prompt without hidden input"))
    monkeypatch.setattr(script, "research_cli", lambda _: pytest.fail("Must not start download"))
    assert script.main(["--prompt-license", "--output", "unused"]) == 1
