"""The NFL implementation of `SportPipeline`."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from core.backtest import MarketModel, TabularBundle
from core.config import SportConfig
from core.features import assert_no_lookahead
from core.io import write_table
from core.pipeline import SportPipeline
from sports.nfl import clean as nfl_clean
from sports.nfl import features as nfl_features
from sports.nfl import ingest as nfl_ingest
from sports.nfl import models as nfl_models

log = logging.getLogger(__name__)

GAME_OUTCOMES = ["home_win", "home_margin", "total_points"]
PLAYER_OUTCOMES = [
    "passing_yards", "passing_tds", "rushing_yards", "receiving_yards",
    "receptions", "scrimmage_yards", "scrimmage_tds", "anytime_td",
]


class NFLPipeline(SportPipeline):
    """nflverse -> clean -> point-in-time features -> game lines and props."""

    def __init__(self, config: SportConfig) -> None:
        super().__init__(config)
        self._cache: dict[str, pd.DataFrame] = {}

    # --- stages -------------------------------------------------------------

    def ingest(self, seasons: list[int], *, force: bool = False) -> dict[str, Path]:
        return nfl_ingest.backfill(self.config, seasons, force=force)

    def clean(self) -> dict[str, Path]:
        nfl_clean.run(self.config)
        self._cache.clear()
        return {
            name: self.config.path("clean", f"{name}.parquet")
            for name in ("games", "team_games", "player_games")
        }

    def build_game_features(self) -> pd.DataFrame:
        if "game" not in self._cache:
            features = nfl_features.build_game_features(self.config)
            cols = nfl_features.game_feature_columns(features)
            # Tripwire, run every time the table is built rather than only in
            # the tests — a leaked column should never reach a fitted model.
            assert_no_lookahead(
                features,
                feature_cols=cols,
                outcome_cols=[*GAME_OUTCOMES, "home_score", "away_score"],
            )
            write_table(features, self.config.path("features", "game_features.parquet"))
            self._cache["game"] = features
        return self._cache["game"]

    def build_player_features(self) -> pd.DataFrame:
        if "player" not in self._cache:
            features = nfl_features.build_player_features(self.config)
            cols = nfl_features.player_feature_columns(features)
            assert_no_lookahead(
                features, feature_cols=cols, outcome_cols=PLAYER_OUTCOMES
            )
            write_table(features, self.config.path("features", "player_features.parquet"))
            self._cache["player"] = features
        return self._cache["player"]

    # --- models -------------------------------------------------------------

    def game_model(self) -> MarketModel:
        features = self.build_game_features()
        return TabularBundle(
            specs=nfl_models.game_targets(),
            feature_cols=nfl_features.game_feature_columns(features),
        )

    def player_model(self) -> MarketModel:
        features = self.build_player_features()
        return TabularBundle(
            specs=nfl_models.player_targets(),
            feature_cols=nfl_features.player_feature_columns(features),
        )

    # --- outputs ------------------------------------------------------------

    def outcome_columns(self, level: str) -> list[str]:
        return GAME_OUTCOMES if level == "game" else PLAYER_OUTCOMES

    def prediction_view(self, scored: pd.DataFrame, level: str) -> pd.DataFrame:
        if level == "game":
            identity = [
                "game_id", "season", "week", "kickoff", "away_team", "home_team",
            ]
        else:
            identity = [
                "game_id", "season", "week", "kickoff", "player_display_name",
                "position", "team", "opponent",
            ]
        prediction = [
            c for c in scored.columns
            if c.endswith(("_prob", "_mean", "_sd", "_p10", "_p90")) or "_p_over_" in c
        ]
        cols = [c for c in [*identity, *prediction] if c in scored.columns]
        out = scored[cols].copy()
        numeric = out.select_dtypes("number").columns
        out[numeric] = out[numeric].round(4)
        sort_key = [c for c in ("kickoff", "game_id") if c in out.columns]
        return out.sort_values(sort_key) if sort_key else out
