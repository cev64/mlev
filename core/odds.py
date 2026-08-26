"""Odds arithmetic: turning model probabilities into something comparable to a book.

The models produce probabilities. A sportsbook quotes prices. To compare them you
have to put both on the same scale, and there are two traps in doing that:

1. **A book's quoted prices do not sum to 100%.** The overround (the vig) is the
   book's margin. Comparing your 55% to a price that implies 55% is comparing
   against a number that already has the house edge baked in. `remove_vig`
   strips it so you are comparing like with like.
2. **Edge is not the same as expected value.** A 3-point edge on a +150 dog is
   worth far more per dollar than 3 points on a -300 favourite. `expected_value`
   is the number that actually decides whether a price is worth taking.

Nothing here reads odds from anywhere. You bring the price, this does the sums.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Below this, a probability is treated as "not a real market" rather than a
# 4000-to-1 shot the model is confident about.
MIN_PROBABILITY = 1e-6


def american_to_decimal(american: float) -> float:
    """-150 -> 1.667, +130 -> 2.30."""
    american = float(american)
    if american == 0:
        raise ValueError("American odds of 0 are not a price")
    if american > 0:
        return 1.0 + american / 100.0
    return 1.0 + 100.0 / abs(american)


def decimal_to_american(decimal: float) -> float:
    """1.667 -> -150, 2.30 -> +130."""
    decimal = float(decimal)
    if decimal <= 1.0:
        raise ValueError(f"decimal odds must exceed 1.0, got {decimal}")
    if decimal >= 2.0:
        return round((decimal - 1.0) * 100.0)
    return round(-100.0 / (decimal - 1.0))


def probability_to_decimal(probability: float) -> float:
    """The fair price: 1 / p. No margin added."""
    probability = float(probability)
    if not MIN_PROBABILITY < probability < 1.0:
        raise ValueError(f"probability must be in (0, 1), got {probability}")
    return 1.0 / probability


def probability_to_american(probability: float) -> float:
    """The fair American price — what a book with no margin would post."""
    return decimal_to_american(probability_to_decimal(probability))


def decimal_to_probability(decimal: float) -> float:
    """The probability a decimal price implies, vig included."""
    if float(decimal) <= 1.0:
        raise ValueError(f"decimal odds must exceed 1.0, got {decimal}")
    return 1.0 / float(decimal)


def american_to_probability(american: float) -> float:
    """The probability an American price implies, vig included."""
    return decimal_to_probability(american_to_decimal(american))


def remove_vig(implied: list[float] | np.ndarray) -> np.ndarray:
    """Strip the book's margin from a complete set of prices on one market.

    Pass every outcome of the market (both sides of a spread, all three of a
    1X2). They will sum to more than 1; this scales them back proportionally.

    The proportional method is the simple one and it slightly over-taxes
    longshots — a book's margin is not spread evenly across outcomes. It is
    still far closer to the truth than not de-vigging at all, which is the
    mistake worth avoiding.
    """
    values = np.asarray(implied, dtype=float)
    if values.size < 2:
        raise ValueError("de-vigging needs every outcome of the market, not one side")
    if (values <= 0).any():
        raise ValueError("implied probabilities must be positive")
    total = values.sum()
    if total <= 0:
        raise ValueError("implied probabilities sum to zero")
    return values / total


def overround(implied: list[float] | np.ndarray) -> float:
    """The book's margin on a market, as a fraction. 0.045 is a 4.5% hold."""
    return float(np.sum(np.asarray(implied, dtype=float)) - 1.0)


def expected_value(
    probability: float,
    decimal_odds: float,
    stake: float = 100.0,
    push_probability: float = 0.0,
) -> float:
    """Expected profit on `stake` at `decimal_odds`, given your probability.

    Win: you keep (decimal - 1) x stake. Lose: you lose the stake. Push: the
    stake comes back and nothing happens.

    `push_probability` matters more than it looks. A -3 NFL spread pushes about
    15% of the time, and treating those as losses understates the bet badly.
    `probability` is P(this side wins outright), so the three outcomes are
    win / push / lose and the loss probability is whatever is left.
    """
    probability = float(probability)
    push = float(push_probability)
    if not 0.0 <= probability <= 1.0:
        raise ValueError(f"probability must be in [0, 1], got {probability}")
    if not 0.0 <= push <= 1.0:
        raise ValueError(f"push probability must be in [0, 1], got {push}")
    if probability + push > 1.0 + 1e-9:
        raise ValueError(
            f"win ({probability}) + push ({push}) probability exceeds 1"
        )
    if float(decimal_odds) <= 1.0:
        raise ValueError(f"decimal odds must exceed 1.0, got {decimal_odds}")

    lose = 1.0 - probability - push
    profit = (float(decimal_odds) - 1.0) * stake
    return probability * profit - lose * stake


def expected_value_pct(
    probability: float, decimal_odds: float, push_probability: float = 0.0
) -> float:
    """EV as a fraction of stake. 0.04 means +4% per unit risked."""
    return expected_value(probability, decimal_odds, 1.0, push_probability)


def no_push_probability(probability: float, push_probability: float = 0.0) -> float:
    """P(win | the bet resolves) — the number to compare against a book's price.

    A book's -110 on a whole-number spread prices the *non-push* outcomes,
    because a push returns the stake. Comparing a raw win probability against
    that implied number compares two different things.
    """
    live = 1.0 - float(push_probability)
    if live <= MIN_PROBABILITY:
        raise ValueError("this market pushes essentially always; there is nothing to price")
    return float(probability) / live


def kelly_fraction(
    probability: float,
    decimal_odds: float,
    cap: float = 1.0,
    push_probability: float = 0.0,
) -> float:
    """The Kelly stake, as a fraction of bankroll. Zero when there is no edge.

    Full Kelly is famously aggressive and assumes your probability is exactly
    right, which it never is. `cap` expresses a fractional Kelly (cap=0.25 for
    quarter Kelly). The UI reports full Kelly and says plainly that it is an
    upper bound on what a bankroll can justify, not a recommendation.
    """
    b = float(decimal_odds) - 1.0
    if b <= 0:
        raise ValueError(f"decimal odds must exceed 1.0, got {decimal_odds}")
    p, push = float(probability), float(push_probability)
    lose = 1.0 - p - push
    edge = p * b - lose
    if edge <= 0:
        return 0.0
    return float(min(edge / b, cap))


def format_american(american: float) -> str:
    """+130 / -150, with the sign a book would show."""
    value = int(round(american))
    return f"+{value}" if value > 0 else str(value)


@dataclass(frozen=True)
class PriceComparison:
    """One side of one market: what the model thinks vs what the book pays."""

    model_probability: float
    book_decimal: float
    book_implied: float
    fair_decimal: float
    fair_american: float
    edge: float               # model probability minus the book's implied
    ev_per_100: float
    ev_pct: float
    kelly: float
    push_probability: float = 0.0
    no_vig_probability: float | None = None
    no_vig_edge: float | None = None

    @property
    def is_positive(self) -> bool:
        return self.ev_per_100 > 0

    def summary(self) -> dict:
        out = {
            "model_probability": round(self.model_probability, 4),
            "push_probability": round(self.push_probability, 4),
            "book_decimal": round(self.book_decimal, 4),
            "book_american": format_american(decimal_to_american(self.book_decimal)),
            "book_implied": round(self.book_implied, 4),
            "fair_decimal": round(self.fair_decimal, 4),
            "fair_american": format_american(self.fair_american),
            "edge": round(self.edge, 4),
            "ev_per_100": round(self.ev_per_100, 2),
            "ev_pct": round(self.ev_pct, 4),
            "kelly": round(self.kelly, 4),
        }
        if self.no_vig_probability is not None:
            out["no_vig_probability"] = round(self.no_vig_probability, 4)
            out["no_vig_edge"] = round(self.no_vig_edge or 0.0, 4)
        return out


def compare(
    model_probability: float,
    book_odds: float,
    *,
    american: bool = True,
    opposing_odds: float | None = None,
    push_probability: float = 0.0,
) -> PriceComparison:
    """Compare one model probability against one posted price.

    `opposing_odds` is the price on the other side of the same market. Supply it
    and the comparison also reports the de-vigged number, which is the honest
    one: it is what the book actually believes, with its margin removed.
    """
    p = float(model_probability)
    if not MIN_PROBABILITY < p < 1.0:
        raise ValueError(f"model probability must be in (0, 1), got {p}")

    decimal = american_to_decimal(book_odds) if american else float(book_odds)
    implied = decimal_to_probability(decimal)
    # The book prices the outcomes that can actually settle, so the comparison
    # has to be against P(win | not a push).
    comparable = no_push_probability(p, push_probability)

    no_vig = no_vig_edge = None
    if opposing_odds is not None:
        other = american_to_decimal(opposing_odds) if american else float(opposing_odds)
        pair = remove_vig([implied, decimal_to_probability(other)])
        no_vig = float(pair[0])
        no_vig_edge = comparable - no_vig

    return PriceComparison(
        model_probability=p,
        book_decimal=decimal,
        book_implied=implied,
        fair_decimal=probability_to_decimal(comparable),
        fair_american=probability_to_american(comparable),
        edge=comparable - implied,
        ev_per_100=expected_value(p, decimal, 100.0, push_probability),
        ev_pct=expected_value_pct(p, decimal, push_probability),
        kelly=kelly_fraction(p, decimal, push_probability=push_probability),
        push_probability=float(push_probability),
        no_vig_probability=no_vig,
        no_vig_edge=no_vig_edge,
    )
