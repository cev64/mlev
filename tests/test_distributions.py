"""Distribution arithmetic.

Every prediction the project makes is one of these objects, so a bug here is a
bug in every number downstream. The scoreline tests matter most: the whole
argument for a goal model is that the derived markets are mutually consistent.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy import stats

from core.distributions import (
    BernoulliOutcome,
    CategoricalDistribution,
    NegativeBinomialDistribution,
    NormalDistribution,
    PoissonDistribution,
    ScorelineDistribution,
)


def poisson_grid(lam: float, mu: float, max_goals: int = 12) -> np.ndarray:
    goals = np.arange(max_goals + 1)
    return np.outer(stats.poisson.pmf(goals, lam), stats.poisson.pmf(goals, mu))


def test_normal_moments_and_tails():
    d = NormalDistribution(3.0, 13.5)
    assert d.mean == pytest.approx(3.0)
    assert d.sd == pytest.approx(13.5)
    assert d.prob_over(3.0) == pytest.approx(0.5)
    assert d.prob_over(-100) == pytest.approx(1.0, abs=1e-9)
    assert d.quantile(0.5) == pytest.approx(3.0)
    # A continuous distribution can never land exactly on a line.
    assert d.prob_exactly(3.0) == 0.0
    assert d.prob_over(2.5) + d.prob_under(2.5) == pytest.approx(1.0)


def test_normal_rejects_degenerate_parameters():
    with pytest.raises(ValueError):
        NormalDistribution(0.0, 0.0)
    with pytest.raises(ValueError):
        NormalDistribution(float("nan"), 1.0)


def test_poisson_anytime_scorer():
    d = PoissonDistribution(0.65)
    assert d.prob_at_least(1) == pytest.approx(1 - np.exp(-0.65))
    assert d.mean == pytest.approx(d.var)  # the Poisson's defining property
    # An integer line splits into over / push / under, and they must sum to 1.
    assert d.prob_over(1) + d.prob_exactly(1) + d.prob_under(1) == pytest.approx(1.0)


def test_negative_binomial_is_overdispersed():
    d = NegativeBinomialDistribution(5.0, 0.4)
    assert d.mean == pytest.approx(5.0)
    assert d.var == pytest.approx(5.0 + 0.4 * 25.0)
    assert d.var > d.mean
    # Wider tails than the Poisson with the same mean — the reason it exists.
    assert d.prob_at_least(12) > PoissonDistribution(5.0).prob_over(11.5)


def test_bernoulli_summary_is_a_probability():
    d = BernoulliOutcome(0.62)
    assert d.summary("home_win") == {"home_win_prob": 0.62}
    assert d.var == pytest.approx(0.62 * 0.38)
    with pytest.raises(ValueError):
        BernoulliOutcome(1.5)


def test_categorical_requires_normalised_probabilities():
    d = CategoricalDistribution(("home", "draw", "away"), (0.5, 0.3, 0.2))
    assert d.prob("draw") == pytest.approx(0.3)
    with pytest.raises(ValueError):
        CategoricalDistribution(("a", "b"), (0.5, 0.2))


def test_scoreline_outcomes_sum_to_one():
    s = ScorelineDistribution(poisson_grid(1.6, 1.1))
    outcome = s.outcome_probs()
    assert sum(outcome.probs) == pytest.approx(1.0)
    assert outcome.prob("home") > outcome.prob("away")  # the stronger side


def test_scoreline_marginals_recover_the_rates():
    s = ScorelineDistribution(poisson_grid(1.9, 0.8, max_goals=15))
    assert s.team_goals("home").mean == pytest.approx(1.9, abs=1e-3)
    assert s.team_goals("away").mean == pytest.approx(0.8, abs=1e-3)
    assert s.supremacy().mean == pytest.approx(1.1, abs=1e-3)
    assert s.total_goals().mean == pytest.approx(2.7, abs=1e-3)


def test_derived_markets_are_mutually_consistent():
    """The point of a goal model: every market comes from one distribution."""
    s = ScorelineDistribution(poisson_grid(1.7, 1.2))
    outcome = s.outcome_probs()
    # A 0.0 handicap is the draw-no-bet market: home / push(draw) / away.
    ah = s.asian_handicap(0.0)
    assert ah["home"] == pytest.approx(outcome.prob("home"))
    assert ah["push"] == pytest.approx(outcome.prob("draw"))
    assert ah["away"] == pytest.approx(outcome.prob("away"))
    # A -0.5 handicap can never push, and home must win outright.
    half = s.asian_handicap(-0.5)
    assert half["push"] == pytest.approx(0.0)
    assert half["home"] == pytest.approx(outcome.prob("home"))


def test_whole_goal_handicap_differs_only_by_the_push():
    """-1.0 and -1.5 share a cover probability; the push is what separates them.

    Emitting the cover column alone would make the two lines look identical, so
    this pins the relationship the prediction output relies on.
    """
    s = ScorelineDistribution(poisson_grid(1.9, 1.0))
    whole, half = s.asian_handicap(-1.0), s.asian_handicap(-1.5)
    assert whole["home"] == pytest.approx(half["home"])
    assert half["push"] == pytest.approx(0.0)
    assert whole["push"] > 0.0
    # Each line's three outcomes must still be a probability distribution.
    for line in (-1.5, -1.0, -0.5, 0.0, 0.5, 1.0):
        ah = s.asian_handicap(line)
        assert sum(ah.values()) == pytest.approx(1.0)


def test_quarter_handicap_splits_the_stake():
    s = ScorelineDistribution(poisson_grid(1.8, 1.0))
    low, high = s.asian_handicap(-0.5), s.asian_handicap(-1.0)
    quarter = s.asian_handicap(-0.75)
    for key in ("home", "push", "away"):
        assert quarter[key] == pytest.approx((low[key] + high[key]) / 2)


def test_handicap_rejects_non_quarter_lines():
    s = ScorelineDistribution(poisson_grid(1.5, 1.5))
    with pytest.raises(ValueError, match="quarter-line"):
        s.asian_handicap(-0.3)


def test_totals_and_btts_are_bounded_probabilities():
    s = ScorelineDistribution(poisson_grid(1.5, 1.3))
    over, under = s.total_goals().prob_over(2.5), s.total_goals().prob_under(2.5)
    assert over + under == pytest.approx(1.0)  # 2.5 cannot push
    assert 0.0 < s.btts() < 1.0
    # Over 1.5 must be at least as likely as over 2.5, and so on.
    totals = s.total_goals()
    probs = [totals.prob_over(line) for line in (0.5, 1.5, 2.5, 3.5, 4.5)]
    assert probs == sorted(probs, reverse=True)


def test_scoreline_grid_is_renormalised():
    """Truncating at max_goals loses a little mass; it must be put back."""
    s = ScorelineDistribution(poisson_grid(3.0, 2.5, max_goals=6))
    assert s.grid.sum() == pytest.approx(1.0)
    assert sum(s.outcome_probs().probs) == pytest.approx(1.0)


def test_scoreline_rejects_empty_mass():
    with pytest.raises(ValueError):
        ScorelineDistribution(np.zeros((5, 5)))
