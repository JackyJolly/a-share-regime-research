from dataclasses import replace
import json
import pytest
from regime_research.config import ResearchConfig, DataConfig, EvaluationConfig
from regime_research.datasets import synthetic_bundle
from regime_research.pipeline import run_research
from regime_research.cli import main


@pytest.mark.parametrize("profile", ["core", "paper"])
def test_offline_end_to_end(tmp_path, model_config, profile):
    source = synthetic_bundle(tmp_path/"data", periods=650)
    cfg = ResearchConfig(data=DataConfig(end_date="2030-01-01"), model=model_config,
                         evaluation=EvaluationConfig(horizons=[5, 20, 60]))
    output = tmp_path/"outputs"
    result = run_research(source, output, cfg, profile, with_charts=False)
    assert result["predictions"] > 100 and result["synthetic"]
    manifest = json.loads((output/"run_manifest.json").read_text())
    assert manifest["dataset"]["is_synthetic"]
    assert (output/"historical_analogs.csv").exists()
    metrics = json.loads((output/"metrics.json").read_text())
    if profile == "paper":
        assert len(metrics["industry_strategies"]) == 9
        assert len(metrics["style_strategies"]) == 3


def test_cli_reports_missing_config_without_success(capsys):
    assert main(["run", "--config", "missing.yaml", "--data", "missing", "--output", "unused"]) == 1
    assert json.loads(capsys.readouterr().err)["ok"] is False
