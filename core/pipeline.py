"""The shared pipeline interface: ingest -> clean -> feature -> model -> evaluate.

The spec asks for NFL and EPL to be "modular and swappable, sharing a common
pipeline interface, rather than two unrelated codebases". This is that
interface. `run_backfill.py`, `run_backtest.py` and `run_scoring.py` talk only
to `SportPipeline`; adding a third sport means adding a `sports/<key>/` package
and one registry entry, not touching the entrypoints.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path

import pandas as pd

from core.backtest import MarketModel, WalkForwardResult, walk_forward
from core.markets import FixtureMarkets
from core.config import SportConfig, ensure_layers
from core.errors import MissingDataError

log = logging.getLogger(__name__)


class SportPipeline(ABC):
    """One sport's implementation of the five pipeline stages."""

    config: SportConfig

    def __init__(self, config: SportConfig) -> None:
        self.config = config
        ensure_layers(config)

    # --- stage 1: ingest ----------------------------------------------------

    @abstractmethod
    def ingest(self, seasons: list[int], *, force: bool = False) -> dict[str, Path]:
        """Pull raw data from source into data/<sport>/raw/. Fails loudly."""

    # --- stage 2: clean -----------------------------------------------------

    @abstractmethod
    def clean(self) -> dict[str, Path]:
        """Normalize names, join sources, write data/<sport>/clean/."""

    # --- stage 3: features --------------------------------------------------

    @abstractmethod
    def build_game_features(self) -> pd.DataFrame:
        """Point-in-time game/match-level feature table."""

    @abstractmethod
    def build_player_features(self) -> pd.DataFrame:
        """Point-in-time player-level feature table for props."""

    # --- stage 4: models ----------------------------------------------------

    @abstractmethod
    def game_model(self) -> MarketModel:
        """A fresh, unfitted model bundle for the game-line markets."""

    @abstractmethod
    def player_model(self) -> MarketModel:
        """A fresh, unfitted model bundle for the player-prop markets."""

    # --- stage 5: evaluate + score -----------------------------------------

    def backtest(self, level: str = "game", **kwargs) -> WalkForwardResult:
        """Walk-forward evaluation of one level's markets."""
        features, factory = self._level(level)
        return walk_forward(
            features,
            factory,
            first_test_season=kwargs.pop("first_test_season", self.config.first_test_season),
            **kwargs,
        )

    def _level(self, level: str) -> tuple[pd.DataFrame, Callable[[], MarketModel]]:
        if level == "game":
            return self.build_game_features(), self.game_model
        if level == "player":
            return self.build_player_features(), self.player_model
        raise ValueError(f"level must be 'game' or 'player', got {level!r}")

    def train_and_score(
        self, level: str, *, upcoming: pd.DataFrame | None = None
    ) -> pd.DataFrame:
        """Fit on every completed row, then score the rows still to be played.

        This is the weekly (NFL) / matchday (EPL) job. "Upcoming" is defined
        as feature rows whose outcome columns are still null — fixtures that
        are already in the schedule but have not been played. Their features
        come from the same point-in-time builders as the training rows, so
        nothing about scoring differs from the backtest except that the answer
        is not known yet.
        """
        features, factory = self._level(level)
        outcome_cols = self.outcome_columns(level)
        played = features.dropna(subset=outcome_cols, how="all")
        pending = upcoming if upcoming is not None else features[
            features[outcome_cols].isna().all(axis=1)
        ]
        if pending.empty:
            raise MissingDataError(
                f"no unplayed {self.config.label} {level} rows to score — the "
                "schedule may not extend past the last completed fixture yet."
            )
        model = factory()
        model.fit(played)
        preds = model.predict_frame(pending)
        log.info(
            "%s %s: trained on %s rows, scored %s upcoming",
            self.config.label, level, len(played), len(pending),
        )
        return pending.join(preds)

    @abstractmethod
    def outcome_columns(self, level: str) -> list[str]:
        """Columns holding realised results — null for unplayed fixtures."""

    @abstractmethod
    def prediction_view(self, scored: pd.DataFrame, level: str) -> pd.DataFrame:
        """Trim a scored frame to the human-readable columns worth writing out."""

    @abstractmethod
    def fixture_markets(self, scored: pd.DataFrame) -> list[FixtureMarkets]:
        """Reshape scored game-level rows into per-fixture lists of bettable sides.

        Both sides of every market, each with its probability, its push
        probability and the fair price those imply. This is what the EV
        comparison and the phone UI consume.
        """
