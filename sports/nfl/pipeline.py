"""The NFL implementation of `SportPipeline`."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from core.backtest import MarketModel, TabularBundle
from core.config import SportConfig
from core.features import assert_no_lookahead
from core.io import write_table
from core.markets import (
    FixtureMarkets,
    MarketSide,
    complement,
    format_line,
    parse_line_key,
)
from core.pipeline import SportPipeline
from sports.nfl import clean as nfl_clean
from sports.nfl import features as nfl_features
from sports.nfl import ingest as nfl_ingest
from sports.nfl import models as nfl_models
from sports.nfl.models import JointGameModel

log = logging.getLogger(__name__)

GAME_OUTCOMES = ["home_win", "home_margin", "total_points"]

# Down-weight older training seasons by 0.5 ** (seasons_ago / 4). Four seasons
# is roughly how long an NFL roster, coaching staff and scheme stay recognisable,
# and the league drifts underneath a model that ignores it: passing yards per
# quarterback game fell from ~245 in 2016 to ~201 in 2025. See the README's
# "league drift" note for the sensitivity check behind this default.
RECENCY_HALFLIFE_SEASONS = 4.0
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
        """One joint model for all three game markets.

        Fitting moneyline, spread and total as three independent models let them
        contradict each other -- the old bundle quoted a 0.679 moneyline beside a
        0.662 P(margin > 0) for the same game. Here every market is read off a
        fitted margin and total distribution, so they agree by construction, and
        the lattice shape gives real push probabilities on whole-number lines
        (a Normal prices a -3 push at zero; it is really about 7%).

        `nfl_models.game_targets()` still exists and still works with
        `TabularBundle` if you want the independent-model behaviour back for a
        comparison run.
        """
        features = self.build_game_features()
        return JointGameModel(
            nfl_features.game_feature_columns(features),
            recency_halflife_seasons=RECENCY_HALFLIFE_SEASONS,
        )

    def player_model(self) -> MarketModel:
        features = self.build_player_features()
        return TabularBundle(
            specs=nfl_models.player_targets(),
            feature_cols=nfl_features.player_feature_columns(features),
            recency_halflife_seasons=RECENCY_HALFLIFE_SEASONS,
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
            if c.endswith(("_prob", "_mean", "_sd", "_p10", "_p50", "_p90"))
            or "_p_over_" in c
            or c.startswith(("home_cover_", "home_push_", "total_over_", "total_push_", "exp_"))
        ]
        cols = [c for c in [*identity, *prediction] if c in scored.columns]
        out = scored[cols].copy()
        numeric = out.select_dtypes("number").columns
        out[numeric] = out[numeric].round(4)
        sort_key = [c for c in ("kickoff", "game_id") if c in out.columns]
        return out.sort_values(sort_key) if sort_key else out

    def fixture_markets(self, scored: pd.DataFrame) -> list[FixtureMarkets]:
        """Every NFL game market, both sides, from a `JointGameModel` output.

        Because all three markets come off the same fitted margin and total
        distributions, the moneyline, every spread and every total here are
        mutually consistent — the away side is genuinely one minus the home
        side and the push, not a separately fitted number.
        """
        out: list[FixtureMarkets] = []
        for _, row in scored.iterrows():
            home, away = row.get("home_team"), row.get("away_team")
            sides: list[MarketSide] = []

            # --- moneyline ---
            if pd.notna(row.get("home_win_prob")):
                tie = float(row.get("tie_prob") or 0.0)
                home_p = float(row["home_win_prob"]) * (1.0 - tie)
                sides.append(MarketSide("Moneyline", "Moneyline", home, home_p, tie))
                sides.append(
                    MarketSide("Moneyline", "Moneyline", away, complement(home_p, tie), tie)
                )

            # --- spreads ---
            for column in scored.columns:
                if not column.startswith("home_cover_"):
                    continue
                key = column[len("home_cover_"):]
                cover = row.get(column)
                if pd.isna(cover):
                    continue
                push = float(row.get(f"home_push_{key}") or 0.0)
                line = parse_line_key(key)
                label = f"Spread {format_line(line)}"
                sides.append(
                    MarketSide("Spread", label, f"{home} {format_line(line)}",
                               float(cover), push)
                )
                sides.append(
                    MarketSide("Spread", label, f"{away} {format_line(-line)}",
                               complement(float(cover), push), push)
                )

            # --- totals ---
            for column in scored.columns:
                if not column.startswith("total_over_"):
                    continue
                key = column[len("total_over_"):]
                over = row.get(column)
                if pd.isna(over):
                    continue
                push = float(row.get(f"total_push_{key}") or 0.0)
                line = parse_line_key(key)
                label = f"Total {format_line(line)}"
                sides.append(MarketSide("Total", label, f"Over {format_line(line)}",
                                        float(over), push))
                sides.append(MarketSide("Total", label, f"Under {format_line(line)}",
                                        complement(float(over), push), push))

            context = {
                "Projected score": (
                    f"{home} {row['exp_home_score']:.1f} — {away} {row['exp_away_score']:.1f}"
                    if pd.notna(row.get("exp_home_score")) else ""
                ),
                "Margin": (
                    f"{row['home_margin_mean']:+.1f} ± {row['home_margin_sd']:.1f}"
                    if pd.notna(row.get("home_margin_mean")) else ""
                ),
                "Total": (
                    f"{row['total_points_mean']:.1f} ± {row['total_points_sd']:.1f}"
                    if pd.notna(row.get("total_points_mean")) else ""
                ),
            }
            out.append(
                FixtureMarkets(
                    fixture_id=str(row.get("game_id", "")),
                    label=f"{away} @ {home}",
                    kickoff=str(row.get("kickoff", ""))[:10],
                    sides=sides,
                    context={k: v for k, v in context.items() if v},
                )
            )
        return out
