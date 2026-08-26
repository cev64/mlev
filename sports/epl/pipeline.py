"""The EPL implementation of `SportPipeline`."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from core.backtest import MarketModel, TabularBundle
from core.config import SportConfig
from core.errors import MissingDataError
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
from sports.epl import clean as epl_clean
from sports.epl import features as epl_features
from sports.epl import ingest as epl_ingest
from sports.epl import models as epl_models

log = logging.getLogger(__name__)

GAME_OUTCOMES = ["home_goals", "away_goals", "total_goals", "goal_difference"]
PLAYER_OUTCOMES = ["goals", "assists", "shots", "xg", "carded", "scored"]

# The Dixon-Coles game model carries its own per-match exponential decay, so
# only the player bundle needs season weighting here.
RECENCY_HALFLIFE_SEASONS = 4.0


class EPLPipeline(SportPipeline):
    """football-data + Understat -> Dixon-Coles game lines and player props."""

    def __init__(self, config: SportConfig) -> None:
        super().__init__(config)
        self._cache: dict[str, pd.DataFrame] = {}

    # --- stages -------------------------------------------------------------

    def ingest(
        self,
        seasons: list[int],
        *,
        force: bool = False,
        with_players: bool = False,
        player_seasons: list[int] | None = None,
    ) -> dict[str, Path]:
        return epl_ingest.backfill(
            self.config,
            seasons,
            force=force,
            with_players=with_players,
            player_seasons=player_seasons,
        )

    def clean(self) -> dict[str, Path]:
        produced = epl_clean.run(self.config)
        self._cache.clear()
        return {
            name: self.config.path("clean", f"{name}.parquet") for name in produced
        }

    def build_game_features(self) -> pd.DataFrame:
        if "game" not in self._cache:
            features = epl_features.build_game_features(self.config)
            assert_no_lookahead(
                features,
                feature_cols=epl_features.game_feature_columns(features),
                outcome_cols=GAME_OUTCOMES,
            )
            write_table(features, self.config.path("features", "game_features.parquet"))
            self._cache["game"] = features
        return self._cache["game"]

    def build_player_features(self) -> pd.DataFrame:
        if "player" not in self._cache:
            if not self.config.path("clean", "player_matches.parquet").exists():
                raise MissingDataError(
                    "EPL player props need per-match player data, which is not "
                    "backfilled by default (it costs one Understat request per "
                    "match). Run:\n"
                    "  python run_backfill.py --sport epl --with-players "
                    "--player-seasons 2022 2023 2024 2025 2026"
                )
            features = epl_features.build_player_features(self.config)
            assert_no_lookahead(
                features,
                feature_cols=epl_features.player_feature_columns(features),
                outcome_cols=PLAYER_OUTCOMES,
            )
            write_table(features, self.config.path("features", "player_features.parquet"))
            self._cache["player"] = features
        return self._cache["player"]

    # --- models -------------------------------------------------------------

    def game_model(self) -> MarketModel:
        return epl_models.DixonColesMarketModel()

    def player_model(self) -> MarketModel:
        features = self.build_player_features()
        return TabularBundle(
            specs=epl_models.player_targets(),
            feature_cols=epl_features.player_feature_columns(features),
            recency_halflife_seasons=RECENCY_HALFLIFE_SEASONS,
        )

    # --- outputs ------------------------------------------------------------

    def outcome_columns(self, level: str) -> list[str]:
        return GAME_OUTCOMES if level == "game" else PLAYER_OUTCOMES

    def prediction_view(self, scored: pd.DataFrame, level: str) -> pd.DataFrame:
        if level == "game":
            identity = ["match_id", "season", "kickoff", "home_team", "away_team"]
            prediction = [
                c for c in scored.columns
                if c.startswith(("p_", "exp_")) or c in
                ("supremacy_sd", "likely_score", "likely_score_prob", "uses_replacement_rating")
            ]
        else:
            identity = [
                "match_id", "season", "kickoff", "player_raw", "team", "opponent", "position",
            ]
            prediction = [
                c for c in scored.columns
                if c.endswith(("_prob", "_mean", "_sd", "_p10", "_p90")) or "_p_over_" in c
            ]
        cols = [c for c in [*identity, *prediction] if c in scored.columns]
        out = scored[cols].copy()
        numeric = out.select_dtypes("number").columns
        out[numeric] = out[numeric].round(4)
        sort_key = [c for c in ("kickoff", "match_id") if c in out.columns]
        return out.sort_values(sort_key) if sort_key else out

    def upcoming_fixtures(self) -> pd.DataFrame:
        """Scheduled-but-unplayed Premier League matches to score.

        Unlike the NFL, football-data publishes results only as matches are
        played, so upcoming fixtures come from a separate rolling feed. Between
        matchweeks that feed can legitimately be empty.
        """
        fixtures = epl_ingest.fetch_fixtures()
        if fixtures.empty:
            raise MissingDataError(
                "football-data's fixture feed currently lists no Premier League "
                "matches. It only covers the next few days, so this is expected "
                "mid-week between matchdays — try again closer to the weekend, "
                "or pass --fixtures with your own CSV of HomeTeam/AwayTeam/Date."
            )
        return fixtures

    def fixture_markets(self, scored: pd.DataFrame) -> list[FixtureMarkets]:
        """Every EPL match market, both sides, from the Dixon-Coles output.

        All of these are read off one scoreline distribution, so the match
        result, the handicaps, the totals and both-teams-to-score cannot
        disagree with each other.
        """
        out: list[FixtureMarkets] = []
        for _, row in scored.iterrows():
            home, away = row.get("home_team"), row.get("away_team")
            sides: list[MarketSide] = []

            # --- match result ---
            if pd.notna(row.get("p_home")):
                for label, column in ((home, "p_home"), ("Draw", "p_draw"), (away, "p_away")):
                    sides.append(
                        MarketSide("Match result", "Match result", label, float(row[column]))
                    )
                # Double chance, since it is derived for free and people bet it.
                sides.append(MarketSide("Double chance", "Double chance",
                                        f"{home} or Draw",
                                        float(row["p_home"]) + float(row["p_draw"])))
                sides.append(MarketSide("Double chance", "Double chance",
                                        f"{away} or Draw",
                                        float(row["p_away"]) + float(row["p_draw"])))
                sides.append(MarketSide("Double chance", "Double chance",
                                        f"{home} or {away}",
                                        float(row["p_home"]) + float(row["p_away"])))

            # --- asian handicap ---
            for column in scored.columns:
                if not column.startswith("p_ah_home_"):
                    continue
                key = column[len("p_ah_home_"):]
                cover = row.get(column)
                if pd.isna(cover):
                    continue
                push = float(row.get(f"p_ah_push_{key}") or 0.0)
                line = parse_line_key(key)
                label = f"Handicap {format_line(line)}"
                sides.append(MarketSide("Handicap", label,
                                        f"{home} {format_line(line)}", float(cover), push))
                sides.append(MarketSide("Handicap", label,
                                        f"{away} {format_line(-line)}",
                                        complement(float(cover), push), push))

            # --- totals ---
            for column in scored.columns:
                if not column.startswith("p_over_"):
                    continue
                over = row.get(column)
                if pd.isna(over):
                    continue
                line = parse_line_key("p" + column[len("p_over_"):])
                label = f"Goals {format_line(line)}"
                sides.append(MarketSide("Total goals", label,
                                        f"Over {format_line(line)}", float(over)))
                sides.append(MarketSide("Total goals", label,
                                        f"Under {format_line(line)}", complement(float(over))))

            # --- both teams to score ---
            if pd.notna(row.get("p_btts")):
                btts = float(row["p_btts"])
                sides.append(MarketSide("Both to score", "Both teams to score", "Yes", btts))
                sides.append(MarketSide("Both to score", "Both teams to score", "No",
                                        complement(btts)))

            context = {
                "Expected goals": (
                    f"{home} {row['exp_home_goals']:.2f} — {away} {row['exp_away_goals']:.2f}"
                    if pd.notna(row.get("exp_home_goals")) else ""
                ),
                "Most likely score": (
                    f"{row['likely_score']} ({float(row['likely_score_prob']) * 100:.1f}%)"
                    if pd.notna(row.get("likely_score")) else ""
                ),
            }
            if int(row.get("uses_replacement_rating") or 0):
                context["Caution"] = (
                    "One club has no rating history (newly promoted) — "
                    "predicted from a replacement-level prior"
                )
            out.append(
                FixtureMarkets(
                    fixture_id=str(row.get("match_id", "")),
                    label=f"{home} vs {away}",
                    kickoff=str(row.get("kickoff", ""))[:10],
                    sides=sides,
                    context={k: v for k, v in context.items() if v},
                )
            )
        return out
