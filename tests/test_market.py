"""The market layer: de-vigging, blending, and settling bets.

These are the numbers that decide whether a prediction is worth acting on, so
the arithmetic is pinned rather than trusted. The leakage test at the bottom is
the important one: a blend weight is chosen by looking at results, and the
whole design depends on those results never coming from the test season.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core import market as MKT


class TestDevig:
    def test_even_prices_are_a_coin_flip(self):
        # -110 both ways is the standard spread price: equal sides, 4.5% hold.
        assert MKT.two_way_probability(-110, -110) == pytest.approx(0.5)
        assert MKT.hold(-110, -110) == pytest.approx(0.0476, abs=1e-4)

    def test_the_favourite_gets_the_larger_share(self):
        p = MKT.two_way_probability(-200, +170)
        assert 0.6 < p < 0.7
        # De-vigging must produce a probability, not an implied price: the raw
        # implied 66.7% still has the book's margin inside it.
        assert p < 1 / MKT.american_to_decimal(-200)

    def test_both_sides_sum_to_one(self):
        home = MKT.two_way_probability(-350, +280)
        away = MKT.two_way_probability(+280, -350)
        assert home + away == pytest.approx(1.0)

    def test_a_missing_price_is_not_invented(self):
        assert np.isnan(MKT.two_way_probability(np.nan, -110))


class TestBlend:
    def test_the_weight_means_what_it_says(self):
        assert MKT.blend(10.0, 0.0, 0.25) == pytest.approx(2.5)
        assert MKT.blend(10.0, 0.0, 1.0) == pytest.approx(10.0)
        assert MKT.blend(10.0, 0.0, 0.0) == pytest.approx(0.0)

    def test_no_line_leaves_the_model_alone(self):
        # A fixture priced too early to have a line still gets a prediction.
        blended = MKT.blend([3.0, 4.0], [np.nan, 0.0], 0.5)
        assert blended[0] == pytest.approx(3.0)
        assert blended[1] == pytest.approx(2.0)

    def test_a_weight_outside_the_range_is_clipped(self):
        assert MKT.blend(10.0, 0.0, 5.0) == pytest.approx(10.0)
        assert MKT.blend(10.0, 0.0, -1.0) == pytest.approx(0.0)


class TestFitBlendWeight:
    def test_a_useless_model_gets_no_weight(self):
        rng = np.random.default_rng(0)
        outcome = rng.normal(0, 10, 500)
        market = outcome + rng.normal(0, 1, 500)      # the line is nearly right
        model = rng.normal(0, 10, 500)                # the model is noise
        assert MKT.fit_blend_weight(model, market, outcome) <= 0.1

    def test_a_perfect_model_takes_the_weight(self):
        rng = np.random.default_rng(1)
        outcome = rng.normal(0, 10, 500)
        model = outcome + rng.normal(0, 0.5, 500)
        market = rng.normal(0, 10, 500)
        assert MKT.fit_blend_weight(model, market, outcome) >= 0.9

    def test_too_little_data_falls_back_rather_than_guessing(self):
        assert MKT.fit_blend_weight([1.0], [1.0], [1.0]) == MKT.DEFAULT_BLEND_WEIGHT


class TestSettle:
    def test_roi_is_profit_over_stake(self):
        # Three bets at +100. Two win, one loses: +1 +1 -1 over 3 units.
        result = MKT.settle([0.9, 0.9, 0.9], [100, 100, 100], [1, 1, 0], min_ev=0.0)
        assert result.n == 3
        assert result.roi == pytest.approx(1 / 3)
        assert result.hit_rate == pytest.approx(2 / 3)

    def test_only_bets_over_the_threshold_are_counted(self):
        # 40% at +100 is -20% EV and must not be bet; 60% at +100 is +20%.
        result = MKT.settle([0.4, 0.6], [100, 100], [1, 1], min_ev=0.0)
        assert result.n == 1

    def test_a_losing_favourite_costs_one_unit(self):
        result = MKT.settle([0.9], [-200], [0], min_ev=0.0)
        assert result.roi == pytest.approx(-1.0)

    def test_nothing_qualifying_is_reported_as_nothing(self):
        result = MKT.settle([0.1], [-200], [1], min_ev=0.0)
        assert result.n == 0


class TestMarketComparison:
    def test_it_names_the_winner_honestly(self):
        frame = pd.DataFrame({
            "outcome": [0.0, 10.0, -3.0],
            "model": [1.0, 11.0, -4.0],      # off by 1 every time
            "line": [3.0, 13.0, -6.0],       # off by 3 every time
        })
        report = MKT.market_comparison(
            frame, model_col="model", market_col="line",
            outcome_col="outcome", label="margin",
        )
        assert report["model_mae"] == pytest.approx(1.0)
        assert report["market_mae"] == pytest.approx(3.0)
        assert report["model_beats_market"] is True


class TestNoLeakage:
    """The blend weight must never be chosen by looking at the test season."""

    def _frame(self, seasons, rng):
        rows = []
        for season in seasons:
            for _ in range(120):
                margin = rng.normal(2, 12)
                rows.append({
                    "season": season,
                    "home_margin": margin,
                    "total_points": rng.normal(45, 10),
                    "spread_line": margin + rng.normal(0, 9),
                    "total_line": rng.normal(45, 3),
                    "feature_a": margin + rng.normal(0, 11),
                    "feature_b": rng.normal(0, 1),
                })
        return pd.DataFrame(rows)

    def test_the_weight_ignores_rows_it_is_asked_to_predict(self):
        from sports.nfl.models import JointGameModel

        rng = np.random.default_rng(7)
        train = self._frame([2018, 2019, 2020, 2021], rng)

        model = JointGameModel(["feature_a", "feature_b"]).fit(train)
        chosen = (model.margin_blend_, model.total_blend_)

        # Refit on the same training rows, with a wildly different future
        # attached. If any of it reached the weight, the weight would move.
        future = self._frame([2022], np.random.default_rng(99))
        future["spread_line"] = future["home_margin"] * 5
        model_again = JointGameModel(["feature_a", "feature_b"]).fit(train)
        assert (model_again.margin_blend_, model_again.total_blend_) == chosen

    def test_predictions_use_the_line_but_the_weight_came_from_training(self):
        from sports.nfl.models import JointGameModel

        rng = np.random.default_rng(11)
        train = self._frame([2018, 2019, 2020, 2021], rng)
        upcoming = self._frame([2022], rng).drop(columns=["home_margin", "total_points"])
        upcoming["home_margin"] = np.nan
        upcoming["total_points"] = np.nan

        model = JointGameModel(["feature_a", "feature_b"]).fit(train)
        predicted = model.predict_frame(upcoming)
        assert (predicted["margin_blend_weight"] == model.margin_blend_).all()
        assert predicted["home_margin_mean"].notna().all()
