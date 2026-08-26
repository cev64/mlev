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
from core.odds import american_to_decimal, compare
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
        }
    )
    # The teams have to be in the id. Keying on season and date alone gave every
    # match in a matchday the same id, and anything downstream that groups by it
    # — the Edge tab's saved prices, for one — silently merged them.
    fixtures["match_id"] = (
        fixtures["season"].astype(str)
        + "_"
        + fixtures["kickoff"].dt.strftime("%Y%m%d")
        + "_"
        + fixtures["home_team"].str.replace(" ", "-", regex=False)
        + "_"
        + fixtures["away_team"].str.replace(" ", "-", regex=False)
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


@app.get("/api/markets/<sport>/<name>")
def read_markets(sport: str, name: str):
    """Every bettable side of every market in a saved prediction file.

    This is the phone view's data source: one entry per fixture, each carrying
    both sides of the moneyline, every spread and every total, with the fair
    price the model implies.
    """
    config = get_sport(sport)
    path = (config.path("predictions") / name).resolve()
    if not path.is_relative_to(config.path("predictions").resolve()) or not path.exists():
        return jsonify({"error": "no such prediction file"}), 404
    if not name.startswith("game"):
        return jsonify({"error": "market view is only available for game-level predictions"}), 400

    pipeline = get_pipeline(sport)
    frame = pd.read_csv(path)
    fixtures = [f.to_dict() for f in pipeline.fixture_markets(frame)]
    return jsonify({"file": name, "sport": sport, "fixtures": fixtures})


@app.post("/api/ev")
def expected_value_endpoint():
    """Compare one or many posted prices against the model's probabilities.

    Body: {"bets": [{"probability": .., "push_probability": .., "odds": -110,
                     "format": "american"|"decimal", "opposing_odds": ..}]}

    Nothing is fetched from a book here — you bring the price. The response adds
    the de-vigged comparison whenever the other side of the market is supplied,
    because that is the only version that strips the house margin out of what
    you are measuring against.
    """
    body = request.get_json(force=True, silent=True) or {}
    bets = body.get("bets") or []
    if not isinstance(bets, list) or not bets:
        return jsonify({"error": "send a non-empty 'bets' list"}), 400
    if len(bets) > 500:
        return jsonify({"error": "at most 500 bets per request"}), 400

    results = []
    for index, bet in enumerate(bets):
        try:
            odds = bet.get("odds")
            if odds in (None, ""):
                results.append({"index": index, "error": "no price given"})
                continue
            comparison = compare(
                float(bet["probability"]),
                float(odds),
                american=str(bet.get("format", "american")).lower() != "decimal",
                opposing_odds=(
                    float(bet["opposing_odds"])
                    if bet.get("opposing_odds") not in (None, "")
                    else None
                ),
                push_probability=float(bet.get("push_probability") or 0.0),
            )
            results.append({"index": index, **comparison.summary()})
        except (ValueError, TypeError, KeyError) as exc:
            results.append({"index": index, "error": str(exc)})
    return jsonify({"results": results})


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


def local_ip() -> str | None:
    """This machine's address on the LAN, for connecting a phone.

    Opening a UDP socket to a public address does not send anything; it just
    makes the OS pick the interface it would route through, which is the one
    the phone can reach.
    """
    import socket

    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()


def qr_code(text: str) -> str | None:
    """A scannable QR for the terminal, so connecting a phone is not typing an IP.

    Optional: if `qrcode` is not installed the printed URL is still there, so a
    missing package costs a convenience and nothing else.
    """
    try:
        import io

        import qrcode

        code = qrcode.QRCode(border=1)
        code.add_data(text)
        code.make(fit=True)
        buffer = io.StringIO()
        code.print_ascii(out=buffer, invert=True)
        return buffer.getvalue()
    except Exception:
        return None


def serve(
    host: str = "127.0.0.1",
    port: int = 8733,
    open_browser: bool = True,
    lan: bool = False,
) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    # Binding 0.0.0.0 exposes the app to everything on the network, so it is
    # opt-in rather than the default.
    bind = "0.0.0.0" if lan else host
    url = f"http://127.0.0.1:{port}"

    if open_browser:
        import threading

        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    print(f"\n  mlev is running at {url}")
    if lan:
        address = local_ip()
        if address:
            phone_url = f"http://{address}:{port}"
            print(f"\n  On your phone, on the same Wi-Fi, open:\n      {phone_url}\n")
            code = qr_code(phone_url)
            if code:
                print(code)
            print(
                "  Anyone on this network can reach it while it is running.\n"
                "  Close this window when you are done."
            )
        else:
            print("\n  Could not work out this machine's network address.")
            print("  Find it in System Settings > Network and use http://<that>:%s" % port)
    print("\n  Press Ctrl+C to stop.\n")
    app.run(host=bind, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    serve()
