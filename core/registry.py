"""Maps a sport key to its pipeline implementation.

Imports are lazy so that a missing optional dependency in one sport's module
cannot stop the other sport's job from running.
"""

from __future__ import annotations

from core.config import get_sport
from core.pipeline import SportPipeline

SPORT_KEYS = ("nfl", "epl")


def get_pipeline(key: str) -> SportPipeline:
    config = get_sport(key)
    if config.key == "nfl":
        from sports.nfl.pipeline import NFLPipeline

        return NFLPipeline(config)
    if config.key == "epl":
        from sports.epl.pipeline import EPLPipeline

        return EPLPipeline(config)
    raise ValueError(f"no pipeline registered for {key!r}")
