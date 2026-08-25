"""Model and metric behaviour, on data whose right answer is known."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core import metrics as M
from core.errors import ModelNotFittedError
from core.models import (
    BinaryProbabilityModel,
    GaussianRegressionModel,
    NegativeBinomialCountModel,
    PoissonCountModel,
)


@pytest.fixture
def linear_data() -> tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series]:
    rng = np.random.default_rng(11)
    n = 2500
    X = pd.DataFrame({f"x{i}": rng.normal(size=n) for i in range(4)})
    logit = 0.9 * X["x0"] - 0.6 * X["x1"]
    y_bin = pd.Series((rng.uniform(size=n) < 1 / (1 + np.exp(-logit))).astype(float))
    y_num = pd.Series(4.0 + 2.0 * X["x0"] - 1.5 * X["x1"] + rng.normal(0, 3.0, n))
    y_cnt = pd.Series(rng.poisson(np.exp(0.3 + 0.5 * X["x0"])).astype(float))
    return X, y_bin, y_num, y_cnt


def test_predict_before_fit_raises(linear_data):
    X, *_ = linear_data
    with pytest.raises(ModelNotFittedError):
        BinaryProbabilityModel(list(X.columns)).predict_dist(X)


def test_binary_model_beats_the_base_rate(linear_data):
    X, y_bin, _, _ = linear_data
    model = BinaryProbabilityModel(list(X.columns), C=1.0).fit(X, y_bin)
    probs = model.predict_proba(X)
    assert M.brier_score(y_bin, probs) < M.baseline_brier(y_bin)
    assert M.expected_calibration_error(y_bin, probs) < 0.05


def test_binary_model_rejects_single_class(linear_data):
    X, *_ = linear_data
    with pytest.raises(ValueError, match="single class"):
        BinaryProbabilityModel(list(X.columns)).fit(X, pd.Series(np.ones(len(X))))


def test_gaussian_model_recovers_the_noise_scale(linear_data):
    X, _, y_num, _ = linear_data
    model = GaussianRegressionModel(list(X.columns), alpha=1.0).fit(X, y_num)
    dists = model.predict_dist(X)
    assert model.sigma_ == pytest.approx(3.0, rel=0.15)
    # The interval it advertises must contain roughly the share it claims.
    assert M.pit_coverage(dists, y_num, 0.80) == pytest.approx(0.80, abs=0.05)
    assert M.pit_coverage(dists, y_num, 0.50) == pytest.approx(0.50, abs=0.05)


def test_heteroskedastic_model_widens_where_noise_is_larger():
    rng = np.random.default_rng(12)
    n = 4000
    X = pd.DataFrame({"signal": rng.normal(size=n), "spread": rng.uniform(0, 1, n)})
    # Noise grows with `spread`, so the model should report a larger sd there.
    y = pd.Series(2.0 * X["signal"] + rng.normal(0, 1, n) * (0.5 + 4 * X["spread"]))
    model = GaussianRegressionModel(
        ["signal", "spread"], alpha=1.0, heteroskedastic=True
    ).fit(X, y)
    sds = np.array([d.sd for d in model.predict_dist(X)])
    quiet = sds[X["spread"] < 0.2].mean()
    noisy = sds[X["spread"] > 0.8].mean()
    assert noisy > quiet * 1.5


def test_poisson_model_matches_the_mean_count(linear_data):
    X, _, _, y_cnt = linear_data
    model = PoissonCountModel(list(X.columns)).fit(X, y_cnt)
    assert model.predict_mean(X).mean() == pytest.approx(y_cnt.mean(), rel=0.05)
    # Every prediction is a distribution, so P(at least one) is available.
    dists = model.predict_dist(X)
    assert all(0.0 <= d.prob_at_least(1) <= 1.0 for d in dists[:50])


def test_poisson_model_rejects_negative_targets(linear_data):
    X, _, y_num, _ = linear_data
    with pytest.raises(ValueError, match="negative"):
        PoissonCountModel(list(X.columns)).fit(X, y_num)


def test_negative_binomial_detects_overdispersion(linear_data):
    X, _, _, y_cnt = linear_data
    rng = np.random.default_rng(13)
    # Genuinely Poisson data -> dispersion near zero.
    tight = NegativeBinomialCountModel(list(X.columns)).fit(X, y_cnt)
    assert tight.dispersion_ < 0.05

    # Overdispersed data -> a clearly positive dispersion.
    mu = np.exp(0.3 + 0.5 * X["x0"])
    spread = pd.Series(rng.negative_binomial(2, 2 / (2 + mu)).astype(float))
    loose = NegativeBinomialCountModel(list(X.columns)).fit(X, spread)
    assert loose.dispersion_ > tight.dispersion_


def test_missing_feature_column_at_predict_time_is_loud(linear_data):
    X, y_bin, _, _ = linear_data
    model = BinaryProbabilityModel(list(X.columns), C=1.0).fit(X, y_bin)
    with pytest.raises(KeyError, match="absent at predict time"):
        model.predict_dist(X.drop(columns=["x2"]))


def test_calibration_error_separates_good_from_bad():
    rng = np.random.default_rng(14)
    p = rng.uniform(0.05, 0.95, 5000)
    y = (rng.uniform(size=5000) < p).astype(float)
    skewed = np.clip(p * 1.6 - 0.3, 0.01, 0.99)
    # Same ranking, so the same accuracy — only calibration differs.
    assert M.accuracy(y, p) == pytest.approx(M.accuracy(y, skewed))
    assert M.expected_calibration_error(y, p) < M.expected_calibration_error(y, skewed)


def test_metrics_reject_empty_input():
    with pytest.raises(ValueError):
        M.brier_score([np.nan], [np.nan])
