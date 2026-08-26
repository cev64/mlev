"""The market as a benchmark, a feature, and a check on the model.

Everything else in this project answers "is the model right?". This module
answers the harder question: "is the model right about something the price does
not already know?" — which is the only question that decides whether a bet is
worth making.

Three things live here:

* **De-vigging a posted pair** into the market's own probability, so a model
  probability is compared against a number that does not include the house's
  margin.
* **Blending** the model's point estimate with the posted line. The line is not
  a competitor to be beaten so much as a very strong prior with thousands of
  people's information already in it, and the honest use of a model this size is
  to nudge that prior rather than replace it. The weight is fitted, never
  assumed, and always on training data only.
* **Settling bets** against realised outcomes, so the backtest can report what
  following the model would actually have returned rather than only how well
  calibrated it was.

A note on what the blend can and cannot do. Fitting
`margin ~ a + b*line + c*model` over 2019-2025 gives b ~ 0.97 and c ~ 0.10: the
model carries a little information the closing line does not, but only a little,
and a 3-4% hold is a large thing to overcome with it. Blending improves the
forecast. It does not manufacture an edge, and nothing here should be read as
claiming one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# Weight on the model when there is nothing to fit on. Deliberately small: the
# line is the better estimator of the two, so the safe default leans on it.
DEFAULT_BLEND_WEIGHT = 0.15

# The grid the fitted weight is chosen from. Coarse on purpose — the curve is
# flat near its minimum, and a finer grid would be fitting noise.
WEIGHT_GRID = np.round(np.arange(0.0, 1.01, 0.05), 2)


def american_to_decimal(american) -> np.ndarray:
    """Vectorised American -> decimal. NaN passes through as NaN."""
    a = np.asarray(american, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(a > 0, 1.0 + a / 100.0, 1.0 + 100.0 / np.abs(a))


def two_way_probability(home_price, away_price) -> np.ndarray:
    """The market's probability for the home side, with the margin removed.

    A book's two prices imply more than 100% between them; the excess is its
    hold. Normalising the pair is the standard way to recover what the market
    actually thinks, and it is the number a model probability should be
    compared against — comparing against the raw implied price compares against
    something with the house edge already baked in.
    """
    home_implied = 1.0 / american_to_decimal(home_price)
    away_implied = 1.0 / american_to_decimal(away_price)
    total = home_implied + away_implied
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(total > 0, home_implied / total, np.nan)


def hold(home_price, away_price) -> np.ndarray:
    """The book's margin on a two-way market, as a fraction."""
    return (
        1.0 / american_to_decimal(home_price) + 1.0 / american_to_decimal(away_price) - 1.0
    )


def blend(model_value, market_value, weight: float):
    """`weight` on the model, the rest on the market.

    Where the market has no line the model stands alone — a fixture priced too
    early to have one still gets a prediction, just without the benefit of the
    market's information.
    """
    model_value = np.asarray(model_value, dtype=float)
    market_value = np.asarray(market_value, dtype=float)
    w = float(np.clip(weight, 0.0, 1.0))
    blended = w * model_value + (1.0 - w) * market_value
    return np.where(np.isfinite(market_value), blended, model_value)


def fit_blend_weight(
    model_value,
    market_value,
    outcome,
    *,
    grid: np.ndarray = WEIGHT_GRID,
    min_rows: int = 100,
) -> float:
    """Pick the blend weight that minimises absolute error on *this* data.

    Called with a training fold and nothing else. Choosing the weight by
    looking at test-season results would be fitting the backtest, which is the
    one thing the walk-forward design exists to prevent.

    MAE rather than squared error because a handful of blowouts should not
    decide how much to trust the model on a normal Sunday.
    """
    model_value = np.asarray(model_value, dtype=float)
    market_value = np.asarray(market_value, dtype=float)
    outcome = np.asarray(outcome, dtype=float)
    usable = np.isfinite(model_value) & np.isfinite(market_value) & np.isfinite(outcome)
    if usable.sum() < min_rows:
        log.info(
            "blend weight: only %s usable rows, falling back to %s",
            int(usable.sum()), DEFAULT_BLEND_WEIGHT,
        )
        return DEFAULT_BLEND_WEIGHT

    m, k, y = model_value[usable], market_value[usable], outcome[usable]
    errors = [np.mean(np.abs(y - (w * m + (1.0 - w) * k))) for w in grid]
    return float(grid[int(np.argmin(errors))])


# --------------------------------------------------------------- settlement


@dataclass(frozen=True)
class BetResult:
    """What a set of bets returned, flat-staked at one unit each."""

    n: int
    roi: float
    hit_rate: float
    stderr: float
    mean_claimed_ev: float

    @property
    def roi_interval(self) -> tuple[float, float]:
        """95% interval on ROI. Nearly always contains zero, which is the point."""
        return (self.roi - 1.96 * self.stderr, self.roi + 1.96 * self.stderr)

    def to_dict(self) -> dict:
        low, high = self.roi_interval
        return {
            "n": self.n,
            "roi": round(self.roi, 5),
            "roi_low": round(low, 5),
            "roi_high": round(high, 5),
            "hit_rate": round(self.hit_rate, 5),
            "claimed_ev": round(self.mean_claimed_ev, 5),
        }


def settle(
    probability,
    price,
    won,
    *,
    min_ev: float = 0.0,
) -> BetResult:
    """Settle every bet whose expected value clears `min_ev`.

    `won` is the realised result with pushes already removed by the caller: a
    push returns the stake and belongs in neither column.

    ROI is total profit over total staked, at one unit a bet. A winner returns
    `decimal - 1`, a loser returns -1. This is the number that decides whether a
    model is worth betting, and it is a far higher bar than being well
    calibrated: at a 3.4% hold, a forecast can be better than the base rate by a
    wide margin and still lose money on every ticket.
    """
    p = np.asarray(probability, dtype=float)
    decimal = american_to_decimal(price)
    won = np.asarray(won, dtype=float)

    usable = np.isfinite(p) & np.isfinite(decimal) & np.isfinite(won)
    p, decimal, won = p[usable], decimal[usable], won[usable]

    ev = p * (decimal - 1.0) - (1.0 - p)
    chosen = ev > min_ev
    if not chosen.any():
        return BetResult(0, float("nan"), float("nan"), float("nan"), float("nan"))

    profit = np.where(won[chosen] > 0, decimal[chosen] - 1.0, -1.0)
    n = int(chosen.sum())
    return BetResult(
        n=n,
        roi=float(profit.mean()),
        hit_rate=float(won[chosen].mean()),
        stderr=float(profit.std(ddof=1) / np.sqrt(n)) if n > 1 else float("nan"),
        mean_claimed_ev=float(ev[chosen].mean()),
    )


def market_comparison(
    frame: pd.DataFrame,
    *,
    model_col: str,
    market_col: str,
    outcome_col: str,
    label: str,
) -> dict:
    """Model against the line on the same games, side by side.

    The comparison that matters and the one the project was missing: a model
    beating the base rate is table stakes, while beating the posted line is what
    a bet requires.
    """
    sub = frame.dropna(subset=[model_col, market_col, outcome_col])
    if sub.empty:
        return {}
    model_error = np.abs(sub[outcome_col] - sub[model_col])
    market_error = np.abs(sub[outcome_col] - sub[market_col])
    return {
        "target": label,
        "n": int(len(sub)),
        "model_mae": round(float(model_error.mean()), 4),
        "market_mae": round(float(market_error.mean()), 4),
        "model_beats_market": bool(model_error.mean() < market_error.mean()),
        "mean_disagreement": round(float(np.abs(sub[model_col] - sub[market_col]).mean()), 4),
    }
