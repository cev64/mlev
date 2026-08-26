"""Lattice distributions — the key-number machinery.

The whole point is pricing whole-number lines. A Normal puts ~0 on an exact
3-point margin when the real rate is 15%, which makes every push probability
wrong. These tests pin the behaviour that fixes it.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy import stats

from core.distributions import LatticeDistribution, LatticeShape, NormalDistribution


def football_like_margins(n: int = 4000, seed: int = 3) -> np.ndarray:
    """Synthetic margins that clump on 3 and 7, the way real ones do."""
    rng = np.random.default_rng(seed)
    smooth = rng.normal(2.0, 13.0, n)
    margins = np.round(smooth)
    # Pull a slice of the mass onto the key numbers.
    keys = np.array([3, -3, 7, -7])
    move = rng.uniform(size=n) < 0.18
    margins[move] = rng.choice(keys, size=move.sum())
    # Ties are rare in football: they need overtime to finish level.
    ties = margins == 0
    margins[ties] = np.where(rng.uniform(size=ties.sum()) < 0.9, 1.0, 0.0)
    return margins


def test_shape_learns_the_key_numbers():
    shape = LatticeShape.from_outcomes(football_like_margins())
    assert shape.factor(3) > 1.5
    assert shape.factor(-3) > 1.5
    assert shape.factor(7) > 1.2
    # A value with no special status should be left roughly alone.
    assert 0.6 < shape.factor(11) < 1.6


def test_shape_learns_that_ties_are_rare():
    shape = LatticeShape.from_outcomes(football_like_margins())
    assert shape.factor(0) < 0.5


def test_shape_needs_enough_history():
    with pytest.raises(ValueError, match="at least 200"):
        LatticeShape.from_outcomes(np.arange(50.0))


def test_lattice_preserves_the_predicted_centre_and_spread():
    """The regression model decides where the mass sits; the shape only clumps it."""
    shape = LatticeShape.from_outcomes(football_like_margins())
    for mu, sigma in ((0.0, 13.0), (7.5, 11.0), (-4.25, 14.5)):
        d = LatticeDistribution(mu, sigma, shape)
        assert d.mean == pytest.approx(mu, abs=1.0)
        assert d.sd == pytest.approx(sigma, rel=0.12)


def test_lattice_is_a_proper_distribution():
    shape = LatticeShape.from_outcomes(football_like_margins())
    d = LatticeDistribution(3.0, 12.0, shape)
    assert d.cdf(200) == pytest.approx(1.0, abs=1e-6)
    assert d.cdf(-200) == pytest.approx(0.0, abs=1e-6)
    # over / push / under must partition the whole line at an integer.
    assert d.prob_over(3) + d.prob_exactly(3) + d.prob_under(3) == pytest.approx(1.0)
    # Quantiles must be monotone.
    qs = [d.quantile(q) for q in (0.1, 0.25, 0.5, 0.75, 0.9)]
    assert qs == sorted(qs)


def test_lattice_beats_normal_on_key_numbers():
    """The reason this class exists, stated as a test."""
    margins = football_like_margins()
    shape = LatticeShape.from_outcomes(margins)
    lattice = LatticeDistribution(2.0, 13.0, shape)
    normal = NormalDistribution(2.0, 13.0)

    actual_three = float(np.mean(margins == 3))
    normal_three = normal.cdf(3.5) - normal.cdf(2.5)

    assert lattice.prob_exactly(3) > 1.6 * normal_three
    assert lattice.prob_exactly(3) == pytest.approx(actual_three, abs=0.03)
    # A Normal is continuous: it assigns exactly zero to any single value, so it
    # cannot express a push at all.
    assert normal.prob_exactly(3) == 0.0
    assert lattice.prob_exactly(3) > 0.0


def test_lattice_only_puts_mass_on_integers():
    shape = LatticeShape.from_outcomes(football_like_margins())
    d = LatticeDistribution(1.0, 10.0, shape)
    assert d.prob_exactly(3.5) == 0.0
    # A half-point line therefore cannot push, and over + under must fill it.
    assert d.prob_over(3.5) + d.prob_under(3.5) == pytest.approx(1.0)


def test_lattice_rejects_degenerate_parameters():
    shape = LatticeShape.from_outcomes(football_like_margins())
    with pytest.raises(ValueError):
        LatticeDistribution(0.0, 0.0, shape)
    with pytest.raises(ValueError):
        LatticeDistribution(float("nan"), 10.0, shape)
