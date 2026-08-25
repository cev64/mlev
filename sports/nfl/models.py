"""NFL model definitions.

Game lines and player props are both expressed as `TargetSpec`s, so the same
walk-forward engine scores them. Every spec names the estimator to use, and
every estimator returns a distribution:

* win probability -> Bernoulli (classification)
* margin, total, yardage -> Normal with a fitted, feature-dependent sd
* receptions -> Negative Binomial (reception counts are overdispersed)
* touchdowns -> Poisson, from which `prob_at_least(1)` gives anytime-TD

Per the spec, the baselines are deliberately well-understood: regularised
logistic and ridge regression for the game lines, log-link GLMs for the counts.
Swapping in gradient boosting is a one-word change (`estimator="gbm"`), which
is the point of routing everything through `core.models`.
"""

from __future__ import annotations

import pandas as pd

from core.backtest import TargetSpec
from core.models import (
    BinaryProbabilityModel,
    GaussianRegressionModel,
    NegativeBinomialCountModel,
    PoissonCountModel,
)

RECEIVING_GROUPS = ("WR", "TE", "RB")


def game_targets() -> list[TargetSpec]:
    """Moneyline, spread and total — the three game-line markets."""
    return [
        TargetSpec(
            name="home_win",
            outcome_col="home_win",
            kind="binary",
            factory=lambda cols: BinaryProbabilityModel(cols, name="home_win"),
        ),
        TargetSpec(
            name="home_margin",
            outcome_col="home_margin",
            kind="regression",
            factory=lambda cols: GaussianRegressionModel(
                cols, heteroskedastic=True, name="home_margin"
            ),
            # Common spread numbers; each becomes a P(home margin > line) column.
            prob_lines=(-7.5, -3.5, -2.5, 0.0, 2.5, 3.5, 7.5),
        ),
        TargetSpec(
            name="total_points",
            outcome_col="total_points",
            kind="regression",
            factory=lambda cols: GaussianRegressionModel(
                cols, heteroskedastic=True, name="total_points"
            ),
            prob_lines=(37.5, 41.5, 44.5, 47.5, 51.5),
        ),
    ]


# --- player prop row filters -----------------------------------------------
# Props are only meaningful for players with a real recent role. Filtering on
# *prior* usage (the _r4 rolling columns, which exclude the current week) keeps
# these gates point-in-time: nothing here reads the week being predicted.


def _is_qb(df: pd.DataFrame) -> pd.Series:
    return (df["position_group"] == "QB") & (df["attempts_r4"].fillna(0) >= 10)


def _is_rusher(df: pd.DataFrame) -> pd.Series:
    return df["position_group"].isin(("RB", "QB")) & (df["carries_r4"].fillna(0) >= 4)


def _is_receiver(df: pd.DataFrame) -> pd.Series:
    return df["position_group"].isin(RECEIVING_GROUPS) & (df["targets_r4"].fillna(0) >= 2)


def _is_skill(df: pd.DataFrame) -> pd.Series:
    """Anyone with a realistic path to a scrimmage touchdown."""
    return df["position_group"].isin(RECEIVING_GROUPS) & (
        (df["targets_r4"].fillna(0) >= 1) | (df["carries_r4"].fillna(0) >= 1)
    )


def player_targets() -> list[TargetSpec]:
    """Per-stat prop models, each restricted to the players it applies to."""
    return [
        TargetSpec(
            name="passing_yards",
            outcome_col="passing_yards",
            kind="regression",
            factory=lambda cols: GaussianRegressionModel(
                cols, heteroskedastic=True, name="passing_yards"
            ),
            prob_lines=(199.5, 224.5, 249.5, 274.5, 299.5),
            row_filter=_is_qb,
        ),
        TargetSpec(
            name="passing_tds",
            outcome_col="passing_tds",
            kind="count",
            factory=lambda cols: PoissonCountModel(cols, name="passing_tds"),
            prob_lines=(0.5, 1.5, 2.5),
            row_filter=_is_qb,
        ),
        TargetSpec(
            name="rushing_yards",
            outcome_col="rushing_yards",
            kind="regression",
            factory=lambda cols: GaussianRegressionModel(
                cols, heteroskedastic=True, name="rushing_yards"
            ),
            prob_lines=(29.5, 49.5, 69.5, 89.5),
            row_filter=_is_rusher,
        ),
        TargetSpec(
            name="receiving_yards",
            outcome_col="receiving_yards",
            kind="regression",
            factory=lambda cols: GaussianRegressionModel(
                cols, heteroskedastic=True, name="receiving_yards"
            ),
            prob_lines=(24.5, 39.5, 49.5, 69.5, 89.5),
            row_filter=_is_receiver,
        ),
        TargetSpec(
            name="receptions",
            outcome_col="receptions",
            kind="count",
            factory=lambda cols: NegativeBinomialCountModel(cols, name="receptions"),
            prob_lines=(1.5, 2.5, 3.5, 4.5, 5.5),
            row_filter=_is_receiver,
        ),
        TargetSpec(
            name="scrimmage_yards",
            outcome_col="scrimmage_yards",
            kind="regression",
            factory=lambda cols: GaussianRegressionModel(
                cols, heteroskedastic=True, name="scrimmage_yards"
            ),
            prob_lines=(39.5, 59.5, 79.5, 99.5),
            row_filter=_is_skill,
        ),
        TargetSpec(
            name="scrimmage_tds",
            outcome_col="scrimmage_tds",
            kind="count",
            factory=lambda cols: PoissonCountModel(cols, name="scrimmage_tds"),
            prob_lines=(0.5, 1.5),
            row_filter=_is_skill,
        ),
        TargetSpec(
            name="anytime_td",
            outcome_col="anytime_td",
            kind="binary",
            factory=lambda cols: BinaryProbabilityModel(cols, name="anytime_td"),
            row_filter=_is_skill,
        ),
    ]
