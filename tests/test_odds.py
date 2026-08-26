"""Odds and expected-value arithmetic.

These are the numbers a bet gets sized on, so the tests are deliberately
concrete: known prices with known answers, not property checks.
"""

from __future__ import annotations

import numpy as np
import pytest

from core.odds import (
    american_to_decimal,
    american_to_probability,
    compare,
    decimal_to_american,
    decimal_to_probability,
    expected_value,
    expected_value_pct,
    format_american,
    kelly_fraction,
    no_push_probability,
    overround,
    probability_to_american,
    probability_to_decimal,
    remove_vig,
)


def test_american_decimal_roundtrip():
    for american in (-350, -150, -110, 100, 130, 250, 900):
        assert decimal_to_american(american_to_decimal(american)) == pytest.approx(american)


def test_known_american_conversions():
    assert american_to_decimal(-110) == pytest.approx(1.909091, abs=1e-5)
    assert american_to_decimal(100) == pytest.approx(2.0)
    assert american_to_decimal(150) == pytest.approx(2.5)
    assert american_to_decimal(-200) == pytest.approx(1.5)


def test_even_money_is_plus_100():
    assert probability_to_american(0.5) == pytest.approx(100)
    assert format_american(probability_to_american(0.5)) == "+100"


def test_minus_110_implies_the_famous_52_38():
    assert american_to_probability(-110) == pytest.approx(0.5238, abs=1e-4)


def test_zero_and_impossible_prices_are_rejected():
    with pytest.raises(ValueError):
        american_to_decimal(0)
    with pytest.raises(ValueError):
        decimal_to_probability(1.0)
    with pytest.raises(ValueError):
        probability_to_decimal(0.0)
    with pytest.raises(ValueError):
        probability_to_decimal(1.0)


def test_standard_two_way_hold_is_about_four_and_a_half_percent():
    implied = [american_to_probability(-110)] * 2
    assert overround(implied) == pytest.approx(0.0476, abs=1e-4)
    fair = remove_vig(implied)
    assert fair.sum() == pytest.approx(1.0)
    assert fair[0] == pytest.approx(0.5)


def test_devigging_an_uneven_market():
    implied = [american_to_probability(-200), american_to_probability(170)]
    fair = remove_vig(implied)
    assert fair.sum() == pytest.approx(1.0)
    assert fair[0] > fair[1]          # the favourite stays the favourite
    assert fair[0] < implied[0]       # but both come down


def test_devigging_needs_the_whole_market():
    with pytest.raises(ValueError, match="every outcome"):
        remove_vig([0.55])


def test_break_even_price_has_zero_ev():
    """-110 needs 52.38% to break even; that is the whole point of the number."""
    assert expected_value(0.5238, american_to_decimal(-110)) == pytest.approx(0.0, abs=0.02)


def test_ev_scales_with_stake():
    d = american_to_decimal(150)
    assert expected_value(0.5, d, stake=100.0) == pytest.approx(25.0)
    assert expected_value(0.5, d, stake=50.0) == pytest.approx(12.5)
    assert expected_value_pct(0.5, d) == pytest.approx(0.25)


def test_a_certain_loser_loses_the_stake():
    assert expected_value(0.0, 2.0, stake=100.0) == pytest.approx(-100.0)


def test_pushes_are_returned_not_lost():
    """The correction that matters most: a -3 NFL spread pushes ~15% of the time."""
    d = american_to_decimal(-110)
    treated_as_loss = expected_value(0.46, d, 100.0, push_probability=0.0)
    treated_properly = expected_value(0.46, d, 100.0, push_probability=0.08)
    assert treated_properly > treated_as_loss
    # 46% win / 8% push / 46% lose at -110: profit 0.46*90.91 minus 46 staked.
    assert treated_properly == pytest.approx(0.46 * 90.909 - 46.0, abs=0.05)


def test_push_probability_cannot_exceed_what_is_left():
    with pytest.raises(ValueError, match="exceeds 1"):
        expected_value(0.7, 2.0, 100.0, push_probability=0.5)


def test_no_push_probability_is_the_comparable_number():
    """A book's price is on the outcomes that can settle, so ours must be too."""
    assert no_push_probability(0.46, 0.08) == pytest.approx(0.5)
    assert no_push_probability(0.5, 0.0) == pytest.approx(0.5)


def test_kelly_is_zero_without_an_edge():
    d = american_to_decimal(-110)
    assert kelly_fraction(0.50, d) == 0.0
    assert kelly_fraction(0.5238, d) == pytest.approx(0.0, abs=1e-3)
    assert kelly_fraction(0.60, d) > 0.0


def test_kelly_matches_the_closed_form():
    # Even money, 60% shot: Kelly = 2p - 1 = 0.20.
    assert kelly_fraction(0.6, 2.0) == pytest.approx(0.20)


def test_kelly_cap_expresses_fractional_kelly():
    assert kelly_fraction(0.9, 2.0, cap=0.05) == pytest.approx(0.05)


def test_compare_reports_a_real_edge():
    c = compare(0.58, -110, opposing_odds=-110)
    assert c.is_positive
    assert c.edge == pytest.approx(0.58 - 0.5238, abs=1e-3)
    assert c.no_vig_probability == pytest.approx(0.5)
    assert c.no_vig_edge == pytest.approx(0.08, abs=1e-3)
    assert c.ev_per_100 == pytest.approx(10.73, abs=0.05)
    assert c.summary()["fair_american"] == "-138"


def test_compare_flags_a_bad_price():
    c = compare(0.45, -150)
    assert not c.is_positive
    assert c.ev_per_100 < 0
    assert c.kelly == 0.0


def test_compare_uses_the_settling_probability_against_the_book():
    """With a push in play, the edge is measured on the non-push outcomes."""
    c = compare(0.46, -110, push_probability=0.08, opposing_odds=-110)
    assert c.no_vig_probability == pytest.approx(0.5)
    assert c.no_vig_edge == pytest.approx(0.0, abs=1e-6)
    assert c.summary()["fair_american"] == "+100"


def test_compare_accepts_decimal_prices():
    a = compare(0.58, -110, american=True)
    b = compare(0.58, american_to_decimal(-110), american=False)
    assert a.ev_per_100 == pytest.approx(b.ev_per_100)
