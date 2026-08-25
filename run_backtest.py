#!/usr/bin/env python3
"""Walk-forward backtest for one sport.

    python run_backtest.py --sport nfl
    python run_backtest.py --sport nfl --level player
    python run_backtest.py --sport epl --first-test-season 2020

Trains on every season before the test season, predicts the test season, rolls
forward, and reports calibration and accuracy. No market data is involved, so
there is no ROI here by design — the question is whether the model is right and
whether its stated probabilities mean what they say.

Results are written to data/<sport>/models/ for later comparison.
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
    parser.add_argument("--level", default="game", choices=("game", "player"))
    parser.add_argument("--first-test-season", type=int, default=None)
    parser.add_argument(
        "--min-train-seasons", type=int, default=2,
        help="Seasons of history required before the first test fold.",
    )
    parser.add_argument("--save-predictions", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(message)s",
    )
    config = get_sport(args.sport)
    pipeline = get_pipeline(args.sport)

    kwargs = {"min_train_seasons": args.min_train_seasons}
    if args.first_test_season is not None:
        kwargs["first_test_season"] = args.first_test_season

    result = pipeline.backtest(args.level, **kwargs)

    header = f"{config.label} — {args.level}-level walk-forward backtest"
    print(header)
    print("=" * len(header))
    print(result.describe())

    stem = f"backtest_{args.level}"
    result.overall.to_csv(config.path("models", f"{stem}_overall.csv"), index=False)
    result.by_season.to_csv(config.path("models", f"{stem}_by_season.csv"), index=False)
    if not result.calibration.empty:
        result.calibration.to_csv(config.path("models", f"{stem}_calibration.csv"), index=False)
    if args.save_predictions:
        result.predictions.to_csv(config.path("models", f"{stem}_predictions.csv"), index=False)
    print(f"\nmetrics written to {config.path('models')}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MlevError as exc:
        logging.error("%s", exc)
        sys.exit(2)
