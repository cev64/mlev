"""Premier League raw data backfill.

**Primary source: football-data.co.uk.** One CSV per season, no scraping, no
rate limit, uniform schema back to the 1990s, and it carries more than the
scoreline: shots, shots on target, corners, fouls and cards for both sides.
That makes it the results-and-context backbone.

**Underlying performance: Understat**, via the same JSON endpoint the site's
own front end calls (`getLeagueData/EPL/<season>`), one request per season.
It supplies per-match team xG, which is what the spec asks for and what
football-data does not have.

The spec offers FBref or StatsBomb as alternatives to Understat. Understat is
the pick here for three reasons, and they are worth writing down because the
answer could change:

1. One request per season for every match's xG, versus one request per match
   for FBref.
2. FBref (sports-reference) returns HTTP 403 to non-browser clients and asks
   scrapers to throttle to one request every few seconds; a 12-season backfill
   there is both slow and impolite.
3. StatsBomb's free tier does not cover the Premier League broadly enough for a
   multi-season backtest.

Player-level data (goals, assists, shots, cards per match) comes from
Understat's per-match roster endpoint. That *is* one request per match, so it
is opt-in via `--with-players` and cached per season.

Everything raises `DataSourceError` on failure. Nothing degrades to partial data.
"""

from __future__ import annotations

import gzip
import json
import logging
import time
import urllib.error
import urllib.request
from io import StringIO
from pathlib import Path

import pandas as pd

from core.config import SportConfig
from core.errors import DataSourceError
from core.io import write_table

log = logging.getLogger(__name__)

FOOTBALL_DATA_URL = "https://www.football-data.co.uk/mmz4281/{code}/E0.csv"
FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"
UNDERSTAT_LEAGUE_URL = "https://understat.com/getLeagueData/EPL/{season}"
UNDERSTAT_MATCH_URL = "https://understat.com/getMatchData/{match_id}"

# Understat is a small free site. Be a good citizen on the per-match endpoint.
UNDERSTAT_DELAY_SECONDS = 0.4
_HEADERS = {
    "User-Agent": "mlev-model/0.1 (personal research; contact via repo)",
    "X-Requested-With": "XMLHttpRequest",
}


def season_code(season: int) -> str:
    """2024 (the 2024/25 season) -> '2425', football-data's directory code."""
    return f"{season % 100:02d}{(season + 1) % 100:02d}"


def _get(url: str, *, timeout: int = 60) -> bytes:
    request = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        raise DataSourceError(
            f"could not fetch {url}: {type(exc).__name__}: {exc}. "
            "Not falling back to partial or cached-elsewhere data."
        ) from exc
    if not payload:
        raise DataSourceError(f"{url} returned an empty body.")
    return payload


def _get_json(url: str) -> dict:
    """Understat gzips its JSON responses regardless of Accept-Encoding."""
    payload = _get(url)
    if payload[:2] == b"\x1f\x8b":
        payload = gzip.decompress(payload)
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataSourceError(
            f"{url} did not return usable JSON ({type(exc).__name__}: {exc}). "
            "Understat may have changed its endpoint; the parser needs updating "
            "rather than the pipeline continuing without xG."
        ) from exc


# --- football-data.co.uk ----------------------------------------------------


def fetch_results(seasons: list[int]) -> pd.DataFrame:
    """Match results and match context, one season CSV at a time."""
    frames = []
    for season in seasons:
        url = FOOTBALL_DATA_URL.format(code=season_code(season))
        text = _get(url).decode("utf-8-sig", errors="replace")
        df = pd.read_csv(StringIO(text))
        df = df.dropna(subset=["HomeTeam", "AwayTeam"])
        if df.empty:
            raise DataSourceError(
                f"football-data returned no matches for {season}/{season + 1} ({url})."
            )
        df["season"] = season
        frames.append(df)
        log.info("season %s/%s: %s matches", season, (season + 1) % 100, len(df))
    return pd.concat(frames, ignore_index=True)


def fetch_fixtures() -> pd.DataFrame:
    """Upcoming Premier League fixtures — the matchday scoring job's input.

    football-data publishes a rolling near-term fixture list. Between
    matchweeks it can legitimately hold no Premier League rows, which is a
    fact about the calendar and is reported as such rather than as an error.
    """
    text = _get(FIXTURES_URL).decode("utf-8-sig", errors="replace")
    fixtures = pd.read_csv(StringIO(text))
    if "Div" not in fixtures.columns:
        raise DataSourceError(
            f"{FIXTURES_URL} has no 'Div' column; the feed format has changed."
        )
    epl = fixtures[fixtures["Div"] == "E0"].dropna(subset=["HomeTeam", "AwayTeam"])
    log.info("upcoming EPL fixtures in feed: %s", len(epl))
    return epl.reset_index(drop=True)


# --- Understat --------------------------------------------------------------


def fetch_team_xg(seasons: list[int]) -> pd.DataFrame:
    """Per-match team xG for both sides, one request per season."""
    rows = []
    for season in seasons:
        data = _get_json(UNDERSTAT_LEAGUE_URL.format(season=season))
        matches = data.get("dates") or data.get("datesData")
        if not matches:
            raise DataSourceError(
                f"Understat returned no match list for {season}; expected a 'dates' key, "
                f"got {sorted(data)}."
            )
        for match in matches:
            if not match.get("isResult"):
                continue  # not played yet; there is no xG to record
            rows.append(
                {
                    "understat_id": match["id"],
                    "season": season,
                    "datetime": match["datetime"],
                    "home_team_raw": match["h"]["title"],
                    "away_team_raw": match["a"]["title"],
                    "home_goals_us": _num(match["goals"]["h"]),
                    "away_goals_us": _num(match["goals"]["a"]),
                    "home_xg": _num(match["xG"]["h"]),
                    "away_xg": _num(match["xG"]["a"]),
                }
            )
        log.info("season %s: %s Understat matches with xG", season, len(rows))
    if not rows:
        raise DataSourceError("Understat returned no completed matches for any season.")
    return pd.DataFrame(rows)


def fetch_player_matches(match_ids: list[str]) -> pd.DataFrame:
    """Per-player per-match lines, for the EPL prop models.

    One request per match, so this is the expensive path. Callers pass only the
    match ids they still need; `backfill` caches per season so a re-run costs
    nothing.
    """
    rows = []
    for i, match_id in enumerate(match_ids, start=1):
        data = _get_json(UNDERSTAT_MATCH_URL.format(match_id=match_id))
        rosters = data.get("rosters")
        if not rosters:
            raise DataSourceError(f"Understat match {match_id} returned no rosters.")
        for side, players in rosters.items():
            for entry in players.values():
                rows.append(
                    {
                        "understat_id": str(match_id),
                        "player_id": entry["player_id"],
                        "player_raw": entry["player"],
                        "team_id": entry["team_id"],
                        "side": "home" if side == "h" else "away",
                        "position": entry.get("position"),
                        "minutes": _num(entry.get("time")),
                        "goals": _num(entry.get("goals")),
                        "assists": _num(entry.get("assists")),
                        "shots": _num(entry.get("shots")),
                        "key_passes": _num(entry.get("key_passes")),
                        "xg": _num(entry.get("xG")),
                        "xa": _num(entry.get("xA")),
                        "yellow_card": _num(entry.get("yellow_card")),
                        "red_card": _num(entry.get("red_card")),
                    }
                )
        if i % 50 == 0:
            log.info("fetched %s/%s match rosters", i, len(match_ids))
        time.sleep(UNDERSTAT_DELAY_SECONDS)
    if not rows:
        raise DataSourceError("no player rows returned for the requested matches.")
    return pd.DataFrame(rows)


def _num(value) -> float:
    """Understat sends every number as a string; missing stays missing."""
    if value is None or value == "":
        return float("nan")
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


# --- orchestration ----------------------------------------------------------


def backfill(
    config: SportConfig,
    seasons: list[int],
    *,
    force: bool = False,
    with_players: bool = False,
    player_seasons: list[int] | None = None,
) -> dict[str, Path]:
    """Pull every raw EPL source for `seasons` into data/epl/raw/."""
    # The in-progress season is included: football-data publishes it
    # incrementally, and its played matches are real, usable history.
    all_seasons = sorted(
        set(seasons) | ({config.upcoming_season} if config.upcoming_season else set())
    )

    written: dict[str, Path] = {}
    for name, job in (
        ("results", lambda: fetch_results(all_seasons)),
        ("team_xg", lambda: fetch_team_xg(all_seasons)),
    ):
        path = config.path("raw", f"{name}.parquet")
        if path.exists() and not force:
            log.info("raw/%s.parquet exists, skipping (use --force to refetch)", name)
            written[name] = path
            continue
        written[name] = write_table(job(), path)

    if with_players:
        written["player_matches"] = _backfill_players(
            config, player_seasons or all_seasons, force=force
        )
    return written


def _backfill_players(config: SportConfig, seasons: list[int], *, force: bool) -> Path:
    """Fetch per-match player lines season by season, caching each one."""
    path = config.path("raw", "player_matches.parquet")
    xg = pd.read_parquet(config.path("raw", "team_xg.parquet"))

    existing = pd.DataFrame()
    if path.exists() and not force:
        existing = pd.read_parquet(path)

    wanted = xg[xg["season"].isin(seasons)]["understat_id"].astype(str).unique().tolist()
    have = set(existing["understat_id"].astype(str)) if not existing.empty else set()
    todo = [m for m in wanted if m not in have]

    if not todo:
        log.info("player match lines already cached for seasons %s", seasons)
        return path

    log.info(
        "fetching %s match rosters from Understat (~%.0f min at %.1fs each)",
        len(todo), len(todo) * UNDERSTAT_DELAY_SECONDS / 60, UNDERSTAT_DELAY_SECONDS,
    )
    fresh = fetch_player_matches(todo)
    combined = pd.concat([existing, fresh], ignore_index=True) if not existing.empty else fresh
    return write_table(combined.drop_duplicates(["understat_id", "player_id"]), path)
