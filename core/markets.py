"""Turning a scored prediction row into a list of bettable sides.

The prediction tables are wide — forty-odd columns of means, standard
deviations and probabilities. That is the right shape for analysis and the
wrong shape for the question you actually ask before a bet, which is:

    "What does the model give this side, and what is the book paying?"

So this module reshapes one fixture into a flat list of `MarketSide` records —
one per side of every market — each carrying its probability, its push
probability, and the fair price implied by them. That list is what the phone UI
renders and what the EV comparison consumes.

Both sides are always emitted. A moneyline row gives you the home side *and*
the away side, because you might be betting either.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from core.odds import (
    format_american,
    no_push_probability,
    probability_to_american,
    probability_to_decimal,
)

# Below this the fair price is astronomic and the market is not real.
MIN_TRADEABLE = 0.001


@dataclass
class MarketSide:
    """One bettable side of one market, with the model's price for it."""

    group: str           # "Moneyline", "Spread", "Total" — how the UI groups them
    market: str          # "Moneyline", "Spread -3", "Over/Under 47.5"
    side: str            # "SEA", "Over", "Draw"
    probability: float   # P(this side wins outright)
    push_probability: float = 0.0
    note: str = ""

    @property
    def settles_probability(self) -> float:
        """P(win | the bet resolves) — the number comparable to a book's price."""
        return no_push_probability(self.probability, self.push_probability)

    @property
    def fair_decimal(self) -> float:
        return probability_to_decimal(self.settles_probability)

    @property
    def fair_american(self) -> float:
        return probability_to_american(self.settles_probability)

    def to_dict(self) -> dict:
        return {
            "group": self.group,
            "market": self.market,
            "side": self.side,
            "probability": round(self.probability, 4),
            "push_probability": round(self.push_probability, 4),
            "settles_probability": round(self.settles_probability, 4),
            "fair_decimal": round(self.fair_decimal, 3),
            "fair_american": format_american(self.fair_american),
            "note": self.note,
        }


@dataclass
class FixtureMarkets:
    """Every market for one fixture, plus enough identity to label it."""

    fixture_id: str
    label: str                       # "SEA vs NE"
    kickoff: str
    sides: list[MarketSide] = field(default_factory=list)
    context: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "fixture_id": self.fixture_id,
            "label": self.label,
            "kickoff": self.kickoff,
            "context": self.context,
            "sides": [s.to_dict() for s in self.sides if _tradeable(s)],
        }


def _tradeable(side: MarketSide) -> bool:
    """Drop sides too extreme to price, and anything non-finite."""
    p = side.probability
    if not math.isfinite(p) or not math.isfinite(side.push_probability):
        return False
    live = 1.0 - side.push_probability
    if live <= MIN_TRADEABLE:
        return False
    return MIN_TRADEABLE < p / live < 1.0 - MIN_TRADEABLE


def complement(
    probability: float, push_probability: float = 0.0
) -> float:
    """The other side's probability: whatever is left after this side and a push."""
    return max(0.0, 1.0 - probability - push_probability)


def parse_line_key(key: str) -> float:
    """Turn a column suffix back into the number it encodes.

    `m3` -> -3.0, `p47_5` -> 47.5. The encoding exists because a column name
    cannot contain a minus sign or a decimal point.
    """
    sign = -1.0 if key.startswith("m") else 1.0
    body = key[1:] if key[0] in "mp" else key
    return sign * float(body.replace("_", "."))


def format_line(value: float) -> str:
    """-3.0 -> '-3', 47.5 -> '47.5' — how a book would write it."""
    text = f"{value:g}"
    return text.replace("-", "−") if value < 0 else text
