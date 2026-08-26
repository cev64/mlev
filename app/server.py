"""Local web UI for the mlev prediction pipeline.

Runs on 127.0.0.1 only. Everything it does is something you could do from the
command line — it just does not make you remember the flags, and it shows the
backtest evidence next to the predictions so you can see whether a number is
worth anything before you act on it.
"""

from __future__ import annotations

import logging
import math
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from flask import Flask, jsonify, request, send_from_directory

from app.jobs import RUNNER
from core.config import SPORTS, get_sport
from core.errors import MlevError
from core.registry import get_pipeline

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
app = Flask(__name__, static_folder=None)


def _clean(value):
    """JSON cannot hold NaN or Timestamp; convert rather than emit invalid JSON."""
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.strftime("%Y-%m-%d")
    if hasattr(value, "item"):
        try:
            return _clean(value.item())
        except (ValueError, AttributeError):
            return str(value)
    return value


def frame_to_json(df: pd.DataFrame, limit: int | None = None) -> dict:
    if df is None or df.empty:
        return {"columns": [], "rows": []}
    view = df.head(limit) if limit else df
    return {
        "columns": [str(c) for c in view.columns],
        "rows": [[_clean(v) for v in row] for row in view.itertuples(index=False)],
    }


# --- pages ------------------------------------------------------------------


@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/static/<path:filename>")
def static_files(filename: str):
    return send_from_directory(STATIC_DIR, filename)


# --- status -----------------------------------------------------------------


def _layer_status(config, layer: str, names: list[str]) -> list[dict]:
    out = []
    for name in names:
        path = config.path(layer, f"{name}.parquet")
        exists = path.exists()
        out.append(
            {
                "name": name,
                "exists": exists,
                "rows": _row_count(path) if exists else 0,
                "updated": (
                    datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                    if exists
                    else None
                ),
            }
        )
    return out


def _row_count(path: Path) -> int:
    try:
        import pyarrow.parquet as pq

        return pq.ParquetFile(path).metadata.num_rows
    except Exception:
        try:
            return len(pd.read_parquet(path))
        except Exception:
            return 0


RAW_FILES = {
    "nfl": ["schedules", "team_week_epa", "weekly_players", "snap_counts", "injuries", "player_ids"],
    "epl": ["results", "team_xg", "player_matches"],
}
CLEAN_FILES = {
    "nfl": ["games", "team_games", "player_games"],
    "epl": ["matches", "team_matches", "player_matches"],
}


@app.get("/api/status")
def status():
    payload = {}
    for key, config in SPORTS.items():
        raw = _layer_status(config, "raw", RAW_FILES[key])
        clean = _layer_status(config, "clean", CLEAN_FILES[key])
        features = _layer_status(config, "features", ["game_features", "player_features"])
        payload[key] = {
            "label": config.label,
            "seasons": f"{config.first_season}–{config.last_season}",
            "upcoming_season": config.upcoming_season,
            "raw": raw,
            "clean": clean,
            "features": features,
            "ready": all(f["exists"] for f in clean[:2]),
            "game_features_ready": features[0]["exists"],
            "player_features_ready": features[1]["exists"],
            "backtests": _backtest_files(config),
            "predictions": _prediction_files(config),
        }
    payload["_jobs"] = RUNNER.recent()
    return jsonify(payload)


def _backtest_files(config) -> list[dict]:
    out = []
    for level in ("game", "player"):
        path = config.path("models", f"backtest_{level}_overall.csv")
        if path.exists():
            out.append(
                {
                    "level": level,
                    "updated": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                }
            )
    return out


def _prediction_files(config) -> list[dict]:
    directory = config.path("predictions")
    if not directory.exists():
        return []
    files = sorted(directory.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        {
            "name": f.name,
            "level": "player" if f.name.startswith("player") else "game",
            "updated": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
        }
        for f in files[:20]
    ]


# --- jobs -------------------------------------------------------------------


@app.get("/api/job/<job_id>")
def job_status(job_id: str):
    job = RUNNER.get(job_id)
    if job is None:
        return jsonify({"error": "no such job"}), 404
    return jsonify(job.snapshot())


def _submit(kind: str, sport: str, label: str, target):
    try:
        job = RUNNER.submit(kind=kind, sport=sport, label=label, target=target)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 409
    return jsonify({"job_id": job.id, "label": label})


@app.post("/api/backfill")
def backfill():
    body = request.get_json(force=True, silent=True) or {}
    sport = body.get("sport", "nfl")
    with_players = bool(body.get("with_players", False))
    force = bool(body.get("force", False))
    config = get_sport(sport)

    def run(job):
        pipeline = get_pipeline(sport)
        kwargs = {"force": force}
        if sport == "epl":
            kwargs["with_players"] = with_players
            kwargs["player_seasons"] = [2022, 2023, 2024, 2025, 2026]
        job.log(f"[1/3] downloading raw data for {config.label} — this is the slow part")
        pipeline.ingest(config.seasons, **kwargs)
        job.log("[2/3] cleaning and joining sources")
        pipeline.clean()
        job.log("[3/3] building point-in-time features")
        games = pipeline.build_game_features()
        summary = {"game_feature_rows": len(games)}
        try:
            players = pipeline.build_player_features()
            summary["player_feature_rows"] = len(players)
        except MlevError as exc:
            job.log(f"player features unavailable: {exc}")
            summary["player_feature_rows"] = 0
        return summary

    label = f"Download & prepare {config.label} data"
    return _submit("backfill", sport, label, run)


@app.post("/api/backtest")
def backtest():
    body = request.get_json(force=True, silent=True) or {}
    sport = body.get("sport", "nfl")
    level = body.get("level", "game")
    config = get_sport(sport)

    def run(job):
        pipeline = get_pipeline(sport)
        kwargs = {}
        first = body.get("first_test_season")
        if first:
            kwargs["first_test_season"] = int(first)
        elif sport == "epl" and level == "player":
            kwargs["first_test_season"] = 2023
        elif sport == "nfl" and level == "player":
            kwargs["first_test_season"] = 2022
        job.log("walk-forward: train on prior seasons, predict the next, roll on")
        result = pipeline.backtest(level, **kwargs)
        stem = f"backtest_{level}"
        result.overall.to_csv(config.path("models", f"{stem}_overall.csv"), index=False)
        result.by_season.to_csv(config.path("models", f"{stem}_by_season.csv"), index=False)
        if not result.calibration.empty:
            result.calibration.to_csv(config.path("models", f"{stem}_calibration.csv"), index=False)
        job.log(f"scored {len(result.predictions)} out-of-sample rows")
        return {
            "overall": frame_to_json(result.overall),
            "by_season": frame_to_json(result.by_season),
            "calibration": frame_to_json(result.calibration),
        }

    return _submit("backtest", sport, f"Backtest {config.label} {level} models", run)


@app.post("/api/score")
def score():
    body = request.get_json(force=True, silent=True) or {}
    sport = body.get("sport", "nfl")
    level = body.get("level", "game")
    config = get_sport(sport)

    def run(job):
        pipeline = get_pipeline(sport)
        outcome_cols = pipeline.outcome_columns(level)
        features = (
            pipeline.build_game_features() if level == "game" else pipeline.build_player_features()
        )

        if sport == "epl" and level == "game":
            upcoming = _epl_upcoming(pipeline, features, body, job)
        else:
            upcoming = features[features[outcome_cols].isna().all(axis=1)].copy()
            season = body.get("season")
            week = body.get("week")
            if season:
                upcoming = upcoming[upcoming["season"] == int(season)]
            if week and "week" in upcoming.columns:
                upcoming = upcoming[upcoming["week"] == int(week)]
            elif not upcoming.empty and "week" in upcoming.columns:
                first = upcoming.sort_values("kickoff").iloc[0]
                upcoming = upcoming[
                    (upcoming["season"] == first["season"]) & (upcoming["week"] == first["week"])
                ]

        if upcoming.empty:
            raise MlevError(
                f"No unplayed {config.label} {level} fixtures match that filter. "
                "Try a different week, or re-run the data download to pick up a "
                "newly published schedule."
            )

        job.log(f"training on all completed data, then scoring {len(upcoming)} fixtures")
        scored = pipeline.train_and_score(level, upcoming=upcoming)
        view = pipeline.prediction_view(scored, level)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = config.path("predictions", f"{level}_{stamp}.csv")
        out.parent.mkdir(parents=True, exist_ok=True)
        view.to_csv(out, index=False)
        job.log(f"wrote {out.name}")
        return {"file": out.name, "table": frame_to_json(view, limit=300)}

    return _submit("score", sport, f"Predict upcoming {config.label} {level}s", run)


def _epl_upcoming(pipeline, features: pd.DataFrame, body: dict, job) -> pd.DataFrame:
    """Attach point-in-time features to EPL fixtures that have no result yet."""
    from core.naming import normalize_series, unmapped_names
    from sports.epl.teams import CLUB_ALIAS_MAP

    manual = body.get("fixtures")
    if manual:
        raw = pd.DataFrame(manual)
        job.log(f"using {len(raw)} manually entered fixtures")
    else:
        raw = pipeline.upcoming_fixtures()

    for column in ("HomeTeam", "AwayTeam", "Date"):
        if column not in raw.columns:
            raise MlevError(f"fixture list is missing a '{column}' column")

    missing = unmapped_names(pd.concat([raw["HomeTeam"], raw["AwayTeam"]]), CLUB_ALIAS_MAP)
    if missing:
        raise MlevError(
            f"These club names are not recognised: {', '.join(missing)}. "
            "Check the spelling, or add them to sports/epl/teams.py."
        )

    kickoff = pd.to_datetime(raw["Date"], dayfirst=True, errors="coerce")
    if kickoff.isna().any():
        raise MlevError("Some fixture dates could not be read. Use DD/MM/YYYY.")

    season = int(kickoff.min().year - 1 if kickoff.min().month <= 6 else kickoff.min().year)
    fixtures = pd.DataFrame(
        {
            "home_team": normalize_series(raw["HomeTeam"], CLUB_ALIAS_MAP),
            "away_team": normalize_series(raw["AwayTeam"], CLUB_ALIAS_MAP),
            "kickoff": kickoff,
            "season": season,
            "match_id": season.__str__() + "_" + kickoff.dt.strftime("%Y%m%d") + "_upcoming",
        }
    )
    for col in pipeline.outcome_columns("game"):
        fixtures[col] = float("nan")

    played = features.dropna(subset=["home_goals"])
    combined = pd.concat([played, fixtures], ignore_index=True)
    return combined.tail(len(fixtures)).copy()


# --- reading saved artefacts ------------------------------------------------


@app.get("/api/backtest/<sport>/<level>")
def read_backtest(sport: str, level: str):
    config = get_sport(sport)
    out = {}
    for part in ("overall", "by_season", "calibration"):
        path = config.path("models", f"backtest_{level}_{part}.csv")
        out[part] = frame_to_json(pd.read_csv(path)) if path.exists() else {"columns": [], "rows": []}
    return jsonify(out)


@app.get("/api/predictions/<sport>/<name>")
def read_predictions(sport: str, name: str):
    config = get_sport(sport)
    # Never let a crafted name walk out of the predictions directory.
    path = (config.path("predictions") / name).resolve()
    if not path.is_relative_to(config.path("predictions").resolve()) or not path.exists():
        return jsonify({"error": "no such prediction file"}), 404
    return jsonify(frame_to_json(pd.read_csv(path), limit=400))


@app.get("/api/fixtures/epl")
def epl_fixtures():
    """The live football-data fixture feed, for pre-filling the EPL form."""
    try:
        from sports.epl.ingest import fetch_fixtures

        fixtures = fetch_fixtures()
    except Exception as exc:
        return jsonify({"fixtures": [], "note": str(exc)})
    rows = [
        {"Date": r["Date"], "HomeTeam": r["HomeTeam"], "AwayTeam": r["AwayTeam"]}
        for _, r in fixtures.iterrows()
    ]
    return jsonify({"fixtures": rows, "note": "" if rows else "The feed lists no Premier League matches right now — it only covers the next few days."})


def serve(host: str = "127.0.0.1", port: int = 8733, open_browser: bool = True) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    url = f"http://{host}:{port}"
    if open_browser:
        import threading

        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"\n  mlev is running at {url}\n  Press Ctrl+C to stop.\n")
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    serve()
