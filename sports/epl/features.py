"""EPL feature engineering — strictly point-in-time.

Per the spec: rolling xG/xGA for and against, recent form (points per game,
goal difference), home/away, rest days between fixtures, and fixture
congestion. Every rolling column comes from the shifted helpers in
`core.features`, so nothing describes the match being predicted.

A note on what is *not* here: football-data.co.uk ships bookmaker odds in the
same CSV as the results, and those columns are dropped in `clean.py` rather
than carried through. They are pregame-available, so they are not leakage — but
market data is out of scope for this phase, and a model that quietly learns to
copy the closing line would tell us nothing about whether the model itself
works.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from core.config import SportConfig
from core.features import (
    days_since_prior,
    drop_thin_history,
    ewm_prior_mean,
    prior_game_count,
    rolling_prior_mean,
    rolling_prior_sum,
)
from core.io import read_table

log = logging.getLogger(__name__)

FORM_WINDOW = 6        # ~6 matches: the standard "recent form" horizon
LONG_WINDOW = 19       # half a season
XG_HALFLIFE = 5.0      # matches, for the recency-weighted xG rating

TEAM_ROLL_COLS = [
    "goals_for", "goals_against",
    "xg_for", "xg_against",
    "shots_for", "shots_against",
    "shots_on_target_for", "shots_on_target_against",
    "corners_for", "corners_against",
    "fouls_for", "fouls_against",
    "yellows_for", "reds_for",
    "points", "goal_diff",
]

# A midweek fixture means European or cup football in the days around it; the
# spec calls this out explicitly as a congestion signal.
CONGESTION_WINDOW_DAYS = 14


def _load(config: SportConfig, name: str) -> pd.DataFrame:
    return read_table(
        config.path("clean", f"{name}.parquet"),
        hint="Run the clean stage first (`python run_backfill.py --sport epl`).",
    )


def _team_form(team_matches: pd.DataFrame) -> pd.DataFrame:
    """Prior-form columns per club-match. Never reads the current row."""
    df = team_matches.sort_values(["team", "kickoff"]).copy()
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

    # Recency-weighted xG rating: the single most useful club-strength signal.
    for col in ("xg_for", "xg_against"):
        df[f"{col}_ewm"] = ewm_prior_mean(
            df, col, group_cols=group, sort_cols=sort, halflife=XG_HALFLIFE
        )
    df["xg_diff_ewm"] = df["xg_for_ewm"] - df["xg_against_ewm"]

    df["rest_days"] = days_since_prior(
        df, "kickoff", group_cols=group, sort_cols=sort, cap=21.0
    )
    df["prior_matches"] = prior_game_count(df, group_cols=group, sort_cols=sort)

    # Fixture congestion: league matches in the previous fortnight. It
    # undercounts, because midweek European and cup ties are not in this feed
    # at all -- so a club in Europe shows up as *fewer* league matches, not
    # more. Documented in the README as a known limitation.
    df["_one"] = 1.0
    df["matches_last_14d"] = _rolling_days_count(df, days=CONGESTION_WINDOW_DAYS)
    df = df.drop(columns=["_one"])

    return df


def _rolling_days_count(df: pd.DataFrame, *, days: int) -> pd.Series:
    """Count of a club's *previous* matches within `days` before each kickoff."""
    out = pd.Series(0.0, index=df.index)
    for team, block in df.groupby("team", sort=False):
        times = block["kickoff"]
        counts = []
        for kickoff in times:
            window_start = kickoff - pd.Timedelta(days=days)
            counts.append(float(((times >= window_start) & (times < kickoff)).sum()))
        out.loc[block.index] = counts
    return out


def build_game_features(config: SportConfig) -> pd.DataFrame:
    """One row per match: home form, away form, differences, and context.

    The Dixon-Coles model reads only the identity columns (teams, kickoff,
    goals) — its team ratings *are* its form model. The rolling columns are
    here for the covariate-augmented alternative and for the player-prop
    matchup joins, and they are held to the same point-in-time standard.
    """
    matches = _load(config, "matches")
    team_matches = _load(config, "team_matches")
    form = _team_form(team_matches)

    feature_cols = list(
        dict.fromkeys(
            [
                c for c in form.columns
                if c.endswith((f"_r{FORM_WINDOW}", f"_r{LONG_WINDOW}", "_ewm"))
            ]
            + ["rest_days", "prior_matches", "matches_last_14d"]
        )
    )

    carry = ["match_id", *feature_cols]
    home = form.loc[form["is_home"] == 1, carry].add_prefix("home_")
    home = home.rename(columns={"home_match_id": "match_id"})
    away = form.loc[form["is_home"] == 0, carry].add_prefix("away_")
    away = away.rename(columns={"away_match_id": "match_id"})

    out = matches.merge(home, on="match_id", how="left").merge(away, on="match_id", how="left")

    for col in feature_cols:
        if col == "prior_matches":
            continue
        h, a = f"home_{col}", f"away_{col}"
        if h in out.columns and a in out.columns:
            out[f"diff_{col}"] = out[h] - out[a]

    out["rest_diff"] = out["home_rest_days"] - out["away_rest_days"]
    out["congestion_diff"] = out["home_matches_last_14d"] - out["away_matches_last_14d"]
    out["is_midweek"] = out["kickoff"].dt.dayofweek.isin([1, 2, 3]).astype(int)

    out = drop_thin_history(
        out,
        count_cols=["home_prior_matches", "away_prior_matches"],
        min_prior_games=config.min_prior_games,
    )
    log.info("epl match features: %s rows, %s columns", len(out), out.shape[1])
    return out.sort_values(["kickoff", "match_id"]).reset_index(drop=True)


def game_feature_columns(features: pd.DataFrame) -> list[str]:
    """Model matrix for the covariate-augmented alternative to Dixon-Coles."""
    rolled = [c for c in features.columns if c.startswith("diff_")]
    context = [
        "home_xg_for_ewm", "home_xg_against_ewm",
        "away_xg_for_ewm", "away_xg_against_ewm",
        "home_rest_days", "away_rest_days", "rest_diff",
        "home_matches_last_14d", "away_matches_last_14d", "congestion_diff",
        "is_midweek",
    ]
    cols = [c for c in dict.fromkeys([*rolled, *context]) if c in features.columns]
    return [c for c in cols if features[c].notna().any()]


PLAYER_ROLL_COLS = [
    "minutes", "goals", "assists", "shots", "key_passes",
    "xg", "xa", "cards", "goal_involvements", "started",
]


def build_player_features(config: SportConfig) -> pd.DataFrame:
    """One row per player-match: rolling usage/production plus the matchup."""
    players = _load(config, "player_matches")
    team_matches = _load(config, "team_matches")
    form = _team_form(team_matches)

    df = players.sort_values(["player_key", "kickoff"]).copy()
    group, sort = ["player_key"], ["kickoff"]

    for col in PLAYER_ROLL_COLS:
        if col not in df.columns:
            continue
        df[f"{col}_r5"] = rolling_prior_mean(
            df, col, group_cols=group, sort_cols=sort, window=5, min_periods=2
        )
        df[f"{col}_r10"] = rolling_prior_mean(
            df, col, group_cols=group, sort_cols=sort, window=10, min_periods=3
        )

    # Minutes played recently is the strongest single predictor of whether a
    # player will be on the pitch long enough to score, shoot or be booked.
    df["minutes_sum_r5"] = rolling_prior_sum(
        df, "minutes", group_cols=group, sort_cols=sort, window=5, min_periods=1
    )
    df["player_prior_matches"] = prior_game_count(df, group_cols=group, sort_cols=sort)

    opponent_form = form[
        ["match_id", "team", "xg_against_ewm", f"goals_against_r{FORM_WINDOW}",
         f"shots_against_r{FORM_WINDOW}", f"fouls_for_r{FORM_WINDOW}",
         f"yellows_for_r{FORM_WINDOW}"]
    ].rename(
        columns={
            "team": "opponent",
            "xg_against_ewm": "opp_xg_conceded_ewm",
            f"goals_against_r{FORM_WINDOW}": "opp_goals_conceded_r6",
            f"shots_against_r{FORM_WINDOW}": "opp_shots_conceded_r6",
            f"fouls_for_r{FORM_WINDOW}": "opp_fouls_r6",
            f"yellows_for_r{FORM_WINDOW}": "opp_yellows_r6",
        }
    )
    df = df.merge(opponent_form, on=["match_id", "opponent"], how="left")

    team_form = form[["match_id", "team", "xg_for_ewm", f"goals_for_r{FORM_WINDOW}"]].rename(
        columns={"xg_for_ewm": "team_xg_ewm", f"goals_for_r{FORM_WINDOW}": "team_goals_r6"}
    )
    df = df.merge(team_form, on=["match_id", "team"], how="left")

    df = drop_thin_history(
        df, count_cols=["player_prior_matches"], min_prior_games=config.min_prior_games
    )
    log.info("epl player features: %s rows, %s columns", len(df), df.shape[1])
    return df.sort_values(["kickoff", "player_key"]).reset_index(drop=True)


def player_feature_columns(features: pd.DataFrame) -> list[str]:
    rolled = [c for c in features.columns if c.endswith(("_r5", "_r10"))]
    context = [
        "is_home", "minutes_sum_r5",
        "opp_xg_conceded_ewm", "opp_goals_conceded_r6", "opp_shots_conceded_r6",
        "opp_fouls_r6", "opp_yellows_r6",
        "team_xg_ewm", "team_goals_r6",
    ]
    cols = [c for c in dict.fromkeys([*rolled, *context]) if c in features.columns]
    return [c for c in cols if features[c].notna().any()]
