"""Local real CSI 300 sample acquisition. Never generates replacement data."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta, timezone
import json
import os
import sys

import pandas as pd

from .auth import _Discard, initialize
from .config import DataConfig
from .datasets import ricequant_bundle


def download_sample(directory, end_date=None, client=None, today=None):
    """Select the last 60 CN sessions through yesterday (Shanghai date by default).

    A supplied client is for offline contract tests and must already be initialized.
    Explicit cutoffs must also precede today; we never request an unfinished daily bar.
    """
    today = today or datetime.now(timezone(timedelta(hours=8))).date()
    cutoff = date.fromisoformat(end_date) if end_date else today - timedelta(days=1)
    if cutoff >= today:
        raise ValueError("end-date must precede today's Shanghai date; exclude unfinished daily bars")
    if client is None:
        if not os.environ.get("RQDATAC_LICENSE_KEY"):
            raise RuntimeError("Set RQDATAC_LICENSE_KEY in the local process environment before downloading")
        client = initialize()
    start = cutoff - timedelta(days=370)
    try:
        # Suppress arbitrary SDK diagnostics, including exception text.
        with redirect_stdout(_Discard()), redirect_stderr(_Discard()):
            dates = client.get_trading_dates(start.isoformat(), cutoff.isoformat(), market="cn")
    except Exception:
        raise RuntimeError("Ricequant calendar request failed; check local connectivity and entitlement") from None
    calendar = pd.DatetimeIndex(pd.to_datetime(dates), name="date")
    if (len(calendar) < 60 or calendar.hasnans or calendar.has_duplicates or
            not calendar.is_monotonic_increasing or calendar.tz is not None or
            (calendar != calendar.normalize()).any() or
            calendar[0].date() < start or calendar[-1].date() > cutoff):
        raise ValueError("Ricequant returned an invalid or insufficient trading calendar")
    sessions = calendar[-60:]
    cfg = DataConfig(order_book_id="000300.XSHG", start_date=sessions[0].date().isoformat(),
                     end_date=sessions[-1].date().isoformat())
    return ricequant_bundle(directory, cfg, client=client, output_format="parquet",
                            expected_sessions=sessions)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Download 60 completed CSI 300 trading sessions to Parquet")
    parser.add_argument("--output", default="data/hs300-60")
    parser.add_argument("--end-date", help="Optional inclusive YYYY-MM-DD cutoff, strictly before today in Shanghai")
    args = parser.parse_args(argv)
    try:
        output = download_sample(args.output, args.end_date)
    except Exception:
        # Even vendor exceptions and local paths must not inadvertently echo secrets.
        print(json.dumps({"ok": False, "error": (
            "Sample download failed. Check RQDATAC_LICENSE_KEY presence, TCP access, "
            "account entitlement, a past cutoff and an empty output path. "
            "No completed sample was published; SDK details suppressed."
        )}), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "dataset": str(output), "source": "ricequant",
                      "market_index": "000300.XSHG", "sessions": 60}))
    return 0
