"""EPL model definitions.

Game lines are a single Dixon-Coles fit whose scoreline distribution yields
1X2, Asian handicap, over/under, both-teams-to-score and correct score — all
consistent with each other by construction.

Player props reuse the same per-stat machinery as NFL, since "rolling usage +
opponent matchup -> count or regression model" transfers directly from a wide
receiver's targets to a forward's shots.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from core import metrics as M
from core.backtest import MarketModel, TargetSpec
from core.models import (
    BinaryProbabilityModel,
    GaussianRegressionModel,
    NegativeBinomialCountModel,
    PoissonCountModel,
)
from sports.epl.dixon_coles import DEFAULT_DECAY, DixonColesModel

log = logging.getLogger(__name__)

OUTCOME_LABELS = ("home", "draw", "away")
TOTAL_LINES = (1.5, 2.5, 3.5, 4.5)
HANDICAP_LINES = (-1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5)

# Candidate settings for the inner tuning pass. Small on purpose: each
# candidate is a full MLE fit, and the grid is searched inside every
# walk-forward fold.
DECAY_GRID = (0.0008, 0.0015, 0.0030)
XG_WEIGHT_GRID = (0.0, 0.5, 0.75)


class DixonColesMarketModel(MarketModel):
    """Wraps `DixonColesModel` in the interface the backtest engine expects.

    `tune=True` selects the time-decay rate and the goals/xG blend weight by
    holding out the most recent season *within the training fold* and scoring
    1X2 log loss on it. The test season is never touched — picking these two
    knobs by looking at walk-forward results would be fitting the backtest.
    """

    def __init__(
        self,
        *,
        decay: float = DEFAULT_DECAY,
        xg_weight: float = 0.5,
        use_xg: bool = True,
        tune: bool = True,
    ) -> None:
        self.decay = decay
        self.xg_weight = xg_weight
        self.use_xg = use_xg
        self.tune = tune
        self.model: DixonColesModel | None = None
        self.chosen_: dict[str, float] = {}

    # --- fit ----------------------------------------------------------------

    def fit(self, train: pd.DataFrame) -> "DixonColesMarketModel":
        played = train.dropna(subset=["home_goals", "away_goals"])
        if len(played) < 200:
            raise ValueError(f"only {len(played)} completed matches to fit Dixon-Coles")

        decay, xg_weight = self.decay, self.xg_weight
        if self.tune:
            tuned = self._tune(played)
            if tuned is not None:
                decay, xg_weight = tuned

        self.chosen_ = {"decay": decay, "xg_weight": xg_weight}
        self.model = DixonColesModel(
            decay=decay, xg_weight=xg_weight, use_xg=self.use_xg
        ).fit(played)
        return self

    def _tune(self, played: pd.DataFrame) -> tuple[float, float] | None:
        """Inner holdout: fit on all but the last training season, score on it."""
        seasons = sorted(played["season"].unique())
        if len(seasons) < 3:
            return None  # not enough history to hold a season out
        inner_train = played[played["season"] < seasons[-1]]
        inner_valid = played[played["season"] == seasons[-1]]
        if len(inner_train) < 200 or inner_valid.empty:
            return None

        best, best_loss = None, np.inf
        for decay in DECAY_GRID:
            for xg_weight in (XG_WEIGHT_GRID if self.use_xg else (0.0,)):
                try:
                    candidate = DixonColesModel(
                        decay=decay, xg_weight=xg_weight, use_xg=self.use_xg
                    ).fit(inner_train)
                except ValueError:
                    continue
                probs = np.array(
                    [
                        candidate.scoreline(h, a).outcome_probs().probs
                        for h, a in zip(inner_valid["home_team"], inner_valid["away_team"])
                    ]
                )
                truth = inner_valid["outcome"].map(
                    {lab: i for i, lab in enumerate(OUTCOME_LABELS)}
                ).to_numpy()
                loss = M.multiclass_log_loss(truth, probs)
                if loss < best_loss:
                    best, best_loss = (decay, xg_weight), loss
        if best is not None:
            log.info(
                "inner tuning chose decay=%.4f xg_weight=%.2f (1X2 log loss %.4f)",
                best[0], best[1], best_loss,
            )
        return best

    # --- predict ------------------------------------------------------------

    def predict_frame(self, test: pd.DataFrame) -> pd.DataFrame:
        if self.model is None:
            raise ValueError("call fit() before predict_frame()")

        records = []
        for home, away in zip(test["home_team"], test["away_team"]):
            scoreline = self.model.scoreline(home, away)
            outcome = scoreline.outcome_probs()
            totals = scoreline.total_goals()
            supremacy = scoreline.supremacy()
            best_h, best_a, best_p = scoreline.most_likely_scoreline()

            row = {
                "p_home": outcome.prob("home"),
                "p_draw": outcome.prob("draw"),
                "p_away": outcome.prob("away"),
                "exp_home_goals": scoreline.team_goals("home").mean,
                "exp_away_goals": scoreline.team_goals("away").mean,
                "exp_total_goals": totals.mean,
                "exp_supremacy": supremacy.mean,
                "supremacy_sd": supremacy.sd,
                "p_btts": scoreline.btts(),
                "likely_score": f"{best_h}-{best_a}",
                "likely_score_prob": best_p,
                # A club with no fitted rating is predicted from a
                # replacement-level prior; surface that rather than hide it.
                "uses_replacement_rating": int(
                    not self.model.is_known(home) or not self.model.is_known(away)
                ),
            }
            for line in TOTAL_LINES:
                row[f"p_over_{line:g}".replace(".", "_")] = totals.prob_over(line)
            for line in HANDICAP_LINES:
                ah = scoreline.asian_handicap(line)
                key = f"{line:+g}".replace(".", "_").replace("-", "m").replace("+", "p")
                row[f"p_ah_home_{key}"] = ah["home"]
            records.append(row)

        return pd.DataFrame(records, index=test.index)

    # --- evaluate -----------------------------------------------------------

    def evaluate(self, joined: pd.DataFrame) -> list[dict]:
        rows: list[dict] = []
        played = joined.dropna(subset=["home_goals", "away_goals", "p_home"])
        if played.empty:
            return rows

        probs = played[["p_home", "p_draw", "p_away"]].to_numpy()
        truth = played["outcome"].map({lab: i for i, lab in enumerate(OUTCOME_LABELS)}).to_numpy()
        rows.append(
            {
                "target": "match_outcome_1x2",
                "n": len(played),
                "log_loss": round(M.multiclass_log_loss(truth, probs), 5),
                "brier": round(M.multiclass_brier(truth, probs), 5),
                "accuracy": round(float(np.mean(probs.argmax(axis=1) == truth)), 5),
                # A model that cannot beat the base rate of home/draw/away has
                # learned nothing about the clubs.
                "baseline_log_loss": round(_baseline_log_loss(truth), 5),
            }
        )

        # The individual 1X2 legs, so calibration is readable per outcome.
        for i, label in enumerate(OUTCOME_LABELS):
            actual = (truth == i).astype(float)
            rows.append(
                M.classification_report(actual, probs[:, i], label=f"outcome_{label}")
            )

        rows.append(
            M.regression_report(
                played["total_goals"], played["exp_total_goals"], label="total_goals"
            )
        )
        rows.append(
            M.regression_report(
                played["goal_difference"], played["exp_supremacy"], label="supremacy"
            )
        )
        for line in TOTAL_LINES:
            col = f"p_over_{line:g}".replace(".", "_")
            if col in played.columns:
                actual = (played["total_goals"] > line).astype(float)
                rows.append(M.classification_report(actual, played[col], label=f"over_{line:g}"))
        if "p_btts" in played.columns:
            actual = ((played["home_goals"] > 0) & (played["away_goals"] > 0)).astype(float)
            rows.append(M.classification_report(actual, played["p_btts"], label="btts"))
        return rows

    def calibration(self, joined: pd.DataFrame) -> pd.DataFrame:
        played = joined.dropna(subset=["home_goals", "p_home"])
        if played.empty:
            return pd.DataFrame()
        frames = []
        for i, label in enumerate(OUTCOME_LABELS):
            actual = (played["outcome"] == label).astype(float)
            table = M.calibration_table(actual, played[f"p_{label}"])
            table.insert(0, "target", f"outcome_{label}")
            frames.append(table)
        over = (played["total_goals"] > 2.5).astype(float)
        table = M.calibration_table(over, played["p_over_2_5"])
        table.insert(0, "target", "over_2.5")
        frames.append(table)
        return pd.concat(frames, ignore_index=True)


def _baseline_log_loss(truth: np.ndarray) -> float:
    """Log loss of always quoting the observed home/draw/away base rate."""
    rates = np.array([(truth == i).mean() for i in range(len(OUTCOME_LABELS))])
    return M.multiclass_log_loss(truth, np.tile(rates, (len(truth), 1)))


# --- player props -----------------------------------------------------------


def _plays_regularly(df: pd.DataFrame) -> pd.Series:
    """Only model players with a real recent role — judged on prior matches."""
    return df["minutes_r5"].fillna(0) >= 30


def _is_attacking(df: pd.DataFrame) -> pd.Series:
    return _plays_regularly(df) & (df["shots_r5"].fillna(0) >= 0.5)


def player_targets() -> list[TargetSpec]:
    """Goals, assists, shots and cards — the four props Understat supports.

    Shots *on target* is the one prop from the spec that is missing: Understat's
    match rosters carry total shots and xG but not the on-target split, and
    football-data only has it at team level. Modelling total shots and
    documenting the gap beats inventing a conversion rate.
    """
    return [
        TargetSpec(
            name="goals",
            outcome_col="goals",
            kind="count",
            factory=lambda cols: PoissonCountModel(cols, max_lambda=5.0, name="goals"),
            prob_lines=(0.5, 1.5),
            row_filter=_is_attacking,
        ),
        TargetSpec(
            name="anytime_scorer",
            outcome_col="scored",
            kind="binary",
            factory=lambda cols: BinaryProbabilityModel(cols, name="anytime_scorer"),
            row_filter=_is_attacking,
        ),
        TargetSpec(
            name="assists",
            outcome_col="assists",
            kind="count",
            factory=lambda cols: PoissonCountModel(cols, max_lambda=4.0, name="assists"),
            prob_lines=(0.5,),
            row_filter=_plays_regularly,
        ),
        TargetSpec(
            name="shots",
            outcome_col="shots",
            kind="count",
            factory=lambda cols: NegativeBinomialCountModel(
                cols, max_lambda=12.0, name="shots"
            ),
            prob_lines=(0.5, 1.5, 2.5, 3.5),
            row_filter=_is_attacking,
        ),
        TargetSpec(
            name="xg",
            outcome_col="xg",
            kind="regression",
            factory=lambda cols: GaussianRegressionModel(
                cols, heteroskedastic=True, name="xg"
            ),
            row_filter=_is_attacking,
        ),
        TargetSpec(
            name="carded",
            outcome_col="carded",
            kind="binary",
            factory=lambda cols: BinaryProbabilityModel(cols, name="carded"),
            row_filter=_plays_regularly,
        ),
    ]
