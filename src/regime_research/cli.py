import argparse
from dataclasses import replace
import json
import sys
from .config import ResearchConfig
from .datasets import synthetic_bundle, ricequant_bundle
from .pipeline import run_research


def parser():
    p = argparse.ArgumentParser(description="Ricequant A-share regime research; no fabricated empirical claims")
    sub = p.add_subparsers(dest="command", required=True)
    synthetic = sub.add_parser("synthetic", help="Generate synthetic integration data, NOT historical evidence")
    synthetic.add_argument("--output", required=True)
    synthetic.add_argument("--periods", type=int, default=1800)
    synthetic.add_argument("--seed", type=int, default=42)
    fetch = sub.add_parser("fetch", help="Authenticated Ricequant data download (licensed account required)")
    fetch.add_argument("--config", default="configs/baseline.yaml")
    fetch.add_argument("--output", required=True)
    fetch.add_argument("--format", choices=["csv", "parquet"], default="csv",
                       help="Downloaded table format; Parquet requires pyarrow")
    fetch.add_argument("--with-panels", action="store_true", help="Historical daily constituents and configured sector indices; potentially large")
    run = sub.add_parser("run", help="Run chronological research and write reproducible artifacts")
    run.add_argument("--config", default="configs/baseline.yaml")
    run.add_argument("--data", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--profile", choices=["core", "paper"], default="core")
    run.add_argument("--model", choices=["gmm", "hmm"])
    run.add_argument("--no-charts", action="store_true")
    inspect = sub.add_parser("validate-data", help="Verify local CSV/Parquet hashes and OHLCV; no network or model fitting")
    inspect.add_argument("--data", required=True)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "synthetic":
            result = {"dataset": str(synthetic_bundle(args.output, args.periods, args.seed)), "synthetic": True}
        elif args.command == "fetch":
            cfg = ResearchConfig.load(args.config)
            # SDK failures may contain server/authentication details. Do not print them.
            try:
                path = ricequant_bundle(args.output, cfg.data, args.with_panels, output_format=args.format)
            except (ValueError, RuntimeError):
                raise
            except Exception:
                raise RuntimeError("Ricequant request failed; inspect account entitlement and network configuration securely") from None
            result = {"dataset": str(path), "source": "ricequant"}
        elif args.command == "validate-data":
            from .quality import inspect_dataset
            result = inspect_dataset(args.data)
        else:
            cfg = ResearchConfig.load(args.config)
            if args.model:
                cfg = replace(cfg, model=replace(cfg.model, model_type=args.model))
            result = run_research(args.data, args.output, cfg, args.profile, not args.no_charts)
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
