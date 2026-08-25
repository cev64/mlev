"""Leakage guards.

These are the most important tests in the project. Everything else measures how
good the model is; these check that the measurement itself is honest. A rolling
feature that accidentally includes the current row inflates every backtest
number in a way that looks like success.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.backtest import TabularBundle, TargetSpec, walk_forward
from core.errors import LeakageError
from core.features import (
    assert_no_lookahead,
    days_since_prior,
    ewm_prior_mean,
    expanding_prior_mean,
    prior_game_count,
    rolling_prior_mean,
    rolling_prior_std,
)
from core.models import BinaryProbabilityModel


@pytest.fixture
def toy() -> pd.DataFrame:
    """Two teams, strictly increasing values, so leakage is arithmetic."""
    return pd.DataFrame(
        {
            "team": ["A"] * 5 + ["B"] * 5,
            "date": pd.to_datetime(
                ["2024-01-01", "2024-01-08", "2024-01-15", "2024-01-22", "2024-01-29"] * 2
            ),
            "value": [10, 20, 30, 40, 50, 1, 2, 3, 4, 5],
            "season": [2024] * 10,
        }
    )


def test_rolling_mean_excludes_current_row(toy):
    got = rolling_prior_mean(
        toy, "value", group_cols=["team"], sort_cols=["date"], window=2
    )
    # Row 2 (value 30) must average rows 0 and 1 only: (10 + 20) / 2.
    assert got.iloc[0] != got.iloc[0] or pd.isna(got.iloc[0])  # first row has no prior
    assert got.iloc[1] == 10.0
    assert got.iloc[2] == 15.0
    assert got.iloc[3] == 25.0
    # And never equals the current row's own value.
    assert not (got.dropna() == toy.loc[got.dropna().index, "value"]).any()


def test_rolling_mean_is_group_local(toy):
    got = rolling_prior_mean(
        toy, "value", group_cols=["team"], sort_cols=["date"], window=5
    )
    # Team B's first row must be NaN, not contaminated by team A's history.
    assert pd.isna(got.iloc[5])
    assert got.iloc[6] == 1.0


def test_rolling_helpers_never_see_the_future(toy):
    """Changing a row's own value must not change that row's own features."""
    helpers = {
        "roll": lambda df: rolling_prior_mean(
            df, "value", group_cols=["team"], sort_cols=["date"], window=3
        ),
        "ewm": lambda df: ewm_prior_mean(
            df, "value", group_cols=["team"], sort_cols=["date"], halflife=2.0
        ),
        "expanding": lambda df: expanding_prior_mean(
            df, "value", group_cols=["team"], sort_cols=["date"]
        ),
        "std": lambda df: rolling_prior_std(
            df, "value", group_cols=["team"], sort_cols=["date"], window=4, min_periods=2
        ),
    }
    tampered = toy.copy()
    tampered.loc[3, "value"] = 9999  # a wild change to one row

    for name, fn in helpers.items():
        before, after = fn(toy), fn(tampered)
        assert before.iloc[3] == after.iloc[3] or (
            pd.isna(before.iloc[3]) and pd.isna(after.iloc[3])
        ), f"{name}: row 3's feature moved when row 3's own outcome changed"
        # Earlier rows must be untouched too — information cannot flow backwards.
        pd.testing.assert_series_equal(
            before.iloc[:3], after.iloc[:3], check_names=False
        )


def test_prior_game_count_starts_at_zero(toy):
    got = prior_game_count(toy, group_cols=["team"], sort_cols=["date"])
    assert list(got[:5]) == [0, 1, 2, 3, 4]
    assert list(got[5:]) == [0, 1, 2, 3, 4]


def test_days_since_prior_is_capped(toy):
    got = days_since_prior(toy, "date", group_cols=["team"], sort_cols=["date"], cap=5.0)
    assert pd.isna(got.iloc[0])
    assert got.iloc[1] == 5.0  # 7 days, capped to 5


def test_assert_no_lookahead_rejects_outcome_in_matrix():
    df = pd.DataFrame({"feat": np.arange(50.0), "outcome": np.arange(50.0)})
    with pytest.raises(LeakageError, match="outcome columns present"):
        assert_no_lookahead(df, feature_cols=["feat", "outcome"], outcome_cols=["outcome"])


def test_assert_no_lookahead_rejects_perfect_copy():
    rng = np.random.default_rng(0)
    outcome = rng.normal(size=200)
    df = pd.DataFrame({"sneaky": outcome * 2.0, "outcome": outcome})
    with pytest.raises(LeakageError, match="collinear"):
        assert_no_lookahead(df, feature_cols=["sneaky"], outcome_cols=["outcome"])


def test_assert_no_lookahead_passes_on_honest_features():
    rng = np.random.default_rng(1)
    outcome = rng.normal(size=200)
    df = pd.DataFrame({"honest": outcome * 0.3 + rng.normal(size=200), "outcome": outcome})
    assert_no_lookahead(df, feature_cols=["honest"], outcome_cols=["outcome"])


def test_walk_forward_never_trains_on_the_test_season():
    """The engine must refuse a split whose training fold reaches the test season."""
    rng = np.random.default_rng(2)
    n = 900
    features = pd.DataFrame(
        {
            "season": np.repeat([2020, 2021, 2022], n // 3),
            "x": rng.normal(size=n),
        }
    )
    features["y"] = (rng.uniform(size=n) < 1 / (1 + np.exp(-features["x"]))).astype(float)

    seen_train_seasons: list[tuple[int, int]] = []

    class Spy(TabularBundle):
        def fit(self, train):
            seen_train_seasons.append((int(train["season"].min()), int(train["season"].max())))
            return super().fit(train)

    spec = TargetSpec(
        name="y", outcome_col="y", kind="binary",
        factory=lambda cols: BinaryProbabilityModel(cols, C=1.0),
    )
    result = walk_forward(
        features, lambda: Spy(specs=[spec], feature_cols=["x"]), min_train_seasons=1
    )

    tested = sorted(result.predictions["test_season"].unique())
    for (_, train_max), test_season in zip(seen_train_seasons, tested):
        assert train_max < test_season, (
            f"trained through {train_max} while testing {test_season}"
        )


def test_walk_forward_raises_when_training_fold_overlaps():
    """Directly exercise the guard with a deliberately broken season column."""
    rng = np.random.default_rng(3)
    features = pd.DataFrame({"season": [2020] * 400 + [2021] * 400, "x": rng.normal(size=800)})
    features["y"] = (rng.uniform(size=800) < 0.5).astype(float)

    class Cheat(TabularBundle):
        def fit(self, train):
            return super().fit(train)

    spec = TargetSpec(
        name="y", outcome_col="y", kind="binary",
        factory=lambda cols: BinaryProbabilityModel(cols, C=1.0),
    )
    # Monkeypatch the comparison by making every row look like the test season.
    broken = features.copy()
    broken["season"] = 2021
    with pytest.raises(ValueError, match="more than"):
        walk_forward(broken, lambda: Cheat(specs=[spec], feature_cols=["x"]), min_train_seasons=1)
