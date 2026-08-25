"""Walk-forward backtesting.

The rule, from the spec: *train on season N and earlier, test on N+1, roll
forward — never train on data from after the test window.* That is enforced
here rather than trusted: `walk_forward` asserts the training fold's maximum
season is strictly below the test season on every fold, and raises
`LeakageError` if it is not.

Two model shapes plug into the same engine:

* `TabularBundle` — a set of independent per-row sklearn targets (NFL game
  lines, and player props for both sports).
* a sport-specific `MarketModel` — e.g. EPL Dixon-Coles, where one fitted
  object produces several mutually consistent markets at once.

Both implement `fit` / `predict_frame` / `evaluate`, so the engine below never
branches on sport.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

from core import metrics as M
from core.errors import LeakageError
from core.models import BaseModel

log = logging.getLogger(__name__)

TargetKind = Literal["binary", "regression", "count"]


class MarketModel(ABC):
    """Something that can be trained on a season slice and asked to predict."""

    @abstractmethod
    def fit(self, train: pd.DataFrame) -> "MarketModel": ...

    @abstractmethod
    def predict_frame(self, test: pd.DataFrame) -> pd.DataFrame:
        """One row per row of `test`, indexed identically, prediction columns only."""

    @abstractmethod
    def evaluate(self, joined: pd.DataFrame) -> list[dict]:
        """Score predictions against realised outcomes in the same frame."""

    def calibration(self, joined: pd.DataFrame) -> pd.DataFrame:
        """Optional per-market calibration tables. Default: none."""
        return pd.DataFrame()


@dataclass
class TargetSpec:
    """One modelled quantity: what to predict, with what, and how to score it."""

    name: str
    outcome_col: str
    kind: TargetKind
    factory: Callable[[list[str]], BaseModel]
    # Extra P(X > line) columns to emit — the shape the EV phase will consume.
    prob_lines: tuple[float, ...] = ()
    # Restrict training/scoring to rows matching this predicate (e.g. QBs only).
    row_filter: Callable[[pd.DataFrame], pd.Series] | None = None


@dataclass
class TabularBundle(MarketModel):
    """A set of independent per-row targets sharing one feature matrix."""

    specs: Sequence[TargetSpec]
    feature_cols: list[str]
    fitted: dict[str, BaseModel] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)

    def _rows(self, df: pd.DataFrame, spec: TargetSpec) -> pd.DataFrame:
        sub = df if spec.row_filter is None else df.loc[spec.row_filter(df)]
        return sub.dropna(subset=[spec.outcome_col])

    def fit(self, train: pd.DataFrame) -> "TabularBundle":
        self.fitted, self.skipped = {}, {}
        for spec in self.specs:
            rows = self._rows(train, spec)
            if len(rows) < 50:
                # Too little history to fit honestly. Record it and move on;
                # the target is reported as skipped rather than silently
                # predicted from a model that saw 12 rows.
                self.skipped[spec.name] = f"only {len(rows)} training rows"
                continue
            try:
                model = spec.factory(self.feature_cols)
                model.fit(rows, rows[spec.outcome_col])
            except ValueError as exc:  # single-class target, all-NaN column, ...
                self.skipped[spec.name] = str(exc)
                continue
            self.fitted[spec.name] = model
        if not self.fitted:
            raise ValueError(f"no targets could be fit; reasons: {self.skipped}")
        return self

    def predict_frame(self, test: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(index=test.index)
        for spec in self.specs:
            model = self.fitted.get(spec.name)
            if model is None:
                continue
            rows = test if spec.row_filter is None else test.loc[spec.row_filter(test)]
            if rows.empty:
                continue
            dists = model.predict_dist(rows)
            if spec.kind == "binary":
                out.loc[rows.index, f"{spec.name}_prob"] = [d.mean for d in dists]
            else:
                out.loc[rows.index, f"{spec.name}_mean"] = [d.mean for d in dists]
                out.loc[rows.index, f"{spec.name}_sd"] = [d.sd for d in dists]
                out.loc[rows.index, f"{spec.name}_p10"] = [d.quantile(0.10) for d in dists]
                out.loc[rows.index, f"{spec.name}_p90"] = [d.quantile(0.90) for d in dists]
            for line in spec.prob_lines:
                col = f"{spec.name}_p_over_{line:g}".replace(".", "_")
                out.loc[rows.index, col] = [d.prob_over(line) for d in dists]
        return out

    def evaluate(self, joined: pd.DataFrame) -> list[dict]:
        rows: list[dict] = []
        for spec in self.specs:
            if spec.name in self.skipped:
                rows.append({"target": spec.name, "n": 0, "skipped": self.skipped[spec.name]})
                continue
            pred_col = f"{spec.name}_prob" if spec.kind == "binary" else f"{spec.name}_mean"
            if pred_col not in joined.columns:
                continue
            sub = joined.dropna(subset=[pred_col, spec.outcome_col])
            if sub.empty:
                continue
            if spec.kind == "binary":
                rows.append(
                    M.classification_report(
                        sub[spec.outcome_col], sub[pred_col], label=spec.name
                    )
                )
            else:
                report = M.regression_report(
                    sub[spec.outcome_col], sub[pred_col], label=spec.name
                )
                sd_col = f"{spec.name}_sd"
                if sd_col in sub.columns:
                    report["cov80"] = round(
                        _normal_coverage(sub[pred_col], sub[sd_col], sub[spec.outcome_col]),
                        4,
                    )
                rows.append(report)
        return rows

    def calibration(self, joined: pd.DataFrame) -> pd.DataFrame:
        frames = []
        for spec in self.specs:
            if spec.kind != "binary":
                continue
            col = f"{spec.name}_prob"
            if col not in joined.columns:
                continue
            sub = joined.dropna(subset=[col, spec.outcome_col])
            if sub.empty:
                continue
            table = M.calibration_table(sub[spec.outcome_col], sub[col])
            table.insert(0, "target", spec.name)
            frames.append(table)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _normal_coverage(mu: pd.Series, sd: pd.Series, actual: pd.Series, level: float = 0.80) -> float:
    """Share of outcomes inside the central `level` Normal interval.

    Reported next to MAE because a regression can have a fine MAE and still be
    lying about its own uncertainty, and the prop layer is built on that spread.
    """
    from scipy import stats

    lo, hi = (1 - level) / 2, 1 - (1 - level) / 2
    low = stats.norm.ppf(lo, mu, sd)
    high = stats.norm.ppf(hi, mu, sd)
    return float(np.mean((actual >= low) & (actual <= high)))


@dataclass
class WalkForwardResult:
    predictions: pd.DataFrame
    by_season: pd.DataFrame
    overall: pd.DataFrame
    calibration: pd.DataFrame

    def describe(self) -> str:
        lines = ["=== overall (all test seasons pooled) ===", self.overall.to_string(index=False)]
        if not self.by_season.empty:
            lines += ["", "=== by test season ===", self.by_season.to_string(index=False)]
        if not self.calibration.empty:
            lines += ["", "=== calibration ===", self.calibration.to_string(index=False)]
        return "\n".join(lines)


def walk_forward(
    features: pd.DataFrame,
    model_factory: Callable[[], MarketModel],
    *,
    season_col: str = "season",
    first_test_season: int | None = None,
    min_train_seasons: int = 2,
) -> WalkForwardResult:
    """Roll through seasons: fit on everything before, predict, score, repeat.

    Returns per-season and pooled metrics plus the full out-of-sample
    prediction set — every number reported is out-of-sample by construction.
    """
    if season_col not in features.columns:
        raise KeyError(f"features have no {season_col!r} column to split on")
    features = features.sort_values(season_col).copy()
    seasons = sorted(features[season_col].dropna().unique())
    if len(seasons) <= min_train_seasons:
        raise ValueError(
            f"need more than {min_train_seasons} seasons to walk forward, got {len(seasons)}"
        )

    candidates = seasons[min_train_seasons:]
    if first_test_season is not None:
        candidates = [s for s in candidates if s >= first_test_season]
    if not candidates:
        raise ValueError(
            f"no test seasons left after first_test_season={first_test_season}; "
            f"available seasons: {seasons}"
        )

    pred_frames, season_rows, calib_frames = [], [], []
    for test_season in candidates:
        train = features[features[season_col] < test_season]
        test = features[features[season_col] == test_season]
        if train.empty or test.empty:
            continue

        # The guarantee, checked rather than assumed.
        if train[season_col].max() >= test_season:
            raise LeakageError(
                f"training fold reaches season {train[season_col].max()} "
                f"while testing on {test_season}"
            )

        model = model_factory()
        try:
            model.fit(train)
        except ValueError as exc:
            log.warning("season %s: skipped, could not fit (%s)", test_season, exc)
            continue

        preds = model.predict_frame(test)
        joined = test.join(preds)
        joined.insert(0, "test_season", test_season)
        pred_frames.append(joined)

        for row in model.evaluate(joined):
            season_rows.append({"test_season": test_season, **row})

        calib = model.calibration(joined)
        if not calib.empty:
            calib.insert(0, "test_season", test_season)
            calib_frames.append(calib)

        log.info("season %s: trained on %s rows, scored %s", test_season, len(train), len(test))

    if not pred_frames:
        raise ValueError("walk-forward produced no folds; check the season column and filters")

    predictions = pd.concat(pred_frames)
    by_season = pd.DataFrame(season_rows)

    # Pooled metrics: refit the last model's evaluator over every fold's
    # predictions at once, so `overall` is not an average of per-season averages.
    final_model = model_factory()
    final_model.fit(features[features[season_col] < candidates[-1]])
    overall = pd.DataFrame(final_model.evaluate(predictions))
    calibration = (
        pd.concat(calib_frames, ignore_index=True) if calib_frames else pd.DataFrame()
    )
    return WalkForwardResult(predictions, by_season, overall, calibration)
