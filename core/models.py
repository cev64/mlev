"""Model wrappers that emit distributions rather than point estimates.

Every class here exposes the same two methods — `fit(X, y)` and
`predict_dist(X) -> list[PredictiveDistribution]` — so the backtest engine and
the scoring job never need to know which sport or which target they are
holding. Swapping a logistic regression for gradient boosting is a constructor
argument, not a code change downstream.

Deliberately boring estimators. The spec says to start with a well-understood
baseline before anything fancier, and a well-calibrated logistic regression is
worth more here than an uncalibrated ensemble.
"""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import (
    LogisticRegression,
    LogisticRegressionCV,
    PoissonRegressor,
    Ridge,
    RidgeCV,
)
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from core.distributions import (
    BernoulliOutcome,
    NegativeBinomialDistribution,
    NormalDistribution,
    PoissonDistribution,
    PredictiveDistribution,
)
from core.errors import ModelNotFittedError

# A ridge on log|residual| predicts E[log|r|], not log E|r|. For r ~ N(0, s),
# E[log|r|] = log(s) - (euler_gamma + log 2)/2, so recovering s means undoing
# that bias -- not multiplying by sqrt(pi/2), which converts E|r| -> s and
# would leave every predicted interval ~34% too narrow.
_LOG_RESID_TO_SIGMA = float(np.exp(0.5 * (np.euler_gamma + np.log(2.0))))

# Residual NaNs after `drop_thin_history` are rare and structural (a rookie's
# first game has no prior target share). Imputing the *training median* inside
# the fitted pipeline is not fabricating a data source: the statistic is learned
# from the training fold only, so it can never carry information backwards from
# the test fold.
def _prep(scale: bool) -> list[tuple[str, object]]:
    steps: list[tuple[str, object]] = [("impute", SimpleImputer(strategy="median"))]
    if scale:
        steps.append(("scale", StandardScaler()))
    return steps


# Regularisation strength is chosen by cross-validation *inside the training
# fold*, using forward-chaining splits so the inner folds respect time order
# too. Picking a penalty by looking at walk-forward test scores would be
# choosing a hyperparameter on the test set — the backtest would then be
# reporting a number it could not reproduce live.
_INNER_CV_SPLITS = 4


def _supported(cls, **kwargs) -> dict:
    """Keep only kwargs this scikit-learn version actually accepts.

    Lets the project pin forward-looking defaults (so a sklearn upgrade cannot
    silently change how the penalty is selected) while still importing on the
    older versions allowed by requirements.txt.
    """
    accepted = inspect.signature(cls).parameters
    return {k: v for k, v in kwargs.items() if k in accepted}


def _inner_cv(n_rows: int) -> TimeSeriesSplit | int:
    """Forward-chaining inner CV, degrading to plain k-fold on small folds."""
    if n_rows >= 400:
        return TimeSeriesSplit(n_splits=_INNER_CV_SPLITS)
    return 3


def _weight_kwargs(pipeline: Pipeline, sample_weight: np.ndarray | None) -> dict:
    """Route sample weights to the final step of a fitted sklearn Pipeline.

    Pipelines take per-step fit params as `<step>__<param>`, so the caller does
    not need to know whether the estimator is called "clf" or "reg".
    """
    if sample_weight is None:
        return {}
    final_step = pipeline.steps[-1][0]
    return {f"{final_step}__sample_weight": np.asarray(sample_weight, dtype=float)}


class BaseModel(ABC):
    """Common fit/predict contract for every model in the project."""

    def __init__(self, feature_cols: list[str], *, name: str = "") -> None:
        self.feature_cols = list(feature_cols)
        self.name = name or type(self).__name__
        self._fitted = False

    def _matrix(self, X: pd.DataFrame) -> np.ndarray:
        missing = [c for c in self.feature_cols if c not in X.columns]
        if missing:
            raise KeyError(f"{self.name}: feature columns absent at predict time: {missing}")
        return X[self.feature_cols].to_numpy(dtype=float)

    def _check_fitted(self) -> None:
        if not self._fitted:
            raise ModelNotFittedError(f"{self.name}: call fit() before predict_dist()")

    @abstractmethod
    def fit(
        self, X: pd.DataFrame, y: pd.Series, sample_weight: np.ndarray | None = None
    ) -> "BaseModel":
        """Fit the model. `sample_weight` lets callers down-weight old seasons."""

    @abstractmethod
    def predict_dist(self, X: pd.DataFrame) -> list[PredictiveDistribution]: ...

    def predict_mean(self, X: pd.DataFrame) -> np.ndarray:
        """Convenience for regression metrics; the distribution is the product."""
        return np.array([d.mean for d in self.predict_dist(X)])


class BinaryProbabilityModel(BaseModel):
    """Win probability, anytime-touchdown, player-to-be-carded.

    `estimator="logistic"` is the default baseline. `"gbm"` swaps in gradient
    boosting wrapped in `CalibratedClassifierCV`, because raw boosted trees are
    reliably overconfident and an uncalibrated probability is useless for the
    EV phase this all feeds into.
    """

    def __init__(
        self,
        feature_cols: list[str],
        *,
        estimator: str = "logistic",
        C: float | None = None,
        random_state: int = 7,
        name: str = "",
    ) -> None:
        super().__init__(feature_cols, name=name)
        self.estimator = estimator
        self.C = C
        self.random_state = random_state
        self.pipeline: Pipeline | None = None
        self.base_rate_: float = float("nan")

    def _build(self, n_train: int) -> Pipeline:
        if self.estimator == "logistic":
            # C=None (the default) means "choose the penalty by inner CV".
            # Passing an explicit C pins it, which the tests use for determinism.
            if self.C is None:
                clf = LogisticRegressionCV(
                    Cs=np.logspace(-3, 1, 9),
                    cv=_inner_cv(n_train),
                    scoring="neg_log_loss",
                    max_iter=4000,
                    n_jobs=1,
                    **_supported(
                        LogisticRegressionCV,
                        # Pinned so a scikit-learn upgrade cannot change how the
                        # penalty is selected underneath the backtest.
                        l1_ratios=(0.0,),
                        use_legacy_attributes=False,
                    ),
                )
            else:
                clf = LogisticRegression(C=self.C, max_iter=4000)
            return Pipeline([*_prep(scale=True), ("clf", clf)])
        if self.estimator == "gbm":
            gbm = GradientBoostingClassifier(
                n_estimators=250,
                learning_rate=0.05,
                max_depth=3,
                subsample=0.8,
                random_state=self.random_state,
            )
            # Isotonic needs room to breathe; fall back to Platt on small folds.
            method = "isotonic" if n_train >= 1000 else "sigmoid"
            clf = CalibratedClassifierCV(gbm, method=method, cv=3)
            return Pipeline([*_prep(scale=False), ("clf", clf)])
        raise ValueError(f"unknown estimator {self.estimator!r}")

    def fit(
        self, X: pd.DataFrame, y: pd.Series, sample_weight: np.ndarray | None = None
    ) -> "BinaryProbabilityModel":
        y = pd.Series(y).astype(float)
        if y.nunique() < 2:
            raise ValueError(f"{self.name}: training target has a single class")
        self.base_rate_ = float(y.mean())
        self.pipeline = self._build(len(y))
        self.pipeline.fit(self._matrix(X), y.to_numpy(), **_weight_kwargs(self.pipeline, sample_weight))
        self._fitted = True
        return self

    def predict_dist(self, X: pd.DataFrame) -> list[BernoulliOutcome]:
        self._check_fitted()
        assert self.pipeline is not None
        probs = self.pipeline.predict_proba(self._matrix(X))[:, 1]
        probs = np.clip(probs, 1e-6, 1 - 1e-6)
        return [BernoulliOutcome(float(p)) for p in probs]

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return np.array([d.p for d in self.predict_dist(X)])


class GaussianRegressionModel(BaseModel):
    """Continuous targets: point margin, game total, passing/rushing yards.

    Fits a mean and a *spread*. The spread is the whole reason this class
    exists: a margin prediction of +3 is worth nothing for a spread market
    without knowing whether the sd is 9 or 14.

    With `heteroskedastic=True` a second model predicts log absolute residual,
    so a game between two volatile offences gets a wider distribution than a
    pair of run-heavy teams. Both models are fit on the training fold only.
    """

    def __init__(
        self,
        feature_cols: list[str],
        *,
        estimator: str = "ridge",
        alpha: float | None = None,
        heteroskedastic: bool = False,
        min_sigma: float = 1e-3,
        random_state: int = 7,
        name: str = "",
    ) -> None:
        super().__init__(feature_cols, name=name)
        self.estimator = estimator
        self.alpha = alpha
        self.heteroskedastic = heteroskedastic
        self.min_sigma = min_sigma
        self.random_state = random_state
        self.pipeline: Pipeline | None = None
        self.spread_pipeline: Pipeline | None = None
        self.sigma_: float = float("nan")

    def _build_mean(self, n_train: int) -> Pipeline:
        if self.estimator == "ridge":
            if self.alpha is None:
                reg = RidgeCV(alphas=np.logspace(-2, 4, 13), cv=_inner_cv(n_train))
            else:
                reg = Ridge(alpha=self.alpha)
            return Pipeline([*_prep(scale=True), ("reg", reg)])
        if self.estimator == "gbm":
            gbm = GradientBoostingRegressor(
                n_estimators=350,
                learning_rate=0.04,
                max_depth=3,
                subsample=0.8,
                random_state=self.random_state,
            )
            return Pipeline([*_prep(scale=False), ("reg", gbm)])
        raise ValueError(f"unknown estimator {self.estimator!r}")

    def fit(
        self, X: pd.DataFrame, y: pd.Series, sample_weight: np.ndarray | None = None
    ) -> "GaussianRegressionModel":
        y = pd.Series(y).astype(float)
        mat = self._matrix(X)
        self.pipeline = self._build_mean(len(y))
        self.pipeline.fit(mat, y.to_numpy(), **_weight_kwargs(self.pipeline, sample_weight))

        residuals = y.to_numpy() - self.pipeline.predict(mat)
        # In-sample residuals understate true error; the walk-forward backtest
        # is what tells you whether this sigma is honest (see pit_coverage).
        # Weighted, so the spread reflects recent seasons when weights are given.
        if sample_weight is None:
            self.sigma_ = max(float(np.std(residuals, ddof=1)), self.min_sigma)
        else:
            w = np.asarray(sample_weight, dtype=float)
            mean = float(np.average(residuals, weights=w))
            var = float(np.average((residuals - mean) ** 2, weights=w))
            self.sigma_ = max(float(np.sqrt(var)), self.min_sigma)

        if self.heteroskedastic:
            log_abs = np.log(np.maximum(np.abs(residuals), self.min_sigma))
            self.spread_pipeline = Pipeline(
                [*_prep(scale=True), ("reg", RidgeCV(alphas=np.logspace(-2, 4, 13)))]
            )
            self.spread_pipeline.fit(
                mat, log_abs, **_weight_kwargs(self.spread_pipeline, sample_weight)
            )
        self._fitted = True
        return self

    def predict_dist(self, X: pd.DataFrame) -> list[NormalDistribution]:
        self._check_fitted()
        assert self.pipeline is not None
        mat = self._matrix(X)
        mu = self.pipeline.predict(mat)
        if self.spread_pipeline is not None:
            sigma = np.exp(self.spread_pipeline.predict(mat)) * _LOG_RESID_TO_SIGMA
            # Keep the learned spread inside a sane band around the pooled sd
            # so one odd row cannot produce a degenerate distribution.
            sigma = np.clip(sigma, 0.4 * self.sigma_, 2.5 * self.sigma_)
        else:
            sigma = np.full(len(mat), self.sigma_)
        return [
            NormalDistribution(float(m), float(max(s, self.min_sigma)))
            for m, s in zip(mu, sigma)
        ]


class PoissonCountModel(BaseModel):
    """Low-frequency counts: touchdowns, goals, cards.

    A log-link Poisson GLM. `predict_dist` returns a Poisson, so
    `prob_at_least(1)` gives the anytime-scorer probability directly rather
    than needing a separate classifier that could disagree with it.
    """

    def __init__(
        self,
        feature_cols: list[str],
        *,
        alpha: float = 1e-4,
        max_lambda: float = 25.0,
        name: str = "",
    ) -> None:
        super().__init__(feature_cols, name=name)
        self.alpha = alpha
        self.max_lambda = max_lambda
        self.pipeline: Pipeline | None = None

    def fit(
        self, X: pd.DataFrame, y: pd.Series, sample_weight: np.ndarray | None = None
    ) -> "PoissonCountModel":
        y = pd.Series(y).astype(float)
        if (y < 0).any():
            raise ValueError(f"{self.name}: Poisson target has negative values")
        self.pipeline = Pipeline(
            [
                *_prep(scale=True),
                ("reg", PoissonRegressor(alpha=self.alpha, max_iter=1000)),
            ]
        )
        self.pipeline.fit(
            self._matrix(X), y.to_numpy(), **_weight_kwargs(self.pipeline, sample_weight)
        )
        self._fitted = True
        return self

    def predict_dist(self, X: pd.DataFrame) -> list[PoissonDistribution]:
        self._check_fitted()
        assert self.pipeline is not None
        lam = np.clip(self.pipeline.predict(self._matrix(X)), 1e-6, self.max_lambda)
        return [PoissonDistribution(float(v)) for v in lam]


class NegativeBinomialCountModel(PoissonCountModel):
    """Overdispersed counts: receptions, shots on target.

    Same log-link mean as the Poisson, plus a dispersion estimated once on the
    training fold by method of moments. Real reception and shot counts have
    Var > Mean, and forcing them into a Poisson quietly understates the tails.
    """

    def __init__(
        self,
        feature_cols: list[str],
        *,
        alpha: float = 1e-4,
        max_lambda: float = 25.0,
        min_dispersion: float = 1e-3,
        name: str = "",
    ) -> None:
        super().__init__(feature_cols, alpha=alpha, max_lambda=max_lambda, name=name)
        self.min_dispersion = min_dispersion
        self.dispersion_: float = float("nan")

    def fit(
        self, X: pd.DataFrame, y: pd.Series, sample_weight: np.ndarray | None = None
    ) -> "NegativeBinomialCountModel":
        super().fit(X, y, sample_weight)
        assert self.pipeline is not None
        y_arr = pd.Series(y).astype(float).to_numpy()
        mu = np.clip(self.pipeline.predict(self._matrix(X)), 1e-6, self.max_lambda)
        # Var = mu + a*mu^2  =>  a = mean[ ((y-mu)^2 - mu) / mu^2 ]
        moment = ((y_arr - mu) ** 2 - mu) / np.maximum(mu**2, 1e-9)
        estimate = (
            np.mean(moment)
            if sample_weight is None
            else np.average(moment, weights=np.asarray(sample_weight, dtype=float))
        )
        self.dispersion_ = max(float(estimate), self.min_dispersion)
        return self

    def predict_dist(self, X: pd.DataFrame) -> list[NegativeBinomialDistribution]:
        self._check_fitted()
        assert self.pipeline is not None
        mu = np.clip(self.pipeline.predict(self._matrix(X)), 1e-6, self.max_lambda)
        return [
            NegativeBinomialDistribution(float(m), self.dispersion_) for m in mu
        ]
