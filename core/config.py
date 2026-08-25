"""Project-wide paths and per-sport configuration.

Sport is a top-level config, not a fork in the code: `SPORTS` is the single
registry that both the CLI entrypoints and the pipeline layer read from.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Override with MLEV_DATA_DIR to keep large backfills outside the repo.
DATA_ROOT = Path(os.environ.get("MLEV_DATA_DIR", REPO_ROOT / "data"))

# Layers every sport writes, in pipeline order.
LAYERS = ("raw", "clean", "features", "models", "predictions")


@dataclass(frozen=True)
class SportConfig:
    """Everything that differs between sports but not between runs."""

    key: str
    label: str
    # Seasons available for backfill. For NFL these are calendar years
    # (2016 == the 2016-17 season); for EPL the year the season started
    # (2016 == 2016/17), which is also how football-data.co.uk codes them.
    first_season: int
    last_season: int
    # Walk-forward: the earliest season we are willing to *test* on. Everything
    # before it is burn-in for the rolling features, which are undefined for a
    # team's first few games in the dataset.
    first_test_season: int
    # Minimum prior games before a rolling feature is considered trustworthy.
    min_prior_games: int
    # The season currently being played / about to start. Its fixtures exist but
    # its results do not, so it is the season the scoring job predicts. Raw
    # sources that only publish completed data are backfilled through
    # `last_season`; only the schedule/fixture pull reaches into this one.
    upcoming_season: int | None = None
    # Human-readable note surfaced in README and --help.
    sources: tuple[str, ...] = field(default_factory=tuple)

    @property
    def seasons(self) -> list[int]:
        """Seasons with complete, modellable history — the training universe."""
        return list(range(self.first_season, self.last_season + 1))

    @property
    def all_seasons(self) -> list[int]:
        """Training seasons plus the in-progress one, where there is one."""
        if self.upcoming_season is None:
            return self.seasons
        return [*self.seasons, self.upcoming_season]

    def path(self, layer: str, filename: str | None = None) -> Path:
        if layer not in LAYERS:
            raise ValueError(f"unknown layer {layer!r}, expected one of {LAYERS}")
        directory = DATA_ROOT / self.key / layer
        return directory / filename if filename else directory


NFL = SportConfig(
    key="nfl",
    label="NFL",
    # 2016 is the first season with the full nflverse participation/snap data
    # we lean on; ten seasons of history through the most recent completed one.
    first_season=2016,
    last_season=2025,
    first_test_season=2019,
    min_prior_games=4,
    # The 2026 schedule is published well before Week 1, so the weekly scoring
    # job has fixtures to predict before the season starts.
    upcoming_season=2026,
    sources=(
        "nflverse (schedules, play-by-play, weekly player stats, snap counts, injuries)",
    ),
)

EPL = SportConfig(
    key="epl",
    label="Premier League",
    first_season=2014,
    last_season=2025,
    first_test_season=2017,
    min_prior_games=5,
    # 2026/27 is underway; football-data.co.uk publishes it incrementally as
    # matches are played, so it is both partially ingested and actively scored.
    upcoming_season=2026,
    sources=(
        "football-data.co.uk (results, shots, cards, corners)",
        "Understat (team + player xG) — primary underlying-performance source",
    ),
)

SPORTS: dict[str, SportConfig] = {NFL.key: NFL, EPL.key: EPL}


def get_sport(key: str) -> SportConfig:
    try:
        return SPORTS[key.lower()]
    except KeyError:
        raise ValueError(
            f"unknown sport {key!r}; available: {', '.join(sorted(SPORTS))}"
        ) from None


def ensure_layers(sport: SportConfig) -> None:
    """Create the data directories for a sport if they are missing."""
    for layer in LAYERS:
        sport.path(layer).mkdir(parents=True, exist_ok=True)
