"""Predictive distributions.

Non-negotiable #2 from the build spec: *every prediction traceable to a
probability or distribution, not just a point pick*. So no model in this
project returns a bare float. They all return one of the objects below, which
can answer "what is P(over 47.5)?" or "what is P(at least 1 TD)?" directly.

That is deliberately more than the current scope needs — nothing here compares
to a book line yet — but it is the shape the EV phase will need, and retrofitting
a variance onto a point estimate later is not possible.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
from scipy import stats


class PredictiveDistribution(ABC):
    """A distribution over a single outcome for a single game/player."""

    @property
    @abstractmethod
    def mean(self) -> float: ...

    @property
    @abstractmethod
    def var(self) -> float: ...

    @property
    def sd(self) -> float:
        return float(np.sqrt(self.var))

    @abstractmethod
    def cdf(self, x: float) -> float:
        """P(X <= x)."""

    @abstractmethod
    def pmf_or_pdf(self, x: float) -> float:
        """Density (continuous) or mass (discrete) at x — used for log loss."""

    @abstractmethod
    def quantile(self, q: float) -> float: ...

    def prob_over(self, line: float) -> float:
        """P(X > line). On an integer line this excludes the push."""
        return float(1.0 - self.cdf(line))

    def prob_under(self, line: float) -> float:
        """P(X < line). On an integer line this excludes the push."""
        return float(self.cdf(line) - self.prob_exactly(line))

    def prob_exactly(self, x: float) -> float:
        """P(X == x). Zero for continuous distributions; the push probability."""
        return 0.0

    def summary(self, prefix: str = "") -> dict[str, float]:
        """Flat dict for writing one prediction row to CSV."""
        p = f"{prefix}_" if prefix else ""
        return {
            f"{p}mean": round(self.mean, 4),
            f"{p}sd": round(self.sd, 4),
            f"{p}p10": round(self.quantile(0.10), 4),
            f"{p}p50": round(self.quantile(0.50), 4),
            f"{p}p90": round(self.quantile(0.90), 4),
        }


@dataclass(frozen=True)
class NormalDistribution(PredictiveDistribution):
    """Continuous target: point margin, total points, passing/rushing yards."""

    mu: float
    sigma: float

    def __post_init__(self) -> None:
        if not np.isfinite(self.mu) or not np.isfinite(self.sigma):
            raise ValueError(f"non-finite Normal({self.mu}, {self.sigma})")
        if self.sigma <= 0:
            raise ValueError(f"Normal sigma must be positive, got {self.sigma}")

    @property
    def mean(self) -> float:
        return float(self.mu)

    @property
    def var(self) -> float:
        return float(self.sigma**2)

    def cdf(self, x: float) -> float:
        return float(stats.norm.cdf(x, self.mu, self.sigma))

    def pmf_or_pdf(self, x: float) -> float:
        return float(stats.norm.pdf(x, self.mu, self.sigma))

    def quantile(self, q: float) -> float:
        return float(stats.norm.ppf(q, self.mu, self.sigma))


@dataclass(frozen=True)
class PoissonDistribution(PredictiveDistribution):
    """Low-frequency counts: touchdowns, goals, cards."""

    lam: float

    def __post_init__(self) -> None:
        if not np.isfinite(self.lam) or self.lam < 0:
            raise ValueError(f"Poisson lambda must be finite and >= 0, got {self.lam}")

    @property
    def mean(self) -> float:
        return float(self.lam)

    @property
    def var(self) -> float:
        return float(self.lam)

    def cdf(self, x: float) -> float:
        return float(stats.poisson.cdf(np.floor(x), self.lam))

    def pmf_or_pdf(self, x: float) -> float:
        return float(stats.poisson.pmf(x, self.lam))

    def quantile(self, q: float) -> float:
        return float(stats.poisson.ppf(q, self.lam))

    def prob_exactly(self, x: float) -> float:
        if x != np.floor(x):
            return 0.0
        return float(stats.poisson.pmf(x, self.lam))

    def prob_at_least(self, k: int) -> float:
        """P(X >= k). `prob_at_least(1)` is the anytime-scorer probability."""
        return float(1.0 - stats.poisson.cdf(k - 1, self.lam))


@dataclass(frozen=True)
class NegativeBinomialDistribution(PredictiveDistribution):
    """Overdispersed counts: receptions, shots on target.

    Parameterised by mean `mu` and dispersion `alpha`, where
    Var = mu + alpha * mu^2. alpha -> 0 recovers the Poisson. Real receiving
    and shot data is reliably wider than Poisson, and using Poisson there would
    understate the tails — exactly the part that matters for a prop line.
    """

    mu: float
    alpha: float

    def __post_init__(self) -> None:
        if not np.isfinite(self.mu) or self.mu <= 0:
            raise ValueError(f"NegBinom mu must be finite and > 0, got {self.mu}")
        if self.alpha <= 0:
            raise ValueError(f"NegBinom alpha must be > 0, got {self.alpha}")

    @property
    def _n(self) -> float:
        return 1.0 / self.alpha

    @property
    def _p(self) -> float:
        return self._n / (self._n + self.mu)

    @property
    def mean(self) -> float:
        return float(self.mu)

    @property
    def var(self) -> float:
        return float(self.mu + self.alpha * self.mu**2)

    def cdf(self, x: float) -> float:
        return float(stats.nbinom.cdf(np.floor(x), self._n, self._p))

    def pmf_or_pdf(self, x: float) -> float:
        return float(stats.nbinom.pmf(x, self._n, self._p))

    def quantile(self, q: float) -> float:
        return float(stats.nbinom.ppf(q, self._n, self._p))

    def prob_exactly(self, x: float) -> float:
        if x != np.floor(x):
            return 0.0
        return float(stats.nbinom.pmf(x, self._n, self._p))

    def prob_at_least(self, k: int) -> float:
        return float(1.0 - stats.nbinom.cdf(k - 1, self._n, self._p))


class LatticeShape:
    """The key-number structure of a discrete outcome, learned from history.

    Football margins are not smooth. 14.7% of NFL games are decided by exactly
    3 points and 8.5% by exactly 7, because scores are built out of 3s and 7s.
    A Normal distribution puts about 3% on each, so it cannot price a -3 spread,
    where the push is the single biggest term.

    The fix is to separate two things that a Normal conflates:

    * *where* the distribution sits and how wide it is - that is what the
      regression model predicts, and it moves game to game;
    * *which values are intrinsically common* - that is a property of how
      football scoring works, and barely moves at all.

    This class captures the second part as a multiplicative `bump` per integer:
    the ratio of how often a value actually occurs to how often a smooth
    distribution of the same shape would produce it. Values on key numbers get
    a bump above 1; a tie, which needs overtime to finish level, gets a bump
    well below 1.

    Fitted on the training fold only.
    """

    __slots__ = ("values", "bump", "_lookup")

    # Values seen fewer times than this are not evidence of anything.
    MIN_COUNT = 5
    # Half-width of the smoothing window used to build the reference density.
    SMOOTH_HALFWIDTH = 4
    # A bump outside this range is noise, not structure.
    BUMP_CLIP = (0.05, 8.0)

    def __init__(self, values: np.ndarray, bump: np.ndarray) -> None:
        self.values = np.asarray(values, dtype=float)
        self.bump = np.asarray(bump, dtype=float)
        self._lookup = {int(v): float(b) for v, b in zip(self.values, self.bump)}

    @classmethod
    def from_outcomes(cls, outcomes: np.ndarray) -> "LatticeShape":
        y = np.asarray(outcomes, dtype=float)
        y = y[np.isfinite(y)]
        y = np.round(y).astype(int)
        if y.size < 200:
            raise ValueError(f"need at least 200 outcomes to learn a lattice shape, got {y.size}")

        lo, hi = int(y.min()), int(y.max())
        grid = np.arange(lo, hi + 1)
        counts = np.bincount(y - lo, minlength=grid.size).astype(float)
        empirical = counts / counts.sum()

        # Reference density: the same histogram smoothed over a window wide
        # enough to erase the key-number spikes but narrow enough to keep the
        # overall shape. The ratio of the two is what the spikes actually are.
        width = 2 * cls.SMOOTH_HALFWIDTH + 1
        kernel = np.ones(width) / width
        reference = np.convolve(empirical, kernel, mode="same")

        with np.errstate(divide="ignore", invalid="ignore"):
            bump = np.where(reference > 0, empirical / reference, 1.0)
        # Only trust the bump where there is enough data behind it.
        bump = np.where(counts >= cls.MIN_COUNT, bump, 1.0)
        bump = np.clip(np.nan_to_num(bump, nan=1.0), *cls.BUMP_CLIP)
        return cls(grid.astype(float), bump)

    def factor(self, value: float) -> float:
        """Bump for one value; 1.0 (no adjustment) outside the learned range."""
        return self._lookup.get(int(round(value)), 1.0)

    def top_key_numbers(self, n: int = 6) -> list[tuple[int, float]]:
        """The most inflated values — a readable summary of what was learned."""
        order = np.argsort(self.bump)[::-1][:n]
        return [(int(self.values[i]), float(self.bump[i])) for i in order]


class LatticeDistribution(PredictiveDistribution):
    """A discrete predictive distribution over integers, with key numbers.

    Built as `smooth density at the predicted mean and spread` x `the learned
    lattice shape`, renormalised. The regression model decides where the mass
    sits; the lattice shape decides how it clumps onto football's real scoring
    values.
    """

    __slots__ = ("mu", "sigma", "_values", "_weights", "_cum")

    # Support runs this many predicted standard deviations either side.
    SUPPORT_SDS = 5.0

    def __init__(self, mu: float, sigma: float, shape: LatticeShape) -> None:
        if not np.isfinite(mu) or not np.isfinite(sigma) or sigma <= 0:
            raise ValueError(f"LatticeDistribution needs finite mu and positive sigma, got {mu}, {sigma}")
        self.mu = float(mu)
        self.sigma = float(sigma)

        lo = int(np.floor(mu - self.SUPPORT_SDS * sigma))
        hi = int(np.ceil(mu + self.SUPPORT_SDS * sigma))
        values = np.arange(lo, hi + 1, dtype=float)

        # Integrate the smooth density across each integer's cell rather than
        # sampling it at the centre, so the weights are a genuine pmf.
        upper = stats.norm.cdf(values + 0.5, mu, sigma)
        lower = stats.norm.cdf(values - 0.5, mu, sigma)
        weights = (upper - lower) * np.array([shape.factor(v) for v in values])

        total = weights.sum()
        if not np.isfinite(total) or total <= 0:
            raise ValueError("lattice distribution collapsed to zero mass")
        self._values = values
        self._weights = weights / total
        self._cum = np.cumsum(self._weights)

    @property
    def mean(self) -> float:
        return float(np.dot(self._values, self._weights))

    @property
    def var(self) -> float:
        return float(np.dot((self._values - self.mean) ** 2, self._weights))

    def cdf(self, x: float) -> float:
        idx = np.searchsorted(self._values, x, side="right") - 1
        return float(self._cum[idx]) if idx >= 0 else 0.0

    def pmf_or_pdf(self, x: float) -> float:
        return self.prob_exactly(x)

    def prob_exactly(self, x: float) -> float:
        if abs(x - round(x)) > 1e-9:
            return 0.0
        match = np.isclose(self._values, round(x))
        return float(self._weights[match].sum()) if match.any() else 0.0

    def quantile(self, q: float) -> float:
        idx = int(np.searchsorted(self._cum, q))
        return float(self._values[min(idx, self._values.size - 1)])


@dataclass(frozen=True)
class BernoulliOutcome(PredictiveDistribution):
    """A binary event: home win, anytime touchdown, player to be carded."""

    p: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.p <= 1.0 or not np.isfinite(self.p):
            raise ValueError(f"Bernoulli p must be in [0, 1], got {self.p}")

    @property
    def mean(self) -> float:
        return float(self.p)

    @property
    def var(self) -> float:
        return float(self.p * (1.0 - self.p))

    def cdf(self, x: float) -> float:
        if x < 0:
            return 0.0
        return 1.0 - self.p if x < 1 else 1.0

    def pmf_or_pdf(self, x: float) -> float:
        return float(self.p if x == 1 else (1.0 - self.p) if x == 0 else 0.0)

    def quantile(self, q: float) -> float:
        return float(0.0 if q <= 1.0 - self.p else 1.0)

    def summary(self, prefix: str = "") -> dict[str, float]:
        p = f"{prefix}_" if prefix else ""
        return {f"{p}prob": round(self.p, 4)}


@dataclass(frozen=True)
class CategoricalDistribution(PredictiveDistribution):
    """A named multi-outcome market — for EPL, the 1X2 (home/draw/away)."""

    labels: tuple[str, ...]
    probs: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.labels) != len(self.probs):
            raise ValueError("labels and probs must be the same length")
        total = float(np.sum(self.probs))
        if not np.isclose(total, 1.0, atol=1e-6):
            raise ValueError(f"probabilities must sum to 1, got {total}")

    def prob(self, label: str) -> float:
        try:
            return float(self.probs[self.labels.index(label)])
        except ValueError:
            raise KeyError(f"{label!r} not in {self.labels}") from None

    # The index-space moments below exist only to satisfy the interface;
    # a 1X2 market has no meaningful mean, so use prob()/summary() instead.
    @property
    def mean(self) -> float:
        return float(np.dot(np.arange(len(self.probs)), self.probs))

    @property
    def var(self) -> float:
        idx = np.arange(len(self.probs))
        return float(np.dot(idx**2, self.probs) - self.mean**2)

    def cdf(self, x: float) -> float:
        return float(np.sum(self.probs[: int(np.floor(x)) + 1]))

    def pmf_or_pdf(self, x: float) -> float:
        i = int(x)
        return float(self.probs[i]) if 0 <= i < len(self.probs) else 0.0

    def quantile(self, q: float) -> float:
        return float(np.searchsorted(np.cumsum(self.probs), q))

    def summary(self, prefix: str = "") -> dict[str, float]:
        p = f"{prefix}_" if prefix else ""
        return {f"{p}{lab}": round(pr, 4) for lab, pr in zip(self.labels, self.probs)}


class ScorelineDistribution:
    """A joint distribution over (home goals, away goals).

    This is the object the EPL model actually produces. The spec calls for
    win/draw/loss, Asian handicap and over/under to be *derived from the same
    underlying scoreline distribution* rather than fitted as three separate
    classifiers — that way the markets are guaranteed mutually consistent.
    """

    def __init__(self, grid: np.ndarray) -> None:
        grid = np.asarray(grid, dtype=float)
        if grid.ndim != 2:
            raise ValueError("scoreline grid must be 2-D (home goals x away goals)")
        total = grid.sum()
        if not np.isfinite(total) or total <= 0:
            raise ValueError("scoreline grid must have positive finite mass")
        # Renormalise: the grid is truncated at max_goals, so it is a hair short.
        self.grid = grid / total

    @property
    def max_goals(self) -> int:
        return self.grid.shape[0] - 1

    def outcome_probs(self) -> CategoricalDistribution:
        """Home win / draw / away win."""
        home = float(np.tril(self.grid, -1).sum())
        draw = float(np.trace(self.grid))
        away = float(np.triu(self.grid, 1).sum())
        return CategoricalDistribution(("home", "draw", "away"), (home, draw, away))

    def supremacy(self) -> PredictiveDistribution:
        """Distribution of (home goals - away goals) — the handicap market."""
        diffs = np.subtract.outer(
            np.arange(self.grid.shape[0]), np.arange(self.grid.shape[1])
        )
        return _EmpiricalDistribution(diffs.ravel(), self.grid.ravel())

    def total_goals(self) -> PredictiveDistribution:
        """Distribution of total goals — the over/under market."""
        totals = np.add.outer(
            np.arange(self.grid.shape[0]), np.arange(self.grid.shape[1])
        )
        return _EmpiricalDistribution(totals.ravel(), self.grid.ravel())

    def team_goals(self, side: str) -> PredictiveDistribution:
        """Marginal goal distribution for one side — team totals."""
        if side == "home":
            values, weights = np.arange(self.grid.shape[0]), self.grid.sum(axis=1)
        elif side == "away":
            values, weights = np.arange(self.grid.shape[1]), self.grid.sum(axis=0)
        else:
            raise ValueError("side must be 'home' or 'away'")
        return _EmpiricalDistribution(values, weights)

    def asian_handicap(self, line: float) -> dict[str, float]:
        """P(home covers / push / away covers) at a handicap `line`.

        `line` is applied to the home side: -1.5 means home must win by 2+.
        Quarter lines (e.g. -0.75) split the stake across the two adjacent
        half-lines, which is what the market actually does.
        """
        if abs(line * 4 - round(line * 4)) > 1e-9:
            raise ValueError(f"handicap {line} is not a quarter-line multiple")
        if abs(line * 2 - round(line * 2)) > 1e-9:  # quarter line: split it
            low, high = line - 0.25, line + 0.25
            a, b = self.asian_handicap(low), self.asian_handicap(high)
            return {k: (a[k] + b[k]) / 2 for k in a}
        sup = self.supremacy()
        return {
            "home": sup.prob_over(-line),
            "push": sup.prob_exactly(-line),
            "away": sup.prob_under(-line),
        }

    def btts(self) -> float:
        """P(both teams to score)."""
        return float(self.grid[1:, 1:].sum())

    def most_likely_scoreline(self) -> tuple[int, int, float]:
        i, j = np.unravel_index(int(np.argmax(self.grid)), self.grid.shape)
        return int(i), int(j), float(self.grid[i, j])


class _EmpiricalDistribution(PredictiveDistribution):
    """A discrete distribution read off a weighted set of values.

    Produced by collapsing a scoreline grid onto supremacy / totals; not
    constructed directly.
    """

    def __init__(self, values: np.ndarray, weights: np.ndarray) -> None:
        values = np.asarray(values, dtype=float).ravel()
        weights = np.asarray(weights, dtype=float).ravel()
        order = np.argsort(values, kind="stable")
        values, weights = values[order], weights[order]
        # Collapse duplicate values (many cells share a supremacy/total).
        self.values, index = np.unique(values, return_inverse=True)
        self.weights = np.bincount(index, weights=weights, minlength=self.values.size)
        self.weights /= self.weights.sum()

    @property
    def mean(self) -> float:
        return float(np.dot(self.values, self.weights))

    @property
    def var(self) -> float:
        return float(np.dot((self.values - self.mean) ** 2, self.weights))

    def cdf(self, x: float) -> float:
        return float(self.weights[self.values <= x].sum())

    def pmf_or_pdf(self, x: float) -> float:
        return self.prob_exactly(x)

    def prob_exactly(self, x: float) -> float:
        match = np.isclose(self.values, x)
        return float(self.weights[match].sum()) if match.any() else 0.0

    def quantile(self, q: float) -> float:
        idx = int(np.searchsorted(np.cumsum(self.weights), q))
        return float(self.values[min(idx, self.values.size - 1)])
