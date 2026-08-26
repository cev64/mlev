"""Elo ratings — opponent-adjusted team strength.

Why this exists: a rolling average of EPA or points treats every opponent the
same. A team posting good numbers against a weak schedule looks identical to one
posting the same numbers against a hard schedule, and the rolling features in
`core/features.py` cannot tell them apart. Elo can, because every update is
scaled by who the opponent was.

The implementation is the standard one, with the two adjustments that matter for
football:

* **Margin of victory**, damped. A 40-point win is more evidence than a 1-point
  win, but not 40 times more, and the damping term also corrects Elo's tendency
  to over-reward blowouts by strong favourites.
* **Between-season regression** toward the league mean, because rosters turn
  over and last January's rating is not this September's team.

Point-in-time by construction: `pregame_ratings` returns the rating each team
carried *into* each game, and the update using that game's result is applied
only afterwards. That ordering is the whole ballgame, and it is unit-tested.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

BASE_RATING = 1500.0
# 65 rating points is roughly the NFL's home-field edge in Elo terms.
HOME_ADVANTAGE = 65.0
K_FACTOR = 20.0
# How far each team is pulled back toward the mean between seasons.
SEASON_REGRESSION = 1.0 / 3.0
# Elo's logistic scale: a 400-point gap means a 10:1 expected-score ratio.
SCALE = 400.0


def expected_score(rating_a: float, rating_b: float) -> float:
    """Probability that A beats B, before any margin adjustment."""
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / SCALE))


def _margin_multiplier(margin: float, rating_diff: float) -> float:
    """Damped margin-of-victory weight (the FiveThirtyEight formulation).

    The `rating_diff` term in the denominator is the important half: without it,
    a strong favourite winning big gains more than the result justifies, and
    ratings run away.
    """
    return float(np.log(abs(margin) + 1.0) * (2.2 / (rating_diff * 0.001 + 2.2)))


def pregame_ratings(
    games: pd.DataFrame,
    *,
    home_col: str = "home_team",
    away_col: str = "away_team",
    margin_col: str = "home_margin",
    date_col: str = "kickoff",
    season_col: str = "season",
    k: float = K_FACTOR,
    home_advantage: float = HOME_ADVANTAGE,
    regression: float = SEASON_REGRESSION,
) -> pd.DataFrame:
    """Rating each side carried into each game, plus the derived win probability.

    Returns a frame aligned to `games`' index with `home_elo`, `away_elo`,
    `elo_diff` (home's edge including home advantage) and `elo_win_prob`.
    Unplayed games get ratings but do not update anything, so a schedule that
    runs ahead of results is handled correctly.
    """
    ordered = games.sort_values([date_col]).copy()
    ratings: dict[str, float] = {}
    last_season: int | None = None

    home_elo = np.full(len(ordered), np.nan)
    away_elo = np.full(len(ordered), np.nan)

    for position, (_, game) in enumerate(ordered.iterrows()):
        season = game[season_col]
        if last_season is not None and season != last_season:
            # New season: pull everyone partway back to the mean.
            for team in ratings:
                ratings[team] += (BASE_RATING - ratings[team]) * regression
        last_season = season

        home, away = game[home_col], game[away_col]
        rating_home = ratings.setdefault(home, BASE_RATING)
        rating_away = ratings.setdefault(away, BASE_RATING)
        home_elo[position] = rating_home
        away_elo[position] = rating_away

        margin = game[margin_col]
        if pd.isna(margin):
            continue  # not played yet — nothing to learn from

        edge = rating_home + home_advantage - rating_away
        expected = expected_score(rating_home + home_advantage, rating_away)
        actual = 1.0 if margin > 0 else 0.0 if margin < 0 else 0.5
        # A tie carries no margin information; treat it as a unit-margin draw.
        multiplier = _margin_multiplier(margin if margin != 0 else 1.0, edge if actual == 1 else -edge)
        change = k * multiplier * (actual - expected)
        ratings[home] = rating_home + change
        ratings[away] = rating_away - change

    out = pd.DataFrame(
        {
            "home_elo": home_elo,
            "away_elo": away_elo,
        },
        index=ordered.index,
    )
    out["elo_diff"] = out["home_elo"] + home_advantage - out["away_elo"]
    out["elo_win_prob"] = 1.0 / (1.0 + 10.0 ** (-out["elo_diff"] / SCALE))
    return out.reindex(games.index)
