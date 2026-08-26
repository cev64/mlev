"""The prediction bundle — what the phone needs to work without the Mac.

The models cannot run on a phone: they need Python, pandas, scikit-learn and
about a hundred megabytes of historical data. But they do not *have* to. What a
phone actually needs is the shape of each fixture's predictive distribution, and
that is small.

So rather than exporting a fixed list of probabilities, this exports the
**parameters of the distribution itself**:

* NFL — the fitted mean and standard deviation for margin and total, plus the
  lattice shape (the key-number structure of football scoring, shared across
  fixtures). From those, a client can compute the probability of *any* spread or
  total, including lines nobody precomputed.
* EPL — the full scoreline grid. Every soccer market is a projection of it, so a
  client can derive match result, any handicap, any goal line, both-teams-to-score
  and correct score from the same object, and they cannot contradict each other.

The result is a few tens of kilobytes that turns a phone into a full client.
The Mac (or CI) still does the modelling; the phone does the arithmetic.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from core.config import SportConfig
from core.errors import MissingDataError

log = logging.getLogger(__name__)

# Bump when the shape changes in a way an older client cannot read. The Android
# app refuses a bundle whose schema it does not know rather than guessing.
SCHEMA_VERSION = 1

# The scoreline grid is truncated for transport. Beyond 8 goals a side the mass
# is negligible and the client renormalises anyway.
EPL_GRID_MAX_GOALS = 8


def _round(value, digits: int = 6):
    """JSON is the transport, so keep it readable and small."""
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return None
    return round(float(value), digits)


@dataclass
class BundleMeta:
    sport: str
    generated_at: str
    trained_through: str
    fixture_count: int
    notes: dict


def _backtest_summary(config: SportConfig) -> dict:
    """The headline out-of-sample numbers, carried alongside the predictions.

    A probability without the evidence behind it invites more confidence than it
    deserves, so the app shows these next to the markets rather than making the
    user go and look them up.
    """
    path = config.path("models", "backtest_game_overall.csv")
    if not path.exists():
        return {}
    frame = pd.read_csv(path)
    out = {}
    for _, row in frame.iterrows():
        entry = {}
        for key in ("n", "brier", "baseline_brier", "log_loss", "accuracy", "ece", "mae"):
            if key in row and pd.notna(row[key]):
                entry[key] = _round(row[key], 5)
        if entry:
            out[str(row["target"])] = entry
    return out


def build_nfl_bundle(pipeline, scored: pd.DataFrame) -> dict:
    """NFL: distribution parameters plus the shared lattice shapes."""
    model = pipeline.game_model()
    features = pipeline.build_game_features()
    model.fit(features.dropna(subset=["home_margin", "total_points"]))

    def lattice(shape) -> dict:
        return {
            "values": [int(v) for v in shape.values],
            "bump": [_round(b, 4) for b in shape.bump],
        }

    fixtures = []
    for _, row in scored.iterrows():
        if pd.isna(row.get("home_margin_mean")):
            continue
        fixtures.append(
            {
                "id": str(row.get("game_id", "")),
                "home": str(row.get("home_team", "")),
                "away": str(row.get("away_team", "")),
                "kickoff": str(row.get("kickoff", ""))[:10],
                "season": int(row["season"]) if pd.notna(row.get("season")) else None,
                "week": int(row["week"]) if pd.notna(row.get("week")) else None,
                # Everything the client needs to build the two distributions.
                "margin": {
                    "mean": _round(row["home_margin_mean"], 4),
                    "sd": _round(row["home_margin_sd"], 4),
                },
                "total": {
                    "mean": _round(row["total_points_mean"], 4),
                    "sd": _round(row["total_points_sd"], 4),
                },
            }
        )

    return {
        "kind": "nfl",
        "lattice": {
            "margin": lattice(model.margin_shape_) if model.margin_shape_ else None,
            "total": lattice(model.total_shape_) if model.total_shape_ else None,
        },
        "fixtures": fixtures,
    }


def build_epl_bundle(pipeline, scored: pd.DataFrame) -> dict:
    """EPL: the scoreline grid every market is derived from."""
    from sports.epl.models import DixonColesMarketModel

    features = pipeline.build_game_features()
    model = DixonColesMarketModel()
    model.fit(features.dropna(subset=["home_goals"]))

    size = EPL_GRID_MAX_GOALS + 1
    fixtures = []
    for _, row in scored.iterrows():
        home, away = row.get("home_team"), row.get("away_team")
        if not isinstance(home, str) or not isinstance(away, str):
            continue
        grid = model.model.scoreline(home, away).grid[:size, :size]
        grid = grid / grid.sum()
        fixtures.append(
            {
                "id": str(row.get("match_id", "")),
                "home": home,
                "away": away,
                "kickoff": str(row.get("kickoff", ""))[:10],
                "season": int(row["season"]) if pd.notna(row.get("season")) else None,
                # Row-major, home goals by away goals. Rounded hard: a cell below
                # 1e-6 changes no market anyone bets.
                "grid": [[_round(cell, 7) for cell in line] for line in grid],
                "replacement_rating": bool(row.get("uses_replacement_rating", 0)),
            }
        )

    return {
        "kind": "epl",
        "grid_max_goals": EPL_GRID_MAX_GOALS,
        "model": {
            "home_advantage": _round(model.model.home_advantage_, 4),
            "rho": _round(model.model.rho_, 4),
            "decay": _round(model.chosen_.get("decay"), 5),
            "xg_weight": _round(model.chosen_.get("xg_weight"), 3),
        },
        "fixtures": fixtures,
    }


def build_bundle(sport: str, scored: pd.DataFrame) -> dict:
    """Assemble the full bundle for one sport from a scored fixture frame."""
    from core.registry import get_pipeline

    pipeline = get_pipeline(sport)
    config = pipeline.config
    if scored.empty:
        raise MissingDataError(f"no scored {config.label} fixtures to export")

    body = (
        build_nfl_bundle(pipeline, scored)
        if sport == "nfl"
        else build_epl_bundle(pipeline, scored)
    )

    played = pipeline.build_game_features().dropna(
        subset=["home_margin"] if sport == "nfl" else ["home_goals"]
    )
    trained_through = str(played["kickoff"].max())[:10] if not played.empty else ""

    return {
        "schema": SCHEMA_VERSION,
        "sport": sport,
        "label": config.label,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "trained_through": trained_through,
        "training_rows": int(len(played)),
        "backtest": _backtest_summary(config),
        **body,
    }


def write_bundle(bundle: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle, separators=(",", ":")), encoding="utf-8")
    log.info(
        "wrote %s (%s fixtures, %.1f KB)",
        path, len(bundle.get("fixtures", [])), path.stat().st_size / 1024,
    )
    return path
