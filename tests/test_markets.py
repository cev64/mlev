"""Market enumeration: both sides of everything, and they must add up.

The failure mode this guards against is subtle and expensive — an away side
that is not actually one minus the home side, so the two prices you compare
against a book are quietly inconsistent with each other.
"""

from __future__ import annotations

import pandas as pd
import pytest

from core.config import EPL, NFL
from core.markets import (
    MarketSide,
    complement,
    format_line,
    parse_line_key,
)
from sports.epl.pipeline import EPLPipeline
from sports.nfl.pipeline import NFLPipeline


def nfl_row() -> pd.DataFrame:
    return pd.DataFrame([{
        "game_id": "2026_01_NE_SEA",
        "kickoff": "2026-09-09",
        "home_team": "SEA",
        "away_team": "NE",
        "home_win_prob": 0.6721,
        "tie_prob": 0.0035,
        "home_margin_mean": 5.22, "home_margin_sd": 11.9,
        "total_points_mean": 51.0, "total_points_sd": 12.9,
        "exp_home_score": 28.1, "exp_away_score": 22.9,
        "home_cover_m3": 0.5333, "home_push_m3": 0.0858,
        "home_cover_m7": 0.4039, "home_push_m7": 0.0478,
        "total_over_p47_5": 0.5616, "total_push_p47_5": 0.0,
        "total_over_p47": 0.5744, "total_push_p47": 0.0328,
    }])


def epl_row() -> pd.DataFrame:
    return pd.DataFrame([{
        "match_id": "2026_20260829_x",
        "kickoff": "2026-08-29",
        "home_team": "Liverpool",
        "away_team": "Arsenal",
        "p_home": 0.3051, "p_draw": 0.2668, "p_away": 0.4281,
        "exp_home_goals": 1.30, "exp_away_goals": 1.58,
        "likely_score": "1-1", "likely_score_prob": 0.1256,
        "p_btts": 0.5884,
        "p_over_2_5": 0.5498,
        "p_ah_home_m1": 0.1367, "p_ah_push_m1": 0.1684,
        "p_ah_home_p0": 0.3051, "p_ah_push_p0": 0.2668,
        "uses_replacement_rating": 0,
    }])


# --- helpers ----------------------------------------------------------------


def test_parse_line_key_decodes_the_column_encoding():
    assert parse_line_key("m3") == -3.0
    assert parse_line_key("p0") == 0.0
    assert parse_line_key("p47_5") == 47.5
    assert parse_line_key("m10_5") == -10.5


def test_format_line_uses_a_real_minus_sign():
    assert format_line(47.5) == "47.5"
    assert format_line(-3.0) == "−3"


def test_complement_accounts_for_the_push():
    assert complement(0.5333, 0.0858) == pytest.approx(0.3809, abs=1e-4)
    assert complement(0.6) == pytest.approx(0.4)


def test_market_side_prices_the_settling_outcomes():
    side = MarketSide("Spread", "Spread -3", "SEA -3", 0.5333, 0.0858)
    assert side.settles_probability == pytest.approx(0.5333 / (1 - 0.0858), abs=1e-6)
    assert side.fair_decimal == pytest.approx(1 / side.settles_probability)


def test_extreme_sides_are_dropped_as_untradeable():
    from core.markets import FixtureMarkets

    fixture = FixtureMarkets("x", "A vs B", "2026-01-01", [
        MarketSide("Moneyline", "Moneyline", "A", 0.5),
        MarketSide("Spread", "Spread -60", "A -60", 0.00001),
    ])
    sides = fixture.to_dict()["sides"]
    assert len(sides) == 1
    assert sides[0]["side"] == "A"


# --- NFL --------------------------------------------------------------------


def test_nfl_emits_both_sides_of_every_market():
    fixtures = NFLPipeline(NFL).fixture_markets(nfl_row())
    assert len(fixtures) == 1
    sides = fixtures[0].sides
    for market in ("Moneyline", "Spread −3", "Total 47.5"):
        pair = [s for s in sides if s.market == market]
        assert len(pair) == 2, f"{market} should have exactly two sides"


def test_nfl_market_sides_sum_to_one_with_the_push():
    fixtures = NFLPipeline(NFL).fixture_markets(nfl_row())
    by_market: dict[str, list[MarketSide]] = {}
    for side in fixtures[0].sides:
        by_market.setdefault(side.market, []).append(side)

    for market, sides in by_market.items():
        assert len(sides) == 2
        total = sides[0].probability + sides[1].probability + sides[0].push_probability
        assert total == pytest.approx(1.0, abs=1e-6), f"{market} does not sum to 1"


def test_nfl_push_is_shared_by_both_sides_of_a_spread():
    fixtures = NFLPipeline(NFL).fixture_markets(nfl_row())
    spread = [s for s in fixtures[0].sides if s.market == "Spread −3"]
    assert spread[0].push_probability == pytest.approx(spread[1].push_probability)
    assert spread[0].push_probability == pytest.approx(0.0858)


def test_nfl_half_point_lines_never_push():
    fixtures = NFLPipeline(NFL).fixture_markets(nfl_row())
    for side in fixtures[0].sides:
        if side.market.endswith(".5"):
            assert side.push_probability == 0.0


def test_nfl_moneyline_excludes_the_tie_from_both_sides():
    fixtures = NFLPipeline(NFL).fixture_markets(nfl_row())
    ml = [s for s in fixtures[0].sides if s.market == "Moneyline"]
    assert ml[0].push_probability == pytest.approx(0.0035)
    # The two win probabilities plus the tie must be the whole distribution.
    assert ml[0].probability + ml[1].probability + 0.0035 == pytest.approx(1.0, abs=1e-6)


def test_nfl_fixture_carries_readable_context():
    fixture = NFLPipeline(NFL).fixture_markets(nfl_row())[0]
    assert fixture.label == "NE @ SEA"
    assert "28.1" in fixture.context["Projected score"]
    assert fixture.context["Margin"].startswith("+5.2")


# --- EPL --------------------------------------------------------------------


def test_epl_match_result_has_three_sides_summing_to_one():
    fixture = EPLPipeline(EPL).fixture_markets(epl_row())[0]
    result = [s for s in fixture.sides if s.market == "Match result"]
    assert len(result) == 3
    assert sum(s.probability for s in result) == pytest.approx(1.0, abs=1e-4)


def test_epl_double_chance_is_consistent_with_the_match_result():
    fixture = EPLPipeline(EPL).fixture_markets(epl_row())[0]
    dc = {s.side: s.probability for s in fixture.sides if s.group == "Double chance"}
    assert len(dc) == 3
    # Each double chance is exactly two of the three outcomes, so the three of
    # them together must count every outcome twice.
    assert sum(dc.values()) == pytest.approx(2.0, abs=1e-4)


def test_epl_handicap_shares_its_push_across_both_sides():
    fixture = EPLPipeline(EPL).fixture_markets(epl_row())[0]
    ah = [s for s in fixture.sides if s.market == "Handicap −1"]
    assert len(ah) == 2
    assert ah[0].push_probability == pytest.approx(0.1684)
    assert ah[0].probability + ah[1].probability + 0.1684 == pytest.approx(1.0, abs=1e-6)


def test_epl_draw_no_bet_matches_the_match_result():
    """The 0.0 handicap is draw-no-bet, so it must agree with the 1X2 exactly."""
    fixture = EPLPipeline(EPL).fixture_markets(epl_row())[0]
    home_win = next(s for s in fixture.sides
                    if s.market == "Match result" and s.side == "Liverpool")
    dnb = next(s for s in fixture.sides
               if s.market == "Handicap 0" and s.side.startswith("Liverpool"))
    assert dnb.probability == pytest.approx(home_win.probability)
    assert dnb.push_probability == pytest.approx(0.2668)


def test_epl_btts_and_totals_have_both_sides():
    fixture = EPLPipeline(EPL).fixture_markets(epl_row())[0]
    btts = [s for s in fixture.sides if s.group == "Both to score"]
    assert {s.side for s in btts} == {"Yes", "No"}
    assert sum(s.probability for s in btts) == pytest.approx(1.0, abs=1e-6)

    totals = [s for s in fixture.sides if s.market == "Goals 2.5"]
    assert sum(s.probability for s in totals) == pytest.approx(1.0, abs=1e-6)


def test_epl_flags_a_promoted_club():
    row = epl_row()
    row.loc[0, "uses_replacement_rating"] = 1
    fixture = EPLPipeline(EPL).fixture_markets(row)[0]
    assert "Caution" in fixture.context
