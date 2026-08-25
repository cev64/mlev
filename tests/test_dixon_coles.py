"""Dixon-Coles fitting, on simulated leagues whose true ratings are known."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.errors import ModelNotFittedError
from sports.epl.dixon_coles import DixonColesModel, tau


def simulate_league(
    n_seasons: int = 4, seed: int = 21, home_advantage: float = 0.25
) -> tuple[pd.DataFrame, dict[str, float]]:
    """A synthetic league where we know each club's true attack strength."""
    rng = np.random.default_rng(seed)
    teams = [f"T{i:02d}" for i in range(14)]
    true_attack = {t: v for t, v in zip(teams, np.linspace(0.45, -0.45, len(teams)))}
    true_defence = {t: v for t, v in zip(teams, np.linspace(-0.35, 0.35, len(teams)))}
    base = np.log(1.35)

    rows, day = [], pd.Timestamp("2018-08-01")
    for season in range(2018, 2018 + n_seasons):
        for home in teams:
            for away in teams:
                if home == away:
                    continue
                lam = np.exp(base + true_attack[home] + true_defence[away] + home_advantage)
                mu = np.exp(base + true_attack[away] + true_defence[home])
                rows.append(
                    {
                        "season": season,
                        "kickoff": day,
                        "home_team": home,
                        "away_team": away,
                        "home_goals": float(rng.poisson(lam)),
                        "away_goals": float(rng.poisson(mu)),
                        "home_xg": lam,
                        "away_xg": mu,
                    }
                )
                day += pd.Timedelta(days=1)
    return pd.DataFrame(rows), true_attack


def test_tau_is_one_outside_the_low_score_cells():
    lam = np.full(4, 1.4)
    mu = np.full(4, 1.1)
    home = np.array([2, 3, 0, 5])
    away = np.array([2, 1, 4, 0])
    assert np.allclose(tau(home, away, lam, mu, rho=-0.1), 1.0)


def test_tau_adjusts_exactly_the_four_cells():
    lam, mu, rho = np.array([1.5]), np.array([1.2]), -0.08
    assert tau(np.array([0]), np.array([0]), lam, mu, rho)[0] == pytest.approx(
        1 - 1.5 * 1.2 * rho
    )
    assert tau(np.array([0]), np.array([1]), lam, mu, rho)[0] == pytest.approx(1 + 1.5 * rho)
    assert tau(np.array([1]), np.array([0]), lam, mu, rho)[0] == pytest.approx(1 + 1.2 * rho)
    assert tau(np.array([1]), np.array([1]), lam, mu, rho)[0] == pytest.approx(1 - rho)


def test_predict_before_fit_raises():
    with pytest.raises(ModelNotFittedError):
        DixonColesModel().scoreline("A", "B")


def test_fit_recovers_the_true_rating_order():
    matches, true_attack = simulate_league()
    # Low decay so the whole simulated history counts; ratings are stationary.
    model = DixonColesModel(decay=0.0002, ridge=0.01, use_xg=False).fit(matches)
    fitted = pd.Series(model.attack_)
    truth = pd.Series(true_attack)
    assert fitted.corr(truth) > 0.95


def test_fit_recovers_home_advantage_and_scoring_level():
    matches, _ = simulate_league(home_advantage=0.25)
    model = DixonColesModel(decay=0.0002, ridge=0.01, use_xg=False).fit(matches)
    assert model.home_advantage_ == pytest.approx(0.25, abs=0.06)
    # The base rate must not be shrunk toward one goal per game by the ridge.
    assert np.exp(model.base_) == pytest.approx(1.35, rel=0.15)


def test_ridge_does_not_distort_the_league_scoring_level():
    """A heavy ridge should shrink clubs together, not deflate total goals."""
    matches, _ = simulate_league()
    tight = DixonColesModel(decay=0.0002, ridge=2.0, use_xg=False).fit(matches)
    loose = DixonColesModel(decay=0.0002, ridge=0.01, use_xg=False).fit(matches)

    spread_tight = np.std(list(tight.attack_.values()))
    spread_loose = np.std(list(loose.attack_.values()))
    assert spread_tight < spread_loose  # clubs pulled together

    expected = matches["home_goals"].mean() + matches["away_goals"].mean()
    for model in (tight, loose):
        totals = [
            model.scoreline(h, a).total_goals().mean
            for h, a in zip(matches["home_team"][:100], matches["away_team"][:100])
        ]
        assert np.mean(totals) == pytest.approx(expected, rel=0.2)


def test_unrated_team_falls_back_to_replacement_level():
    matches, _ = simulate_league()
    model = DixonColesModel(decay=0.0002, use_xg=False).fit(matches)
    assert not model.is_known("PromotedFC")
    # It must still produce a usable, normalised distribution rather than fail.
    s = model.scoreline("T00", "PromotedFC")
    assert sum(s.outcome_probs().probs) == pytest.approx(1.0)
    # And a promoted side should be rated below the league's best.
    strong = model.scoreline("T00", "T13").outcome_probs().prob("home")
    promoted = s.outcome_probs().prob("home")
    assert promoted > 0.3 and strong > 0.3


def test_time_decay_weights_recent_seasons_more():
    """A club that improves sharply should be rated on its recent form."""
    matches, _ = simulate_league(n_seasons=4, seed=5)
    # Make T13 (the weakest club) score heavily in the final season only.
    final = matches["season"] == matches["season"].max()
    improved = final & (matches["home_team"] == "T13")
    matches.loc[improved, "home_goals"] = 5.0

    fast = DixonColesModel(decay=0.006, use_xg=False).fit(matches)
    slow = DixonColesModel(decay=0.0001, use_xg=False).fit(matches)
    assert fast.attack_["T13"] > slow.attack_["T13"]


def test_too_few_matches_is_an_error():
    matches, _ = simulate_league()
    with pytest.raises(ValueError, match="too few"):
        DixonColesModel().fit(matches.head(50))


def test_missing_columns_are_reported():
    matches, _ = simulate_league()
    with pytest.raises(KeyError, match="missing columns"):
        DixonColesModel().fit(matches.drop(columns=["home_goals"]))


def test_xg_blend_changes_predictions_but_stays_valid():
    matches, _ = simulate_league()
    goals_only = DixonColesModel(decay=0.001, use_xg=False).fit(matches)
    blended = DixonColesModel(decay=0.001, use_xg=True, xg_weight=0.75).fit(matches)
    a = goals_only.scoreline("T00", "T13").outcome_probs().prob("home")
    b = blended.scoreline("T00", "T13").outcome_probs().prob("home")
    assert 0.0 < b < 1.0
    assert a != pytest.approx(b, abs=1e-9)
