"""Clean and join the EPL raw layer.

Two sources have to be reconciled: football-data.co.uk (results, shots, cards)
and Understat (xG). They share no ID, so the join is on **canonical team names
plus date**, which is where the name normalisation in `sports.epl.teams` earns
its keep.

Kickoff times differ between the two sources for the same fixture (timezone and
rescheduling), so the join allows a +/- 1 day tolerance on the date while
requiring an exact match on both team names. That is tight enough to be
unambiguous — a given pair of clubs plays at home to each other once per season.

Produces:
* `matches`       — one row per match, both sources joined.
* `team_matches`  — two rows per match, the long shape rolling features need.
* `player_matches`— per-player per-match lines, when the player backfill has run.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from core.config import SportConfig
from core.errors import DataSourceError
from core.io import read_table, write_table
from core.naming import normalize_series, slugify, unmapped_names
from sports.epl.teams import CLUB_ALIAS_MAP

log = logging.getLogger(__name__)

# football-data column -> our name. Everything not listed is dropped, including
# every bookmaker odds column: market data is deliberately out of scope, and
# leaving it in the clean layer invites it into a feature by accident.
RESULT_COLUMNS = {
    "Date": "date_raw",
    "Time": "time_raw",
    "HomeTeam": "home_team_raw",
    "AwayTeam": "away_team_raw",
    "FTHG": "home_goals",
    "FTAG": "away_goals",
    "FTR": "result",
    "HTHG": "home_goals_ht",
    "HTAG": "away_goals_ht",
    "HS": "home_shots",
    "AS": "away_shots",
    "HST": "home_shots_on_target",
    "AST": "away_shots_on_target",
    "HC": "home_corners",
    "AC": "away_corners",
    "HF": "home_fouls",
    "AF": "away_fouls",
    "HY": "home_yellows",
    "AY": "away_yellows",
    "HR": "home_reds",
    "AR": "away_reds",
    "Referee": "referee",
}

JOIN_TOLERANCE_DAYS = 1

# football-data switched from two-digit to four-digit years partway through the
# archive, so both appear across a multi-season backfill. Parse each explicitly
# and coalesce rather than letting pandas infer per row -- inference on
# ambiguous dd/mm/yy values is exactly how a season silently lands in 2015
# instead of 2014.
DATE_FORMATS = ("%d/%m/%Y", "%d/%m/%y")


def _parse_dates(raw: pd.Series) -> pd.Series:
    parsed = pd.Series(pd.NaT, index=raw.index, dtype="datetime64[ns]")
    for fmt in DATE_FORMATS:
        remaining = parsed.isna()
        if not remaining.any():
            break
        parsed.loc[remaining] = pd.to_datetime(
            raw.loc[remaining], format=fmt, errors="coerce"
        )
    return parsed


def _require(config: SportConfig, name: str) -> pd.DataFrame:
    return read_table(
        config.path("raw", f"{name}.parquet"),
        hint="Run `python run_backfill.py --sport epl` first.",
    )


def _canonical(series: pd.Series, *, label: str) -> pd.Series:
    missing = unmapped_names(series, CLUB_ALIAS_MAP)
    if missing:
        raise DataSourceError(
            f"{label} contains club names with no canonical mapping: {missing}. "
            "Add them to sports/epl/teams.py — a newly promoted club must be "
            "mapped explicitly rather than silently becoming a second team with "
            "no history."
        )
    return normalize_series(series, CLUB_ALIAS_MAP)


def clean_matches(config: SportConfig) -> pd.DataFrame:
    results = _require(config, "results")
    xg = _require(config, "team_xg")

    available = {k: v for k, v in RESULT_COLUMNS.items() if k in results.columns}
    matches = results[["season", *available]].rename(columns=available).copy()

    matches["kickoff"] = _parse_dates(matches["date_raw"])
    if matches["kickoff"].isna().any():
        bad = matches.loc[matches["kickoff"].isna(), "date_raw"].head(5).tolist()
        raise DataSourceError(f"unparseable match dates in football-data feed: {bad}")

    matches["home_team"] = _canonical(matches["home_team_raw"], label="football-data results")
    matches["away_team"] = _canonical(matches["away_team_raw"], label="football-data results")

    # --- join Understat xG on canonical teams + near-identical date ---
    xg = xg.copy()
    xg["home_team"] = _canonical(xg["home_team_raw"], label="Understat")
    xg["away_team"] = _canonical(xg["away_team_raw"], label="Understat")
    xg["xg_kickoff"] = pd.to_datetime(xg["datetime"], errors="coerce")

    merged = matches.merge(
        xg[["understat_id", "home_team", "away_team", "xg_kickoff",
            "home_xg", "away_xg", "home_goals_us", "away_goals_us"]],
        on=["home_team", "away_team"],
        how="left",
    )
    day_gap = (merged["kickoff"] - merged["xg_kickoff"]).dt.days.abs()
    merged = merged[day_gap.isna() | (day_gap <= JOIN_TOLERANCE_DAYS)]
    # A club pair can meet at the same venue in consecutive seasons, so the
    # date tolerance is what disambiguates; keep one row per football-data match.
    merged = merged.drop_duplicates(
        subset=["season", "kickoff", "home_team", "away_team"], keep="first"
    )

    if len(merged) != len(matches):
        log.warning(
            "xG join changed the row count (%s -> %s); check the club alias map",
            len(matches), len(merged),
        )

    coverage = merged["home_xg"].notna().mean()
    log.info("xG coverage: %.1f%% of matches", 100 * coverage)
    if coverage < 0.80:
        raise DataSourceError(
            f"only {coverage:.1%} of matches matched an Understat record. That is "
            "too low to model on — almost certainly a club-name mismatch rather "
            "than genuinely missing data. Fix the alias map before continuing."
        )

    # Cross-check the two sources agree on what happened, where both have it.
    both = merged.dropna(subset=["home_goals_us"])
    disagree = (both["home_goals"] != both["home_goals_us"]) | (
        both["away_goals"] != both["away_goals_us"]
    )
    if disagree.any():
        raise DataSourceError(
            f"{int(disagree.sum())} matches have different scorelines in "
            "football-data and Understat — the join is matching the wrong "
            "fixtures. Refusing to build features on it."
        )

    merged["total_goals"] = merged["home_goals"] + merged["away_goals"]
    merged["goal_difference"] = merged["home_goals"] - merged["away_goals"]
    merged["outcome"] = np.select(
        [merged["goal_difference"] > 0, merged["goal_difference"] == 0],
        ["home", "draw"],
        default="away",
    )
    merged.loc[merged["home_goals"].isna(), "outcome"] = None
    merged["home_win"] = np.where(
        merged["home_goals"].isna(), np.nan, (merged["goal_difference"] > 0).astype(float)
    )
    merged["match_id"] = (
        merged["season"].astype(str)
        + "_"
        + merged["kickoff"].dt.strftime("%Y%m%d")
        + "_"
        + merged["home_team"].map(slugify).str.replace(" ", "-")
        + "_"
        + merged["away_team"].map(slugify).str.replace(" ", "-")
    )
    return merged.sort_values(["kickoff", "match_id"]).reset_index(drop=True)


def clean_team_matches(matches: pd.DataFrame) -> pd.DataFrame:
    """Two rows per match: each club's own and conceded production."""
    pairs = {
        "goals": ("home_goals", "away_goals"),
        "xg": ("home_xg", "away_xg"),
        "shots": ("home_shots", "away_shots"),
        "shots_on_target": ("home_shots_on_target", "away_shots_on_target"),
        "corners": ("home_corners", "away_corners"),
        "fouls": ("home_fouls", "away_fouls"),
        "yellows": ("home_yellows", "away_yellows"),
        "reds": ("home_reds", "away_reds"),
    }
    base = ["match_id", "season", "kickoff", "referee"]
    rows = []
    for side, other in (("home", "away"), ("away", "home")):
        block = matches[base].copy()
        block["team"] = matches[f"{side}_team"]
        block["opponent"] = matches[f"{other}_team"]
        block["is_home"] = 1 if side == "home" else 0
        for stat, (home_col, away_col) in pairs.items():
            own, opp = (home_col, away_col) if side == "home" else (away_col, home_col)
            block[f"{stat}_for"] = matches[own] if own in matches else np.nan
            block[f"{stat}_against"] = matches[opp] if opp in matches else np.nan
        block["goal_diff"] = block["goals_for"] - block["goals_against"]
        block["points"] = np.select(
            [block["goal_diff"] > 0, block["goal_diff"] == 0],
            [3.0, 1.0],
            default=0.0,
        )
        block.loc[block["goals_for"].isna(), "points"] = np.nan
        rows.append(block)
    return pd.concat(rows, ignore_index=True).sort_values(["team", "kickoff"]).reset_index(drop=True)


def clean_player_matches(config: SportConfig, matches: pd.DataFrame) -> pd.DataFrame | None:
    """Per-player match lines, if the opt-in player backfill has been run."""
    path = config.path("raw", "player_matches.parquet")
    if not path.exists():
        log.info(
            "no raw/player_matches.parquet — EPL player props are unavailable. "
            "Run `python run_backfill.py --sport epl --with-players` to fetch them."
        )
        return None

    players = read_table(path)
    key = matches[["match_id", "season", "kickoff", "home_team", "away_team", "understat_id"]].copy()
    key["understat_id"] = key["understat_id"].astype(str)
    players["understat_id"] = players["understat_id"].astype(str)

    merged = players.merge(key, on="understat_id", how="inner")
    if merged.empty:
        raise DataSourceError(
            "player match lines did not join to any cleaned match; the Understat "
            "ids in raw/player_matches.parquet do not correspond to raw/team_xg.parquet."
        )

    merged["team"] = np.where(merged["side"] == "home", merged["home_team"], merged["away_team"])
    merged["opponent"] = np.where(merged["side"] == "home", merged["away_team"], merged["home_team"])
    merged["is_home"] = (merged["side"] == "home").astype(int)
    merged["player_key"] = merged["player_id"].astype(str)
    merged["started"] = (merged["minutes"] >= 60).astype(int)
    merged["cards"] = merged["yellow_card"].fillna(0) + merged["red_card"].fillna(0)
    merged["carded"] = (merged["cards"] > 0).astype(float)
    merged["scored"] = (merged["goals"].fillna(0) > 0).astype(float)
    merged["goal_involvements"] = merged["goals"].fillna(0) + merged["assists"].fillna(0)

    return merged.sort_values(["player_key", "kickoff"]).reset_index(drop=True)


def run(config: SportConfig) -> dict[str, pd.DataFrame]:
    matches = clean_matches(config)
    team_matches = clean_team_matches(matches)

    write_table(matches, config.path("clean", "matches.parquet"))
    write_table(team_matches, config.path("clean", "team_matches.parquet"))
    out = {"matches": matches, "team_matches": team_matches}

    players = clean_player_matches(config, matches)
    if players is not None:
        write_table(players, config.path("clean", "player_matches.parquet"))
        out["player_matches"] = players
    return out
