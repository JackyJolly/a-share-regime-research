"""Offline format/contract fixtures, never market observations or empirical data."""
import hashlib
import json
import pandas as pd
import pytest
from regime_research.storage import resolve_table, read_table
from regime_research.data import read_prices
from regime_research.datasets import synthetic_bundle, verify_manifest
from regime_research.pipeline import run_research
from regime_research.config import ResearchConfig, DataConfig, EvaluationConfig


def _manifest(directory, filenames, mapping=None):
    result = {"source": "offline_test_fixture", "is_synthetic": True,
              "sha256": {name: hashlib.sha256((directory/name).read_bytes()).hexdigest()
                         for name in filenames}}
    if mapping is not None:
        result["logical_tables"] = mapping
    return result


def test_csv_parquet_price_parity(tmp_path, prices):
    csv = tmp_path/"prices.csv"
    parquet = tmp_path/"prices.parquet"
    prices.to_csv(csv)
    prices.to_parquet(parquet, engine="pyarrow")
    pd.testing.assert_frame_equal(read_prices(csv), read_prices(parquet), check_freq=False)


@pytest.mark.parametrize("suffix", ["csv", "parquet"])
def test_identifiers_and_daily_dates_are_preserved(tmp_path, suffix):
    frame = pd.DataFrame({"date": pd.to_datetime(["2020-01-02", "2020-01-03"]),
                          "order_book_id": pd.Series(["000001", "000002"], dtype="string"),
                          "industry_id": pd.Series(["001", "003"], dtype="string"),
                          "close": [10., 11.]})
    path = tmp_path/f"panel.{suffix}"
    if suffix == "csv": frame.to_csv(path, index=False)
    else: frame.to_parquet(path, index=False)
    pd.testing.assert_frame_equal(read_table(path), frame)


def test_resolution_rejects_ambiguity_and_uses_explicit_mapping(tmp_path, prices):
    prices.to_csv(tmp_path/"prices.csv")
    prices.to_parquet(tmp_path/"prices.parquet")
    manifest = _manifest(tmp_path, ["prices.csv", "prices.parquet"])
    with pytest.raises(ValueError, match="Ambiguous"):
        resolve_table(tmp_path, manifest, "prices")
    manifest["logical_tables"] = {"prices": "prices.parquet"}
    assert resolve_table(tmp_path, manifest, "prices").name == "prices.parquet"


def test_resolution_requires_hash_for_actual_file(tmp_path, prices):
    prices.to_csv(tmp_path/"prices.csv")
    prices.to_parquet(tmp_path/"alternate.parquet")
    manifest = _manifest(tmp_path, ["prices.csv"], {"prices": "alternate.parquet"})
    with pytest.raises(ValueError, match="covered by sha256"):
        resolve_table(tmp_path, manifest, "prices")


@pytest.mark.parametrize("filename", ["../prices.csv", "/tmp/prices.csv", "..\\prices.csv"])
def test_resolution_rejects_path_escape(tmp_path, filename):
    manifest = {"sha256": {filename: "0"*64}, "logical_tables": {"prices": filename}}
    with pytest.raises(ValueError, match="basenames"):
        resolve_table(tmp_path, manifest, "prices")


def test_resolution_rejects_symlink_escape(tmp_path, prices):
    target = tmp_path/"outside.csv"
    prices.to_csv(target)
    dataset = tmp_path/"data"; dataset.mkdir()
    try:
        (dataset/"prices.csv").symlink_to(target)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows requires Developer Mode or symlink permission for this test")
        raise
    manifest = _manifest(dataset, ["prices.csv"])
    with pytest.raises(ValueError, match="escapes"):
        resolve_table(dataset, manifest, "prices")


def test_resolution_detects_changed_parquet(tmp_path, prices):
    path = tmp_path/"prices.parquet"
    prices.to_parquet(path)
    manifest = _manifest(tmp_path, [path.name])
    altered = prices.copy(); altered.iloc[0, -1] *= 1.1
    altered.to_parquet(path)
    with pytest.raises(ValueError, match="hash mismatch"):
        resolve_table(tmp_path, manifest, "prices")


@pytest.mark.parametrize("bad_date", ["2020-01-02T15:00:00", "2020-01-02T00:00:00+08:00", None])
def test_non_daily_or_missing_dates_are_rejected(tmp_path, bad_date):
    path = tmp_path/"prices.csv"
    pd.DataFrame({"date": [bad_date], "close": [1.]}).to_csv(path, index=False)
    with pytest.raises(ValueError, match="daily session"):
        read_table(path)


@pytest.mark.parametrize("profile", ["core", "paper"])
def test_parquet_and_csv_pipeline_agree_without_changing_provenance(tmp_path, model_config, profile):
    # The repository's synthetic generator is explicitly a test fixture, not a
    # fallback for absent licensed market data. Keep its provenance throughout.
    csv_source = synthetic_bundle(tmp_path/"csv", periods=650)
    parquet_source = tmp_path/"parquet"; parquet_source.mkdir()
    csv_manifest = json.loads((csv_source/"manifest.json").read_text())
    names = ["prices"] if profile == "core" else ["prices", "industry_panel", "stock_panel", "membership", "styles"]
    mapping = {}
    for name in names:
        frame = read_table(csv_source/f"{name}.csv")
        mapping[name] = f"{name}.parquet"
        frame.to_parquet(parquet_source/mapping[name], index=False)
    manifest = {**csv_manifest, **_manifest(parquet_source, mapping.values(), mapping)}
    (parquet_source/"manifest.json").write_text(json.dumps(manifest))
    assert verify_manifest(parquet_source)["is_synthetic"]
    config = ResearchConfig(data=DataConfig(end_date="2030-01-01"), model=model_config,
                            evaluation=EvaluationConfig(horizons=[5, 20, 60]))
    first = run_research(csv_source, tmp_path/"csv_output", config, profile, with_charts=False)
    second = run_research(parquet_source, tmp_path/"parquet_output", config, profile, with_charts=False)
    assert first["synthetic"] and second["synthetic"]
    csv_predictions = pd.read_csv(tmp_path/"csv_output/predictions.csv")
    parquet_predictions = pd.read_csv(tmp_path/"parquet_output/predictions.csv")
    pd.testing.assert_frame_equal(csv_predictions, parquet_predictions)
    saved = json.loads((tmp_path/"parquet_output/run_manifest.json").read_text())
    assert saved["dataset"]["source"] == "offline_test_fixture"
    assert saved["dataset"]["is_synthetic"] is True
    assert saved["dataset"]["logical_tables"] == mapping
