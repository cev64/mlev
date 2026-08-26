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

import logging

import numpy as np
import pandas as pd

from core import market as MKT
from core import metrics as M
from core.backtest import MarketModel, TargetSpec, _normal_coverage
from core.distributions import LatticeDistribution, LatticeShape, NormalDistribution
from core.models import (
    BinaryProbabilityModel,
    GaussianRegressionModel,
    NegativeBinomialCountModel,
    PoissonCountModel,
)

log = logging.getLogger(__name__)

# Seasons held out inside the training fold to fit the market blend weight.
BLEND_HOLDOUT_SEASONS = 2

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


class JointGameModel(MarketModel):
    """All three NFL game markets derived from one pair of fitted distributions.

    The problem this replaces: fitting win probability, margin and total as three
    independent models lets them disagree. The old bundle produced a 0.679
    moneyline and a 0.662 `P(margin > 0)` for the same game, which cannot both
    be right.

    Here a margin model and a total model are fitted, and every market is read
    off them:

    * moneyline      = P(margin > 0), with the tie handled explicitly
    * spread cover   = P(margin > line), plus the push probability at whole numbers
    * total over     = P(total > line), plus the push
    * team scores    = (E[total] +/- E[margin]) / 2

    The distributions are `LatticeDistribution`, not Normal, which is what makes
    the push probabilities real. A Normal prices a -3 push at 3% when it is
    really 15%, and prices a tie at 3% when it is really 0.35%. The lattice
    shape is learned from the training fold only.
    """

    # Whole-number spreads (where a push is possible) and the common hooks.
    SPREAD_LINES = (-10.5, -7.0, -6.5, -3.5, -3.0, -2.5, 0.0, 2.5, 3.0, 3.5, 6.5, 7.0, 10.5)
    TOTAL_LINES = (37.5, 41.5, 44.5, 47.5, 51.5, 44.0, 47.0)

    # Where the book's numbers live, once `clean` has carried them through.
    MARKET_MARGIN_COL = "spread_line"
    MARKET_TOTAL_COL = "total_line"

    def __init__(
        self,
        feature_cols: list[str],
        *,
        recency_halflife_seasons: float | None = 4.0,
        season_col: str = "season",
        empirical: bool = True,
        blend_with_market: bool = True,
    ) -> None:
        self.feature_cols = list(feature_cols)
        self.recency_halflife_seasons = recency_halflife_seasons
        self.season_col = season_col
        self.empirical = empirical
        self.blend_with_market = blend_with_market
        self.margin_model: GaussianRegressionModel | None = None
        self.total_model: GaussianRegressionModel | None = None
        self.margin_shape_: LatticeShape | None = None
        self.total_shape_: LatticeShape | None = None
        self.margin_blend_: float = 1.0
        self.total_blend_: float = 1.0

    def _weights(self, rows: pd.DataFrame) -> np.ndarray | None:
        if self.recency_halflife_seasons is None or self.season_col not in rows.columns:
            return None
        seasons_ago = rows[self.season_col].max() - rows[self.season_col]
        return np.power(0.5, seasons_ago / self.recency_halflife_seasons).to_numpy(dtype=float)

    def fit(self, train: pd.DataFrame) -> "JointGameModel":
        rows = train.dropna(subset=["home_margin", "total_points"])
        if len(rows) < 100:
            raise ValueError(f"only {len(rows)} completed games to fit the joint game model")
        weights = self._weights(rows)

        self.margin_model = GaussianRegressionModel(
            self.feature_cols, heteroskedastic=True, name="home_margin"
        ).fit(rows, rows["home_margin"], weights)
        self.total_model = GaussianRegressionModel(
            self.feature_cols, heteroskedastic=True, name="total_points"
        ).fit(rows, rows["total_points"], weights)

        if self.empirical:
            # Learned from outcomes, not residuals: the 3- and 7-point spikes
            # live in absolute margin space. Standardising by each row's own
            # predicted mean would smear them away, which is exactly the bug
            # this replaced.
            self.margin_shape_ = LatticeShape.from_outcomes(rows["home_margin"].to_numpy())
            self.total_shape_ = LatticeShape.from_outcomes(rows["total_points"].to_numpy())

        if self.blend_with_market:
            self._fit_blend_weights(rows)
        return self

    def _fit_blend_weights(self, rows: pd.DataFrame) -> None:
        """How far to move the model's number toward the posted line.

        Fitted on a holdout *inside* the training fold — the most recent
        training season, scored by a model that never saw it. Using in-sample
        predictions here would flatter the model badly: its training-fold
        residuals are far smaller than its real ones, so the weight would come
        out near 1 and the blend would do nothing. The test season is never
        touched, for the same reason the rest of the pipeline never touches it.
        """
        seasons = sorted(rows[self.season_col].dropna().unique())
        if len(seasons) < 4:
            self.margin_blend_ = self.total_blend_ = MKT.DEFAULT_BLEND_WEIGHT
            return

        # Two seasons rather than one. A single season is ~280 games, and the
        # error curve across candidate weights is nearly flat near its minimum,
        # so one season lets noise pick the weight — it swung between 0.0 and
        # 0.4 across runs that differed by nothing that mattered.
        holdout_seasons = seasons[-BLEND_HOLDOUT_SEASONS:]
        inner = rows[~rows[self.season_col].isin(holdout_seasons)]
        holdout = rows[rows[self.season_col].isin(holdout_seasons)]
        if len(inner) < 200 or holdout.empty:
            self.margin_blend_ = self.total_blend_ = MKT.DEFAULT_BLEND_WEIGHT
            return

        # Recomputed for the inner fold rather than sliced out of the caller's
        # array: slicing assumes `rows` is ordered by season, and a positional
        # slice that is quietly wrong would attach each game's weight to some
        # other game. Recency is relative to the inner fold's own last season,
        # which is what a model trained on only those rows should see.
        inner_weights = self._weights(inner)

        for target, market_col, attribute in (
            ("home_margin", self.MARKET_MARGIN_COL, "margin_blend_"),
            ("total_points", self.MARKET_TOTAL_COL, "total_blend_"),
        ):
            if market_col not in holdout.columns:
                setattr(self, attribute, 1.0)  # no line to blend with
                continue
            probe = GaussianRegressionModel(
                self.feature_cols, heteroskedastic=True, name=f"{target}_blend_probe"
            ).fit(inner, inner[target], inner_weights)
            predicted = probe.predict_mean(holdout)
            setattr(
                self,
                attribute,
                MKT.fit_blend_weight(predicted, holdout[market_col], holdout[target]),
            )
        log.info(
            "blend weights on the model: margin %.2f, total %.2f",
            self.margin_blend_, self.total_blend_,
        )

    def _market_column(self, frame: pd.DataFrame, column: str) -> np.ndarray:
        """The posted line, or all-NaN where a fixture has none yet."""
        if not self.blend_with_market or column not in frame.columns:
            return np.full(len(frame), np.nan)
        return pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float)

    def _distribution(self, shape: LatticeShape | None, row_dist):
        if not self.empirical or shape is None:
            return row_dist
        return LatticeDistribution(row_dist.mean, row_dist.sd, shape)

    def predict_frame(self, test: pd.DataFrame) -> pd.DataFrame:
        if self.margin_model is None or self.total_model is None:
            raise ValueError("call fit() before predict_frame()")

        margin_base = self.margin_model.predict_dist(test)
        total_base = self.total_model.predict_dist(test)

        # Move each mean toward the posted line by the fitted weight. The sd is
        # left alone: a blended mean is more accurate than the model's own, so
        # keeping the model's spread makes every probability slightly less
        # confident than it could be. That is the safe direction to be wrong in
        # for anything that feeds an expected-value calculation.
        margin_lines = self._market_column(test, self.MARKET_MARGIN_COL)
        total_lines = self._market_column(test, self.MARKET_TOTAL_COL)
        margin_means = MKT.blend(
            [d.mean for d in margin_base], margin_lines, self.margin_blend_
        )
        total_means = MKT.blend(
            [d.mean for d in total_base], total_lines, self.total_blend_
        )

        records = []
        for index, (m_base, t_base) in enumerate(zip(margin_base, total_base)):
            m_base = NormalDistribution(float(margin_means[index]), m_base.sd)
            t_base = NormalDistribution(float(total_means[index]), t_base.sd)
            margin = self._distribution(self.margin_shape_, m_base)
            total = self._distribution(self.total_shape_, t_base)

            push_zero = margin.prob_exactly(0.0)
            home_win = margin.prob_over(0.0)
            # A tie is not a home win. Renormalise so the moneyline pair sums to
            # one over the non-tie outcomes, which is how the market settles.
            denominator = max(1.0 - push_zero, 1e-9)
            row = {
                "home_win_prob": home_win / denominator,
                "tie_prob": push_zero,
                "home_margin_mean": margin.mean,
                "home_margin_sd": margin.sd,
                "home_margin_p10": margin.quantile(0.10),
                "home_margin_p50": margin.quantile(0.50),
                "home_margin_p90": margin.quantile(0.90),
                "total_points_mean": total.mean,
                "total_points_sd": total.sd,
                "total_points_p10": total.quantile(0.10),
                "total_points_p90": total.quantile(0.90),
                "exp_home_score": (total.mean + margin.mean) / 2.0,
                "exp_away_score": (total.mean - margin.mean) / 2.0,
                # Carried with the row so anything reading these predictions —
                # the bundle above all — reports the weight that actually
                # produced them, rather than re-deriving it from a second fit
                # that could differ.
                "margin_blend_weight": self.margin_blend_,
                "total_blend_weight": self.total_blend_,
            }
            for line in self.SPREAD_LINES:
                key = _line_key(line)
                row[f"home_cover_{key}"] = margin.prob_over(-line)
                row[f"home_push_{key}"] = margin.prob_exactly(-line)
            for line in self.TOTAL_LINES:
                key = _line_key(line)
                row[f"total_over_{key}"] = total.prob_over(line)
                row[f"total_push_{key}"] = total.prob_exactly(line)
            records.append(row)

        return pd.DataFrame(records, index=test.index)

    def evaluate(self, joined: pd.DataFrame) -> list[dict]:
        rows: list[dict] = []
        wins = joined.dropna(subset=["home_win", "home_win_prob"])
        if not wins.empty:
            rows.append(M.classification_report(wins["home_win"], wins["home_win_prob"], label="home_win"))
        for outcome, pred in (("home_margin", "home_margin_mean"), ("total_points", "total_points_mean")):
            sub = joined.dropna(subset=[outcome, pred])
            if sub.empty:
                continue
            report = M.regression_report(sub[outcome], sub[pred], label=outcome)
            sd_col = pred.replace("_mean", "_sd")
            if sd_col in sub.columns:
                report["cov80"] = round(
                    _normal_coverage(sub[pred], sub[sd_col], sub[outcome]), 4
                )
            rows.append(report)
        rows.extend(self.market_report(joined))
        # Score the derived spread and total markets too — they are the point of
        # the joint model, and a good mean with bad cover probabilities is a
        # model that still cannot price a spread.
        for line in (-3.0, -7.0, 0.0, 3.0):
            key = _line_key(line)
            col = f"home_cover_{key}"
            if col not in joined.columns:
                continue
            sub = joined.dropna(subset=["home_margin", col])
            live = sub[sub["home_margin"] != -line]  # exclude pushes
            if len(live) < 50:
                continue
            actual = (live["home_margin"] > -line).astype(float)
            rows.append(M.classification_report(actual, live[col], label=f"spread{line:+g}"))
        return rows

    def market_report(self, joined: pd.DataFrame) -> list[dict]:
        """The model against the posted line, and what betting it would return.

        Two questions the rest of the metrics cannot answer. Beating the base
        rate says a model knows something about football; beating the line says
        it knows something the price does not; and only the ROI row says whether
        that difference survives the hold. They are reported together on
        purpose, because the first number on its own reads far better than the
        position it describes.
        """
        rows: list[dict] = []
        for outcome, model_col, market_col, label in (
            ("home_margin", "home_margin_mean", self.MARKET_MARGIN_COL, "margin vs line"),
            ("total_points", "total_points_mean", self.MARKET_TOTAL_COL, "total vs line"),
        ):
            if market_col not in joined.columns:
                continue
            comparison = MKT.market_comparison(
                joined, model_col=model_col, market_col=market_col,
                outcome_col=outcome, label=label,
            )
            if comparison:
                rows.append(comparison)

        rows.extend(self._moneyline_roi(joined))
        return rows

    def _moneyline_roi(self, joined: pd.DataFrame) -> list[dict]:
        """Flat-stake return of backing every side the model calls +EV."""
        needed = {"home_win_prob", "home_moneyline", "away_moneyline", "home_margin"}
        if not needed.issubset(joined.columns):
            return []
        live = joined.dropna(subset=sorted(needed))
        live = live[live["home_margin"] != 0]  # a tie settles neither side
        if len(live) < 100:
            return []

        # Both sides of every game, so the report cannot flatter itself by
        # quietly scoring only the half the model happened to like.
        probability = np.concatenate([live["home_win_prob"], 1.0 - live["home_win_prob"]])
        price = np.concatenate([live["home_moneyline"], live["away_moneyline"]])
        won = np.concatenate([live["home_margin"] > 0, live["home_margin"] < 0]).astype(float)

        rows = []
        for min_ev, label in ((0.0, "moneyline +EV"), (0.10, "moneyline EV>10%")):
            result = MKT.settle(probability, price, won, min_ev=min_ev)
            if result.n:
                rows.append({"target": label, **result.to_dict()})
        # The zero-skill reference: back both sides of everything. Its ROI is
        # the hold, and any selection rule worth using has to beat it.
        rows.append({
            "target": "moneyline every side",
            **MKT.settle(probability, price, won, min_ev=-9.9).to_dict(),
        })
        return rows

    def calibration(self, joined: pd.DataFrame) -> pd.DataFrame:
        sub = joined.dropna(subset=["home_win", "home_win_prob"])
        if sub.empty:
            return pd.DataFrame()
        table = M.calibration_table(sub["home_win"], sub["home_win_prob"])
        table.insert(0, "target", "home_win")
        return table


def _line_key(line: float) -> str:
    return f"{line:+g}".replace(".", "_").replace("-", "m").replace("+", "p")
