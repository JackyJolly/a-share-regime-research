#!/usr/bin/env python3
"""Run on a local machine with Ricequant entitlement and a working SDK connection.

Install this repository first. Read the license from RQDATAC_LICENSE_KEY or the
SDK's supported environment configuration; never pass the key on the command line.
This entry point only downloads real SDK responses. It never generates fixtures.

Example:
  python scripts/download_ricequant.py --config configs/paper.yaml \
      --output data/ricequant-paper --with-panels --format parquet
"""
import argparse
import getpass
import os
import sys
import warnings

from regime_research.cli import main as research_cli


def main(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--prompt-license", action="store_true")
    options, remaining = parser.parse_known_args(sys.argv[1:] if argv is None else argv)
    if not options.prompt_license:
        return research_cli(["fetch", *remaining])
    if not sys.stdin.isatty():
        print("License prompting requires an interactive terminal; use a secure environment variable otherwise.", file=sys.stderr)
        return 1
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            key = getpass.getpass("Ricequant license (hidden): ").strip()
    except (getpass.GetPassWarning, EOFError, KeyboardInterrupt):
        print("Could not read a hidden license; no download was attempted.", file=sys.stderr)
        return 1
    if not key:
        print("Empty license; no download was attempted.", file=sys.stderr)
        return 1
    previous = os.environ.get("RQDATAC_LICENSE_KEY")
    try:
        os.environ["RQDATAC_LICENSE_KEY"] = key
        return research_cli(["fetch", *remaining])
    finally:
        if previous is None:
            os.environ.pop("RQDATAC_LICENSE_KEY", None)
        else:
            os.environ["RQDATAC_LICENSE_KEY"] = previous


if __name__ == "__main__":
    raise SystemExit(main())
