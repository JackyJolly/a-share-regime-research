"""Offline OHLCV quality checks; passing checks do not establish trading efficacy."""
from datetime import datetime, timezone
from pathlib import Path
import json

from .data import FIELDS, read_prices, validate_prices
from .features import make_features
from .storage import resolve_table


def price_quality_report(prices, *, expected_sessions=None):
    prices = validate_prices(prices)
    if expected_sessions is not None and not prices.index.equals(expected_sessions):
        raise ValueError("Downloaded prices do not match the exact requested trading sessions")
    usable = len(make_features(prices).dropna())
    return {
        "status": "passed",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "rows": len(prices),
        "start_date": prices.index[0].date().isoformat(),
        "end_date": prices.index[-1].date().isoformat(),
        "fields": FIELDS,
        "checks": {
            "unique_increasing_daily_dates": True,
            "missing_values": 0,
            "nonfinite_values": 0,
            "positive_ohlc": True,
            "valid_ohlc_bounds": True,
            "nonnegative_volume_and_turnover": True,
            "exact_requested_calendar": True if expected_sessions is not None else None,
        },
        "zero_volume_rows": int(prices.volume.eq(0).sum()),
        "zero_turnover_rows": int(prices.total_turnover.eq(0).sum()),
        "usable_core_feature_rows": usable,
        "research_note": (
            "This is a data/reader check, not an empirical result. Core features require "
            "252 sessions of warm-up; the baseline also needs 504 training feature rows "
            "plus out-of-sample observations. A 60-session sample is insufficient."
        ),
    }


def write_quality_report(directory, report):
    directory = Path(directory)
    (directory / "quality_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# OHLCV data quality", "", f"Status: {report['status']}",
             f"Rows: {report['rows']}",
             f"Dates: {report['start_date']} to {report['end_date']}",
             f"Complete core feature rows: {report['usable_core_feature_rows']}", "",
             "Checks:", ""]
    lines.extend(f"- {name}: {value}" for name, value in report["checks"].items())
    lines.extend(["", f"Zero volume rows: {report['zero_volume_rows']}",
                  f"Zero turnover rows: {report['zero_turnover_rows']}", "",
                  "Source metadata is a provenance declaration, not independent verification.",
                  report["research_note"], ""])
    (directory / "quality_report.md").write_text("\n".join(lines), encoding="utf-8")


def inspect_dataset(directory):
    """Load through the same manifest and price reader used by run_research; no SDK."""
    from .datasets import verify_manifest
    source = verify_manifest(directory)
    prices = read_prices(resolve_table(directory, source, "prices"))
    report = price_quality_report(prices)
    report.update(source=source["source"], is_synthetic=source["is_synthetic"],
                  market_index=source.get("market_index"), hash_verified=True)
    return report
