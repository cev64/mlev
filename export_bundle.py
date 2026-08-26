#!/usr/bin/env python3
"""Export prediction bundles for the Android app.

    python export_bundle.py                    # both sports, next fixtures
    python export_bundle.py --sport nfl --season 2026 --week 1
    python export_bundle.py --sport epl --fixtures my_fixtures.csv
    python export_bundle.py --out dist/        # where CI publishes from

A bundle is the phone's whole world: it carries each fixture's predictive
distribution, so the app can compute any market at any line offline, with no
connection to this machine. See core/bundle.py for why it exports distribution
parameters rather than a fixed list of probabilities.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

from core.bundle import build_bundle, write_bundle
from core.config import SPORTS, get_sport
from core.errors import MlevError
from core.registry import get_pipeline

log = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--sport", choices=sorted(SPORTS), default=None,
                        help="Default: both.")
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument("--week", type=int, default=None, help="NFL only.")
    parser.add_argument("--fixtures", type=Path, default=None, help="EPL only.")
    parser.add_argument("--out", type=Path, default=Path("dist"),
                        help="Directory to write bundles into (default: dist/).")
    parser.add_argument("--index", action="store_true",
                        help="Also write index.json listing the bundles.")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def score_upcoming(sport: str, args: argparse.Namespace) -> pd.DataFrame:
    """Reuse exactly the selection logic the scoring job uses."""
    from run_scoring import _epl_upcoming, _select_upcoming

    pipeline = get_pipeline(sport)
    features = pipeline.build_game_features()

    if sport == "epl":
        namespace = argparse.Namespace(
            sport="epl", season=args.season, week=None, fixtures=args.fixtures
        )
        upcoming = _epl_upcoming(pipeline, features, namespace)
    else:
        namespace = argparse.Namespace(sport="nfl", season=args.season, week=args.week)
        upcoming = _select_upcoming(features, pipeline.outcome_columns("game"), namespace)

    if upcoming.empty:
        raise MlevError(f"no unplayed {sport.upper()} fixtures matched the filters")
    return pipeline.train_and_score("game", upcoming=upcoming)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(message)s",
    )

    sports = [args.sport] if args.sport else list(SPORTS)
    written: list[dict] = []

    for sport in sports:
        config = get_sport(sport)
        try:
            scored = score_upcoming(sport, args)
            bundle = build_bundle(sport, scored)
        except MlevError as exc:
            # One sport being between seasons must not stop the other exporting.
            log.warning("skipping %s: %s", config.label, exc)
            print(f"  {config.label}: skipped — {exc}")
            continue

        path = write_bundle(bundle, args.out / f"{sport}.json")
        written.append(
            {
                "sport": sport,
                "label": config.label,
                "file": path.name,
                "generated_at": bundle["generated_at"],
                "fixtures": len(bundle["fixtures"]),
                "schema": bundle["schema"],
                "bytes": path.stat().st_size,
            }
        )
        print(
            f"  {config.label}: {len(bundle['fixtures'])} fixtures "
            f"-> {path} ({path.stat().st_size / 1024:.1f} KB)"
        )

    if not written:
        print("\nNothing exported. Both sports are between fixtures, or the "
              "schedule needs refreshing (run run_backfill.py).")
        return 1

    if args.index or len(sports) > 1:
        index = args.out / "index.json"
        index.write_text(
            json.dumps({"schema": written[0]["schema"], "bundles": written}, indent=2),
            encoding="utf-8",
        )
        print(f"  index -> {index}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MlevError as exc:
        logging.error("%s", exc)
        sys.exit(2)
