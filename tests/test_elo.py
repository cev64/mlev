"""Elo ratings, and above all that they are point-in-time.

Elo is the easiest feature in the project to leak with, because the natural way
to write it — rate everyone, then look up ratings — uses the result of the game
you are predicting. These tests pin the ordering.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.elo import BASE_RATING, HOME_ADVANTAGE, expected_score, pregame_ratings


def make_games(results: list[tuple[str, str, float]], season: int = 2024) -> pd.DataFrame:
    start = pd.Timestamp(f"{season}-09-01")
    return pd.DataFrame(
        {
            "season": season,
            "kickoff": [start + pd.Timedelta(days=7 * i) for i in range(len(results))],
            "home_team": [r[0] for r in results],
            "away_team": [r[1] for r in results],
            "home_margin": [r[2] for r in results],
        }
    )


def test_everyone_starts_level():
    games = make_games([("A", "B", 10.0)])
    out = pregame_ratings(games)
    assert out["home_elo"].iloc[0] == BASE_RATING
    assert out["away_elo"].iloc[0] == BASE_RATING
    # With equal ratings the only edge is home advantage.
    assert out["elo_diff"].iloc[0] == pytest.approx(HOME_ADVANTAGE)
    assert out["elo_win_prob"].iloc[0] > 0.5


def test_a_games_own_result_does_not_move_its_own_rating():
    """The leakage test. Change one game's score; its own features must not move."""
    base = make_games([("A", "B", 3.0), ("A", "C", 3.0), ("A", "D", 3.0)])
    tampered = base.copy()
    tampered.loc[2, "home_margin"] = 60.0  # a blowout in the last game

    before = pregame_ratings(base)
    after = pregame_ratings(tampered)

    for column in ("home_elo", "away_elo", "elo_diff", "elo_win_prob"):
        assert before[column].iloc[2] == pytest.approx(after[column].iloc[2]), (
            f"{column} on row 2 moved when row 2's own result changed"
        )
        # Earlier rows cannot move either: information never flows backwards.
        assert before[column].iloc[0] == pytest.approx(after[column].iloc[0])
        assert before[column].iloc[1] == pytest.approx(after[column].iloc[1])


def test_winning_raises_your_rating_and_lowers_theirs():
    games = make_games([("A", "B", 14.0), ("A", "B", 14.0)])
    out = pregame_ratings(games)
    # The second meeting must reflect the first result.
    assert out["home_elo"].iloc[1] > BASE_RATING
    assert out["away_elo"].iloc[1] < BASE_RATING
    # Elo is zero-sum: what one side gains the other loses.
    gain = out["home_elo"].iloc[1] - BASE_RATING
    loss = BASE_RATING - out["away_elo"].iloc[1]
    assert gain == pytest.approx(loss)


def test_bigger_margins_move_ratings_more_but_not_proportionally():
    narrow = pregame_ratings(make_games([("A", "B", 1.0), ("A", "B", 0.0)]))
    wide = pregame_ratings(make_games([("A", "B", 35.0), ("A", "B", 0.0)]))
    narrow_gain = narrow["home_elo"].iloc[1] - BASE_RATING
    wide_gain = wide["home_elo"].iloc[1] - BASE_RATING
    assert wide_gain > narrow_gain
    # Damped: a 35-point win is worth more than a 1-point win, nowhere near 35x.
    assert wide_gain < 6 * narrow_gain


def test_unplayed_games_get_ratings_but_change_nothing():
    games = make_games([("A", "B", 21.0), ("A", "C", np.nan), ("A", "D", np.nan)])
    out = pregame_ratings(games)
    assert out["home_elo"].notna().all()
    # A's rating after its one real win must not drift across the unplayed rows.
    assert out["home_elo"].iloc[1] == pytest.approx(out["home_elo"].iloc[2])


def test_ratings_regress_between_seasons():
    first = make_games([("A", "B", 28.0)] * 6, season=2023)
    second = make_games([("A", "C", 0.0)], season=2024)
    combined = pd.concat([first, second], ignore_index=True)
    out = pregame_ratings(combined)

    end_of_first = out["home_elo"].iloc[len(first) - 1]
    start_of_second = out["home_elo"].iloc[len(first)]
    assert start_of_second < end_of_first          # pulled back toward the mean
    assert start_of_second > BASE_RATING           # but not all the way


def test_expected_score_is_symmetric_and_monotone():
    assert expected_score(1500, 1500) == pytest.approx(0.5)
    assert expected_score(1900, 1500) == pytest.approx(10 / 11, abs=1e-6)
    assert expected_score(1500, 1900) == pytest.approx(1 / 11, abs=1e-6)
    assert expected_score(1600, 1500) + expected_score(1500, 1600) == pytest.approx(1.0)


def test_output_is_aligned_to_the_input_index():
    """Games arrive sorted by kickoff elsewhere; the join must survive shuffling."""
    games = make_games([("A", "B", 7.0), ("C", "D", -3.0), ("A", "C", 10.0)])
    shuffled = games.sample(frac=1.0, random_state=0)
    out = pregame_ratings(shuffled)
    assert list(out.index) == list(shuffled.index)
    assert out["home_elo"].notna().all()
