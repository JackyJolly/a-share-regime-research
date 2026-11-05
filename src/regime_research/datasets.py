from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import tempfile
import importlib.util
from dataclasses import asdict
from contextlib import redirect_stdout, redirect_stderr
import numpy as np
import pandas as pd
from .data import synthetic_prices, fetch_ricequant, FIELDS


def new_directory(path):
    path = Path(path)
    if path.exists() and any(path.iterdir()):
        raise ValueError(f"Refusing to overwrite nonempty directory: {path}")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dataset_manifest(directory, metadata):
    from .storage import TABLE_NAMES
    directory = Path(directory)
    files = sorted(p for p in directory.iterdir() if p.suffix.lower() in {".csv", ".parquet"}
                   or p.name in {"quality_report.json", "quality_report.md"})
    tables = {}
    for path in files:
        if path.is_symlink() or not path.is_file():
            raise ValueError("Dataset tables must be ordinary files")
        if path.stem not in TABLE_NAMES:
            continue
        if path.stem in tables:
            raise ValueError(f"Ambiguous dataset table formats: {path.stem}")
        tables[path.stem] = path.name
    content = {**metadata, "created_utc": datetime.now(timezone.utc).isoformat(),
               "logical_tables": tables,
               "sha256": {p.name: _file_sha256(p) for p in files}}
    temporary = directory/".manifest.json.tmp"
    temporary.write_text(json.dumps(content, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    temporary.replace(directory/"manifest.json")
    return content


def synthetic_bundle(directory, periods=1800, seed=42):
    directory = new_directory(directory)
    market, states = synthetic_prices(periods, seed)
    market.to_csv(directory/"prices.csv")
    states.to_csv(directory/"synthetic_truth.csv")
    rng = np.random.default_rng(seed+1)
    industry_rows = []
    for j in range(8):
        r = market.close.pct_change().fillna(0).to_numpy()*.7 + rng.normal(.0001, .009, periods)
        close = 1000*np.exp(np.cumsum(r))
        industry_rows.append(pd.DataFrame({"date": market.index, "industry_id": f"SYNTH_SECTOR_{j}",
                                          "close": close, "total_turnover": rng.lognormal(21, .4, periods)}))
    pd.concat(industry_rows).to_csv(directory/"industry_panel.csv", index=False)
    stock_rows, member_rows = [], []
    for j in range(40):
        # Include listings and departures to exercise the historical membership contract.
        r = market.close.pct_change().fillna(0).to_numpy() + rng.normal(0, .015, periods)
        close = 20*np.exp(np.cumsum(r))
        start = j*3
        end = periods if j % 7 else periods-100
        close[:start] = np.nan
        close[end:] = np.nan
        stock_rows.append(pd.DataFrame({"date": market.index, "order_book_id": f"SYNTH_STOCK_{j}", "close": close}))
        eligible = (np.arange(periods) >= start+60) & (np.arange(periods) < end)
        member_rows.append(pd.DataFrame({"date": market.index, "order_book_id": f"SYNTH_STOCK_{j}",
                                        "eligible": eligible.astype(int)}))
    pd.concat(stock_rows).to_csv(directory/"stock_panel.csv", index=False)
    pd.concat(member_rows).to_csv(directory/"membership.csv", index=False)
    pd.DataFrame({"small_close": market.close*np.exp(np.cumsum(rng.normal(0, .004, periods))),
                  "large_close": market.close}, index=market.index).to_csv(directory/"styles.csv")
    dataset_manifest(directory, {"source": "synthetic", "is_synthetic": True, "seed": seed,
                                  "periods": periods, "industry_classification": "synthetic_fixed_8",
                                  "industry_contributions": "equal_weight_index_return_proxy",
                                  "calendar": "business_days_not_actual_exchange_calendar"})
    return directory


def init_ricequant():
    from .auth import initialize
    return initialize()


def _write_download_table(frame, directory, name, output_format, *, date_index=False):
    table = frame.rename_axis("date").reset_index() if date_index else frame
    path = directory/f"{name}.{output_format}"
    if output_format == "parquet":
        table.to_parquet(path, index=False, engine="pyarrow", compression="zstd")
    else:
        table.to_csv(path, index=False)


def _download_ricequant_tables(directory, cfg, with_panels, client, output_format):
    market = fetch_ricequant(cfg.order_book_id, cfg.start_date, cfg.end_date, client)
    _write_download_table(market, directory, "prices", output_format, date_index=True)
    if with_panels:
        industries = []
        for identifier in cfg.industry_ids:
            frame = fetch_ricequant(identifier, cfg.start_date, cfg.end_date, client)
            industries.append(frame[["close", "total_turnover"]].assign(industry_id=identifier).reset_index())
        _write_download_table(pd.concat(industries), directory, "industry_panel", output_format)
        small = fetch_ricequant(cfg.small_cap_id, cfg.start_date, cfg.end_date, client)
        large = fetch_ricequant(cfg.large_cap_id, cfg.start_date, cfg.end_date, client)
        _write_download_table(pd.DataFrame({"small_close": small.close, "large_close": large.close}),
                              directory, "styles", output_format, date_index=True)
        snapshots = {}
        for date in market.index:
            snapshots[date] = set(client.index_components(cfg.order_book_id, date=date.date()))
        instruments = sorted(set().union(*snapshots.values()))
        if not instruments:
            raise ValueError("No historical benchmark constituents")
        blocks = []
        for start in range(0, len(instruments), 200):
            batch = instruments[start:start+200]
            # Ratio-based breadth cancels common per-stock adjustment scaling.
            frame = client.get_price(batch, start_date=cfg.start_date, end_date=cfg.end_date,
                                     frequency="1d", fields=["close", "volume"], adjust_type="pre",
                                     expect_df=True)
            if frame is None or frame.empty:
                raise ValueError("Missing stock price batch")
            blocks.append(frame.reset_index())
        raw = pd.concat(blocks, ignore_index=True)
        close = raw.pivot(index="date", columns="order_book_id", values="close").reindex(market.index)
        volume = raw.pivot(index="date", columns="order_book_id", values="volume").reindex_like(close)
        members = pd.DataFrame(False, index=close.index, columns=close.columns)
        for date, ids in snapshots.items():
            missing = ids - set(close.columns)
            if missing:
                raise ValueError("Historical constituents missing from stock prices")
            members.loc[date, list(ids)] = True
        eligible = members & volume.gt(0) & close.rolling(60).count().eq(60)
        stock_panel = close.rename_axis(index="date", columns="order_book_id").stack(
            future_stack=True).rename("close").reset_index()
        membership = eligible.astype(int).rename_axis(index="date", columns="order_book_id").stack(
            future_stack=True).rename("eligible").reset_index()
        _write_download_table(stock_panel, directory, "stock_panel", output_format)
        _write_download_table(membership, directory, "membership", output_format)
    return market


def ricequant_bundle(directory, cfg, with_panels=False, client=None, output_format="csv", *, expected_sessions=None):
    """Download genuine SDK responses on the host running this command.

    A desktop can connect using its usual SDK transport; managed cloud network
    policy remains enforced by initialize(). Nothing substitutes synthetic data.
    Publish the destination atomically only after all tables and hashes validate.
    Failed downloads retain a separate marked staging directory, never a valid
    research dataset. Re-running needs a new empty output path; no implicit resume.
    """
    if output_format not in {"csv", "parquet"}:
        raise ValueError("output_format must be csv or parquet")
    if output_format == "parquet" and importlib.util.find_spec("pyarrow") is None:
        raise RuntimeError("Parquet output requires the parquet optional dependency (pyarrow)")
    if with_panels and (len(cfg.industry_ids) < 4 or cfg.industry_classification == "unspecified"):
        raise ValueError("Paper fetch requires >=4 licensed industry index IDs and a fixed classification name")
    destination = Path(directory)
    if destination.is_symlink() or (destination.exists() and
            (not destination.is_dir() or any(destination.iterdir()))):
        raise ValueError(f"Refusing to overwrite existing data: {destination}")
    client = client or init_ricequant()
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.download-", dir=destination.parent))
    marker = staging/"INCOMPLETE.json"
    marker.write_text(json.dumps({"status": "incomplete", "config": asdict(cfg),
                                  "output_format": output_format}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    try:
        # SDK diagnostics can include authentication details. Do not echo them.
        from .auth import _Discard
        sink = _Discard()
        with redirect_stdout(sink), redirect_stderr(sink):
            market = _download_ricequant_tables(staging, cfg, with_panels, client, output_format)
        from .quality import price_quality_report, write_quality_report
        report = price_quality_report(market, expected_sessions=expected_sessions)
        # fetch_ricequant always checks against the provider's requested calendar.
        report["checks"]["exact_requested_calendar"] = True
        report.update(source="ricequant", is_synthetic=False, market_index=cfg.order_book_id)
        write_quality_report(staging, report)
        dataset_manifest(staging, {"source": "ricequant", "is_synthetic": False,
                                  "acquisition": "rqdatac_sdk", "storage_format": output_format,
                                  "market_index": cfg.order_book_id, "start_date": cfg.start_date,
                                  "end_date": cfg.end_date, "price_fields": FIELDS,
                                  "session_count": len(market),
                                  "market_adjustment": "none_index", "profile": "paper_proxy" if with_panels else "core",
                                  "industry_classification": cfg.industry_classification,
                                  "industry_ids": cfg.industry_ids,
                                  "industry_contributions": "equal_weight_index_return_proxy_not_actual_contributions",
                                  "breadth_universe": "historical_benchmark_constituents",
                                  "stock_adjustment": "pre_ratio_based_features_only_frozen_snapshot",
                                  "membership_vintage": "historical_snapshots_not_verified_vendor_vintages",
                                  "stock_exclusions": "volume<=0 or <60 observed sessions; no ST exclusion"})
        marker.unlink()
        verify_manifest(staging)
        if destination.exists():
            destination.rmdir()  # Only the still-empty directory may be removed.
        staging.rename(destination)
    except Exception:
        if staging.exists():
            marker.write_text(json.dumps({"status": "incomplete", "config": asdict(cfg),
                                          "output_format": output_format}, ensure_ascii=False)+"\n", encoding="utf-8")
        raise RuntimeError(f"Ricequant download failed; partial files retained at {staging}. "
                           "No completed dataset was published; SDK details were suppressed.") from None
    return destination


def verify_manifest(directory):
    from .storage import resolve_table
    directory = Path(directory)
    if (directory/"INCOMPLETE.json").exists():
        raise ValueError("Incomplete download staging directory cannot be used for research")
    path = directory/"manifest.json"
    if not path.is_file():
        raise ValueError("Dataset manifest.json required; document source and file hashes")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Dataset manifest must be a JSON object")
    if not isinstance(manifest.get("source"), str) or not manifest["source"].strip():
        raise ValueError("Manifest must declare a nonempty source")
    if not isinstance(manifest.get("is_synthetic"), bool):
        raise ValueError("Manifest must explicitly declare is_synthetic as true or false")
    hashes = manifest.get("sha256", {})
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError("Manifest must contain table hashes")
    for name, digest in hashes.items():
        if (not isinstance(name, str) or not name or "/" in name or "\\" in name or
                ":" in name or Path(name).name != name or name in {".", ".."}):
            raise ValueError("Manifest filenames must be local basenames")
        if (not isinstance(digest, str) or len(digest) != 64 or
                any(c not in "0123456789abcdefABCDEF" for c in digest)):
            raise ValueError("Manifest SHA-256 digests must be 64 hexadecimal characters")
        table = directory/name
        if table.is_symlink() or not table.is_file() or table.resolve().parent != directory.resolve():
            raise ValueError(f"Dataset file is missing or not local: {name}")
        if _file_sha256(table) != digest.lower():
            raise ValueError(f"Dataset hash mismatch: {name}")
    resolve_table(directory, manifest, "prices")
    declared = manifest.get("logical_tables", {})
    if not isinstance(declared, dict):
        raise ValueError("Manifest logical_tables must be an object")
    for name in declared:
        resolve_table(directory, manifest, name)
    return manifest
