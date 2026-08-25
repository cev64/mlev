#!/usr/bin/env python3
"""Backfill raw data and rebuild the clean + feature layers for one sport.

    python run_backfill.py --sport nfl
    python run_backfill.py --sport epl --with-players
    python run_backfill.py --sport nfl --force          # refetch, ignore cache

Raw files are cached: a second run without --force re-uses what is on disk and
only rebuilds the derived layers. Any unavailable source aborts the run with an
explanation rather than producing a partial dataset.
"""

from __future__ import annotations

import argparse
import logging
import sys

from core.config import SPORTS, get_sport
from core.errors import MlevError
from core.registry import get_pipeline


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sport", required=True, choices=sorted(SPORTS))
    parser.add_argument(
        "--seasons", nargs="+", type=int, default=None,
        help="Seasons to pull (default: the sport's configured range).",
    )
    parser.add_argument(
        "--force", action="store_true", help="Refetch raw data even if cached."
    )
    parser.add_argument(
        "--with-players", action="store_true",
        help="EPL only: also fetch per-match player lines from Understat "
             "(one request per match, so it is slow the first time).",
    )
    parser.add_argument(
        "--player-seasons", nargs="+", type=int, default=None,
        help="EPL only: restrict the player backfill to these seasons.",
    )
    parser.add_argument("--skip-features", action="store_true", help="Ingest and clean only.")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    config = get_sport(args.sport)
    seasons = args.seasons or config.seasons
    pipeline = get_pipeline(args.sport)

    ingest_kwargs = {"force": args.force}
    if args.sport == "epl":
        ingest_kwargs["with_players"] = args.with_players
        ingest_kwargs["player_seasons"] = args.player_seasons
    elif args.with_players or args.player_seasons:
        logging.warning("--with-players/--player-seasons only apply to EPL; ignoring")

    logging.info("[1/3] ingest %s seasons %s-%s", config.label, seasons[0], seasons[-1])
    pipeline.ingest(seasons, **ingest_kwargs)

    logging.info("[2/3] clean")
    pipeline.clean()

    if args.skip_features:
        logging.info("--skip-features set; stopping before the feature build")
        return 0

    logging.info("[3/3] features")
    games = pipeline.build_game_features()
    logging.info("game features: %s rows", len(games))
    try:
        players = pipeline.build_player_features()
        logging.info("player features: %s rows", len(players))
    except MlevError as exc:
        logging.warning("player features unavailable: %s", exc)

    logging.info("done — data written under %s", config.path("features").parent)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MlevError as exc:
        logging.error("%s", exc)
        sys.exit(2)
