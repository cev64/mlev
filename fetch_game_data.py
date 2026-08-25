#!/usr/bin/env python3
"""Pull NFL data from nflverse.

    python fetch_game_data.py                       # current + previous season
    python fetch_game_data.py --seasons 2016 2025   # an explicit range
    python fetch_game_data.py --full-backfill       # everything the models need

This is the original single-purpose fetch script, kept because it is a handy way
to grab a season or two without running the whole pipeline. For the modelling
work, `run_backfill.py --sport nfl` is the entrypoint: it calls the same ingest
code and then builds the clean and feature layers on top.
"""

from __future__ import annotations

import argparse
import logging
import sys

from core.config import NFL, ensure_layers
from core.errors import MlevError
from sports.nfl import ingest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seasons", nargs="+", type=int, default=None)
    parser.add_argument(
        "--full-backfill", action="store_true",
        help=f"Pull every season the models train on ({NFL.first_season}-{NFL.last_season}).",
    )
    parser.add_argument("--force", action="store_true", help="Refetch even if cached.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ensure_layers(NFL)

    if args.full_backfill:
        seasons = NFL.seasons
    elif args.seasons:
        seasons = (
            list(range(args.seasons[0], args.seasons[1] + 1))
            if len(args.seasons) == 2 and args.seasons[1] > args.seasons[0]
            else args.seasons
        )
    else:
        seasons = NFL.seasons[-2:]

    written = ingest.backfill(NFL, seasons, force=args.force)
    for name, path in written.items():
        logging.info("%-16s -> %s", name, path)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MlevError as exc:
        logging.error("%s", exc)
        sys.exit(2)
