from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import numpy as np
import pandas as pd
from .data import synthetic_prices, fetch_ricequant, FIELDS


def new_directory(path):
    path = Path(path)
    if path.exists() and any(path.iterdir()):
        raise ValueError(f"Refusing to overwrite nonempty directory: {path}")
    path.mkdir(parents=True, exist_ok=True)
    return path


def dataset_manifest(directory, metadata):
    directory = Path(directory)
    content = {**metadata, "created_utc": datetime.now(timezone.utc).isoformat(),
               "sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted(directory.glob("*.csv"))}}
    (directory/"manifest.json").write_text(json.dumps(content, ensure_ascii=False, indent=2)+"\n")
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
    try:
        import rqdatac
    except ImportError:
        raise RuntimeError("Install .[ricequant] in an isolated environment") from None
    username, password = os.getenv("RQDATAC_USERNAME"), os.getenv("RQDATAC_PASSWORD")
    has_uri = bool(os.getenv("RQDATAC_CONF") or os.getenv("RQDATAC2_CONF"))
    if not (username and password) and not has_uri:
        raise RuntimeError("Set RQDATAC_USERNAME and RQDATAC_PASSWORD securely; no values in chat or Git")
    try:
        # Preserve SDK-native authentication and transport configuration if present.
        if username and password:
            rqdatac.init(username, password, auto_load_plugins=False)
        else:
            rqdatac.init(auto_load_plugins=False)
    except Exception:
        raise RuntimeError("Ricequant init failed; check entitlement, credentials and SDK transport") from None
    return rqdatac


def ricequant_bundle(directory, cfg, with_panels=False, client=None):
    """Historical daily membership is intentionally opt-in and potentially costly.

    Industry IDs must be supplied from the user's licensed, fixed-version catalog.
    Breadth uses the benchmark's HISTORICAL constituents, not all A shares by fiat.
    """
    if with_panels and (len(cfg.industry_ids) < 4 or cfg.industry_classification == "unspecified"):
        raise ValueError("Paper fetch requires >=4 licensed industry index IDs and a fixed classification name")
    client = client or init_ricequant()
    market = fetch_ricequant(cfg.order_book_id, cfg.start_date, cfg.end_date, client)
    directory = new_directory(directory)
    market.to_csv(directory/"prices.csv")
    if with_panels:
        industries = []
        for identifier in cfg.industry_ids:
            frame = fetch_ricequant(identifier, cfg.start_date, cfg.end_date, client)
            industries.append(frame[["close", "total_turnover"]].assign(industry_id=identifier).reset_index())
        pd.concat(industries).to_csv(directory/"industry_panel.csv", index=False)
        small = fetch_ricequant(cfg.small_cap_id, cfg.start_date, cfg.end_date, client)
        large = fetch_ricequant(cfg.large_cap_id, cfg.start_date, cfg.end_date, client)
        pd.DataFrame({"small_close": small.close, "large_close": large.close}).to_csv(directory/"styles.csv")
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
        close.rename_axis(index="date", columns="order_book_id").stack(dropna=False).rename("close").to_csv(directory/"stock_panel.csv")
        eligible.astype(int).rename_axis(index="date", columns="order_book_id").stack().rename("eligible").to_csv(directory/"membership.csv")
    dataset_manifest(directory, {"source": "ricequant", "is_synthetic": False,
                                  "market_index": cfg.order_book_id, "start_date": cfg.start_date,
                                  "end_date": cfg.end_date, "price_fields": FIELDS,
                                  "market_adjustment": "none_index", "profile": "paper_proxy" if with_panels else "core",
                                  "industry_classification": cfg.industry_classification,
                                  "industry_ids": cfg.industry_ids,
                                  "industry_contributions": "equal_weight_index_return_proxy_not_actual_contributions",
                                  "breadth_universe": "historical_benchmark_constituents",
                                  "stock_adjustment": "pre_ratio_based_features_only_frozen_snapshot",
                                  "membership_vintage": "historical_snapshots_not_verified_vendor_vintages",
                                  "stock_exclusions": "volume<=0 or <60 observed sessions; no ST exclusion"})
    return directory


def verify_manifest(directory):
    directory = Path(directory)
    path = directory/"manifest.json"
    if not path.is_file():
        raise ValueError("Dataset manifest.json required; document source and file hashes")
    manifest = json.loads(path.read_text())
    hashes = manifest.get("sha256", {})
    if "prices.csv" not in hashes:
        raise ValueError("Manifest must include prices.csv")
    for name, digest in hashes.items():
        if Path(name).name != name:
            raise ValueError("Manifest filenames must be local basenames")
        if hashlib.sha256((directory/name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Dataset hash mismatch: {name}")
    return manifest
