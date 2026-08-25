"""Evaluation metrics: calibration first, accuracy second.

There is no market data wired in, so there is no ROI to report and none of
these are betting metrics. The question they answer is narrower and more
useful right now: *when the model says 62%, does it happen 62% of the time?*
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.distributions import PredictiveDistribution

_EPS = 1e-15


def _clean_pairs(y_true, y_pred) -> tuple[np.ndarray, np.ndarray]:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    if y_true.shape != y_pred.shape:
        raise ValueError(f"shape mismatch: {y_true.shape} vs {y_pred.shape}")
    keep = np.isfinite(y_true) & np.isfinite(y_pred)
    if not keep.any():
        raise ValueError("no finite (actual, prediction) pairs to score")
    return y_true[keep], y_pred[keep]


# --- classification ---------------------------------------------------------


def brier_score(y_true, y_prob) -> float:
    """Mean squared error of a probability forecast. Lower is better."""
    y_true, y_prob = _clean_pairs(y_true, y_prob)
    return float(np.mean((y_prob - y_true) ** 2))


def log_loss(y_true, y_prob) -> float:
    """Negative log likelihood per observation. Punishes confident misses."""
    y_true, y_prob = _clean_pairs(y_true, y_prob)
    p = np.clip(y_prob, _EPS, 1 - _EPS)
    return float(-np.mean(y_true * np.log(p) + (1 - y_true) * np.log(1 - p)))


def multiclass_log_loss(y_true_idx, probs) -> float:
    """Log loss for a k-outcome market (EPL 1X2). `probs` is (n, k)."""
    probs = np.clip(np.asarray(probs, dtype=float), _EPS, 1.0)
    probs = probs / probs.sum(axis=1, keepdims=True)
    idx = np.asarray(y_true_idx, dtype=int)
    return float(-np.mean(np.log(probs[np.arange(len(idx)), idx])))


def multiclass_brier(y_true_idx, probs) -> float:
    """Multi-class Brier (sum of squared error across outcomes, averaged)."""
    probs = np.asarray(probs, dtype=float)
    onehot = np.zeros_like(probs)
    onehot[np.arange(len(y_true_idx)), np.asarray(y_true_idx, dtype=int)] = 1.0
    return float(np.mean(np.sum((probs - onehot) ** 2, axis=1)))


def accuracy(y_true, y_prob, threshold: float = 0.5) -> float:
    y_true, y_prob = _clean_pairs(y_true, y_prob)
    return float(np.mean((y_prob >= threshold).astype(float) == y_true))


def baseline_brier(y_true) -> float:
    """Brier of always predicting the base rate — the bar to clear."""
    y_true = np.asarray(y_true, dtype=float)
    y_true = y_true[np.isfinite(y_true)]
    return float(np.mean((y_true.mean() - y_true) ** 2))


def calibration_table(y_true, y_prob, bins: int = 10) -> pd.DataFrame:
    """Predicted vs. observed frequency by probability decile.

    The single most informative output in this file: a model can have a decent
    Brier score and still be systematically overconfident, and only this shows
    it.
    """
    y_true, y_prob = _clean_pairs(y_true, y_prob)
    edges = np.linspace(0.0, 1.0, bins + 1)
    which = np.clip(np.digitize(y_prob, edges[1:-1], right=False), 0, bins - 1)
    rows = []
    for b in range(bins):
        mask = which == b
        if not mask.any():
            continue
        rows.append(
            {
                "bin": f"[{edges[b]:.1f}, {edges[b + 1]:.1f})",
                "n": int(mask.sum()),
                "mean_predicted": round(float(y_prob[mask].mean()), 4),
                "observed_rate": round(float(y_true[mask].mean()), 4),
                "gap": round(float(y_prob[mask].mean() - y_true[mask].mean()), 4),
            }
        )
    return pd.DataFrame(rows)


def expected_calibration_error(y_true, y_prob, bins: int = 10) -> float:
    """Sample-weighted mean |predicted - observed| across bins."""
    table = calibration_table(y_true, y_prob, bins=bins)
    if table.empty:
        return float("nan")
    weights = table["n"] / table["n"].sum()
    return float((weights * table["gap"].abs()).sum())


# --- regression -------------------------------------------------------------


def mae(y_true, y_pred) -> float:
    y_true, y_pred = _clean_pairs(y_true, y_pred)
    return float(np.mean(np.abs(y_pred - y_true)))


def rmse(y_true, y_pred) -> float:
    y_true, y_pred = _clean_pairs(y_true, y_pred)
    return float(np.sqrt(np.mean((y_pred - y_true) ** 2)))


def bias(y_true, y_pred) -> float:
    """Mean signed error — catches a model that is tilted, not just noisy."""
    y_true, y_pred = _clean_pairs(y_true, y_pred)
    return float(np.mean(y_pred - y_true))


# --- distributional ---------------------------------------------------------


def pit_coverage(
    distributions: list[PredictiveDistribution], y_true, level: float = 0.80
) -> float:
    """Share of outcomes inside the model's central `level` interval.

    A model claiming an 80% interval that only contains 60% of outcomes has an
    understated variance — which a point-estimate metric like MAE cannot see,
    and which would misprice every prop line built on it.
    """
    lo, hi = (1 - level) / 2, 1 - (1 - level) / 2
    y_true = np.asarray(y_true, dtype=float)
    inside = [
        d.quantile(lo) <= y <= d.quantile(hi)
        for d, y in zip(distributions, y_true)
        if np.isfinite(y)
    ]
    if not inside:
        raise ValueError("no finite outcomes to score coverage against")
    return float(np.mean(inside))


def mean_log_score(distributions: list[PredictiveDistribution], y_true) -> float:
    """Mean negative log density/mass of the realised outcome.

    The general-purpose scoring rule for a distributional forecast: it grades
    the whole shape, not just the centre. Lower is better.
    """
    y_true = np.asarray(y_true, dtype=float)
    scores = [
        -np.log(max(d.pmf_or_pdf(y), _EPS))
        for d, y in zip(distributions, y_true)
        if np.isfinite(y)
    ]
    if not scores:
        raise ValueError("no finite outcomes to score")
    return float(np.mean(scores))


def classification_report(y_true, y_prob, *, label: str = "") -> dict[str, float]:
    return {
        "target": label,
        "n": int(np.isfinite(np.asarray(y_prob, dtype=float)).sum()),
        "brier": round(brier_score(y_true, y_prob), 5),
        "baseline_brier": round(baseline_brier(y_true), 5),
        "log_loss": round(log_loss(y_true, y_prob), 5),
        "accuracy": round(accuracy(y_true, y_prob), 5),
        "ece": round(expected_calibration_error(y_true, y_prob), 5),
    }


def regression_report(y_true, y_pred, *, label: str = "") -> dict[str, float]:
    return {
        "target": label,
        "n": int(np.isfinite(np.asarray(y_pred, dtype=float)).sum()),
        "mae": round(mae(y_true, y_pred), 4),
        "rmse": round(rmse(y_true, y_pred), 4),
        "bias": round(bias(y_true, y_pred), 4),
    }
