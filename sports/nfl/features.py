"""NFL feature engineering — strictly point-in-time.

Every rolling statistic here is built with the shifted helpers in
`core.features`, so a row's features describe only what had happened *before*
that kickoff. The pregame context columns (rest days, divisional flag, roof,
primetime) are known in advance by definition.

Game-level features follow the spec: rolling EPA/play and success rate,
recency-weighted points for and against, home/away, rest days,
divisional/primetime flags, weather. Player-level: rolling usage (target share,
carry share, snap %), opponent-adjusted matchup, recent production trend.

Both tables are built in the "long" team/player shape first — where a rolling
window is well defined — then game features are pivoted to one row per game.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from core.config import SportConfig
from core.features import (
    drop_thin_history,
    ewm_prior_mean,
    prior_game_count,
    rolling_prior_mean,
    rolling_prior_std,
)
from core.io import read_table

log = logging.getLogger(__name__)

FORM_WINDOW = 8       # roughly half a season of recent form
LONG_WINDOW = 17      # a full season, for a stabler baseline
POINTS_HALFLIFE = 4.0  # recency weighting on points for/against

# Team-game columns rolled into prior-form features.
TEAM_ROLL_COLS = [
    "epa_per_play",
    "epa_per_play_competitive",
    "success_rate",
    "early_down_success_rate",
    "pass_epa_per_play",
    "rush_epa_per_play",
    "yards_per_play",
    "pass_rate",
    "def_epa_per_play",
    "def_success_rate",
    "def_pass_epa_per_play",
    "def_rush_epa_per_play",
]

PLAYER_ROLL_COLS = [
    "offense_pct",
    "target_share",
    "air_yards_share",
    "wopr",
    "targets",
    "carries",
    "receptions",
    "receiving_yards",
    "rushing_yards",
    "scrimmage_yards",
    "passing_yards",
    "attempts",
    "scrimmage_tds",
    "total_tds",
    "fantasy_points_ppr",
]


def _load(config: SportConfig, name: str) -> pd.DataFrame:
    return read_table(
        config.path("clean", f"{name}.parquet"),
        hint="Run the clean stage first (`python run_backfill.py --sport nfl`).",
    )


def _team_form(team_games: pd.DataFrame) -> pd.DataFrame:
    """Prior-form columns for each team-game. Never reads the current row."""
    df = team_games.sort_values(["team", "kickoff"]).copy()
    group, sort = ["team"], ["kickoff"]

    for col in TEAM_ROLL_COLS:
        if col not in df.columns:
            continue
        df[f"{col}_r{FORM_WINDOW}"] = rolling_prior_mean(
            df, col, group_cols=group, sort_cols=sort, window=FORM_WINDOW, min_periods=2
        )
        df[f"{col}_r{LONG_WINDOW}"] = rolling_prior_mean(
            df, col, group_cols=group, sort_cols=sort, window=LONG_WINDOW, min_periods=4
        )

    # Recency-weighted scoring, per the spec.
    for col in ("points_for", "points_against"):
        df[f"{col}_ewm"] = ewm_prior_mean(
            df, col, group_cols=group, sort_cols=sort, halflife=POINTS_HALFLIFE
        )
    df["margin_ewm"] = ewm_prior_mean(
        df, "margin", group_cols=group, sort_cols=sort, halflife=POINTS_HALFLIFE
    )
    df["margin_sd_r8"] = rolling_prior_std(
        df, "margin", group_cols=group, sort_cols=sort, window=FORM_WINDOW, min_periods=3
    )
    df["win_rate_r8"] = rolling_prior_mean(
        df, "won", group_cols=group, sort_cols=sort, window=FORM_WINDOW, min_periods=2
    )
    df["prior_games"] = prior_game_count(df, group_cols=group, sort_cols=sort)

    return df


def build_game_features(config: SportConfig) -> pd.DataFrame:
    """One row per game: home form, away form, their differences, context."""
    games = _load(config, "games")
    team_games = _load(config, "team_games")
    form = _team_form(team_games)

    # dict.fromkeys dedupes: win_rate_r8 already matches the _r{FORM_WINDOW}
    # suffix, and a duplicate name here makes every later df[col] a DataFrame.
    feature_cols = list(
        dict.fromkeys(
            [
                c for c in form.columns
                if c.endswith((f"_r{FORM_WINDOW}", f"_r{LONG_WINDOW}", "_ewm", "_sd_r8"))
            ]
            + ["win_rate_r8", "prior_games"]
        )
    )

    carry = ["game_id", "team", *feature_cols]
    home = form.loc[form["is_home"] == 1, carry].add_prefix("home_")
    home = home.rename(columns={"home_game_id": "game_id"})
    away = form.loc[form["is_home"] == 0, carry].add_prefix("away_")
    away = away.rename(columns={"away_game_id": "game_id"})

    out = games.merge(home, on="game_id", how="left").merge(away, on="game_id", how="left")

    # Differences carry most of the signal for a margin/total model; giving the
    # linear baseline the difference directly saves it from having to learn a
    # cancellation it has no reason to find.
    for col in feature_cols:
        if col == "prior_games":
            continue
        h, a = f"home_{col}", f"away_{col}"
        if h in out.columns and a in out.columns:
            out[f"diff_{col}"] = out[h] - out[a]

    out["rest_diff"] = out["home_rest"] - out["away_rest"]
    out["is_short_week_home"] = (out["home_rest"] <= 4).astype(int)
    out["is_short_week_away"] = (out["away_rest"] <= 4).astype(int)
    # Outdoor weather only matters where there is weather; inside a dome the
    # nflverse temp/wind fields are constants, so zero them rather than let the
    # model read a dome's 68F as meaningful.
    out["temp_outdoor"] = np.where(out["is_dome"] == 1, np.nan, out["temp"])
    out["wind_outdoor"] = np.where(out["is_dome"] == 1, 0.0, out["wind"])

    out = drop_thin_history(
        out,
        count_cols=["home_prior_games", "away_prior_games"],
        min_prior_games=config.min_prior_games,
    )
    log.info("nfl game features: %s rows, %s columns", len(out), out.shape[1])
    return out.sort_values(["kickoff", "game_id"]).reset_index(drop=True)


def game_feature_columns(features: pd.DataFrame) -> list[str]:
    """The model matrix for game-line targets: prior form + pregame context."""
    rolled = [
        c for c in features.columns
        if c.startswith("diff_") or c.endswith(("_ewm", "_sd_r8"))
    ]
    context = [
        "home_win_rate_r8", "away_win_rate_r8",
        "home_rest", "away_rest", "rest_diff",
        "is_short_week_home", "is_short_week_away",
        "is_divisional", "is_primetime", "is_playoff",
        "is_dome", "is_turf", "neutral_site",
        "temp_outdoor", "wind_outdoor",
    ]
    cols = [c for c in [*rolled, *context] if c in features.columns]
    # Drop anything that is entirely null across the table — a column that is
    # never observed cannot help, and it makes the imputer's job ambiguous.
    return [c for c in cols if features[c].notna().any()]


def build_player_features(config: SportConfig) -> pd.DataFrame:
    """One row per player-week: rolling usage and production, plus matchup."""
    players = _load(config, "player_games")
    team_games = _load(config, "team_games")
    form = _team_form(team_games)

    df = players.sort_values(["player_key", "kickoff"]).copy()
    group, sort = ["player_key"], ["kickoff"]

    for col in PLAYER_ROLL_COLS:
        if col not in df.columns:
            continue
        df[f"{col}_r4"] = rolling_prior_mean(
            df, col, group_cols=group, sort_cols=sort, window=4, min_periods=2
        )
        df[f"{col}_r8"] = rolling_prior_mean(
            df, col, group_cols=group, sort_cols=sort, window=8, min_periods=3
        )

    # Volatility of recent production feeds the variance of the prop
    # distribution — a boom/bust receiver should get a wider interval than a
    # steady possession target with the same mean.
    for col in ("scrimmage_yards", "receiving_yards", "rushing_yards", "passing_yards", "receptions"):
        if col in df.columns:
            df[f"{col}_sd8"] = rolling_prior_std(
                df, col, group_cols=group, sort_cols=sort, window=8, min_periods=3
            )

    df["player_prior_games"] = prior_game_count(df, group_cols=group, sort_cols=sort)

    # Opponent-adjusted matchup: how good is the defence this player faces,
    # measured on that defence's prior games only.
    opponent_form = form[
        ["game_id", "team", "def_epa_per_play_r8", "def_success_rate_r8",
         "def_pass_epa_per_play_r8", "def_rush_epa_per_play_r8", "prior_games"]
    ].rename(
        columns={
            "team": "opponent",
            "def_epa_per_play_r8": "opp_def_epa_r8",
            "def_success_rate_r8": "opp_def_success_r8",
            "def_pass_epa_per_play_r8": "opp_def_pass_epa_r8",
            "def_rush_epa_per_play_r8": "opp_def_rush_epa_r8",
            "prior_games": "opp_prior_games",
        }
    )
    df = df.merge(opponent_form, on=["game_id", "opponent"], how="left")

    # The player's own team's prior offensive form: volume context.
    team_form = form[["game_id", "team", "epa_per_play_r8", "pass_rate_r8", "points_for_ewm"]].rename(
        columns={
            "epa_per_play_r8": "team_off_epa_r8",
            "pass_rate_r8": "team_pass_rate_r8",
            "points_for_ewm": "team_points_ewm",
        }
    )
    df = df.merge(team_form, on=["game_id", "team"], how="left")

    df = drop_thin_history(
        df,
        count_cols=["player_prior_games"],
        min_prior_games=config.min_prior_games,
    )
    log.info("nfl player features: %s rows, %s columns", len(df), df.shape[1])
    return df.sort_values(["kickoff", "player_key"]).reset_index(drop=True)


def player_feature_columns(features: pd.DataFrame) -> list[str]:
    rolled = [c for c in features.columns if c.endswith(("_r4", "_r8", "_sd8"))]
    context = [
        "is_home", "is_primetime", "is_divisional", "is_dome", "is_turf",
        "injury_questionable", "injury_listed",
        "opp_def_epa_r8", "opp_def_success_r8",
        "opp_def_pass_epa_r8", "opp_def_rush_epa_r8",
        "team_off_epa_r8", "team_pass_rate_r8", "team_points_ewm",
    ]
    cols = [c for c in dict.fromkeys([*rolled, *context]) if c in features.columns]
    return [c for c in cols if features[c].notna().any()]
