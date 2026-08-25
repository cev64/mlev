#!/usr/bin/env python3
"""Score the upcoming week (NFL) or matchday (EPL).

    python run_scoring.py --sport nfl                    # next unplayed week
    python run_scoring.py --sport nfl --week 1 --season 2026
    python run_scoring.py --sport epl
    python run_scoring.py --sport epl --fixtures my_fixtures.csv
    python run_scoring.py --sport nfl --level player

Trains on every completed row available, then predicts the fixtures that have
not been played. Output is a CSV under data/<sport>/predictions/ where every
row carries a probability or a distribution (mean, sd, decile bounds, and
P(over line) for the standard lines) rather than a single point pick.

No book lines are read and no EV is computed — that is deliberately a later
phase. These are the model's own numbers.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from core.config import SPORTS, get_sport
from core.errors import MissingDataError, MlevError
from core.io import write_predictions
from core.registry import get_pipeline

log = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sport", required=True, choices=sorted(SPORTS))
    parser.add_argument("--level", default="game", choices=("game", "player"))
    parser.add_argument("--season", type=int, default=None, help="Restrict to one season.")
    parser.add_argument("--week", type=int, default=None, help="NFL only: restrict to one week.")
    parser.add_argument(
        "--fixtures", type=Path, default=None,
        help="EPL only: a CSV of fixtures to score (columns HomeTeam, AwayTeam, Date). "
             "Use when football-data's rolling feed is between matchdays.",
    )
    parser.add_argument("--out", type=Path, default=None, help="Override the output path.")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def _select_upcoming(
    features: pd.DataFrame, outcome_cols: list[str], args: argparse.Namespace
) -> pd.DataFrame:
    """Unplayed rows, optionally narrowed to one season/week."""
    pending = features[features[outcome_cols].isna().all(axis=1)].copy()
    if args.season is not None:
        pending = pending[pending["season"] == args.season]
    if args.week is not None:
        if "week" not in pending.columns:
            raise MissingDataError(f"--week is not meaningful for {args.sport}")
        pending = pending[pending["week"] == args.week]
    elif not pending.empty and "week" in pending.columns:
        # Default to the single earliest unplayed week rather than the whole
        # remaining season: scoring week 14 off week 1's form is meaningless,
        # because the features for those rows do not exist yet.
        first = pending.sort_values("kickoff").iloc[0]
        pending = pending[
            (pending["season"] == first["season"]) & (pending["week"] == first["week"])
        ]
    return pending


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(message)s",
    )
    config = get_sport(args.sport)
    pipeline = get_pipeline(args.sport)

    features = (
        pipeline.build_game_features()
        if args.level == "game"
        else pipeline.build_player_features()
    )
    outcome_cols = pipeline.outcome_columns(args.level)

    if args.sport == "epl" and args.level == "game":
        upcoming = _epl_upcoming(pipeline, features, args)
    else:
        upcoming = _select_upcoming(features, outcome_cols, args)

    if upcoming.empty:
        raise MissingDataError(
            f"no unplayed {config.label} {args.level} rows match the requested "
            "filters. Check --season/--week, or re-run run_backfill.py to pick "
            "up a newly published schedule."
        )

    scored = pipeline.train_and_score(args.level, upcoming=upcoming)
    view = pipeline.prediction_view(scored, args.level)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = args.out or config.path("predictions", f"{args.level}_{stamp}.csv")
    write_predictions(view, out)

    print(f"{config.label}: {len(view)} {args.level} predictions -> {out}\n")
    with pd.option_context("display.width", 200, "display.max_columns", 24):
        print(view.head(20).to_string(index=False))
    if len(view) > 20:
        print(f"... {len(view) - 20} more rows in the CSV")
    return 0


def _epl_upcoming(pipeline, features: pd.DataFrame, args) -> pd.DataFrame:
    """Build feature rows for EPL fixtures that have no result yet.

    football-data publishes results only once matches are played, so upcoming
    fixtures arrive from a separate feed (or a user-supplied CSV) and have to be
    given the same rolling features as a historical row — computed from every
    completed match to date, which is exactly the point-in-time position a real
    matchday scoring run is in.
    """
    from sports.epl import features as epl_features
    from sports.epl.teams import CLUB_ALIAS_MAP
    from core.naming import normalize_series, unmapped_names

    if args.fixtures is not None:
        raw = pd.read_csv(args.fixtures)
    else:
        raw = pipeline.upcoming_fixtures()

    for column in ("HomeTeam", "AwayTeam"):
        if column not in raw.columns:
            raise MissingDataError(
                f"fixture source is missing a {column!r} column; expected the "
                "football-data layout (Date, HomeTeam, AwayTeam)."
            )
    missing = unmapped_names(
        pd.concat([raw["HomeTeam"], raw["AwayTeam"]]), CLUB_ALIAS_MAP
    )
    if missing:
        raise MissingDataError(
            f"fixture list names clubs with no canonical mapping: {missing}. "
            "Add them to sports/epl/teams.py."
        )

    fixtures = pd.DataFrame(
        {
            "home_team": normalize_series(raw["HomeTeam"], CLUB_ALIAS_MAP),
            "away_team": normalize_series(raw["AwayTeam"], CLUB_ALIAS_MAP),
            "kickoff": pd.to_datetime(raw["Date"], dayfirst=True, errors="coerce"),
        }
    )
    if fixtures["kickoff"].isna().any():
        raise MissingDataError("some fixture dates could not be parsed; expected dd/mm/yyyy")

    season = args.season if args.season is not None else _season_of(fixtures["kickoff"].min())
    fixtures["season"] = season
    fixtures["match_id"] = (
        fixtures["season"].astype(str)
        + "_"
        + fixtures["kickoff"].dt.strftime("%Y%m%d")
        + "_upcoming"
    )
    for col in pipeline.outcome_columns("game"):
        fixtures[col] = float("nan")

    # Give the fixtures the same rolling-form columns the historical rows have,
    # derived from completed matches only.
    played = features.dropna(subset=["home_goals"])
    combined = pd.concat([played, fixtures], ignore_index=True)
    log.info("scoring %s upcoming fixtures against %s completed matches", len(fixtures), len(played))
    return combined.tail(len(fixtures)).copy()


def _season_of(kickoff: pd.Timestamp) -> int:
    """A fixture in Jan-Jun belongs to the season that started the year before."""
    return int(kickoff.year - 1 if kickoff.month <= 6 else kickoff.year)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MlevError as exc:
        logging.error("%s", exc)
        sys.exit(2)
