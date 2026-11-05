from dataclasses import replace
from pathlib import Path
import pandas as pd
from .config import ResearchConfig
from .data import read_prices
from .datasets import verify_manifest, new_directory
from .features import make_features
from .panels import combined_features
from .model import walk_forward, initial_bic_diagnostic
from .evaluation import forward_outcomes, state_statistics, transition_statistics, timing_strategy, rule_baseline
from .similarity import historical_analogs
from .reporting import run_manifest, write_json, charts, markdown_report
from .inference import incremental_regressions
from .storage import resolve_table, read_table


def run_research(data_dir, output_dir, cfg: ResearchConfig, profile="core", with_charts=True):
    data_dir = Path(data_dir)
    source = verify_manifest(data_dir)
    prices = read_prices(resolve_table(data_dir, source, "prices"))
    # Honor configured sample bounds even for imported CSVs or synthetic fixtures.
    prices = prices.loc[cfg.data.start_date:cfg.data.end_date]
    if prices.empty:
        raise ValueError("No data in configured sample dates")
    if profile == "paper":
        paths = {name: resolve_table(data_dir, source, name)
                 for name in ["industry_panel", "stock_panel", "membership", "styles"]}
        if not source.get("industry_classification") or source.get("industry_classification") == "unspecified":
            raise ValueError("Paper profile requires an explicit industry classification")
        industries = read_table(paths["industry_panel"])
        stocks = read_table(paths["stock_panel"])
        membership = read_table(paths["membership"])
        styles = read_table(paths["styles"], date_index=True)
        features = combined_features(prices, industries, stocks, membership, styles)
    elif profile == "core":
        features = make_features(prices)
    else:
        raise ValueError("profile must be core or paper")
    result = walk_forward(features, cfg.model)
    bic = initial_bic_diagnostic(features, cfg.model)
    outcomes = forward_outcomes(prices, cfg.evaluation.horizons)
    stats = state_statistics(result.predictions, outcomes, cfg.evaluation.horizons, cfg.model.n_states)
    regressions = incremental_regressions(features, result.predictions, outcomes, cfg.evaluation.horizons)
    counts, transition = transition_statistics(result.predictions, cfg.model.n_states)
    backtest, metrics = timing_strategy(prices, result.predictions, cfg.evaluation)
    rule = rule_baseline(features, cfg.model)
    rule_backtest, metrics["rule_baseline"] = timing_strategy(prices, rule, cfg.evaluation)
    analogs = historical_analogs(features, prices, cfg.model)
    manifest = run_manifest(cfg, source, profile, features.columns)
    manifest["numerical_health"] = {
        "unconverged_fits": int((~result.fits.converged.astype(bool)).sum()),
        "small_component_fits": int(result.fits.small_component_warning.sum()),
    }
    output = new_directory(output_dir)
    tables = {"features": features, "predictions": result.predictions, "fits": result.fits,
              "centroids": result.centroids, "bic_initial": bic, "forward_outcomes": outcomes,
              "state_statistics": stats, "transitions_counts": counts, "transitions_probabilities": transition,
              "backtest": backtest, "rule_predictions": rule, "rule_backtest": rule_backtest,
              "historical_analogs": analogs}
    regressions.to_csv(output/"incremental_hac_regressions.csv", index=False)
    for name, frame in tables.items():
        frame.to_csv(output/f"{name}.csv", index=name not in {"fits", "centroids", "bic_initial", "state_statistics", "historical_analogs"})
    if profile == "paper":
        from .strategies import industry_strategy_comparison, style_strategy_comparison
        # Fit-unrelated, predeclared portfolios; same OOS decision dates for all.
        portfolios, industry_metrics = industry_strategy_comparison(industries, result.predictions, cfg.evaluation, rule=rule)
        style_portfolios, style_metrics = style_strategy_comparison(styles, result.predictions, rule, cfg.evaluation)
        portfolios.update(style_portfolios)
        for name, frame in portfolios.items():
            frame.to_csv(output/f"{name}.csv")
        metrics["industry_strategies"] = industry_metrics
        metrics["style_strategies"] = style_metrics
    write_json(output/"metrics.json", metrics)
    write_json(output/"run_manifest.json", manifest)
    if with_charts:
        charts(output, prices, features, result, backtest, bool(source.get("is_synthetic")))
    markdown_report(output, result, manifest, metrics)
    return {"output_dir": str(output), "predictions": len(result.predictions), "fits": len(result.fits),
            "synthetic": bool(source.get("is_synthetic")), "profile": profile, "model": cfg.model.model_type}
